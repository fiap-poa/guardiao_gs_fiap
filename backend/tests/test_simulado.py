"""Canal simulado, cenários e fábrica (história 3), sem rede."""

import os
import re
import socket
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

import guardiao.config as config
from guardiao.canal.base import Alerta, Contato, InicioBot, MensagemRecebida, RespostaAlerta, procurar_contatos
from guardiao.canal.cenarios import (
    CENARIOS,
    CONTATOS,
    CONVERSAS_ANTIGAS,
    ID_IDOSA,
    TELEFONE_IDOSA,
    listar_cenarios,
    obter_cenario,
)
from guardiao.canal.fabrica import criar_canal
from guardiao.canal.simulado import CanalSimulado, SemSaida, descrever_recebido, formatar_celular

TELEFONE_FICTICIO = re.compile(r"^5500\d{9}$")
IDS_CENARIOS = [
    "golpe_classico",
    "parente_trocou_numero",
    "contato_antigo_pede_dinheiro",
    "mensagem_em_grupo",
    "contato_novo_sem_dinheiro",
]


@pytest.fixture
def sem_rede(monkeypatch):
    """Qualquer tentativa de abrir socket falha o teste."""

    def proibido(*args, **kwargs):
        raise AssertionError("tentou acessar a rede")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)


def _canal(saida=None):
    canal = CanalSimulado(saida=saida)
    recebidos = []
    canal.receber_mensagens(recebidos.append)
    return canal, recebidos


# --------------------------------------------------------------------------- dados fictícios


def test_cinco_cenarios_com_esperado():
    assert [c.id for c in listar_cenarios()] == IDS_CENARIOS
    assert {c.id: c.esperado for c in CENARIOS} == {
        "golpe_classico": "alerta",
        "parente_trocou_numero": "alerta_era_ele_mesmo",
        "contato_antigo_pede_dinheiro": "ignorado",
        "mensagem_em_grupo": "ignorado",
        "contato_novo_sem_dinheiro": "sem_alerta",
    }
    for cenario in CENARIOS:
        assert cenario.descricao and cenario.mensagens and all(cenario.mensagens)


def test_todo_telefone_ficticio_tem_ddd_00():
    telefones = [TELEFONE_IDOSA] + [c.telefone for c in CONTATOS]
    telefones += [c.remetente_telefone for c in CENARIOS if c.remetente_telefone]
    assert telefones and all(TELEFONE_FICTICIO.match(t) for t in telefones), telefones
    for cenario in CENARIOS:
        if cenario.remetente_nome.startswith("+"):
            assert cenario.remetente_nome.startswith("+55 00 ")


def test_contatos_e_conversas_antigas():
    assert [c.id for c in CONTATOS] == ["sim:mariana", "sim:lucas", "sim:pedro", "sim:julia", "sim:carlos"]
    assert all(isinstance(c, Contato) for c in CONTATOS)
    antigas = {c.conversa_id: c.tipo for c in CONVERSAS_ANTIGAS}
    assert antigas == {
        "sim:mariana": "privada",
        "sim:lucas": "privada",
        "sim:pedro": "privada",
        "sim:carlos": "privada",
        "sim:grupo-familia": "grupo",
    }
    assert [c.nome for c in CONVERSAS_ANTIGAS if c.tipo == "grupo"] == ["Família"]


def test_origem_dos_cenarios_bate_com_as_conversas_antigas():
    antigas = {c.conversa_id for c in CONVERSAS_ANTIGAS}
    contatos = {c.id for c in CONTATOS}
    for cenario in CENARIOS:
        if cenario.origem == "novo":
            assert cenario.remetente_id.startswith("sim:novo-")
            assert cenario.conversa_id == cenario.remetente_id
            assert cenario.conversa_id not in antigas and cenario.remetente_id not in contatos
        elif cenario.origem == "antigo":
            assert cenario.conversa_id == cenario.remetente_id and cenario.conversa_id in antigas
        else:
            assert cenario.conversa_id == "sim:grupo-familia"


