"""Guardião ponta a ponta no canal simulado (CAP-1, CAP-2, CAP-7), sem rede."""

import time
from datetime import datetime, timedelta, timezone

import pytest

import guardiao.canal.simulado as simulado
from guardiao.cadastro import TEXTO_BOT_PRIVADO
from guardiao.canal.base import InicioBot, MensagemRecebida, RespostaAlerta
from guardiao.canal.cenarios import CENARIOS, ID_IDOSA
from guardiao.canal.fabrica import criar_canal
from guardiao.canal.simulado import CanalSimulado
from guardiao.recepcao import Guardiao, RelogioAjustavel, SemBot
from test_canal_offline import BotFalso
from test_simulado import TOKEN_FALSO, SaidaFalsa, sem_rede  # noqa: F401 (fixture)

BOT = {"id": 7555000111, "username": "guardiao_teste_bot"}
RESPONSAVEL = 7987654321
OUTRA = 7111222333
PRONTO = "Pronto, Ana. Você vai receber aqui os alertas do Guardião sobre Dona Maria."


class SaidaComBot(SaidaFalsa):
    def info_bot(self):
        return dict(BOT)


class MensagemVigiada(MensagemRecebida):
    """Falha o teste se alguém ler o texto."""

    def __getattribute__(self, nome):
        if nome in ("texto", "tem_texto"):
            raise AssertionError("o texto foi lido")
        return super().__getattribute__(nome)


def _guardiao(saida=None, relogio=None):
    canal = CanalSimulado(saida=saida)
    analisadas, respostas = [], []
    guardiao = Guardiao(
        canal, relogio=relogio or RelogioAjustavel(), ao_analisar=analisadas.append, ao_responder=respostas.append
    )
    guardiao.conectar()
    return guardiao, canal, analisadas, respostas


def _codigo(link):
    return link.split("?start=", 1)[1]


def _inicio(usuario=RESPONSAVEL, codigo=None, nome="Ana"):
    return InicioBot(usuario_id=usuario, destinatario=usuario, parametro=codigo, nome=nome)


# --------------------------------------------------------------------------- conectar


def test_conectar_pareia_liga_a_recepcao_e_habilita_a_idosa_sem_resposta():
    saida = SaidaComBot()
    guardiao, canal, _, _ = _guardiao(saida)
    assert guardiao.estado() == {
        "conectado": True,
        "idosa_habilitada": True,
        "tem_bot": True,
        "responsavel_cadastrada": False,
        "codigos_validos": 0,
        "conhecidos": 5,  # Mariana, Lucas, Pedro, Carlos e o bot
        "observados": 0,
        "casos": {"aguardando": 0, "golpe": 0, "era_ele_mesmo": 0, "sem_resposta": 0},
    }
    assert saida.handler is not None  # a recepção do bot também está ligada
    assert saida.avisos == [] and canal.celular() == []  # o bot não responde à pessoa idosa
    assert guardiao.filtro.situacao(BOT["id"]) == "conhecido"
    assert guardiao.conectar()["conectado"]  # de novo: não refaz nada


def test_conectar_sem_bot():
    guardiao, _, _, _ = _guardiao()
    estado = guardiao.estado()
    assert estado["conectado"] and estado["idosa_habilitada"] and not estado["tem_bot"]
    assert estado["conhecidos"] == 4


def test_mensagem_do_bot_a_idosa_nao_e_contato_novo():
    guardiao, canal, analisadas, _ = _guardiao(SaidaComBot())
    canal.injetar_mensagem(BOT["id"], "aviso do Guardião")
    assert analisadas == []


def test_info_bot_falhando_nao_impede_a_conexao(capsys):
    class SaidaQuebrada(SaidaFalsa):
        def info_bot(self):
            raise ConnectionError("detalhe sensível")

    guardiao, canal, analisadas, _ = _guardiao(SaidaQuebrada())
    assert guardiao.estado()["conectado"] and not guardiao.estado()["tem_bot"]
    erro = capsys.readouterr().err
    assert "ConnectionError" in erro and "detalhe sensível" not in erro
    canal.injetar("golpe_classico")
    assert len(analisadas) == 2


