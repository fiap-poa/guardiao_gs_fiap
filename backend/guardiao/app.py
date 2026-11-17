"""Servidor Flask do Guardião (só em 127.0.0.1).

Por ora expõe só o estado (conexão da conta e cadastro da responsável), lido do Guardião
registrado por `definir_guardiao`, e serve a página estática de `frontend/`. Sem Guardião
registrado, tudo é falso. Casos e tela completa vêm depois.
No Colab, `iniciar_em_segundo_plano` sobe o servidor numa thread e o notebook o mostra
por `serve_kernel_port_as_iframe`; por isso o frontend usa caminhos relativos.
"""

import threading

from flask import Flask, jsonify, send_from_directory
from werkzeug.serving import BaseWSGIServer, make_server

from guardiao.config import FRONTEND_DIR

HOST = "127.0.0.1"
PORTA = 5000


_guardiao = None  # o `recepcao.Guardiao` cujo estado a tela mostra


def definir_guardiao(guardiao) -> None:
    """Registra o Guardião que `api/estado` lê (`None` desfaz o registro)."""
    global _guardiao
    _guardiao = guardiao


def estado_atual() -> dict:
    guardiao = _guardiao
    if guardiao is None:
        return {"conectado": False, "responsavel_cadastrada": False}
    estado = guardiao.estado()
    return {
        "conectado": bool(estado["conectado"]),
        "responsavel_cadastrada": bool(estado["responsavel_cadastrada"]),
    }


def criar_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/api/estado")
    def api_estado():
        return jsonify(estado_atual())

    @app.get("/")
    def pagina():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:arquivo>")
    def estaticos(arquivo: str):
        return send_from_directory(FRONTEND_DIR, arquivo)

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
            servidor = make_server(host, porta, criar_app(), threaded=True)
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
    criar_app().run(host=HOST, port=PORTA, debug=False)


if __name__ == "__main__":
    main()
