"""Filtro de contato novo (CAP-2).

Decide, para cada mensagem que chega à conta da pessoa idosa, se ela vai para a análise
ou é descartada. A decisão olha só `tipo` e `remetente_id`: o texto nunca é lido,
guardado nem logado aqui.

- No pareamento, os remetentes das conversas privadas que já existiam (e o bot do
  Guardião) viram **conhecidos**.
- Grupo e conhecido: descarte.
- Remetente sem conversa no pareamento é **contato novo**, mesmo que esteja salvo nos
  contatos: passa a **observado** e vai para a análise por 7 dias, contados da primeira
  mensagem. Passados 7 dias sem alerta, a mensagem seguinte o torna conhecido (e é
  descartada). Com alerta registrado, ele continua observado até ser liberado.

Estado em memória: reiniciar o processo refaz o pareamento.
"""

import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

from guardiao.canal.base import ConversaAntiga, MensagemRecebida

OBSERVACAO = timedelta(days=7)

Acao = Literal["analisar", "descartar"]
Motivo = Literal["contato_novo", "observado", "grupo", "conhecido", "sem_remetente", "observacao_encerrada"]
Situacao = Literal["conhecido", "observado", "desconhecido"]


class SemPareamento(RuntimeError):
    """`classificar` antes de `registrar_pareamento`: sem a base de conhecidos, nada é decidido."""


@dataclass(frozen=True)
class Decisao:
    """O que fazer com uma mensagem, e por quê. Não carrega remetente nem texto."""

    acao: Acao
    motivo: Motivo

    @property
    def analisar(self) -> bool:
        return self.acao == "analisar"


def _chave(remetente_id) -> str:
    # ids do Telegram são inteiros e os simulados são texto; a chave é sempre texto
    return str(remetente_id)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class FiltroContatos:
    """Base de contatos conhecidos e observados da pessoa idosa."""

    def __init__(self, observacao: timedelta = OBSERVACAO):
        self._observacao = observacao
        self._trava = threading.Lock()
        self._pareado = False
        self._conhecidos: set[str] = set()
        self._observados: dict[str, datetime] = {}  # remetente → primeira mensagem
        self._com_alerta: set[str] = set()
        self._motivos: Counter = Counter()

    def __repr__(self) -> str:
        contagens = self.contagens()
        return f"FiltroContatos(conhecidos={contagens['conhecidos']}, observados={contagens['observados']})"

    @property
    def pareado(self) -> bool:
        return self._pareado

    # ------------------------------------------------------------- pareamento

    def registrar_pareamento(self, conversas: Iterable[ConversaAntiga], extras: Iterable = ()) -> int:
        """Torna conhecidos os remetentes das conversas privadas existentes e os `extras`
        (o id do bot). Grupos não entram. Devolve quantos conhecidos há.
        """
        novos = {_chave(c.conversa_id) for c in conversas if c.tipo == "privada" and c.conversa_id is not None}
        novos |= {_chave(e) for e in extras if e is not None}
        with self._trava:
            self._conhecidos |= novos
            for chave in novos:
                self._observados.pop(chave, None)
                self._com_alerta.discard(chave)
            self._pareado = True
            return len(self._conhecidos)

    # ------------------------------------------------------------- decisão

    def classificar(self, msg: MensagemRecebida, agora: datetime | None = None) -> Decisao:
        """`analisar` para contato novo ou observado; `descartar` para o resto.

        Lê só `msg.tipo` e `msg.remetente_id`.
        """
        if not self._pareado:
            raise SemPareamento("registre o pareamento antes de classificar mensagens")
        agora = agora or _agora()
        with self._trava:
            decisao = self._decidir(msg.tipo, msg.remetente_id, agora)
            self._motivos[decisao.motivo] += 1
            return decisao

    def _decidir(self, tipo, remetente_id, agora: datetime) -> Decisao:
        if tipo != "privada":
            return Decisao("descartar", "grupo")
        if remetente_id is None:
            return Decisao("descartar", "sem_remetente")
        chave = _chave(remetente_id)
        if chave in self._conhecidos:
            return Decisao("descartar", "conhecido")
        primeira = self._observados.get(chave)
        if primeira is None:
            self._observados[chave] = agora
            return Decisao("analisar", "contato_novo")
        if agora - primeira >= self._observacao and chave not in self._com_alerta:
            self._tornar_conhecido(chave)
            return Decisao("descartar", "observacao_encerrada")
        return Decisao("analisar", "observado")

    def _tornar_conhecido(self, chave: str) -> None:
        self._observados.pop(chave, None)
        self._com_alerta.discard(chave)
        self._conhecidos.add(chave)

    # ------------------------------------------------------------- ajustes (histórias 5 e 6)

    def marcar_conhecido(self, remetente_id) -> None:
        """Passa a descartar as mensagens deste remetente."""
        with self._trava:
            self._tornar_conhecido(_chave(remetente_id))

    def registrar_alerta(self, remetente_id) -> None:
        """Houve alerta para este contato: ele continua observado depois dos 7 dias."""
        chave = _chave(remetente_id)
        with self._trava:
            if chave not in self._conhecidos:
                self._com_alerta.add(chave)

    def liberar(self, remetente_id) -> bool:
        """Resposta "Era ele mesmo": encerra a análise do contato, que vira conhecido.

        Devolve se ele estava observado.
        """
        chave = _chave(remetente_id)
        with self._trava:
            estava = chave in self._observados
            self._tornar_conhecido(chave)
            return estava

    # ------------------------------------------------------------- consulta

    def situacao(self, remetente_id) -> Situacao:
        chave = _chave(remetente_id)
        with self._trava:
            if chave in self._conhecidos:
                return "conhecido"
            if chave in self._observados:
                return "observado"
            return "desconhecido"

    def contagens(self) -> dict:
        """Tamanhos da base e quantas decisões houve por motivo (sem ids)."""
        with self._trava:
            analisar = self._motivos["contato_novo"] + self._motivos["observado"]
            return {
                "conhecidos": len(self._conhecidos),
                "observados": len(self._observados),
                "com_alerta": len(self._com_alerta),
                "analisadas": analisar,
                "descartadas": sum(self._motivos.values()) - analisar,
                "por_motivo": dict(self._motivos),
            }
