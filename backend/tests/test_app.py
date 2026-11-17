import json
import re
import socket
import urllib.request

import pytest

from guardiao.app import HOST, criar_app, iniciar_em_segundo_plano, parar_servidor

ESTADO_SEM_GUARDIAO = {
    "rodando": False,
    "modo": None,
    "conectado": False,
    "idosa_habilitada": False,
    "tem_bot": False,
    "responsavel_cadastrada": False,
}


def test_estado_inicial():
    cliente = criar_app().test_client()
    resposta = cliente.get("/api/estado")
    assert resposta.status_code == 200
    assert resposta.get_json() == ESTADO_SEM_GUARDIAO
    assert resposta.headers["Cache-Control"] == "no-store"


def test_serve_frontend():
    cliente = criar_app().test_client()
    pagina = cliente.get("/")
    assert pagina.status_code == 200 and b"/api/estado" not in pagina.data
    assert b"app.js" in pagina.data
    script = cliente.get("/app.js")
    # relativo, para funcionar no iframe do Colab (serve_kernel_port_as_iframe)
    assert script.status_code == 200 and b'"api/estado"' in script.data
    assert b'"/api/estado"' not in script.data
    assert cliente.get("/styles.css").status_code == 200
    assert pagina.headers["Cache-Control"] == "no-cache" and script.headers["Cache-Control"] == "no-cache"
    for sonda in ("/../backend/pytest.ini", "/..%2fbackend/pytest.ini", "/..%2Fbackend%2Fpytest.ini"):
        assert cliente.get(sonda).status_code == 404, sonda


def test_so_localhost():
    assert HOST == "127.0.0.1"


def test_servidor_em_segundo_plano_responde_e_e_idempotente():
    servidor = iniciar_em_segundo_plano(HOST, 0)
    try:
        assert iniciar_em_segundo_plano(HOST, 0) is servidor
        sem_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with sem_proxy.open(f"http://{HOST}:{servidor.port}/api/estado", timeout=5) as resposta:
            assert json.load(resposta) == ESTADO_SEM_GUARDIAO
    finally:
        parar_servidor()
    porta = servidor.port
    with pytest.raises(OSError):  # URLError é OSError: o servidor parou de verdade
        sem_proxy.open(f"http://{HOST}:{porta}/api/estado", timeout=2)
    novo = iniciar_em_segundo_plano(HOST, porta)  # e liberou a porta
    try:
        assert novo is not servidor and novo.port == porta
    finally:
        parar_servidor()
    parar_servidor()  # sem servidor no ar: não faz nada


def test_porta_ocupada_levanta_oserror():
    with socket.socket() as ocupante:
        ocupante.bind((HOST, 0))
        ocupante.listen()
        with pytest.raises(OSError, match="em uso"):
            iniciar_em_segundo_plano(HOST, ocupante.getsockname()[1])
    parar_servidor()


def test_pagina_usa_caminhos_relativos_e_nao_cita_endereco():
    pagina = criar_app().test_client().get("/").data
    assert b'href="styles.css"' in pagina and b'src="app.js"' in pagina
    assert b'"/styles.css"' not in pagina and b'"/app.js"' not in pagina
    assert b"127.0.0.1" not in pagina


def test_script_so_usa_caminhos_relativos_e_texto_por_textcontent():
    script = criar_app().test_client().get("/app.js").data.decode("utf-8")
    caminhos = set(re.findall(r'"(api/[a-z/]+)"', script))
    assert caminhos == {
        "api/estado", "api/conexao", "api/cadastro", "api/casos", "api/demo/cenarios", "api/demo/injetar"
    }
    # nenhum caminho absoluto nem endereço: fetch e src só relativos (iframe do Colab)
    assert not re.search(r"""["'`]/(?!/)""", script) and "http://" not in script
    assert "127.0.0.1" not in script and "localhost" not in script
    assert "innerHTML" not in script and "outerHTML" not in script and "insertAdjacentHTML" not in script
    assert "fetch(API." in script and re.search(r"fetch\((?!caminho|API\.)", script) is None


@pytest.fixture
def guardiao_registrado():
    from guardiao.app import definir_guardiao
    from guardiao.canal.simulado import CanalSimulado
    from guardiao.recepcao import Guardiao

    guardiao = Guardiao(CanalSimulado())
    definir_guardiao(guardiao)
    yield guardiao
    definir_guardiao(None)


def test_estado_le_o_guardiao_registrado(guardiao_registrado):
    from guardiao.canal.base import InicioBot

    cliente = criar_app().test_client()
    base = {"rodando": True, "modo": "demonstracao", "tem_bot": False}
    assert cliente.get("/api/estado").get_json() == {
        **base, "conectado": False, "idosa_habilitada": False, "responsavel_cadastrada": False
    }
    guardiao_registrado.conectar()
    assert cliente.get("/api/estado").get_json() == {
        **base, "conectado": True, "idosa_habilitada": True, "responsavel_cadastrada": False
    }
    codigo = guardiao_registrado.cadastro.gerar_codigo()
    guardiao_registrado.cadastro.tratar_inicio(InicioBot(9, 9, parametro=codigo, nome="Ana"))
    assert cliente.get("/api/estado").get_json() == {
        **base, "conectado": True, "idosa_habilitada": True, "responsavel_cadastrada": True
    }


def test_sem_guardiao_registrado_tudo_falso(guardiao_registrado):
    from guardiao.app import definir_guardiao

    guardiao_registrado.conectar()
    definir_guardiao(None)
    assert criar_app().test_client().get("/api/estado").get_json() == ESTADO_SEM_GUARDIAO
