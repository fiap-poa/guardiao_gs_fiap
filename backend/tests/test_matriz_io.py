"""Linhas da matriz I/O da história 2, sem rede: conta e bot falsos, nada de backend/.env."""

import asyncio
import json
import os
import stat
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from telethon import events
from telethon.errors import PasswordHashInvalidError, RPCError, SessionPasswordNeededError

import guardiao.canal.telegram as telegram

import guardiao.mascara as mascara
import guardiao.verificar as verificar
from guardiao.canal.base import Contato, InicioBot, MensagemRecebida, RespostaAlerta
from guardiao.canal.telegram import TelegramCanal
from guardiao.mascara import hash_id

CONTA_A = 7123456789
CONTA_C = 7987654321
BOT_ID = 7555000111


@pytest.fixture
def evidencias(tmp_path, monkeypatch):
    pasta = tmp_path / "evidencias"
    monkeypatch.setattr(mascara, "EVIDENCIAS_DIR", pasta)
    return pasta


def _linhas(pasta, verificacao):
    caminho = pasta / f"{verificacao}.jsonl"
    if not caminho.exists():
        return []
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- conta falsa


class QRFalso:
    def __init__(self, esperas):
        self.esperas = list(esperas)  # cada item: None (lido) ou exceção a levantar
        self.recriados = 0

    @property
    def url(self):
        return f"tg://login?token=falso{self.recriados}"

    async def wait(self, timeout=None):
        efeito = self.esperas.pop(0)
        if efeito is not None:
            raise efeito

    async def recreate(self):
        self.recriados += 1


class ClienteFalso:
    def __init__(self, qr=None, autorizado=False, senhas_validas=(), logout_ok=True, logout_erro=None):
        self.qr = qr
        self.autorizado = autorizado
        self.senhas_validas = set(senhas_validas)
        self.logout_ok = logout_ok
        self.logout_erro = logout_erro
        self.handlers = []
        self.senhas_tentadas = []
        self.log_out_chamado = False
        self.desconectado = False
        self.conectado = False

    async def connect(self):
        self.conectado = True

    def is_connected(self):
        return self.conectado

    async def disconnect(self):
        self.conectado = False
        self.desconectado = True

    async def is_user_authorized(self):
        return self.autorizado

    async def qr_login(self):
        return self.qr

    async def sign_in(self, password=None):
        self.senhas_tentadas.append(password)
        if password not in self.senhas_validas:
            raise PasswordHashInvalidError(request=None)
        self.autorizado = True

    async def get_me(self):
        return SimpleNamespace(id=CONTA_A, bot=False)

    async def log_out(self):
        self.log_out_chamado = True
        if self.logout_erro:
            raise self.logout_erro
        self.conectado = False
        return self.logout_ok

    def add_event_handler(self, callback, filtro):
        self.handlers.append((callback, filtro))


def _canal_com_cliente(tmp_path, cliente):
    canal = TelegramCanal(1, "x", None, dir_sessao=tmp_path, usar_bot=False)
    canal._cliente = cliente
    return canal


def _login(canal, max_qr=6, senhas=("errada",)):
    mostrados, pedidas = [], []

    def mostrar(url, n):
        mostrados.append((url, n))

    def pedir(tentativa):
        pedidas.append(tentativa)
        return senhas[min(tentativa, len(senhas)) - 1]

    try:
        return canal.login_qr(mostrar, pedir, max_qr=max_qr), mostrados, pedidas
    finally:
        canal.fechar()


# --------------------------------------------------------------------------- 1. login por QR


def test_qr_vencido_gera_outro_e_mostra_de_novo(tmp_path):
    qr = QRFalso([asyncio.TimeoutError(), None])
    cliente = ClienteFalso(qr=qr)
    conta, mostrados, pedidas = _login(_canal_com_cliente(tmp_path, cliente))
    assert conta == CONTA_A
    assert qr.recriados == 1
    assert mostrados == [("tg://login?token=falso0", 1), ("tg://login?token=falso1", 2)]
    assert pedidas == []