def test_parentes_alegados_estao_nos_contatos():
    assert [c.telefone for c in procurar_contatos(list(CONTATOS), "Pedro")] == ["5500987650003"]
    assert [c.telefone for c in procurar_contatos(list(CONTATOS), "lucas")] == ["5500987650002"]
    assert [c.nome for c in procurar_contatos(list(CONTATOS), "Julia")] == ["Júlia Neta"]


def test_cenario_desconhecido_levanta_key_error_com_o_nome():
    with pytest.raises(KeyError, match="'x'"):
        obter_cenario("x")
    canal, recebidos = _canal()
    with pytest.raises(KeyError, match="'x'"):
        canal.injetar("x")
    assert recebidos == [] and canal.celular() == []


# --------------------------------------------------------------------------- injeção (matriz I/O)


def test_golpe_classico(sem_rede):
    canal, recebidos = _canal()
    entregues = canal.injetar("golpe_classico")
    assert recebidos == entregues and len(recebidos) == 2
    assert all(m.tipo == "privada" and m.remetente_id == "sim:novo-1" == m.conversa_id for m in recebidos)
    assert "Pedro" in recebidos[0].texto and "Pix" in recebidos[1].texto
    assert obter_cenario("golpe_classico").esperado == "alerta"


def test_parente_trocou_numero(sem_rede):
    canal, recebidos = _canal()
    canal.injetar("parente_trocou_numero")
    assert {m.remetente_id for m in recebidos} == {"sim:novo-2"}
    assert "Lucas" in recebidos[0].texto and "transferência" in recebidos[1].texto


def test_contato_antigo_pede_dinheiro(sem_rede):
    canal, recebidos = _canal()
    canal.injetar("contato_antigo_pede_dinheiro")
    assert [(m.tipo, m.remetente_id) for m in recebidos] == [("privada", "sim:carlos")]
    assert "sim:carlos" in {c.conversa_id for c in canal.conversas_existentes()}


def test_mensagem_em_grupo_chega_so_com_o_tipo(sem_rede):
    canal, recebidos = _canal()
    canal.injetar("mensagem_em_grupo")
    assert recebidos == [MensagemRecebida(tipo="grupo", recebida_em=recebidos[0].recebida_em)]
    assert recebidos[0].remetente_id is None and recebidos[0].conversa_id is None
    assert recebidos[0].texto is None


def test_contato_novo_sem_dinheiro(sem_rede):
    canal, recebidos = _canal()
    canal.injetar("contato_novo_sem_dinheiro")
    assert {m.remetente_id for m in recebidos} == {"sim:novo-3"}
    texto = " ".join(m.texto for m in recebidos).lower()
    assert "júlia" in texto and not re.search(r"pix|transfer|r\$|boleto|dinheiro", texto)


def test_cinco_cenarios_sem_token_nao_acessam_a_rede(sem_rede, capsys):
    canal = criar_canal("demonstracao", ambiente={})
    assert not canal.tem_bot
    assert "TELEGRAM_BOT_TOKEN ausente" in capsys.readouterr().err
    recebidos = []
    canal.receber_mensagens(recebidos.append)
    for cenario_id in IDS_CENARIOS:
        canal.injetar(cenario_id)
    assert len(recebidos) == sum(len(c.mensagens) for c in CENARIOS)
    assert [m.tipo for m in recebidos].count("grupo") == 1
    with pytest.raises(SemSaida):
        canal.enviar_alerta(Alerta("resp", "c1", "Pedro", "sua mãe", "oi vó"))
    canal.fechar()


def test_injecao_chama_o_handler_na_thread_de_quem_injeta():
    threads = []
    canal = CanalSimulado()
    canal.receber_mensagens(lambda evento: threads.append(threading.current_thread()))
    resultado = []
    t = threading.Thread(target=lambda: resultado.append(canal.injetar("golpe_classico")))
    t.start()
    t.join(5)
    assert threads == [t, t] and len(resultado[0]) == 2


def test_injetar_antes_de_receber_mensagens_levanta():
    with pytest.raises(RuntimeError, match="receber_mensagens"):
        CanalSimulado().injetar("golpe_classico")


