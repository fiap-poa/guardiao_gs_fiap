"""Alerta real pelo bot do Guardião (CAP-5). Opcional: só com GUARDIAO_BOT_REAL=1, o token e o chat.

    cd backend && GUARDIAO_BOT_REAL=1 GUARDIAO_CHAT_RESPONSAVEL=<chat id> .venv/bin/pytest -q tests/test_bot_real.py

O chat é o da responsável, que já tocou Iniciar no bot. Usa o token de `backend/.env` (ou do
ambiente). Manda um único alerta, com o golpe clássico fictício (DDD 00) e os dois botões;
o toque não é esperado (nada faz polling aqui).
"""

import os
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from guardiao.config import ENV_PATH

# lê o .env sem pôr nada em os.environ: os outros testes não podem ver credenciais reais
_AMBIENTE = {**(dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}), **os.environ}
_TOKEN = (_AMBIENTE.get("TELEGRAM_BOT_TOKEN") or "").strip()
_CHAT = (_AMBIENTE.get("GUARDIAO_CHAT_RESPONSAVEL") or "").strip()
LIGADO = os.environ.get("GUARDIAO_BOT_REAL") == "1" and bool(_TOKEN) and bool(_CHAT)

pytestmark = pytest.mark.skipif(
    not LIGADO, reason="bot real desligado (TELEGRAM_BOT_TOKEN + GUARDIAO_CHAT_RESPONSAVEL + GUARDIAO_BOT_REAL=1)"
)


def test_alerta_real_chega_a_responsavel_com_os_dois_botoes():
    from datetime import datetime, timezone

    from guardiao.analise import Analise, ResultadoAnalise
    from guardiao.busca import ResultadoBusca
    from guardiao.canal.cenarios import CONTATOS, ID_IDOSA, obter_cenario
    from guardiao.canal.simulado import CanalSimulado
    from guardiao.canal.telegram import TelegramCanal
    from guardiao.casos import GestorCasos

    chat = int(_CHAT) if _CHAT.lstrip("-").isdigit() else _CHAT
    bot = TelegramCanal(None, None, _TOKEN, usar_conta=False, usar_bot=True)
    canal = CanalSimulado(saida=bot)
    responsavel = SimpleNamespace(usuario_id=chat, destinatario=chat, nome="Responsável")
    gestor = GestorCasos(
        canal,
        responsavel=lambda: responsavel,
        destinatario_idosa=lambda: ID_IDOSA,
        nome_idosa="Dona Maria",
        como_chama_idosa="sua mãe",
        varredura_s=None,
    )
    cenario = obter_cenario("golpe_classico")
    pedro = next(c for c in CONTATOS if c.nome == "Pedro Neto")
    resultado = ResultadoAnalise(
        cenario.remetente_id,
        "suspeita",
        datetime.now(timezone.utc),
        Analise(True, True, nome_alegado="Pedro", parentesco="neto", forma_pagamento="pix"),
        ResultadoBusca("encontrado", contato=pedro, candidatos=1),
        cenario.mensagens[1],
    )
    try:
        caso = gestor.abrir(resultado)
        assert caso.estado == "aguardando"
        assert gestor._vinculos[caso.id].alerta_id.isdigit()  # message_id devolvido pelo Telegram
    finally:
        gestor.fechar()
        canal.fechar()