def test_2fa_pede_senha_e_faz_sign_in(tmp_path):
    qr = QRFalso([SessionPasswordNeededError(request=None)])
    cliente = ClienteFalso(qr=qr, senhas_validas={"certa"})
    conta, mostrados, pedidas = _login(_canal_com_cliente(tmp_path, cliente), senhas=("certa",))
    assert conta == CONTA_A
    assert pedidas == [1]
    assert cliente.senhas_tentadas == ["certa"]
    assert len(mostrados) == 1


def test_2fa_errada_depois_certa(tmp_path):
    qr = QRFalso([SessionPasswordNeededError(request=None)])
    cliente = ClienteFalso(qr=qr, senhas_validas={"certa"})
    conta, _, pedidas = _login(_canal_com_cliente(tmp_path, cliente), senhas=("errada", "certa"))
    assert conta == CONTA_A
    assert pedidas == [1, 2]
    assert cliente.senhas_tentadas == ["errada", "certa"]


def test_2fa_errada_tres_vezes_levanta_permission_error(tmp_path):
    qr = QRFalso([SessionPasswordNeededError(request=None)])
    cliente = ClienteFalso(qr=qr, senhas_validas={"certa"})
    with pytest.raises(PermissionError):
        _login(_canal_com_cliente(tmp_path, cliente), senhas=("errada",))
    assert cliente.senhas_tentadas == ["errada"] * 3


def test_qr_esgotado_levanta_timeout(tmp_path):
    qr = QRFalso([asyncio.TimeoutError(), asyncio.TimeoutError()])
    cliente = ClienteFalso(qr=qr)
    mostrados = []
    canal = _canal_com_cliente(tmp_path, cliente)
    try:
        with pytest.raises(TimeoutError):
            canal.login_qr(lambda url, n: mostrados.append(n), lambda t: "x", max_qr=2)
    finally:
        canal.fechar()
    assert mostrados == [1, 2]
    assert qr.recriados == 1  # o último vencimento não gera QR que ninguém verá


def test_sessao_ja_logada_nao_mostra_qr(tmp_path):
    cliente = ClienteFalso(qr=None, autorizado=True)
    conta, mostrados, _ = _login(_canal_com_cliente(tmp_path, cliente))
    assert conta == CONTA_A and mostrados == []


class CanalLoginFalso:
    def __init__(self, conta=CONTA_A, erro=None):
        self.conta = conta
        self.erro = erro
        self.fechado = False

    def login_qr(self, mostrar_qr, pedir_senha):
        mostrar_qr("tg://login?token=falso", 1)
        if self.erro:
            raise self.erro
        return self.conta

    def fechar(self):
        self.fechado = True


