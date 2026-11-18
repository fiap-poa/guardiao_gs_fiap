"""Funções de apoio do notebook e conferência do sinal de sucesso (história 8), sem rede.

Canal simulado com o dublê do bot (`test_casos.DubleBot`) e o dublê do Gemini. A conferência
lê `api/casos` pelo HTTP local: a rede fica proibida, menos 127.0.0.1.
"""

import socket
import threading
import time
from datetime import datetime, timezone

import pytest

from guardiao import roteiro
from guardiao.app import HOST, iniciar_em_segundo_plano, parar_servidor
from guardiao.canal.base import InicioBot
from guardiao.canal.cenarios import obter_cenario
from guardiao.canal.simulado import FUSO_BRASILIA, CanalSimulado, MensagemCelular, formatar_celular
from guardiao.canal.telegram import TelegramCanal
from guardiao.recepcao import Guardiao
from test_casos import NUMERO_PEDRO, RESPONSAVEL, Montagem
from test_simulado import TOKEN_FALSO, sem_rede  # noqa: F401 (fixture)

LOCAIS = {"127.0.0.1", "localhost", "::1"}


@pytest.fixture
def so_local(monkeypatch):
    """Rede proibida, menos o HTTP local da tela (127.0.0.1)."""
    conectar = socket.socket.connect

    def so_local_connect(self, endereco):
        if isinstance(endereco, tuple) and endereco[0] in LOCAIS:
            return conectar(self, endereco)
        raise AssertionError("tentou acessar a rede")

    def proibido(*args, **kwargs):
        raise AssertionError("tentou acessar a rede")

    monkeypatch.setattr(socket.socket, "connect", so_local_connect)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo_local(socket.getaddrinfo, proibido))


def _getaddrinfo_local(original, proibido):
    def getaddrinfo(host, *args, **kwargs):
        if host in LOCAIS:
            return original(host, *args, **kwargs)
        return proibido()

    return getaddrinfo


@pytest.fixture
def m(tmp_path, so_local):
    montagem = Montagem(tmp_path, cadastrar=False)
    montagem.analisadas = []
    montagem.guardiao.ao_analisar = montagem.analisadas.append
    yield montagem
    montagem.guardiao.fechar()


@pytest.fixture
def tela():
    servidor = iniciar_em_segundo_plano(HOST, 0)
    yield servidor
    parar_servidor()


@pytest.fixture
def registrado(m):
    """A tela (`api/casos`) lê o Guardião registrado."""
    from guardiao.app import definir_guardiao

    definir_guardiao(m.guardiao)
    yield m
    definir_guardiao(None)


def _roteiro_completo(m):
    """Cadastro, golpe clássico com "É golpe" e os três cenários sem alerta."""
    m.cadastrar()
    caso = roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico")
    m.bot.tocar("golpe", caso.id)
    for cenario_id in roteiro.CENARIOS_SEM_ALERTA:
        roteiro.injetar_mostrando(m.guardiao, m.analisadas, m.canal.injetar, cenario_id)
    return caso


# --------------------------------------------------------------------------- horários de Brasília


def test_hora_no_fuso_de_brasilia():
    assert roteiro.hora(datetime(2026, 11, 17, 15, 4, tzinfo=timezone.utc)) == "12:04"
    assert roteiro.hora("2026-11-17T02:30:00+00:00") == "23:30"  # vira o dia anterior
    assert roteiro.hora("2026-11-17T15:00:00") == "12:00"  # sem fuso: UTC, como os casos gravam
    assert roteiro.hora(None) == "-" and roteiro.hora("") == "-"
    assert FUSO_BRASILIA.utcoffset(None).total_seconds() == -3 * 3600


def test_celular_simulado_mostra_o_horario_de_brasilia():
    linha = MensagemCelular("aviso", "Guardião da Família", "sim:idosa", "texto", datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc))
    assert ">> [12:00] Guardião da Família: texto" in formatar_celular([linha])


# --------------------------------------------------------------------------- injeção


def test_injetar_mostrando_mostra_a_analise_e_esconde_o_descartado(m, capsys):
    for cenario_id in ("golpe_classico", "contato_antigo_pede_dinheiro", "mensagem_em_grupo"):
        roteiro.injetar_mostrando(m.guardiao, m.analisadas, m.canal.injetar, cenario_id)
    saida = capsys.readouterr().out
    assert "análise:" in saida and "Gemini: SUSPEITA" in saida  # sem responsável: a suspeita não vira caso
    assert "descarte (contato conhecido): 1" in saida and "descarte (grupo): 1" in saida
    for cenario_id in ("contato_antigo_pede_dinheiro", "mensagem_em_grupo"):
        for texto in obter_cenario(cenario_id).mensagens:
            assert texto not in saida


