"""Alerta, toque, desfecho e casos (CAP-5, CAP-6), sem rede.

Canal simulado com um dublê do bot na saída, dublê do Gemini e relógio ajustável.
"""

import json
import os
import stat
import threading
from datetime import datetime, timedelta, timezone

import pytest

import guardiao.casos as casos_mod
from duble_gemini import DubleRegras
from guardiao.analise import Analisador, Detector, ResultadoAnalise
from guardiao.busca import ResultadoBusca
from guardiao.canal.base import Contato, InicioBot, RespostaAlerta, texto_alerta
from guardiao.canal.cenarios import CENARIOS, ID_IDOSA, obter_cenario
from guardiao.canal.simulado import CanalSimulado
from guardiao.canal.telegram import TelegramCanal, dados_botao, teclado_alerta
from guardiao.casos import (
    CAMPOS_ARQUIVO,
    Caso,
    GestorCasos,
    RepositorioCasos,
    SemResponsavel,
    caso_para_dict,
    formatar_numero,
    pronome,
    quem_diz_ser,
    texto_aviso,
)
from guardiao.recepcao import Guardiao, RelogioAjustavel
from test_canal_offline import BotFalso
from test_simulado import TOKEN_FALSO, sem_rede  # noqa: F401 (fixture)

RESPONSAVEL = 7987654321
OUTRA = 7111222333
BOT = {"id": 7555000111, "username": "guardiao_teste_bot"}
AVISO_PEDRO = (
    "Dona Maria, chegou uma mensagem de um número novo dizendo ser Pedro. Não faça nenhum Pix agora. "
    "Ana está confirmando com ele. Ninguém vai ficar bravo se a senhora esperar."
)
NUMERO_PEDRO = "+55 00 98765-0003 (salvo como Pedro Neto)"


class DubleBot:
    """Dublê do bot na saída do canal simulado: guarda alertas e avisos e simula toques."""

    def __init__(self):
        self.handler = None
        self.alertas = []
        self.avisos = []
        self.falhar_alerta: Exception | None = None
        self.fechado = False

    def receber_mensagens(self, handler):
        self.handler = handler

    def info_bot(self):
        return dict(BOT)

    def enviar_alerta(self, alerta):
        if self.falhar_alerta is not None:
            raise self.falhar_alerta
        self.alertas.append(alerta)
        return str(100 + len(self.alertas))

    def enviar_aviso(self, destinatario, texto):
        self.avisos.append((destinatario, texto))
        return "200"

    def fechar(self):
        self.fechado = True

    def tocar(self, resposta, caso_id=None, respondente=RESPONSAVEL):
        caso_id = caso_id or self.alertas[-1].caso_id
        self.handler(RespostaAlerta("101", caso_id, resposta, respondente))


class Montagem:
    def __init__(self, tmp_path, cadastrar=True, arquivo=True, **kwargs):
        self.bot = DubleBot()
        self.canal = CanalSimulado(saida=self.bot)
        self.relogio = RelogioAjustavel()
        self.suspeitas = []
        self.analisador = Analisador(
            Detector(DubleRegras()),
            self.canal.listar_contatos,
            ao_suspeitar=self.suspeitas.append,
            relogio=self.relogio,
            varredura_s=None,
        )
        self.arquivo = tmp_path / "local" / "casos.json" if arquivo else None
        self.guardiao = Guardiao(
            self.canal,
            relogio=self.relogio,
            analisador=self.analisador,
            casos_arquivo=self.arquivo,
            como_chama_idosa="sua mãe",
            varredura_casos_s=None,
            **kwargs,
        )
        self.guardiao.conectar()
        if cadastrar:
            self.cadastrar()

    def cadastrar(self):
        link = self.guardiao.link_cadastro()
        self.bot.handler(InicioBot(RESPONSAVEL, RESPONSAVEL, parametro=link.split("?start=")[1], nome="Ana"))
        self.bot.avisos.clear()  # o "Pronto" do cadastro

    @property
    def casos(self):
        return self.guardiao.casos

    def caso(self, cenario_id):
        return self.casos.caso_de(obter_cenario(cenario_id).remetente_id)

    def avisos_no_celular(self):
        return [linha.texto for linha in self.canal.celular() if linha.tipo == "aviso"]

    def arquivo_json(self):
        return json.loads(self.arquivo.read_text(encoding="utf-8"))


@pytest.fixture
def m(tmp_path, sem_rede):
    montagem = Montagem(tmp_path)
    yield montagem
    montagem.guardiao.fechar()


# --------------------------------------------------------------------------- golpe clássico