@pytest.fixture
def local_tmp(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setattr(verificar, "LOCAL_DIR", local)
    monkeypatch.setattr(verificar, "QR_PNG", local / "qr.png")
    return local


def test_cmd_login_registra_conectado_com_conta_em_hash(evidencias, local_tmp, monkeypatch, capsys):
    canal = CanalLoginFalso()
    monkeypatch.setattr("builtins.input", lambda _: "sim")
    monkeypatch.setattr(verificar.TelegramCanal, "do_ambiente", classmethod(lambda cls, **kw: canal))
    assert verificar.cmd_login(Namespace(inverter=False)) == 0
    [linha] = _linhas(evidencias, "login")
    assert linha["resultado"] == "conectado"
    assert linha["conta"] == hash_id(CONTA_A)
    assert linha["qr_gerados"] == 1
    assert str(CONTA_A) not in (evidencias / "login.jsonl").read_text()
    assert canal.fechado
    assert not (local_tmp / "qr.png").exists()  # o QR é apagado depois do login


def test_cmd_login_qr_vencido_registra_falhou(evidencias, local_tmp, monkeypatch):
    canal = CanalLoginFalso(erro=TimeoutError("QR não foi lido"))
    monkeypatch.setattr("builtins.input", lambda _: "sim")
    monkeypatch.setattr(verificar.TelegramCanal, "do_ambiente", classmethod(lambda cls, **kw: canal))
    assert verificar.cmd_login(Namespace(inverter=False)) == 1
    [linha] = _linhas(evidencias, "login")
    assert linha["resultado"] == "falhou" and linha["motivo"] == "qr_vencido"
    assert not (local_tmp / "qr.png").exists()


def test_cmd_login_sem_sim_cancela_antes_de_conectar(evidencias, local_tmp, monkeypatch, capsys):
    def nao_pode(cls, **kw):
        raise AssertionError("não deveria criar o canal")

    monkeypatch.setattr("builtins.input", lambda _: "não")
    monkeypatch.setattr(verificar.TelegramCanal, "do_ambiente", classmethod(nao_pode))
    assert verificar.cmd_login(Namespace(inverter=False)) == 1
    assert "cancelado" in capsys.readouterr().out
    assert _linhas(evidencias, "login") == []


# --------------------------------------------------------------------------- bot falso


def _agora_se_fabrica(evento):
    """Eventos passados como função são criados na entrega (com o horário de agora)."""
    return evento() if callable(evento) else evento


def _start(usuario, idade=None):
    """Fábrica de InicioBot; `idade` (timedelta) data o /start no passado."""
    def fabricar():
        quando = datetime.now(timezone.utc) - (idade or timedelta(0))
        return InicioBot(usuario_id=usuario, destinatario=usuario, recebido_em=quando)
    return fabricar


class CanalBotFalso:
    """Canal que entrega eventos roteirizados ao handler, como o polling faria."""

    def __init__(self, ao_receber=(), ao_enviar_alerta=None, ao_start=(), ao_aviso=None):
        self.ao_receber = list(ao_receber)
        self.ao_enviar_alerta = ao_enviar_alerta
        self.ao_start = list(ao_start)
        self.ao_aviso = ao_aviso
        self.handler = None
        self.alertas = []
        self.avisos = []
        self.fechado = False

    def conectar(self):
        return CONTA_A

    def info_bot(self):
        return {"id": BOT_ID, "username": "guardiao_teste_bot"}

    def receber_mensagens(self, handler):
        self.handler = handler
        for evento in self.ao_receber:
            handler(_agora_se_fabrica(evento))

    def enviar_alerta(self, alerta):
        self.alertas.append(alerta)
        if self.ao_enviar_alerta:
            self.handler(self.ao_enviar_alerta(alerta))
        return "77"

    def enviar_start_ao_bot(self):
        for evento in self.ao_start:
            self.handler(_agora_se_fabrica(evento))

    def enviar_aviso(self, destinatario, texto):
        self.avisos.append((destinatario, texto))
        if self.ao_aviso:
            self.handler(_agora_se_fabrica(self.ao_aviso))
        return "1"

    def fechar(self):
        self.fechado = True


def _usar(monkeypatch, canal):
    monkeypatch.setattr(verificar.TelegramCanal, "do_ambiente", classmethod(lambda cls, **kw: canal))


def _args_alerta(espera):
    return Namespace(espera=espera, nome="Pedro", como_chama="sua mãe",
                     trecho=verificar.TRECHO_TESTE, numero=None)


# --------------------------------------------------------------------------- 2. bot-alerta


def test_bot_alerta_sem_start_no_prazo(evidencias, monkeypatch, capsys):
    canal = CanalBotFalso()
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(0.2)) == 1
    [linha] = _linhas(evidencias, "bot-alerta")
    assert linha["resultado"] == "falhou" and linha["motivo"] == "sem_start"
    assert "sem /start" in capsys.readouterr().out
    assert canal.alertas == [] and canal.fechado


