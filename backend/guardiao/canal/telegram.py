"""Canal Telegram.

- Leitura: Telethon logado por QR na conta de teste da pessoa idosa. Roda numa thread
  com loop asyncio próprio; o resto do código chama métodos síncronos.
- Saída: Bot API do Telegram por HTTP (`requests`), com `getUpdates` em long polling
  numa thread (sem webhook).

A sessão do Telethon é credencial: fica em `backend/.local/` (modo 600) e é encerrada
com `log_out()` e apagada por `sair()`. O token do bot nunca aparece em mensagens de erro.
"""

import asyncio
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests
from telethon import TelegramClient, events, functions
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from guardiao.canal.base import (
    Alerta,
    Contato,
    Handler,
    InicioBot,
    MensagemRecebida,
    RespostaAlerta,
    ROTULOS_BOTOES,
    texto_alerta,
)
from guardiao.config import LOCAL_DIR, carregar_env, exigir, garantir_dir_privado

BOT_API_URL = "https://api.telegram.org"
NOME_SESSAO = "guardiao"
TENTATIVAS_SENHA = 3

# resposta -> código no callback_data ("<código>:<caso_id>", até 64 bytes)
CODIGOS_BOTAO = {"golpe": "golpe", "era_ele_mesmo": "ele_mesmo"}
_RESPOSTA_POR_CODIGO = {codigo: resposta for resposta, codigo in CODIGOS_BOTAO.items()}


class SemSessao(RuntimeError):
    """Não há sessão do Telethon salva; rode `login`."""


class SessaoNaoAutorizada(RuntimeError):
    """O arquivo de sessão existe, mas a conta não está logada; rode `login`."""


class ErroBotAPI(RuntimeError):
    """Falha numa chamada da Bot API (sem URL nem token na mensagem)."""


# --------------------------------------------------------------------------- Bot API


def dados_botao(resposta: str, caso_id: str) -> str:
    dados = f"{CODIGOS_BOTAO[resposta]}:{caso_id}"
    if len(dados.encode("utf-8")) > 64:
        raise ValueError("caso_id longo demais para callback_data")
    return dados


def teclado_alerta(caso_id: str) -> dict:
    """`reply_markup` com [É golpe] [Era ele mesmo] numa linha."""
    return {
        "inline_keyboard": [
            [
                {"text": ROTULOS_BOTOES[resposta], "callback_data": dados_botao(resposta, caso_id)}
                for resposta in ("golpe", "era_ele_mesmo")
            ]
        ]
    }


@dataclass(frozen=True)
class ToqueBot:
    """`callback_query` recebido; `resposta` é `None` se o botão não for de um alerta."""

    callback_id: str
    resposta: RespostaAlerta | None


def _data_unix(valor) -> datetime:
    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor, tz=timezone.utc)
    return datetime.now(timezone.utc)


def interpretar_update(update: dict) -> InicioBot | ToqueBot | None:
    """Traduz um update do `getUpdates`: `/start` em chat privado ou toque num botão."""
    toque = update.get("callback_query")
    if toque:
        codigo, _, caso_id = str(toque.get("data") or "").partition(":")
        resposta = None
        if codigo in _RESPOSTA_POR_CODIGO and caso_id:
            mensagem = toque.get("message") or {}
            resposta = RespostaAlerta(
                alerta_id=str(mensagem.get("message_id", "")),
                caso_id=caso_id,
                resposta=_RESPOSTA_POR_CODIGO[codigo],
                respondente_id=(toque.get("from") or {}).get("id"),
            )
        return ToqueBot(callback_id=str(toque.get("id", "")), resposta=resposta)

    mensagem = update.get("message")
    if mensagem:
        texto = mensagem.get("text") or ""
        comando = texto.split(maxsplit=1)[0] if texto.strip() else ""
        chat = mensagem.get("chat") or {}
        remetente = mensagem.get("from") or {}
        if (comando == "/start" or comando.startswith("/start@")) and chat.get("type") == "private":
            return InicioBot(
                usuario_id=remetente.get("id"),
                destinatario=chat.get("id"),
                recebido_em=_data_unix(mensagem.get("date")),
            )
    return None


