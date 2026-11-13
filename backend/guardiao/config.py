"""Caminhos do backend e carga do `.env`.

Credenciais só existem em `backend/.env` (ignorado pelo git, modo 600).
"""

import os
import stat
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAIZ_DIR = BACKEND_DIR.parent
FRONTEND_DIR = RAIZ_DIR / "frontend"
ENV_PATH = BACKEND_DIR / ".env"
LOCAL_DIR = BACKEND_DIR / ".local"
EVIDENCIAS_DIR = BACKEND_DIR / "evidencias"


def carregar_env(caminho: Path = ENV_PATH) -> bool:
    """Carrega o `.env` se existir. Avisa (sem mostrar valores) se o modo não for 600."""
    if not caminho.exists():
        return False
    modo = stat.S_IMODE(caminho.stat().st_mode)
    if modo & 0o077:
        print(
            f"aviso: {caminho.name} está com modo {oct(modo)}; rode `chmod 600 {caminho}`",
            file=sys.stderr,
        )
    load_dotenv(caminho, override=False)
    return True


def exigir(nome: str) -> str:
    """Lê uma variável de ambiente obrigatória; o erro cita só o nome."""
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise RuntimeError(f"variável {nome} ausente em backend/.env")
    return valor


def garantir_dir_privado(caminho: Path) -> Path:
    """Cria o diretório com modo 700 (e corrige o modo se já existir)."""
    caminho.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(caminho, 0o700)
    return caminho
