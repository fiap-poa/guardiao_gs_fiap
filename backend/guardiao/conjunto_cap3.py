"""Conjunto de teste do CAP-3: conversas de contato novo e a suspeita esperada.

Tudo fictício, sem telefones. Os três primeiros são os cenários de contato novo do canal
simulado; os outros cobrem os casos com só uma das duas condições (parentesco sem pedido,
pedido sem parentesco) e as formas de pagamento. Serve aos testes com o dublê, ao teste
opcional contra o Gemini real e à célula do notebook.
"""

from dataclasses import dataclass

from guardiao.canal.cenarios import obter_cenario


@dataclass(frozen=True)
class ConversaTeste:
    id: str
    descricao: str
    mensagens: tuple[str, ...]
    suspeita: bool  # alegação de parentesco E pedido de dinheiro
    alega_parentesco: bool
    pede_dinheiro: bool
    nome_alegado: str | None = None  # quando a conversa diz um nome


def _do_cenario(cenario_id: str, **esperado) -> ConversaTeste:
    cenario = obter_cenario(cenario_id)
    return ConversaTeste(cenario.id, cenario.descricao, cenario.mensagens, **esperado)


CONJUNTO_CAP3: tuple[ConversaTeste, ...] = (
    _do_cenario("golpe_classico", suspeita=True, alega_parentesco=True, pede_dinheiro=True, nome_alegado="Pedro"),
    _do_cenario(
        "parente_trocou_numero", suspeita=True, alega_parentesco=True, pede_dinheiro=True, nome_alegado="Lucas"
    ),
    _do_cenario(
        "contato_novo_sem_dinheiro", suspeita=False, alega_parentesco=True, pede_dinheiro=False, nome_alegado="Júlia"
    ),
    ConversaTeste(
        "parente_pede_boleto",
        "Número novo diz ser a neta Júlia e pede que a avó pague o boleto da faculdade.",
        (
            "Oi vó, é a Júlia, tô com número novo.",
            "Vó, a senhora paga o boleto da minha faculdade? Vence hoje, depois te explico.",
        ),
        suspeita=True,
        alega_parentesco=True,
        pede_dinheiro=True,
        nome_alegado="Júlia",
    ),
    ConversaTeste(
        "parente_sem_pedir",
        "Número novo diz ser o filho Lucas e conta que recebeu o salário, sem pedir nada.",
        (
            "Oi mãe, é o Lucas. Esse é meu número do trabalho.",
            "Recebi meu salário hoje! Domingo levo a senhora pra almoçar, eu pago.",
        ),
        suspeita=False,
        alega_parentesco=True,
        pede_dinheiro=False,
        nome_alegado="Lucas",
    ),
    ConversaTeste(
        "banco_pede_boleto",
        "Número novo diz ser do banco e pede o pagamento de um boleto (sem alegar parentesco).",
        (
            "Olá, aqui é da central de segurança do banco.",
            "Sua conta tem uma pendência. Pague o boleto hoje para não ser bloqueada.",
        ),
        suspeita=False,
        alega_parentesco=False,
        pede_dinheiro=True,
    ),
    ConversaTeste(
        "amiga_pede_pix",
        "Número novo diz ser uma amiga da igreja e pede um Pix emprestado (amiga não é parente).",
        ("Oi Dona Maria, é a Cida da igreja!", "Me empresta R$ 100 por Pix? Devolvo sexta."),
        suspeita=False,
        alega_parentesco=False,
        pede_dinheiro=True,
        nome_alegado="Cida",
    ),
    ConversaTeste(
        "neto_sem_nome_pede_deposito",
        "Número novo diz ser o neto, sem dizer o nome, e pede um depósito urgente.",
        (
            "Oi vó, sou eu, seu neto. Troquei de celular.",
            "Preciso que a senhora deposite R$ 400 na conta de um amigo, é urgente.",
        ),
        suspeita=True,
        alega_parentesco=True,
        pede_dinheiro=True,
    ),
)
