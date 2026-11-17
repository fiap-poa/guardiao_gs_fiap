"""Cadastro da responsável pelo Iniciar com código de uso único (CAP-7)."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from guardiao.cadastro import (
    TEXTO_BOT_PRIVADO,
    VALIDADE_CODIGO,
    CadastroResponsavel,
    JaCadastrada,
    texto_pronto,
)
from guardiao.canal.base import InicioBot
from guardiao.recepcao import RelogioAjustavel

RESPONSAVEL = 7987654321
OUTRA = 7111222333
PRONTO_ANA = "Pronto, Ana. Você vai receber aqui os alertas do Guardião sobre Dona Maria."


@pytest.fixture
def relogio():
    inicio = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    return RelogioAjustavel(base=lambda: inicio)


@pytest.fixture
def cadastro(relogio):
    return CadastroResponsavel("Dona Maria", relogio=relogio)


def _inicio(usuario=RESPONSAVEL, codigo=None, nome="Ana"):
    return InicioBot(usuario_id=usuario, destinatario=usuario, parametro=codigo, nome=nome)


def test_textos_do_modelo():
    assert texto_pronto("Ana", "Dona Maria") == PRONTO_ANA
    assert texto_pronto(None, "Dona Maria").startswith("Pronto. Você vai receber")
    assert TEXTO_BOT_PRIVADO == (
        "Este bot é privado. Para usar o Guardião, abra o link mostrado na tela de configuração."
    )


def test_codigo_tem_22_caracteres_validos_para_o_start(cadastro):
    codigo = cadastro.gerar_codigo()
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", codigo)
    assert cadastro.gerar_codigo() != codigo
    assert cadastro.estado() == {"responsavel_cadastrada": False, "codigos_validos": 2}


def test_link_usa_o_username_do_bot(cadastro):
    link = cadastro.link("@guardiao_teste_bot")
    assert re.fullmatch(r"https://t\.me/guardiao_teste_bot\?start=[A-Za-z0-9_-]{22}", link)
    assert cadastro.link("guardiao_teste_bot", "abc") == "https://t.me/guardiao_teste_bot?start=abc"
    with pytest.raises(ValueError):
        cadastro.link("")


def test_codigo_valido_cadastra_e_invalida_todos(cadastro):
    primeiro, segundo = cadastro.gerar_codigo(), cadastro.gerar_codigo()
    resultado = cadastro.tratar_inicio(_inicio(codigo=segundo))
    assert resultado.cadastrou and resultado.motivo == "cadastrada"
    assert resultado.destinatario == RESPONSAVEL and resultado.resposta == PRONTO_ANA
    assert cadastro.cadastrada and cadastro.responsavel.usuario_id == RESPONSAVEL
    assert cadastro.estado() == {"responsavel_cadastrada": True, "codigos_validos": 0}
    for codigo in (primeiro, segundo):  # os dois códigos deixam de valer
        outra = cadastro.tratar_inicio(_inicio(OUTRA, codigo))
        assert not outra.cadastrou and outra.motivo == "codigo_usado" and outra.resposta == TEXTO_BOT_PRIVADO
    assert cadastro.responsavel.usuario_id == RESPONSAVEL


def test_segundo_iniciar_com_o_mesmo_codigo_recebe_bot_privado(cadastro):
    codigo = cadastro.gerar_codigo()
    assert cadastro.tratar_inicio(_inicio(codigo=codigo)).cadastrou
    de_novo = cadastro.tratar_inicio(_inicio(codigo=codigo))
    assert not de_novo.cadastrou and de_novo.resposta == TEXTO_BOT_PRIVADO


def test_depois_do_cadastro_gerar_codigo_falha_e_iniciar_dela_repete_o_pronto(cadastro):
    cadastro.tratar_inicio(_inicio(codigo=cadastro.gerar_codigo()))
    with pytest.raises(JaCadastrada):
        cadastro.gerar_codigo()
    antes = cadastro.responsavel
    repetido = cadastro.tratar_inicio(_inicio(nome="Outro nome"))
    assert not repetido.cadastrou and repetido.motivo == "ja_cadastrada" and repetido.resposta == PRONTO_ANA
    assert cadastro.responsavel is antes
    estranha = cadastro.tratar_inicio(_inicio(OUTRA))
    assert estranha.motivo == "sem_codigo" and estranha.resposta == TEXTO_BOT_PRIVADO


@pytest.mark.parametrize("codigo, motivo", [(None, "sem_codigo"), ("", "sem_codigo"), ("inventado", "codigo_invalido")])
def test_iniciar_invalido_nao_cadastra(cadastro, codigo, motivo):
    cadastro.gerar_codigo()
    resultado = cadastro.tratar_inicio(_inicio(codigo=codigo))
    assert not resultado.cadastrou and resultado.motivo == motivo
    assert resultado.resposta == TEXTO_BOT_PRIVADO and resultado.destinatario == RESPONSAVEL
    assert not cadastro.cadastrada


def test_codigo_vencido_nao_cadastra(cadastro, relogio):
    codigo = cadastro.gerar_codigo()
    relogio.adiantar(minutes=29, seconds=59)
    valido = cadastro.gerar_codigo()
    relogio.adiantar(seconds=1)  # 30 min exatos do primeiro
    resultado = cadastro.tratar_inicio(_inicio(codigo=codigo))
    assert resultado.motivo == "codigo_vencido" and not cadastro.cadastrada
    assert cadastro.tratar_inicio(_inicio(codigo=codigo)).motivo == "codigo_invalido"
    assert cadastro.tratar_inicio(_inicio(codigo=valido)).cadastrou


def test_vencidos_saem_do_estado(cadastro, relogio):
    cadastro.gerar_codigo()
    relogio.adiantar(minutes=VALIDADE_CODIGO.total_seconds() / 60)
    assert cadastro.estado()["codigos_validos"] == 0


def test_repr_nao_mostra_ids_nem_nome(cadastro):
    resultado = cadastro.tratar_inicio(_inicio(codigo=cadastro.gerar_codigo()))
    texto = repr(cadastro) + repr(cadastro.responsavel) + repr(resultado)
    assert str(RESPONSAVEL) not in texto and "Ana" not in texto
    inicio = repr(_inicio(codigo="xyz"))  # o id é opaco, mas código e nome ficam fora do repr
    assert "xyz" not in inicio and "Ana" not in inicio
