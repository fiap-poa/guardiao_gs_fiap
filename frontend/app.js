// Lê api/estado e mostra o estado da conexão e do cadastro da responsável.
// O caminho é relativo para funcionar também no iframe do Colab (serve_kernel_port_as_iframe).
(function () {
  const campos = {
    conectado: { el: document.getElementById("conectado"), sim: "conectada", nao: "não conectada" },
    responsavel_cadastrada: {
      el: document.getElementById("responsavel"), sim: "cadastrada", nao: "ainda não",
    },
  };
  const erro = document.getElementById("erro");

  function mostrar(estado) {
    for (const [chave, campo] of Object.entries(campos)) {
      const valor = Boolean(estado[chave]);
      campo.el.textContent = valor ? campo.sim : campo.nao;
      campo.el.className = valor ? "sim" : "nao";
    }
    erro.hidden = true;
  }

  async function atualizar() {
    try {
      const resposta = await fetch("api/estado", { cache: "no-store" });
      if (!resposta.ok) throw new Error("HTTP " + resposta.status);
      mostrar(await resposta.json());
    } catch (_) {
      erro.hidden = false;
    }
  }

  atualizar();
  setInterval(atualizar, 5000);
})();
