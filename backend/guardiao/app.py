"""Servidor Flask do Guardião (só em 127.0.0.1) e endpoints da tela do familiar (CAP-7, CAP-8).

Tudo é lido do Guardião registrado por `definir_guardiao`; sem Guardião, tudo é falso e as
listas vêm vazias. A página estática de `frontend/` lê os endpoints por caminhos relativos
(funciona no iframe de `serve_kernel_port_as_iframe` do Colab):

- `GET api/estado`: se o Guardião está rodando, o modo, a conexão, a pessoa idosa habilitada
  no bot, se há bot e se a responsável está cadastrada;
- `GET api/conexao`: estado da conta da pessoa idosa (`conexao.LoginConta`); no modo real
  sem sessão, o pedido começa o login por QR e devolve o QR em SVG;
- `GET api/cadastro`: o link do bot com o código vigente e o QR dele, enquanto a responsável
  não está cadastrada;
- `GET api/casos`: os casos, do mais recente, só com horário, quem a pessoa diz ser,
  trecho, estado e horário do aviso (nenhum id, telefone, resposta ou conversa);
- `GET api/demo/cenarios` e `POST api/demo/injetar` (`{"cenario": "<id>"}`): a caixa do
  "celular do golpista", só no modo demonstração (no modo real, 404).

A tela não responde casos. Os pedidos não são registrados em log (o caminho nunca leva
código ou link, mas a tela consulta a cada poucos segundos).
No Colab, `iniciar_em_segundo_plano` sobe o servidor numa thread.
"""

import threading

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from guardiao.cadastro import JaCadastrada
from guardiao.canal.cenarios import CENARIOS, obter_cenario
from guardiao.config import FRONTEND_DIR
from guardiao.conexao import LoginConta, qr_svg
from guardiao.recepcao import SemBot

HOST = "127.0.0.1"
PORTA = 5000

# só o que a tela mostra de cada caso
CAMPOS_CASO_TELA: tuple[str, ...] = ("criado_em", "quem", "trecho", "estado", "avisado_em")

ROTULOS_CENARIOS: dict[str, str] = {
    "golpe_classico": "Golpe clássico: diz ser o neto Pedro e pede Pix",
    "parente_trocou_numero": "O filho Lucas trocou de número de verdade e pede transferência",
    "contato_antigo_pede_dinheiro": "O vizinho Carlos, contato antigo, pede dinheiro",
    "mensagem_em_grupo": "Pedido de Pix no grupo da família",
    "contato_novo_sem_dinheiro": "Número novo diz ser a neta Júlia e só manda saudades",
}

_guardiao = None  # o `recepcao.Guardiao` que a tela mostra
_login: LoginConta | None = None
_trava_registro = threading.Lock()
_trava_injecao = threading.Lock()  # uma injeção por vez: as contagens antes/depois não se misturam


def definir_guardiao(guardiao) -> None:
    """Registra o Guardião que a tela mostra (`None` desfaz o registro).

    Registrar de novo o mesmo Guardião (seções 5 e 9 do notebook) mantém o login em andamento.
    """
    global _guardiao, _login
    with _trava_registro:
        if guardiao is _guardiao:
            return
        _guardiao = guardiao
        _login = LoginConta(guardiao) if guardiao is not None else None


def _registrado():
    with _trava_registro:
        return _guardiao, _login


def estado_atual() -> dict:
    guardiao, _ = _registrado()
    if guardiao is None:
        return {
            "rodando": False,
            "modo": None,
            "conectado": False,
            "idosa_habilitada": False,
            "tem_bot": False,
            "responsavel_cadastrada": False,
        }
    estado = guardiao.estado()
    return {
        "rodando": True,
        "modo": guardiao.modo,
        "conectado": bool(estado["conectado"]),
        "idosa_habilitada": bool(estado["idosa_habilitada"]),
        "tem_bot": bool(estado["tem_bot"]),
        "responsavel_cadastrada": bool(estado["responsavel_cadastrada"]),
    }


def conexao_atual() -> dict:
    guardiao, login = _registrado()
    if guardiao is None or login is None:
        return {"estado": "sem_guardiao", "qr_svg": None, "motivo": None}
    return login.estado()


def _cadastro(estado: str, link: str | None = None) -> dict:
    return {
        "estado": estado,
        "cadastrada": estado == "cadastrada",
        "link": link,
        "qr_svg": qr_svg(link) if link else None,
    }


def cadastro_atual() -> dict:
    guardiao, _ = _registrado()
    if guardiao is None:
        return _cadastro("sem_guardiao")
    if guardiao.cadastro.cadastrada:
        return _cadastro("cadastrada")
    try:
        link = guardiao.link_cadastro_vigente()
    except SemBot:
        # canal simulado sem bot (sem TELEGRAM_BOT_TOKEN); com bot, o getMe falhou: tenta no próximo pedido
        sem_bot = getattr(guardiao.canal, "tem_bot", True) is False
        return _cadastro("sem_bot" if sem_bot else "erro")
    except JaCadastrada:  # cadastrou entre a conferência e o link
        return _cadastro("cadastrada")
    except Exception:
        return _cadastro("erro")
    return _cadastro("aguardando", link)


