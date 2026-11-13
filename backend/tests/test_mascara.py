import json
import os
import stat

import pytest

from guardiao.mascara import gravar_evidencia, hash_id, mascarar_telefone, validar_campo


def test_hash_id_formato_e_determinismo():
    h = hash_id(123456789)
    assert h.startswith("h:") and len(h) == 14
    assert all(c in "0123456789abcdef" for c in h[2:])
    assert h == hash_id("123456789")
    assert h != hash_id(123456780)


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("5500987651234", "55*******1234"),
        ("+55 (00) 98765-1234", "55*******1234"),
        (5500987651234, "55*******1234"),
        ("123456", "******"),
        ("", None),
        (None, None),
    ],
)
def test_mascarar_telefone(entrada, esperado):
    assert mascarar_telefone(entrada) == esperado


def test_mascara_nao_preserva_digitos_do_meio():
    mascarado = mascarar_telefone("5500987651234")
    assert "98765" not in mascarado


@pytest.mark.parametrize(
    "chave, valor",
    [
        ("texto", "oi"),
        ("mensagem", "x"),
        ("nome", "pedro"),
        ("remetente", 987654321),             # id cru
        ("telefone", "5500987651234"),        # telefone sem máscara
        ("id", "7123456789"),                 # id cru como texto
        ("trecho_qualquer", "oi vó, é o Pedro"),  # texto livre
        ("lista", ["a"]),
        ("telefone", "55-00-98765-1234"),     # dígitos com separador
        ("id", "712.345.678"),
        ("id", 7123456789.0),                 # float grande
    ],
)
def test_validar_campo_recusa_conteudo(chave, valor):
    with pytest.raises(ValueError):
        validar_campo(chave, valor)


@pytest.mark.parametrize(
    "chave, valor",
    [
        ("tipo", "privada"),
        ("remetente", hash_id(987654321)),
        ("telefone", "55*******1234"),
        ("total", 12),
        ("tem_texto", True),
        ("motivo", None),
        ("caso", "teste-a1b2c3"),
        ("alerta_id", "77"),
    ],
)
def test_validar_campo_aceita_metadados(chave, valor):
    validar_campo(chave, valor)


def test_gravar_evidencia_jsonl_modo_600(tmp_path):
    gravar_evidencia("escutar", diretorio=tmp_path, tipo="privada", tem_texto=True)
    gravar_evidencia("escutar", diretorio=tmp_path, tipo="grupo")
    caminho = tmp_path / "escutar.jsonl"
    linhas = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()]
    assert [l["tipo"] for l in linhas] == ["privada", "grupo"]
    assert all(l["verificacao"] == "escutar" for l in linhas)
    assert stat.S_IMODE(os.stat(caminho).st_mode) == 0o600


def test_gravar_evidencia_nao_grava_nada_se_campo_invalido(tmp_path):
    with pytest.raises(ValueError):
        gravar_evidencia("escutar", diretorio=tmp_path, texto="oi vó")
    assert not (tmp_path / "escutar.jsonl").exists()


def test_gravar_evidencia_corrige_modos_abertos(tmp_path):
    pasta = tmp_path / "evid"
    pasta.mkdir(mode=0o755)
    os.chmod(pasta, 0o755)
    arquivo = pasta / "escutar.jsonl"
    arquivo.write_text("")
    os.chmod(arquivo, 0o644)
    gravar_evidencia("escutar", diretorio=pasta, tipo="grupo")
    assert stat.S_IMODE(os.stat(pasta).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(arquivo).st_mode) == 0o600
