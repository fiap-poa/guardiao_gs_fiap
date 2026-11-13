"""Só a camada de canal conhece o Telegram (critério de aceite da história 2)."""

import re
from pathlib import Path

GUARDIAO = Path(__file__).resolve().parents[1] / "guardiao"
PADRAO = re.compile(r"telethon|api\.telegram\.org", re.IGNORECASE)


def test_nada_fora_de_canal_cita_telethon_ou_bot_api():
    ocorrencias = [
        str(p.relative_to(GUARDIAO))
        for p in GUARDIAO.rglob("*.py")
        if "canal" not in p.relative_to(GUARDIAO).parts and PADRAO.search(p.read_text(encoding="utf-8"))
    ]
    assert ocorrencias == []