def test_injetar_mensagem_avulsa():
    canal, recebidos = _canal()
    privada = canal.injetar_mensagem("sim:novo-9", "oi, sou eu", de="+55 00 98765-1009")
    assert privada == recebidos[0] and privada.conversa_id == "sim:novo-9" and privada.texto == "oi, sou eu"
    grupo = canal.injetar_mensagem("sim:mariana", "oi grupo", tipo="grupo", conversa_id="sim:grupo-familia")
    assert grupo.tipo == "grupo" and grupo.texto is None
    with pytest.raises(ValueError):
        canal.injetar_mensagem("sim:mariana", "oi", tipo="grupo")
    with pytest.raises(ValueError):
        canal.injetar_mensagem("sim:mariana", "oi", tipo="canal")
    assert [linha.de for linha in canal.celular()] == ["+55 00 98765-1009", "sim:mariana"]


def test_handler_que_levanta_nao_interrompe_a_injecao(capsys):
    canal = CanalSimulado()
    vistos = []

    def handler(evento):
        vistos.append(evento)
        raise RuntimeError("conteúdo sensível")

    canal.receber_mensagens(handler)
    assert len(canal.injetar("golpe_classico")) == 2 and len(vistos) == 2
    erro = capsys.readouterr().err
    assert "RuntimeError" in erro and "conteúdo sensível" not in erro


# --------------------------------------------------------------------------- celular e saída


class SaidaFalsa:
    def __init__(self):
        self.handler = None
        self.alertas = []
        self.avisos = []
        self.fechada = False

    def receber_mensagens(self, handler):
        self.handler = handler

    def enviar_alerta(self, alerta):
        self.alertas.append(alerta)
        return "77"

    def enviar_aviso(self, destinatario, texto):
        self.avisos.append((destinatario, texto))
        return "78"

    def fechar(self):
        self.fechada = True


def test_aviso_a_idosa_vai_para_o_celular_e_nao_sai_pelo_bot():
    saida = SaidaFalsa()
    canal, _ = _canal(saida)
    assert canal.id_idosa == ID_IDOSA
    assert canal.enviar_aviso(ID_IDOSA, "Dona Maria, não faça nenhum Pix agora.") == "sim:aviso-1"
    assert saida.avisos == [] and saida.alertas == []
    [linha] = canal.celular()
    assert linha.tipo == "aviso" and linha.texto == "Dona Maria, não faça nenhum Pix agora."
    assert "não faça nenhum Pix agora" in formatar_celular(canal.celular())


def test_aviso_a_outro_destino_e_alerta_vao_pela_saida():
    saida = SaidaFalsa()
    canal, _ = _canal(saida)
    assert canal.enviar_aviso(9, "oi") == "78" and saida.avisos == [(9, "oi")]
    alerta = Alerta(9, "c1", "Pedro", "sua mãe", "oi vó")
    assert canal.enviar_alerta(alerta) == "77" and saida.alertas == [alerta]
    assert canal.celular() == []
    canal.fechar()
    assert saida.fechada


def test_sem_saida_aviso_a_outro_destino_levanta():
    canal, _ = _canal()
    with pytest.raises(SemSaida):
        canal.enviar_aviso(9, "oi")
    assert canal.enviar_aviso(ID_IDOSA, "oi").startswith("sim:aviso-")


def test_eventos_do_bot_chegam_ao_mesmo_handler():
    saida = SaidaFalsa()
    canal, recebidos = _canal(saida)
    saida.handler(InicioBot(usuario_id=9, destinatario=9))
    saida.handler(RespostaAlerta("77", "c1", "golpe", 9))
    canal.injetar("golpe_classico")
    assert [type(e).__name__ for e in recebidos] == ["InicioBot", "RespostaAlerta"] + ["MensagemRecebida"] * 2


def test_celular_mostra_as_mensagens_recebidas():
    canal, _ = _canal()
    canal.injetar("golpe_classico")
    canal.injetar("mensagem_em_grupo")
    linhas = canal.celular()
    assert [l.tipo for l in linhas] == ["recebida"] * 3
    assert linhas[0].de == "+55 00 98765-1001" and linhas[2].de == "Família"
    texto = formatar_celular(linhas)
    assert texto.startswith("Celular de Dona Maria") and "pizza" in texto
    assert "nada por enquanto" in formatar_celular([])


