"""Nenhuma evidência carrega texto de mensagem, nome, telefone real ou id cru."""

import json

import pytest

import guardiao.mascara as mascara
from guardiao.canal.base import Contato, MensagemRecebida
from guardiao.verificar import _registrar, evidencia_contatos, evidencia_mensagem

TEXTO = "oi vó, é o Pedro, troquei de número, me manda um Pix"
REMETENTE = 7123456789
TELEFONE = "5500987651234"


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(mascara, "EVIDENCIAS_DIR", tmp_path)
    return tmp_path


def _tudo(pasta):
    return "\n".join(p.read_text(encoding="utf-8") for p in pasta.glob("*.jsonl"))


def test_evidencia_de_mensagem_privada_sem_texto(pasta):
    msg = MensagemRecebida(tipo="privada", remetente_id=REMETENTE, conversa_id=REMETENTE, texto=TEXTO)
    dados = evidencia_mensagem(msg)
    assert dados == {
        "tipo": "privada",
        "remetente": mascara.hash_id(REMETENTE),
        "conversa": mascara.hash_id(REMETENTE),
        "tem_texto": True,
    }
    _registrar("escutar", evento="mensagem", **dados)
    conteudo = _tudo(pasta)
    assert "Pedro" not in conteudo and "vó" not in conteudo
    assert str(REMETENTE) not in conteudo


def test_evidencia_de_grupo_so_tipo(pasta):
    msg = MensagemRecebida(tipo="grupo")
    assert evidencia_mensagem(msg) == {"tipo": "grupo"}


def test_evidencia_de_contatos_mascara_telefone_e_omite_nomes(pasta):
    contatos = [Contato(1, "Pedro Silva", TELEFONE), Contato(2, "Ana", None)]
    dados = evidencia_contatos(contatos, "Pedro")
    assert dados == {
        "total": 2,
        "com_telefone": 1,
        "sem_telefone": 1,
        "resultado": "ok",
        "busca": "encontrado_com_telefone",
        "telefone": "55*******1234",
        "encontrados": 1,
    }
    _registrar("contatos", **dados)
    conteudo = _tudo(pasta)
    assert TELEFONE not in conteudo and "Pedro" not in conteudo and "Silva" not in conteudo
    json.loads(conteudo)  # uma linha JSON válida


def test_contatos_vazios_e_resultado_falhou_nao_erro(pasta):
    dados = evidencia_contatos([], "Pedro")
    assert dados["resultado"] == "falhou"
    assert dados["busca"] == "nao_encontrado"


def test_contato_sem_telefone():
    dados = evidencia_contatos([Contato(1, "Pedro", None)], "pedro")
    assert dados["busca"] == "encontrado_sem_telefone"
    assert "telefone" not in dados
