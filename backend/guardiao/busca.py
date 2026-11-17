"""Busca do parente verdadeiro nos contatos da pessoa idosa (CAP-4).

A busca é toda local: o Gemini não vê os contatos. Ela usa o nome que a pessoa disse ter
(todas as palavras, sem acento, sem caixa e sem pontuação: "Pedro (neto)" e "Ana-Clara"
casam com "Pedro" e "Ana Clara"). O parentesco só desempata
homônimos, porque "Neto" e "Filho" também são sobrenomes no Brasil: sozinho, ele não acha
ninguém. Ficam fora da busca o próprio remetente (o golpista pode ter sido salvo como
"Pedro"), a conta da pessoa idosa e os contatos sem nome.

Sem correspondência, com homônimos sem desempate ou sem conseguir ler os contatos
(`sem_contatos`, decidido por quem chama), não há número sugerido: um número errado é
pior que nenhum.
"""

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from guardiao.canal.base import Contato, _normalizar

_PONTUACAO = re.compile(r"[^\w\s]")

MotivoBusca = Literal["encontrado", "sem_nome", "sem_correspondencia", "ambiguo", "sem_telefone", "sem_contatos"]

# palavras que, no nome salvo, indicam cada parentesco
PALAVRAS_PARENTESCO: dict[str, frozenset[str]] = {
    "filho": frozenset({"filho"}),
    "filha": frozenset({"filha"}),
    "neto": frozenset({"neto"}),
    "neta": frozenset({"neta"}),
    "sobrinho": frozenset({"sobrinho"}),
    "sobrinha": frozenset({"sobrinha"}),
    "irmao": frozenset({"irmao", "mano"}),
    "irma": frozenset({"irma", "mana"}),
    "genro": frozenset({"genro"}),
    "nora": frozenset({"nora"}),
}


@dataclass(frozen=True)
class ResultadoBusca:
    """`contato`/`numero` só quando há um único contato achado. `candidatos` é quantos casaram."""

    motivo: MotivoBusca
    contato: Contato | None = field(default=None, repr=False)
    candidatos: int = 0

    @property
    def numero(self) -> str | None:
        if self.contato is None or not self.contato.telefone:
            return None
        return self.contato.telefone.strip() or None

    @property
    def encontrado(self) -> bool:
        return self.motivo == "encontrado"


def _palavras(texto: str) -> list[str]:
    return _normalizar(_PONTUACAO.sub(" ", texto)).split()


def buscar_parente(
    contatos: Iterable[Contato],
    nome_alegado: str | None,
    parentesco: str | None = None,
    excluir: Iterable = (),
) -> ResultadoBusca:
    """Acha o contato salvo com o nome alegado. Veja o docstring do módulo."""
    procuradas = _palavras(nome_alegado) if nome_alegado else []
    if not procuradas:
        return ResultadoBusca("sem_nome")
    fora = {str(i) for i in excluir if i is not None}
    validos = [c for c in contatos if str(c.id) not in fora and c.nome and _palavras(c.nome)]
    achados = [c for c in validos if all(p in _palavras(c.nome) for p in procuradas)]
    if not achados:
        return ResultadoBusca("sem_correspondencia")
    if len(achados) > 1:
        palavras = PALAVRAS_PARENTESCO.get(parentesco or "", frozenset())
        desempate = [c for c in achados if palavras.intersection(_palavras(c.nome))]
        if len(desempate) != 1:
            return ResultadoBusca("ambiguo", candidatos=len(achados))
        achados = desempate
    contato = achados[0]
    if not (contato.telefone or "").strip():
        return ResultadoBusca("sem_telefone", contato=contato, candidatos=1)
    return ResultadoBusca("encontrado", contato=contato, candidatos=1)
