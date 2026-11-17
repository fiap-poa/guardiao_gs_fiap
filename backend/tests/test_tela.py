"""Tela do familiar (história 7): endpoints da configuração, dos casos e do golpista, sem rede.

Canal simulado (com e sem bot), dublê do bot, dublê do Gemini e um canal real falso com
`login_qr`, para a matriz de I/O da história.
"""

import json
import threading
from datetime import timedelta

import pytest

import guardiao.app as app_mod
from guardiao.app import criar_app, definir_guardiao
from guardiao.cadastro import JaCadastrada
from guardiao.canal.base import ConversaAntiga, InicioBot
from guardiao.canal.cenarios import CENARIOS, obter_cenario
from guardiao.canal.simulado import CanalSimulado
from guardiao.canal.telegram import SemSessao
from guardiao.conexao import COMANDO_LOGIN, LoginConta, qr_svg
from guardiao.recepcao import Guardiao, RelogioAjustavel
from test_casos import BOT, RESPONSAVEL, DubleBot, Montagem
from test_simulado import sem_rede  # noqa: F401 (fixture)

CAMPOS_CASO = {"criado_em", "quem", "trecho", "estado", "avisado_em"}


@pytest.fixture
def cliente():
    yield criar_app().test_client()
    definir_guardiao(None)


def _json(cliente, caminho):
    resposta = cliente.get(caminho)
    assert resposta.status_code == 200, caminho
    return resposta.get_json()


def _codigo(link):
    return link.split("?start=")[1]


# --------------------------------------------------------------------------- QR


def test_qr_svg_sem_pil_e_sem_script():
    svg = qr_svg("https://t.me/guardiao_teste_bot?start=abc")
    assert svg.startswith("<svg") and "</svg>" in svg and "<path" in svg
    assert "<script" not in svg and "href" not in svg and "abc" not in svg  # o texto vira desenho
    assert qr_svg("x") != qr_svg("y")


# --------------------------------------------------------------------------- sem Guardião


def test_sem_guardiao_tudo_falso_e_vazio(cliente):
    assert _json(cliente, "/api/estado") == {
        "rodando": False,
        "modo": None,
        "conectado": False,
        "idosa_habilitada": False,
        "tem_bot": False,
        "responsavel_cadastrada": False,
    }
    assert _json(cliente, "/api/casos") == {"casos": []}
    assert _json(cliente, "/api/cadastro") == {"estado": "sem_guardiao", "cadastrada": False, "link": None, "qr_svg": None}
    assert _json(cliente, "/api/conexao") == {"estado": "sem_guardiao", "qr_svg": None, "motivo": None}
    assert cliente.get("/api/demo/cenarios").status_code == 404
    assert cliente.post("/api/demo/injetar", json={"cenario": "golpe_classico"}).status_code == 404
    assert cliente.get("/api/nao-existe").status_code == 404


def test_pagina_avisa_guardiao_parado_e_backend_fora_do_ar(cliente):
    pagina = cliente.get("/").data.decode("utf-8")
    assert "Guardião não está rodando" in pagina
    assert "Não consegui falar com o backend do Guardião" in pagina
    assert "Abrir o bot" in pagina and "Celular do golpista" in pagina


# --------------------------------------------------------------------------- demonstração


def test_demo_sem_bot_conexao_simulada_e_cadastro_sem_bot(cliente, sem_rede):
    guardiao = Guardiao(CanalSimulado(saida=None), varredura_casos_s=None)
    guardiao.conectar()
    definir_guardiao(guardiao)
    estado = _json(cliente, "/api/estado")
    assert estado["rodando"] and estado["modo"] == "demonstracao" and estado["conectado"]
    assert estado["tem_bot"] is False
    assert _json(cliente, "/api/conexao") == {"estado": "simulada", "qr_svg": None, "motivo": None}
    assert _json(cliente, "/api/cadastro") == {"estado": "sem_bot", "cadastrada": False, "link": None, "qr_svg": None}
    guardiao.fechar()


