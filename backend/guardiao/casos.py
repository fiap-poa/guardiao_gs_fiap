"""Casos: alerta à responsável, toque, desfecho e persistência (CAP-5, CAP-6).

Um caso por suspeita (`ResultadoAnalise` do `Analisador`), com os estados de
architecture-diagrams.md:

- `aguardando`: o alerta com [É golpe] [Era ele mesmo] saiu pelo canal à responsável;
- `golpe`: ela tocou "É golpe" → aviso à pessoa idosa;
- `era_ele_mesmo`: ela tocou "Era ele mesmo" → o contato é liberado (vira conhecido) e
  esquecido pelo analisador; nenhum aviso;
- `sem_resposta`: o prazo (10 min por padrão) passou sem toque → aviso à pessoa idosa. Um
  "Era ele mesmo" tardio ainda vale (libera, sem novo aviso); qualquer outro toque num caso
  decidido é ignorado.

Sem responsável cadastrada ou com falha no envio do alerta, `abrir` levanta e nenhum caso
fica: o `Analisador` desfaz a suspeita e reanalisa na próxima mensagem.

As transições rodam sob a trava; o aviso sai fora dela, com o estado já gravado.

Persistência (`RepositorioCasos`): um arquivo JSON local (modo 600, escrita atômica) só com
id, quem a pessoa diz ser (nome e parentesco), trecho, estado, resposta e horários. Nunca a
conversa, o id do remetente, o número sugerido ou ids da responsável: esses ficam só em
memória. Casos com mais de 30 dias são apagados na carga e na varredura; `apagar_tudo()`
apaga a memória e o arquivo. Um caso `aguardando` de outra execução volta como
`sem_resposta`, sem aviso.

Logs só com o tipo do erro e o estado, nunca texto.
"""

import json
import os
import secrets
import sys
import tempfile
import threading
import weakref
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from guardiao.analise import ResultadoAnalise
from guardiao.canal.base import Alerta, Canal, RespostaAlerta
from guardiao.config import LOCAL_DIR, garantir_dir_privado

Estado = Literal["aguardando", "golpe", "era_ele_mesmo", "sem_resposta"]
ESTADOS: tuple[str, ...] = ("aguardando", "golpe", "era_ele_mesmo", "sem_resposta")
RESPOSTAS: tuple[str, ...] = ("golpe", "era_ele_mesmo")

PRAZO_RESPOSTA = timedelta(minutes=10)
RETENCAO = timedelta(days=30)
VARREDURA_S = 15  # de quanto em quanto tempo os prazos e a retenção são conferidos
ARQUIVO_CASOS = LOCAL_DIR / "casos.json"
VERSAO_ARQUIVO = 1
MAX_TRECHO = 300
MAX_NOME = 60

# como a pessoa é chamada quando não disse o nome: "o neto", "a filha"…
QUEM_POR_PARENTESCO: dict[str, str] = {
    "filho": "o filho",
    "filha": "a filha",
    "neto": "o neto",
    "neta": "a neta",
    "sobrinho": "o sobrinho",
    "sobrinha": "a sobrinha",
    "irmao": "o irmão",
    "irma": "a irmã",
    "genro": "o genro",
    "nora": "a nora",
}
FEMININOS = frozenset({"filha", "neta", "sobrinha", "irma", "nora"})
QUEM_SEM_NADA = "um parente"
RESPONSAVEL_SEM_NOME = "A família"