def test_descrever_recebido():
    assert "tipo=grupo" in descrever_recebido(MensagemRecebida(tipo="grupo"))
    privada = MensagemRecebida(tipo="privada", remetente_id="sim:novo-1", conversa_id="sim:novo-1", texto="oi")
    assert descrever_recebido(privada) == 'MensagemRecebida(tipo=privada, de=sim:novo-1): "oi"'
    assert "9" not in descrever_recebido(InicioBot(7123456789, 7123456789))
    resposta = descrever_recebido(RespostaAlerta("77", "c1", "golpe", 7123456789))
    assert "resposta=golpe" in resposta and "7123456789" not in resposta
    real = MensagemRecebida(tipo="privada", remetente_id=7123456789, conversa_id=7123456789, texto="segredo")
    assert "segredo" not in descrever_recebido(real) and "7123456789" not in descrever_recebido(real)


# --------------------------------------------------------------------------- fábrica

TOKEN_FALSO = "123456:token-falso"


def test_fabrica_demonstracao_com_token_usa_o_bot_como_saida(sem_rede):
    from guardiao.canal.telegram import TelegramCanal

    canal = criar_canal("demonstracao", ambiente={"TELEGRAM_BOT_TOKEN": TOKEN_FALSO})
    assert isinstance(canal, CanalSimulado) and canal.tem_bot
    saida = canal.saida
    assert isinstance(saida, TelegramCanal) and saida.usar_bot and not saida.usar_conta
    assert saida._espera_polling == 5
    assert TOKEN_FALSO not in repr(canal) + repr(saida)


def test_fabrica_demonstracao_com_token_entrega_start_e_toque(tmp_path):
    """Com token, `/start` e toque chegam ao handler pelo polling do bot (Bot API falsa)."""
    from test_canal_offline import START, BotFalso, _toque

    canal = criar_canal("demonstracao", ambiente={"TELEGRAM_BOT_TOKEN": TOKEN_FALSO})
    bot = BotFalso([[START], [_toque("golpe:c1")]])
    canal._saida._bot = bot
    canal._saida._espera_polling = 0
    canal._saida._dir = tmp_path
    recebidos = []
    canal.receber_mensagens(recebidos.append)
    assert bot.vazio.wait(5)
    canal.injetar("contato_novo_sem_dinheiro")
    canal.fechar()
    assert isinstance(recebidos[0], InicioBot) and isinstance(recebidos[1], RespostaAlerta)
    assert recebidos[1].resposta == "golpe"
    assert all(isinstance(e, MensagemRecebida) for e in recebidos[2:]) and len(recebidos) == 4


def test_fabrica_real_usa_o_telegram(sem_rede):
    from guardiao.canal.telegram import TelegramCanal

    ambiente = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "abc", "TELEGRAM_BOT_TOKEN": TOKEN_FALSO}
    canal = criar_canal("real", ambiente=ambiente)
    assert isinstance(canal, TelegramCanal) and canal.usar_conta and canal.usar_bot