def test_bot_alerta_caminho_feliz(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_C)],
        ao_enviar_alerta=lambda alerta: RespostaAlerta(
            alerta_id="77", caso_id=alerta.caso_id, resposta="golpe", respondente_id=CONTA_C
        ),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(2)) == 0

    [alerta] = canal.alertas
    assert alerta.destinatario == CONTA_C and alerta.nome_alegado == "Pedro"
    start, enviado, toque = _linhas(evidencias, "bot-alerta")
    assert start["evento"] == "start" and start["responsavel"] == hash_id(CONTA_C)
    assert enviado["evento"] == "alerta_enviado" and enviado["alerta_id"] == "77"
    assert enviado["caso"] == alerta.caso_id and enviado["com_numero"] is False
    assert toque["evento"] == "toque" and toque["resposta"] == "golpe"
    assert toque["mesmo_alerta"] is True and toque["mesmo_respondente"] is True
    assert toque["respondido"] is True and toque["resultado"] == "ok"
    conteudo = (evidencias / "bot-alerta.jsonl").read_text()
    assert "Pedro" not in conteudo and str(CONTA_C) not in conteudo


def test_bot_alerta_ignora_toque_de_outro_caso(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_C)],
        ao_enviar_alerta=lambda alerta: RespostaAlerta(
            alerta_id="5", caso_id="teste-antigo", resposta="golpe", respondente_id=CONTA_C
        ),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(0.3)) == 1
    assert _linhas(evidencias, "bot-alerta")[-1]["motivo"] == "sem_toque"


# --------------------------------------------------------------------------- 3. bot-start-idosa


def test_bot_start_idosa_ok(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_start=[
            _start(CONTA_C),  # /start de outra conta
            _start(CONTA_A),
        ],
        ao_aviso=MensagemRecebida(tipo="privada", remetente_id=BOT_ID, conversa_id=BOT_ID,
                                  texto=verificar.TEXTO_TESTE_IDOSA),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_start_idosa(Namespace(espera=2)) == 0
    assert canal.avisos == [(CONTA_A, verificar.TEXTO_TESTE_IDOSA)]
    enviado, recebido, aviso = _linhas(evidencias, "bot-start-idosa")
    assert enviado["evento"] == "start_enviado" and enviado["idosa"] == hash_id(CONTA_A)
    assert recebido["evento"] == "start_recebido_pelo_bot" and recebido["idosa"] == hash_id(CONTA_A)
    assert aviso["aviso_recebido_pela_conta"] is True and aviso["resultado"] == "ok"
    assert "Teste do Guardi" not in (evidencias / "bot-start-idosa.jsonl").read_text()


def test_bot_start_idosa_bot_nao_recebe(evidencias, monkeypatch):
    canal = CanalBotFalso(ao_start=[_start(CONTA_C)])
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_start_idosa(Namespace(espera=0.2)) == 1
    assert canal.avisos == []
    linha = _linhas(evidencias, "bot-start-idosa")[-1]
    assert linha["resultado"] == "falhou" and linha["motivo"] == "bot_nao_recebeu_start"


def test_bot_start_idosa_conta_nao_recebe_o_aviso(evidencias, monkeypatch):
    monkeypatch.setattr(verificar, "ESPERA_AVISO", 0.2)
    canal = CanalBotFalso(
        ao_start=[_start(CONTA_A)],
        ao_aviso=MensagemRecebida(tipo="privada", remetente_id=CONTA_C, conversa_id=CONTA_C),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_start_idosa(Namespace(espera=2)) == 1
    aviso = _linhas(evidencias, "bot-start-idosa")[-1]
    assert aviso["aviso_enviado"] is True and aviso["aviso_recebido_pela_conta"] is False
    assert aviso["resultado"] == "falhou"


# --------------------------------------------------------------------------- 4. sair


def _criar_sessao(pasta):
    pasta.mkdir(exist_ok=True)
    for nome in ("guardiao.session", "guardiao.session-journal"):
        (pasta / nome).write_bytes(b"")


def test_sair_autorizado_faz_log_out_e_apaga_sessao(tmp_path):
    _criar_sessao(tmp_path)
    cliente = ClienteFalso(autorizado=True)
    canal = _canal_com_cliente(tmp_path, cliente)
    try:
        assert canal.sair() == "encerrada"
    finally:
        canal.fechar()
    assert cliente.log_out_chamado
    assert list(tmp_path.glob("guardiao.session*")) == []


def test_sair_sem_login_apaga_sem_log_out(tmp_path):
    _criar_sessao(tmp_path)
    cliente = ClienteFalso(autorizado=False)
    canal = _canal_com_cliente(tmp_path, cliente)
    try:
        assert canal.sair() == "apagada_sem_login"
    finally:
        canal.fechar()
    assert not cliente.log_out_chamado and cliente.desconectado
    assert list(tmp_path.glob("guardiao.session*")) == []


def test_sair_log_out_falhou_ainda_apaga(tmp_path):
    _criar_sessao(tmp_path)
    cliente = ClienteFalso(autorizado=True, logout_ok=False)
    canal = _canal_com_cliente(tmp_path, cliente)
    try:
        assert canal.sair() == "logout_falhou_apagada"
    finally:
        canal.fechar()
    assert list(tmp_path.glob("guardiao.session*")) == []


def test_cmd_sair_sem_sessao_avisa_e_sai(evidencias, local_tmp, monkeypatch, capsys):
    def nao_pode(cls, **kw):
        raise AssertionError("não deveria criar o canal")

    monkeypatch.setattr(verificar.TelegramCanal, "do_ambiente", classmethod(nao_pode))
    assert verificar.cmd_sair(Namespace()) == 0
    assert "Sem sessão" in capsys.readouterr().out
    assert _linhas(evidencias, "sair")[-1]["resultado"] == "sem_sessao"


# --------------------------------------------------------------------------- revisão


ANTIGO = timedelta(hours=1)


def test_bot_alerta_ignora_start_antigo_e_aceita_o_novo(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_A, idade=ANTIGO), _start(CONTA_C)],
        ao_enviar_alerta=lambda alerta: RespostaAlerta(
            alerta_id="77", caso_id=alerta.caso_id, resposta="golpe", respondente_id=CONTA_C
        ),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(2)) == 0
    assert canal.alertas[0].destinatario == CONTA_C
    assert _linhas(evidencias, "bot-alerta")[0]["responsavel"] == hash_id(CONTA_C)


