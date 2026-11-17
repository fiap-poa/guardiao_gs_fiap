// Tela da responsável: configuração (QR da conta e QR do bot) e depois a lista de casos.
// Todo caminho é relativo, para funcionar também no iframe do Colab (serve_kernel_port_as_iframe).
// Texto vindo da API entra só por textContent; o QR (SVG gerado no backend) entra como imagem.
(function () {
  "use strict";

  const API = {
    estado: "api/estado",
    conexao: "api/conexao",
    cadastro: "api/cadastro",
    casos: "api/casos",
    cenarios: "api/demo/cenarios",
    injetar: "api/demo/injetar",
  };
  const INTERVALO_MS = 3000;

  const ESTADOS_CASO = {
    aguardando: "Aguardando a responsável",
    golpe: "Golpe",
    era_ele_mesmo: "Era ele mesmo",
    sem_resposta: "Sem resposta",
  };

  const $ = (id) => document.getElementById(id);
  const el = {
    foraDoAr: $("fora-do-ar"),
    parado: $("parado"),
    resumo: $("resumo"),
    resumoModo: $("resumo-modo"),
    resumoConta: $("resumo-conta"),
    resumoResponsavel: $("resumo-responsavel"),
    configuracao: $("configuracao"),
    passoConta: $("passo-conta"),
    contaTexto: $("conta-texto"),
    contaQr: $("conta-qr"),
    contaQrImg: $("conta-qr-img"),
    contaDetalhe: $("conta-detalhe"),
    contaComando: $("conta-comando"),
    passoBot: $("passo-bot"),
    botTexto: $("bot-texto"),
    botQr: $("bot-qr"),
    botQrImg: $("bot-qr-img"),
    botAbrir: $("bot-abrir"),
    botDetalhe: $("bot-detalhe"),
    casos: $("casos"),
    casosVazio: $("casos-vazio"),
    casosLista: $("casos-lista"),
    golpista: $("golpista"),
    golpistaBotoes: $("golpista-botoes"),
    golpistaResultado: $("golpista-resultado"),
  };

  let cenariosCarregados = false;
  let casosMostrados = null; // JSON dos últimos casos desenhados: sem mudança, a lista não é refeita
  let injetando = false;
  let proximo = null;

  async function obter(caminho) {
    const resposta = await fetch(caminho, { cache: "no-store" });
    if (!resposta.ok) throw new Error("HTTP " + resposta.status);
    return resposta.json();
  }

  function texto(elemento, valor) {
    elemento.textContent = valor == null ? "" : String(valor);
  }

  function detalhe(elemento, valor) {
    texto(elemento, valor);
    elemento.hidden = !valor;
  }

  // QR em SVG vindo do backend, mostrado como imagem (uma imagem SVG não roda script)
  function mostrarQr(figura, imagem, svg) {
    const valido = typeof svg === "string" && svg.trimStart().startsWith("<svg");
    figura.hidden = !valido;
    if (!valido) {
      imagem.removeAttribute("src");
      delete imagem.dataset.svg;
      return;
    }
    if (imagem.dataset.svg !== svg) {
      imagem.dataset.svg = svg;
      imagem.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    }
  }

  function hora(iso) {
    if (!iso) return "";
    const data = new Date(iso);
    if (Number.isNaN(data.getTime())) return "";
    const hh = data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    const hoje = new Date();
    if (data.toDateString() === hoje.toDateString()) return hh;
    return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " + hh;
  }

  // ------------------------------------------------------------------ estado geral

  function mostrarResumo(estado) {
    const demo = estado.modo === "demonstracao";
    texto(el.resumoModo, demo ? "demonstração" : "real");
    el.resumoModo.className = "";
    texto(el.resumoConta, estado.conectado ? (demo ? "simulada, conectada" : "conectada") : "não conectada");
    el.resumoConta.className = estado.conectado ? "sim" : "nao";
    texto(el.resumoResponsavel, estado.responsavel_cadastrada ? "cadastrada" : "ainda não");
    el.resumoResponsavel.className = estado.responsavel_cadastrada ? "sim" : "nao";
  }

  // ------------------------------------------------------------------ passo 1: conta

  function mostrarConexao(conexao) {
    el.contaComando.hidden = true;
    let concluido = false;
    let textoPrincipal = "";
    let textoDetalhe = "";
    let svg = null;
    switch (conexao.estado) {
      case "simulada":
        concluido = true;
        textoPrincipal = "Modo demonstração: a conta da Dona Maria é simulada e já está conectada.";
        break;
      case "conectada":
        concluido = true;
        textoPrincipal = "Conta conectada. O Guardião já recebe as mensagens dela.";
        break;
      case "aguardando_leitura":
        svg = conexao.qr_svg;
        textoPrincipal =
          "No celular da pessoa idosa, abra o Telegram em Configurações → Dispositivos → " +
          "Conectar dispositivo e aponte a câmera para este QR.";
        textoDetalhe = "O QR muda sozinho a cada 30 segundos, mais ou menos. Use só uma conta de teste.";
        break;
      case "iniciando":
        textoPrincipal = "Preparando o QR da conta…";
        break;
      case "erro":
        if (conexao.motivo === "senha_2fa") {
          textoPrincipal =
            "Esta conta tem verificação em duas etapas, e a senha não é pedida nesta tela. " +
            "Faça o login pelo terminal, na pasta backend, e depois rode a seção 5 do notebook de novo:";
          texto(el.contaComando, conexao.comando || "python -m guardiao.verificar login");
          el.contaComando.hidden = false;
        } else if (conexao.motivo === "qr_vencido") {
          textoPrincipal = "O QR venceu sem ser lido. Gerando outro…";
        } else {
          textoPrincipal = "O login da conta falhou. Tentando de novo…";
        }
        break;
      case "desconectada":
        textoPrincipal = "A conta não está conectada. Rode a seção 5 do notebook de novo.";
        break;
      default:
        textoPrincipal = "Guardião não está rodando.";
    }
    texto(el.contaTexto, textoPrincipal);
    detalhe(el.contaDetalhe, textoDetalhe);
    mostrarQr(el.contaQr, el.contaQrImg, svg);
    el.passoConta.classList.toggle("feito", concluido);
  }

  // ------------------------------------------------------------------ passo 2: bot

  function mostrarCadastro(cadastro) {
    let textoPrincipal = "";
    let textoDetalhe = "";
    let link = null;
    switch (cadastro.estado) {
      case "aguardando":
        link = typeof cadastro.link === "string" && cadastro.link.startsWith("https://t.me/") ? cadastro.link : null;
        textoPrincipal =
          "No celular da responsável, leia este QR com a câmera (ou toque em Abrir o bot, se " +
          "estiver nesse celular) e toque em Iniciar no Telegram.";
        textoDetalhe = "O link é de uso único e muda sozinho antes de vencer. Ninguém mais consegue usar o bot.";
        break;
      case "cadastrada":
        textoPrincipal = "Responsável cadastrada. Os alertas chegam pelo bot no Telegram dela.";
        break;
      case "sem_bot":
        textoPrincipal =
          "Sem bot do Guardião: crie o Secret TELEGRAM_BOT_TOKEN e rode as seções 3 e 5 do notebook de novo.";
        break;
      case "erro":
        textoPrincipal = "Não consegui falar com o bot do Guardião. Tentando de novo…";
        break;
      default:
        textoPrincipal = "Guardião não está rodando.";
    }
    texto(el.botTexto, textoPrincipal);
    detalhe(el.botDetalhe, textoDetalhe);
    mostrarQr(el.botQr, el.botQrImg, link ? cadastro.qr_svg : null);
    if (link) {
      el.botAbrir.href = link;
      el.botAbrir.hidden = false;
    } else {
      el.botAbrir.removeAttribute("href");
      el.botAbrir.hidden = true;
    }
    el.passoBot.classList.toggle("feito", cadastro.estado === "cadastrada");
  }

  // ------------------------------------------------------------------ casos

  function itemCaso(caso) {
    const item = document.createElement("li");
    const estado = Object.prototype.hasOwnProperty.call(ESTADOS_CASO, caso.estado) ? caso.estado : "aguardando";
    item.className = "caso estado-" + estado;

    const topo = document.createElement("div");
    topo.className = "caso-topo";
    const quando = document.createElement("time");
    quando.className = "hora";
    texto(quando, hora(caso.criado_em));
    if (caso.criado_em) quando.dateTime = String(caso.criado_em);
    const selo = document.createElement("span");
    selo.className = "estado";
    texto(selo, ESTADOS_CASO[estado]);
    topo.append(quando, selo);

    const quem = document.createElement("p");
    quem.className = "quem";
    quem.append("Número novo dizendo ser ");
    const nome = document.createElement("strong");
    texto(nome, caso.quem);
    quem.append(nome);

    const trecho = document.createElement("blockquote");
    trecho.className = "trecho";
    texto(trecho, caso.trecho);

    item.append(topo, quem, trecho);
    if (caso.avisado_em) {
      const aviso = document.createElement("p");
      aviso.className = "avisado";
      texto(aviso, "Aviso à pessoa idosa às " + hora(caso.avisado_em));
      item.append(aviso);
    }
    return item;
  }

  function mostrarCasos(casos) {
    const lista = Array.isArray(casos) ? casos : [];
    const assinatura = JSON.stringify(lista);
    if (assinatura === casosMostrados) return; // não apaga a seleção nem repete o anúncio do leitor de tela
    casosMostrados = assinatura;
    el.casosLista.replaceChildren(...lista.map(itemCaso));
    el.casosVazio.hidden = lista.length > 0;
  }

  // ------------------------------------------------------------------ celular do golpista (demonstração)

  async function carregarCenarios() {
    if (cenariosCarregados) return;
    const dados = await obter(API.cenarios);
    const botoes = (dados.cenarios || []).map((cenario) => {
      const botao = document.createElement("button");
      botao.type = "button";
      botao.className = "cenario";
      const rotulo = document.createElement("span");
      rotulo.className = "cenario-rotulo";
      texto(rotulo, cenario.rotulo);
      const descricao = document.createElement("span");
      descricao.className = "cenario-descricao";
      texto(descricao, cenario.descricao);
      botao.append(rotulo, descricao);
      botao.addEventListener("click", () => injetar(cenario, botao));
      return botao;
    });
    el.golpistaBotoes.replaceChildren(...botoes);
    cenariosCarregados = true;
  }

  function plural(n, um, varios) {
    return n + " " + (n === 1 ? um : varios);
  }

  async function injetar(cenario, botao) {
    if (injetando) return;
    injetando = true;
    const botoes = el.golpistaBotoes.querySelectorAll("button");
    botoes.forEach((b) => { b.disabled = true; });
    botao.classList.add("enviando");
    texto(el.golpistaResultado, "Enviando as mensagens de “" + cenario.rotulo + "”… (a análise pode levar alguns segundos)");
    try {
      const resposta = await fetch(API.injetar, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cenario: cenario.id }),
        cache: "no-store",
      });
      const dados = await resposta.json().catch(() => ({}));
      if (!resposta.ok) {
        texto(el.golpistaResultado, "Não enviei: " + (dados.erro || "HTTP " + resposta.status) + ".");
      } else {
        texto(
          el.golpistaResultado,
          "“" + cenario.rotulo + "”: " + plural(dados.mensagens, "mensagem enviada", "mensagens enviadas") +
            "; " + plural(dados.analisadas, "foi para a análise", "foram para a análise") +
            " e " + plural(dados.descartadas, "descartada sem ler", "descartadas sem ler") + "."
        );
      }
    } catch (_) {
      texto(el.golpistaResultado, "Não consegui falar com o backend do Guardião.");
    } finally {
      injetando = false;
      botoes.forEach((b) => { b.disabled = false; });
      botao.classList.remove("enviando");
      agendar(0);
    }
  }

  // ------------------------------------------------------------------ ciclo

  async function atualizar() {
    const estado = await obter(API.estado);
    el.foraDoAr.hidden = true;
    el.parado.hidden = estado.rodando;
    el.resumo.hidden = !estado.rodando;
    if (!estado.rodando) {
      el.configuracao.hidden = true;
      el.casos.hidden = true;
      el.golpista.hidden = true;
      cenariosCarregados = false;
      return;
    }
    mostrarResumo(estado);
    const configurado = Boolean(estado.conectado && estado.responsavel_cadastrada);
    if (!configurado) {
      const [conexao, cadastro] = await Promise.all([obter(API.conexao), obter(API.cadastro)]);
      mostrarConexao(conexao);
      mostrarCadastro(cadastro);
    } else {
      mostrarCasos((await obter(API.casos)).casos);
    }
    el.configuracao.hidden = configurado;
    el.casos.hidden = !configurado;

    const demo = estado.modo === "demonstracao";
    if (demo) {
      try {
        await carregarCenarios();
      } catch (_) {
        cenariosCarregados = false;
      }
    } else {
      cenariosCarregados = false;
    }
    el.golpista.hidden = !(demo && cenariosCarregados);
  }

  async function ciclo() {
    proximo = null;
    try {
      await atualizar();
    } catch (_) {
      el.foraDoAr.hidden = false;
    }
    agendar(INTERVALO_MS);
  }

  function agendar(ms) {
    if (proximo !== null) clearTimeout(proximo);
    proximo = setTimeout(ciclo, ms);
  }

  ciclo();
})();
