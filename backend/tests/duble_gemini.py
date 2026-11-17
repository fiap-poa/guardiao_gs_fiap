"""Dublês do Gemini para os testes (nenhum acessa a rede).

- `DubleRegras`: responde como o Gemini responderia, por regras simples de palavras-chave
  sobre o conteúdo que recebeu. Serve para testar a janela, a validação, a regra da
  suspeita e a busca de ponta a ponta. Guarda cada pedido para inspeção.
- `DubleFixo`: devolve sempre a mesma resposta (ou levanta a exceção dada).
"""

import json
import re

_LINHA = re.compile(r"^\[(\d+)\] (.*)$")
_CHAMADO = re.compile(r"\b(?:oi|olá)\s+(vó|vovó|mãe|mae)\b", re.IGNORECASE)
_NOME = re.compile(r"\bé (o|a) ([A-ZÁÉÍÓÚÂÊÔÃÕ][a-záéíóúâêôãõç]+)")
_NETO_SEM_NOME = re.compile(r"\bseu (neto|neta|filho|filha)\b", re.IGNORECASE)
_FORMAS = (
    ("pix", re.compile(r"\bpix\b", re.IGNORECASE)),
    ("transferencia", re.compile(r"\btransfer[êe]ncia\b", re.IGNORECASE)),
    ("conta_ou_boleto", re.compile(r"\bboleto\b", re.IGNORECASE)),
    ("nao_especificada", re.compile(r"\b(deposite|dep[óo]sito|empresta)\b", re.IGNORECASE)),
)
_PEDIDO = re.compile(r"\b(preciso|consegue|paga|pague|empresta|deposite|faz|fazer)\b", re.IGNORECASE)


def _mensagens(conteudo: str) -> list[str]:
    linhas = conteudo.strip().splitlines()
    assert linhas[0] == "<conversa>" and linhas[-1] == "</conversa>", "conteúdo fora dos delimitadores"
    mensagens = []
    for linha in linhas[1:-1]:
        casado = _LINHA.match(linha)
        assert casado and int(casado.group(1)) == len(mensagens) + 1, "mensagens fora de ordem"
        mensagens.append(casado.group(2))
    return mensagens


def responder_por_regras(conteudo: str) -> dict:
    mensagens = _mensagens(conteudo)
    conversa = " ".join(mensagens)
    chamado = _CHAMADO.search(conversa)
    nome = _NOME.search(conversa)
    sem_nome = _NETO_SEM_NOME.search(conversa)
    alega = bool(chamado and (nome or sem_nome))
    parentesco = None
    if alega:
        if sem_nome:
            parentesco = sem_nome.group(1).lower()
        else:
            feminino = nome.group(1) == "a"
            vo = chamado.group(1).lower() in ("vó", "vovó")
            parentesco = ("neta" if feminino else "neto") if vo else ("filha" if feminino else "filho")
    forma, indice = None, None
    for numero, mensagem in enumerate(mensagens, start=1):
        if not _PEDIDO.search(mensagem):
            continue
        for rotulo, padrao in _FORMAS:
            if padrao.search(mensagem):
                forma, indice = rotulo, numero
                break
        if forma:
            break
    return {
        "alega_parentesco": alega,
        "nome_alegado": nome.group(2) if nome else None,
        "parentesco": parentesco,
        "pede_dinheiro": forma is not None,
        "forma_pagamento": forma,
        "motivo": "motivo do teste" if forma else None,
        "mensagem_do_pedido": indice,
    }


class DubleRegras:
    modelo = "dublê-por-regras"

    def __init__(self):
        self.pedidos: list[dict] = []

    def gerar_json(self, instrucao: str, conteudo: str, esquema: dict) -> str:
        self.pedidos.append({"instrucao": instrucao, "conteudo": conteudo, "esquema": esquema})
        return json.dumps(responder_por_regras(conteudo), ensure_ascii=False)


class DubleFixo:
    modelo = "dublê-fixo"

    def __init__(self, resposta=None, erro: Exception | None = None):
        self.resposta = resposta
        self.erro = erro
        self.pedidos: list[str] = []

    def gerar_json(self, instrucao: str, conteudo: str, esquema: dict) -> str:
        self.pedidos.append(conteudo)
        if self.erro is not None:
            raise self.erro
        if isinstance(self.resposta, dict):
            return json.dumps(self.resposta)
        return self.resposta
