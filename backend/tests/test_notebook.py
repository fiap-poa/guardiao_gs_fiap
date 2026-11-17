"""Notebook do Colab e varredura do repositório (história 3)."""

import json
import re
from pathlib import Path

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
        "canal.injetar(",
        "formatar_celular(canal.celular())",
        "iniciar_em_segundo_plano",
        "serve_kernel_port_as_iframe",
    ):
        assert trecho in codigo, trecho


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