def test_tratar_antes_de_conectar_nao_decide():
    guardiao = Guardiao(CanalSimulado())
    with pytest.raises(RuntimeError):
        guardiao.tratar(MensagemRecebida(tipo="privada", remetente_id="sim:novo-1", conversa_id="sim:novo-1"))


# --------------------------------------------------------------------------- filtro pelo canal


def test_cinco_cenarios_so_os_tres_numeros_novos_chegam_a_analise(sem_rede, capsys):
    canal = criar_canal("demonstracao", ambiente={})
    analisadas = []
    guardiao = Guardiao(canal, ao_analisar=analisadas.append)
    guardiao.conectar()
    capsys.readouterr()
    for cenario in CENARIOS:
        canal.injetar(cenario.id)
    assert {m.remetente_id for m in analisadas} == {"sim:novo-1", "sim:novo-2", "sim:novo-3"}
    novos = [c for c in CENARIOS if c.origem == "novo"]
    assert [m.texto for m in analisadas] == [t for c in novos for t in c.mensagens]
    assert guardiao.estado()["observados"] == 3
    assert capsys.readouterr().err == ""
    canal.fechar()


def test_golpe_classico_vai_para_a_analise_e_remetente_fica_observado():
    guardiao, canal, analisadas, _ = _guardiao()
    canal.injetar("golpe_classico")
    assert len(analisadas) == 2 and all(m.remetente_id == "sim:novo-1" for m in analisadas)
    assert guardiao.filtro.situacao("sim:novo-1") == "observado"


def test_conhecido_e_grupo_descartados_sem_ler_texto_e_sem_imprimir(monkeypatch, capsys):
    monkeypatch.setattr(simulado, "MensagemRecebida", MensagemVigiada)
    guardiao, canal, analisadas, _ = _guardiao()
    capsys.readouterr()
    canal.injetar("contato_antigo_pede_dinheiro")
    canal.injetar("mensagem_em_grupo")
    assert analisadas == []
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err == ""  # nem "handler falhou": o texto não foi lido
    assert guardiao.filtro.contagens()["por_motivo"] == {"conhecido": 1, "grupo": 1}


def test_salvo_sem_conversa_vai_para_a_analise():
    guardiao, canal, analisadas, _ = _guardiao()
    canal.injetar_mensagem("sim:julia", "Oi vó, tudo bem?")
    assert [m.remetente_id for m in analisadas] == ["sim:julia"]


def test_sete_dias_pelo_relogio_do_guardiao():
    relogio = RelogioAjustavel()
    guardiao, canal, analisadas, _ = _guardiao(relogio=relogio)
    canal.injetar("golpe_classico")
    canal.injetar("contato_novo_sem_dinheiro")
    guardiao.filtro.registrar_alerta("sim:novo-1")
    relogio.adiantar(7)
    antes = len(analisadas)
    canal.injetar_mensagem("sim:novo-3", "Vó, viu a foto?")
    canal.injetar_mensagem("sim:novo-1", "Vó, e o Pix?")
    assert [m.remetente_id for m in analisadas[antes:]] == ["sim:novo-1"]
    assert guardiao.filtro.situacao("sim:novo-3") == "conhecido"
    assert guardiao.filtro.situacao("sim:novo-1") == "observado"


# --------------------------------------------------------------------------- cadastro


def test_iniciar_com_codigo_cadastra_e_responde_pelo_bot():
    saida = SaidaComBot()
    guardiao, canal, _, _ = _guardiao(saida)
    link = guardiao.link_cadastro()
    assert link.startswith("https://t.me/guardiao_teste_bot?start=")
    outro = _codigo(guardiao.link_cadastro())
    assert guardiao.estado()["codigos_validos"] == 2
    saida.handler(_inicio(codigo=_codigo(link)))
    assert saida.avisos == [(RESPONSAVEL, PRONTO)]
    assert guardiao.estado()["responsavel_cadastrada"] and guardiao.estado()["codigos_validos"] == 0
    saida.handler(_inicio(OUTRA, outro))  # os demais códigos foram invalidados
    assert saida.avisos[-1] == (OUTRA, TEXTO_BOT_PRIVADO)
    assert guardiao.cadastro.responsavel.usuario_id == RESPONSAVEL
    assert canal.celular() == []