class BotAPI:
    """Cliente HTTP mínimo da Bot API."""

    def __init__(self, token: str, sessao_http: requests.Session | None = None):
        self._token = token
        self._http = sessao_http or requests.Session()

    def __repr__(self) -> str:  # nunca mostrar o token
        return "BotAPI(<token>)"

    def chamar(self, metodo: str, timeout_http: float = 15, **params):
        url = f"{BOT_API_URL}/bot{self._token}/{metodo}"
        try:
            resposta = self._http.post(url, json=params, timeout=timeout_http)
        except requests.RequestException as erro:
            raise ErroBotAPI(f"{metodo}: falha de rede ({type(erro).__name__})") from None
        try:
            corpo = resposta.json()
        except ValueError:
            raise ErroBotAPI(f"{metodo}: HTTP {resposta.status_code}") from None
        if not corpo.get("ok"):
            raise ErroBotAPI(f"{metodo}: {corpo.get('error_code')} {corpo.get('description', '')}".strip())
        return corpo.get("result")

    def get_me(self) -> dict:
        return self.chamar("getMe")

    def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self.chamar("getUpdates", timeout_http=timeout + 10, **params)

    def send_message(self, chat_id, texto: str, reply_markup: dict | None = None) -> dict:
        params = {"chat_id": chat_id, "text": texto}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self.chamar("sendMessage", **params)

    def answer_callback_query(self, callback_id: str, texto: str | None = None) -> None:
        params = {"callback_query_id": callback_id}
        if texto:
            params["text"] = texto
        self.chamar("answerCallbackQuery", **params)


# --------------------------------------------------------------------------- Telethon


def mensagem_de_evento(event) -> MensagemRecebida:
    """Converte um `events.NewMessage`. Grupos e canais saem só com o tipo, sem ler o texto."""
    if not event.is_private:
        return MensagemRecebida(tipo="grupo")
    return MensagemRecebida(
        tipo="privada",
        remetente_id=event.sender_id,
        conversa_id=event.chat_id,
        texto=event.raw_text or None,
        recebida_em=getattr(event, "date", None) or datetime.now(timezone.utc),
    )