def test_bot_alerta_so_start_antigo_e_sem_start(evidencias, monkeypatch):
    canal = CanalBotFalso(ao_receber=[_start(CONTA_C, idade=ANTIGO)])
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(0.3)) == 1
    assert _linhas(evidencias, "bot-alerta")[-1]["motivo"] == "sem_start"
    assert canal.alertas == []


def test_bot_alerta_toque_de_outra_pessoa_e_falhou(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_C)],
        ao_enviar_alerta=lambda alerta: RespostaAlerta(
            alerta_id="77", caso_id=alerta.caso_id, resposta="golpe", respondente_id=CONTA_A
        ),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(2)) == 1
    toque = _linhas(evidencias, "bot-alerta")[-1]
    assert toque["mesmo_respondente"] is False and toque["resultado"] == "falhou"


def test_bot_alerta_toque_noutro_alerta_do_mesmo_caso_e_falhou(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_C)],
        ao_enviar_alerta=lambda alerta: RespostaAlerta(
            alerta_id="76", caso_id=alerta.caso_id, resposta="golpe", respondente_id=CONTA_C
        ),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_alerta(_args_alerta(2)) == 1
    toque = _linhas(evidencias, "bot-alerta")[-1]
    assert toque["mesmo_alerta"] is False and toque["resultado"] == "falhou"


def test_bot_start_idosa_ignora_start_antigo_da_propria_conta(evidencias, monkeypatch):
    canal = CanalBotFalso(ao_receber=[_start(CONTA_A, idade=ANTIGO)])  # pendente no getUpdates
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_start_idosa(Namespace(espera=0.3)) == 1
    assert _linhas(evidencias, "bot-start-idosa")[-1]["motivo"] == "bot_nao_recebeu_start"
    assert canal.avisos == []


