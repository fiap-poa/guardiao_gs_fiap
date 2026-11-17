"""Busca do parente verdadeiro nos contatos (CAP-4)."""

import pytest

from guardiao.busca import buscar_parente
from guardiao.canal.base import Contato
from guardiao.canal.cenarios import CONTATOS, ID_IDOSA


def test_oi_vo_e_o_pedro_acha_o_pedro_com_o_telefone_salvo():
    resultado = buscar_parente(CONTATOS, "Pedro", "neto")
    assert resultado.motivo == "encontrado" and resultado.encontrado
    assert resultado.contato.nome == "Pedro Neto"
    assert resultado.numero == "5500987650003"


@pytest.mark.parametrize("nome", ["pedro", "PEDRO", " Pedro "])
def test_sem_caixa_e_espacos(nome):
    assert buscar_parente(CONTATOS, nome).numero == "5500987650003"


def test_sem_acento():
    assert buscar_parente(CONTATOS, "Julia").contato.nome == "Júlia Neta"


def test_filho_lucas():
    assert buscar_parente(CONTATOS, "Lucas", "filho").numero == "5500987650002"


def test_nome_fora_dos_contatos_segue_sem_numero():
    resultado = buscar_parente(CONTATOS, "Rafael", "neto")
    assert resultado.motivo == "sem_correspondencia"
    assert resultado.numero is None and resultado.contato is None


@pytest.mark.parametrize("nome", [None, "", "   "])
def test_sem_nome_alegado(nome):
    assert buscar_parente(CONTATOS, nome, "neto").motivo == "sem_nome"


def test_parentesco_sozinho_nao_acha_ninguem():
    # "Neto" no nome salvo também é sobrenome: sem o nome alegado, não há número
    assert buscar_parente(CONTATOS, None, "neto").numero is None


def test_apelido_nao_casa():
    assert buscar_parente(CONTATOS, "Pedrinho", "neto").motivo == "sem_correspondencia"


HOMONIMOS = [
    Contato("sim:pedro", "Pedro Neto", "5500987650003"),
    Contato("sim:pedro-sobrinho", "Pedro Sobrinho", "5500987650006"),
]


def test_homonimos_desempatados_pelo_parentesco():
    resultado = buscar_parente(HOMONIMOS, "Pedro", "sobrinho")
    assert resultado.motivo == "encontrado" and resultado.numero == "5500987650006"


@pytest.mark.parametrize("parentesco", [None, "filho", "outro"])
def test_homonimos_sem_desempate_nao_sugerem_numero(parentesco):
    resultado = buscar_parente(HOMONIMOS, "Pedro", parentesco)
    assert resultado.motivo == "ambiguo" and resultado.numero is None and resultado.candidatos == 2


def test_dois_homonimos_com_o_mesmo_parentesco_sao_ambiguos():
    contatos = [Contato("a", "Pedro Neto", "5500987650003"), Contato("b", "Pedro Henrique Neto", "5500987650007")]
    assert buscar_parente(contatos, "Pedro", "neto").motivo == "ambiguo"


def test_remetente_salvo_com_o_nome_alegado_fica_fora():
    # a pessoa idosa salvou o golpista como "Pedro Novo": só o Pedro verdadeiro serve
    contatos = [*CONTATOS, Contato("sim:novo-1", "Pedro Novo", "5500987651001")]
    resultado = buscar_parente(contatos, "Pedro", "neto", excluir=("sim:novo-1", ID_IDOSA))
    assert resultado.motivo == "encontrado" and resultado.numero == "5500987650003"


def test_conta_da_idosa_e_nomes_vazios_ficam_fora():
    contatos = [
        Contato(ID_IDOSA, "Maria", "5500987650000"),
        Contato(42, "", "5500987650008"),
        Contato(43, "   ", None),
        Contato(44, "Maria Filha", "5500987650009"),
    ]
    resultado = buscar_parente(contatos, "Maria", "filha", excluir=(ID_IDOSA,))
    assert resultado.motivo == "encontrado" and resultado.numero == "5500987650009"


def test_ids_inteiros_e_texto_comparados_como_texto():
    contatos = [Contato(7001, "Pedro Neto", "5500987650003")]
    assert buscar_parente(contatos, "Pedro", excluir=("7001",)).motivo == "sem_correspondencia"


def test_contato_sem_telefone():
    resultado = buscar_parente([Contato(1, "Pedro Neto", None)], "Pedro")
    assert resultado.motivo == "sem_telefone" and resultado.numero is None


def test_repr_sem_telefone_nem_nome():
    texto = repr(buscar_parente(CONTATOS, "Pedro"))
    assert "5500" not in texto and "Pedro" not in texto


@pytest.mark.parametrize(
    "salvo, alegado", [("Pedro (neto)", "Pedro"), ("Pedro - Neto", "pedro"), ("Ana-Clara Neta", "Ana Clara"), ("Pedro Neto", "Pedro.")]
)
def test_pontuacao_no_nome_salvo_ou_alegado(salvo, alegado):
    resultado = buscar_parente([Contato(1, salvo, "5500987650003")], alegado, "neto")
    assert resultado.numero == "5500987650003"


def test_parentesco_entre_parenteses_desempata():
    contatos = [Contato(1, "Pedro (neto)", "5500987650003"), Contato(2, "Pedro (sobrinho)", "5500987650006")]
    assert buscar_parente(contatos, "Pedro", "neto").numero == "5500987650003"


def test_telefone_so_com_espacos_e_sem_telefone():
    resultado = buscar_parente([Contato(1, "Pedro Neto", "   ")], "Pedro")
    assert resultado.motivo == "sem_telefone" and resultado.numero is None


def test_nome_so_com_pontuacao_e_sem_nome():
    assert buscar_parente(CONTATOS, "?!").motivo == "sem_nome"
