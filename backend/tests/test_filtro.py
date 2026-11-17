"""Filtro de contato novo (CAP-2), sem canal e sem rede."""

from datetime import datetime, timedelta, timezone

import pytest

from guardiao.canal.base import ConversaAntiga, MensagemRecebida
from guardiao.canal.cenarios import CONVERSAS_ANTIGAS
from guardiao.filtro import OBSERVACAO, Decisao, FiltroContatos, SemPareamento

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


class MensagemSemLeitura:
    """Mensagem cujo texto não pode ser lido: o filtro só pode olhar tipo e remetente."""

    def __init__(self, tipo, remetente_id=None):
        self.tipo = tipo
        self.remetente_id = remetente_id
        self.conversa_id = remetente_id

    @property
    def texto(self):
        raise AssertionError("o filtro leu o texto")

    tem_texto = texto


def _filtro():
    filtro = FiltroContatos()
    filtro.registrar_pareamento(CONVERSAS_ANTIGAS, extras=[7555000111])
    return filtro


def _privada(remetente):
    return MensagemRecebida(tipo="privada", remetente_id=remetente, conversa_id=remetente, texto="oi")


def test_pareamento_conhece_so_as_conversas_privadas_e_o_bot():
    filtro = FiltroContatos()
    assert filtro.registrar_pareamento(CONVERSAS_ANTIGAS, extras=[7555000111, None]) == 5
    assert filtro.pareado
    for conhecido in ("sim:mariana", "sim:lucas", "sim:pedro", "sim:carlos", 7555000111):
        assert filtro.situacao(conhecido) == "conhecido"
    assert filtro.situacao("sim:grupo-familia") == "desconhecido"
    assert filtro.situacao("sim:julia") == "desconhecido"  # salva nos contatos, sem conversa


def test_classificar_antes_do_pareamento_levanta():
    with pytest.raises(SemPareamento):
        FiltroContatos().classificar(_privada("sim:novo-1"), T0)


def test_grupo_e_conhecido_sao_descartados_sem_ler_o_texto():
    filtro = _filtro()
    assert filtro.classificar(MensagemSemLeitura("grupo"), T0) == Decisao("descartar", "grupo")
    assert filtro.classificar(MensagemSemLeitura("privada", "sim:carlos"), T0) == Decisao("descartar", "conhecido")
    assert filtro.classificar(MensagemSemLeitura("privada", None), T0) == Decisao("descartar", "sem_remetente")
    assert filtro.classificar(MensagemSemLeitura("privada", "sim:novo-1"), T0).analisar  # nem o novo é lido


def test_contato_novo_passa_a_observado():
    filtro = _filtro()
    assert filtro.classificar(_privada("sim:novo-1"), T0) == Decisao("analisar", "contato_novo")
    assert filtro.situacao("sim:novo-1") == "observado"
    assert filtro.classificar(_privada("sim:novo-1"), T0 + timedelta(minutes=1)) == Decisao("analisar", "observado")


def test_salvo_sem_conversa_e_analisado():
    filtro = _filtro()
    assert filtro.classificar(_privada("sim:julia"), T0).analisar


def test_ids_inteiros_e_texto_sao_a_mesma_chave():
    filtro = FiltroContatos()
    filtro.registrar_pareamento([ConversaAntiga(123, "privada")])
    assert filtro.classificar(_privada("123"), T0).motivo == "conhecido"


def test_sete_dias_sem_alerta_vira_conhecido_e_e_descartada():
    filtro = _filtro()
    filtro.classificar(_privada("sim:novo-3"), T0)
    quase = T0 + OBSERVACAO - timedelta(seconds=1)
    assert filtro.classificar(_privada("sim:novo-3"), quase).motivo == "observado"
    assert filtro.classificar(_privada("sim:novo-3"), T0 + OBSERVACAO) == Decisao("descartar", "observacao_encerrada")
    assert filtro.situacao("sim:novo-3") == "conhecido"
    assert filtro.classificar(_privada("sim:novo-3"), T0 + OBSERVACAO * 2).motivo == "conhecido"


def test_sete_dias_com_alerta_continua_observado():
    filtro = _filtro()
    filtro.classificar(_privada("sim:novo-1"), T0)
    filtro.registrar_alerta("sim:novo-1")
    assert filtro.classificar(_privada("sim:novo-1"), T0 + timedelta(days=30)) == Decisao("analisar", "observado")
    assert filtro.situacao("sim:novo-1") == "observado"


def test_liberar_e_marcar_conhecido():
    filtro = _filtro()
    filtro.classificar(_privada("sim:novo-2"), T0)
    filtro.registrar_alerta("sim:novo-2")
    assert filtro.liberar("sim:novo-2") is True
    assert filtro.classificar(_privada("sim:novo-2"), T0).motivo == "conhecido"
    assert filtro.contagens()["com_alerta"] == 0
    assert filtro.liberar("sim:novo-9") is False and filtro.situacao("sim:novo-9") == "conhecido"
    filtro.marcar_conhecido("sim:novo-8")
    assert filtro.classificar(_privada("sim:novo-8"), T0).motivo == "conhecido"


def test_registrar_alerta_de_conhecido_nao_muda_nada():
    filtro = _filtro()
    filtro.registrar_alerta("sim:carlos")
    assert filtro.contagens()["com_alerta"] == 0 and filtro.situacao("sim:carlos") == "conhecido"


def test_contagens():
    filtro = _filtro()
    filtro.classificar(_privada("sim:novo-1"), T0)
    filtro.classificar(_privada("sim:novo-1"), T0)
    filtro.classificar(MensagemRecebida(tipo="grupo"), T0)
    filtro.classificar(_privada("sim:carlos"), T0)
    assert filtro.contagens() == {
        "conhecidos": 5,
        "observados": 1,
        "com_alerta": 0,
        "analisadas": 2,
        "descartadas": 2,
        "por_motivo": {"contato_novo": 1, "observado": 1, "grupo": 1, "conhecido": 1},
    }
    assert "sim:" not in repr(filtro)


def test_classificar_sem_agora_usa_o_relogio_do_sistema():
    filtro = _filtro()
    assert filtro.classificar(_privada("sim:novo-1")).motivo == "contato_novo"