def test_injetar_mostrando_aceita_mensagem_avulsa(m, capsys):
    roteiro.injetar_mostrando(m.guardiao, m.analisadas, m.canal.injetar_mensagem, "sim:julia", "Oi vó", de="Júlia Neta")
    assert 'de=sim:julia): "Oi vó"' in capsys.readouterr().out


# --------------------------------------------------------------------------- cadastro


def test_esperar_cadastro_sem_guardiao_e_sem_bot_volta_na_hora(capsys):
    assert roteiro.esperar_cadastro(None, 60) is False
    assert "não está conectado" in capsys.readouterr().out
    guardiao = Guardiao(CanalSimulado(), varredura_casos_s=None)
    guardiao.conectar()
    inicio = time.monotonic()
    assert roteiro.esperar_cadastro(guardiao, 60) is False
    assert time.monotonic() - inicio < 1
    assert "TELEGRAM_BOT_TOKEN ausente" in capsys.readouterr().out
    guardiao.fechar()


def test_esperar_cadastro_tempo_esgotado_avisa(m, capsys):
    assert roteiro.esperar_cadastro(m.guardiao, 0.2, intervalo=0.05) is False
    saida = capsys.readouterr().out
    assert "ninguém tocou Iniciar em 0.2 s" in saida and "pulam com aviso" in saida


def test_esperar_cadastro_espera_o_iniciar(m, capsys):
    link = m.guardiao.link_cadastro_vigente()

    def toca_iniciar():
        time.sleep(0.2)
        m.bot.handler(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=link.split("?start=")[1], nome="Ana"))

    tocador = threading.Thread(target=toca_iniciar)
    tocador.start()
    assert roteiro.esperar_cadastro(m.guardiao, 10, intervalo=0.05) is True
    tocador.join(5)
    assert "responsável cadastrada" in capsys.readouterr().out
    assert roteiro.esperar_cadastro(m.guardiao, 10) is True
    assert "já está cadastrada" in capsys.readouterr().out
    assert "responsável cadastrada:           sim" in roteiro.descrever_estado(m.guardiao)


# --------------------------------------------------------------------------- alerta e toque


def test_falta_para_alertar_em_ordem(m):
    assert "modo demonstração" in roteiro.falta_para_alertar(m.guardiao, "real")
    assert "não está conectado" in roteiro.falta_para_alertar(None, "demonstracao")
    assert "não está cadastrada" in roteiro.falta_para_alertar(m.guardiao, "demonstracao")
    m.cadastrar()
    assert roteiro.falta_para_alertar(m.guardiao, "demonstracao") is None
    sem_gemini = Guardiao(CanalSimulado(), varredura_casos_s=None)
    sem_gemini.conectar()
    assert "GEMINI_API_KEY" in roteiro.falta_para_alertar(sem_gemini, "demonstracao")
    sem_gemini.analisador = object()
    assert "TELEGRAM_BOT_TOKEN" in roteiro.falta_para_alertar(sem_gemini, "demonstracao")
    sem_gemini.fechar()


def test_abrir_caso_e_toque_simulado(m, capsys):
    m.cadastrar()
    caso = roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico")
    assert caso.estado == "aguardando" and caso.quem == "Pedro"
    assert roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico") is caso  # não reinjeta
    assert len(m.bot.alertas) == 1
    caso = roteiro.tocar(m.guardiao, caso, "golpe", simulado=True)
    assert caso.estado == "golpe" and 'toque simulado: "É golpe"' in capsys.readouterr().out
    assert m.avisos_no_celular() and "dizendo ser Pedro" in m.avisos_no_celular()[0]


def test_abrir_caso_depois_de_conversa_sem_alerta_recomeca(m):
    roteiro.injetar_mostrando(m.guardiao, m.analisadas, m.canal.injetar, "golpe_classico")  # sem responsável
    assert m.caso("golpe_classico") is None
    m.cadastrar()
    assert roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico").estado == "aguardando"


