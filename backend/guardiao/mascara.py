"""Máscaras e gravação de evidências só com metadados.

Evidências nunca carregam texto de mensagem, nome, telefone real ou id cru:
- ids viram `h:` + 12 hex do sha256 (`hash_id`);
- telefones viram `55*******1234` (`mascarar_telefone`);
- o resto são contagens, booleanos e rótulos curtos (`privada`, `golpe`, ...).

`gravar_evidencia` recusa qualquer campo fora dessas formas.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from guardiao.config import EVIDENCIAS_DIR, garantir_dir_privado

# Chaves que denunciam conteúdo; nunca entram numa evidência.
CHAVES_PROIBIDAS = frozenset(
    {
        "texto", "text", "raw_text", "mensagem", "message", "conteudo", "corpo",
        "body", "trecho", "nome", "name", "first_name", "last_name", "username",
        "telefone_real", "phone", "token", "senha", "password", "api_hash",
    }
)
_ROTULO = re.compile(r"^[a-z0-9_.:\-]{1,48}$")
_HASH = re.compile(r"^h:[0-9a-f]{12}$")
_TELEFONE_MASCARADO = re.compile(r"^\d{0,2}\*+\d{0,4}$")
# 7+ dígitos num rótulo (mesmo com separadores) parecem telefone ou id cru.
MAX_DIGITOS_ROTULO = 6
# Contagens e ids de mensagem são pequenos; ids de usuário/chat e telefones não.
LIMITE_INTEIRO = 1_000_000


def hash_id(valor) -> str:
    """`h:` + 12 primeiros hex do sha256 do valor (como texto)."""
    return "h:" + hashlib.sha256(str(valor).encode("utf-8")).hexdigest()[:12]


def mascarar_telefone(telefone) -> str | None:
    """Mantém os 2 primeiros e os 4 últimos dígitos: `5500987651234` → `55*******1234`."""
    if telefone is None:
        return None
    digitos = re.sub(r"\D", "", str(telefone))
    if not digitos:
        return None
    if len(digitos) <= 6:
        return "*" * len(digitos)
    return digitos[:2] + "*" * (len(digitos) - 6) + digitos[-4:]


def validar_campo(chave: str, valor) -> None:
    """Levanta ValueError se o campo puder carregar conteúdo ou dado pessoal."""
    if chave.lower() in CHAVES_PROIBIDAS:
        raise ValueError(f"campo proibido em evidência: {chave}")
    if valor is None or isinstance(valor, bool):
        return
    if isinstance(valor, int):
        if abs(valor) >= LIMITE_INTEIRO:
            raise ValueError(f"inteiro grande em {chave}: use hash_id ou mascarar_telefone")
        return
    if isinstance(valor, float):
        if abs(valor) >= LIMITE_INTEIRO:
            raise ValueError(f"número grande em {chave}: use hash_id ou mascarar_telefone")
        return
    if isinstance(valor, str):
        if _HASH.match(valor) or _TELEFONE_MASCARADO.match(valor):
            return
        digitos = sum(1 for c in valor if c.isdigit())
        if _ROTULO.match(valor) and digitos <= MAX_DIGITOS_ROTULO:
            return
        raise ValueError(f"texto livre em {chave}: evidência só aceita rótulos, hashes e máscaras")
    raise ValueError(f"tipo não permitido em {chave}: {type(valor).__name__}")


def gravar_evidencia(verificacao: str, diretorio: Path | None = None, **campos) -> dict:
    """Acrescenta uma linha JSON em `evidencias/<verificacao>.jsonl` (modo 600)."""
    validar_campo("verificacao", verificacao)
    for chave, valor in campos.items():
        validar_campo(chave, valor)
    registro = {
        "em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verificacao": verificacao,
        **campos,
    }
    pasta = Path(diretorio) if diretorio is not None else EVIDENCIAS_DIR
    garantir_dir_privado(pasta)
    caminho = pasta / f"{verificacao}.jsonl"
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
