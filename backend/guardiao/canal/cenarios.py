"""Dados fictícios do modo demonstração (canal simulado).

Tudo aqui é inventado. Todo telefone tem DDD 00, que não existe no Brasil: `5500` + 9 dígitos.
Os ids dos remetentes simulados são `sim:<nome>`; números novos são `sim:novo-<n>`; a pessoa
idosa é `sim:idosa`.

Os cinco cenários servem de roteiro da demonstração e de conjunto de teste das histórias
seguintes. `esperado` diz o que o Guardião deve fazer com cada um:

- `alerta`: alerta à responsável (golpe);
- `alerta_era_ele_mesmo`: alerta, e a responsável responde "Era ele mesmo";
- `ignorado`: não chega à análise (contato antigo ou grupo);
- `sem_alerta`: é analisado, mas não gera alerta.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from guardiao.canal.base import Contato, ConversaAntiga  # ConversaAntiga: reexportada

Origem = Literal["novo", "antigo", "grupo"]
Esperado = Literal["alerta", "alerta_era_ele_mesmo", "ignorado", "sem_alerta"]

ID_IDOSA = "sim:idosa"
NOME_IDOSA = "Dona Maria"
TELEFONE_IDOSA = "5500987650000"


@dataclass(frozen=True)
class Cenario:
    id: str
    descricao: str
    remetente_id: str
    remetente_nome: str  # como aparece no celular: nome salvo, telefone novo ou nome do grupo
    remetente_telefone: str | None
    origem: Origem
    conversa_id: str
    mensagens: tuple[str, ...]
    esperado: Esperado


CONTATOS: tuple[Contato, ...] = (
    Contato(id="sim:mariana", nome="Mariana Filha", telefone="5500987650001"),
    Contato(id="sim:lucas", nome="Lucas Filho", telefone="5500987650002"),
    Contato(id="sim:pedro", nome="Pedro Neto", telefone="5500987650003"),
    Contato(id="sim:julia", nome="Júlia Neta", telefone="5500987650004"),
    Contato(id="sim:carlos", nome="Carlos Vizinho", telefone="5500987650005"),
)


def _em(ano: int, mes: int, dia: int) -> datetime:
    return datetime(ano, mes, dia, 12, 0, tzinfo=timezone.utc)


ID_GRUPO_FAMILIA = "sim:grupo-familia"

CONVERSAS_ANTIGAS: tuple[ConversaAntiga, ...] = (
    ConversaAntiga("sim:mariana", "privada", "Mariana Filha", _em(2021, 3, 2)),
    ConversaAntiga("sim:lucas", "privada", "Lucas Filho", _em(2021, 3, 5)),
    ConversaAntiga("sim:pedro", "privada", "Pedro Neto", _em(2022, 8, 14)),
    ConversaAntiga("sim:carlos", "privada", "Carlos Vizinho", _em(2023, 1, 20)),
    ConversaAntiga(ID_GRUPO_FAMILIA, "grupo", "Família", _em(2021, 4, 10)),
)

CENARIOS: tuple[Cenario, ...] = (
    Cenario(
        id="golpe_classico",
        descricao="Número novo diz ser o neto Pedro, diz que trocou de número e pede um Pix urgente.",
        remetente_id="sim:novo-1",
        remetente_nome="+55 00 98765-1001",
        remetente_telefone="5500987651001",
        origem="novo",
        conversa_id="sim:novo-1",
        mensagens=(
            "Oi vó, é o Pedro! Troquei de número, salva esse aqui.",
            "Vó, preciso de um Pix de R$ 850 agora pra pagar o aluguel, senão me despejam. "
            "Amanhã te devolvo, não conta pra minha mãe.",
        ),
        esperado="alerta",
    ),
    Cenario(
        id="parente_trocou_numero",
        descricao="O filho Lucas trocou de número de verdade e pede uma transferência; "
        "a responsável confirma que era ele.",
        remetente_id="sim:novo-2",
        remetente_nome="+55 00 98765-1002",
        remetente_telefone="5500987651002",
        origem="novo",
        conversa_id="sim:novo-2",
        mensagens=(
            "Oi mãe, é o Lucas. Meu celular quebrou e estou com esse número novo.",
            "Mãe, consegue me fazer uma transferência de R$ 300 pra oficina do carro? "
            "Sábado eu passo aí e te devolvo.",
        ),
        esperado="alerta_era_ele_mesmo",
    ),
    Cenario(
        id="contato_antigo_pede_dinheiro",
        descricao="O vizinho Carlos, que já conversava com ela, pede dinheiro emprestado.",
        remetente_id="sim:carlos",
        remetente_nome="Carlos Vizinho",
        remetente_telefone="5500987650005",
        origem="antigo",
        conversa_id="sim:carlos",
        mensagens=("Dona Maria, a senhora me empresta R$ 50 até sexta? Te faço um Pix de volta.",),
        esperado="ignorado",
    ),
    Cenario(
        id="mensagem_em_grupo",
        descricao="Alguém no grupo Família pede um Pix para a pizza de domingo.",
        remetente_id="sim:mariana",
        remetente_nome="Família",
        remetente_telefone=None,
        origem="grupo",
        conversa_id=ID_GRUPO_FAMILIA,
        mensagens=("Gente, quem faz o Pix da pizza de domingo? São R$ 30 por pessoa.",),
        esperado="ignorado",
    ),
    Cenario(
        id="contato_novo_sem_dinheiro",
        descricao="Número novo diz ser a neta Júlia e só manda saudades, sem pedir dinheiro.",
        remetente_id="sim:novo-3",
        remetente_nome="+55 00 98765-1003",
        remetente_telefone="5500987651003",
        origem="novo",
        conversa_id="sim:novo-3",
        mensagens=(
            "Oi vó, é a Júlia! Esse é meu número novo.",
            "Estou com saudades, domingo passo aí pra tomar café com a senhora.",
        ),
        esperado="sem_alerta",
    ),
)

_POR_ID = {cenario.id: cenario for cenario in CENARIOS}


def obter_cenario(cenario_id: str) -> Cenario:
    """Cenário pelo id; `KeyError` com o nome se não existir."""
    try:
        return _POR_ID[cenario_id]
    except KeyError:
        raise KeyError(f"cenário desconhecido: {cenario_id!r}") from None


def listar_cenarios() -> list[Cenario]:
    return list(CENARIOS)
