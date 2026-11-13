import pytest

from guardiao.canal.base import Alerta, Contato, procurar_contatos, texto_alerta
from guardiao.canal.telegram import dados_botao, teclado_alerta


def _alerta(numero=None):
    return Alerta(
        destinatario=1,
        caso_id="c1",
        nome_alegado="Pedro",
        como_chama_idosa="sua mãe",
        trecho="oi vó, é o Pedro, troquei de número",
        numero_verdadeiro=numero,
    )


def test_texto_alerta_com_numero_segue_o_modelo():
    assert texto_alerta(_alerta("+55 00 90000-0000")) == (
        "Um número novo está dizendo ser Pedro e pediu dinheiro para sua mãe.\n"
        'Mensagem recebida: "oi vó, é o Pedro, troquei de número".\n'
        "O número salvo nos contatos para esse nome é +55 00 90000-0000. "
        "Ligue para esse número antes de qualquer coisa."
    )


def test_texto_alerta_sem_numero_troca_a_ultima_frase():
    texto = texto_alerta(_alerta())
    assert texto.endswith(
        "Não achei esse nome nos contatos. Confirme com a família antes de qualquer coisa."
    )
    assert "número salvo" not in texto


def test_teclado_tem_os_dois_botoes_numa_linha():
    teclado = teclado_alerta("c1")
    assert teclado == {
        "inline_keyboard": [
            [
                {"text": "É golpe", "callback_data": "golpe:c1"},
                {"text": "Era ele mesmo", "callback_data": "ele_mesmo:c1"},
            ]
        ]
    }


def test_callback_data_respeita_64_bytes():
    with pytest.raises(ValueError):
        dados_botao("golpe", "x" * 64)


def test_procurar_contatos_sem_caixa_e_sem_acento():
    contatos = [
        Contato(1, "Pedro Henrique", "5500900000001"),
        Contato(2, "Pedrinho", None),
        Contato(3, "José Pedro", None),
        Contato(4, "Ana", "5500900000004"),
    ]
    assert [c.id for c in procurar_contatos(contatos, "pedro")] == [1, 3]
    assert [c.id for c in procurar_contatos(contatos, "JOSE")] == [3]
    assert procurar_contatos(contatos, "Maria") == []
    assert procurar_contatos(contatos, "  ") == []
