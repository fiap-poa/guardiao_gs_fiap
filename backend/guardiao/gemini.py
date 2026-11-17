"""Cliente do Gemini (Google AI Studio). Único módulo que importa o SDK `google-genai`.

A chave vem de `GEMINI_API_KEY` (Secrets do Colab ou `backend/.env`) e nunca é impressa.

Privacidade: o que vai ao Google são os textos das mensagens do contato novo (no modo
demonstração, fictícios; no modo real, as mensagens recebidas pela conta de teste). Nos
termos da Gemini API, o conteúdo enviado no nível gratuito pode ser usado pelo Google para
melhorar os produtos; por isso o modo real fica restrito a contas de teste da equipe.
O modelo pode ser trocado por `GEMINI_MODELO`. Erros 5xx têm até duas novas tentativas; o
resto (cota, chave inválida, rede) chega a quem chama, que loga só o tipo.
"""

import os
import sys
from typing import Mapping

from guardiao.analise import Detector
from guardiao.config import carregar_env

# conferido em 17/11/2026: o gemini-2.5-flash não aceita mais chaves novas, e os modelos
# "flash" maiores estavam respondendo 503/504 por demanda; o lite acertou o conjunto do CAP-3
MODELO_PADRAO = "gemini-3.5-flash-lite"
TIMEOUT_S = 30
# até duas novas tentativas só para sobrecarga e erro do servidor (não para cota esgotada, 429)
TENTATIVAS = 3
STATUS_REPETIR = (500, 502, 503, 504)


class RespostaVazia(RuntimeError):
    """O Gemini respondeu sem texto (bloqueio de segurança, cota…)."""


class ClienteGemini:
    """`gerar_json` com saída JSON pelo esquema e temperatura 0."""

    def __init__(self, chave: str, modelo: str | None = None, timeout_s: float = TIMEOUT_S, cliente=None):
        from google.genai import types

        self._types = types
        self.modelo = modelo or MODELO_PADRAO
        if cliente is None:
            from google import genai

            opcoes = types.HttpOptions(
                timeout=int(timeout_s * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=TENTATIVAS, initial_delay=1.0, http_status_codes=list(STATUS_REPETIR)
                ),
            )
            cliente = genai.Client(api_key=chave, http_options=opcoes)
        self._cliente = cliente

    def __repr__(self) -> str:  # nunca mostrar a chave
        return f"ClienteGemini(modelo={self.modelo!r})"

    def gerar_json(self, instrucao: str, conteudo: str, esquema: dict) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=instrucao,
            temperature=0,
            response_mime_type="application/json",
            response_schema=esquema,
        )
        resposta = self._cliente.models.generate_content(model=self.modelo, contents=conteudo, config=config)
        texto = getattr(resposta, "text", None)
        if not texto:
            raise RespostaVazia("o Gemini respondeu sem texto")
        return texto


def criar_detector(ambiente: Mapping[str, str] | None = None) -> Detector | None:
    """Detector com o Gemini; sem `GEMINI_API_KEY`, `None` com aviso (recepção e filtro seguem)."""
    if ambiente is None:
        carregar_env()
        ambiente = os.environ
    chave = (ambiente.get("GEMINI_API_KEY") or "").strip()
    if not chave:
        print("[análise] aviso: GEMINI_API_KEY ausente; a detecção fica desligada", file=sys.stderr)
        return None
    modelo = (ambiente.get("GEMINI_MODELO") or "").strip() or None
    return Detector(ClienteGemini(chave, modelo))
