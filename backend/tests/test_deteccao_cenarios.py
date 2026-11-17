"""Detecção (CAP-3) e busca (CAP-4) de ponta a ponta no canal simulado, com o dublê do Gemini."""

import re

import pytest

from duble_gemini import DubleRegras
from guardiao.analise import Analisador, Detector, montar_pedido
from guardiao.canal.cenarios import CENARIOS, CONTATOS, NOME_IDOSA
from guardiao.canal.fabrica import criar_canal
from guardiao.conjunto_cap3 import CONJUNTO_CAP3
from guardiao.recepcao import Guardiao, RelogioAjustavel
from test_simulado import sem_rede  # noqa: F401 (fixture)


@pytest.fixture
def montagem(sem_rede):
    canal = criar_canal("demonstracao", ambiente={})
    duble = DubleRegras()
    suspeitas = []
    relogio = RelogioAjustavel()
    analisador = Analisador(
        Detector(duble), canal.listar_contatos, ao_suspeitar=suspeitas.append, relogio=relogio, varredura_s=None
    )
    guardiao = Guardiao(canal, relogio=relogio, analisador=analisador)
    guardiao.conectar()
    yield canal, duble, suspeitas, analisador
    canal.fechar()


def _pedidos_de(duble, cenario):
    return [p for p in duble.pedidos if any(m in p["conteudo"] for m in cenario.mensagens)]


def test_cinco_cenarios_so_golpe_e_troca_de_numero_marcam_suspeita(montagem, capsys):
    canal, duble, suspeitas, analisador = montagem
    capsys.readouterr()
    for cenario in CENARIOS:
        canal.injetar(cenario.id)
    assert [(s.remetente_id, s.busca.numero) for s in suspeitas] == [
        ("sim:novo-1", "5500987650003"),  # Pedro Neto
        ("sim:novo-2", "5500987650002"),  # Lucas Filho
    ]
    golpe, troca = suspeitas
    assert (golpe.analise.nome_alegado, golpe.analise.parentesco, golpe.analise.forma_pagamento) == ("Pedro", "neto", "pix")
    assert (troca.analise.nome_alegado, troca.analise.parentesco) == ("Lucas", "filho")
    assert troca.analise.forma_pagamento == "transferencia"
    assert golpe.trecho.startswith("Vó, preciso de um Pix de R$ 850")
    por_cenario = {c.id: _pedidos_de(duble, c) for c in CENARIOS}
    assert por_cenario["contato_antigo_pede_dinheiro"] == [] and por_cenario["mensagem_em_grupo"] == []
    assert len(por_cenario["contato_novo_sem_dinheiro"]) == 2
    situacoes = {r.remetente_id: r.situacao for r in analisador.resultados}
    assert situacoes == {"sim:novo-1": "suspeita", "sim:novo-2": "suspeita", "sim:novo-3": "sem_suspeita"}
    assert capsys.readouterr().err == ""  # nada impresso, nem texto nem aviso


def test_golpe_classico_primeira_mensagem_sem_suspeita_segunda_com_a_conversa_inteira(montagem):
    canal, duble, suspeitas, analisador = montagem
    canal.injetar("golpe_classico")
    primeiro, segundo = analisador.resultados
    assert primeiro.situacao == "sem_suspeita" and primeiro.analise.alega_parentesco
    assert segundo.situacao == "suspeita" and segundo.mensagens_analisadas == 2
    cenario = CENARIOS[0]
    assert duble.pedidos[-1]["conteudo"] == montar_pedido(list(cenario.mensagens))
    assert len(suspeitas) == 1


