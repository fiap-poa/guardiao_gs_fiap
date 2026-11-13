"""Camada de canal. Só este pacote conversa com o mensageiro.

Importe a implementação explicitamente (`guardiao.canal.telegram`) para que o contrato
em `base` não carregue as bibliotecas do Telegram.
"""

from guardiao.canal.base import (
    Alerta,
    Canal,
    Contato,
    Handler,
    InicioBot,
    MensagemRecebida,
    Recebido,
    RespostaAlerta,
    procurar_contatos,
    texto_alerta,
)

__all__ = [
    "Alerta",
    "Canal",
    "Contato",
    "Handler",
    "InicioBot",
    "MensagemRecebida",
    "Recebido",
    "RespostaAlerta",
    "procurar_contatos",
    "texto_alerta",
]
