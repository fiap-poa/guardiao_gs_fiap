"""Notebook do Colab e varredura do repositório (histórias 3 a 8).

A história 8 roda o notebook inteiro, célula por célula e em ordem, com dublês do bot e do
Gemini (`_rodar_notebook`), além das checagens por trecho.
"""

import json
import re
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
NOTEBOOK = RAIZ / "notebook" / "guardiao_colab.ipynb"
PASTAS_VARRIDAS = [RAIZ / "backend", RAIZ / "frontend", RAIZ / "notebook"]
ARQUIVOS_VARRIDOS = [RAIZ / "README.md"]  # história 8: o README vai no ZIP da entrega
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
    yield from (arquivo for arquivo in ARQUIVOS_VARRIDOS if arquivo.exists())
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
        "CONJUNTO_CAP3",
        "RODAR_CONJUNTO_CAP3 = False",
        "guardiao.conectar()",
        "definir_guardiao(guardiao)",
        "iniciar_em_segundo_plano",
        "serve_kernel_port_as_iframe",
        "guardiao.link_cadastro_vigente()",
        "ESPERA_CADASTRO_S = 300",
        "esperar_cadastro(guardiao, ESPERA_CADASTRO_S)",
        'abrir_caso(guardiao, ANALISADAS, "golpe_classico")',
        "TOQUE_SIMULADO = False",
        "ESPERA_TOQUE_S = 180",
        "injetar_mostrando(guardiao, ANALISADAS, canal.injetar, cenario_id)",
        "conferir_sinal(guardiao, SUSPEITAS",
        "mostrar_deteccao(guardiao, SUSPEITAS)",
        "RELOGIO.adiantar(7)",
        "RELOGIO.voltar()",
        "formatar_celular(canal.celular())",
        "guardiao.casos.verificar_prazos()",
        "guardiao.casos.listar()",
        "guardiao.casos.apagar_tudo()",
        "guardiao.fechar()",
        "apagar_sessao(canal_encerrado, LOCAL_DIR)",
        # história 6: alerta, toque, desfecho e casos
        "PRAZO_RESPOSTA = timedelta(minutes=10)",
        'COMO_CHAMA_IDOSA = "sua mãe"',
        'CASOS_ARQUIVO = LOCAL_DIR / "casos.json"',
        "prazo_resposta=PRAZO_RESPOSTA, casos_arquivo=CASOS_ARQUIVO, como_chama_idosa=COMO_CHAMA_IDOSA",
    ):
        assert trecho in codigo, trecho


def test_secoes_numeradas_na_ordem_do_sinal_de_sucesso(notebook):
    titulos = [
        _fonte(c).splitlines()[0] for c in notebook["cells"] if c["cell_type"] == "markdown" and _fonte(c).startswith("## ")
    ]
    assert [t.split(".")[0] for t in titulos] == [f"## {n}" for n in range(1, 13)]
    for titulo in (
        "## 5. Conectar o Guardião",
        "## 6. Tela do familiar",
        "## 7. Cadastro da responsável",
        '## 8. Golpe clássico: alerta e toque "É golpe"',
        "## 9. Os três cenários sem alerta",
        "## 10. Conferência do sinal de sucesso",
        "## 11. Extras (opcional)",
        "## 12. Encerrar",
    ):
        assert titulo in titulos, titulo
    texto = "\n".join(_fonte(c) for c in notebook["cells"])
    assert "próximas versões" not in texto and "próxima versão" not in texto
    assert "Teste do Guardião" not in texto  # o aviso de teste saiu: os avisos agora são de verdade
    assert "Executar tudo" in texto and "Executar anteriores" in texto
    assert "seção 9)" not in _fonte(notebook["cells"][9]) + _codigo(notebook)[4]  # a tela agora é a seção 6


def test_notebook_nao_mostra_texto_do_que_foi_descartado(notebook):
    """A injeção passa por `roteiro.injetar_mostrando`, que só mostra o texto do que foi analisado."""
    from pathlib import Path as _Path

    codigo = "\n".join(_codigo(notebook))
    roteiro = (_Path(__file__).resolve().parents[1] / "guardiao" / "roteiro.py").read_text(encoding="utf-8")
    assert "injetar_mostrando(guardiao, ANALISADAS" in codigo
    assert "analisadas[ja_analisadas:]" in roteiro and "texto não lido" in roteiro
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