def test_demo_registrado_sem_conectar_fica_desconectada(cliente, sem_rede):
    guardiao = Guardiao(CanalSimulado(saida=None), varredura_casos_s=None)
    definir_guardiao(guardiao)
    assert _json(cliente, "/api/conexao") == {"estado": "desconectada", "qr_svg": None, "motivo": None}
    guardiao.conectar()
    assert _json(cliente, "/api/conexao")["estado"] == "simulada"
    guardiao.fechar()


def test_demo_bot_fora_do_ar_cadastro_erro_e_depois_aguardando(cliente, sem_rede):
    class BotInstavel(DubleBot):
        fora = True

        def info_bot(self):
            if self.fora:
                raise ConnectionError("getMe falhou")
            return super().info_bot()

    bot = BotInstavel()
    guardiao = Guardiao(CanalSimulado(saida=bot), varredura_casos_s=None)
    guardiao.conectar()
    definir_guardiao(guardiao)
    assert _json(cliente, "/api/cadastro") == {"estado": "erro", "cadastrada": False, "link": None, "qr_svg": None}
    bot.fora = False
    resposta = _json(cliente, "/api/cadastro")
    assert resposta["estado"] == "aguardando" and resposta["qr_svg"].startswith("<svg")
    assert resposta["link"].startswith(f"https://t.me/{BOT['username']}?start=")
    guardiao.fechar()


@pytest.fixture
def demo(tmp_path, sem_rede, cliente):
    montagem = Montagem(tmp_path, cadastrar=False)
    definir_guardiao(montagem.guardiao)
    yield montagem
    montagem.guardiao.fechar()


def test_demo_com_bot_link_e_qr_com_o_mesmo_codigo(cliente, demo):
    primeiro = _json(cliente, "/api/cadastro")
    assert primeiro["estado"] == "aguardando" and primeiro["cadastrada"] is False
    assert primeiro["link"].startswith(f"https://t.me/{BOT['username']}?start=")
    assert len(_codigo(primeiro["link"])) == 22
    assert primeiro["qr_svg"].startswith("<svg")
    segundo = _json(cliente, "/api/cadastro")
    assert segundo["link"] == primeiro["link"] and segundo["qr_svg"] == primeiro["qr_svg"]
    assert demo.guardiao.estado()["codigos_validos"] == 1


def test_codigo_perto_de_vencer_vira_codigo_novo(cliente, demo):
    primeiro = _json(cliente, "/api/cadastro")["link"]
    demo.relogio.adiantar(minutes=24)  # faltam 6 min: ainda o mesmo
    assert _json(cliente, "/api/cadastro")["link"] == primeiro
    demo.relogio.adiantar(minutes=2)  # +26 min: faltam 4 min, código novo
    novo = _json(cliente, "/api/cadastro")["link"]
    assert novo != primeiro
    assert _json(cliente, "/api/cadastro")["link"] == novo
    # os dois valem até vencer; o antigo ainda cadastra
    assert demo.guardiao.estado()["codigos_validos"] == 2
    demo.bot.handler(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=_codigo(primeiro), nome="Ana"))
    assert demo.guardiao.cadastro.cadastrada


def test_codigo_vigente_nao_muda_o_uso_unico(demo):
    cadastro = demo.guardiao.cadastro
    codigo = cadastro.codigo_vigente()
    assert cadastro.codigo_vigente() == codigo
    assert cadastro.tratar_inicio(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=codigo, nome="Ana")).cadastrou
    assert cadastro.tratar_inicio(InicioBot(5, 5, parametro=codigo)).motivo == "codigo_usado"
    with pytest.raises(JaCadastrada):
        cadastro.codigo_vigente()


