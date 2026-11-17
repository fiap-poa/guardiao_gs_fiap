"""Canal simulado (modo demonstração).

Outra implementação do contrato `Canal`. A "conta da pessoa idosa" é feita de dados
fictícios (`cenarios.py`, DDD 00): contatos, conversas antigas e os cinco cenários, que
são injetados por `injetar`/`injetar_mensagem`. A injeção chama o handler na thread de
quem injeta, com os mesmos objetos que o canal Telegram entrega: em grupo, só o tipo.

Saída: o alerta à responsável e qualquer aviso a outro destinatário vão para `saida`
(no modo demonstração, um `TelegramCanal` só do bot). O aviso à pessoa idosa aparece no
celular simulado (`celular()`), e nada sai pelo bot. Sem `saida`, `enviar_alerta` levanta
`SemSaida` e nada toca a rede.

Este módulo não importa o Telegram: a fábrica (`fabrica.py`) monta a saída.
"""

import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from guardiao.canal.base import (
    Alerta,
    Contato,
    ConversaAntiga,
    Handler,
    InicioBot,
    MensagemRecebida,
    Recebido,
    RespostaAlerta,
)
from guardiao.canal.cenarios import (
    CONTATOS,
    CONVERSAS_ANTIGAS,
    ID_IDOSA,
    NOME_IDOSA,
    obter_cenario,
)

NOME_GUARDIAO = "Guardião da Família"


class SemSaida(RuntimeError):
    """O canal simulado foi criado sem bot: não há como alertar a responsável."""


class Saida(Protocol):
    """O que o canal simulado usa do `TelegramCanal` (só o bot)."""

    def receber_mensagens(self, handler: Handler) -> None: ...

    def enviar_alerta(self, alerta: Alerta) -> str: ...

    def enviar_aviso(self, destinatario, texto: str) -> str: ...

    def info_bot(self) -> dict: ...

    def fechar(self) -> None: ...


@dataclass(frozen=True)
class MensagemCelular:
    """Uma linha do celular simulado da pessoa idosa.

    `tipo="recebida"`: mensagem injetada (o que ela veria no mensageiro);
    `tipo="aviso"`: aviso do Guardião a ela.
    """

    tipo: Literal["recebida", "aviso"]
    de: str
    conversa_id: str
    texto: str
    em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _avisar(texto: str) -> None:
    print(f"[canal simulado] {texto}", file=sys.stderr)