class _LoopThread:
    """Loop asyncio numa thread própria, para o Telethon."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._rodar, name="guardiao-telethon", daemon=True)
        self._thread.start()

    def _rodar(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def executar(self, coro, timeout: float | None = None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def parar(self):
        if self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self.loop.close()


def _avisar(texto: str) -> None:
    print(f"[canal] {texto}", file=sys.stderr)


def _entregar(handler: Handler, evento) -> None:
    try:
        handler(evento)
    except Exception as erro:  # o tipo basta; a mensagem pode carregar conteúdo
        _avisar(f"handler falhou: {type(erro).__name__}")


# --------------------------------------------------------------------------- canal


class TelegramCanal:
    """Implementação Telegram do contrato `Canal`, com operações extras de verificação."""

    def __init__(
        self,
        api_id: int | None,
        api_hash: str | None,
        bot_token: str | None,
        dir_sessao: Path = LOCAL_DIR,
        usar_conta: bool = True,
        usar_bot: bool = True,
        espera_polling: int = 20,
    ):
        if usar_conta and not (api_id and api_hash):
            raise ValueError("api_id e api_hash são obrigatórios para a conta")
        if usar_bot and not bot_token:
            raise ValueError("token do bot é obrigatório para o bot")
        self._api_id = api_id
        self._api_hash = api_hash
        self._bot = BotAPI(bot_token) if usar_bot else None
        self._dir = Path(dir_sessao)
        self.usar_conta = usar_conta
        self.usar_bot = usar_bot
        self._espera_polling = espera_polling
        self._loop: _LoopThread | None = None
        self._cliente: TelegramClient | None = None
        self._conta_id: int | None = None
        self._info_bot: dict | None = None
        self._parar = threading.Event()
        self._thread_bot: threading.Thread | None = None
        self._offset: int | None = None
        self._pausa_erro = 3  # segundos de espera após falha no getUpdates

    def __repr__(self) -> str:
        return f"TelegramCanal(conta={self.usar_conta}, bot={self.usar_bot})"

    @classmethod
    def do_ambiente(cls, usar_conta: bool = True, usar_bot: bool = True, **kwargs) -> "TelegramCanal":
        """Lê as credenciais de `backend/.env` / variáveis de ambiente."""
        carregar_env()
        api_id = None
        if usar_conta:
            try:
                api_id = int(exigir("TELEGRAM_API_ID"))
            except ValueError:
                raise RuntimeError("TELEGRAM_API_ID não é numérico") from None
        api_hash = exigir("TELEGRAM_API_HASH") if usar_conta else None
        token = exigir("TELEGRAM_BOT_TOKEN") if usar_bot else None
        return cls(api_id, api_hash, token, usar_conta=usar_conta, usar_bot=usar_bot, **kwargs)

    # ------------------------------------------------------------- sessão

    @property
    def caminho_sessao(self) -> Path:
        return self._dir / f"{NOME_SESSAO}.session"

    def _arquivos_sessao(self) -> list[Path]:
        if not self._dir.exists():
            return []
        return sorted(self._dir.glob(f"{NOME_SESSAO}.session*"))

    def tem_sessao(self) -> bool:
        return self.caminho_sessao.exists()

    def _proteger_sessao(self) -> None:
        for arquivo in self._arquivos_sessao():
            try:
                os.chmod(arquivo, 0o600)
            except FileNotFoundError:  # o journal do SQLite pode sumir no meio
                pass

    def _executar(self, coro, timeout: float | None = None):
        if self._loop is None:
            self._loop = _LoopThread()
        return self._loop.executar(coro, timeout)

    def _obter_cliente(self, criar_sessao: bool) -> TelegramClient:
        if not self.usar_conta:
            raise RuntimeError("canal criado sem a conta (usar_conta=False)")
        if self._cliente is not None:
            return self._cliente
        if not self.tem_sessao():
            if not criar_sessao:
                raise SemSessao("sem sessão salva; rode `login`")
            garantir_dir_privado(self._dir)
            # cria o arquivo vazio já com modo 600; o SQLite o aproveita
            os.close(os.open(self.caminho_sessao, os.O_WRONLY | os.O_CREAT, 0o600))

        async def criar():
            return TelegramClient(
                str(self._dir / NOME_SESSAO),
                self._api_id,
                self._api_hash,
                device_model="Guardiao da Familia (teste)",
                system_version="backend",
                app_version="0.2",
            )

        self._cliente = self._executar(criar())
        self._proteger_sessao()
        return self._cliente

    # ------------------------------------------------------------- conta (Telethon)

    def login_qr(
        self,
        mostrar_qr: Callable[[str, int], None],
        pedir_senha: Callable[[int], str],
        max_qr: int = 6,
    ) -> int:
        """Login por QR. `mostrar_qr(url, n)` exibe cada QR; `pedir_senha(tentativa)` pede a 2FA.

        Devolve o id da conta. Se a sessão já estiver logada, não mostra QR.
        """
        cliente = self._obter_cliente(criar_sessao=True)

        async def senha_2fa():
            loop = asyncio.get_running_loop()
            for tentativa in range(1, TENTATIVAS_SENHA + 1):
                senha = await loop.run_in_executor(None, pedir_senha, tentativa)
                try:
                    await cliente.sign_in(password=senha)
                    return
                except PasswordHashInvalidError:
                    continue
                finally:
                    senha = None
            raise PermissionError("senha de 2FA incorreta")

        async def login():
            await cliente.connect()
            if not await cliente.is_user_authorized():
                qr = await cliente.qr_login()
                for n in range(1, max_qr + 1):
                    mostrar_qr(qr.url, n)
                    try:
                        await qr.wait()
                        break
                    except asyncio.TimeoutError:
                        if n == max_qr:
                            raise TimeoutError("QR não foi lido") from None
                        await qr.recreate()
                    except SessionPasswordNeededError:
                        await senha_2fa()
                        break
            eu = await cliente.get_me()
            if eu is None:
                raise SessaoNaoAutorizada("login não concluído")
            if eu.bot:
                raise RuntimeError("a sessão é de um bot, não de uma conta")
            return eu.id

        try:
            self._conta_id = self._executar(login())
        finally:
            self._proteger_sessao()
        return self._conta_id

    def conectar(self) -> int:
        """Conecta com a sessão salva e devolve o id da conta."""
        if self._conta_id is not None:
            return self._conta_id
        cliente = self._obter_cliente(criar_sessao=False)

        async def conectar():
            await cliente.connect()
            if not await cliente.is_user_authorized():
                raise SessaoNaoAutorizada("a sessão não está logada; rode `login`")
            eu = await cliente.get_me()
            return eu.id

        self._conta_id = self._executar(conectar())
        return self._conta_id

    def listar_contatos(self) -> list[Contato]:
        """Contatos salvos na conta; `telefone` vem `None` quando o Telegram não o expõe."""
        self.conectar()
        cliente = self._cliente

        async def listar():
            resultado = await cliente(functions.contacts.GetContactsRequest(hash=0))
            contatos = []
            for usuario in getattr(resultado, "users", []) or []:
                nome = " ".join(p for p in (usuario.first_name, usuario.last_name) if p)
                contatos.append(Contato(id=usuario.id, nome=nome, telefone=usuario.phone or None))
            return contatos

        return self._executar(listar())

    def enviar_start_ao_bot(self) -> None:
        """A conta da pessoa idosa manda `/start` ao bot do Guardião."""
        self.conectar()
        usuario = self.info_bot().get("username")
        if not usuario:
            raise RuntimeError("o bot não tem username")
        cliente = self._cliente

        async def enviar():
            await cliente.send_message(usuario, "/start")

        self._executar(enviar())

    def sair(self) -> str:
        """`log_out()` no servidor e apaga a sessão local.

        Devolve `sem_sessao`, `encerrada`, `apagada_sem_login` ou `logout_falhou_apagada`.
        """
        if not self._arquivos_sessao():
            return "sem_sessao"
        situacao = "apagada_sem_login"
        try:
            if self.tem_sessao():
                cliente = self._obter_cliente(criar_sessao=False)

                async def encerrar():
                    await cliente.connect()
                    if await cliente.is_user_authorized():
                        return "encerrada" if await cliente.log_out() else "logout_falhou_apagada"
                    await cliente.disconnect()
                    return "apagada_sem_login"

                async def desconectar():
                    if cliente.is_connected():
                        await cliente.disconnect()

                try:
                    situacao = self._executar(encerrar())
                except Exception as erro:  # a sessão é apagada mesmo assim
                    _avisar(f"log_out falhou: {type(erro).__name__}")
                    situacao = "logout_falhou_apagada"
                    try:
                        self._executar(desconectar(), timeout=10)
                    except Exception:
                        pass
                self._cliente = None
                self._conta_id = None
        finally:
            for arquivo in self._arquivos_sessao():
                arquivo.unlink(missing_ok=True)
        return situacao

    # ------------------------------------------------------------- bot (Bot API)

    def _exigir_bot(self) -> BotAPI:
        if self._bot is None:
            raise RuntimeError("canal criado sem o bot (usar_bot=False)")
        return self._bot

    def info_bot(self) -> dict:
        """`getMe` do bot: `id` e `username`."""
        if self._info_bot is None:
            dados = self._exigir_bot().get_me()
            self._info_bot = {"id": dados.get("id"), "username": dados.get("username")}
        return self._info_bot

    def enviar_aviso(self, destinatario, texto: str) -> str:
        """Mensagem simples do bot (sem botões) a quem já tocou Iniciar."""
        mensagem = self._exigir_bot().send_message(destinatario, texto)
        return str(mensagem["message_id"])

    def _laco_bot(self, handler: Handler) -> None:
        bot = self._exigir_bot()
        while not self._parar.is_set():
            try:
                updates = bot.get_updates(self._offset, self._espera_polling)
            except ErroBotAPI as erro:
                _avisar(f"aviso: {erro}")
                self._parar.wait(self._pausa_erro)
                continue
            for update in updates or []:
                self._offset = update["update_id"] + 1
                evento = interpretar_update(update)
                if isinstance(evento, ToqueBot):
                    try:
                        bot.answer_callback_query(
                            evento.callback_id, "Resposta registrada." if evento.resposta else None
                        )
                    except ErroBotAPI as erro:
                        _avisar(f"aviso: {erro}")
                    if evento.resposta is not None:
                        _entregar(handler, evento.resposta)
                elif evento is not None:
                    _entregar(handler, evento)
        if self._offset is not None:  # confirma ao Telegram os updates já tratados
            try:
                bot.get_updates(self._offset, 0)
            except ErroBotAPI:
                pass

    # ------------------------------------------------------------- contrato Canal

    def receber_mensagens(self, handler: Handler) -> None:
        if self.usar_conta:
            self.conectar()
            cliente = self._cliente

            async def ao_receber(event):
                try:
                    mensagem = mensagem_de_evento(event)
                except Exception as erro:
                    _avisar(f"mensagem ignorada: {type(erro).__name__}")
                    return
                _entregar(handler, mensagem)

            async def registrar():
                cliente.add_event_handler(ao_receber, events.NewMessage(incoming=True))

            self._executar(registrar())
        if self.usar_bot and self._thread_bot is None:
            self._parar.clear()
            self._thread_bot = threading.Thread(
                target=self._laco_bot, args=(handler,), name="guardiao-bot", daemon=True
            )
            self._thread_bot.start()

    def enviar_alerta(self, alerta: Alerta) -> str:
        mensagem = self._exigir_bot().send_message(
            alerta.destinatario, texto_alerta(alerta), reply_markup=teclado_alerta(alerta.caso_id)
        )
        return str(mensagem["message_id"])

    def fechar(self) -> None:
        """Para o polling e desconecta o Telethon (a sessão continua salva)."""
        self._parar.set()
        if self._thread_bot is not None:
            self._thread_bot.join(self._espera_polling + 15)
            self._thread_bot = None
        if self._cliente is not None and self._loop is not None:
            cliente = self._cliente

            async def desconectar():  # disconnect() precisa rodar dentro do loop do cliente
                if cliente.is_connected():
                    await cliente.disconnect()

            try:
                self._executar(desconectar(), timeout=10)
            except Exception as erro:
                _avisar(f"desconexão: {type(erro).__name__}")
            self._cliente = None
        self._conta_id = None
        if self._loop is not None:
            self._loop.parar()
            self._loop = None
        self._proteger_sessao()