class SemResponsavel(RuntimeError):
    """Ninguém cadastrado para receber o alerta: o caso não é aberto."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _avisar(texto: str) -> None:
    print(f"[casos] {texto}", file=sys.stderr)


# --------------------------------------------------------------------------- textos


def quem_diz_ser(nome_alegado: str | None, parentesco: str | None) -> str:
    """O nome alegado; sem nome, "o neto"/"a filha"…; sem nada, "um parente"."""
    nome = " ".join((nome_alegado or "").split())
    if nome:
        return nome
    return QUEM_POR_PARENTESCO.get(parentesco or "", QUEM_SEM_NADA)


def pronome(parentesco: str | None) -> str:
    """ "ela" para parentesco feminino; "ele" para o resto (inclusive sem parentesco)."""
    return "ela" if parentesco in FEMININOS else "ele"


def texto_aviso(nome_idosa: str, quem: str, nome_responsavel: str | None, parentesco: str | None = None) -> str:
    """Aviso à pessoa idosa (message-templates.md, CAP-6), no tom calmo do modelo."""
    nome_idosa = " ".join((nome_idosa or "").split()) or "Olá"
    nome_idosa = nome_idosa[0].upper() + nome_idosa[1:]
    responsavel = " ".join((nome_responsavel or "").split()) or RESPONSAVEL_SEM_NOME
    return (
        f"{nome_idosa}, chegou uma mensagem de um número novo dizendo ser {quem}. "
        f"Não faça nenhum Pix agora. {responsavel} está confirmando com {pronome(parentesco)}. "
        "Ninguém vai ficar bravo se a senhora esperar."
    )


def formatar_numero(telefone: str | None) -> str | None:
    """`5500987650003` → `+55 00 98765-0003`. Fora do Brasil, `+` e os dígitos."""
    if not telefone:
        return None
    digitos = "".join(c for c in telefone if c.isdigit())
    if not digitos:
        return None
    if digitos.startswith("55") and len(digitos) in (12, 13):
        ddd, numero = digitos[2:4], digitos[4:]
        return f"+55 {ddd} {numero[:-4]}-{numero[-4:]}"
    return f"+{digitos}"


def numero_sugerido(resultado: ResultadoAnalise) -> str | None:
    """O número verdadeiro com o nome salvo: `+55 00 98765-0003 (salvo como Pedro Neto)`."""
    busca = resultado.busca
    if busca is None or busca.contato is None:
        return None
    numero = formatar_numero(busca.numero)
    if numero is None:
        return None
    nome = " ".join((busca.contato.nome or "").split())
    return f"{numero} (salvo como {nome})" if nome else numero


# --------------------------------------------------------------------------- caso


@dataclass(frozen=True)
class Caso:
    """O que fica de uma suspeita. Só estes campos vão para o arquivo."""

    id: str
    estado: Estado
    criado_em: datetime
    prazo_em: datetime
    trecho: str = field(default="", repr=False)
    nome_alegado: str | None = field(default=None, repr=False)
    parentesco: str | None = None
    resposta: str | None = None
    respondido_em: datetime | None = None
    atualizado_em: datetime | None = None
    avisado_em: datetime | None = None

    @property
    def quem(self) -> str:
        return quem_diz_ser(self.nome_alegado, self.parentesco)

    @property
    def decidido(self) -> bool:
        return self.estado != "aguardando"


CAMPOS_ARQUIVO: tuple[str, ...] = (
    "id",
    "nome_alegado",
    "parentesco",
    "trecho",
    "estado",
    "resposta",
    "criado_em",
    "prazo_em",
    "respondido_em",
    "atualizado_em",
    "avisado_em",
)
_HORARIOS = ("criado_em", "prazo_em", "respondido_em", "atualizado_em", "avisado_em")


def _iso(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor is not None else None


def _data(valor) -> datetime | None:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValueError("horário inválido")
    data = datetime.fromisoformat(valor)
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data


def caso_para_dict(caso: Caso) -> dict:
    """O caso como fica no arquivo (só os campos permitidos)."""
    dados = {nome: getattr(caso, nome) for nome in CAMPOS_ARQUIVO}
    for nome in _HORARIOS:
        dados[nome] = _iso(dados[nome])
    return dados


def caso_de_dict(dados: dict) -> Caso:
    """Lê um caso do arquivo, sem confiar nele (`ValueError` se inválido)."""
    if not isinstance(dados, dict):
        raise ValueError("caso não é objeto")
    caso_id, estado, trecho = dados.get("id"), dados.get("estado"), dados.get("trecho")
    if not isinstance(caso_id, str) or not caso_id or estado not in ESTADOS or not isinstance(trecho, str):
        raise ValueError("caso inválido")
    resposta = dados.get("resposta")
    if resposta is not None and resposta not in RESPOSTAS:
        raise ValueError("resposta inválida")
    nome, parentesco = dados.get("nome_alegado"), dados.get("parentesco")
    criado_em, prazo_em = _data(dados.get("criado_em")), _data(dados.get("prazo_em"))
    if criado_em is None or prazo_em is None:
        raise ValueError("caso sem horários")
    return Caso(
        id=caso_id,
        estado=estado,
        criado_em=criado_em,
        prazo_em=prazo_em,
        trecho=trecho[:MAX_TRECHO],
        nome_alegado=nome[:MAX_NOME] if isinstance(nome, str) and nome.strip() else None,
        parentesco=parentesco if isinstance(parentesco, str) and parentesco else None,
        resposta=resposta,
        respondido_em=_data(dados.get("respondido_em")),
        atualizado_em=_data(dados.get("atualizado_em")),
        avisado_em=_data(dados.get("avisado_em")),
    )


# --------------------------------------------------------------------------- repositório


class RepositorioCasos:
    """Casos num arquivo JSON local; `arquivo=None` guarda só em memória (nada no disco)."""

    def __init__(self, arquivo: Path | str | None = None):
        self.arquivo = Path(arquivo) if arquivo is not None else None

    def __repr__(self) -> str:
        return f"RepositorioCasos({'arquivo' if self.arquivo is not None else 'memória'})"

    def carregar(self) -> list[Caso]:
        """Os casos do arquivo. Arquivo ilegível ou caso inválido: descartado (log só do tipo)."""
        if self.arquivo is None or not self.arquivo.exists():
            return []
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            lista = dados.get("casos") if isinstance(dados, dict) else None
            if not isinstance(lista, list):
                raise ValueError("sem lista de casos")
        except (OSError, ValueError) as erro:
            _avisar(f"arquivo de casos ilegível ({type(erro).__name__}); começando sem casos")
            return []
        casos = []
        for item in lista:
            try:
                casos.append(caso_de_dict(item))
            except (ValueError, TypeError) as erro:
                _avisar(f"caso inválido descartado ({type(erro).__name__})")
        return casos

    def salvar(self, casos: list[Caso]) -> None:
        """Grava todos os casos de uma vez: arquivo temporário (600) + `os.replace`."""
        if self.arquivo is None:
            return
        pasta = garantir_dir_privado(self.arquivo.parent)
        conteudo = json.dumps(
            {"versao": VERSAO_ARQUIVO, "casos": [caso_para_dict(c) for c in casos]}, ensure_ascii=False, indent=1
        )
        descritor, temporario = tempfile.mkstemp(prefix=".casos-", suffix=".tmp", dir=pasta)  # já nasce 600
        try:
            with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
                arquivo.write(conteudo)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.chmod(temporario, 0o600)
            os.replace(temporario, self.arquivo)
        except BaseException:
            Path(temporario).unlink(missing_ok=True)
            raise

    def apagar(self) -> None:
        """Apaga o arquivo e qualquer temporário que tenha sobrado."""
        if self.arquivo is None:
            return
        self.arquivo.unlink(missing_ok=True)
        if self.arquivo.parent.exists():
            for sobra in self.arquivo.parent.glob(".casos-*.tmp"):
                sobra.unlink(missing_ok=True)


# --------------------------------------------------------------------------- gestão


@dataclass
class _Vinculo:
    """O que o caso precisa em memória e nunca vai para o arquivo."""

    remetente_id: object = field(repr=False)
    respondente_id: object = field(repr=False)
    alerta_id: str | None = field(default=None, repr=False)
    avisando: bool = False  # aviso à pessoa idosa em andamento (não reenviar ao mesmo tempo)


def _varrer(referencia: "weakref.ref[GestorCasos]", parar: threading.Event, intervalo: float) -> None:
    """Confere prazos e retenção a cada `intervalo`; termina no `fechar()` ou quando o gestor some."""
    while not parar.wait(intervalo):
        gestor = referencia()
        if gestor is None:
            return
        try:
            gestor.verificar_prazos()
        except Exception as erro:
            _avisar(f"varredura falhou: {type(erro).__name__}")
        del gestor


class GestorCasos:
    """Abre o caso com o alerta, aplica o toque da responsável e o prazo, e guarda os casos.

    - `responsavel()`: a responsável cadastrada (`destinatario`, `usuario_id`, `nome`) ou `None`;
    - `destinatario_idosa()`: para onde vai o aviso à pessoa idosa;
    - `ao_alertar(remetente)`: o alerta saiu (o filtro mantém o contato observado);
    - `ao_liberar(remetente)`: "Era ele mesmo" (o filtro libera, o analisador esquece).
    """

    def __init__(
        self,
        canal: Canal,
        repositorio: RepositorioCasos | None = None,
        relogio: Callable[[], datetime] = _agora,
        prazo: timedelta = PRAZO_RESPOSTA,
        responsavel: Callable[[], object] = lambda: None,
        destinatario_idosa: Callable[[], object] = lambda: None,
        nome_idosa: str = "a pessoa idosa",
        como_chama_idosa: str | None = None,
        ao_alertar: Callable[[object], None] | None = None,
        ao_liberar: Callable[[object], None] | None = None,
        retencao: timedelta = RETENCAO,
        varredura_s: float | None = VARREDURA_S,
    ):
        self.canal = canal
        self.repositorio = repositorio or RepositorioCasos(None)
        self._relogio = relogio
        self.prazo = prazo
        self.retencao = retencao
        self._responsavel = responsavel
        self._destinatario_idosa = destinatario_idosa
        self.nome_idosa = nome_idosa
        self.como_chama_idosa = como_chama_idosa or nome_idosa
        self.ao_alertar = ao_alertar
        self.ao_liberar = ao_liberar
        self._trava = threading.Lock()
        self._casos: dict[str, Caso] = {}
        self._vinculos: dict[str, _Vinculo] = {}
        self._parar = threading.Event()
        self._carregar()
        if varredura_s:
            threading.Thread(
                target=_varrer,
                args=(weakref.ref(self), self._parar, varredura_s),
                name="guardiao-casos",
                daemon=True,
            ).start()

    def __repr__(self) -> str:
        contagens = self.contagens()
        return "GestorCasos(" + ", ".join(f"{estado}={n}" for estado, n in contagens.items()) + ")"

    # ------------------------------------------------------------- carga e gravação

    def _carregar(self) -> None:
        agora = self._relogio()
        carregados = self.repositorio.carregar()
        mudou = False
        for caso in carregados:
            if caso.criado_em < agora - self.retencao:
                mudou = True
                continue
            if caso.estado == "aguardando":  # de outra execução: o prazo não é mais acompanhado
                caso = replace(caso, estado="sem_resposta", atualizado_em=agora)
                mudou = True
            self._casos[caso.id] = caso
        if mudou:
            self._salvar()

    def _salvar(self) -> None:
        """Grava o estado atual (chamado sob a trava). Falha no disco não desfaz a transição."""
        try:
            self.repositorio.salvar(sorted(self._casos.values(), key=lambda c: c.criado_em))
        except Exception as erro:
            _avisar(f"casos não gravados: {type(erro).__name__}")

    # ------------------------------------------------------------- abrir

    def abrir(self, resultado: ResultadoAnalise) -> Caso:
        """Abre o caso e manda o alerta à responsável. Levanta se não houver como alertar."""
        if not resultado.suspeita:
            raise ValueError("só uma suspeita abre caso")
        responsavel = self._responsavel()
        if responsavel is None:
            raise SemResponsavel("nenhuma responsável cadastrada para receber o alerta")
        analise = resultado.analise
        nome = analise.nome_alegado if analise is not None else None
        parentesco = analise.parentesco if analise is not None else None
        agora = self._relogio()
        with self._trava:
            caso_id = self._novo_id()
            caso = Caso(
                id=caso_id,
                estado="aguardando",
                criado_em=agora,
                prazo_em=agora + self.prazo,
                trecho=(resultado.trecho or "")[:MAX_TRECHO],
                nome_alegado=nome,
                parentesco=parentesco,
                atualizado_em=agora,
            )
            # em memória antes do envio: um toque que chegue antes do retorno já acha o caso
            self._casos[caso_id] = caso
            self._vinculos[caso_id] = _Vinculo(resultado.remetente_id, responsavel.usuario_id)
        alerta = Alerta(
            destinatario=responsavel.destinatario,
            caso_id=caso_id,
            nome_alegado=caso.quem,
            como_chama_idosa=self.como_chama_idosa,
            trecho=caso.trecho,
            numero_verdadeiro=numero_sugerido(resultado),
        )
        try:
            alerta_id = self.canal.enviar_alerta(alerta)
        except BaseException:
            with self._trava:
                self._casos.pop(caso_id, None)
                self._vinculos.pop(caso_id, None)
                self._salvar()  # outra transição pode ter gravado o arquivo enquanto o alerta saía
            raise
        with self._trava:
            vinculo = self._vinculos.get(caso_id)
            if vinculo is not None:
                vinculo.alerta_id = str(alerta_id) if alerta_id is not None else None
            self._salvar()
            caso = self._casos.get(caso_id, caso)
        if self.ao_alertar is not None:
            try:
                self.ao_alertar(resultado.remetente_id)
            except Exception as erro:
                _avisar(f"ao_alertar falhou: {type(erro).__name__}")
        return caso

    def _novo_id(self) -> str:
        while True:  # 12 caracteres: cabe no callback_data do Telegram (64 bytes)
            caso_id = secrets.token_urlsafe(9)
            if caso_id not in self._casos:
                return caso_id

    # ------------------------------------------------------------- toque

    def responder(self, resposta: RespostaAlerta) -> Caso | None:
        """Aplica o toque. Devolve o caso alterado, ou `None` se o toque foi ignorado."""
        if resposta.resposta not in RESPOSTAS:
            return None
        agora = self._relogio()
        with self._trava:
            caso = self._casos.get(resposta.caso_id)
            if caso is None:
                return None  # caso desconhecido (ou apagado)
            vinculo = self._vinculos.get(caso.id)
            if vinculo is None:
                return None  # caso de outra execução: não há como conferir o toque nem liberar o contato
            if str(vinculo.respondente_id) != str(resposta.respondente_id):
                return None  # o alerta foi para outra conta
            if caso.estado == "aguardando":
                pass
            elif caso.estado == "sem_resposta" and resposta.resposta == "era_ele_mesmo":
                pass  # toque tardio: libera, sem novo aviso
            else:
                return None  # caso decidido
            avisar = caso.estado == "aguardando" and resposta.resposta == "golpe"
            caso = replace(
                caso,
                estado=resposta.resposta,
                resposta=resposta.resposta,
                respondido_em=agora,
                atualizado_em=agora,
            )
            self._casos[caso.id] = caso
            self._salvar()
            remetente = vinculo.remetente_id
            vinculo.avisando = vinculo.avisando or avisar
        if avisar:
            caso = self._avisar_idosa(caso)
        elif resposta.resposta == "era_ele_mesmo" and remetente is not None and self.ao_liberar is not None:
            try:
                self.ao_liberar(remetente)
            except Exception as erro:
                _avisar(f"ao_liberar falhou: {type(erro).__name__}")
        return caso

    # ------------------------------------------------------------- prazo e retenção

    def verificar_prazos(self) -> list[Caso]:
        """`aguardando` com o prazo vencido → `sem_resposta` e aviso. Também aplica a retenção e
        tenta de novo o aviso que não saiu (só casos desta execução). Devolve os que venceram agora."""
        agora = self._relogio()
        with self._trava:
            vencidos, pendentes = [], []
            for caso in list(self._casos.values()):
                vinculo = self._vinculos.get(caso.id)
                if caso.estado == "aguardando" and agora >= caso.prazo_em:
                    caso = replace(caso, estado="sem_resposta", atualizado_em=agora)
                    self._casos[caso.id] = caso
                    vencidos.append(caso)
                elif (
                    caso.estado in ("golpe", "sem_resposta")
                    and caso.avisado_em is None
                    and vinculo is not None
                    and not vinculo.avisando
                ):
                    pendentes.append(caso)  # o aviso falhou antes: nova tentativa
                else:
                    continue
                if vinculo is not None:
                    vinculo.avisando = True
            removidos = self._limpar_antigos(agora)
            if vencidos or removidos:
                self._salvar()
        for caso in pendentes:
            self._avisar_idosa(caso)
        return [self._avisar_idosa(caso) for caso in vencidos]

    def limpar_antigos(self) -> int:
        """Apaga os casos com mais de 30 dias; devolve quantos saíram."""
        with self._trava:
            removidos = self._limpar_antigos(self._relogio())
            if removidos:
                self._salvar()
            return removidos

    def _limpar_antigos(self, agora: datetime) -> int:
        limite = agora - self.retencao
        antigos = [caso_id for caso_id, caso in self._casos.items() if caso.criado_em < limite]
        for caso_id in antigos:
            del self._casos[caso_id]
            self._vinculos.pop(caso_id, None)
        return len(antigos)

    # ------------------------------------------------------------- aviso

    def _avisar_idosa(self, caso: Caso) -> Caso:
        """Manda o aviso fora da trava (o estado já está gravado) e registra o horário."""
        try:
            return self._enviar_aviso(caso)
        finally:
            with self._trava:
                vinculo = self._vinculos.get(caso.id)
                if vinculo is not None:
                    vinculo.avisando = False

    def _enviar_aviso(self, caso: Caso) -> Caso:
        destinatario = self._destinatario_idosa()
        if destinatario is None:
            _avisar(f"aviso à pessoa idosa não saiu (caso {caso.estado}): sem destinatário")
            return caso
        responsavel = self._responsavel()
        texto = texto_aviso(self.nome_idosa, caso.quem, getattr(responsavel, "nome", None), caso.parentesco)
        try:
            self.canal.enviar_aviso(destinatario, texto)
        except Exception as erro:
            _avisar(f"aviso à pessoa idosa não saiu (caso {caso.estado}): {type(erro).__name__}")
            return caso
        agora = self._relogio()
        with self._trava:
            atual = self._casos.get(caso.id)
            if atual is None:
                return caso
            atual = replace(atual, avisado_em=agora)
            self._casos[caso.id] = atual
            self._salvar()
            return atual

    # ------------------------------------------------------------- consulta

    def obter(self, caso_id: str) -> Caso | None:
        with self._trava:
            return self._casos.get(caso_id)

    def caso_de(self, remetente_id) -> Caso | None:
        """O caso mais recente deste remetente nesta execução (o vínculo só existe em memória)."""
        chave = str(remetente_id)
        with self._trava:
            casos = [
                self._casos[caso_id]
                for caso_id, vinculo in self._vinculos.items()
                if str(vinculo.remetente_id) == chave and caso_id in self._casos
            ]
        return max(casos, key=lambda c: c.criado_em, default=None)

    def listar(self) -> list[dict]:
        """Os casos para a tela, do mais recente: sem ids, com quem diz ser, trecho e estado."""
        with self._trava:
            casos = sorted(self._casos.values(), key=lambda c: c.criado_em, reverse=True)
        lista = []
        for caso in casos:
            dados = caso_para_dict(caso)
            del dados["id"]
            dados["quem"] = caso.quem
            lista.append(dados)
        return lista

    def contagens(self) -> dict:
        with self._trava:
            contagem = {estado: 0 for estado in ESTADOS}
            for caso in self._casos.values():
                contagem[caso.estado] += 1
            return contagem

    # ------------------------------------------------------------- fim

    def apagar_tudo(self) -> None:
        """Apaga todos os casos: memória e arquivo (fim da demonstração)."""
        with self._trava:
            self._casos.clear()
            self._vinculos.clear()
            self.repositorio.apagar()

    def fechar(self) -> None:
        """Para a varredura. Os casos continuam (use `apagar_tudo` para apagá-los)."""
        self._parar.set()