def test_golpe_classico_abre_caso_aguardando_e_alerta_a_responsavel(m):
    m.canal.injetar("golpe_classico")
    caso = m.caso("golpe_classico")
    assert caso.estado == "aguardando" and caso.resposta is None
    assert caso.prazo_em - caso.criado_em == timedelta(minutes=10)
    [alerta] = m.bot.alertas
    assert alerta.destinatario == RESPONSAVEL and alerta.caso_id == caso.id
    assert alerta.nome_alegado == "Pedro" and alerta.como_chama_idosa == "sua mãe"
    assert alerta.numero_verdadeiro == NUMERO_PEDRO
    texto = texto_alerta(alerta)
    assert texto.startswith("Um número novo está dizendo ser Pedro e pediu dinheiro para sua mãe.")
    assert 'Mensagem recebida: "Vó, preciso de um Pix de R$ 850' in texto
    assert f"O número salvo nos contatos para esse nome é {NUMERO_PEDRO}." in texto
    botoes = teclado_alerta(alerta.caso_id)["inline_keyboard"][0]
    assert [b["text"] for b in botoes] == ["É golpe", "Era ele mesmo"]
    assert m.guardiao.filtro.contagens()["com_alerta"] == 1  # filtro.registrar_alerta
    assert m.avisos_no_celular() == [] and m.bot.avisos == []
    assert m.guardiao.estado()["casos"] == {"aguardando": 1, "golpe": 0, "era_ele_mesmo": 0, "sem_resposta": 0}


def test_e_golpe_avisa_a_pessoa_idosa_e_o_numero_continua_suspeito(m):
    m.canal.injetar("golpe_classico")
    m.relogio.adiantar(minutes=2)
    m.bot.tocar("golpe")
    caso = m.caso("golpe_classico")
    assert (caso.estado, caso.resposta) == ("golpe", "golpe")
    assert caso.avisado_em >= caso.respondido_em
    assert timedelta(minutes=2) <= caso.respondido_em - caso.criado_em < timedelta(minutes=2, seconds=5)
    assert m.avisos_no_celular() == [AVISO_PEDRO]
    assert m.bot.avisos == []  # o aviso à pessoa idosa não sai pelo bot no modo demonstração
    m.canal.injetar_mensagem("sim:novo-1", "Vó, faz logo o Pix, por favor!")
    assert m.analisador.ultimos()[-1].situacao == "ja_suspeito"
    assert len(m.bot.alertas) == 1 and m.guardiao.filtro.situacao("sim:novo-1") == "observado"
    m.relogio.adiantar(minutes=20)
    assert m.casos.verificar_prazos() == []  # o prazo não vale mais para um caso decidido
    assert m.avisos_no_celular() == [AVISO_PEDRO]


def test_era_ele_mesmo_libera_o_contato_sem_aviso(m):
    m.canal.injetar("parente_trocou_numero")
    [alerta] = m.bot.alertas
    assert alerta.nome_alegado == "Lucas" and alerta.numero_verdadeiro == "+55 00 98765-0002 (salvo como Lucas Filho)"
    m.bot.tocar("era_ele_mesmo")
    caso = m.caso("parente_trocou_numero")
    assert (caso.estado, caso.resposta) == ("era_ele_mesmo", "era_ele_mesmo") and caso.avisado_em is None
    assert m.guardiao.filtro.situacao("sim:novo-2") == "conhecido"
    assert not m.analisador.suspeito("sim:novo-2")
    assert m.avisos_no_celular() == [] and m.bot.avisos == []
    antes = len(m.analisador.ultimos())
    m.canal.injetar_mensagem("sim:novo-2", "Mãe, chegou a transferência?")
    assert len(m.analisador.ultimos()) == antes  # conhecido: nem chega à análise


# --------------------------------------------------------------------------- prazo


def test_dez_minutos_sem_resposta_avisam_uma_vez(m):
    m.canal.injetar("golpe_classico")
    m.relogio.adiantar(minutes=9, seconds=59)
    assert m.casos.verificar_prazos() == [] and m.caso("golpe_classico").estado == "aguardando"
    m.relogio.adiantar(seconds=1)
    [vencido] = m.casos.verificar_prazos()
    assert vencido.estado == "sem_resposta" and vencido.resposta is None and vencido.avisado_em is not None
    assert m.avisos_no_celular() == [AVISO_PEDRO]
    assert m.casos.verificar_prazos() == []
    assert m.avisos_no_celular() == [AVISO_PEDRO]
    assert m.analisador.suspeito("sim:novo-1")  # sem reanálise nem novo alerta


def test_prazo_configuravel(tmp_path, sem_rede):
    montagem = Montagem(tmp_path, prazo_resposta=timedelta(minutes=3))
    montagem.canal.injetar("golpe_classico")
    montagem.relogio.adiantar(minutes=3)
    assert [c.estado for c in montagem.casos.verificar_prazos()] == ["sem_resposta"]


