"""Cadastro da responsável pelo Iniciar com código de uso único (CAP-7).

O bot é privado. A tela mostra um link do bot com um código (`?start=<código>`); quem toca
Iniciar por esse link fica cadastrada como responsável. Iniciar sem código, com código já
usado, vencido ou inventado recebe a mensagem de bot privado e não cadastra ninguém.

- O código tem 22 caracteres (`secrets.token_urlsafe(16)`, válido como payload do
  `/start`) e vale 30 minutos. Vários podem coexistir até o cadastro, que invalida todos.
- `codigo_vigente()` (a tela) reaproveita o código válido enquanto faltarem mais de 5
  minutos para ele vencer: a atualização periódica da tela não gera um código a cada pedido.
  O uso único não muda: o cadastro invalida todos.
- Uma responsável só: depois do cadastro, `gerar_codigo` falha, e um novo Iniciar dela sem
  código repete o "Pronto" sem mudar nada.

Textos de message-templates.md. Estado em memória.
"""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from guardiao.canal.base import InicioBot

VALIDADE_CODIGO = timedelta(minutes=30)
MARGEM_CODIGO = timedelta(minutes=5)  # com menos que isso para vencer, a tela ganha um código novo
TEXTO_BOT_PRIVADO = "Este bot é privado. Para usar o Guardião, abra o link mostrado na tela de configuração."

MotivoInicio = Literal[
    "cadastrada", "ja_cadastrada", "sem_codigo", "codigo_usado", "codigo_vencido", "codigo_invalido"
]


class JaCadastrada(RuntimeError):
    """A responsável já está cadastrada: não há mais código a gerar."""


def texto_pronto(nome_responsavel: str | None, nome_idosa: str) -> str:
    """ "Pronto, {nome}. Você vai receber aqui os alertas do Guardião sobre {idosa}." """
    saudacao = f"Pronto, {nome_responsavel}." if nome_responsavel else "Pronto."
    return f"{saudacao} Você vai receber aqui os alertas do Guardião sobre {nome_idosa}."


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Responsavel:
    """Quem recebe os alertas. `destinatario` serve para `Alerta.destinatario`."""

    usuario_id: int | str = field(repr=False)
    destinatario: int | str = field(repr=False)
    nome: str | None = field(repr=False)
    cadastrada_em: datetime


@dataclass(frozen=True)
class ResultadoInicio:
    """O que fazer com um Iniciar: responder `resposta` a `destinatario` pelo bot."""

    cadastrou: bool
    motivo: MotivoInicio
    destinatario: int | str | None = field(repr=False)
    resposta: str = field(repr=False)


class CadastroResponsavel:
    """Códigos de uso único e a responsável cadastrada."""

    def __init__(
        self,
        nome_idosa: str,
        relogio: Callable[[], datetime] = _agora,
        validade: timedelta = VALIDADE_CODIGO,
    ):
        self._nome_idosa = nome_idosa
        self._relogio = relogio
        self._validade = validade
        self._trava = threading.Lock()
        self._codigos: dict[str, datetime] = {}  # código → vence em
        self._usados: set[str] = set()  # invalidados pelo cadastro
        self._responsavel: Responsavel | None = None

    def __repr__(self) -> str:
        return f"CadastroResponsavel(cadastrada={'sim' if self.cadastrada else 'não'})"

    @property
    def cadastrada(self) -> bool:
        return self._responsavel is not None

    @property
    def responsavel(self) -> Responsavel | None:
        return self._responsavel

    # ------------------------------------------------------------- código e link

    def gerar_codigo(self) -> str:
        """Novo código de uso único, válido por 30 min. Falha depois do cadastro."""
        with self._trava:
            return self._novo_codigo()

    def codigo_vigente(self, margem: timedelta = MARGEM_CODIGO) -> str:
        """O código válido que vence por último, se faltar mais que `margem`; senão, um novo.

        Falha depois do cadastro, como `gerar_codigo`.
        """
        with self._trava:
            if self._responsavel is not None:
                raise JaCadastrada("a responsável já está cadastrada")
            agora = self._relogio()
            self._descartar_vencidos(agora)
            if self._codigos:
                codigo, vence = max(self._codigos.items(), key=lambda item: item[1])
                if vence - agora > margem:
                    return codigo
            return self._novo_codigo()

    def _novo_codigo(self) -> str:
        """Chamado sob a trava."""
        if self._responsavel is not None:
            raise JaCadastrada("a responsável já está cadastrada")
        agora = self._relogio()
        self._descartar_vencidos(agora)
        codigo = secrets.token_urlsafe(16)
        self._codigos[codigo] = agora + self._validade
        return codigo

    def link(self, usuario_bot: str, codigo: str | None = None) -> str:
        """Link do bot com o código (`t.me/<bot>?start=<código>`); gera um código se faltar."""
        usuario = (usuario_bot or "").lstrip("@")
        if not usuario:
            raise ValueError("o bot não tem username")
        return f"https://t.me/{usuario}?start={codigo or self.gerar_codigo()}"

    def _descartar_vencidos(self, agora: datetime) -> None:
        for codigo, vence in list(self._codigos.items()):
            if agora >= vence:
                del self._codigos[codigo]

    # ------------------------------------------------------------- Iniciar

    def tratar_inicio(self, inicio: InicioBot) -> ResultadoInicio:
        """Cadastra com código válido; qualquer outro Iniciar recebe a mensagem de bot privado."""
        codigo = inicio.parametro or None
        with self._trava:
            agora = self._relogio()
            atual = self._responsavel
            if atual is not None:
                if codigo is None and inicio.usuario_id == atual.usuario_id:
                    return self._pronto(atual, "ja_cadastrada", cadastrou=False)
                if codigo is None:
                    return self._privado(inicio, "sem_codigo")
                return self._privado(inicio, "codigo_usado" if codigo in self._usados else "codigo_invalido")
            if codigo is None:
                return self._privado(inicio, "sem_codigo")
            if codigo in self._usados:
                return self._privado(inicio, "codigo_usado")
            vence = self._codigos.get(codigo)
            if vence is None:
                return self._privado(inicio, "codigo_invalido")
            if agora >= vence:
                del self._codigos[codigo]
                return self._privado(inicio, "codigo_vencido")
            self._responsavel = Responsavel(
                usuario_id=inicio.usuario_id,
                destinatario=inicio.destinatario,
                nome=inicio.nome,
                cadastrada_em=agora,
            )
            self._usados |= set(self._codigos)  # o cadastro invalida todos os códigos
            self._codigos.clear()
            return self._pronto(self._responsavel, "cadastrada", cadastrou=True)

    def _pronto(self, responsavel: Responsavel, motivo: MotivoInicio, cadastrou: bool) -> ResultadoInicio:
        texto = texto_pronto(responsavel.nome, self._nome_idosa)
        return ResultadoInicio(cadastrou, motivo, responsavel.destinatario, texto)

    @staticmethod
    def _privado(inicio: InicioBot, motivo: MotivoInicio) -> ResultadoInicio:
        return ResultadoInicio(False, motivo, inicio.destinatario, TEXTO_BOT_PRIVADO)

    # ------------------------------------------------------------- estado

    def estado(self) -> dict:
        with self._trava:
            self._descartar_vencidos(self._relogio())
            return {
                "responsavel_cadastrada": self._responsavel is not None,
                "codigos_validos": len(self._codigos),
            }
