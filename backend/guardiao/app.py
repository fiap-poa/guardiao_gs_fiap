"""Servidor Flask do Guardião (só em 127.0.0.1).

Por ora expõe só o estado (conexão e cadastro da responsável, ainda fixos em falso)
e serve a página estática de `frontend/`. Filtro, casos e tela completa vêm depois.
"""

from flask import Flask, jsonify, send_from_directory

from guardiao.config import FRONTEND_DIR

HOST = "127.0.0.1"
PORTA = 5000


def estado_atual() -> dict:
    return {"conectado": False, "responsavel_cadastrada": False}


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


def main() -> None:
    criar_app().run(host=HOST, port=PORTA, debug=False)


if __name__ == "__main__":
    main()
