"""Conexão da conta da pessoa idosa pela tela (CAP-7) e QR em SVG.

`LoginConta(guardiao).estado()` é o que `api/conexao` devolve:

- `simulada`: modo demonstração com o Guardião conectado (não há QR); desconectado, é
  `desconectada`;
- `conectada`: o Guardião está conectado;
- `aguardando_leitura` (com `qr_svg`): modo real sem sessão. O primeiro pedido começa o login
  por QR do canal (`canal.login_qr`) numa thread; cada QR novo (vence em cerca de 30 s)
  substitui o anterior. Lido o QR, a thread conecta o Guardião (`guardiao.conectar()`);
- `iniciando`: o login começou, mas o primeiro QR ainda não chegou;
- `erro` (com `motivo`): `qr_vencido` (ninguém leu os QR), `senha_2fa` (a conta tem
  verificação em duas etapas: o login é pelo terminal, `python -m guardiao.verificar login`)
  ou `falha`. O `qr_vencido` aparece num pedido e o seguinte tenta de novo; a `falha` (API_ID
  errado, rede fora) continua como erro e só tenta de novo 30 s depois; o `senha_2fa` não
  repete sozinho (a tela nunca pede a senha);
- `desconectada`: modo real com um canal que não faz login por QR.

Só uma thread de login por vez. Nada de QR, link ou token em log: só o tipo do erro.
"""

import sys
import threading
import time
from typing import Callable, Literal

import qrcode
from qrcode.image.svg import SvgPathImage

EstadoConexao = Literal["simulada", "conectada", "aguardando_leitura", "iniciando", "erro", "desconectada"]
MotivoErro = Literal["qr_vencido", "senha_2fa", "falha"]

COMANDO_LOGIN = "python -m guardiao.verificar login"
ESPERA_PRIMEIRO_QR_S = 10  # quanto o pedido que começa o login espera o primeiro QR
ESPERA_APOS_FALHA_S = 30  # depois de uma `falha`, quanto esperar antes de tentar o login de novo


class PrecisaSenha(RuntimeError):
    """A conta tem verificação em duas etapas: a tela não pede a senha."""


def _avisar(texto: str) -> None:
    print(f"[conexão] {texto}", file=sys.stderr)


def qr_svg(texto: str) -> str:
    """O QR de `texto` como SVG (só caminhos, sem PIL e sem recurso externo)."""
    imagem = qrcode.make(texto, image_factory=SvgPathImage, border=4)
    return imagem.to_string(encoding="unicode")


class LoginConta:
    """Estado da conexão da conta e login por QR em segundo plano."""

    def __init__(
        self,
        guardiao,
        espera_primeiro_qr_s: float = ESPERA_PRIMEIRO_QR_S,
        espera_apos_falha_s: float = ESPERA_APOS_FALHA_S,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.guardiao = guardiao
        self._espera = espera_primeiro_qr_s
        self._espera_falha = espera_apos_falha_s
        self._relogio = relogio
        self._falhou_em: float | None = None
        self._mudou = threading.Condition()
        self._thread: threading.Thread | None = None
        self._qr: str | None = None  # SVG do QR atual (nunca a URL)
        self._erro: MotivoErro | None = None
        self._erro_mostrado = False

    def __repr__(self) -> str:
        return f"LoginConta(rodando={'sim' if self.rodando else 'não'}, erro={self._erro})"

    @property
    def rodando(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # ------------------------------------------------------------- estado

    def estado(self) -> dict:
        """O estado da conexão; no modo real sem conexão, começa (ou retoma) o login."""
        guardiao = self.guardiao
        if guardiao.modo == "demonstracao":
            return self._resposta("simulada" if guardiao.conectado else "desconectada")
        if guardiao.conectado:
            return self._resposta("conectada")
        login_qr = getattr(guardiao.canal, "login_qr", None)
        if not callable(login_qr):
            return self._resposta("desconectada")
        with self._mudou:
            if self._thread is not None and self._thread.is_alive():
                return self._atual()
            if self._erro is not None:
                if self._erro == "falha" and self._relogio() - self._falhou_em < self._espera_falha:
                    self._erro_mostrado = True
                    return self._resposta("erro", motivo=self._erro)
                if self._erro == "senha_2fa" or not self._erro_mostrado:
                    self._erro_mostrado = True
                    return self._resposta("erro", motivo=self._erro)
            # sem login em andamento: começa um (o primeiro pedido, ou depois de um QR vencido)
            self._qr, self._erro, self._erro_mostrado = None, None, False
            self._thread = threading.Thread(target=self._login, args=(login_qr,), name="guardiao-login", daemon=True)
            self._thread.start()
            self._mudou.wait_for(lambda: self._qr is not None or not self._thread.is_alive(), timeout=self._espera)
            if not self._thread.is_alive() and self._erro is not None:
                self._erro_mostrado = True
            return self._atual()

    def _atual(self) -> dict:
        """Chamado sob a trava, com o login rodando ou recém-terminado."""
        if self.guardiao.conectado:
            return self._resposta("conectada")
        if self._erro is not None:
            return self._resposta("erro", motivo=self._erro)
        if self._qr is not None:
            return self._resposta("aguardando_leitura", qr_svg=self._qr)
        return self._resposta("iniciando")

    @staticmethod
    def _resposta(estado: EstadoConexao, qr_svg: str | None = None, motivo: MotivoErro | None = None) -> dict:
        resposta = {"estado": estado, "qr_svg": qr_svg, "motivo": motivo}
        if motivo == "senha_2fa":
            resposta["comando"] = COMANDO_LOGIN
        return resposta

    def aguardar(self, timeout: float | None = None) -> bool:
        """Espera a thread de login terminar (testes e notebook). `True` se terminou."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ------------------------------------------------------------- thread de login

    def _mostrar_qr(self, url: str, _n: int) -> None:
        svg = qr_svg(url)
        with self._mudou:
            self._qr = svg
            self._mudou.notify_all()

    def _pedir_senha(self, _tentativa: int) -> str:
        with self._mudou:
            self._erro = "senha_2fa"
        raise PrecisaSenha("a conta tem verificação em duas etapas: faça o login pelo terminal")

    def _login(self, login_qr) -> None:
        motivo: MotivoErro | None = None
        try:
            login_qr(self._mostrar_qr, self._pedir_senha)
            with self._mudou:  # o QR já foi usado: durante o pareamento a tela mostra "iniciando"
                self._qr = None
            self.guardiao.conectar()
        except PrecisaSenha:
            motivo = "senha_2fa"
        except TimeoutError:
            motivo = "qr_vencido"
        except Exception as erro:
            motivo = "falha"
            _avisar(f"login falhou: {type(erro).__name__}")
        with self._mudou:
            if motivo is not None:
                # a senha foi pedida: vale o motivo da 2FA, qualquer que seja a exceção que subiu
                self._erro = "senha_2fa" if self._erro == "senha_2fa" else motivo
                self._falhou_em = self._relogio()
            self._qr = None
            self._mudou.notify_all()
        if self._erro == "senha_2fa":
            self._liberar_sessao()

    def _liberar_sessao(self) -> None:
        """Fecha o canal (desconecta a conta), para o login pelo terminal usar a mesma sessão."""
        fechar = getattr(self.guardiao.canal, "fechar", None)
        if callable(fechar) and not self.guardiao.conectado:
            try:
                fechar()
            except Exception as erro:
                _avisar(f"desconexão falhou: {type(erro).__name__}")