def test_gemini_recebe_so_a_conversa_do_contato_novo(montagem):
    canal, duble, _, _ = montagem
    for cenario in CENARIOS:
        canal.injetar(cenario.id)
    canal.injetar_mensagem("sim:julia", "Oi vó, a senhora está bem?", de="Júlia Neta")
    assert duble.pedidos
    for pedido in duble.pedidos:
        enviado = pedido["instrucao"] + pedido["conteudo"] + repr(pedido["esquema"])
        assert not re.search(r"5500\d{9}", enviado)  # nenhum telefone
        assert "sim:" not in enviado  # nenhum id
        assert NOME_IDOSA not in enviado
        for contato in CONTATOS:
            primeiro_nome = contato.nome.split()[0]
            assert primeiro_nome not in pedido["instrucao"]  # a instrução não traz a agenda
            for parte in contato.nome.split():  # nenhum nome salvo que a própria conversa não traga
                if parte not in pedido["conteudo"]:
                    assert parte not in enviado, parte


def test_mensagens_seguintes_do_suspeito_nao_voltam_ao_gemini(montagem):
    canal, duble, suspeitas, analisador = montagem
    canal.injetar("golpe_classico")
    chamadas = len(duble.pedidos)
    canal.injetar_mensagem("sim:novo-1", "Vó, faz logo o Pix!")
    assert len(duble.pedidos) == chamadas and len(suspeitas) == 1
    assert analisador.resultados[-1].situacao == "ja_suspeito"


def test_sem_analisador_o_guardiao_segue_como_antes(sem_rede):
    canal = criar_canal("demonstracao", ambiente={})
    analisadas = []
    guardiao = Guardiao(canal, ao_analisar=analisadas.append)
    guardiao.conectar()
    canal.injetar("golpe_classico")
    assert len(analisadas) == 2
    canal.fechar()


@pytest.mark.parametrize("conversa", CONJUNTO_CAP3, ids=lambda c: c.id)
def test_conjunto_cap3_com_o_duble(conversa):
    detector = Detector(DubleRegras())
    analise = detector.analisar(list(conversa.mensagens))
    assert analise.alega_parentesco == conversa.alega_parentesco
    assert analise.pede_dinheiro == conversa.pede_dinheiro
    assert analise.suspeita == conversa.suspeita
    if conversa.nome_alegado:
        assert analise.nome_alegado == conversa.nome_alegado


def test_conjunto_cap3_cobre_as_duas_condicoes_isoladas():
    combinacoes = {(c.alega_parentesco, c.pede_dinheiro) for c in CONJUNTO_CAP3}
    assert combinacoes == {(True, True), (True, False), (False, True)}
    assert all(c.suspeita == (c.alega_parentesco and c.pede_dinheiro) for c in CONJUNTO_CAP3)
    assert len({c.id for c in CONJUNTO_CAP3}) == len(CONJUNTO_CAP3)


def test_conta_da_idosa_nos_contatos_nao_vira_o_numero_do_parente(sem_rede, monkeypatch):
    from guardiao.canal.base import Contato
    from guardiao.canal.cenarios import ID_IDOSA

    canal = criar_canal("demonstracao", ambiente={})
    contatos = [Contato(ID_IDOSA, "Pedro Neto Maria", "5500987650000"), *CONTATOS]
    monkeypatch.setattr(canal, "listar_contatos", lambda: contatos)
    suspeitas = []
    analisador = Analisador(Detector(DubleRegras()), canal.listar_contatos, ao_suspeitar=suspeitas.append, varredura_s=None)
    Guardiao(canal, analisador=analisador).conectar()
    canal.injetar("golpe_classico")
    assert [s.busca.numero for s in suspeitas] == ["5500987650003"]
    canal.fechar()


def test_observador_ao_analisar_com_defeito_nao_impede_a_analise(sem_rede, capsys):
    canal = criar_canal("demonstracao", ambiente={})
    suspeitas = []
    analisador = Analisador(Detector(DubleRegras()), canal.listar_contatos, ao_suspeitar=suspeitas.append, varredura_s=None)

    def quebrado(_):
        raise RuntimeError("observador")

    Guardiao(canal, ao_analisar=quebrado, analisador=analisador).conectar()
    canal.injetar("golpe_classico")
    assert len(suspeitas) == 1 and "ao_analisar falhou: RuntimeError" in capsys.readouterr().err
    canal.fechar()
