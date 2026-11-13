from guardiao.app import HOST, criar_app


def test_estado_inicial():
    cliente = criar_app().test_client()
    resposta = cliente.get("/api/estado")
    assert resposta.status_code == 200
    assert resposta.get_json() == {"conectado": False, "responsavel_cadastrada": False}


def test_serve_frontend():
    cliente = criar_app().test_client()
    pagina = cliente.get("/")
    assert pagina.status_code == 200 and b"/api/estado" not in pagina.data
    assert b"app.js" in pagina.data
    script = cliente.get("/app.js")
    assert script.status_code == 200 and b"/api/estado" in script.data
    assert cliente.get("/styles.css").status_code == 200
    for sonda in ("/../backend/pytest.ini", "/..%2fbackend/pytest.ini", "/..%2Fbackend%2Fpytest.ini"):
        assert cliente.get(sonda).status_code == 404, sonda


def test_so_localhost():
    assert HOST == "127.0.0.1"