def test_responsavel_cadastrada_sem_link_nem_qr(cliente, demo):
    link = _json(cliente, "/api/cadastro")["link"]
    demo.bot.handler(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=_codigo(link), nome="Ana"))
    assert _json(cliente, "/api/cadastro") == {"estado": "cadastrada", "cadastrada": True, "link": None, "qr_svg": None}
    estado = _json(cliente, "/api/estado")
    assert estado["conectado"] and estado["responsavel_cadastrada"]


def test_casos_so_com_os_campos_da_tela(cliente, demo):
    demo.cadastrar()
    assert _json(cliente, "/api/casos") == {"casos": []}
    demo.canal.injetar("golpe_classico")
    demo.bot.tocar("golpe")
    resposta = cliente.get("/api/casos")
    [caso] = resposta.get_json()["casos"]
    assert set(caso) == CAMPOS_CASO
    assert caso["quem"] == "Pedro" and caso["estado"] == "golpe"
    assert caso["trecho"] and caso["criado_em"] and caso["avisado_em"]
    bruto = resposta.data.decode("utf-8")
    caso_id = demo.caso("golpe_classico").id
    for proibido in (caso_id, "sim:", "5500", "98765", "Pedro Neto", "resposta", '"id"', str(RESPONSAVEL)):
        assert proibido not in bruto, proibido
    # o trecho vem do caso, não da conversa inteira
    assert all(texto not in bruto for texto in obter_cenario("golpe_classico").mensagens if texto not in caso["trecho"])


def test_casos_do_mais_recente_e_com_estados_da_tela(cliente, demo):
    demo.cadastrar()
    demo.canal.injetar("golpe_classico")
    demo.relogio.adiantar(minutes=1)
    demo.canal.injetar("parente_trocou_numero")
    casos = _json(cliente, "/api/casos")["casos"]
    assert [c["quem"] for c in casos] == ["Lucas", "Pedro"]
    assert [c["estado"] for c in casos] == ["aguardando", "aguardando"] and casos[0]["avisado_em"] is None


# --------------------------------------------------------------------------- golpista (demonstração)


def test_golpista_lista_os_cinco_cenarios(cliente, demo):
    cenarios = _json(cliente, "/api/demo/cenarios")["cenarios"]
    assert [c["id"] for c in cenarios] == [c.id for c in CENARIOS]
    assert all(set(c) == {"id", "rotulo", "descricao"} and c["rotulo"] for c in cenarios)


@pytest.mark.parametrize(
    ("cenario_id", "mensagens", "analisadas", "descartadas"),
    [
        ("golpe_classico", 2, 2, 0),
        ("parente_trocou_numero", 2, 2, 0),
        ("contato_antigo_pede_dinheiro", 1, 0, 1),
        ("mensagem_em_grupo", 1, 0, 1),
        ("contato_novo_sem_dinheiro", 2, 2, 0),
    ],
)
def test_golpista_injeta_e_conta(cliente, demo, cenario_id, mensagens, analisadas, descartadas):
    resposta = cliente.post("/api/demo/injetar", json={"cenario": cenario_id})
    assert resposta.status_code == 200
    assert resposta.get_json() == {
        "cenario": cenario_id,
        "mensagens": mensagens,
        "analisadas": analisadas,
        "descartadas": descartadas,
    }


def test_golpista_com_responsavel_vira_caso(cliente, demo):
    demo.cadastrar()
    assert cliente.post("/api/demo/injetar", json={"cenario": "golpe_classico"}).status_code == 200
    [alerta] = demo.bot.alertas
    assert alerta.nome_alegado == "Pedro"
    assert [c["estado"] for c in _json(cliente, "/api/casos")["casos"]] == ["aguardando"]