def test_readme_existe_e_entra_na_varredura():
    assert RAIZ / "README.md" in list(_arquivos())


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


# --------------------------------------------------------------------------- notebook inteiro, em ordem (história 8)

LOCAIS = {"127.0.0.1", "localhost", "::1"}


def _descartados() -> list[str]:
    from guardiao.canal.cenarios import obter_cenario

    return [t for c in ("contato_antigo_pede_dinheiro", "mensagem_em_grupo") for t in obter_cenario(c).mensagens]


@pytest.fixture
def so_local(monkeypatch):
    """Rede proibida, menos o HTTP local da tela (a conferência lê `api/casos` em 127.0.0.1)."""
    import socket

    conectar, resolver = socket.socket.connect, socket.getaddrinfo

    def connect(self, endereco):
        if isinstance(endereco, tuple) and endereco[0] in LOCAIS:
            return conectar(self, endereco)
        raise AssertionError("tentou acessar a rede")

    def getaddrinfo(host, *args, **kwargs):
        if host in LOCAIS:
            return resolver(host, *args, **kwargs)
        raise AssertionError("tentou acessar a rede")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


class _Responsavel:
    """A responsável, numa thread: toca Iniciar pelo link do notebook e os botões do alerta."""

    def __init__(self, ns, bot, iniciar=True, tocar_golpe=True):
        self.ns, self.bot = ns, bot
        self.iniciar, self.tocar_golpe = iniciar, tocar_golpe
        self.parar = threading.Event()
        self.thread = threading.Thread(target=self._rodar, name="responsavel-teste", daemon=True)
        self.thread.start()

    def _rodar(self):
        from guardiao.canal.base import InicioBot
        from test_casos import RESPONSAVEL

        while not self.parar.wait(0.02):
            guardiao, link = self.ns.get("guardiao"), self.ns.get("LINK_CADASTRO")
            if guardiao is None:
                continue
            if self.iniciar and link and not guardiao.cadastro.cadastrada:
                codigo = link.split("?start=")[1]
                self.bot.handler(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=codigo, nome="Ana"))
            pedro = guardiao.casos.caso_de("sim:novo-1")
            if self.tocar_golpe and pedro is not None and pedro.estado == "aguardando":
                self.bot.tocar("golpe", pedro.id)

    def fim(self):
        self.parar.set()
        self.thread.join(5)