def test_toque_tardio_era_ele_mesmo_libera_sem_novo_aviso_e_os_outros_sao_ignorados(m):
    m.canal.injetar("parente_trocou_numero")
    m.relogio.adiantar(minutes=10)
    m.casos.verificar_prazos()
    aviso_lucas = m.avisos_no_celular()
    assert len(aviso_lucas) == 1 and "dizendo ser Lucas" in aviso_lucas[0]
    m.bot.tocar("golpe")  # tardio, mas não é "Era ele mesmo": ignorado
    assert m.caso("parente_trocou_numero").estado == "sem_resposta"
    m.bot.tocar("era_ele_mesmo")
    caso = m.caso("parente_trocou_numero")
    assert (caso.estado, caso.resposta) == ("era_ele_mesmo", "era_ele_mesmo")
    assert m.guardiao.filtro.situacao("sim:novo-2") == "conhecido" and not m.analisador.suspeito("sim:novo-2")
    m.bot.tocar("golpe")
    m.bot.tocar("era_ele_mesmo")
    assert m.caso("parente_trocou_numero").respondido_em == caso.respondido_em
    assert m.avisos_no_celular() == aviso_lucas


def test_toques_num_caso_ja_decidido_sao_ignorados(m):
    m.canal.injetar("golpe_classico")
    m.bot.tocar("golpe")
    decidido = m.caso("golpe_classico")
    m.relogio.adiantar(minutes=1)
    m.bot.tocar("era_ele_mesmo")
    m.bot.tocar("golpe")
    assert m.caso("golpe_classico") == decidido
    assert m.guardiao.filtro.situacao("sim:novo-1") == "observado"
    assert len(m.avisos_no_celular()) == 1


# --------------------------------------------------------------------------- sem correspondência


def test_nome_fora_dos_contatos_alerta_sem_numero(m):
    m.canal.injetar_mensagem("sim:novo-9", "Oi vó, é o Rafael! Troquei de número.")
    m.canal.injetar_mensagem("sim:novo-9", "Vó, preciso de um Pix de R$ 400 hoje, depois te explico.")
    [alerta] = m.bot.alertas
    assert alerta.numero_verdadeiro is None and alerta.nome_alegado == "Rafael"
    assert texto_alerta(alerta).splitlines()[-1] == (
        "Não achei esse nome nos contatos. Confirme com a família antes de qualquer coisa."
    )


# --------------------------------------------------------------------------- sem responsável / falha no envio


def test_sem_responsavel_nenhum_caso_e_reanalisa_na_proxima_mensagem(tmp_path, sem_rede, capsys):
    montagem = Montagem(tmp_path, cadastrar=False)
    montagem.canal.injetar("golpe_classico")
    assert montagem.casos.listar() == [] and montagem.bot.alertas == []
    assert not montagem.analisador.suspeito("sim:novo-1")
    assert not montagem.arquivo.exists()
    assert len(montagem.suspeitas) == 1  # o observador antigo roda primeiro
    erro = capsys.readouterr().err
    assert "SemResponsavel" in erro and "Pedro" not in erro and "Pix" not in erro
    montagem.cadastrar()
    montagem.canal.injetar_mensagem("sim:novo-1", "Vó, faz o Pix, por favor!")
    caso = montagem.caso("golpe_classico")
    assert caso is not None and caso.estado == "aguardando" and len(montagem.bot.alertas) == 1
    assert montagem.bot.alertas[0].nome_alegado == "Pedro"  # a janela ficou: a conversa inteira foi reanalisada


def test_falha_no_envio_do_alerta_nenhum_caso_e_reanalisa(m, capsys):
    m.bot.falhar_alerta = ConnectionError("detalhe com texto")
    m.canal.injetar("golpe_classico")
    assert m.casos.listar() == [] and m.casos.contagens()["aguardando"] == 0
    assert not m.analisador.suspeito("sim:novo-1")
    assert m.guardiao.filtro.contagens()["com_alerta"] == 0
    assert m.arquivo_json()["casos"] == []  # gravado de novo sem o caso
    erro = capsys.readouterr().err
    assert "ConnectionError" in erro and "detalhe com texto" not in erro
    m.bot.falhar_alerta = None
    m.canal.injetar_mensagem("sim:novo-1", "Vó, faz o Pix, por favor!")
    assert m.caso("golpe_classico").estado == "aguardando" and len(m.bot.alertas) == 1


def test_abrir_direto_sem_responsavel_levanta(tmp_path):
    gestor = GestorCasos(CanalSimulado(saida=DubleBot()), varredura_s=None)
    with pytest.raises(SemResponsavel):
        gestor.abrir(_resultado())
    assert gestor.listar() == []


# --------------------------------------------------------------------------- toque inválido


