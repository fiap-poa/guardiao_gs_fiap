"""Núcleo do Guardião: recepção, filtro e cadastro sobre a camada de canal (CAP-1, CAP-2, CAP-7).

`Guardiao(canal).conectar()`:

1. conecta a conta da pessoa idosa (`canal.conectar()`, que devolve o id dela);
2. pareamento: os remetentes das conversas privadas existentes e o bot viram conhecidos;
3. liga a recepção (`canal.receber_mensagens(guardiao.tratar)`);
4. manda o `/start` automático pela conta da pessoa idosa, para o bot poder avisá-la.

Depois, `tratar(evento)` recebe tudo o que o canal entrega:

- `MensagemRecebida`: o filtro decide; só a de contato novo/observado vai a `ao_analisar`
  e ao `analisador` (Gemini e busca do parente, CAP-3 e CAP-4). Grupo e conhecido são
  descartados sem ler o texto e sem log;
- `InicioBot`: o da pessoa idosa (reconhecida pelo id da conta) só a habilita, sem
  resposta do bot; o de qualquer outra pessoa vai ao cadastro, e a resposta sai pelo bot;
- `RespostaAlerta`: o toque da responsável cadastrada vai a `ao_responder` e à gestão de
  casos (`casos.py`), que decide o desfecho.

Com `analisador`, cada suspeita abre um caso (`self.casos`): o alerta com os botões vai
pelo canal à responsável cadastrada; "É golpe" e o prazo sem resposta (10 min) avisam a
pessoa idosa; "Era ele mesmo" libera o contato. Sem responsável ou com falha no envio, a
exceção sobe ao `Analisador`, que reanalisa na próxima mensagem.

O núcleo fala com o mensageiro só pela camada de canal. Erros logam só o tipo.
"""

import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from guardiao.analise import Analisador, ResultadoAnalise
from guardiao.cadastro import CadastroResponsavel, ResultadoInicio
from guardiao.casos import PRAZO_RESPOSTA, VARREDURA_S, GestorCasos, RepositorioCasos
from guardiao.canal.base import CanalConectavel, InicioBot, MensagemRecebida, Recebido, RespostaAlerta
from guardiao.filtro import Decisao, FiltroContatos

NOME_IDOSA_PADRAO = "a pessoa idosa"


