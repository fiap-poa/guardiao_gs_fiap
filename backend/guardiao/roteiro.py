"""Funções de apoio do notebook do Colab: as quatro fases e os três testes.

O notebook segue Filtra → Interpreta → Confere → Avisa e, no fim, os três testes do
enunciado. A conferência (`conferir_sinal`) lê o que as fases já produziram: o Pedro
(alerta, caso golpe, aviso e tela) e os descartes da Filtra. A Júlia fica no teste 2.
As células ficam curtas e chamam estas funções, que recebem tudo por parâmetro (o
Guardião, as listas de observação, o servidor da tela).

O que é impresso segue a regra do notebook: o texto só aparece quando é fictício (remetente
`sim:` do modo demonstração); do que foi descartado, nem isso. Nenhum id de conta real,
telefone real, código ou credencial.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from guardiao import config
from guardiao.canal.base import RespostaAlerta
from guardiao.canal.cenarios import obter_cenario
from guardiao.canal.simulado import FUSO_BRASILIA, descrever_recebido
from guardiao.casos import formatar_numero, numero_sugerido

SIM_NAO = {True: "sim", False: "não"}

MOTIVOS_DESCARTE = {
    "grupo": "grupo",
    "conhecido": "contato conhecido",
    "observacao_encerrada": "7 dias sem alerta: virou conhecido",
    "sem_remetente": "sem remetente",
}

SITUACOES = {
    "suspeita": "SUSPEITA: diz ser parente e pede dinheiro",
    "sem_suspeita": "sem suspeita",
    "ja_suspeito": "já marcado como suspeito (não reanalisa)",
    "falha": "falha ao consultar o Gemini",
    "sem_texto": "mensagem sem texto",
}

BUSCAS = {
    "encontrado": "número salvo nos contatos",
    "sem_correspondencia": "não achei esse nome nos contatos: o alerta segue sem número",
    "ambiguo": "mais de um contato com esse nome: o alerta segue sem número",
    "sem_nome": "a pessoa não disse o nome: o alerta segue sem número",
    "sem_telefone": "o contato não tem telefone salvo: o alerta segue sem número",
    "sem_contatos": "não consegui ler os contatos: o alerta segue sem número",
}

ESTADOS_CASO = {
    "aguardando": "aguardando o toque da responsável",
    "golpe": "golpe (a responsável tocou É golpe)",
    "era_ele_mesmo": "era ele mesmo (contato liberado)",
    "sem_resposta": "sem resposta (o prazo venceu)",
}

ROTULOS_TOQUE = {"golpe": "É golpe", "era_ele_mesmo": "Era ele mesmo"}

SESSAO = {
    "sem_sessao": "não havia sessão",
    "encerrada": "encerrada no Telegram e apagada",
    "apagada_sem_login": "apagada",
    "logout_falhou_apagada": "apagada (o log_out no Telegram falhou)",
}

# o roteiro do sinal de sucesso
CENARIO_GOLPE = "golpe_classico"
CENARIOS_SEM_ALERTA: tuple[str, ...] = ("contato_antigo_pede_dinheiro", "mensagem_em_grupo", "contato_novo_sem_dinheiro")
CONTATO_PEDRO = "sim:pedro"  # o contato salvo do neto Pedro (cenarios.py)
ROTULOS_SEM_ALERTA = {
    "contato_antigo_pede_dinheiro": "contato antigo (Carlos) sem alerta",
    "mensagem_em_grupo": "mensagem em grupo sem alerta",
    "contato_novo_sem_dinheiro": "contato novo sem pedido de dinheiro (Júlia) sem alerta",
}

INTERVALO_ESPERA_S = 0.5
TIMEOUT_TELA_S = 5


def _avisar(texto: str) -> None:
    print(f"[roteiro] {texto}", file=sys.stderr)


# --------------------------------------------------------------------------- horários


def hora(valor) -> str:
    """`HH:MM` no horário de Brasília; aceita `datetime` ou texto ISO (dos casos). Vazio → `-`."""
    if not valor:
        return "-"
    data = datetime.fromisoformat(valor) if isinstance(valor, str) else valor
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data.astimezone(FUSO_BRASILIA).strftime("%H:%M")


# --------------------------------------------------------------------------- injeção


def injetar_mostrando(guardiao, analisadas: list, injetar, *args, **kwargs):
    """Injeta e mostra a decisão do Guardião, sem mostrar o texto do que foi descartado.

    `analisadas` é a lista que o Guardião alimenta (`ao_analisar`); `injetar` é
    `canal.injetar` (cenário) ou `canal.injetar_mensagem` (mensagem avulsa).
    """
    ja_analisadas = len(analisadas)
    analisador = guardiao.analisador
    antes_resultados = analisador.ultimos() if analisador is not None else []
    antes = guardiao.filtro.contagens()["por_motivo"]
    devolvido = injetar(*args, **kwargs)
    for mensagem in analisadas[ja_analisadas:]:
        print("   análise:", descrever_recebido(mensagem))
    if analisador is not None:
        novos = [r for r in analisador.ultimos() if not any(r is a for a in antes_resultados)]
        for resultado in novos:
            print(f"   Gemini: {SITUACOES[resultado.situacao]}")
    depois = guardiao.filtro.contagens()["por_motivo"]
    for motivo, rotulo in MOTIVOS_DESCARTE.items():
        descartadas = depois.get(motivo, 0) - antes.get(motivo, 0)
        if descartadas:
            print(f"   descarte ({rotulo}): {descartadas} mensagem(ns), texto não lido")
    return devolvido


# --------------------------------------------------------------------------- cadastro


def descrever_estado(guardiao) -> str:
    """O estado do Guardião em linhas legíveis (sem ids nem nomes)."""
    estado = guardiao.estado()
    return "\n".join(
        (
            f"conta da pessoa idosa conectada:  {SIM_NAO[bool(estado['conectado'])]}",
            f"pessoa idosa habilitada no bot:   {SIM_NAO[bool(estado['idosa_habilitada'])]}",
            f"bot do Guardião:                  {SIM_NAO[bool(estado['tem_bot'])]}",
            f"responsável cadastrada:           {SIM_NAO[bool(estado['responsavel_cadastrada'])]}",
            f"contatos conhecidos: {estado['conhecidos']}; contatos novos observados: {estado['observados']}",
        )
    )


def esperar_cadastro(guardiao, espera_s: float, intervalo: float = INTERVALO_ESPERA_S) -> bool:
    """Espera a responsável tocar Iniciar pelo link (ou QR) da tela, até `espera_s` segundos.

    Devolve se ela está cadastrada. Sem Guardião ou sem bot, avisa e volta na hora; no tempo
    esgotado, avisa (as células seguintes pulam com aviso). Nunca levanta.
    """
    if guardiao is None:
        print("aviso: o Guardião não está conectado; rode a célula da seção 5")
        return False
    if guardiao.cadastro.cadastrada:
        print("a responsável já está cadastrada")
        return True
    if getattr(guardiao.canal, "tem_bot", True) is False:
        print("aviso: sem bot do Guardião (Secret TELEGRAM_BOT_TOKEN ausente): não há Iniciar a esperar;")
        print("as células seguintes pulam com aviso")
        return False
    print(f"esperando a responsável tocar Iniciar no bot (até {espera_s:g} s)...")
    limite = time.monotonic() + espera_s
    while not guardiao.cadastro.cadastrada and time.monotonic() < limite:
        time.sleep(intervalo)
    if guardiao.cadastro.cadastrada:
        print("responsável cadastrada: ela recebeu o \"Pronto\" pelo bot")
        return True
    print(f"aviso: ninguém tocou Iniciar em {espera_s:g} s; as células seguintes pulam com aviso.")
    print("Abra o link (ou leia o QR da tela) no Telegram da responsável, toque Iniciar e rode esta célula de novo.")
    return False


# --------------------------------------------------------------------------- alerta e toque


def falta_para_alertar(guardiao, modo: str) -> str | None:
    """O que falta para o roteiro com alerta rodar, ou `None` quando está tudo pronto."""
    if modo != "demonstracao":
        return "os cenários do roteiro só existem no modo demonstração; pulando"
    if guardiao is None:
        return "o Guardião não está conectado; rode a célula da seção 5"
    if guardiao.analisador is None:
        return "a detecção está desligada (sem GEMINI_API_KEY): crie o Secret e rode as seções 3 e 5 de novo"
    if not guardiao.estado()["tem_bot"]:
        return "sem bot do Guardião (sem TELEGRAM_BOT_TOKEN): crie o Secret e rode as seções 3 e 5 de novo"
    if not guardiao.estado()["responsavel_cadastrada"]:
        return "a responsável não está cadastrada: toque Iniciar pelo link da seção 6 e rode a seção 7 de novo"
    return None


def abrir_caso(guardiao, analisadas: list, cenario_id: str):
    """Injeta o cenário, se o número ainda não tem caso, e devolve o caso dele (ou `None`)."""
    remetente = obter_cenario(cenario_id).remetente_id
    caso = guardiao.casos.caso_de(remetente)
    if caso is None:
        guardiao.analisador.esquecer(remetente)  # uma conversa anterior sem alerta: recomeça do zero
        injetar_mostrando(guardiao, analisadas, guardiao.canal.injetar, cenario_id)
        caso = guardiao.casos.caso_de(remetente)
    return caso


def tocar(guardiao, caso, resposta: str, simulado: bool = False, espera_s: float = 180,
          intervalo: float = INTERVALO_ESPERA_S):
    """O toque da responsável: simulado (pelo mesmo caminho do bot) ou de verdade, no Telegram.

    De verdade, espera até `espera_s` o estado do caso mudar; devolve o caso como ficou.
    """
    if simulado:
        print(f'   (toque simulado: "{ROTULOS_TOQUE[resposta]}")')
        guardiao.tratar(RespostaAlerta("simulado", caso.id, resposta, guardiao.cadastro.responsavel.usuario_id))
        return guardiao.casos.obter(caso.id) or caso
    print(f'   no Telegram da responsável, toque "{ROTULOS_TOQUE[resposta]}" no alerta (espero até {espera_s:g} s)')
    limite = time.monotonic() + espera_s
    atual = guardiao.casos.obter(caso.id)
    while atual is not None and atual.estado == caso.estado and time.monotonic() < limite:
        time.sleep(intervalo)
        atual = guardiao.casos.obter(caso.id)
    return atual or caso


def numero_no_alerta(suspeitas: list, remetente_id) -> str | None:
    """O número verdadeiro que foi no alerta deste remetente (o da última suspeita dele)."""
    chave = str(remetente_id)
    do_remetente = [s for s in suspeitas if str(s.remetente_id) == chave]
    return numero_sugerido(do_remetente[-1]) if do_remetente else None


def numero_esperado_pedro(canal) -> str | None:
    """`+55 00 98765-0003 (salvo como Pedro Neto)`, montado do contato salvo do Pedro."""
    for contato in canal.listar_contatos():
        if contato.id == CONTATO_PEDRO:
            numero = formatar_numero(contato.telefone)
            return f"{numero} (salvo como {contato.nome})" if numero else None
    return None


# --------------------------------------------------------------------------- detecção (extra)


def mostrar_deteccao(guardiao, suspeitas: list) -> None:
    """O que o Gemini extraiu de cada mensagem analisada e, com suspeita, a busca do parente."""
    if guardiao is None:
        print("aviso: o Guardião não está conectado; rode a célula da seção 5")
        return
    if guardiao.analisador is None:
        print("aviso: a detecção está desligada (sem GEMINI_API_KEY): crie o Secret e rode as seções 3 e 5 de novo")
        return
    resultados = guardiao.analisador.ultimos()  # cópia: no modo real, chegam resultados de outra thread
    if not resultados:
        print("nada analisado ainda: rode a fase Interpreta (seção 9)")
        return
    for resultado in resultados:
        ficticio = str(resultado.remetente_id).startswith("sim:")  # conta real: sem textos
        print(f"== {resultado.remetente_id if ficticio else 'contato novo'}: {SITUACOES[resultado.situacao]}")
        analise = resultado.analise
        if analise is not None:
            print(f"   mensagens na janela: {resultado.mensagens_analisadas}")
            quem = f" ({analise.nome_alegado or 'sem nome'}, {analise.parentesco or 'parentesco não dito'})"
            print(f"   diz ser parente: {SIM_NAO[analise.alega_parentesco]}{quem if ficticio and analise.alega_parentesco else ''}")
            como = f" ({analise.forma_pagamento}; motivo: {analise.motivo or 'não disse'})"
            print(f"   pede dinheiro: {SIM_NAO[analise.pede_dinheiro]}{como if ficticio and analise.pede_dinheiro else ''}")
        if resultado.erro:
            print(f"   erro: {resultado.erro} (a mensagem fica na janela para a próxima análise)")
        if resultado.suspeita:
            busca = resultado.busca
            if ficticio:
                print(f'   trecho: "{resultado.trecho}"')
            if busca.numero and ficticio:
                print(f"   {BUSCAS[busca.motivo]}: {busca.contato.nome} {busca.numero}")
            else:
                print(f"   {BUSCAS[busca.motivo]}")
    print(f"\nsuspeitas: {len(suspeitas)}")


# --------------------------------------------------------------------------- conferência


def _casos_da_tela(servidor) -> list[dict]:
    """`GET api/casos` pelo HTTP local, como a tela lê."""
    url = f"http://127.0.0.1:{servidor.port}/api/casos"
    with urllib.request.urlopen(url, timeout=TIMEOUT_TELA_S) as resposta:  # noqa: S310 (só 127.0.0.1)
        return json.loads(resposta.read().decode("utf-8"))["casos"]


def _itens_do_sinal(guardiao, suspeitas: list, servidor) -> list[tuple[str, bool, str]]:
    canal = guardiao.canal
    estado = guardiao.estado()
    itens = [
        ("bot do Guardião", bool(estado["tem_bot"]), "falta o Secret TELEGRAM_BOT_TOKEN (seção 3)"),
        ("detecção pelo Gemini", guardiao.analisador is not None, "falta o Secret GEMINI_API_KEY (seção 3)"),
        (
            "responsável cadastrada",
            bool(estado["responsavel_cadastrada"]),
            "ninguém tocou Iniciar pelo link ou QR da tela (seções 6 e 7)",
        ),
    ]

    remetente = obter_cenario(CENARIO_GOLPE).remetente_id
    caso = guardiao.casos.caso_de(remetente)
    esperado = numero_esperado_pedro(canal)
    numero = numero_no_alerta(suspeitas, remetente) if caso is not None else None
    if caso is None:
        detalhe = "o golpe clássico não gerou alerta (seção 9)"
    else:
        detalhe = f"o alerta saiu com {numero or 'nenhum número'}; o esperado era {esperado}"
    itens.append((f"alerta do golpe clássico com o número do Pedro ({esperado})", caso is not None and numero == esperado, detalhe))

    estado_caso = caso.estado if caso is not None else None
    itens.append(
        (
            'caso do Pedro como "golpe"',
            estado_caso == "golpe",
            f"o caso está {ESTADOS_CASO[estado_caso]}" if caso is not None else "não há caso do Pedro",
        )
    )

    avisos = [linha for linha in canal.celular() if linha.tipo == "aviso"]
    avisado = caso is not None and caso.avisado_em is not None and any(caso.quem in a.texto for a in avisos)
    itens.append(("aviso no celular simulado da Dona Maria", avisado, "o aviso não apareceu no celular simulado"))

    if servidor is None:
        na_tela, detalhe = False, "a tela não está no ar (seção 6)"
    else:
        try:
            casos_tela = _casos_da_tela(servidor)
        except Exception as erro:
            na_tela, detalhe = False, f"não consegui ler api/casos ({type(erro).__name__})"
        else:
            quem = caso.quem if caso is not None else None
            na_tela = any(c.get("quem") == quem and c.get("estado") == "golpe" for c in casos_tela)
            detalhe = "a tela não mostra o caso do Pedro como golpe"
    itens.append(('tela (api/casos) com o Pedro como "golpe"', na_tela, detalhe))

    # Carlos e o grupo, já injetados na Filtra. A Júlia fica no teste 2, fora deste sinal.
    for cenario_id in ("contato_antigo_pede_dinheiro", "mensagem_em_grupo"):
        cenario = obter_cenario(cenario_id)
        chegou = any(m.tipo == "recebida" and m.conversa_id == cenario.conversa_id for m in canal.celular())
        sem_caso = guardiao.casos.caso_de(cenario.remetente_id) is None
        if not chegou:
            detalhe = "o cenário não foi injetado (seção 8)"
        else:
            detalhe = "gerou alerta, e não devia"
        itens.append((ROTULOS_SEM_ALERTA[cenario_id], chegou and sem_caso, detalhe))
    return itens


def conferir_sinal(guardiao, suspeitas: list, servidor, modo: str) -> bool:
    """Confere o sinal de sucesso do SPEC e mostra cada item; devolve se tudo passou.

    Lê o caso do Pedro, o número que foi no alerta (comparado com o contato salvo do Pedro),
    o celular simulado, `api/casos` pelo HTTP local da tela e os descartes da Filtra
    (Carlos e o grupo). A Júlia não entra aqui: ela fica no teste 2.
    """
    if modo != "demonstracao":
        print("aviso: a conferência do sinal de sucesso é do modo demonstração; pulando")
        return False
    if guardiao is None:
        print("aviso: o Guardião não está conectado; rode a célula da seção 5")
        print("sinal de sucesso: FALHOU (sem Guardião)")
        return False
    itens = _itens_do_sinal(guardiao, suspeitas, servidor)
    falhas = []
    for rotulo, ok, detalhe in itens:
        print(f"[{'ok' if ok else 'FALHOU'}] {rotulo}")
        if not ok:
            print(f"         {detalhe}")
            falhas.append(rotulo)
    print()
    if falhas:
        print(f"sinal de sucesso: FALHOU em {len(falhas)} de {len(itens)} itens: {'; '.join(falhas)}")
        return False
    print(f"sinal de sucesso: OK ({len(itens)} de {len(itens)} itens)")
    return True


# --------------------------------------------------------------------------- encerrar


def apagar_sessao(canal=None, pasta: Path | str | None = None) -> str:
    """Apaga a sessão da conta da pessoa idosa (`<pasta>/guardiao.session*`), mesmo sem Guardião conectado.

    Com um canal real (`TelegramCanal` com a conta), chama `sair()` antes (log_out no Telegram e
    apaga); os arquivos que sobrarem são apagados pelo glob. Devolve uma chave de `SESSAO`.
    """
    from guardiao.canal.telegram import NOME_SESSAO  # só aqui: o resto do roteiro não carrega a camada do Telegram

    pasta = Path(pasta) if pasta is not None else config.LOCAL_DIR
    situacao = "sem_sessao"
    sair = getattr(canal, "sair", None)
    if callable(sair) and getattr(canal, "usar_conta", False):
        try:
            situacao = sair()
        except Exception as erro:
            _avisar(f"log_out falhou: {type(erro).__name__}")
            situacao = "logout_falhou_apagada"
        try:
            canal.fechar()  # o sair() pode ter aberto outro loop da conta
        except Exception as erro:
            _avisar(f"fechar o canal falhou: {type(erro).__name__}")
    sobras = sorted(pasta.glob(f"{NOME_SESSAO}.session*")) if pasta.is_dir() else []
    for arquivo in sobras:
        arquivo.unlink(missing_ok=True)
    if sobras and situacao == "sem_sessao":
        situacao = "apagada_sem_login"
    return situacao