def test_golpista_pedido_invalido_400(cliente, demo):
    for corpo in ({"cenario": "nao_existe"}, {"cenario": 3}, {}, [], None):
        assert cliente.post("/api/demo/injetar", json=corpo).status_code == 400, corpo
    # sem Content-Type JSON (formulário de outra página): recusado
    assert cliente.post("/api/demo/injetar", data="cenario=golpe_classico").status_code == 400
    assert cliente.post("/api/demo/injetar", data='{"cenario": "golpe_classico"}', content_type="text/plain").status_code == 400
    assert demo.canal.celular() == []  # nada foi injetado
    assert cliente.get("/api/demo/injetar").status_code == 404  # só POST


def test_golpista_guardiao_desconectado_409(cliente, sem_rede):
    guardiao = Guardiao(CanalSimulado(), varredura_casos_s=None)
    definir_guardiao(guardiao)
    assert cliente.post("/api/demo/injetar", json={"cenario": "golpe_classico"}).status_code == 409
    guardiao.fechar()


# --------------------------------------------------------------------------- modo real (canal falso)


class CanalRealFalso:
    """Canal real falso: sem sessão até o `login_qr` terminar; o teste decide o desfecho."""

    URL_QR = "tg://login?token=token-falso-do-qr"

    def __init__(self, desfecho="lido", segura=True):
        self.desfecho = desfecho  # "lido", "2fa", "vencido" ou "falha"
        self.logins = 0
        self.ativos = 0
        self.max_ativos = 0
        self.liberar = threading.Event()
        if not segura:
            self.liberar.set()
        self.mostrou = threading.Event()
        self.logado = False
        self.fechado = 0
        self.handler = None
        self.starts = 0
        self._trava = threading.Lock()

    def login_qr(self, mostrar_qr, pedir_senha):
        with self._trava:
            self.logins += 1
            self.ativos += 1
            self.max_ativos = max(self.max_ativos, self.ativos)
        try:
            mostrar_qr(self.URL_QR, 1)
            self.mostrou.set()
            assert self.liberar.wait(5)
            if self.desfecho == "2fa":
                return pedir_senha(1)
            if self.desfecho == "vencido":
                raise TimeoutError("QR não foi lido")
            if self.desfecho == "falha":
                raise ConnectionError("rede")
            self.logado = True
            return 4242
        finally:
            with self._trava:
                self.ativos -= 1

    def conectar(self):
        if not self.logado:
            raise SemSessao("sem sessão salva; rode `login`")
        return 4242

    def conversas_existentes(self):
        return [ConversaAntiga(conversa_id=11, tipo="privada")]

    def info_bot(self):
        return dict(BOT)

    def receber_mensagens(self, handler):
        self.handler = handler

    def enviar_start_ao_bot(self):
        self.starts += 1

    def enviar_aviso(self, destinatario, texto):
        return "1"

    def enviar_alerta(self, alerta):
        return "1"

    def listar_contatos(self):
        return []

    def fechar(self):
        self.fechado += 1


def _real(desfecho="lido", segura=True):
    canal = CanalRealFalso(desfecho, segura)
    guardiao = Guardiao(canal, relogio=RelogioAjustavel(), varredura_casos_s=None)
    with pytest.raises(SemSessao):
        guardiao.conectar()
    definir_guardiao(guardiao)
    return canal, guardiao


def _login():
    return app_mod._login