def _rodar_notebook(
    notebook,
    monkeypatch,
    tmp_path,
    capsys,
    com_bot=True,
    com_gemini=True,
    iniciar=True,
    tocar_golpe=True,
    trocas=(),
    sem_encerrar=False,
):
    """Roda as células de código do notebook em ordem num namespace só, como o *Executar tudo*.

    Dublês: canal simulado com `test_casos.DubleBot` na saída, `duble_gemini.DubleRegras`,
    `carregar_env` neutralizado, Flask na porta 0 e `backend/.local` trocado por `tmp_path`.
    Devolve o namespace, o bot e a saída de cada célula.
    """
    import functools

    import guardiao.app as app_mod
    import guardiao.canal.fabrica as fabrica
    import guardiao.config as config
    import guardiao.gemini as gemini
    from duble_gemini import DubleRegras
    from guardiao.analise import Detector
    from guardiao.canal.simulado import CanalSimulado
    from test_casos import DubleBot

    duble_bot = DubleBot() if com_bot else None
    monkeypatch.chdir(RAIZ / "notebook")  # o Colab abre o notebook da pasta dele
    monkeypatch.setattr(config, "carregar_env", lambda *a, **k: False)  # nada de backend/.env
    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(fabrica, "criar_canal", lambda modo: CanalSimulado(saida=duble_bot))
    monkeypatch.setattr(gemini, "criar_detector", lambda: Detector(DubleRegras()) if com_gemini else None)
    monkeypatch.setattr(app_mod, "iniciar_em_segundo_plano", functools.partial(app_mod.iniciar_em_segundo_plano, porta=0))
    for nome, presente in (("TELEGRAM_BOT_TOKEN", com_bot), ("GEMINI_API_KEY", com_gemini)):
        if presente:
            monkeypatch.setenv(nome, "dublê")
        else:
            monkeypatch.delenv(nome, raising=False)
    for nome in ("GEMINI_MODELO", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        monkeypatch.delenv(nome, raising=False)

    ns: dict = {"__name__": "__main__"}
    responsavel = _Responsavel(ns, duble_bot, iniciar, tocar_golpe) if duble_bot is not None else None
    saidas = []
    try:
        for fonte in _codigo(notebook):
            if sem_encerrar and "parar_servidor()" in fonte:
                break
            for velho, novo in trocas:
                fonte = fonte.replace(velho, novo)
            exec(fonte, ns)
            saidas.append(capsys.readouterr().out)
    finally:
        if responsavel is not None:
            responsavel.fim()
        if not sem_encerrar:
            app_mod.parar_servidor()
            app_mod.definir_guardiao(None)
            if ns.get("guardiao") is not None:
                ns["guardiao"].fechar()
    return ns, duble_bot, saidas


def _saida_com(saidas, notebook, trecho) -> str:
    """A saída da célula que contém `trecho` (as células e as saídas estão na mesma ordem)."""
    [indice] = [i for i, fonte in enumerate(_codigo(notebook)) if trecho in fonte]
    return saidas[indice]


def _sessao_falsa(pasta):
    arquivos = [pasta / "guardiao.session", pasta / "guardiao.session-journal"]
    for arquivo in arquivos:
        arquivo.write_bytes(b"")
    return arquivos


CURTO = (("ESPERA_CADASTRO_S = 300", "ESPERA_CADASTRO_S = 0.3"), ("ESPERA_TOQUE_S = 180", "ESPERA_TOQUE_S = 0.3"))
EXTRAS = (
    ("RODAR_PRAZO = False", "RODAR_PRAZO = True"),
    ("RODAR_7_DIAS = False", "RODAR_7_DIAS = True"),
    ("RODAR_CONJUNTO_CAP3 = False", "RODAR_CONJUNTO_CAP3 = True"),
)


def test_roteiro_completo_com_dubles(notebook, monkeypatch, tmp_path, capsys, so_local):
    """O sinal de sucesso de ponta a ponta: Iniciar e "É golpe" tocados por uma thread."""
    import guardiao.app as app_mod
    from test_casos import NUMERO_PEDRO

    sessao = _sessao_falsa(tmp_path)
    ns, bot, saidas = _rodar_notebook(notebook, monkeypatch, tmp_path, capsys)
    tudo = "\n".join(saidas)

    assert "Flask no ar na porta" in tudo and "Traceback" not in tudo
    cadastro = _saida_com(saidas, notebook, "esperar_cadastro(guardiao")
    # a thread pode tocar Iniciar logo que o link sai, antes de a espera começar
    assert "responsável cadastrada: ela recebeu" in cadastro or "a responsável já está cadastrada" in cadastro
    assert "responsável cadastrada:           sim" in cadastro
    golpe = _saida_com(saidas, notebook, 'abrir_caso(guardiao, ANALISADAS, "golpe_classico")')
    assert "dizendo ser Pedro" in golpe and f"número verdadeiro no alerta: {NUMERO_PEDRO}" in golpe
    assert 'toque "É golpe" no alerta' in golpe and "caso: golpe (a responsável tocou É golpe)" in golpe
    assert ">> [" in golpe and "Não faça nenhum Pix agora" in golpe
    [alerta] = bot.alertas
    assert alerta.numero_verdadeiro == NUMERO_PEDRO and alerta.como_chama_idosa == "sua mãe"

    sem_alerta = _saida_com(saidas, notebook, "CENARIOS_SEM_ALERTA")
    assert sem_alerta.count("alerta: nenhum") == 3 and "SIM (não devia)" not in sem_alerta
    assert "descarte (contato conhecido)" in sem_alerta and "descarte (grupo)" in sem_alerta
    assert "Gemini: sem suspeita" in sem_alerta
    deteccao = _saida_com(saidas, notebook, "mostrar_deteccao(")
    conferencia = _saida_com(saidas, notebook, "conferir_sinal(")
    for texto in _descartados():  # do que foi descartado, nem o texto (o celular da Dona Maria mostra tudo)
        assert texto not in sem_alerta + deteccao + conferencia

    assert "sinal de sucesso: OK (10 de 10 itens)" in conferencia and "FALHOU" not in conferencia
    assert ns["SINAL_OK"] is True

    assert "número salvo nos contatos: Pedro Neto 5500987650003" in deteccao and "suspeitas: 1" in deteccao
    for chave in ("RODAR_PRAZO", "RODAR_7_DIAS", "RODAR_CONJUNTO_CAP3"):
        assert f"mude {chave} para True" in _saida_com(saidas, notebook, f"{chave} = False")
    casos = _saida_com(saidas, notebook, "ROTULOS_TOQUE, hora")
    assert "Pedro: golpe" in casos and "resposta: É golpe" in casos
    assert "sim:" not in casos and "5500" not in casos and "98765" not in casos

    encerrar = _saida_com(saidas, notebook, "parar_servidor()")
    assert "casos apagados" in encerrar and "sessão do Telethon: apagada" in encerrar
    assert not (tmp_path / "casos.json").exists() and not any(a.exists() for a in sessao)
    assert ns["guardiao"] is None and app_mod._servidor is None and app_mod._guardiao is None


def test_roteiro_completo_com_os_extras(notebook, monkeypatch, tmp_path, capsys, so_local):
    """Com as chaves dos extras ligadas: 10 minutos e "Era ele mesmo" tardio, 7 dias e CAP-3.

    Toques simulados: um toque de verdade da thread no Lucas correria com a própria célula, que
    só pede o toque tardio depois de mostrar o "sem resposta".
    """
    trocas = EXTRAS + (("TOQUE_SIMULADO = False", "TOQUE_SIMULADO = True"),)
    ns, bot, saidas = _rodar_notebook(
        notebook, monkeypatch, tmp_path, capsys, tocar_golpe=False, trocas=trocas, sem_encerrar=True
    )
    try:
        assert ns["SINAL_OK"] is True
        prazo = _saida_com(saidas, notebook, "RODAR_PRAZO = False")
        assert "relógio do Guardião adiantado 0:10:00" in prazo and "caso: sem resposta (o prazo venceu)" in prazo
        assert "caso: era ele mesmo (contato liberado)" in prazo and "o número agora está: conhecido" in prazo
        sete = _saida_com(saidas, notebook, "RODAR_7_DIAS = False")
        assert "virou conhecido" in sete and "agora: observado" in sete
        assert "acertos: 8 de 8" in _saida_com(saidas, notebook, "RODAR_CONJUNTO_CAP3 = False")
        assert ns["RELOGIO"].deslocamento.total_seconds() == 0
        assert ns["guardiao"].estado()["casos"] == {"aguardando": 0, "golpe": 1, "era_ele_mesmo": 1, "sem_resposta": 0}
        avisos = [linha.texto for linha in ns["canal"].celular() if linha.tipo == "aviso"]
        assert len(avisos) == 2 and "dizendo ser Lucas" in avisos[1]

        golpe = _celula_com(notebook, 'abrir_caso(guardiao, ANALISADAS, "golpe_classico")')
        exec(golpe, ns)  # de novo: o caso já está decidido
        assert "já foi decidido" in capsys.readouterr().out and len(bot.alertas) == 2
    finally:
        exec(_celula_com(notebook, "parar_servidor()"), ns)
    assert "casos apagados" in capsys.readouterr().out and ns["guardiao"] is None


def test_roteiro_com_toque_simulado(notebook, monkeypatch, tmp_path, capsys, so_local):
    trocas = (("TOQUE_SIMULADO = False", "TOQUE_SIMULADO = True"),)
    ns, bot, saidas = _rodar_notebook(notebook, monkeypatch, tmp_path, capsys, tocar_golpe=False, trocas=trocas)
    golpe = _saida_com(saidas, notebook, 'abrir_caso(guardiao, ANALISADAS, "golpe_classico")')
    assert 'toque simulado: "É golpe"' in golpe and "caso: golpe" in golpe and ns["SINAL_OK"] is True


def test_roteiro_sem_iniciar_pula_com_aviso(notebook, monkeypatch, tmp_path, capsys, so_local):
    ns, bot, saidas = _rodar_notebook(notebook, monkeypatch, tmp_path, capsys, iniciar=False, trocas=CURTO)
    assert "ninguém tocou Iniciar em 0.3 s" in _saida_com(saidas, notebook, "esperar_cadastro(guardiao")
    for trecho in ('abrir_caso(guardiao, ANALISADAS, "golpe_classico")', "CENARIOS_SEM_ALERTA"):
        assert "aviso: a responsável não está cadastrada" in _saida_com(saidas, notebook, trecho)
    conferencia = _saida_com(saidas, notebook, "conferir_sinal(")
    assert "[FALHOU] responsável cadastrada" in conferencia and "sinal de sucesso: FALHOU" in conferencia
    assert ns["SINAL_OK"] is False and bot.alertas == []
    assert "casos apagados" in _saida_com(saidas, notebook, "parar_servidor()")


def test_roteiro_sem_toque_deixa_o_caso_aguardando(notebook, monkeypatch, tmp_path, capsys, so_local):
    ns, bot, saidas = _rodar_notebook(notebook, monkeypatch, tmp_path, capsys, tocar_golpe=False, trocas=CURTO)
    golpe = _saida_com(saidas, notebook, 'abrir_caso(guardiao, ANALISADAS, "golpe_classico")')
    assert "caso: aguardando o toque da responsável" in golpe and "ainda sem toque" in golpe
    conferencia = _saida_com(saidas, notebook, "conferir_sinal(")
    assert '[FALHOU] caso do Pedro como "golpe"' in conferencia and "aguardando o toque" in conferencia
    assert "[ok] alerta do golpe clássico" in conferencia and "FALHOU em 3 de 10 itens" in conferencia
    assert len(bot.alertas) == 1 and ns["SINAL_OK"] is False


@pytest.mark.parametrize("bot,gemini", [(False, True), (True, False), (False, False)])
def test_roteiro_sem_bot_ou_sem_gemini_avisa(notebook, monkeypatch, tmp_path, capsys, so_local, bot, gemini):
    ns, duble, saidas = _rodar_notebook(
        notebook, monkeypatch, tmp_path, capsys, com_bot=bot, com_gemini=gemini, trocas=CURTO
    )
    credenciais = _saida_com(saidas, notebook, "carregar_segredos_colab(SEGREDOS)")
    conferencia = _saida_com(saidas, notebook, "conferir_sinal(")
    golpe = _saida_com(saidas, notebook, 'abrir_caso(guardiao, ANALISADAS, "golpe_classico")')
    if not bot:
        assert "sem TELEGRAM_BOT_TOKEN o modo demonstração segue sem bot" in credenciais
        assert "TELEGRAM_BOT_TOKEN ausente" in _saida_com(saidas, notebook, "esperar_cadastro(guardiao")
        assert "[FALHOU] bot do Guardião" in conferencia and "falta o Secret TELEGRAM_BOT_TOKEN" in conferencia
    if not gemini:
        assert "sem GEMINI_API_KEY a detecção pelo Gemini fica desligada" in credenciais
        assert "detecção está desligada" in golpe
        assert "[FALHOU] detecção pelo Gemini" in conferencia and "falta o Secret GEMINI_API_KEY" in conferencia
    assert "aviso:" in golpe and ns["SINAL_OK"] is False
    assert "casos apagados" in _saida_com(saidas, notebook, "parar_servidor()")


# --------------------------------------------------------------------------- estrutura do roteiro


def test_celulas_curtas_com_as_funcoes_no_roteiro(notebook):
    codigo = "\n".join(_codigo(notebook))
    for nome in ("def injetar_mostrando", "def abrir_caso", "def tocar", "def _hora", "def falta_para_alertar"):
        assert nome not in codigo, nome  # saíram para guardiao/roteiro.py
    for fonte in _codigo(notebook):
        assert len(fonte.splitlines()) <= 75


def test_ordem_do_sinal_de_sucesso(notebook):
    codigo = _codigo(notebook)

    def posicao(trecho):
        [indice] = [i for i, fonte in enumerate(codigo) if trecho in fonte]
        return indice

    ordem = [
        posicao("guardiao.conectar()"),
        posicao("iniciar_em_segundo_plano()"),
        posicao("guardiao.link_cadastro_vigente()"),
        posicao("esperar_cadastro(guardiao"),
        posicao('abrir_caso(guardiao, ANALISADAS, "golpe_classico")'),
        posicao("CENARIOS_SEM_ALERTA"),
        posicao("conferir_sinal("),
        posicao("mostrar_deteccao("),
        posicao("RODAR_PRAZO = False"),
        posicao("RODAR_7_DIAS = False"),
        posicao("RODAR_CONJUNTO_CAP3 = False"),
        posicao("parar_servidor()"),
    ]
    assert ordem == sorted(ordem)
    assert posicao("parar_servidor()") == len(codigo) - 1  # o Encerrar é a última célula
    assert "guardiao.link_cadastro()" not in "\n".join(codigo)  # a célula do link usa o código da tela


# --------------------------------------------------------------------------- seção 5 (histórias 5 e 7)


@pytest.mark.parametrize("com_gemini", [True, False])
def test_celula_da_secao_5_liga_a_deteccao_so_com_detector(notebook, capsys, monkeypatch, tmp_path, com_gemini):
    import guardiao.canal.fabrica as fabrica
    import guardiao.config as config
    import guardiao.gemini as gemini
    from duble_gemini import DubleRegras
    from guardiao.analise import Detector
    from guardiao.app import definir_guardiao
    from guardiao.canal.simulado import CanalSimulado

    detector = Detector(DubleRegras()) if com_gemini else None
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
        assert "a tela (seção 6) mostra o QR da conta" in saida and "não conectou" not in saida
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


# --------------------------------------------------------------------------- seção 6 (tela) e 12 (encerrar)


def test_secao_6_tela_maior_e_texto(notebook):
    fonte = _celula_com(notebook, "serve_kernel_port_as_iframe")
    assert "height=900" in fonte and "height=420" not in fonte
    [texto] = [_fonte(c) for c in notebook["cells"] if _fonte(c).startswith("## 6. Tela do familiar")]
    for trecho in ("Abrir o bot", "celular do golpista", "não responde casos", "caminhos relativos", "duas etapas"):
        assert trecho in texto, trecho
    assert "api/estado" not in texto


def test_encerrar_sem_guardiao_apaga_casos_e_sessao(notebook, capsys, monkeypatch, tmp_path):
    import guardiao.config as config

    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    arquivo = tmp_path / "casos.json"
    arquivo.write_text('{"versao": 1, "casos": []}', encoding="utf-8")
    sessao = _sessao_falsa(tmp_path)
    exec(_celula_com(notebook, "parar_servidor()"), {})  # nem a seção 5 rodou (kernel reiniciado)
    assert not arquivo.exists() and not any(a.exists() for a in sessao)
    assert "casos apagados; sessão do Telethon: apagada" in capsys.readouterr().out


def test_encerrar_modo_real_faz_log_out(notebook, capsys, monkeypatch, tmp_path):
    import guardiao.config as config

    class CanalReal:
        usar_conta = True

        def __init__(self):
            self.chamadas = []

        def sair(self):
            self.chamadas.append("sair")
            for arquivo in tmp_path.glob("guardiao.session"):
                arquivo.unlink()
            return "encerrada"

        def fechar(self):
            self.chamadas.append("fechar")

    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    sessao = _sessao_falsa(tmp_path)  # o journal sobra depois do sair(): sai pelo glob
    canal = CanalReal()
    ns = {"guardiao": None, "canal": canal, "CASOS_ARQUIVO": tmp_path / "casos.json"}
    exec(_celula_com(notebook, "parar_servidor()"), ns)
    assert canal.chamadas == ["fechar", "sair", "fechar"] and not any(a.exists() for a in sessao)
    assert "sessão do Telethon: encerrada no Telegram e apagada" in capsys.readouterr().out
    assert ns["canal"] is None