@pytest.mark.parametrize(
    "ambiente, mensagem",
    [
        ({"TELEGRAM_API_HASH": "abc", "TELEGRAM_BOT_TOKEN": TOKEN_FALSO}, "TELEGRAM_API_ID"),
        ({"TELEGRAM_API_ID": "x", "TELEGRAM_API_HASH": "abc", "TELEGRAM_BOT_TOKEN": TOKEN_FALSO}, "numérico"),
        ({"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "abc"}, "TELEGRAM_BOT_TOKEN"),
    ],
)
def test_fabrica_real_sem_credencial_cita_so_o_nome(ambiente, mensagem):
    with pytest.raises(RuntimeError, match=mensagem) as erro:
        criar_canal("real", ambiente=ambiente)
    assert TOKEN_FALSO not in str(erro.value) and "abc" not in str(erro.value)


@pytest.mark.parametrize("modo", ["", "demo", "Real", None])
def test_fabrica_modo_invalido(modo):
    with pytest.raises(ValueError, match="modo inválido"):
        criar_canal(modo, ambiente={})


@pytest.fixture
def fabrica_sem_env(monkeypatch):
    """`criar_canal` sem `ambiente`, mas sem ler o `backend/.env` real."""
    import guardiao.canal.fabrica as fabrica

    chamadas = []
    monkeypatch.setattr(fabrica, "carregar_env", lambda: chamadas.append(1))
    for nome in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        monkeypatch.setenv(nome, "x")
        monkeypatch.delenv(nome)
    return fabrica, chamadas


def test_fabrica_le_o_ambiente_quando_nao_recebe_um(fabrica_sem_env):
    fabrica, chamadas = fabrica_sem_env
    canal = fabrica.criar_canal("demonstracao")
    assert chamadas == [1] and not canal.tem_bot


def test_fabrica_demonstracao_le_o_token_do_ambiente(fabrica_sem_env, monkeypatch, sem_rede):
    fabrica, chamadas = fabrica_sem_env
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN_FALSO)
    canal = fabrica.criar_canal("demonstracao")
    assert chamadas == [1] and canal.tem_bot


def test_fabrica_real_le_as_credenciais_do_ambiente(fabrica_sem_env, monkeypatch, sem_rede):
    from guardiao.canal.telegram import TelegramCanal

    fabrica, chamadas = fabrica_sem_env
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN_FALSO)
    canal = fabrica.criar_canal("real")
    assert chamadas == [1] and isinstance(canal, TelegramCanal) and canal.usar_conta and canal.usar_bot


# --------------------------------------------------------------------------- Secrets do Colab

NOMES = ["TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "TELEGRAM_API_ID"]


def test_segredos_fora_do_colab_tudo_falso(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.colab", None)  # import falha como fora do Colab
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "do-env")
    assert config.carregar_segredos_colab(NOMES) == {nome: False for nome in NOMES}
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "do-env"


def _colab_falso(monkeypatch, segredos):
    class SecretNotFoundError(Exception):
        pass

    def get(nome):
        if nome not in segredos:
            raise SecretNotFoundError(nome)
        if isinstance(segredos[nome], Exception):
            raise segredos[nome]
        return segredos[nome]

    google = ModuleType("google")
    colab = ModuleType("google.colab")
    colab.userdata = SimpleNamespace(get=get)
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)


def test_segredos_no_colab_viram_variaveis_e_so_presenca(monkeypatch, capsys):
    for nome in NOMES:  # setenv antes do delenv: o monkeypatch desfaz o que o teste gravar
        monkeypatch.setenv(nome, "x")
        monkeypatch.delenv(nome)
    _colab_falso(
        monkeypatch,
        {"TELEGRAM_BOT_TOKEN": "valor-secreto-1", "GEMINI_API_KEY": "  ", "TELEGRAM_API_ID": PermissionError("sem acesso")},
    )
    presenca = config.carregar_segredos_colab(NOMES)
    assert presenca == {"TELEGRAM_BOT_TOKEN": True, "GEMINI_API_KEY": False, "TELEGRAM_API_ID": False}
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "valor-secreto-1"
    assert "GEMINI_API_KEY" not in os.environ and "TELEGRAM_API_ID" not in os.environ
    saida = capsys.readouterr()
    assert "valor-secreto-1" not in saida.out + saida.err
    assert config.carregar_segredos_colab(["AUSENTE"]) == {"AUSENTE": False}


def test_segredo_apagado_no_colab_sai_do_ambiente(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "de-uma-execucao-anterior")
    monkeypatch.setenv("GEMINI_API_KEY", "de-uma-execucao-anterior")
    _colab_falso(monkeypatch, {"GEMINI_API_KEY": ""})
    presenca = config.carregar_segredos_colab(["TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY"])
    assert presenca == {"TELEGRAM_BOT_TOKEN": False, "GEMINI_API_KEY": False}
    assert "TELEGRAM_BOT_TOKEN" not in os.environ and "GEMINI_API_KEY" not in os.environ
