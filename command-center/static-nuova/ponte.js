// Funzioni del Command Center che valgono SOLO dentro il ponte (https://vps.esempio.it,
// cc-ponte sulla VPS), cioè quando l'utente lo usa da fuori casa (2026-10-03).
// All'avvio chiede /_ponte/stato: sul Mac quel percorso non esiste (403/404) e qui non succede
// NIENTE, nessun elemento nuovo. Se risponde 200 {"ponte":true,"mac":…,"comandi":…}:
//  a) badge in alto «● Mac acceso» / «● Mac non raggiungibile», riletto ogni 15 s a scheda visibile;
//  b) microfono nella chat: dettato in italiano nel campo, NON si invia da solo;
//  c) altoparlante: legge a voce l'ultima risposta di Jarvis (preferenza nel browser);
//  d) «■ Stop» grande nella barra di invio quando la chat aspetta una risposta: usa la stessa
//     azione {tipo:"ferma", id} del «■ Ferma» dei lavori (app.js), niente protocollo nuovo;
//  e) avviso in chat se i comandi sono spenti dall'interruttore di emergenza;
//  f) (2026-10-03, coerenza del sito) classe «dentro-ponte» su <html>: mobile.css nasconde le pagine che
//     da internet non funzionano (Terminale, VPS, Tecnico) in tutti i menu, telefono e desktop.
//     «azioni» di /_ponte/stato (la tabella vera del ponte) va ad app.js (PONTE.prendiAzioni) a ogni
//     lettura; qui si spengono, col titolo «Disponibile solo dal Mac», SOLO i pulsanti la cui azione
//     (chiaveDi) il ponte non lascia passare, e si riaccendono quando torna (comandi-off tolto).
//     Senza elenco non si spegne niente.
//  g) modo della chat: l'interruttore lavoro/lettura/approvazione resta se il ponte passa «modo_chat»
//     («lavoro» spento: salta i permessi); senza, al suo posto l'etichetta «modo …».
(function ponte() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STATO = "/_ponte/stato";
  const PREF_VOCE = "ponte.altoparlante";
  const MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg>';
  // le globali di app.js: THREADS e chatCon sono const/let (non stanno su window) ma si leggono per nome
  const fili = () => (typeof THREADS !== "undefined" ? THREADS : null);
  const chatAperta = () => (typeof chatCon !== "undefined" ? chatCon : null);
  let stato = null;

  // ------------------------------------------------ h) sessione finita o uscita: niente conversazioni nel dispositivo
  // (REVISIONE-2, punto 7, 2026-10-03) Le chat stanno nel localStorage di questo browser. Quando il ponte dice
  // che la sessione è scaduta (401 su /api/* o /_ponte/stato, oppure un rinvio alla pagina di accesso) e quando
  // l'utente esce (/_ponte/esci), si cancellano le chiavi con le conversazioni e la cache del service worker.
  const CHIAVI_CONVERSAZIONI = [
    "cc.fili",             // THREADS di app.js: tutte le chat, fino a 120 messaggi per interlocutore
    "cc.chatCon",          // con chi era aperta la chat
    "cc.fili-da-parte",    // fili.js: le ultime 5 conversazioni sostituite
    "cc.fili-lasciati", "cc.fili-tolti", "cc.fili-visto", "cc.fili-ripartiti",   // fili.js: sessioni e messaggi tolti
  ];
  function pulisciDispositivo() {
    window.__ccSessioneFinita = true;          // app.js e fili.js non riscrivono più le chat
    for (const k of CHIAVI_CONVERSAZIONI) { try { localStorage.removeItem(k); } catch (e) { /* niente */ } }
    try { sessionStorage.removeItem("cc.ricarica"); } catch (e) { /* niente */ }
    let cache = Promise.resolve();
    try { if (window.caches) cache = caches.keys().then((k) => Promise.all(k.filter((n) => /^jarvis-cc/.test(n)).map((n) => caches.delete(n)))); } catch (e) { /* niente */ }
    return cache.catch(() => {});
  }
  function sessioneFinita() {
    if (sessioneFinita.fatto) return;
    sessioneFinita.fatto = true;
    pulisciDispositivo().then(() => location.replace("/_ponte/entra"));
  }
  // ogni fetch della pagina passa di qui: un 401 del ponte o un rinvio alla pagina di accesso = sessione finita
  const fetchVero = window.fetch;
  window.fetch = function (...arg) {
    return fetchVero.apply(this, arg).then((r) => {
      try {
        const u = new URL(r.url || (typeof arg[0] === "string" ? arg[0] : arg[0].url), location.href);
        const dentro = typeof PONTE === "object" && PONTE.dentro;
        if (u.origin === location.origin && ((r.status === 401 && (dentro || u.pathname === STATO) && (u.pathname.startsWith("/api/") || u.pathname === STATO))
          || (r.redirected && u.pathname === "/_ponte/entra"))) sessioneFinita();
      } catch (e) { /* niente */ }
      return r;
    });
  };
  // uscita: un link o un modulo verso /_ponte/esci (il ponte poi manda anche Clear-Site-Data)
  const versoEsci = (x) => { try { return new URL(x, location.href).pathname === "/_ponte/esci"; } catch (e) { return false; } };
  document.addEventListener("click", (ev) => { const a = ev.target.closest && ev.target.closest("a[href]"); if (a && versoEsci(a.getAttribute("href"))) pulisciDispositivo(); }, true);
  document.addEventListener("submit", (ev) => { const f = ev.target; if (f && f.action && versoEsci(f.action)) pulisciDispositivo(); }, true);

  async function leggiStato() {
    try {
      const r = await fetch(STATO, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
      if (r.status === 401) { sessioneFinita(); return { assente: true }; }     // dentro il ponte, ma la sessione è scaduta
      if (r.status !== 200) return { assente: true };
      const d = await r.json();
      return d && d.ponte === true ? d : { assente: true };
    } catch (e) {
      return { errore: true };
    }
  }

  // i pulsanti che fanno un POST non ammesso dal ponte (solo /api/azione chiedi, ferma, approva passano):
  // [data-solo-mac] li segna app.js e index.html, gli altri sono le azioni delegate per attributo di app.js
  const SOLO_MAC_SEL = "[data-solo-mac], [data-azione], [data-azione-diretta], [data-apri], [data-android], [data-aggiorna], " +
    "[data-ritira-fantasmi], [data-assist-stop], [data-cmd], [data-int] .switch, [data-tg] .riaggancia, [data-tel] .switch";
  // l'azione che un pulsante chiama, nella forma di ponteConsente() di app.js
  function chiaveDi(b) {
    if (b.hasAttribute("data-solo-mac")) return b.getAttribute("data-solo-mac");
    if (b.dataset.aggiorna) return "aggiorna:" + b.dataset.aggiorna;
    if (b.dataset.azioneDiretta) return b.dataset.azioneDiretta;
    if (b.dataset.azione) return b.dataset.azione;
    if (b.hasAttribute("data-apri")) return "apri";
    if (b.hasAttribute("data-android")) return "android";
    if (b.hasAttribute("data-ritira-fantasmi")) return "portiere:ritira_fantasmi";
    if (b.hasAttribute("data-assist-stop")) return "/api/assistenza/stop";
    if (b.hasAttribute("data-cmd")) return "comando_diretto";
    const tg = b.closest("[data-tg]");
    if (tg && b.classList.contains("riaggancia")) return "telegram_riaggancia";
    const riga = b.closest("[data-int]");
    if (riga) return riga.dataset.int === "schermo_telefono" && !b.classList.contains("on") ? "interruttore=schermo_telefono+acceso" : "interruttore";
    const tel = b.closest("[data-tel]");
    if (tel) return "telefono:" + (tel.dataset.tel === "centralino" ? (b.classList.contains("on") ? "centralino_ferma" : "centralino_avvia") : tel.dataset.tel);
    return "";
  }
  const consente = (k) => { try { return typeof ponteConsente !== "function" || ponteConsente(k); } catch (e) { return true; } };
  const prendiAzioni = (d) => { try { if (typeof PONTE === "object" && PONTE.prendiAzioni) PONTE.prendiAzioni(d && d.azioni); } catch (e) { /* app.js vecchio */ } };
  const SOLO_MAC = "Disponibile solo dal Mac";
  const decidi = (si) => { try { if (typeof PONTE === "object" && PONTE.decidi) PONTE.decidi(si); } catch (e) { /* app.js vecchio */ } };

  (async function avvio() {
    const d = await leggiStato();
    if (!d || d.assente || d.errore) { decidi(false); return; }     // sul Mac (o senza risposta alla prima lettura): niente
    stato = d;
    document.documentElement.classList.add("dentro-ponte");
    prendiAzioni(d);          // prima di decidi(): le chiamate in attesa trovano già l'elenco
    decidi(true);
    // aperta su #terminale, #vps o #tecnico (segnalibro, cronologia): app.js la riporta alla chat
    if (typeof mostraVista === "function" && /^#(terminale|vps|tecnico)$/.test(location.hash)) mostraVista();
    // il benvenuto della chat dice che i comandi con «/» partono solo dal Mac: si ridisegna adesso
    try { if (typeof disegnaModoChat === "function") disegnaModoChat(modoChat); } catch (e) { /* app.js vecchio */ }
    spegniSoloMac();
    new MutationObserver(() => { if (!spegniSoloMac.giro) spegniSoloMac.giro = requestAnimationFrame(spegniSoloMac); })
      .observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });   // app.js li riaccende
    document.body.classList.add("ponte");
    creaBadge();
    creaChat();
    disegna();
    setInterval(() => { if (!document.hidden) aggiornaStato(); }, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) aggiornaStato(); });
    setInterval(giro, 600);
    window.addEventListener("hashchange", voceDaIndirizzo);
    voceDaIndirizzo();
  })();

  async function aggiornaStato() {
    const d = await leggiStato();
    if (d.errore) { stato = Object.assign({}, stato, { rete: false }); }      // lettura fallita: l'elenco di prima resta
    else if (!d.assente) { stato = Object.assign(d, { rete: true }); prendiAzioni(d); }
    disegna();
    spegniSoloMac();
  }

  // ------------------------------------------------ a) badge
  let badge;
  function creaBadge() {
    badge = document.createElement("span");
    badge.className = "ponte-badge";
    badge.setAttribute("role", "status");
    const dopo = document.querySelector(".m-marca") || $("apri-lato");
    const barra = document.querySelector(".barra");
    if (dopo && dopo.parentNode === barra) dopo.after(badge);
    else if (barra) barra.insertBefore(badge, $("avatar-jarvis") || null);
  }

  // ------------------------------------------------ chat: microfono, altoparlante, stop, avvisi, modo
  let mic, stop, voceBtn, nota, avviso, modo;
  const Riconoscimento = window.SpeechRecognition || window.webkitSpeechRecognition;
  function creaChat() {
    const pillola = $("form-chiedi"), invia = $("btn-invia"), strumenti = document.querySelector(".chat-strumenti");
    if (!pillola || !invia) return;
    nota = document.createElement("small");
    nota.className = "ponte-nota";
    nota.setAttribute("aria-live", "polite");
    nota.hidden = true;
    pillola.after(nota);
    if (Riconoscimento) {
      mic = document.createElement("button");
      mic.type = "button";
      mic.className = "ponte-mic";
      mic.title = "Detta il messaggio (non parte da solo: rileggi e premi invio)";
      mic.setAttribute("aria-label", "Detta il messaggio");
      mic.setAttribute("aria-pressed", "false");
      mic.innerHTML = MIC;
      mic.addEventListener("click", () => (ascolto ? fermaAscolto() : avviaAscolto()));
      invia.before(mic);
    } else {
      dici("Il dettato vocale non è disponibile in questo browser: usa il microfono della tastiera");
    }
    stop = document.createElement("button");
    stop.type = "button";
    stop.className = "ponte-stop";
    stop.hidden = true;
    stop.textContent = "■ Stop";
    stop.title = "Ferma il lavoro in corso";
    stop.addEventListener("click", ferma);
    invia.after(stop);
    if (strumenti) {
      modo = document.createElement("span");
      modo.className = "ponte-modo";
      modo.title = "Il modo della chat si cambia dal Mac";
      voceBtn = document.createElement("button");
      voceBtn.type = "button";
      voceBtn.className = "icona ponte-voce-btn";
      voceBtn.addEventListener("click", () => { impostaVoce(!voceAccesa()); });
      strumenti.prepend(modo, voceBtn);
      impostaVoce(voceAccesa(), true);
    }
    avviso = document.createElement("div");
    avviso.className = "ponte-avviso";
    avviso.setAttribute("role", "alert");
    avviso.hidden = true;
    avviso.textContent = "Comandi spenti dall'interruttore di emergenza";
    const msgs = $("messaggi");
    if (msgs) msgs.before(avviso);
    const campo = $("chiedi-testo");
    if (campo) campo.addEventListener("input", () => { if (!scrivoIo) taci(); });
    // chi preme invio ferma la lettura in corso
    pillola.addEventListener("submit", () => { taci(); if (ascolto) fermaAscolto(); }, true);
  }

  function dici(testo, errore = false) {
    if (!nota) return;
    nota.textContent = testo || "";
    nota.hidden = !testo;
    nota.classList.toggle("errore", !!errore);
  }

  function disegna() {
    if (badge) {
      const rete = stato.rete !== false, acceso = rete && stato.mac === true;
      badge.textContent = !rete ? "Rete assente" : acceso ? "Mac acceso" : "Mac non raggiungibile";
      badge.className = "ponte-badge " + (!rete ? "rete" : acceso ? "acceso" : "spento");
      badge.title = !rete ? "Il ponte non risponde: controlla la connessione del telefono"
        : acceso ? "Il Mac di casa risponde attraverso il ponte" : "Il ponte è acceso ma il Mac non risponde: è spento, in stop o senza rete";
    }
    if (avviso) avviso.hidden = stato.comandi !== "spenti";
  }

  // ------------------------------------------------ f) pulsanti che da internet non funzionano
  // Spenti (disabled) con il titolo «Disponibile solo dal Mac» solo se il ponte non passa la loro azione.
  // Il titolo di prima resta in data-titolo-mac; data-ponte-era dice se il pulsante era già spento da
  // app.js (si rimette com'era quando l'azione torna). app.js a volte li riaccende: il giro li rispegne.
  function spegniSoloMac() {
    spegniSoloMac.giro = 0;
    for (const b of document.querySelectorAll(SOLO_MAC_SEL)) {
      const no = !consente(chiaveDi(b));
      const mio = b.dataset.ponteEra !== undefined;
      if (no) {
        if (!mio) { b.dataset.titoloMac = b.getAttribute("title") || ""; b.dataset.ponteEra = ("disabled" in b ? b.disabled : b.getAttribute("aria-disabled") === "true") ? "1" : "0"; b.classList.add("solo-mac"); }
        if (b.getAttribute("title") !== SOLO_MAC) b.setAttribute("title", SOLO_MAC);
        if ("disabled" in b) { if (!b.disabled) b.disabled = true; }
        else if (b.getAttribute("aria-disabled") !== "true") b.setAttribute("aria-disabled", "true");
      } else if (mio) {
        // l'azione ora passa (elenco arrivato, comandi riaccesi): com'era prima
        const era = b.dataset.ponteEra === "1";
        if ("disabled" in b) b.disabled = era; else if (!era) b.removeAttribute("aria-disabled");
        if (b.dataset.titoloMac) b.setAttribute("title", b.dataset.titoloMac); else b.removeAttribute("title");
        delete b.dataset.ponteEra; delete b.dataset.titoloMac; b.classList.remove("solo-mac");
      }
    }
  }

  // ------------------------------------------------ d) Stop e piccoli aggiornamenti, ogni 600 ms
  function attesaChat() {
    const T = fili(), k = chatAperta();
    const t = T && k != null ? T[k] : null;
    return t && t.attesa && t.attesa.id ? t.attesa : null;
  }
  function giro() {
    const a = attesaChat(), invia = $("btn-invia");
    if (stop) {
      stop.hidden = !a;
      if (invia) invia.hidden = !!a;
    }
    if (modo) {
      const m = typeof modoEffettivo === "function" ? modoEffettivo() : "";
      // il ponte passa modo_chat (approvazione, lettura): l'interruttore vero; altrimenti l'etichetta
      const cambia = consente("modo_chat"), box = $("modo-chat");
      if (box && box.style.display !== (cambia ? "" : "none")) box.style.display = cambia ? "" : "none";
      modo.textContent = m ? "modo " + m : "";
      modo.hidden = !m || cambia;
      for (const x of ["lavoro", "lettura", "approvazione"]) modo.classList.toggle(x, m === x);
      // «approvazione: Jarvis chiede il tuo permesso prima di scrivere o lanciare comandi» (titoloModo di app.js)
      const t = (m ? (typeof titoloModo === "function" ? titoloModo(m) : "modo " + m) + ". " : "") + "Il modo della chat si cambia dal Mac";
      if (modo.title !== t) { modo.title = t; modo.setAttribute("aria-label", t); }
    }
    spegniSoloMac();
    controllaRisposta();
  }
  async function ferma() {
    const a = attesaChat();
    if (!a) return;
    taci();
    if (typeof azione !== "function") return;
    await azione({ tipo: "ferma", id: a.id }, stop);
  }

  // ------------------------------------------------ b) microfono
  let ascolto = null, scrivoIo = false;
  function avviaAscolto() {
    if (!Riconoscimento || ascolto) return;
    const campo = $("chiedi-testo");
    if (!campo) return;
    taci();
    const r = new Riconoscimento();
    r.lang = "it-IT";
    r.interimResults = true;
    r.continuous = true;
    r.maxAlternatives = 1;
    const base = campo.value.trim() ? campo.value.replace(/\s*$/, " ") : "";
    r.onresult = (ev) => {
      let fissa = "", provvisoria = "";
      for (let i = 0; i < ev.results.length; i++) {
        const x = ev.results[i][0] ? ev.results[i][0].transcript : "";
        if (ev.results[i].isFinal) fissa += x; else provvisoria += x;
      }
      scrivoIo = true;
      campo.value = (base + fissa + provvisoria).replace(/\s+/g, " ").replace(/^\s/, "");
      campo.dispatchEvent(new Event("input", { bubbles: true }));     // app.js rifà l'altezza del campo
      scrivoIo = false;
    };
    r.onerror = (ev) => {
      const e = ev && ev.error;
      const testi = {
        "not-allowed": "Il microfono è bloccato per questo sito: consentilo nelle impostazioni del browser (il lucchetto accanto all'indirizzo) e riprova.",
        "service-not-allowed": "Il dettato non è permesso in questo browser: usa il microfono della tastiera.",
        "audio-capture": "Nessun microfono trovato: usa il microfono della tastiera.",
        "no-speech": "Non ho sentito niente: tocca il microfono e riprova.",
        network: "Il dettato ha bisogno della rete: riprova quando la connessione torna.",
        "language-not-supported": "Il dettato in italiano non è disponibile su questo browser.",
      };
      if (e !== "aborted") dici(testi[e] || "Il dettato si è fermato: riprova.", e !== "no-speech");
    };
    r.onend = () => { ascolto = null; segnaMic(false); };
    try {
      r.start();
    } catch (e) {
      dici("Il dettato non è partito: riprova.", true);
      return;
    }
    ascolto = r;
    segnaMic(true);
    dici("Ti ascolto… tocca di nuovo il microfono per fermare. Il messaggio non parte da solo.");
  }
  function fermaAscolto() {
    if (!ascolto) return;
    try { ascolto.stop(); } catch (e) { /* già fermo */ }
  }
  function segnaMic(si) {
    if (!mic) return;
    mic.classList.toggle("ascolta", si);
    mic.setAttribute("aria-pressed", String(si));
    mic.setAttribute("aria-label", si ? "Ferma il dettato" : "Detta il messaggio");
    if (!si && nota && !nota.classList.contains("errore")) dici("");
  }

  // ------------------------------------------------ #chat-voce: chat a schermo pieno, microfono pronto
  // I browser accendono il microfono solo dopo un gesto: un tocco grande fa partire il dettato.
  let veloVoce = null;
  function voceDaIndirizzo() {
    if (location.hash !== "#chat-voce") { if (veloVoce) veloVoce.remove(); veloVoce = null; return; }
    if (veloVoce) return;
    veloVoce = document.createElement("div");
    veloVoce.className = "ponte-velo-voce";
    veloVoce.setAttribute("role", "dialog");
    veloVoce.setAttribute("aria-label", "Parla a Jarvis");
    const titolo = document.createElement("b");
    titolo.textContent = "Parla a Jarvis";
    const testo = document.createElement("p");
    const scrivi = document.createElement("button");
    scrivi.type = "button";
    scrivi.className = "ponte-scrivi";
    scrivi.textContent = "Scrivi invece";
    const chiudi = (dettato) => {
      history.replaceState(null, "", "#chat");
      if (veloVoce) veloVoce.remove();
      veloVoce = null;
      if (dettato) avviaAscolto(); else { const c = $("chiedi-testo"); if (c) c.focus(); }
    };
    scrivi.addEventListener("click", () => chiudi(false));
    if (Riconoscimento) {
      const grande = document.createElement("button");
      grande.type = "button";
      grande.className = "ponte-mic-grande";
      grande.setAttribute("aria-label", "Tocca e parla");
      grande.innerHTML = MIC;
      grande.addEventListener("click", () => chiudi(true));
      testo.textContent = "Tocca il microfono e parla. Il testo va nel campo della chat: lo rileggi e premi invio.";
      veloVoce.append(titolo, grande, testo, scrivi);
    } else {
      testo.textContent = "Il dettato vocale non è disponibile in questo browser: usa il microfono della tastiera.";
      veloVoce.append(titolo, testo, scrivi);
    }
    document.body.append(veloVoce);
  }

  // ------------------------------------------------ c) altoparlante
  const voceAccesa = () => { try { return localStorage.getItem(PREF_VOCE) === "1"; } catch (e) { return false; } };
  function impostaVoce(si, soloDisegno = false) {
    if (!soloDisegno) { try { localStorage.setItem(PREF_VOCE, si ? "1" : "0"); } catch (e) { /* preferenza solo per questa volta */ } }
    if (!si) taci();
    if (!voceBtn) return;
    voceBtn.textContent = si ? "🔊" : "🔈";
    voceBtn.setAttribute("aria-pressed", String(si));
    voceBtn.setAttribute("aria-label", si ? "Lettura a voce accesa: tocca per spegnerla" : "Lettura a voce spenta: tocca per accenderla");
    voceBtn.title = voceBtn.getAttribute("aria-label");
    if (si && !("speechSynthesis" in window)) dici("Questo browser non sa leggere a voce.", true);
  }
  function taci() { try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) { /* niente */ } }
  // l'ultima risposta arrivata: si legge solo quella nuova, mai quelle già in pagina all'apertura
  let ultimo = { chat: undefined, msg: undefined };
  function controllaRisposta() {
    const T = fili(), k = chatAperta();
    if (!T || k == null) return;
    const t = T[k], m = t && t.messaggi && t.messaggi.length ? t.messaggi[t.messaggi.length - 1] : null;
    if (ultimo.chat !== k) { ultimo = { chat: k, msg: m }; return; }
    if (m === ultimo.msg) return;
    ultimo.msg = m;
    if (!m || m.chi !== "lui" || m.errore || m.tipo === "comando" || !voceAccesa() || ascolto) return;
    leggi(m.testo);
  }
  function testoDaLeggere(t) {
    return String(t || "")
      .replace(/```[\s\S]*?```/g, " (codice) ")
      .replace(/`([^`]*)`/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/https?:\/\/\S+/g, "(link)")
      .replace(/^[#>\-*•]+\s*/gm, "")
      .replace(/[|]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 1500);
  }
  function leggi(t) {
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return;
    const testo = testoDaLeggere(t);
    if (!testo) return;
    taci();
    const u = new SpeechSynthesisUtterance(testo);
    u.lang = "it-IT";
    u.rate = 1.05;
    try {
      const voci = speechSynthesis.getVoices() || [];
      const it = voci.find((v) => /^it([-_]|$)/i.test(v.lang || ""));
      if (it) u.voice = it;
    } catch (e) { /* voce di sistema */ }
    speechSynthesis.speak(u);
  }
})();