class CanalSimulado:
    """Implementação simulada do contrato `Canal`."""

    id_idosa = ID_IDOSA
    nome_idosa = NOME_IDOSA

    def __init__(self, saida: Saida | None = None):
        self._saida = saida
        self._handler: Handler | None = None
        self._celular: list[MensagemCelular] = []
        self._trava = threading.Lock()
        self._avisos = 0

    def __repr__(self) -> str:
        return f"CanalSimulado(bot={'sim' if self._saida is not None else 'não'})"

    @property
    def tem_bot(self) -> bool:
        return self._saida is not None

    @property
    def saida(self) -> Saida | None:
        """O bot usado como saída (`TelegramCanal` só do bot), ou `None`."""
        return self._saida

    # ------------------------------------------------------------- contrato Canal

    def receber_mensagens(self, handler: Handler) -> None:
        """Guarda o handler das injeções e, com bot, liga o polling dele (`/start` e toques)."""
        self._handler = handler
        if self._saida is not None:
            self._saida.receber_mensagens(handler)

    def enviar_alerta(self, alerta: Alerta) -> str:
        if self._saida is None:
            raise SemSaida("modo demonstração sem bot: defina TELEGRAM_BOT_TOKEN para alertar a responsável")
        return self._saida.enviar_alerta(alerta)

    # ------------------------------------------------------------- extras (como no TelegramCanal)

    def conectar(self) -> str:
        """A conta simulada já está "conectada": devolve o id da pessoa idosa."""
        return self.id_idosa

    def info_bot(self) -> dict | None:
        """`{"id", "username"}` do bot da saída; sem saída, `None` (e nada toca a rede)."""
        if self._saida is None:
            return None
        return self._saida.info_bot()

    def enviar_start_ao_bot(self) -> None:
        """Simula a conta da pessoa idosa tocando Iniciar: entrega o `InicioBot` dela ao handler.

        Roda nesta thread, como a injeção. Nada sai pelo bot.
        """
        if self._handler is None:
            raise RuntimeError("chame receber_mensagens(handler) antes de enviar o /start")
        self._entregar(InicioBot(usuario_id=self.id_idosa, destinatario=self.id_idosa))

    def enviar_aviso(self, destinatario, texto: str) -> str:
        """Pessoa idosa → celular simulado; qualquer outro destinatário → bot."""
        if destinatario == self.id_idosa:
            with self._trava:
                self._avisos += 1
                numero = self._avisos
                self._celular.append(MensagemCelular("aviso", NOME_GUARDIAO, self.id_idosa, texto))
            return f"sim:aviso-{numero}"
        if self._saida is None:
            raise SemSaida("modo demonstração sem bot: não há como enviar aviso a outro destinatário")
        return self._saida.enviar_aviso(destinatario, texto)

    def listar_contatos(self) -> list[Contato]:
        return list(CONTATOS)

    def conversas_existentes(self) -> list[ConversaAntiga]:
        """Conversas que já existiam antes do pareamento (privadas e o grupo)."""
        return list(CONVERSAS_ANTIGAS)

    def celular(self) -> list[MensagemCelular]:
        """Tudo o que apareceu no celular simulado, na ordem."""
        with self._trava:
            return list(self._celular)

    def fechar(self) -> None:
        self._handler = None
        if self._saida is not None:
            self._saida.fechar()

    # ------------------------------------------------------------- injeção

    def injetar_mensagem(
        self,
        remetente_id: str,
        texto: str,
        tipo: Literal["privada", "grupo"] = "privada",
        conversa_id: str | None = None,
        de: str | None = None,
    ) -> MensagemRecebida:
        """Faz uma mensagem chegar à conta simulada e a entrega ao handler (nesta thread).

        Em conversa privada, `conversa_id` é o próprio remetente. Em grupo, `conversa_id` é
        obrigatório e o handler recebe só `MensagemRecebida(tipo="grupo")`.
        """
        if self._handler is None:
            raise RuntimeError("chame receber_mensagens(handler) antes de injetar")
        if tipo == "privada":
            conversa = conversa_id or remetente_id
            mensagem = MensagemRecebida(
                tipo="privada", remetente_id=remetente_id, conversa_id=conversa, texto=texto or None
            )
        elif tipo == "grupo":
            if not conversa_id:
                raise ValueError("mensagem de grupo precisa de conversa_id")
            conversa = conversa_id
            mensagem = MensagemRecebida(tipo="grupo")
        else:
            raise ValueError(f"tipo de conversa inválido: {tipo!r}")
        with self._trava:
            self._celular.append(MensagemCelular("recebida", de or remetente_id, conversa, texto))
        self._entregar(mensagem)
        return mensagem

    def _entregar(self, evento: Recebido) -> None:
        handler = self._handler
        try:
            handler(evento)
        except Exception as erro:  # como no canal Telegram: o tipo basta
            _avisar(f"handler falhou: {type(erro).__name__}")

    def injetar(self, cenario_id: str) -> list[MensagemRecebida]:
        """Injeta as mensagens de um cenário e devolve o que o handler recebeu."""
        cenario = obter_cenario(cenario_id)
        tipo = "grupo" if cenario.origem == "grupo" else "privada"
        return [
            self.injetar_mensagem(
                cenario.remetente_id,
                texto,
                tipo=tipo,
                conversa_id=cenario.conversa_id,
                de=cenario.remetente_nome,
            )
            for texto in cenario.mensagens
        ]


# --------------------------------------------------------------------------- exibição


def descrever_recebido(evento: Recebido) -> str:
    """Uma linha legível do que o handler recebeu (para o notebook).

    Mensagens simuladas mostram remetente e texto (são fictícios). Eventos do bot vêm de
    contas reais do Telegram: saem sem id de usuário.
    """
    if isinstance(evento, MensagemRecebida):
        if evento.tipo == "grupo":
            return "MensagemRecebida(tipo=grupo) (sem remetente nem texto)"
        if not str(evento.remetente_id).startswith("sim:"):
            return "MensagemRecebida(tipo=privada) (conta real: texto omitido)"
        return f'MensagemRecebida(tipo=privada, de={evento.remetente_id}): "{evento.texto or ""}"'
    if isinstance(evento, InicioBot):
        return "InicioBot (alguém tocou Iniciar no bot)"
    if isinstance(evento, RespostaAlerta):
        return f"RespostaAlerta(caso={evento.caso_id}, resposta={evento.resposta})"
    return type(evento).__name__


def formatar_celular(linhas: list[MensagemCelular], nome_idosa: str = NOME_IDOSA) -> str:
    """O celular simulado como texto."""
    saida = [f"Celular de {nome_idosa}"]
    if not linhas:
        saida.append("  (nada por enquanto)")
    for linha in linhas:
        hora = linha.em.astimezone().strftime("%H:%M")
        marca = ">>" if linha.tipo == "aviso" else "  "
        saida.append(f"{marca} [{hora}] {linha.de}: {linha.texto}")
    return "\n".join(saida)