def test_toque_de_caso_desconhecido_ou_de_outra_conta_e_ignorado(m):
    m.canal.injetar("golpe_classico")
    caso = m.caso("golpe_classico")
    m.bot.tocar("golpe", caso_id="inventado")
    m.bot.tocar("golpe", respondente=OUTRA)  # o Guardião só aceita a responsável cadastrada
    assert m.casos.responder(RespostaAlerta("101", caso.id, "golpe", OUTRA)) is None  # nem direto no gestor
    assert m.caso("golpe_classico") == caso and m.avisos_no_celular() == []


# --------------------------------------------------------------------------- persistência


def test_arquivo_so_com_os_campos_permitidos_e_sem_texto_alem_do_trecho(m):
    m.canal.injetar("golpe_classico")
    m.bot.tocar("golpe")
    m.canal.injetar("parente_trocou_numero")
    bruto = m.arquivo.read_text(encoding="utf-8")
    dados = json.loads(bruto)
    assert set(dados) == {"versao", "casos"} and len(dados["casos"]) == 2
    for caso in dados["casos"]:
        assert set(caso) == set(CAMPOS_ARQUIVO)
    trechos = {c["trecho"] for c in dados["casos"]}
    assert trechos == {obter_cenario("golpe_classico").mensagens[1], obter_cenario("parente_trocou_numero").mensagens[1]}
    for cenario in CENARIOS:
        for texto in cenario.mensagens:
            if texto not in trechos:
                assert texto not in bruto
    for proibido in ("sim:", "5500", "98765", "Pedro Neto", "Lucas Filho", str(RESPONSAVEL), "Ana", "sua mãe", "Dona Maria"):
        assert proibido not in bruto, proibido
    assert {(c["nome_alegado"], c["parentesco"]) for c in dados["casos"]} == {("Pedro", "neto"), ("Lucas", "filho")}


def test_arquivo_com_modo_600_e_pasta_700(m):
    m.canal.injetar("golpe_classico")
    assert stat.S_IMODE(m.arquivo.stat().st_mode) == 0o600
    assert stat.S_IMODE(m.arquivo.parent.stat().st_mode) == 0o700
    assert [p.name for p in m.arquivo.parent.iterdir()] == ["casos.json"]  # nenhum temporário sobrando


def test_escrita_atomica_falha_nao_corrompe_o_arquivo(m, monkeypatch, capsys):
    m.canal.injetar("golpe_classico")
    antes = m.arquivo.read_text(encoding="utf-8")

    def falhar(*args):
        raise OSError("disco cheio")

    monkeypatch.setattr(casos_mod.os, "replace", falhar)
    m.bot.tocar("golpe")
    assert m.caso("golpe_classico").estado == "golpe"  # a transição vale mesmo sem gravar
    assert m.arquivo.read_text(encoding="utf-8") == antes
    assert [p.name for p in m.arquivo.parent.iterdir()] == ["casos.json"]
    assert "casos não gravados: OSError" in capsys.readouterr().err


def test_arquivo_reflete_cada_transicao(m):
    m.canal.injetar("golpe_classico")
    assert [c["estado"] for c in m.arquivo_json()["casos"]] == ["aguardando"]
    m.bot.tocar("golpe")
    [caso] = m.arquivo_json()["casos"]
    assert (caso["estado"], caso["resposta"]) == ("golpe", "golpe")
    assert caso["respondido_em"] and caso["avisado_em"]


def test_reinicio_carrega_aguardando_como_sem_resposta_sem_aviso(tmp_path, sem_rede):
    primeira = Montagem(tmp_path)
    primeira.canal.injetar("golpe_classico")
    primeira.canal.injetar("parente_trocou_numero")
    primeira.bot.tocar("era_ele_mesmo")
    primeira.guardiao.fechar()

    segunda = Montagem(tmp_path)
    estados = sorted((c["quem"], c["estado"]) for c in segunda.casos.listar())
    assert estados == [("Lucas", "era_ele_mesmo"), ("Pedro", "sem_resposta")]
    assert segunda.avisos_no_celular() == []
    assert sorted(c["estado"] for c in segunda.arquivo_json()["casos"]) == ["era_ele_mesmo", "sem_resposta"]
    segunda.relogio.adiantar(minutes=30)
    assert segunda.casos.verificar_prazos() == [] and segunda.avisos_no_celular() == []


def test_toque_em_caso_de_outra_execucao_e_ignorado(tmp_path, sem_rede):
    primeira = Montagem(tmp_path)
    primeira.canal.injetar("golpe_classico")
    caso_id = primeira.caso("golpe_classico").id
    primeira.guardiao.fechar()

    segunda = Montagem(tmp_path)
    assert segunda.casos.obter(caso_id).estado == "sem_resposta"
    segunda.bot.tocar("era_ele_mesmo", caso_id=caso_id)
    assert segunda.casos.obter(caso_id).estado == "sem_resposta"
    assert [c["estado"] for c in segunda.arquivo_json()["casos"]] == ["sem_resposta"]
    segunda.guardiao.fechar()