def test_bot_start_idosa_start_antigo_seguido_de_novo(evidencias, monkeypatch):
    canal = CanalBotFalso(
        ao_receber=[_start(CONTA_A, idade=ANTIGO)],
        ao_start=[_start(CONTA_A)],
        ao_aviso=MensagemRecebida(tipo="privada", remetente_id=BOT_ID, conversa_id=BOT_ID),
    )
    _usar(monkeypatch, canal)
    assert verificar.cmd_bot_start_idosa(Namespace(espera=2)) == 0
    assert _linhas(evidencias, "bot-start-idosa")[-1]["resultado"] == "ok"


def test_sair_log_out_que_levanta_ainda_apaga(tmp_path):
    _criar_sessao(tmp_path)
    cliente = ClienteFalso(autorizado=True, logout_erro=RPCError(request=None, message="FALHA"))
    canal = _canal_com_cliente(tmp_path, cliente)
    try:
        assert canal.sair() == "logout_falhou_apagada"
    finally:
        canal.fechar()
    assert cliente.log_out_chamado
    assert list(tmp_path.glob("guardiao.session*")) == []


def test_fechar_zera_conta_em_cache(tmp_path):
    canal = _canal_com_cliente(tmp_path, ClienteFalso(autorizado=True))
    assert canal.conectar() == CONTA_A
    canal.fechar()
    assert canal._conta_id is None and canal._cliente is None


def test_login_qr_cria_sessao_600_em_pasta_700(tmp_path, monkeypatch):
    local = tmp_path / ".local"
    local.mkdir(mode=0o755)
    os.chmod(local, 0o755)

    def cliente_falso(sessao, api_id, api_hash, **kwargs):
        journal = f"{sessao}.session-journal"  # como o SQLite, com modo aberto
        os.close(os.open(journal, os.O_WRONLY | os.O_CREAT, 0o644))
        os.chmod(journal, 0o644)
        return ClienteFalso(qr=QRFalso([None]))

    monkeypatch.setattr(telegram, "TelegramClient", cliente_falso)
    canal = TelegramCanal(1, "x", None, dir_sessao=local, usar_bot=False)
    conta, mostrados, _ = _login(canal)
    assert conta == CONTA_A and len(mostrados) == 1
    assert stat.S_IMODE(local.stat().st_mode) == 0o700
    arquivos = sorted(local.glob("guardiao.session*"))
    assert [a.name for a in arquivos] == ["guardiao.session", "guardiao.session-journal"]
    assert all(stat.S_IMODE(a.stat().st_mode) == 0o600 for a in arquivos)


def test_receber_mensagens_registra_so_entrada_e_entrega_mensagem(tmp_path):
    cliente = ClienteFalso(autorizado=True)
    canal = _canal_com_cliente(tmp_path, cliente)
    recebidos = []
    try:
        canal.receber_mensagens(recebidos.append)
        [(callback, filtro)] = cliente.handlers
        assert isinstance(filtro, events.NewMessage)
        assert filtro.incoming is True and not filtro.outgoing
        evento = SimpleNamespace(is_private=True, sender_id=CONTA_C, chat_id=CONTA_C,
                                 raw_text="oi", date=None)
        canal._executar(callback(evento))
    finally:
        canal.fechar()
    [mensagem] = recebidos
    assert isinstance(mensagem, MensagemRecebida)
    assert mensagem.tipo == "privada" and mensagem.remetente_id == CONTA_C and mensagem.tem_texto


class CanalContaFalso:
    def __init__(self, mensagens=(), contatos=(), situacao_sair="encerrada", local=None):
        self.mensagens = list(mensagens)
        self.contatos = list(contatos)
        self.situacao_sair = situacao_sair
        self.local = local
        self.fechado = False

    def conectar(self):
        return CONTA_A

    def receber_mensagens(self, handler):
        for mensagem in self.mensagens:
            handler(mensagem)

    def listar_contatos(self):
        return self.contatos

    def sair(self):
        for arquivo in self.local.glob("guardiao.session*"):
            arquivo.unlink()
        return self.situacao_sair

    def fechar(self):
        self.fechado = True