def test_real_sem_sessao_primeiro_pedido_mostra_o_qr_e_conecta_ao_ler(cliente, sem_rede):
    canal, guardiao = _real()
    estado = _json(cliente, "/api/estado")
    assert estado["modo"] == "real" and not estado["conectado"]
    assert canal.logins == 0  # o login só começa quando a tela pede a conexão
    primeiro = _json(cliente, "/api/conexao")
    assert primeiro["estado"] == "aguardando_leitura" and primeiro["motivo"] is None
    assert primeiro["qr_svg"] == qr_svg(CanalRealFalso.URL_QR)
    assert CanalRealFalso.URL_QR not in json.dumps(primeiro) and "token-falso" not in json.dumps(primeiro)
    # pedidos ao mesmo tempo: uma thread de login só
    respostas = []
    pedidos = [threading.Thread(target=lambda: respostas.append(_json(cliente, "/api/conexao"))) for _ in range(5)]
    for pedido in pedidos:
        pedido.start()
    for pedido in pedidos:
        pedido.join(5)
    assert [r["estado"] for r in respostas] == ["aguardando_leitura"] * 5
    assert canal.logins == 1 and canal.max_ativos == 1
    # o QR foi lido: o Guardião conecta sozinho
    canal.liberar.set()
    assert _login().aguardar(5)
    assert guardiao.estado()["conectado"] and canal.handler is not None and canal.starts == 1
    assert _json(cliente, "/api/conexao") == {"estado": "conectada", "qr_svg": None, "motivo": None}
    assert _json(cliente, "/api/estado")["conectado"] is True
    assert canal.logins == 1
    # e o cadastro da responsável já tem o link do bot
    assert _json(cliente, "/api/cadastro")["link"].startswith(f"https://t.me/{BOT['username']}?start=")


def test_real_registrar_o_mesmo_guardiao_mantem_o_login(cliente, sem_rede):
    canal, guardiao = _real()
    _json(cliente, "/api/conexao")
    login = _login()
    definir_guardiao(guardiao)  # a seção 9 registra de novo o Guardião da seção 5
    assert _login() is login
    assert _json(cliente, "/api/conexao")["estado"] == "aguardando_leitura" and canal.logins == 1
    canal.liberar.set()
    assert login.aguardar(5)


def test_real_2fa_mostra_erro_e_nao_repete_sozinho(cliente, sem_rede):
    canal, guardiao = _real("2fa", segura=False)
    resposta = _json(cliente, "/api/conexao")
    assert _login().aguardar(5)
    if resposta["estado"] != "erro":  # o primeiro QR chegou antes da senha ser pedida
        resposta = _json(cliente, "/api/conexao")
    assert resposta == {"estado": "erro", "qr_svg": None, "motivo": "senha_2fa", "comando": COMANDO_LOGIN}
    for _ in range(3):
        assert _json(cliente, "/api/conexao")["motivo"] == "senha_2fa"
    assert canal.logins == 1 and not guardiao.estado()["conectado"]
    assert canal.fechado == 1  # a sessão fica livre para o login pelo terminal


def test_real_qr_vencido_mostra_erro_e_o_proximo_pedido_tenta_de_novo(cliente, sem_rede):
    canal, guardiao = _real("vencido")
    assert _json(cliente, "/api/conexao")["estado"] == "aguardando_leitura"
    canal.liberar.set()
    assert _login().aguardar(5)
    assert _json(cliente, "/api/conexao") == {"estado": "erro", "qr_svg": None, "motivo": "qr_vencido"}
    canal.desfecho = "lido"
    canal.liberar.clear()
    novo = _json(cliente, "/api/conexao")  # tenta de novo: QR novo
    assert novo["estado"] == "aguardando_leitura" and novo["qr_svg"]
    assert canal.logins == 2
    canal.liberar.set()
    assert _login().aguardar(5)
    assert _json(cliente, "/api/conexao")["estado"] == "conectada" and guardiao.estado()["conectado"]
    assert canal.fechado == 0


def test_real_falha_no_login_espera_30_s_antes_de_tentar_de_novo(cliente, sem_rede, capsys):
    canal, _ = _real("falha")
    agora = [1000.0]
    _login()._relogio = lambda: agora[0]
    assert _json(cliente, "/api/conexao")["estado"] == "aguardando_leitura"
    canal.liberar.set()
    assert _login().aguardar(5)
    erro = {"estado": "erro", "qr_svg": None, "motivo": "falha"}
    for passo in (0, 3, 3, 23):  # até 29 s depois da falha: continua o erro, sem novo login
        agora[0] += passo
        assert _json(cliente, "/api/conexao") == erro
    assert canal.logins == 1
    canal.liberar.clear()  # o novo login fica no QR até o teste soltar
    agora[0] += 1  # 30 s: tenta de novo
    assert _json(cliente, "/api/conexao")["estado"] == "aguardando_leitura"
    assert canal.logins == 2
    canal.liberar.set()
    assert _login().aguardar(5)
    assert _json(cliente, "/api/conexao") == erro and canal.logins == 2  # e a espera recomeça
    erros = capsys.readouterr().err
    assert "ConnectionError" in erros and "token-falso" not in erros and "tg://" not in erros


