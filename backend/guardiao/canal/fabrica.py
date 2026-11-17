"""Escolhe a implementação do canal pelo modo.

- `"demonstracao"`: `CanalSimulado`; com `TELEGRAM_BOT_TOKEN`, a saída é um `TelegramCanal`
  só do bot (o alerta à responsável é real). Sem token, avisa e segue sem bot.
- `"real"`: `TelegramCanal` com a conta (Telethon) e o bot.

As credenciais vêm de `ambiente` (por padrão, `backend/.env` + variáveis de ambiente, onde
`carregar_segredos_colab` também as coloca). Nenhum valor aparece em mensagem.
"""

import os
import sys
from typing import Literal, Mapping

from guardiao.canal.simulado import CanalSimulado
from guardiao.config import carregar_env

Modo = Literal["demonstracao", "real"]
MODOS: tuple[str, ...] = ("demonstracao", "real")
# polling curto: `fechar()` (rodar a célula de novo, encerrar) espera no máximo ~20 s
ESPERA_POLLING_DEMONSTRACAO = 5


def _ler(ambiente: Mapping[str, str], nome: str) -> str | None:
    valor = (ambiente.get(nome) or "").strip()
    return valor or None


def _exigir(ambiente: Mapping[str, str], nome: str) -> str:
    valor = _ler(ambiente, nome)
    if valor is None:
        raise RuntimeError(f"variável {nome} ausente (Secrets do Colab ou backend/.env)")
    return valor


def criar_canal(modo: str, ambiente: Mapping[str, str] | None = None):
    """Cria o canal do modo pedido. Não acessa a rede: o bot só é chamado depois."""
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo!r} (use {' ou '.join(MODOS)})")
    if ambiente is None:
        carregar_env()
        ambiente = os.environ
    token = _ler(ambiente, "TELEGRAM_BOT_TOKEN")

    if modo == "demonstracao":
        if token is None:
            print(
                "[canal] aviso: TELEGRAM_BOT_TOKEN ausente; modo demonstração sem bot "
                "(os alertas à responsável não saem)",
                file=sys.stderr,
            )
            return CanalSimulado(saida=None)
        from guardiao.canal.telegram import TelegramCanal

        bot = TelegramCanal(
            None, None, token, usar_conta=False, usar_bot=True, espera_polling=ESPERA_POLLING_DEMONSTRACAO
        )
        return CanalSimulado(saida=bot)

    from guardiao.canal.telegram import TelegramCanal

    try:
        api_id = int(_exigir(ambiente, "TELEGRAM_API_ID"))
    except ValueError:
        raise RuntimeError("TELEGRAM_API_ID não é numérico") from None
    api_hash = _exigir(ambiente, "TELEGRAM_API_HASH")
    token = _exigir(ambiente, "TELEGRAM_BOT_TOKEN")
    return TelegramCanal(api_id, api_hash, token)