def test_retencao_apaga_na_varredura_e_na_carga(tmp_path, sem_rede):
    montagem = Montagem(tmp_path)
    montagem.canal.injetar("golpe_classico")
    montagem.bot.tocar("golpe")
    montagem.relogio.adiantar(29)
    montagem.casos.verificar_prazos()
    assert len(montagem.casos.listar()) == 1
    montagem.relogio.adiantar(1, seconds=1)
    montagem.casos.verificar_prazos()
    assert montagem.casos.listar() == [] and montagem.arquivo_json()["casos"] == []

    # na carga: um caso de 31 dias atrás no arquivo
    antigo = Caso(
        id="antigo",
        estado="golpe",
        criado_em=datetime.now(timezone.utc) - timedelta(days=31),
        prazo_em=datetime.now(timezone.utc) - timedelta(days=31),
        trecho="trecho antigo",
    )
    recente = Caso(
        id="recente",
        estado="golpe",
        criado_em=datetime.now(timezone.utc) - timedelta(days=1),
        prazo_em=datetime.now(timezone.utc) - timedelta(days=1),
        trecho="trecho recente",
    )
    RepositorioCasos(montagem.arquivo).salvar([antigo, recente])
    carregado = GestorCasos(CanalSimulado(), RepositorioCasos(montagem.arquivo), varredura_s=None)
    assert [c["trecho"] for c in carregado.listar()] == ["trecho recente"]
    assert "trecho antigo" not in montagem.arquivo.read_text(encoding="utf-8")


def test_apagar_tudo_apaga_memoria_e_arquivo(m):
    m.canal.injetar("golpe_classico")
    assert m.arquivo.exists()
    m.casos.apagar_tudo()
    assert m.casos.listar() == [] and not m.arquivo.exists()
    assert m.casos.caso_de("sim:novo-1") is None
    m.bot.tocar("golpe")  # o caso apagado não existe mais
    assert m.avisos_no_celular() == []


def test_arquivo_ilegivel_ou_caso_invalido_e_descartado(tmp_path, capsys):
    arquivo = tmp_path / "casos.json"
    arquivo.write_text("{não é json", encoding="utf-8")
    assert GestorCasos(CanalSimulado(), RepositorioCasos(arquivo), varredura_s=None).listar() == []
    agora = datetime.now(timezone.utc).isoformat()
    bom = {"id": "a", "estado": "golpe", "trecho": "t", "criado_em": agora, "prazo_em": agora, "resposta": "golpe"}
    arquivo.write_text(
        json.dumps({"versao": 1, "casos": [bom, {"id": "b", "estado": "outro", "trecho": "t"}, "lixo"]}),
        encoding="utf-8",
    )
    assert [c["estado"] for c in GestorCasos(CanalSimulado(), RepositorioCasos(arquivo), varredura_s=None).listar()] == [
        "golpe"
    ]
    erro = capsys.readouterr().err
    assert "ilegível" in erro and "caso inválido descartado" in erro


def test_sem_arquivo_nada_vai_para_o_disco(tmp_path, sem_rede, monkeypatch):
    monkeypatch.chdir(tmp_path)
    montagem = Montagem(tmp_path, arquivo=False)
    montagem.canal.injetar("golpe_classico")
    assert montagem.caso("golpe_classico").estado == "aguardando"
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- concorrência


class CanalContador:
    def __init__(self):
        self.alertas = []
        self.avisos = []
        self.trava = threading.Lock()

    def enviar_alerta(self, alerta):
        self.alertas.append(alerta)
        return "1"

    def enviar_aviso(self, destinatario, texto):
        with self.trava:
            self.avisos.append(texto)
        return "2"


class Responsavel:
    usuario_id = RESPONSAVEL
    destinatario = RESPONSAVEL
    nome = "Ana"


def _resultado(nome="Pedro", parentesco="neto", contato=None, remetente="sim:novo-1"):
    from guardiao.analise import Analise

    analise = Analise(True, True, nome_alegado=nome, parentesco=parentesco, forma_pagamento="pix")
    busca = ResultadoBusca("encontrado", contato=contato, candidatos=1) if contato else ResultadoBusca("sem_correspondencia")
    return ResultadoAnalise(remetente, "suspeita", datetime.now(timezone.utc), analise, busca, "Vó, faz um Pix?")


def _gestor(canal, relogio, arquivo=None, **kwargs):
    return GestorCasos(
        canal,
        RepositorioCasos(arquivo),
        relogio=relogio,
        responsavel=lambda: Responsavel,
        destinatario_idosa=lambda: ID_IDOSA,
        nome_idosa="Dona Maria",
        varredura_s=None,
        **kwargs,
    )


