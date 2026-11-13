"""CLI das verificações ao vivo da história 2 (usa só a camada de canal).

Ordem: login → escutar → contatos → bot-alerta → bot-start-idosa → sair.

    .venv/bin/python -m guardiao.verificar login

Tudo o que é gravado em `evidencias/` e impresso aqui é metadado: contagens, tipo de
conversa, ids em hash e telefones mascarados. Nunca o texto das mensagens.
"""

import argparse
import getpass
import os
import queue
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Callable

import qrcode

from guardiao.canal.base import (
    Alerta,
    Contato,
    InicioBot,
    MensagemRecebida,
    RespostaAlerta,
    procurar_contatos,
)
from guardiao.canal.telegram import (
    ErroBotAPI,
    NOME_SESSAO,
    SemSessao,
    SessaoNaoAutorizada,
    TelegramCanal,
)
from guardiao.config import LOCAL_DIR, garantir_dir_privado
from guardiao.mascara import gravar_evidencia, hash_id, mascarar_telefone

QR_PNG = LOCAL_DIR / "qr.png"
ESPERA_START = 300
ESPERA_AVISO = 30
TRECHO_TESTE = "oi vó, é o Pedro, troquei de número. Preciso de um Pix urgente"
TEXTO_TESTE_IDOSA = "Teste do Guardião da Família: esta conversa com o bot está funcionando."


# --------------------------------------------------------------------------- evidências


def evidencia_mensagem(mensagem: MensagemRecebida) -> dict:
    """Metadados de uma mensagem recebida. Grupos: só o tipo."""
    if mensagem.tipo != "privada":
        return {"tipo": "grupo"}
    return {
        "tipo": "privada",
        "remetente": hash_id(mensagem.remetente_id),
        "conversa": hash_id(mensagem.conversa_id),
        "tem_texto": mensagem.tem_texto,
    }


def evidencia_contatos(contatos: list[Contato], procurar: str | None = None) -> dict:
    """Contagens dos contatos e, se houver busca, o achado com telefone mascarado."""
    com_telefone = sum(1 for c in contatos if c.telefone)
    dados = {
        "total": len(contatos),
        "com_telefone": com_telefone,
        "sem_telefone": len(contatos) - com_telefone,
        "resultado": "ok" if contatos else "falhou",
    }
    if procurar:
        achados = procurar_contatos(contatos, procurar)
        com_numero = [c for c in achados if c.telefone]
        if com_numero:
            dados["busca"] = "encontrado_com_telefone"
            dados["telefone"] = mascarar_telefone(com_numero[0].telefone)
        elif achados:
            dados["busca"] = "encontrado_sem_telefone"
        else:
            dados["busca"] = "nao_encontrado"
        dados["encontrados"] = len(achados)
    return dados


def _registrar(verificacao: str, **campos) -> dict:
    registro = gravar_evidencia(verificacao, **campos)
    resumo = " ".join(f"{k}={v}" for k, v in registro.items() if k not in ("em", "verificacao"))
    print(f"[{verificacao}] {resumo}")
    return registro