def test_cmd_escutar_conta_privada_e_grupo(evidencias, monkeypatch):
    canal = CanalContaFalso(mensagens=[
        MensagemRecebida(tipo="privada", remetente_id=CONTA_C, conversa_id=CONTA_C, texto="oi vó"),
        MensagemRecebida(tipo="grupo"),
    ])
    _usar(monkeypatch, canal)
    assert verificar.cmd_escutar(Namespace(segundos=0.3)) == 0
    linhas = _linhas(evidencias, "escutar")
    assert [l.get("tipo") for l in linhas[:2]] == ["privada", "grupo"]
    resumo = linhas[-1]
    assert resumo["privadas"] == 1 and resumo["grupos"] == 1 and resumo["resultado"] == "ok"
    assert "oi vó" not in (evidencias / "escutar.jsonl").read_text()
    assert canal.fechado


def test_cmd_escutar_sem_privada_sai_1(evidencias, monkeypatch):
    _usar(monkeypatch, CanalContaFalso(mensagens=[MensagemRecebida(tipo="grupo")]))
    assert verificar.cmd_escutar(Namespace(segundos=0.3)) == 1
    resumo = _linhas(evidencias, "escutar")[-1]
    assert resumo["privadas"] == 0 and resumo["resultado"] == "falhou"


def test_cmd_contatos_evidencia_e_saida(evidencias, monkeypatch):
    _usar(monkeypatch, CanalContaFalso(contatos=[Contato(1, "Pedro", "5500987651234")]))
    assert verificar.cmd_contatos(Namespace(procurar="Pedro")) == 0
    linha = _linhas(evidencias, "contatos")[-1]
    assert linha["busca"] == "encontrado_com_telefone" and linha["telefone"] == "55*******1234"
    _usar(monkeypatch, CanalContaFalso(contatos=[]))
    assert verificar.cmd_contatos(Namespace(procurar=None)) == 1
    assert _linhas(evidencias, "contatos")[-1]["resultado"] == "falhou"


@pytest.mark.parametrize("situacao, saida", [("encerrada", 0), ("logout_falhou_apagada", 1)])
def test_cmd_sair_com_sessao(evidencias, local_tmp, monkeypatch, situacao, saida):
    _criar_sessao(local_tmp)
    _usar(monkeypatch, CanalContaFalso(situacao_sair=situacao, local=local_tmp))
    assert verificar.cmd_sair(Namespace()) == saida
    linha = _linhas(evidencias, "sair")[-1]
    assert linha["resultado"] == situacao and linha["sessao_local_existe"] is False


def test_do_ambiente_api_id_nao_numerico_nao_mostra_valor(monkeypatch):
    monkeypatch.setattr(telegram, "carregar_env", lambda: False)  # não lê backend/.env
    monkeypatch.setenv("TELEGRAM_API_ID", "abc-SEGREDO")
    monkeypatch.setenv("TELEGRAM_API_HASH", "x")
    with pytest.raises(RuntimeError) as erro:
        TelegramCanal.do_ambiente(usar_bot=False)
    assert str(erro.value) == "TELEGRAM_API_ID não é numérico"
    assert "SEGREDO" not in str(erro.value)
    assert erro.value.__suppress_context__


def test_main_imprime_so_o_tipo_de_erro_inesperado(evidencias, monkeypatch, capsys):
    class CanalQueFalha(CanalContaFalso):
        def listar_contatos(self):
            raise RPCError(request=None, message="DETALHE_SECRETO")

    _usar(monkeypatch, CanalQueFalha())
    assert verificar.main(["contatos"]) == 2
    erro = capsys.readouterr().err
    assert "RPCError" in erro and "DETALHE_SECRETO" not in erro


def test_main_api_id_nao_numerico(monkeypatch, capsys):
    monkeypatch.setattr(telegram, "carregar_env", lambda: False)
    monkeypatch.setenv("TELEGRAM_API_ID", "abc-SEGREDO")
    monkeypatch.setenv("TELEGRAM_API_HASH", "x")
    assert verificar.main(["contatos"]) == 2
    erro = capsys.readouterr().err
    assert "TELEGRAM_API_ID não é numérico" in erro and "SEGREDO" not in erro
