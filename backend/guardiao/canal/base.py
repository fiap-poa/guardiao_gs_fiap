"""Contrato da camada de canal.

O resto do backend fala com o mensageiro só por este contrato:
- `receber_mensagens(handler)`: entrega ao handler tudo o que chega pelo canal —
  `MensagemRecebida` (conta da pessoa idosa), `InicioBot` (alguém tocou Iniciar no bot)
  e `RespostaAlerta` (toque num botão do alerta);
- `enviar_alerta(alerta) -> id`: manda o alerta com os botões [É golpe] [Era ele mesmo].

O núcleo do Guardião (`recepcao.py`) usa também os extras de `CanalConectavel`.
Ids de usuário e de conversa são opacos para quem usa o canal.
"""

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol, Union

TipoConversa = Literal["privada", "grupo"]
Resposta = Literal["golpe", "era_ele_mesmo"]

ROTULOS_BOTOES: dict[str, str] = {"golpe": "É golpe", "era_ele_mesmo": "Era ele mesmo"}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class MensagemRecebida:
    """Mensagem que chegou à conta da pessoa idosa.

    Em grupos e canais só o tipo é preenchido: remetente, conversa e texto ficam `None`.
    """

    tipo: TipoConversa
    remetente_id: int | str | None = None
    conversa_id: int | str | None = None
    texto: str | None = field(default=None, repr=False)
    recebida_em: datetime = field(default_factory=_agora)

    @property
    def tem_texto(self) -> bool:
        return bool(self.texto)


@dataclass(frozen=True)
class InicioBot:
    """Alguém tocou Iniciar (`/start`) no bot; `destinatario` serve para `Alerta.destinatario`.

    `parametro` é o que veio depois do `/start` (o código do link `?start=<código>`), e
    `nome` é o primeiro nome da conta que tocou Iniciar. Os dois ficam fora do `repr`.
    """

    usuario_id: int | str
    destinatario: int | str
    recebido_em: datetime = field(default_factory=_agora)
    parametro: str | None = field(default=None, repr=False)
    nome: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Alerta:
    """Alerta à responsável (message-templates.md, CAP-5)."""

    destinatario: int | str
    caso_id: str
    nome_alegado: str
    como_chama_idosa: str
    trecho: str
    numero_verdadeiro: str | None = None


@dataclass(frozen=True)
class RespostaAlerta:
    """Toque da responsável num botão do alerta."""

    alerta_id: str
    caso_id: str
    resposta: Resposta
    respondente_id: int | str
    respondida_em: datetime = field(default_factory=_agora)


@dataclass(frozen=True)
class ConversaAntiga:
    """Conversa que já existia na conta da pessoa idosa antes do pareamento.

    Em conversa privada, `conversa_id` é igual ao id do remetente (como no Telegram).
    O canal real não preenche `nome` nem `iniciada_em`: o filtro só usa id e tipo.
    """

    conversa_id: int | str
    tipo: TipoConversa
    nome: str = field(default="", repr=False)
    iniciada_em: datetime | None = None


@dataclass(frozen=True)
class Contato:
    """Contato salvo na conta da pessoa idosa. `telefone` pode faltar."""

    id: int | str
    nome: str
    telefone: str | None


Recebido = Union[MensagemRecebida, InicioBot, RespostaAlerta]
Handler = Callable[[Recebido], None]


class Canal(Protocol):
    def receber_mensagens(self, handler: Handler) -> None:
        """Passa a entregar ao handler tudo o que chega. Retorna logo; o handler roda em outra thread."""
        ...

    def enviar_alerta(self, alerta: Alerta) -> str:
        """Envia o alerta com os dois botões e devolve o id do alerta enviado."""
        ...


class CanalConectavel(Canal, Protocol):
    """O que o núcleo do Guardião (`recepcao.Guardiao`) usa do canal, além do contrato `Canal`."""

    def conectar(self) -> int | str:
        """Conecta a conta da pessoa idosa e devolve o id dela."""
        ...

    def conversas_existentes(self) -> list[ConversaAntiga]:
        """Conversas que já existem na conta (privadas e grupos), para o pareamento."""
        ...

    def info_bot(self) -> dict | None:
        """`{"id", "username"}` do bot do Guardião, ou `None` se o canal não tem bot."""
        ...

    def enviar_start_ao_bot(self) -> None:
        """A conta da pessoa idosa manda `/start` ao bot (o `InicioBot` chega ao handler)."""
        ...

    def enviar_aviso(self, destinatario, texto: str) -> str:
        """Mensagem simples do bot (sem botões) a quem já tocou Iniciar."""
        ...

    def fechar(self) -> None: ...


def texto_alerta(alerta: Alerta) -> str:
    """Monta o texto do alerta a partir do modelo de message-templates.md."""
    linhas = [
        f"Um número novo está dizendo ser {alerta.nome_alegado} e pediu dinheiro "
        f"para {alerta.como_chama_idosa}.",
        f'Mensagem recebida: "{alerta.trecho}".',
    ]
    if alerta.numero_verdadeiro:
        linhas.append(
            f"O número salvo nos contatos para esse nome é {alerta.numero_verdadeiro}. "
            "Ligue para esse número antes de qualquer coisa."
        )
    else:
        linhas.append("Não achei esse nome nos contatos. Confirme com a família antes de qualquer coisa.")
    return "\n".join(linhas)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.lower().split())


def procurar_contatos(contatos: list[Contato], nome: str) -> list[Contato]:
    """Contatos cujo nome contém todas as palavras buscadas (sem caixa e sem acento)."""
    palavras = _normalizar(nome).split()
    if not palavras:
        return []
    achados = []
    for contato in contatos:
        partes = _normalizar(contato.nome).split()
        if all(palavra in partes for palavra in palavras):
            achados.append(contato)
    return achados