def _instante() -> datetime:
    """Agora em UTC, truncado ao segundo (a data dos updates do Telegram é inteira)."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def _esperar(fila: queue.Queue, aceitar: Callable[[object], bool], segundos: float):
    """Primeiro evento da fila que `aceitar` aprova, ou `None` no fim do prazo."""
    limite = time.monotonic() + segundos
    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            return None
        try:
            evento = fila.get(timeout=min(restante, 1.0))
        except queue.Empty:
            continue
        if aceitar(evento):
            return evento


# --------------------------------------------------------------------------- QR


def _salvar_qr_png(url: str) -> None:
    garantir_dir_privado(LOCAL_DIR)
    imagem = qrcode.make(url)
    fd = os.open(QR_PNG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as arquivo:
        imagem.save(arquivo, format="PNG")


def _mostrar_qr(inverter: bool) -> Callable[[str, int], None]:
    def mostrar(url: str, n: int) -> None:
        _salvar_qr_png(url)
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        print(f"\nQR {n} (vale cerca de 30 s; outro aparece sozinho quando vencer).")
        print(f"Também salvo em {QR_PNG}")
        print("No celular da conta A: Configurações → Dispositivos → Conectar dispositivo.\n")
        qr.print_ascii(invert=inverter)
        sys.stdout.flush()

    return mostrar


def _pedir_senha(tentativa: int) -> str:
    print("\nA conta tem verificação em duas etapas.")
    return getpass.getpass(f"Senha da conta A (tentativa {tentativa}/3, não aparece na tela): ")


# --------------------------------------------------------------------------- comandos


def cmd_login(args) -> int:
    resposta = input("A conta que vai ler o QR é uma conta de TESTE da equipe? Digite 'sim': ")
    if resposta.strip().lower() != "sim":
        print("Login cancelado: só contas de teste.")
        return 1
    canal = TelegramCanal.do_ambiente(usar_bot=False)
    gerados = []

    def mostrar(url: str, n: int) -> None:
        gerados.append(n)
        _mostrar_qr(args.inverter)(url, n)

    try:
        conta = canal.login_qr(mostrar, _pedir_senha)
    except (TimeoutError, PermissionError) as erro:
        motivo = "qr_vencido" if isinstance(erro, TimeoutError) else "senha_2fa_incorreta"
        _registrar("login", resultado="falhou", motivo=motivo, qr_gerados=len(gerados))
        return 1
    finally:
        QR_PNG.unlink(missing_ok=True)
        canal.fechar()
    _registrar("login", resultado="conectado", conta=hash_id(conta), qr_gerados=len(gerados))
    return 0


def cmd_escutar(args) -> int:
    canal = TelegramCanal.do_ambiente(usar_bot=False)
    fila: queue.Queue = queue.Queue()
    privadas = grupos = 0
    try:
        conta = canal.conectar()
        canal.receber_mensagens(fila.put)
        prazo = f"por {args.segundos} s" if args.segundos else "até Ctrl+C"
        print(f"Escutando a conta {hash_id(conta)} {prazo}. Mande uma mensagem da conta B para A.")
        limite = time.monotonic() + args.segundos if args.segundos else None
        try:
            while limite is None or time.monotonic() < limite:
                try:
                    evento = fila.get(timeout=1.0)
                except queue.Empty:
                    continue
                if not isinstance(evento, MensagemRecebida):
                    continue
                dados = evidencia_mensagem(evento)
                if dados["tipo"] == "privada":
                    privadas += 1
                else:
                    grupos += 1
                _registrar("escutar", evento="mensagem", **dados)
        except KeyboardInterrupt:
            print()
    finally:
        canal.fechar()
    _registrar(
        "escutar",
        evento="resumo",
        privadas=privadas,
        grupos=grupos,
        resultado="ok" if privadas else "falhou",
    )
    return 0 if privadas else 1


def cmd_contatos(args) -> int:
    canal = TelegramCanal.do_ambiente(usar_bot=False)
    try:
        contatos = canal.listar_contatos()
    finally:
        canal.fechar()
    dados = evidencia_contatos(contatos, args.procurar)
    _registrar("contatos", **dados)
    return 0 if dados["resultado"] == "ok" else 1


def cmd_bot_alerta(args) -> int:
    canal = TelegramCanal.do_ambiente(usar_conta=False, espera_polling=5)
    fila: queue.Queue = queue.Queue()
    try:
        bot = canal.info_bot()
        desde = _instante()  # um /start antigo pendente no getUpdates não vale
        canal.receber_mensagens(fila.put)
        print(f"Na conta C, abra https://t.me/{bot['username']} e toque em Iniciar "
              f"(ou mande /start de novo) agora (espero {args.espera} s).")
        inicio = _esperar(
            fila, lambda e: isinstance(e, InicioBot) and e.recebido_em >= desde, args.espera
        )
        if inicio is None:
            _registrar("bot-alerta", resultado="falhou", motivo="sem_start")
            print("sem /start")
            return 1
        _registrar("bot-alerta", evento="start", responsavel=hash_id(inicio.usuario_id))

        caso_id = f"teste-{secrets.token_hex(3)}"
        alerta = Alerta(
            destinatario=inicio.destinatario,
            caso_id=caso_id,
            nome_alegado=args.nome,
            como_chama_idosa=args.como_chama,
            trecho=args.trecho,
            numero_verdadeiro=args.numero,
        )
        alerta_id = canal.enviar_alerta(alerta)
        _registrar("bot-alerta", evento="alerta_enviado", alerta_id=alerta_id, caso=caso_id,
                   com_numero=bool(args.numero))
        print(f"Na conta C, toque em um dos botões do alerta (espero {args.espera} s).")

        toque = _esperar(
            fila,
            lambda e: isinstance(e, RespostaAlerta) and e.caso_id == caso_id,
            args.espera,
        )
        if toque is None:
            _registrar("bot-alerta", resultado="falhou", motivo="sem_toque", alerta_id=alerta_id)
            return 1
        mesmo_alerta = toque.alerta_id == alerta_id
        mesmo_respondente = toque.respondente_id == inicio.usuario_id
        ok = mesmo_alerta and mesmo_respondente
        _registrar(
            "bot-alerta",
            evento="toque",
            resposta=toque.resposta,
            alerta_id=toque.alerta_id,
            mesmo_alerta=mesmo_alerta,
            mesmo_respondente=mesmo_respondente,
            respondido=True,
            resultado="ok" if ok else "falhou",
        )
        return 0 if ok else 1
    finally:
        canal.fechar()


def cmd_bot_start_idosa(args) -> int:
    canal = TelegramCanal.do_ambiente(espera_polling=5)
    fila: queue.Queue = queue.Queue()
    try:
        conta = canal.conectar()
        bot = canal.info_bot()
        canal.receber_mensagens(fila.put)
        desde = _instante()  # só vale o /start enviado agora
        canal.enviar_start_ao_bot()
        _registrar("bot-start-idosa", evento="start_enviado", idosa=hash_id(conta),
                   bot=hash_id(bot["id"]))

        inicio = _esperar(
            fila,
            lambda e: isinstance(e, InicioBot) and e.usuario_id == conta and e.recebido_em >= desde,
            args.espera,
        )
        if inicio is None:
            _registrar("bot-start-idosa", resultado="falhou", motivo="bot_nao_recebeu_start")
            return 1
        _registrar("bot-start-idosa", evento="start_recebido_pelo_bot",
                   idosa=hash_id(inicio.usuario_id), mesmo_id=True)

        canal.enviar_aviso(inicio.destinatario, TEXTO_TESTE_IDOSA)
        recebida = _esperar(
            fila,
            lambda e: isinstance(e, MensagemRecebida)
            and e.tipo == "privada"
            and e.remetente_id == bot["id"],
            ESPERA_AVISO,
        )
        _registrar(
            "bot-start-idosa",
            evento="aviso",
            aviso_enviado=True,
            aviso_recebido_pela_conta=recebida is not None,
            resultado="ok" if recebida is not None else "falhou",
        )
        return 0 if recebida is not None else 1
    finally:
        canal.fechar()


def cmd_sair(args) -> int:
    QR_PNG.unlink(missing_ok=True)
    sessoes = list(LOCAL_DIR.glob(f"{NOME_SESSAO}.session*")) if LOCAL_DIR.exists() else []
    if not sessoes:
        _registrar("sair", resultado="sem_sessao")
        print("Sem sessão salva; nada a encerrar.")
        return 0
    canal = TelegramCanal.do_ambiente(usar_bot=False)
    try:
        situacao = canal.sair()
    finally:
        canal.fechar()
    restantes = list(LOCAL_DIR.glob(f"{NOME_SESSAO}.session*"))
    _registrar("sair", resultado=situacao, sessao_local_existe=bool(restantes))
    print("Confira na conta A: Configurações → Dispositivos não deve mais listar "
          "'Guardiao da Familia (teste)'.")
    return 0 if situacao == "encerrada" and not restantes else 1


# --------------------------------------------------------------------------- CLI


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m guardiao.verificar", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("login", help="login da conta A por QR")
    p.add_argument("--inverter", action="store_true", help="inverte o QR no terminal (fundo claro)")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("escutar", help="recebe mensagens novas na conta A")
    p.add_argument("--segundos", type=int, default=0, help="0 = até Ctrl+C")
    p.set_defaults(func=cmd_escutar)

    p = sub.add_parser("contatos", help="contagem dos contatos e busca por nome")
    p.add_argument("--procurar", metavar="NOME")
    p.set_defaults(func=cmd_contatos)

    p = sub.add_parser("bot-alerta", help="alerta com botões à conta C após o Iniciar")
    p.add_argument("--espera", type=int, default=ESPERA_START, help="segundos para Iniciar e para o toque")
    p.add_argument("--nome", default="Pedro", help="nome alegado")
    p.add_argument("--como-chama", default="sua mãe", help="como a responsável chama a pessoa idosa")
    p.add_argument("--trecho", default=TRECHO_TESTE, help="trecho de teste no alerta")
    p.add_argument("--numero", default=None, help="número verdadeiro (sem ele, usa a frase sem número)")
    p.set_defaults(func=cmd_bot_alerta)

    p = sub.add_parser("bot-start-idosa", help="a conta A manda /start ao bot e recebe um teste")
    p.add_argument("--espera", type=int, default=60)
    p.set_defaults(func=cmd_bot_start_idosa)

    p = sub.add_parser("sair", help="log_out() da conta A e apaga a sessão")
    p.set_defaults(func=cmd_sair)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SemSessao, SessaoNaoAutorizada, ErroBotAPI, RuntimeError, ValueError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    except OSError as erro:  # rede: só o tipo, sem detalhes
        print(f"erro de conexão: {type(erro).__name__}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130
    except Exception as erro:  # ex.: RPCError do canal; só o tipo, sem detalhes
        print(f"erro: {type(erro).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
