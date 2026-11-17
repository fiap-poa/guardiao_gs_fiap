"""Conjunto do CAP-3 contra o Gemini real. Opcional: só com chave e GUARDIAO_GEMINI_REAL=1.

    cd backend && GUARDIAO_GEMINI_REAL=1 .venv/bin/pytest -q tests/test_gemini_real.py

Usa a chave de `backend/.env` (ou do ambiente). Manda ao Gemini só as conversas fictícias
de `conjunto_cap3.py`.
"""

import os

import pytest
from dotenv import dotenv_values

from guardiao.config import ENV_PATH
from guardiao.conjunto_cap3 import CONJUNTO_CAP3

# lê o .env sem pôr nada em os.environ: os outros testes não podem ver credenciais reais
_AMBIENTE = {**(dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}), **os.environ}
LIGADO = os.environ.get("GUARDIAO_GEMINI_REAL") == "1" and bool((_AMBIENTE.get("GEMINI_API_KEY") or "").strip())

pytestmark = pytest.mark.skipif(not LIGADO, reason="Gemini real desligado (GEMINI_API_KEY + GUARDIAO_GEMINI_REAL=1)")


@pytest.fixture(scope="module")
def detector():
    from guardiao.gemini import criar_detector

    return criar_detector(_AMBIENTE)


@pytest.mark.parametrize("conversa", CONJUNTO_CAP3, ids=lambda c: c.id)
def test_conjunto_cap3_no_gemini_real(detector, conversa):
    analise = detector.analisar(list(conversa.mensagens))
    assert analise.suspeita == conversa.suspeita
    assert analise.alega_parentesco == conversa.alega_parentesco
    assert analise.pede_dinheiro == conversa.pede_dinheiro
    if conversa.suspeita and conversa.nome_alegado:
        assert analise.nome_alegado and conversa.nome_alegado.lower() in analise.nome_alegado.lower()