def test_toque_e_prazo_ao_mesmo_tempo_geram_um_aviso_so(tmp_path):
    for rodada in range(40):
        canal = CanalContador()
        relogio = RelogioAjustavel()
        gestor = _gestor(canal, relogio, tmp_path / f"casos-{rodada}.json")
        caso = gestor.abrir(_resultado())
        relogio.adiantar(minutes=10)
        largada = threading.Barrier(2)

        def tocar():
            largada.wait()
            gestor.responder(RespostaAlerta("1", caso.id, "golpe", RESPONSAVEL))

        def prazo():
            largada.wait()
            gestor.verificar_prazos()

        threads = [threading.Thread(target=tocar), threading.Thread(target=prazo)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        final = gestor.obter(caso.id)
        assert final.estado in ("golpe", "sem_resposta")
        assert len(canal.avisos) == 1, rodada
        assert final.avisado_em is not None


def test_aviso_sai_fora_da_trava_com_o_estado_ja_gravado(tmp_path):
    arquivo = tmp_path / "casos.json"
    vistos = []

    class CanalQueConfere(CanalContador):
        def enviar_aviso(self, destinatario, texto):
            livre = gestor._trava.acquire(blocking=False)  # sem `assert` aqui: o repr do gestor usa a trava
            if livre:
                gestor._trava.release()
            estados = sorted(c["estado"] for c in json.loads(arquivo.read_text(encoding="utf-8"))["casos"])
            vistos.append((livre, estados))
            return super().enviar_aviso(destinatario, texto)

    relogio = RelogioAjustavel()
    gestor = _gestor(CanalQueConfere(), relogio, arquivo)
    caso = gestor.abrir(_resultado())
    gestor.responder(RespostaAlerta("1", caso.id, "golpe", RESPONSAVEL))
    relogio.adiantar(minutes=10)
    outro = gestor.abrir(_resultado(remetente="sim:novo-8"))
    relogio.adiantar(minutes=10)
    gestor.verificar_prazos()
    # a trava estava livre e o arquivo já dizia "golpe" (toque) e "sem_resposta" (prazo)
    assert vistos == [(True, ["golpe"]), (True, ["golpe", "sem_resposta"])]
    assert gestor.obter(outro.id).estado == "sem_resposta" and len(gestor.canal.avisos) == 2


def test_toque_que_chega_antes_do_envio_terminar_acha_o_caso(tmp_path):
    class CanalComToqueImediato(CanalContador):
        def enviar_alerta(self, alerta):
            gestor.responder(RespostaAlerta("1", alerta.caso_id, "golpe", RESPONSAVEL))
            return super().enviar_alerta(alerta)

    canal = CanalComToqueImediato()
    gestor = _gestor(canal, RelogioAjustavel())
    caso = gestor.abrir(_resultado())
    assert gestor.obter(caso.id).estado == "golpe" and len(canal.avisos) == 1


class CanalSemAviso(CanalContador):
    """O aviso falha enquanto `falhar` for verdadeiro."""

    falhar = True

    def enviar_aviso(self, destinatario, texto):
        if self.falhar:
            raise ConnectionError("texto do aviso")
        return super().enviar_aviso(destinatario, texto)


def test_falha_no_aviso_mantem_o_estado(tmp_path, capsys):
    canal = CanalSemAviso()
    gestor = _gestor(canal, RelogioAjustavel(), tmp_path / "casos.json")
    caso = gestor.abrir(_resultado())
    gestor.responder(RespostaAlerta("1", caso.id, "golpe", RESPONSAVEL))
    final = gestor.obter(caso.id)
    assert final.estado == "golpe" and final.avisado_em is None and canal.avisos == []
    erro = capsys.readouterr().err
    assert "aviso à pessoa idosa não saiu (caso golpe): ConnectionError" in erro and "texto do aviso" not in erro


def test_aviso_que_falhou_sai_uma_vez_na_proxima_verificacao(tmp_path):
    canal = CanalSemAviso()
    relogio = RelogioAjustavel()
    gestor = _gestor(canal, relogio, tmp_path / "casos.json")
    golpe = gestor.abrir(_resultado())
    gestor.responder(RespostaAlerta("1", golpe.id, "golpe", RESPONSAVEL))
    prazo = gestor.abrir(_resultado(remetente="sim:novo-8"))
    relogio.adiantar(minutes=10)
    gestor.verificar_prazos()  # o prazo vence, mas o aviso falha de novo
    assert gestor.obter(prazo.id).estado == "sem_resposta" and canal.avisos == []
    canal.falhar = False
    assert gestor.verificar_prazos() == []  # nada venceu agora; os dois avisos pendentes saem
    assert len(canal.avisos) == 2
    assert gestor.obter(golpe.id).avisado_em is not None and gestor.obter(prazo.id).avisado_em is not None
    gestor.verificar_prazos()
    assert len(canal.avisos) == 2  # uma vez só


def test_aviso_pendente_de_caso_carregado_do_arquivo_nao_e_reenviado(tmp_path):
    arquivo = tmp_path / "casos.json"
    canal = CanalSemAviso()
    gestor = _gestor(canal, RelogioAjustavel(), arquivo)
    caso = gestor.abrir(_resultado())
    gestor.responder(RespostaAlerta("1", caso.id, "golpe", RESPONSAVEL))
    canal2 = CanalContador()
    carregado = _gestor(canal2, RelogioAjustavel(), arquivo)
    assert carregado.obter(caso.id).avisado_em is None
    carregado.verificar_prazos()
    assert canal2.avisos == []


def test_varredura_em_thread_aplica_o_prazo_e_para_no_fechar():
    import time

    canal = CanalContador()
    relogio = RelogioAjustavel()
    antes = set(threading.enumerate())
    gestor_varrendo = GestorCasos(
        canal,
        relogio=relogio,
        responsavel=lambda: Responsavel,
        destinatario_idosa=lambda: ID_IDOSA,
        varredura_s=0.01,
    )
    caso = gestor_varrendo.abrir(_resultado())
    relogio.adiantar(minutes=10)
    limite = time.monotonic() + 5
    while gestor_varrendo.obter(caso.id).estado == "aguardando" and time.monotonic() < limite:
        time.sleep(0.01)
    assert gestor_varrendo.obter(caso.id).estado == "sem_resposta" and len(canal.avisos) == 1
    threads = [t for t in set(threading.enumerate()) - antes if t.name == "guardiao-casos"]
    assert len(threads) == 1
    gestor_varrendo.fechar()
    for t in threads:
        t.join(2)
    assert not any(t.is_alive() for t in threads)


def test_guardiao_fechar_para_a_varredura(tmp_path, sem_rede):
    montagem = Montagem(tmp_path)
    assert not montagem.casos._parar.is_set()
    montagem.guardiao.fechar()
    assert montagem.casos._parar.is_set() and montagem.bot.fechado


# --------------------------------------------------------------------------- textos e consulta


def test_quem_diz_ser_e_pronome():
    assert quem_diz_ser("Pedro", "neto") == "Pedro"
    assert quem_diz_ser(None, "neto") == "o neto"
    assert quem_diz_ser("  ", "filha") == "a filha"
    assert quem_diz_ser(None, "irmao") == "o irmão"
    assert quem_diz_ser(None, "outro") == "um parente"
    assert quem_diz_ser(None, None) == "um parente"
    assert [pronome(p) for p in ("neta", "filha", "irma", "nora", "neto", "outro", None)] == [
        "ela",
        "ela",
        "ela",
        "ela",
        "ele",
        "ele",
        "ele",
    ]


def test_texto_aviso_segue_o_modelo_no_tom_calmo():
    assert texto_aviso("Dona Maria", "Pedro", "Ana", "neto") == AVISO_PEDRO
    texto = texto_aviso("Dona Maria", "a neta", None, "neta")
    assert "dizendo ser a neta" in texto and "A família está confirmando com ela." in texto
    for palavra in ("golpe", "fraude", "perigo"):
        assert palavra not in (AVISO_PEDRO + texto).lower()


def test_alerta_sem_nome_usa_o_parentesco(tmp_path):
    canal = CanalContador()
    gestor = _gestor(canal, RelogioAjustavel())
    gestor.abrir(_resultado(nome=None, parentesco="filha"))
    assert canal.alertas[-1].nome_alegado == "a filha"
    assert canal.alertas[-1].como_chama_idosa == "Dona Maria"  # padrão: o nome da pessoa idosa
    gestor.abrir(_resultado(nome=None, parentesco=None, remetente="sim:novo-8"))
    assert canal.alertas[-1].nome_alegado == "um parente"


def test_numero_verdadeiro_formatado_com_o_nome_salvo():
    canal = CanalContador()
    gestor = _gestor(canal, RelogioAjustavel())
    gestor.abrir(_resultado(contato=Contato("sim:pedro", "Pedro Neto", "5500987650003")))
    assert canal.alertas[-1].numero_verdadeiro == NUMERO_PEDRO


def test_formatar_numero():
    assert formatar_numero("5500987650003") == "+55 00 98765-0003"
    assert formatar_numero("+55 00 98765-0003") == "+55 00 98765-0003"
    assert formatar_numero("550098765000") == "+55 00 9876-5000"  # fixo, 8 dígitos
    assert formatar_numero("351912345678") == "+351912345678"
    assert formatar_numero("") is None and formatar_numero(None) is None and formatar_numero("abc") is None


def test_listar_sem_ids_do_mais_recente(m):
    m.canal.injetar("golpe_classico")
    m.relogio.adiantar(minutes=1)
    m.canal.injetar("parente_trocou_numero")
    lista = m.casos.listar()
    assert [c["quem"] for c in lista] == ["Lucas", "Pedro"]
    for item in lista:
        assert "id" not in item and item["estado"] == "aguardando" and item["trecho"]
        assert not any("sim:" in str(v) or str(RESPONSAVEL) in str(v) for v in item.values())
    assert set(lista[0]) == (set(CAMPOS_ARQUIVO) - {"id"}) | {"quem"}


def test_repr_sem_trecho_nem_nome():
    caso = Caso("x", "golpe", datetime.now(timezone.utc), datetime.now(timezone.utc), "Vó, Pix", "Pedro", "neto")
    assert "Pix" not in repr(caso) and "Pedro" not in repr(caso)
    assert "trecho" in caso_para_dict(caso)


def test_id_do_caso_cabe_no_callback_data(m):
    m.canal.injetar("golpe_classico")
    caso_id = m.caso("golpe_classico").id
    assert dados_botao("era_ele_mesmo", caso_id).endswith(caso_id)


# --------------------------------------------------------------------------- observador antigo e encadeamento


def test_observador_antigo_com_defeito_nao_impede_o_caso(tmp_path, sem_rede, capsys):
    montagem = Montagem(tmp_path)

    def quebrado(_):
        raise RuntimeError("observador")

    montagem.analisador.ao_suspeitar = montagem.guardiao._encadear_suspeita(quebrado)
    montagem.canal.injetar("golpe_classico")
    assert montagem.caso("golpe_classico").estado == "aguardando"
    assert "ao_suspeitar falhou: RuntimeError" in capsys.readouterr().err


def test_ao_responder_com_defeito_nao_impede_o_desfecho(tmp_path, sem_rede, capsys):
    def quebrado(_):
        raise RuntimeError("observador")

    montagem = Montagem(tmp_path, ao_responder=quebrado)
    montagem.canal.injetar("golpe_classico")
    montagem.bot.tocar("golpe")
    assert montagem.caso("golpe_classico").estado == "golpe"
    assert montagem.avisos_no_celular() == [AVISO_PEDRO]
    assert "ao_responder falhou: RuntimeError" in capsys.readouterr().err


def test_ao_responder_continua_recebendo_o_toque(tmp_path, sem_rede):
    respostas = []
    montagem = Montagem(tmp_path, ao_responder=respostas.append)
    montagem.canal.injetar("golpe_classico")
    montagem.bot.tocar("golpe")
    assert [r.resposta for r in respostas] == ["golpe"] and montagem.caso("golpe_classico").estado == "golpe"


# --------------------------------------------------------------------------- bot falso de ponta a ponta (callback_data)


class BotFalsoComInfo(BotFalso):
    def get_me(self):
        return dict(BOT)


def _esperar(condicao, segundos=5):
    import time

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def test_toque_real_pelo_callback_data_decide_o_caso(tmp_path, sem_rede):
    bot = BotFalsoComInfo([])
    saida = TelegramCanal(None, None, TOKEN_FALSO, dir_sessao=tmp_path, usar_conta=False, espera_polling=0)
    saida._bot = bot
    canal = CanalSimulado(saida=saida)
    relogio = RelogioAjustavel()
    analisador = Analisador(Detector(DubleRegras()), canal.listar_contatos, relogio=relogio, varredura_s=None)
    guardiao = Guardiao(canal, relogio=relogio, analisador=analisador, varredura_casos_s=None)
    try:
        guardiao.conectar()
        codigo = guardiao.link_cadastro().split("?start=")[1]
        bot.lotes.append([{
            "update_id": 1,
            "message": {"from": {"id": RESPONSAVEL, "first_name": "Ana"}, "chat": {"id": RESPONSAVEL, "type": "private"},
                        "text": f"/start {codigo}", "date": 1},
        }])
        assert _esperar(lambda: guardiao.estado()["responsavel_cadastrada"])
        canal.injetar("golpe_classico")
        destino, texto, teclado = bot.enviados[-1]
        assert destino == RESPONSAVEL and NUMERO_PEDRO in texto
        golpe = teclado["inline_keyboard"][0][0]
        assert golpe["text"] == "É golpe"
        bot.lotes.append([{
            "update_id": 2,
            "callback_query": {"id": "cb1", "from": {"id": RESPONSAVEL}, "data": golpe["callback_data"],
                               "message": {"message_id": 77}},
        }])
        assert _esperar(lambda: guardiao.estado()["casos"]["golpe"] == 1)
        assert _esperar(lambda: any(l.tipo == "aviso" for l in canal.celular()))
        assert [l.texto for l in canal.celular() if l.tipo == "aviso"] == [AVISO_PEDRO]
        assert ("cb1", "Resposta registrada.") in bot.respondidos
    finally:
        guardiao.fechar()
