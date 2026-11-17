"""Notebook do Colab e varredura do repositório (história 3)."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[2]
NOTEBOOK = RAIZ / "notebook" / "guardiao_colab.ipynb"
PASTAS_VARRIDAS = [RAIZ / "backend", RAIZ / "frontend", RAIZ / "notebook"]
EXTENSOES = {".py", ".js", ".html", ".css", ".ipynb", ".md", ".txt", ".json", ".toml", ".example", ".ini"}
# fora da varredura: ambiente, sessão do Telethon, evidências locais, caches e o .env com as credenciais
PASTAS_EXCLUIDAS = {".venv", ".local", "evidencias", "__pycache__"}
ARQUIVOS_EXCLUIDOS = {RAIZ / "backend" / ".env"}

# token do bot (`<id>:<35 caracteres>`), chave do Google, tokens do GitHub, api_hash do Telegram (32 hex)
SEGREDO = re.compile(
    r"[0-9]{8,}:[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|(?<![0-9A-Fa-f])[0-9a-fA-F]{32}(?![0-9A-Fa-f])"
)
# telefone brasileiro só com dígitos (55 + DDD + 8/9 dígitos) ou formatado (+55 DDD ...)
TELEFONE_DIGITOS = re.compile(r"(?<![0-9])55([0-9]{2})[0-9]{8,9}(?![0-9])")
TELEFONE_FORMATADO = re.compile(r"\+55[\s.-]*\(?([0-9]{2})\)?[\s.-]*[0-9]{4,5}[\s.-]?[0-9]{4}")


def _arquivos():
    for pasta in PASTAS_VARRIDAS:
        for caminho in pasta.rglob("*"):
            relativo = caminho.relative_to(pasta).parts
            if (
                caminho.is_file()
                and caminho.suffix in EXTENSOES
                and not PASTAS_EXCLUIDAS.intersection(relativo)
                and caminho not in ARQUIVOS_EXCLUIDOS
            ):
                yield caminho


@pytest.fixture(scope="module")
def notebook():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _fonte(celula) -> str:
    fonte = celula["source"]
    return fonte if isinstance(fonte, str) else "".join(fonte)


def _codigo(notebook) -> list[str]:
    return [_fonte(c) for c in notebook["cells"] if c["cell_type"] == "code"]


def test_notebook_e_json_valido_sem_saidas(notebook):
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kernelspec"]["language"] == "python"
    tipos = [c["cell_type"] for c in notebook["cells"]]
    assert set(tipos) == {"markdown", "code"} and tipos[0] == "markdown"
    for celula in notebook["cells"]:
        if celula["cell_type"] == "code":
            assert celula["outputs"] == [] and celula["execution_count"] is None


def test_toda_celula_de_codigo_vem_depois_de_markdown(notebook):
    tipos = [c["cell_type"] for c in notebook["cells"]]
    for i, tipo in enumerate(tipos):
        if tipo == "code":
            assert tipos[i - 1] == "markdown" or tipos[i - 1] == "code" and tipos[i - 2] == "markdown", i


def test_celulas_de_codigo_compilam(notebook):
    for n, fonte in enumerate(_codigo(notebook)):
        compile(fonte, f"celula-{n}", "exec")


def test_notebook_cobre_o_roteiro(notebook):
    codigo = "\n".join(_codigo(notebook))
    for trecho in (
        "extractall",  # ZIP enviado a /content
        "clone",  # git clone
        "GIT_TERMINAL_PROMPT",  # clone sem token não trava pedindo usuário
        "requirements.txt",
        "carregar_segredos_colab",
        'MODO = "demonstracao"',
        "criar_canal(MODO)",
        "Guardiao(\n    canal, relogio=RELOGIO, ao_analisar=ANALISADAS.append",
        "criar_detector()",
        "Analisador(detector, canal.listar_contatos, ao_suspeitar=SUSPEITAS.append, relogio=RELOGIO)",
        "analisador=analisador",
        "guardiao.analisador.ultimos()",
        "CONJUNTO_CAP3",
        "RODAR_CONJUNTO_CAP3 = False",
        "guardiao.conectar()",
        "injetar_mostrando(canal.injetar, cenario.id)",
        "RELOGIO.adiantar(7)",
        "RELOGIO.voltar()",
        "guardiao.link_cadastro()",
        "guardiao.estado()",
        "formatar_celular(canal.celular())",
        "definir_guardiao(guardiao)",
        "iniciar_em_segundo_plano",
        "serve_kernel_port_as_iframe",
        "guardiao.fechar()",
        # história 6: alerta, toque, desfecho e casos
        "PRAZO_RESPOSTA = timedelta(minutes=10)",
        'COMO_CHAMA_IDOSA = "sua mãe"',
        'CASOS_ARQUIVO = LOCAL_DIR / "casos.json"',
        "prazo_resposta=PRAZO_RESPOSTA, casos_arquivo=CASOS_ARQUIVO, como_chama_idosa=COMO_CHAMA_IDOSA",
        "TOQUE_SIMULADO = False",
        "guardiao.casos.verificar_prazos()",
        "guardiao.casos.listar()",
        "guardiao.casos.apagar_tudo()",
    ):
        assert trecho in codigo, trecho


def test_secoes_numeradas_e_sem_promessa_de_proxima_versao_do_alerta(notebook):
    titulos = [
        _fonte(c).splitlines()[0] for c in notebook["cells"] if c["cell_type"] == "markdown" and _fonte(c).startswith("## ")
    ]
    assert [t.split(".")[0] for t in titulos] == [f"## {n}" for n in range(1, 11)]
    assert "## 8. Alerta, toque e desfecho" in titulos
    texto = "\n".join(_fonte(c) for c in notebook["cells"])
    assert "próximas versões" not in texto
    assert "próxima versão" not in texto  # história 7: a tela do familiar existe
    assert "tela do familiar (seção 9) mostra a configuração e os casos" in texto
    assert "Teste do Guardião" not in texto  # o aviso de teste saiu: os avisos agora são de verdade


def test_notebook_nao_mostra_texto_do_que_foi_descartado(notebook):
    """A célula de injeção só mostra o texto do que foi para a análise (dados fictícios)."""
    codigo = "\n".join(_codigo(notebook))
    assert "ANALISADAS[ja_analisadas:]" in codigo and "texto não lido" in codigo
    assert "RECEBIDOS" not in codigo  # o handler solto da história 3 virou o Guardião


def test_notebook_nao_grava_nem_imprime_credencial(notebook):
    codigo = "\n".join(_codigo(notebook))
    assert "@github.com" not in codigo  # token nunca na URL do clone (iria para o .git/config)
    assert "git config" not in codigo and "remote set-url" not in codigo
    assert "GITHUB_TOKEN" not in codigo  # repositório público: o clone não usa token
    for linha in codigo.splitlines():
        if "print(" in linha:
            assert not re.search(r"\{(token|credencial|valor|os\.environ\[)", linha), linha
            assert "os.environ.get(nome)}" not in linha, linha


def test_varredura_sem_token_nem_chave():
    achados = [
        f"{caminho.relative_to(RAIZ)}:{m.group(0)[:12]}…"
        for caminho in _arquivos()
        for m in SEGREDO.finditer(caminho.read_text(encoding="utf-8"))
    ]
    assert achados == []


def test_varredura_todo_telefone_tem_ddd_00():
    achados = []
    for caminho in _arquivos():
        texto = caminho.read_text(encoding="utf-8")
        for padrao in (TELEFONE_DIGITOS, TELEFONE_FORMATADO):
            for m in padrao.finditer(texto):
                if m.group(1) != "00":
                    achados.append(f"{caminho.relative_to(RAIZ)}: DDD {m.group(1)}")
    assert achados == []


def test_padroes_da_varredura_pegam_o_que_devem():
    assert SEGREDO.search("1234567890:" + "A" * 35)
    assert SEGREDO.search("AIza" + "b" * 35)
    assert SEGREDO.search("ghp_" + "c" * 36)
    assert SEGREDO.search("api_hash=" + "0123456789abcdef" * 2)
    assert not SEGREDO.search("h:" + "a" * 12) and not SEGREDO.search("f" * 40)  # hash_id; sha1 não é api_hash
    # números fora do DDD 00 montados em partes, para a própria varredura não os achar aqui
    assert TELEFONE_DIGITOS.search("55" + "11" + "987654321").group(1) == "11"
    assert TELEFONE_DIGITOS.search("5500987654321").group(1) == "00"
    assert TELEFONE_FORMATADO.search("+55 (" + "21) 98765-4321").group(1) == "21"
    assert TELEFONE_FORMATADO.search("+55 00 98765-1001").group(1) == "00"
    assert not TELEFONE_DIGITOS.search("7123456789")


def _celula_com(notebook, trecho) -> str:
    [fonte] = [f for f in _codigo(notebook) if trecho in f]
    return fonte


def _namespace_demonstracao(com_gemini=False):
    from duble_gemini import DubleRegras
    from guardiao.analise import Analisador, Detector
    from guardiao.canal.cenarios import CENARIOS
    from guardiao.canal.simulado import CanalSimulado
    from guardiao.recepcao import Guardiao, RelogioAjustavel

    canal = CanalSimulado()
    analisadas, suspeitas = [], []
    relogio = RelogioAjustavel()
    detector = analisador = None
    if com_gemini:
        detector = Detector(DubleRegras())
        analisador = Analisador(detector, canal.listar_contatos, ao_suspeitar=suspeitas.append, relogio=relogio)
    guardiao = Guardiao(canal, relogio=relogio, ao_analisar=analisadas.append, analisador=analisador)
    guardiao.conectar()
    return {
        "MODO": "demonstracao",
        "canal": canal,
        "guardiao": guardiao,
        "ANALISADAS": analisadas,
        "SUSPEITAS": suspeitas,
        "CENARIOS": CENARIOS,
        "RELOGIO": relogio,
        "detector": detector,
    }


def test_celula_de_injecao_mostra_o_descarte_sem_o_texto(notebook, capsys):
    from guardiao.canal.cenarios import obter_cenario

    ns = _namespace_demonstracao()
    exec(_celula_com(notebook, "def injetar_mostrando"), ns)
    saida = capsys.readouterr().out
    assert "descarte (contato conhecido)" in saida and "descarte (grupo)" in saida
    for cenario_id in ("contato_antigo_pede_dinheiro", "mensagem_em_grupo"):
        for texto in obter_cenario(cenario_id).mensagens:
            assert texto not in saida
    assert "análise:" in saida and len(ns["ANALISADAS"]) == 6


def test_celula_dos_7_dias_pula_sem_a_injecao(notebook, capsys):
    ns = _namespace_demonstracao()
    exec(_celula_com(notebook, "def injetar_mostrando"), ns)
    sete_dias = _celula_com(notebook, "RELOGIO.adiantar(7)")
    capsys.readouterr()
    exec(sete_dias, ns)
    primeira = capsys.readouterr().out
    assert "virou conhecido" in primeira and "agora: observado" in primeira
    exec(sete_dias, ns)  # de novo: sim:novo-3 já é conhecido
    assert "pulando" in capsys.readouterr().out
    assert ns["RELOGIO"].deslocamento.total_seconds() == 0


def test_celula_de_deteccao_mostra_suspeitas_e_numero_verdadeiro(notebook, capsys):
    from guardiao.canal.cenarios import obter_cenario

    ns = _namespace_demonstracao(com_gemini=True)
    exec(_celula_com(notebook, "def injetar_mostrando"), ns)
    injecao = capsys.readouterr().out
    assert injecao.count("Gemini: SUSPEITA") == 2 and "Gemini: sem suspeita" in injecao
    exec(_celula_com(notebook, "guardiao.analisador.ultimos()"), ns)
    saida = capsys.readouterr().out
    assert "número salvo nos contatos: Pedro Neto 5500987650003" in saida
    assert "número salvo nos contatos: Lucas Filho 5500987650002" in saida
    assert "suspeitas: 2" in saida and "sim:novo-3: sem suspeita" in saida
    for cenario_id in ("contato_antigo_pede_dinheiro", "mensagem_em_grupo"):
        for texto in obter_cenario(cenario_id).mensagens:
            assert texto not in injecao + saida


def test_celula_de_deteccao_sem_gemini_avisa(notebook, capsys):
    ns = _namespace_demonstracao()
    exec(_celula_com(notebook, "def injetar_mostrando"), ns)
    assert "Gemini:" not in capsys.readouterr().out
    exec(_celula_com(notebook, "guardiao.analisador.ultimos()"), ns)
    assert "detecção está desligada" in capsys.readouterr().out


def test_celula_do_conjunto_cap3(notebook, capsys):
    fonte = _celula_com(notebook, "RODAR_CONJUNTO_CAP3 = False")
    ns = _namespace_demonstracao(com_gemini=True)
    exec(fonte, ns)
    assert "pulando" in capsys.readouterr().out and not ns["detector"].cliente.pedidos
    exec(fonte.replace("RODAR_CONJUNTO_CAP3 = False", "RODAR_CONJUNTO_CAP3 = True"), ns)
    assert "acertos: 8 de 8" in capsys.readouterr().out


@pytest.mark.parametrize("com_gemini", [True, False])
def test_celula_da_secao_5_liga_a_deteccao_so_com_detector(notebook, capsys, monkeypatch, tmp_path, com_gemini):
    import guardiao.canal.fabrica as fabrica
    import guardiao.gemini as gemini
    from duble_gemini import DubleRegras
    from guardiao.analise import Detector
    from guardiao.app import definir_guardiao
    from guardiao.canal.simulado import CanalSimulado

    detector = Detector(DubleRegras()) if com_gemini else None
    import guardiao.config as config

    monkeypatch.setattr(gemini, "criar_detector", lambda: detector)
    monkeypatch.setattr(fabrica, "criar_canal", lambda modo: CanalSimulado())
    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)  # os casos não vão para backend/.local
    ns = {"MODO": "demonstracao"}
    try:
        exec(_celula_com(notebook, "criar_canal(MODO)"), ns)
        saida = capsys.readouterr().out
        guardiao = ns["guardiao"]
        assert guardiao.casos.prazo.total_seconds() == 600 and guardiao.casos.como_chama_idosa == "sua mãe"
        assert guardiao.casos.repositorio.arquivo == tmp_path / "casos.json"
        if com_gemini:
            assert guardiao.analisador is not None and guardiao.analisador.detector is detector
            assert "detecção pelo Gemini: ligada" in saida
            ns["canal"].injetar("golpe_classico")
            assert [s.busca.numero for s in ns["SUSPEITAS"]] == ["5500987650003"]
        else:
            assert guardiao.analisador is None and "detecção pelo Gemini: desligada" in saida
    finally:
        if ns.get("guardiao") is not None:
            ns["guardiao"].fechar()
        definir_guardiao(None)


# --------------------------------------------------------------------------- seção 8 (história 6)


def _namespace_com_casos(tmp_path, notebook, capsys, cadastrar=True, cadastrar_antes=False):
    """Seções 5 a 7 na ordem do notebook: injeção (seção 6) e depois o cadastro (seção 7)."""
    from datetime import timedelta

    from duble_gemini import DubleRegras
    from guardiao.analise import Analisador, Detector
    from guardiao.canal.cenarios import CENARIOS
    from guardiao.canal.simulado import CanalSimulado
    from guardiao.recepcao import Guardiao, RelogioAjustavel
    from test_casos import DubleBot, Montagem

    bot = DubleBot()
    canal = CanalSimulado(saida=bot)
    relogio = RelogioAjustavel()
    analisadas, suspeitas = [], []
    detector = Detector(DubleRegras())
    analisador = Analisador(detector, canal.listar_contatos, ao_suspeitar=suspeitas.append, relogio=relogio, varredura_s=None)
    arquivo = tmp_path / "casos.json"
    guardiao = Guardiao(
        canal,
        relogio=relogio,
        ao_analisar=analisadas.append,
        analisador=analisador,
        prazo_resposta=timedelta(minutes=10),
        casos_arquivo=arquivo,
        como_chama_idosa="sua mãe",
        varredura_casos_s=None,
    )
    guardiao.conectar()
    ns = {
        "MODO": "demonstracao",
        "canal": canal,
        "guardiao": guardiao,
        "ANALISADAS": analisadas,
        "SUSPEITAS": suspeitas,
        "CENARIOS": CENARIOS,
        "RELOGIO": relogio,
        "PRAZO_RESPOSTA": timedelta(minutes=10),
        "CASOS_ARQUIVO": arquivo,
        "detector": detector,
        "bot": bot,
    }
    cadastro = lambda: Montagem.cadastrar(SimpleNamespace(guardiao=guardiao, bot=bot))  # noqa: E731
    if cadastrar and cadastrar_antes:
        cadastro()
    exec(_celula_com(notebook, "def injetar_mostrando"), ns)
    if cadastrar and not cadastrar_antes:
        cadastro()
    capsys.readouterr()
    return ns


def _celula_golpe(notebook, simulado=True, espera=None):
    fonte = _celula_com(notebook, "def abrir_caso")
    if simulado:
        fonte = fonte.replace("TOQUE_SIMULADO = False", "TOQUE_SIMULADO = True")
    if espera is not None:
        fonte = fonte.replace("ESPERA_TOQUE_S = 180", f"ESPERA_TOQUE_S = {espera}")
    return fonte


def _avisos(ns):
    return [linha.texto for linha in ns["canal"].celular() if linha.tipo == "aviso"]


def test_secao_8_golpe_com_toque_simulado(notebook, capsys, tmp_path):
    from test_casos import NUMERO_PEDRO

    ns = _namespace_com_casos(tmp_path, notebook, capsys)
    assert ns["guardiao"].casos.listar() == []  # na seção 6 ainda não havia responsável
    exec(_celula_golpe(notebook), ns)
    saida = capsys.readouterr().out
    assert "dizendo ser Pedro" in saida and 'toque simulado: "É golpe"' in saida
    assert "caso: golpe (a responsável tocou É golpe)" in saida
    assert ">> " in saida and "Não faça nenhum Pix agora" in saida
    [alerta] = ns["bot"].alertas
    assert alerta.numero_verdadeiro == NUMERO_PEDRO and alerta.como_chama_idosa == "sua mãe"
    assert len(_avisos(ns)) == 1
    exec(_celula_golpe(notebook), ns)  # de novo: o caso já está decidido
    assert "já foi decidido" in capsys.readouterr().out and len(ns["bot"].alertas) == 1
    ns["guardiao"].fechar()


def test_secao_8_golpe_com_caso_aberto_na_secao_6(notebook, capsys, tmp_path):
    ns = _namespace_com_casos(tmp_path, notebook, capsys, cadastrar_antes=True)
    assert len(ns["bot"].alertas) == 2  # Pedro e Lucas já alertados na injeção
    exec(_celula_golpe(notebook), ns)
    assert "caso: golpe" in capsys.readouterr().out and len(ns["bot"].alertas) == 2
    ns["guardiao"].fechar()


def test_secao_8_golpe_espera_o_toque_de_verdade(notebook, capsys, tmp_path):
    import threading
    import time

    ns = _namespace_com_casos(tmp_path, notebook, capsys)

    def responsavel_toca():
        limite = time.monotonic() + 5
        while ns["guardiao"].casos.caso_de("sim:novo-1") is None and time.monotonic() < limite:
            time.sleep(0.01)
        time.sleep(0.2)
        ns["bot"].tocar("golpe")

    tocador = threading.Thread(target=responsavel_toca)
    tocador.start()
    exec(_celula_golpe(notebook, simulado=False, espera=10), ns)
    tocador.join(5)
    saida = capsys.readouterr().out
    assert 'toque "É golpe" no alerta' in saida and "caso: golpe" in saida and "toque simulado" not in saida
    ns["guardiao"].fechar()


def test_secao_8_golpe_sem_toque_continua_aguardando(notebook, capsys, tmp_path):
    ns = _namespace_com_casos(tmp_path, notebook, capsys)
    exec(_celula_golpe(notebook, simulado=False, espera=0), ns)
    saida = capsys.readouterr().out
    assert "caso: aguardando" in saida and "ainda sem toque" in saida and _avisos(ns) == []
    ns["guardiao"].fechar()


def test_secao_8_lucas_sem_resposta_e_toque_tardio(notebook, capsys, tmp_path):
    ns = _namespace_com_casos(tmp_path, notebook, capsys)
    exec(_celula_golpe(notebook), ns)
    capsys.readouterr()
    exec(_celula_com(notebook, "remetente_lucas"), ns)
    saida = capsys.readouterr().out
    assert "relógio do Guardião adiantado 0:10:00" in saida
    assert "caso: sem resposta (o prazo venceu)" in saida and "caso: era ele mesmo (contato liberado)" in saida
    assert "o número agora está: conhecido" in saida
    avisos = _avisos(ns)
    assert len(avisos) == 2 and "dizendo ser Lucas" in avisos[1]
    assert ns["RELOGIO"].deslocamento.total_seconds() == 0
    assert ns["guardiao"].estado()["casos"] == {"aguardando": 0, "golpe": 1, "era_ele_mesmo": 1, "sem_resposta": 0}
    exec(_celula_com(notebook, "def _hora"), ns)
    lista = capsys.readouterr().out
    assert "Lucas: era ele mesmo" in lista and "Pedro: golpe" in lista and "resposta: É golpe" in lista
    assert "sim:" not in lista and "5500" not in lista and "98765" not in lista
    ns["guardiao"].fechar()


def test_secao_8_sem_responsavel_so_avisa(notebook, capsys, tmp_path):
    ns = _namespace_com_casos(tmp_path, notebook, capsys, cadastrar=False)
    exec(_celula_golpe(notebook), ns)
    assert "a responsável não está cadastrada" in capsys.readouterr().out
    exec(_celula_com(notebook, "remetente_lucas"), ns)
    assert "a responsável não está cadastrada" in capsys.readouterr().out
    assert ns["bot"].alertas == []
    ns["guardiao"].fechar()


def test_encerrar_apaga_os_casos(notebook, capsys, tmp_path):
    ns = _namespace_com_casos(tmp_path, notebook, capsys)
    exec(_celula_golpe(notebook), ns)
    arquivo = ns["CASOS_ARQUIVO"]
    guardiao = ns["guardiao"]
    assert arquivo.exists()
    exec(_celula_com(notebook, "parar_servidor()"), ns)
    assert not arquivo.exists() and guardiao.casos.listar() == [] and ns["guardiao"] is None
    assert "casos apagados" in capsys.readouterr().out


def test_encerrar_sem_guardiao_apaga_o_arquivo_de_casos(notebook, capsys, tmp_path):
    arquivo = tmp_path / "casos.json"
    arquivo.write_text('{"versao": 1, "casos": []}', encoding="utf-8")
    ns = {"guardiao": None, "canal": None, "CASOS_ARQUIVO": arquivo}
    exec(_celula_com(notebook, "parar_servidor()"), ns)
    assert not arquivo.exists() and "casos apagados" in capsys.readouterr().out


# --------------------------------------------------------------------------- seções 5 e 9 (história 7)


class _CanalRealSemSessao:
    """Canal real falso: `conectar` falha por falta de sessão; tem `login_qr` (a tela o usa)."""

    def __init__(self, erro="SemSessao"):
        self.erro = erro
        self.fechado = False

    def login_qr(self, mostrar_qr, pedir_senha):
        raise AssertionError("a seção 5 não começa o login: quem começa é a tela")

    def conectar(self):
        import guardiao.canal.telegram as telegram

        raise getattr(telegram, self.erro)("a sessão não está logada; rode `login`")

    def info_bot(self):
        return {"id": 1, "username": "guardiao_teste_bot"}

    def listar_contatos(self):
        return []

    def fechar(self):
        self.fechado = True


@pytest.mark.parametrize("erro", ["SemSessao", "SessaoNaoAutorizada"])
def test_secao_5_modo_real_sem_sessao_mantem_o_guardiao_registrado(notebook, capsys, monkeypatch, tmp_path, erro):
    import guardiao.app as app_mod
    import guardiao.canal.fabrica as fabrica
    import guardiao.config as config
    import guardiao.gemini as gemini

    canal = _CanalRealSemSessao(erro)
    monkeypatch.setattr(gemini, "criar_detector", lambda: None)
    monkeypatch.setattr(fabrica, "criar_canal", lambda modo: canal)
    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    ns = {"MODO": "real"}
    try:
        exec(_celula_com(notebook, "criar_canal(MODO)"), ns)
        saida = capsys.readouterr().out
        guardiao = ns["guardiao"]
        assert guardiao is not None and app_mod._guardiao is guardiao
        assert not guardiao.estado()["conectado"] and guardiao.modo == "real"
        assert "a tela (seção 9) mostra o QR da conta" in saida and "não conectou" not in saida
        assert "python -m guardiao.verificar login" in saida
        assert not canal.fechado
    finally:
        app_mod.definir_guardiao(None)
        if ns.get("guardiao") is not None:
            ns["guardiao"].fechar()


def test_secao_5_modo_demonstracao_com_falha_nao_registra(notebook, capsys, monkeypatch, tmp_path):
    import guardiao.app as app_mod
    import guardiao.canal.fabrica as fabrica
    import guardiao.config as config
    import guardiao.gemini as gemini
    from guardiao.canal.simulado import CanalSimulado

    class Quebrado(CanalSimulado):
        def conectar(self):
            raise ConnectionError("falhou")

    monkeypatch.setattr(gemini, "criar_detector", lambda: None)
    monkeypatch.setattr(fabrica, "criar_canal", lambda modo: Quebrado())
    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    anterior = _guardiao_anterior()
    app_mod.definir_guardiao(anterior)  # a célula rodou antes e conectou
    ns = {"MODO": "demonstracao", "guardiao": anterior}
    try:
        exec(_celula_com(notebook, "criar_canal(MODO)"), ns)
        registrado = app_mod._guardiao
    finally:
        app_mod.definir_guardiao(None)
    assert anterior.canal._handler is None and not anterior.conectado  # o anterior foi fechado
    assert ns["guardiao"] is None and registrado is None  # e a tela não o mostra mais
    assert "o Guardião não conectou (ConnectionError)" in capsys.readouterr().out


def _guardiao_anterior():
    from guardiao.canal.simulado import CanalSimulado
    from guardiao.recepcao import Guardiao

    guardiao = Guardiao(CanalSimulado(), varredura_casos_s=None)
    guardiao.conectar()
    return guardiao


def test_secao_9_tela_maior_e_texto_novo(notebook):
    fonte = _celula_com(notebook, "serve_kernel_port_as_iframe")
    assert 'height=900' in fonte and "height=420" not in fonte
    [texto] = [_fonte(c) for c in notebook["cells"] if _fonte(c).startswith("## 9. Tela do familiar")]
    for trecho in ("Abrir o bot", "celular do golpista", "não responde casos", "caminhos relativos", "duas etapas"):
        assert trecho in texto, trecho
    assert "api/estado" not in texto