def test_tocar_espera_o_toque_de_verdade_e_desiste_no_prazo(m, capsys):
    m.cadastrar()
    caso = roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico")
    assert roteiro.tocar(m.guardiao, caso, "golpe", espera_s=0.1, intervalo=0.02).estado == "aguardando"
    threading.Timer(0.2, m.bot.tocar, args=("golpe", caso.id)).start()
    assert roteiro.tocar(m.guardiao, caso, "golpe", espera_s=10, intervalo=0.02).estado == "golpe"
    assert 'toque "É golpe" no alerta' in capsys.readouterr().out


def test_numero_do_alerta_e_o_do_contato_do_pedro(m):
    m.cadastrar()
    roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico")
    assert roteiro.numero_esperado_pedro(m.canal) == NUMERO_PEDRO
    assert roteiro.numero_no_alerta(m.suspeitas, "sim:novo-1") == NUMERO_PEDRO == m.bot.alertas[0].numero_verdadeiro
    assert roteiro.numero_no_alerta(m.suspeitas, "sim:novo-9") is None


# --------------------------------------------------------------------------- detecção (extra)


def test_mostrar_deteccao(m, capsys):
    roteiro.mostrar_deteccao(None, [])
    assert "não está conectado" in capsys.readouterr().out
    roteiro.mostrar_deteccao(m.guardiao, m.suspeitas)
    assert "nada analisado ainda" in capsys.readouterr().out
    _roteiro_completo(m)
    capsys.readouterr()
    roteiro.mostrar_deteccao(m.guardiao, m.suspeitas)
    saida = capsys.readouterr().out
    assert "número salvo nos contatos: Pedro Neto 5500987650003" in saida
    assert "sim:novo-3: sem suspeita" in saida and "suspeitas: 1" in saida


# --------------------------------------------------------------------------- conferência


def test_conferencia_ok_no_roteiro_completo(registrado, tela, capsys):
    m = registrado
    _roteiro_completo(m)
    capsys.readouterr()
    assert roteiro.conferir_sinal(m.guardiao, m.suspeitas, tela, "demonstracao") is True
    saida = capsys.readouterr().out
    assert "FALHOU" not in saida and "sinal de sucesso: OK (10 de 10 itens)" in saida
    assert f"[ok] alerta do golpe clássico com o número do Pedro ({NUMERO_PEDRO})" in saida


def test_conferencia_sem_iniciar_aponta_o_que_falta(registrado, tela, capsys):
    m = registrado
    assert roteiro.conferir_sinal(m.guardiao, m.suspeitas, tela, "demonstracao") is False
    saida = capsys.readouterr().out
    assert "[ok] bot do Guardião" in saida and "[ok] detecção pelo Gemini" in saida
    assert "[FALHOU] responsável cadastrada" in saida and "ninguém tocou Iniciar" in saida
    assert "o golpe clássico não gerou alerta" in saida and "o cenário não foi injetado" in saida
    assert "sinal de sucesso: FALHOU em 8 de 10 itens" in saida


def test_conferencia_sem_toque_aponta_o_caso(registrado, tela, capsys):
    m = registrado
    m.cadastrar()
    roteiro.abrir_caso(m.guardiao, m.analisadas, "golpe_classico")
    for cenario_id in roteiro.CENARIOS_SEM_ALERTA:
        m.canal.injetar(cenario_id)
    assert roteiro.conferir_sinal(m.guardiao, m.suspeitas, tela, "demonstracao") is False
    saida = capsys.readouterr().out
    assert "[ok] alerta do golpe clássico com o número do Pedro" in saida
    assert '[FALHOU] caso do Pedro como "golpe"' in saida and "aguardando o toque" in saida
    assert "[FALHOU] aviso no celular simulado" in saida and '[FALHOU] tela (api/casos) com o Pedro como "golpe"' in saida
    assert "FALHOU em 3 de 10 itens" in saida


def test_conferencia_sem_tela_e_com_alerta_indevido(m, capsys, monkeypatch):
    _roteiro_completo(m)
    original = m.guardiao.casos.caso_de
    pedro = m.caso("golpe_classico")
    monkeypatch.setattr(m.guardiao.casos, "caso_de", lambda r: pedro if r == "sim:novo-3" else original(r))
    capsys.readouterr()
    assert roteiro.conferir_sinal(m.guardiao, m.suspeitas, None, "demonstracao") is False
    saida = capsys.readouterr().out
    assert "a tela não está no ar" in saida
    assert "[FALHOU] contato novo sem pedido de dinheiro (Júlia) sem alerta" in saida and "gerou alerta" in saida