@pytest.mark.parametrize("codigo", [None, "inventado"])
def test_iniciar_invalido_recebe_bot_privado(codigo):
    saida = SaidaComBot()
    guardiao, _, _, _ = _guardiao(saida)
    guardiao.link_cadastro()
    saida.handler(_inicio(codigo=codigo))
    assert saida.avisos == [(RESPONSAVEL, TEXTO_BOT_PRIVADO)]
    assert not guardiao.estado()["responsavel_cadastrada"]


def test_iniciar_com_codigo_vencido_recebe_bot_privado():
    relogio = RelogioAjustavel()
    saida = SaidaComBot()
    guardiao, _, _, _ = _guardiao(saida, relogio)
    codigo = _codigo(guardiao.link_cadastro())
    relogio.adiantar(minutes=31)
    saida.handler(_inicio(codigo=codigo))
    assert saida.avisos == [(RESPONSAVEL, TEXTO_BOT_PRIVADO)] and not guardiao.estado()["responsavel_cadastrada"]


def test_idosa_tocando_iniciar_com_codigo_nao_vira_responsavel():
    saida = SaidaComBot()
    guardiao, _, _, _ = _guardiao(saida)
    codigo = _codigo(guardiao.link_cadastro())
    saida.handler(InicioBot(usuario_id=ID_IDOSA, destinatario=ID_IDOSA, parametro=codigo))
    assert saida.avisos == [] and not guardiao.estado()["responsavel_cadastrada"]


def test_falha_ao_responder_o_iniciar_nao_desfaz_o_cadastro(capsys):
    class SaidaSemEnvio(SaidaComBot):
        def enviar_aviso(self, destinatario, texto):
            raise ConnectionError("detalhe")

    saida = SaidaSemEnvio()
    guardiao, _, _, _ = _guardiao(saida)
    saida.handler(_inicio(codigo=_codigo(guardiao.link_cadastro())))
    assert guardiao.estado()["responsavel_cadastrada"]
    assert "ConnectionError" in capsys.readouterr().err


def test_sem_bot_link_falha_com_erro_claro_e_recepcao_funciona():
    guardiao, canal, analisadas, _ = _guardiao()
    with pytest.raises(SemBot, match="TELEGRAM_BOT_TOKEN"):
        guardiao.link_cadastro()
    canal.injetar("golpe_classico")
    assert len(analisadas) == 2


def test_bot_sem_username_falha_com_erro_claro():
    class SaidaSemUsername(SaidaFalsa):
        def info_bot(self):
            return {"id": 1, "username": None}

    guardiao, _, _, _ = _guardiao(SaidaSemUsername())
    with pytest.raises(SemBot, match="username"):
        guardiao.link_cadastro()


# --------------------------------------------------------------------------- respostas aos alertas


def test_so_a_resposta_da_responsavel_chega_a_ao_responder():
    saida = SaidaComBot()
    guardiao, _, _, respostas = _guardiao(saida)
    saida.handler(RespostaAlerta("77", "c1", "golpe", RESPONSAVEL))  # ninguém cadastrado ainda
    saida.handler(_inicio(codigo=_codigo(guardiao.link_cadastro())))
    saida.handler(RespostaAlerta("77", "c1", "golpe", OUTRA))
    saida.handler(RespostaAlerta("77", "c1", "era_ele_mesmo", RESPONSAVEL))
    assert [r.resposta for r in respostas] == ["era_ele_mesmo"]


# --------------------------------------------------------------------------- bot falso pela fábrica


class BotFalsoComInfo(BotFalso):
    def get_me(self):
        return dict(BOT)


def _esperar(condicao, segundos=5):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def _start(update_id, usuario, codigo):
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": usuario, "first_name": "Ana"},
            "chat": {"id": usuario, "type": "private"},
            "text": f"/start {codigo}",
            "date": 1,
        },
    }