class SemBot(RuntimeError):
    """O canal não tem bot (modo demonstração sem `TELEGRAM_BOT_TOKEN`)."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _avisar(texto: str) -> None:
    print(f"[guardião] {texto}", file=sys.stderr)


class RelogioAjustavel:
    """Relógio que pode ser adiantado: a demonstração dos 7 dias sem esperar 7 dias."""

    def __init__(self, base: Callable[[], datetime] = _agora):
        self._base = base
        self.deslocamento = timedelta(0)

    def __call__(self) -> datetime:
        return self._base() + self.deslocamento

    def adiantar(self, dias: float = 0, **outros) -> None:
        self.deslocamento += timedelta(days=dias, **outros)

    def voltar(self) -> None:
        self.deslocamento = timedelta(0)


class Guardiao:
    """Recebe o que chega pelo canal e decide o que segue para a análise."""

    def __init__(
        self,
        canal: CanalConectavel,
        nome_idosa: str | None = None,
        relogio: Callable[[], datetime] = _agora,
        ao_analisar: Callable[[MensagemRecebida], None] | None = None,
        ao_responder: Callable[[RespostaAlerta], None] | None = None,
        analisador: Analisador | None = None,
        prazo_resposta: timedelta = PRAZO_RESPOSTA,
        casos_arquivo: Path | str | None = None,
        como_chama_idosa: str | None = None,
        varredura_casos_s: float | None = VARREDURA_S,
    ):
        """`casos_arquivo=None` guarda os casos só em memória; o notebook usa `backend/.local/`.

        `como_chama_idosa` é como a responsável chama a pessoa idosa no alerta ("sua mãe");
        o padrão é o nome dela.
        """
        self.canal = canal
        self.nome_idosa = nome_idosa or getattr(canal, "nome_idosa", None) or NOME_IDOSA_PADRAO
        self._relogio = relogio
        self.filtro = FiltroContatos()
        self.cadastro = CadastroResponsavel(self.nome_idosa, relogio=relogio)
        self.ao_analisar = ao_analisar
        self.ao_responder = ao_responder
        self.analisador = analisador
        self._trava = threading.Lock()
        self._id_idosa = None
        self._destinatario_idosa = None
        self._bot: dict | None = None
        self._conectado = False
        self._idosa_habilitada = False
        self.casos = GestorCasos(
            canal,
            RepositorioCasos(casos_arquivo),
            relogio=relogio,
            prazo=prazo_resposta,
            responsavel=lambda: self.cadastro.responsavel,
            destinatario_idosa=self._para_idosa,
            nome_idosa=self.nome_idosa,
            como_chama_idosa=como_chama_idosa,
            ao_alertar=self.filtro.registrar_alerta,
            ao_liberar=self._liberar,
            varredura_s=varredura_casos_s,
        )
        if analisador is not None:
            analisador.ao_suspeitar = self._encadear_suspeita(analisador.ao_suspeitar)

    def __repr__(self) -> str:
        estado = self.estado()
        return (
            f"Guardiao(conectado={estado['conectado']}, responsavel_cadastrada={estado['responsavel_cadastrada']}, "
            f"conhecidos={estado['conhecidos']}, observados={estado['observados']})"
        )

    # ------------------------------------------------------------- conexão

    def conectar(self) -> dict:
        """Conecta, faz o pareamento, liga a recepção e manda o `/start` da pessoa idosa.

        Devolve o estado. Chamar de novo com o Guardião conectado não refaz nada.
        """
        with self._trava:
            if self._conectado:
                return self.estado()
            id_idosa = self.canal.conectar()
            conversas = self.canal.conversas_existentes()
            self._bot = self._info_bot()
            # o bot é conhecido: no modo real, os avisos dele à pessoa idosa chegam à conta dela
            extras = [self._bot.get("id")] if self._bot else []
            self.filtro.registrar_pareamento(conversas, extras)
            self._id_idosa = id_idosa
            self.canal.receber_mensagens(self.tratar)
            self._conectado = True
        try:
            self.canal.enviar_start_ao_bot()
        except Exception as erro:
            _avisar(f"/start da pessoa idosa não saiu: {type(erro).__name__}")
        return self.estado()

    def _info_bot(self) -> dict | None:
        try:
            bot = self.canal.info_bot()
        except Exception as erro:
            _avisar(f"bot indisponível: {type(erro).__name__}")
            return None
        if bot and bot.get("id") is not None:
            # mesmo obtido só depois do conectar, o bot é conhecido (avisos dele à pessoa idosa)
            self.filtro.marcar_conhecido(bot["id"])
        return bot

    def fechar(self) -> None:
        """Para a varredura dos casos e fecha o canal. O estado em memória não é apagado (nem o
        arquivo de casos): para recomeçar, crie outro `Guardiao` (como o notebook faz ao rodar a
        seção 5 de novo); para apagar os casos, `casos.apagar_tudo()`."""
        with self._trava:
            self._conectado = False
        self.casos.fechar()
        self.canal.fechar()

    # ------------------------------------------------------------- casos

    def _encadear_suspeita(self, antigo: Callable[[ResultadoAnalise], None] | None):
        """O observador que o analisador já tinha roda primeiro; depois o caso é aberto."""

        def ao_suspeitar(resultado: ResultadoAnalise) -> None:
            if antigo is not None:
                try:  # um observador com defeito não pode impedir o alerta
                    antigo(resultado)
                except Exception as erro:
                    _avisar(f"ao_suspeitar falhou: {type(erro).__name__}")
            self.casos.abrir(resultado)  # se levantar, o Analisador desfaz a suspeita

        return ao_suspeitar

    def _para_idosa(self):
        """Destinatário do aviso à pessoa idosa: o do `/start` dela, ou o id da conta."""
        return self._destinatario_idosa if self._destinatario_idosa is not None else self._id_idosa

    def _liberar(self, remetente_id) -> None:
        """ "Era ele mesmo": o contato vira conhecido e o analisador o esquece."""
        self.filtro.liberar(remetente_id)
        if self.analisador is not None:
            self.analisador.esquecer(remetente_id)

    # ------------------------------------------------------------- eventos do canal

    def tratar(self, evento: Recebido) -> Decisao | ResultadoInicio | None:
        """Handler do canal. Devolve a decisão do filtro ou o resultado do Iniciar."""
        if isinstance(evento, MensagemRecebida):
            return self._tratar_mensagem(evento)
        if isinstance(evento, InicioBot):
            return self._tratar_inicio(evento)
        if isinstance(evento, RespostaAlerta):
            self._tratar_resposta(evento)
        return None

    def _tratar_mensagem(self, mensagem: MensagemRecebida) -> Decisao:
        agora = self._relogio()
        decisao = self.filtro.classificar(mensagem, agora)
        if not decisao.analisar:
            return decisao
        if self.ao_analisar is not None:
            try:  # um observador com defeito não pode impedir a análise
                self.ao_analisar(mensagem)
            except Exception as erro:
                _avisar(f"ao_analisar falhou: {type(erro).__name__}")
        if self.analisador is not None:
            self.analisador.analisar(mensagem, agora=agora, id_idosa=self._id_idosa)
        return decisao

    def _tratar_inicio(self, inicio: InicioBot) -> ResultadoInicio | None:
        if self._id_idosa is not None and inicio.usuario_id == self._id_idosa:
            self._idosa_habilitada = True  # o bot já pode avisá-la; ele não responde a ela
            self._destinatario_idosa = inicio.destinatario
            return None
        resultado = self.cadastro.tratar_inicio(inicio)
        if resultado.destinatario is not None:
            try:
                self.canal.enviar_aviso(resultado.destinatario, resultado.resposta)
            except Exception as erro:
                _avisar(f"resposta ao Iniciar não saiu: {type(erro).__name__}")
        return resultado

    def _tratar_resposta(self, resposta: RespostaAlerta) -> None:
        responsavel = self.cadastro.responsavel
        if responsavel is None or resposta.respondente_id != responsavel.usuario_id:
            return  # só a responsável cadastrada recebe alertas; outro toque não vale
        if self.ao_responder is not None:
            try:  # um observador com defeito não pode impedir o desfecho
                self.ao_responder(resposta)
            except Exception as erro:
                _avisar(f"ao_responder falhou: {type(erro).__name__}")
        self.casos.responder(resposta)

    # ------------------------------------------------------------- configuração

    @property
    def modo(self) -> str:
        """ "demonstracao" quando o canal injeta cenários (canal simulado); senão "real"."""
        return "demonstracao" if callable(getattr(self.canal, "injetar", None)) else "real"

    @property
    def conectado(self) -> bool:
        return self._conectado

    def _usuario_bot(self) -> str:
        bot = self._bot if self._bot is not None else self._info_bot()
        if bot is None:
            raise SemBot("sem bot do Guardião: defina TELEGRAM_BOT_TOKEN para gerar o link de cadastro")
        self._bot = bot
        if not bot.get("username"):
            raise SemBot("o bot do Guardião não tem username")
        return bot["username"]

    def link_cadastro(self) -> str:
        """Link do bot com um código de uso único novo, para a responsável tocar Iniciar."""
        return self.cadastro.link(self._usuario_bot())

    def link_cadastro_vigente(self) -> str:
        """Como `link_cadastro`, mas reaproveita o código vigente (o que a tela mostra).

        O código só muda quando faltam 5 minutos ou menos para ele vencer: a tela, que pede o
        link a cada poucos segundos, não gera um código novo a cada pedido.
        """
        usuario = self._usuario_bot()
        return self.cadastro.link(usuario, self.cadastro.codigo_vigente())

    def estado(self) -> dict:
        """Conexão, cadastro, tamanhos da base e casos por estado (sem ids nem nomes)."""
        cadastro = self.cadastro.estado()
        contagens = self.filtro.contagens()
        return {
            "conectado": self._conectado,
            "idosa_habilitada": self._idosa_habilitada,
            "tem_bot": self._bot is not None,
            "responsavel_cadastrada": cadastro["responsavel_cadastrada"],
            "codigos_validos": cadastro["codigos_validos"],
            "conhecidos": contagens["conhecidos"],
            "observados": contagens["observados"],
            "casos": self.casos.contagens(),
        }