def casos_atuais() -> list[dict]:
    guardiao, _ = _registrado()
    if guardiao is None:
        return []
    return [{campo: caso.get(campo) for campo in CAMPOS_CASO_TELA} for caso in guardiao.casos.listar()]


def _guardiao_demo():
    """O Guardião registrado, se for do modo demonstração; senão, 404."""
    guardiao, _ = _registrado()
    if guardiao is None or guardiao.modo != "demonstracao":
        abort(404)
    return guardiao


def injetar_cenario(guardiao, cenario_id: str) -> dict:
    """Injeta o cenário no canal simulado e conta o que foi analisado e descartado."""
    with _trava_injecao:
        antes = guardiao.filtro.contagens()
        mensagens = guardiao.canal.injetar(cenario_id)
        depois = guardiao.filtro.contagens()
    return {
        "cenario": cenario_id,
        "mensagens": len(mensagens),
        "analisadas": depois["analisadas"] - antes["analisadas"],
        "descartadas": depois["descartadas"] - antes["descartadas"],
    }


class _PedidosSemLog(WSGIRequestHandler):
    """Sem uma linha de log por pedido: a tela consulta a cada poucos segundos."""

    def log_request(self, *args, **kwargs) -> None:
        pass


def _sem_cache(resposta):
    # a página muda entre versões do projeto; o navegador não deve mostrar uma antiga
    resposta.headers["Cache-Control"] = "no-cache"
    return resposta


def criar_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/api/estado")
    def api_estado():
        return jsonify(estado_atual())

    @app.get("/api/conexao")
    def api_conexao():
        return jsonify(conexao_atual())

    @app.get("/api/cadastro")
    def api_cadastro():
        return jsonify(cadastro_atual())

    @app.get("/api/casos")
    def api_casos():
        return jsonify({"casos": casos_atuais()})

    @app.get("/api/demo/cenarios")
    def api_demo_cenarios():
        _guardiao_demo()
        cenarios = [{"id": c.id, "rotulo": ROTULOS_CENARIOS.get(c.id, c.id), "descricao": c.descricao} for c in CENARIOS]
        return jsonify({"cenarios": cenarios})

    @app.post("/api/demo/injetar")
    def api_demo_injetar():
        guardiao = _guardiao_demo()
        # só JSON: outra página não dispara a injeção sem passar pelo preflight do CORS
        dados = request.get_json(silent=True) if request.is_json else None
        cenario_id = dados.get("cenario") if isinstance(dados, dict) else None
        if not isinstance(cenario_id, str):
            return jsonify({"erro": "informe o cenário"}), 400
        try:
            obter_cenario(cenario_id)
        except KeyError:
            return jsonify({"erro": "cenário desconhecido"}), 400
        if not guardiao.conectado:
            return jsonify({"erro": "o Guardião não está conectado"}), 409
        return jsonify(injetar_cenario(guardiao, cenario_id))

    @app.route("/api/<path:_resto>", methods=["GET", "POST"])
    def api_desconhecida(_resto: str):
        abort(404)

    @app.get("/")
    def pagina():
        return _sem_cache(send_from_directory(FRONTEND_DIR, "index.html"))

    @app.get("/<path:arquivo>")
    def estaticos(arquivo: str):
        return _sem_cache(send_from_directory(FRONTEND_DIR, arquivo))

    @app.after_request
    def api_sem_cache(resposta):
        if request.path.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    return app


_servidor: BaseWSGIServer | None = None
_trava = threading.Lock()


def iniciar_em_segundo_plano(host: str = HOST, porta: int = PORTA) -> BaseWSGIServer:
    """Sobe o Flask numa thread daemon e devolve o servidor (`.port`, `.shutdown()`).

    Chamar de novo com o servidor ainda no ar devolve o mesmo (rodar a célula outra vez
    não falha com porta em uso). Porta ocupada por outro processo → `OSError`.
    """
    global _servidor
    with _trava:
        if _servidor is not None:
            return _servidor
        try:
            servidor = make_server(host, porta, criar_app(), threaded=True, request_handler=_PedidosSemLog)
        except SystemExit:  # o werkzeug faz sys.exit(1) quando a porta está ocupada
            raise OSError(f"porta {porta} em uso") from None

        def servir():
            global _servidor
            try:
                servidor.serve_forever()
            finally:
                servidor.server_close()
                with _trava:
                    if _servidor is servidor:
                        _servidor = None

        threading.Thread(target=servir, name="guardiao-flask", daemon=True).start()
        _servidor = servidor
        return servidor


def parar_servidor() -> None:
    """Para o servidor de `iniciar_em_segundo_plano`, se estiver no ar, e libera a porta."""
    global _servidor
    with _trava:
        servidor, _servidor = _servidor, None
    if servidor is not None:
        servidor.shutdown()
        servidor.server_close()


def main() -> None:
    criar_app().run(host=HOST, port=PORTA, debug=False, request_handler=_PedidosSemLog)


if __name__ == "__main__":
    main()
