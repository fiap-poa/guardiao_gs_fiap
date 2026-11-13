"""Canal Telegram sem rede: Bot API falsa e sessão em pasta temporária."""

import threading

import pytest
import requests

from guardiao.canal.base import Alerta, InicioBot, RespostaAlerta
from guardiao.canal.telegram import BotAPI, ErroBotAPI, SemSessao, TelegramCanal

TOKEN = "123456:SEGREDO-do-bot"


class HttpFalho:
    def post(self, url, json=None, timeout=None):
        raise requests.ConnectionError(f"falhou ao abrir {url}")


def test_erro_da_bot_api_nao_vaza_token():
    bot = BotAPI(TOKEN, sessao_http=HttpFalho())
    with pytest.raises(ErroBotAPI) as erro:
        bot.get_me()
    assert TOKEN not in str(erro.value)
    assert erro.value.__cause__ is None and erro.value.__suppress_context__
    assert TOKEN not in repr(bot)


class BotFalso:
    def __init__(self, lotes, falhar_resposta=False):
        self.lotes = list(lotes)  # cada lote: lista de updates ou exceção a levantar
        self.falhar_resposta = falhar_resposta
        self.respondidos = []
        self.enviados = []
        self.offsets = []
        self.vazio = threading.Event()

    def get_updates(self, offset, timeout):
        self.offsets.append(offset)
        if self.lotes:
            lote = self.lotes.pop(0)
            if isinstance(lote, Exception):
                raise lote
            return lote
        self.vazio.set()
        return []

    def answer_callback_query(self, callback_id, texto=None):
        self.respondidos.append((callback_id, texto))
        if self.falhar_resposta:
            raise ErroBotAPI("answerCallbackQuery: 400 query is too old")

    def send_message(self, chat_id, texto, reply_markup=None):
        self.enviados.append((chat_id, texto, reply_markup))
        return {"message_id": 77}


def _canal(tmp_path, bot):
    canal = TelegramCanal(None, None, TOKEN, dir_sessao=tmp_path, usar_conta=False, espera_polling=0)
    canal._bot = bot
    canal._pausa_erro = 0.01
    return canal


def test_polling_entrega_start_e_toque_e_responde_o_toque(tmp_path):
    bot = BotFalso([
        [{"update_id": 1, "message": {"from": {"id": 9}, "chat": {"id": 9, "type": "private"},
                                       "text": "/start", "date": 1}}],
        [{"update_id": 2, "callback_query": {"id": "cb", "from": {"id": 9},
                                              "message": {"message_id": 77}, "data": "golpe:c1"}}],
    ])
    canal = _canal(tmp_path, bot)
    recebidos = []
    canal.receber_mensagens(recebidos.append)
    assert bot.vazio.wait(5)
    canal.fechar()
    assert isinstance(recebidos[0], InicioBot) and recebidos[0].destinatario == 9
    assert isinstance(recebidos[1], RespostaAlerta) and recebidos[1].resposta == "golpe"
    assert bot.respondidos == [("cb", "Resposta registrada.")]
    assert bot.offsets[0] is None and bot.offsets[-1] == 3  # confirma o último update


def test_enviar_alerta_usa_template_e_botoes(tmp_path):
    bot = BotFalso([])
    canal = _canal(tmp_path, bot)
    alerta = Alerta(9, "c1", "Pedro", "sua mãe", "oi vó")
    assert canal.enviar_alerta(alerta) == "77"
    chat, texto, teclado = bot.enviados[0]
    assert chat == 9 and texto.startswith("Um número novo está dizendo ser Pedro")
    assert [b["callback_data"] for b in teclado["inline_keyboard"][0]] == ["golpe:c1", "ele_mesmo:c1"]


def test_sem_sessao_nao_cria_arquivo(tmp_path):
    canal = TelegramCanal(1, "x", None, dir_sessao=tmp_path, usar_bot=False)
    assert canal.sair() == "sem_sessao"
    with pytest.raises(SemSessao):
        canal.conectar()
    canal.fechar()
    assert list(tmp_path.iterdir()) == []


START = {"update_id": 1, "message": {"from": {"id": 9}, "chat": {"id": 9, "type": "private"},
                                      "text": "/start", "date": 1}}


def _toque(dados, update_id=2):
    return {"update_id": update_id, "callback_query": {"id": "cb", "from": {"id": 9},
                                                       "message": {"message_id": 77}, "data": dados}}


def _rodar_laco(tmp_path, bot, handler):
    canal = _canal(tmp_path, bot)
    canal.receber_mensagens(handler)
    assert bot.vazio.wait(5)
    canal.fechar()


def test_laco_continua_apos_falha_no_get_updates(tmp_path):
    bot = BotFalso([ErroBotAPI("getUpdates: 502 Bad Gateway"), [START]])
    recebidos = []
    _rodar_laco(tmp_path, bot, recebidos.append)
    assert [type(e).__name__ for e in recebidos] == ["InicioBot"]


def test_laco_entrega_resposta_mesmo_se_answer_callback_falhar(tmp_path):
    bot = BotFalso([[_toque("golpe:c1")]], falhar_resposta=True)
    recebidos = []
    _rodar_laco(tmp_path, bot, recebidos.append)
    assert bot.respondidos == [("cb", "Resposta registrada.")]
    assert isinstance(recebidos[0], RespostaAlerta) and recebidos[0].caso_id == "c1"


def test_laco_continua_apos_handler_levantar(tmp_path):
    bot = BotFalso([[START, _toque("ele_mesmo:c1")]])
    recebidos = []

    def handler(evento):
        if not recebidos and isinstance(evento, InicioBot):
            recebidos.append("falhou")
            raise RuntimeError("handler quebrou")
        recebidos.append(evento)

    _rodar_laco(tmp_path, bot, handler)
    assert recebidos[0] == "falhou"
    assert isinstance(recebidos[1], RespostaAlerta) and recebidos[1].resposta == "era_ele_mesmo"


def test_toque_desconhecido_e_respondido_sem_texto_e_nao_chega_ao_handler(tmp_path):
    bot = BotFalso([[_toque("outro:c1")]])
    recebidos = []
    _rodar_laco(tmp_path, bot, recebidos.append)
    assert bot.respondidos == [("cb", None)]
    assert recebidos == []


class RespostaHttp:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo

    def json(self):
        if self._corpo is None:
            raise ValueError("não é JSON")
        return self._corpo


class HttpFixo:
    def __init__(self, resposta):
        self.resposta = resposta

    def post(self, url, json=None, timeout=None):
        return self.resposta


def test_bot_api_ok_false_levanta_sem_token():
    corpo = {"ok": False, "error_code": 401, "description": "Unauthorized"}
    bot = BotAPI(TOKEN, sessao_http=HttpFixo(RespostaHttp(401, corpo)))
    with pytest.raises(ErroBotAPI) as erro:
        bot.get_me()
    assert "401" in str(erro.value) and "Unauthorized" in str(erro.value)
    assert TOKEN not in str(erro.value)


def test_bot_api_resposta_nao_json_levanta_sem_token():
    bot = BotAPI(TOKEN, sessao_http=HttpFixo(RespostaHttp(502)))
    with pytest.raises(ErroBotAPI) as erro:
        bot.get_me()
    assert str(erro.value) == "getMe: HTTP 502"
    assert erro.value.__suppress_context__
