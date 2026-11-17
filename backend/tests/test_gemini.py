"""Cliente do Gemini com um cliente do SDK falso (sem rede)."""

import json
from types import SimpleNamespace

import pytest

from guardiao.analise import ESQUEMA, INSTRUCAO_SISTEMA, Detector
from guardiao.gemini import MODELO_PADRAO, ClienteGemini, RespostaVazia, criar_detector

CHAVE_FALSA = "chave-falsa-de-teste"


class ModelosFalsos:
    def __init__(self, texto):
        self.texto = texto
        self.chamadas = []

    def generate_content(self, model, contents, config):
        self.chamadas.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.texto)


def _cliente(texto='{"alega_parentesco": false, "pede_dinheiro": false}', modelo=None):
    modelos = ModelosFalsos(texto)
    return ClienteGemini(CHAVE_FALSA, modelo, cliente=SimpleNamespace(models=modelos)), modelos


def test_gerar_json_pede_saida_json_pelo_esquema_com_temperatura_zero():
    cliente, modelos = _cliente()
    assert cliente.gerar_json(INSTRUCAO_SISTEMA, "<conversa>\n[1] oi\n</conversa>", ESQUEMA)
    (chamada,) = modelos.chamadas
    config = chamada["config"]
    assert chamada["model"] == MODELO_PADRAO
    assert chamada["contents"] == "<conversa>\n[1] oi\n</conversa>"
    assert config.system_instruction == INSTRUCAO_SISTEMA
    assert config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None


def test_esquema_aceito_pelo_sdk():
    from google.genai import types

    schema = types.Schema.model_validate(ESQUEMA)
    assert set(schema.properties) == set(ESQUEMA["properties"])
    assert schema.properties["parentesco"].nullable is True


def test_detector_com_o_cliente_gemini():
    resposta = {
        "alega_parentesco": True,
        "nome_alegado": "Pedro",
        "parentesco": "neto",
        "pede_dinheiro": True,
        "forma_pagamento": "pix",
        "motivo": "aluguel",
        "mensagem_do_pedido": 2,
    }
    cliente, _ = _cliente(json.dumps(resposta))
    assert Detector(cliente).analisar(["Oi vó, é o Pedro", "Faz um Pix?"]).suspeita


def test_resposta_vazia_levanta():
    cliente, _ = _cliente(texto=None)
    with pytest.raises(RespostaVazia):
        cliente.gerar_json("i", "c", ESQUEMA)


def test_repr_sem_chave():
    cliente, _ = _cliente(modelo="gemini-x")
    assert CHAVE_FALSA not in repr(cliente) and "gemini-x" in repr(cliente)


def test_cliente_real_criado_sem_rede():
    cliente = ClienteGemini(CHAVE_FALSA)  # o SDK só acessa a rede ao gerar
    assert cliente.modelo == MODELO_PADRAO and CHAVE_FALSA not in repr(cliente)


def test_criar_detector_sem_chave_avisa_e_devolve_none(capsys):
    assert criar_detector({}) is None
    assert criar_detector({"GEMINI_API_KEY": "  "}) is None
    assert "GEMINI_API_KEY ausente" in capsys.readouterr().err


def test_criar_detector_com_chave_e_modelo(capsys):
    detector = criar_detector({"GEMINI_API_KEY": CHAVE_FALSA, "GEMINI_MODELO": "gemini-outro"})
    assert isinstance(detector, Detector) and detector.cliente.modelo == "gemini-outro"
    assert criar_detector({"GEMINI_API_KEY": CHAVE_FALSA, "GEMINI_MODELO": ""}).cliente.modelo == MODELO_PADRAO
    assert CHAVE_FALSA not in capsys.readouterr().err


def test_criar_detector_le_o_ambiente(monkeypatch):
    monkeypatch.setattr("guardiao.gemini.carregar_env", lambda: False)
    monkeypatch.setenv("GEMINI_API_KEY", CHAVE_FALSA)
    monkeypatch.delenv("GEMINI_MODELO", raising=False)
    assert criar_detector().cliente.modelo == MODELO_PADRAO


def test_cliente_real_com_timeout_e_novas_tentativas_so_para_5xx(monkeypatch):
    from google import genai

    from guardiao.gemini import STATUS_REPETIR, TENTATIVAS

    criados = []
    monkeypatch.setattr(genai, "Client", lambda **kwargs: criados.append(kwargs) or SimpleNamespace(models=None))
    ClienteGemini(CHAVE_FALSA, timeout_s=12)
    [argumentos] = criados
    opcoes = argumentos["http_options"]
    assert argumentos["api_key"] == CHAVE_FALSA
    assert opcoes.timeout == 12000
    assert opcoes.retry_options.attempts == TENTATIVAS == 3
    assert 429 not in STATUS_REPETIR and set(opcoes.retry_options.http_status_codes) == set(STATUS_REPETIR)
