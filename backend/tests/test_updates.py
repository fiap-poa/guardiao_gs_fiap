from types import SimpleNamespace

from guardiao.canal.base import InicioBot, RespostaAlerta
from guardiao.canal.telegram import ToqueBot, interpretar_update, mensagem_de_evento


def _callback(data):
    return {
        "update_id": 10,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 222},
            "message": {"message_id": 77, "chat": {"id": 222, "type": "private"}},
            "data": data,
        },
    }


def _mensagem(texto, tipo="private"):
    return {
        "update_id": 11,
        "message": {
            "message_id": 5,
            "date": 1731400000,
            "from": {"id": 333},
            "chat": {"id": 333 if tipo == "private" else -100, "type": tipo},
            "text": texto,
        },
    }


def test_callback_golpe():
    evento = interpretar_update(_callback("golpe:c1"))
    assert isinstance(evento, ToqueBot)
    assert evento.callback_id == "cb-1"
    assert isinstance(evento.resposta, RespostaAlerta)
    assert evento.resposta.resposta == "golpe"
    assert evento.resposta.caso_id == "c1"
    assert evento.resposta.alerta_id == "77"
    assert evento.resposta.respondente_id == 222


def test_callback_era_ele_mesmo():
    evento = interpretar_update(_callback("ele_mesmo:c9"))
    assert evento.resposta.resposta == "era_ele_mesmo"
    assert evento.resposta.caso_id == "c9"


def test_callback_desconhecido_ainda_e_respondido_mas_sem_resposta():
    for dados in ("outro:c1", "golpe:", "", None):
        evento = interpretar_update(_callback(dados))
        assert isinstance(evento, ToqueBot)
        assert evento.resposta is None


def test_start_em_chat_privado():
    for texto in ("/start", "/start abc", "/start@guardiao_bot"):
        evento = interpretar_update(_mensagem(texto))
        assert isinstance(evento, InicioBot)
        assert evento.usuario_id == 333
        assert evento.destinatario == 333


def test_start_em_grupo_e_outras_mensagens_sao_ignorados():
    assert interpretar_update(_mensagem("/start", tipo="group")) is None
    assert interpretar_update(_mensagem("oi")) is None
    assert interpretar_update(_mensagem("/startx")) is None
    assert interpretar_update(_mensagem(None)) is None
    assert interpretar_update({"update_id": 1}) is None


def test_mensagem_de_evento_privada():
    evento = SimpleNamespace(is_private=True, sender_id=444, chat_id=444, raw_text="oi vó", date=None)
    mensagem = mensagem_de_evento(evento)
    assert mensagem.tipo == "privada"
    assert mensagem.remetente_id == 444
    assert mensagem.tem_texto


def test_mensagem_de_evento_grupo_nao_le_texto_nem_ids():
    evento = SimpleNamespace(is_private=False, sender_id=444, chat_id=-100, raw_text="segredo", date=None)
    mensagem = mensagem_de_evento(evento)
    assert mensagem.tipo == "grupo"
    assert mensagem.texto is None
    assert mensagem.remetente_id is None and mensagem.conversa_id is None


def test_start_traz_o_codigo_e_o_primeiro_nome():
    update = _mensagem("/start abc_DEF-123")
    update["message"]["from"]["first_name"] = "Ana"
    evento = interpretar_update(update)
    assert evento.parametro == "abc_DEF-123" and evento.nome == "Ana"
    assert "abc_DEF-123" not in repr(evento) and "Ana" not in repr(evento)
    assert interpretar_update(_mensagem("/start@guardiao_bot xyz")).parametro == "xyz"


def test_start_sem_codigo_nem_nome():
    evento = interpretar_update(_mensagem("/start"))
    assert evento.parametro is None and evento.nome is None
    update = _mensagem("/start   ")
    update["message"]["from"]["first_name"] = "  "
    evento = interpretar_update(update)
    assert evento.parametro is None and evento.nome is None