def test_conferencia_alerta_com_outro_numero_falha(m, capsys, monkeypatch):
    _roteiro_completo(m)
    monkeypatch.setattr(roteiro, "numero_no_alerta", lambda suspeitas, remetente: "+55 00 98765-9999")
    capsys.readouterr()
    roteiro.conferir_sinal(m.guardiao, m.suspeitas, None, "demonstracao")
    assert "o alerta saiu com +55 00 98765-9999; o esperado era" in capsys.readouterr().out


def test_conferencia_sem_bot_sem_gemini_e_fora_da_demonstracao(capsys):
    guardiao = Guardiao(CanalSimulado(), varredura_casos_s=None)
    guardiao.conectar()
    assert roteiro.conferir_sinal(guardiao, [], None, "demonstracao") is False
    saida = capsys.readouterr().out
    assert "[FALHOU] bot do Guardião" in saida and "falta o Secret TELEGRAM_BOT_TOKEN" in saida
    assert "[FALHOU] detecção pelo Gemini" in saida and "falta o Secret GEMINI_API_KEY" in saida
    guardiao.fechar()
    assert roteiro.conferir_sinal(None, [], None, "demonstracao") is False
    assert "sem Guardião" in capsys.readouterr().out
    assert roteiro.conferir_sinal(guardiao, [], None, "real") is False
    assert "pulando" in capsys.readouterr().out


# --------------------------------------------------------------------------- sessão do Telethon


def _sessao(pasta):
    pasta.mkdir(exist_ok=True)
    arquivos = [pasta / "guardiao.session", pasta / "guardiao.session-journal"]
    for arquivo in arquivos:
        arquivo.write_bytes(b"")
    (pasta / "casos.json").write_text("{}", encoding="utf-8")
    return arquivos


class _CanalReal:
    usar_conta = True

    def __init__(self, sair=None):
        self._sair = sair or (lambda: "encerrada")
        self.chamadas = []

    def sair(self):
        self.chamadas.append("sair")
        return self._sair()

    def fechar(self):
        self.chamadas.append("fechar")


def test_apagar_sessao_sem_canal_apaga_pelo_glob(tmp_path):
    arquivos = _sessao(tmp_path / "local")
    assert roteiro.apagar_sessao(None, tmp_path / "local") == "apagada_sem_login"
    assert not any(a.exists() for a in arquivos) and (tmp_path / "local" / "casos.json").exists()
    assert roteiro.apagar_sessao(None, tmp_path / "local") == "sem_sessao"
    assert roteiro.apagar_sessao(None, tmp_path / "nao-existe") == "sem_sessao"


def test_apagar_sessao_do_canal_real_chama_sair_e_fecha(tmp_path):
    arquivos = _sessao(tmp_path)
    canal = _CanalReal()
    assert roteiro.apagar_sessao(canal, tmp_path) == "encerrada"
    assert canal.chamadas == ["sair", "fechar"] and not any(a.exists() for a in arquivos)


def test_apagar_sessao_com_log_out_falhando_apaga_mesmo_assim(tmp_path, capsys):
    arquivos = _sessao(tmp_path)

    def falha():
        raise ConnectionError("sem rede")

    assert roteiro.apagar_sessao(_CanalReal(falha), tmp_path) == "logout_falhou_apagada"
    assert not any(a.exists() for a in arquivos)
    assert "log_out falhou: ConnectionError" in capsys.readouterr().err


def test_apagar_sessao_nao_faz_log_out_do_canal_simulado_nem_do_bot(tmp_path, sem_rede):
    _sessao(tmp_path)
    bot = TelegramCanal(None, None, TOKEN_FALSO, usar_conta=False, usar_bot=True)
    bot.sair = lambda: pytest.fail("o bot não tem sessão de conta")
    assert roteiro.apagar_sessao(bot, tmp_path) == "apagada_sem_login"
    _sessao(tmp_path)
    assert roteiro.apagar_sessao(CanalSimulado(), tmp_path) == "apagada_sem_login"


def test_apagar_sessao_usa_o_local_dir_por_padrao(tmp_path, monkeypatch):
    import guardiao.config as config

    monkeypatch.setattr(config, "LOCAL_DIR", tmp_path)
    arquivos = _sessao(tmp_path)
    assert roteiro.apagar_sessao() == "apagada_sem_login" and not any(a.exists() for a in arquivos)