def test_responsavel_toca_iniciar_pelo_link_e_segundo_iniciar_recebe_bot_privado(tmp_path, sem_rede):
    canal = criar_canal("demonstracao", ambiente={"TELEGRAM_BOT_TOKEN": TOKEN_FALSO})
    bot = BotFalsoComInfo([])
    canal.saida._bot = bot
    canal.saida._espera_polling = 0
    canal.saida._dir = tmp_path
    guardiao = Guardiao(canal)
    try:
        guardiao.conectar()
        codigo = _codigo(guardiao.link_cadastro())
        bot.lotes.append([_start(1, RESPONSAVEL, codigo)])
        assert _esperar(lambda: len(bot.enviados) == 1)
        assert bot.enviados[0][:2] == (RESPONSAVEL, PRONTO)
        assert guardiao.estado()["responsavel_cadastrada"]
        bot.lotes.append([_start(2, OUTRA, codigo)])
        assert _esperar(lambda: len(bot.enviados) == 2)
        assert bot.enviados[1][:2] == (OUTRA, TEXTO_BOT_PRIVADO)
        assert guardiao.cadastro.responsavel.usuario_id == RESPONSAVEL
    finally:
        guardiao.fechar()
    assert not guardiao.estado()["conectado"]


# --------------------------------------------------------------------------- bot obtido só depois do conectar


def test_bot_obtido_so_no_link_cadastro_vira_conhecido():
    class SaidaQueVolta(SaidaComBot):
        falhar = True

        def info_bot(self):
            if self.falhar:
                raise ConnectionError("fora do ar")
            return super().info_bot()

    saida = SaidaQueVolta()
    guardiao, _, _, _ = _guardiao(saida)
    assert guardiao.filtro.situacao(BOT["id"]) == "desconhecido"
    saida.falhar = False
    assert guardiao.link_cadastro().startswith("https://t.me/guardiao_teste_bot?start=")
    assert guardiao.filtro.situacao(BOT["id"]) == "conhecido"


def test_link_cadastro_depois_do_cadastro_levanta_ja_cadastrada():
    from guardiao.cadastro import JaCadastrada

    saida = SaidaComBot()
    guardiao, _, _, _ = _guardiao(saida)
    saida.handler(_inicio(codigo=_codigo(guardiao.link_cadastro())))
    assert guardiao.estado()["responsavel_cadastrada"]
    with pytest.raises(JaCadastrada):
        guardiao.link_cadastro()


# --------------------------------------------------------------------------- modo real (TelegramCanal com falsos)

CONTA_IDOSA = 7123456789  # int, como `get_me().id` do Telethon


class ClienteContaFalso:
    """Cliente do Telethon falso para o `conectar`, o pareamento, a recepção e o `/start`."""

    def __init__(self, bot):
        self.bot = bot
        self.handlers = []

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        from types import SimpleNamespace

        return SimpleNamespace(id=CONTA_IDOSA, bot=False)

    async def iter_dialogs(self):
        from types import SimpleNamespace

        for dialogo in (SimpleNamespace(id=7000000002, is_user=True), SimpleNamespace(id=-1001, is_user=False)):
            yield dialogo

    def add_event_handler(self, funcao, evento):
        self.handlers.append(funcao)

    async def send_message(self, destino, texto):
        # a Bot API entrega o /start da conta com `from.id` igual ao id (int) da conta
        assert destino == BOT["username"] and texto == "/start"
        self.bot.lotes.append([_start(1, CONTA_IDOSA, "")])

    def is_connected(self):
        return False


def test_modo_real_start_da_idosa_habilita_sem_resposta_e_bot_conhecido(tmp_path, sem_rede):
    from guardiao.canal.telegram import TelegramCanal

    canal = TelegramCanal(1, "x", TOKEN_FALSO, dir_sessao=tmp_path, espera_polling=0)
    bot = BotFalsoComInfo([])
    canal._bot = bot
    canal._cliente = ClienteContaFalso(bot)
    guardiao = Guardiao(canal, nome_idosa="Dona Maria")
    try:
        guardiao.conectar()
        assert _esperar(lambda: guardiao.estado()["idosa_habilitada"])
        assert bot.enviados == []  # o bot não responde à pessoa idosa
        assert guardiao.filtro.situacao(BOT["id"]) == "conhecido"
        assert guardiao.filtro.situacao(7000000002) == "conhecido"
        assert not guardiao.estado()["responsavel_cadastrada"]
    finally:
        guardiao.fechar()