def test_real_qr_lido_some_da_tela_durante_o_pareamento(cliente, sem_rede):
    pareando, liberar_pareamento = threading.Event(), threading.Event()

    class PareamentoLento(CanalRealFalso):
        def conversas_existentes(self):
            pareando.set()
            assert liberar_pareamento.wait(5)
            return super().conversas_existentes()

    canal = PareamentoLento()
    guardiao = Guardiao(canal, varredura_casos_s=None)
    definir_guardiao(guardiao)
    assert _json(cliente, "/api/conexao")["estado"] == "aguardando_leitura"
    canal.liberar.set()
    assert pareando.wait(5)
    assert _json(cliente, "/api/conexao") == {"estado": "iniciando", "qr_svg": None, "motivo": None}
    liberar_pareamento.set()
    assert _login().aguardar(5)
    assert _json(cliente, "/api/conexao")["estado"] == "conectada"


def test_real_sem_login_qr_fica_desconectada(cliente, sem_rede):
    class SemLogin(CanalRealFalso):
        login_qr = None

    guardiao = Guardiao(SemLogin(), varredura_casos_s=None)
    definir_guardiao(guardiao)
    assert _json(cliente, "/api/conexao")["estado"] == "desconectada"


def test_real_golpista_404(cliente, sem_rede):
    canal, _ = _real(segura=False)
    assert cliente.get("/api/demo/cenarios").status_code == 404
    assert cliente.post("/api/demo/injetar", json={"cenario": "golpe_classico"}).status_code == 404


def test_login_conta_espera_o_primeiro_qr_por_pouco_tempo(sem_rede):
    canal = CanalRealFalso()

    def lento(mostrar_qr, pedir_senha):
        canal.liberar.wait(5)
        raise TimeoutError

    canal.login_qr = lento
    guardiao = Guardiao(canal, varredura_casos_s=None)
    login = LoginConta(guardiao, espera_primeiro_qr_s=0.05)
    assert login.estado()["estado"] == "iniciando"
    canal.liberar.set()
    assert login.aguardar(5)


# --------------------------------------------------------------------------- servidor


def test_servidor_nao_loga_os_pedidos(capsys):
    import urllib.request

    from guardiao.app import HOST, iniciar_em_segundo_plano, parar_servidor

    servidor = iniciar_em_segundo_plano(HOST, 0)
    try:
        sem_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with sem_proxy.open(f"http://{HOST}:{servidor.port}/api/cadastro", timeout=5) as resposta:
            assert json.load(resposta)["estado"] == "sem_guardiao"
    finally:
        parar_servidor()
    assert "/api/cadastro" not in capsys.readouterr().err


@pytest.mark.parametrize("minutos", [0, 10])
def test_link_cadastro_do_notebook_continua_gerando_codigo_novo(demo, minutos):
    demo.relogio.adiantar(minutes=minutos)
    assert demo.guardiao.link_cadastro() != demo.guardiao.link_cadastro()
    assert demo.guardiao.link_cadastro_vigente() == demo.guardiao.link_cadastro_vigente()


def test_validade_padrao(demo):
    from guardiao.cadastro import MARGEM_CODIGO, VALIDADE_CODIGO

    assert VALIDADE_CODIGO == timedelta(minutes=30) and MARGEM_CODIGO == timedelta(minutes=5)
