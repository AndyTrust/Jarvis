// La chiamata con Jarvis (2026-10-03): una conversazione a voce a schermo pieno, SOLO dentro il ponte
// (https://vps.esempio.it, cc-ponte sulla VPS). Sul Mac non compare niente e non parte
// nessuna richiesta: questo file non chiede /_ponte/stato, aspetta che ponte.js metta la classe «ponte»
// sul body (lo fa solo quando /_ponte/stato risponde 200).
//
// Il giro: il riconoscimento del browser (it-IT, continuo, con i provvisori) ascolta; dopo una frase e
// 1,5 s di silenzio la frase parte come un messaggio scritto nella chat aperta, con la stessa funzione
// della pagina (invia() di app.js: tipo «chiedi», sessione del filo, storico); il lavoro si segue dove
// lo segue già app.js (THREADS[chat].attesa, seguiRisposte), le attività in diretta arrivano da
// attivita.js (window.CCAttivita.voci); la risposta si legge con speechSynthesis, ripulita (niente
// markdown, codice, indirizzi; le prime 2-3 frasi e poi «il resto è in chat»). Mentre Jarvis parla il
// microfono è chiuso, più 700 ms di coda. Le richieste di permesso compaiono in grande e si decidono
// SOLO con un tocco (mai a voce); rischio alto = secondo tocco entro 5 s, come approvazioni.js.
//
// Ganci con app.js (nessuna modifica): THREADS, chatCon, filo(), invia(), azione(),
// autoAltezza() si leggono per nome (const/let/function di uno script classico).
// Per le prove: window.__CHIAMATA_TEMPI = {silenzio, coda, inattivita, avviso, sfondo, ...} accorcia i tempi.
(function chiamata() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const TEMPI = { silenzio: 1500, coda: 700, inattivita: 300000, avviso: 240000, sfondo: 60000, sonda: 2000,
    rapido: 2000, passoRiavvio: 250, tettoRiavvii: 5, conferma: 5000, giro: 250, attivitaSonda: 2000,
    confermaMin: 800,        // rischio alto: il secondo tocco vale solo dopo 800 ms dal primo (REVISIONE-2, punto 5)
    contoInvio: 2000 };      // la frase sentita parte dopo 2 s, con «Annulla» e «Invia subito» (REVISIONE-2, punto 6)
  const T = () => Object.assign({}, TEMPI, window.__CHIAMATA_TEMPI || {});
  // App Jarvis per Android: il dettato dell'app (window.CCRiconoscimentoNativo, definito in ponte.js).
  const Riconoscimento = () => (window.JarvisApp && window.CCRiconoscimentoNativo) || window.SpeechRecognition || window.webkitSpeechRecognition;
  const FASI = { ascolto: "Ascolto", sente: "Ti sento…", lavora: "Jarvis sta lavorando", parla: "Jarvis parla", muto: "Muto",
    fermo: "Microfono fermo", avvio: "Avvio…" };
  const NON_DISPONIBILE = "La chiamata vocale non è disponibile in questo browser: usa il microfono della tastiera";
  const ERRORI_MIC = {
    "not-allowed": "Il microfono è bloccato per questo sito: consentilo nelle impostazioni del browser (il lucchetto accanto all'indirizzo), poi tocca il cerchio per riprovare.",
    "service-not-allowed": "Il riconoscimento della voce non è permesso in questo browser: usa il microfono della tastiera.",
    "audio-capture": "Nessun microfono trovato: collegane uno o usa il microfono della tastiera.",
    "language-not-supported": "Il riconoscimento in italiano non è disponibile in questo browser.",
  };
  const ICONE = {
    tel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg>',
    micNo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M4 4l16 16"/></svg>',
    alt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/></svg>',
    altNo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9l5 6M22 9l-5 6"/></svg>',
    riduci: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>',
    giu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 14.5c4.5-4 11.5-4 16 0l-2.2 2.6-3.3-1.4v-2.6a10 10 0 0 0-5 0v2.6l-3.3 1.4z"/></svg>',
  };

  // ---------------------------------------------------------------- globali di app.js, lette per nome
  const G = {
    THREADS: () => (typeof THREADS !== "undefined" ? THREADS : undefined),        // eslint-disable-line no-undef
    chatCon: () => (typeof chatCon !== "undefined" ? chatCon : undefined),        // eslint-disable-line no-undef
    filo: () => (typeof filo === "function" ? filo : undefined),                  // eslint-disable-line no-undef
    invia: () => (typeof invia === "function" ? invia : undefined),               // eslint-disable-line no-undef
    azione: () => (typeof azione === "function" ? azione : undefined),            // eslint-disable-line no-undef
    autoAltezza: () => (typeof autoAltezza === "function" ? autoAltezza : undefined),   // eslint-disable-line no-undef
  };
  const globale = (n) => { try { return G[n](); } catch (e) { return undefined; } };
  const filoDi = (k) => { const Th = globale("THREADS"); return Th && k != null ? Th[k] || null : null; };
  const ultimo = (t) => (t && Array.isArray(t.messaggi) && t.messaggi.length ? t.messaggi[t.messaggi.length - 1] : null);

  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;                 // solo le icone fisse di questo file
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const f of figli) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  const mmss = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };
  const corto = (s, max) => { s = String(s == null ? "" : s).trim(); if (s.length <= max) return s; const t = s.slice(0, max - 1); const i = t.lastIndexOf(" "); return (i > max * 0.6 ? t.slice(0, i) : t) + "…"; };

  // ---------------------------------------------------------------- testo da leggere a voce
  // Niente markdown, codice, indirizzi, emoji. Un blocco di codice diventa «ti ho scritto il codice in
  // chat»; un percorso diventa il nome del file; le risposte lunghe si fermano alla terza frase.
  const FRASE_CODICE = "Ti ho scritto il codice in chat.";
  function perVoce(testo, max = 320) {
    let s = String(testo || "");
    let codice = false, link = false;
    s = s.replace(/```[\s\S]*?(```|$)/g, () => { codice = true; return "\n\u0001\n"; });
    s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t) => { link = true; return t; });
    s = s.replace(/\b(?:https?:\/\/|www\.)[^\s<>"')\]]+/g, () => { link = true; return " "; });
    const nomeFile = (p) => { const x = p.replace(/\/+$/, "").split("/").pop(); return x || ""; };
    s = s.replace(/`([^`\n]*)`/g, (m, x) => (/\//.test(x) ? nomeFile(x) : x.length > 48 ? " " : x));
    s = s.replace(/(^|[\s(])((?:~|\.{1,2})?\/[\w.\-@]+(?:\/[\w.\-@ ]*)*)/g, (m, a, p) => a + nomeFile(p));
    s = s.replace(/^\s{0,3}#{1,6}\s*/gm, "")
      .replace(/^\s*>\s?/gm, "")
      .replace(/^\s*[-*+•]\s+/gm, "")
      .replace(/^\s*\|?\s*:?-{2,}.*$/gm, " ")
      .replace(/\|/g, " ")
      .replace(/\*\*|__|~~/g, "")
      .replace(/(^|[\s(])[*_]([^*_\n]+)[*_](?=[\s.,;:!?)]|$)/g, "$1$2");
    try { s = s.replace(/\p{Extended_Pictographic}️?/gu, ""); } catch (e) { /* motore senza \p */ }
    // una riga senza punteggiatura in fondo diventa una frase
    s = s.split(/\n+/).map((r) => r.replace(/\s+/g, " ").trim()).filter(Boolean)
      .map((r) => (r === "\u0001" || /[.!?:;,…]$/.test(r) ? r : r + ".")).join(" ");
    let primoCodice = true;
    s = s.replace(/\s*\u0001\s*/g, () => { const x = primoCodice ? " " + FRASE_CODICE + " " : " "; primoCodice = false; return x; });
    s = s.replace(/\s+([.,;:!?])/g, "$1").replace(/([.:;!?])\.+/g, "$1").replace(/\s+/g, " ").trim();
    if (!s) return codice ? FRASE_CODICE : link ? "Il link è in chat." : "";
    const frasi = s.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [s];
    let fuori = "", n = 0;
    for (const f of frasi) {
      const x = f.trim();
      if (!x) continue;
      if (n >= 3 || (n >= 1 && (fuori + " " + x).length > max)) break;
      fuori = fuori ? fuori + " " + x : x;
      n++;
    }
    let tagliato = fuori.length < s.length - 1;
    if (fuori.length > max + 40) { fuori = corto(fuori, max); tagliato = true; }
    if (tagliato) {
      if (codice && !fuori.includes(FRASE_CODICE)) fuori += " " + FRASE_CODICE;
      fuori += " Il resto è in chat.";
    } else if (link && !/link/i.test(fuori)) fuori += " Il link è in chat.";
    return fuori.trim();
  }
  // il riepilogo di un permesso, a voce: breve, senza percorsi lunghi né comandi
  function riepilogoVoce(a) {
    let r = String((a && a.riepilogo) || "").replace(/`[^`]*`/g, " ");
    r = r.replace(/(?:~|\.{1,2})?\/[\w.\-@/]+/g, (p) => p.replace(/\/+$/, "").split("/").pop());
    r = r.replace(/\s+/g, " ").trim();
    return corto(r || "un'operazione", 90).replace(/[.…]+$/, "");
  }

  // ---------------------------------------------------------------- stato
  const S = {
    montato: false, aperta: false, vista: false, fase: "avvio", inizio: 0,
    micMuto: false, altMuto: false, micErrore: "",
    rec: null, recInizio: 0, recRisultato: false, recErrore: "", riavvii: 0, timerRiavvio: null,
    fissa: "", provv: "", timerSilenzio: null,
    invio: null,             // { k, rif, id, inviando, da } il messaggio partito e il lavoro che lo segue
    fermato: false,
    coda: [], parlando: null, timerParla: null, timerCoda: null, ioCancello: false, voceOrig: null,
    ultimaAttivita: 0, avvisato: false, timerSfondo: null, wake: null, tick: null, ultimoSecondo: -1,
    richieste: 0,            // quante richieste ha fatto questo file (le prove controllano che sul Mac siano zero)
    letture: [],             // per le prove: cosa è stato mandato alla voce
    appr: { attivo: null, lista: [], annunciati: new Set(), conferma: new Map(), primo: new Map(), codici: new Map(), locale: new Map(), inVolo: false, ultima: 0, firma: "",
      visto: new Set(), aperto: new Set() },     // visto: il testo del permesso è stato letto fino in fondo; aperto: «Mostra tutto»
    conto: null,             // { testo, fino, timer, tick } la frase in attesa di partire
    attFallback: { id: null, voci: [], ultima: 0 },
    chiusura: "",
  };
  const mie = new WeakSet();       // gli enunciati di questo file (gli altri tacciono durante la chiamata)

  // ---------------------------------------------------------------- avvio: solo nel ponte
  function quandoPonte(fn) {
    const b = document.body;
    if (!b) { document.addEventListener("DOMContentLoaded", () => quandoPonte(fn)); return; }
    if (b.classList.contains("ponte")) { fn(); return; }
    const mo = new MutationObserver(() => { if (b.classList.contains("ponte")) { mo.disconnect(); fn(); } });
    mo.observe(b, { attributes: true, attributeFilter: ["class"] });
  }
  // 2026-10-03: le variabili prima di quandoPonte(monta). Se ponte.js ha già acceso «ponte» quando questo file
  // gira, monta() parte subito e trovava btn ancora non dichiarata (ReferenceError «Cannot access 'btn' before
  // initialization»: niente pulsante «Chiama»). Visto con Chrome nelle misure del 2026-10-03.
  let btn = null, nota = null, dlg = null, pillola = null, N = {};
  quandoPonte(monta);

  function monta() {
    if (S.montato) return;
    S.montato = true;
    mettiPulsante();
    window.addEventListener("hashchange", daIndirizzo);
    daIndirizzo();
    document.addEventListener("visibilitychange", visibilita);
    window.addEventListener("pagehide", () => { if (S.aperta) chiudi("pagina"); });
  }

  // il pulsante «Chiama» accanto al microfono di ponte.js (che lo mette subito dopo aver acceso il ponte;
  // se non c'è ancora, lo aspetto); senza riconoscimento vocale nel browser va prima di «invio»
  function mettiPulsante() {
    const form = $("form-chiedi");
    if (!form) return;
    btn = el("button", { type: "button", class: "chiamata-btn", title: "Chiama Jarvis: conversazione a voce",
      "aria-label": "Chiama Jarvis: conversazione a voce", "aria-haspopup": "dialog", html: ICONE.tel, onclick: () => apri() });
    nota = el("small", { class: "chiamata-nota", role: "status", "aria-live": "polite", hidden: true });
    const posa = () => {
      const mic = form.querySelector(".ponte-mic");
      if (mic) { if (btn.previousElementSibling !== mic) mic.after(btn); return true; }
      if (!Riconoscimento()) { const inv = $("btn-invia"); if (inv && btn.parentNode !== form) inv.before(btn); return true; }
      return false;
    };
    if (!posa()) {
      const inv = $("btn-invia");
      if (inv) inv.before(btn);                           // intanto qui; si sposta quando arriva il microfono
      const mo = new MutationObserver(() => { if (posa()) mo.disconnect(); });
      mo.observe(form, { childList: true });
      setTimeout(() => mo.disconnect(), 30000);
    }
    form.after(nota);
  }
  function dici(testo, errore = false) {
    if (!nota) return;
    nota.textContent = testo || "";
    nota.hidden = !testo;
    nota.classList.toggle("errore", !!errore);
    clearTimeout(dici.t);
    if (testo) dici.t = setTimeout(() => { nota.hidden = true; }, 12000);
  }

  function daIndirizzo() {
    if (location.hash !== "#chiamata") return;
    history.replaceState(null, "", "#chat");
    try { window.dispatchEvent(new HashChangeEvent("hashchange")); } catch (e) { /* niente */ }
    apri();
  }

  // ---------------------------------------------------------------- la schermata
  function costruisci() {
    if (dlg) return;
    N.tempo = el("span", { class: "chm-tempo", role: "timer", "aria-live": "off", "aria-label": "Durata della chiamata" }, "00:00");
    N.stato = el("span", { class: "chm-stato", id: "chm-stato", role: "status", "aria-live": "polite", "aria-atomic": "true" }, FASI.avvio);
    N.titolo = el("h2", { class: "chm-titolo", id: "chm-titolo" }, "Chiamata con Jarvis");
    N.avatar = el("button", { type: "button", class: "chm-avatar", "aria-describedby": "chm-stato", onclick: toccoAvatar },
      el("span", { class: "chm-onda chm-onda-1", "aria-hidden": "true" }), el("span", { class: "chm-onda chm-onda-2", "aria-hidden": "true" }),
      el("span", { class: "chm-anello", "aria-hidden": "true" }), el("span", { class: "chm-j", "aria-hidden": "true" }, "J"));
    N.suggerimento = el("p", { class: "chm-suggerimento" });
    N.attivita = el("p", { class: "chm-attivita", "aria-live": "off" });
    N.avviso = el("p", { class: "chm-avviso", role: "alert", hidden: true });
    N.tuDef = el("span", { class: "chm-def" });
    N.tuProvv = el("span", { class: "chm-provv", "aria-hidden": "true" });
    N.tu = el("p", { class: "chm-riga chm-tu", hidden: true }, el("span", { class: "chm-chi" }, "Tu"), el("span", { class: "chm-frase" }, N.tuDef, N.tuProvv));
    N.luiSr = el("span", { class: "chm-sr" });
    N.luiLetto = el("span", { class: "chm-letto" });
    N.luiResto = el("span", { class: "chm-resto" });
    N.lui = el("p", { class: "chm-riga chm-lui", hidden: true }, el("span", { class: "chm-chi" }, "Jarvis"),
      el("span", { class: "chm-frase" }, N.luiSr, el("span", { "aria-hidden": "true" }, N.luiLetto, N.luiResto)));
    N.sottotitoli = el("section", { class: "chm-sottotitoli", role: "log", "aria-live": "polite", "aria-label": "Sottotitoli" }, N.tu, N.lui);
    // il conto alla rovescia prima dell'invio (punto 6 della REVISIONE-2)
    N.contoTesto = el("span", { class: "chm-conto-testo", "aria-hidden": "true" });
    N.contoSr = el("span", { class: "chm-sr", role: "status", "aria-live": "assertive" });
    N.contoAnnulla = el("button", { type: "button", class: "chm-conto-annulla", onclick: () => annullaConto(true) }, "Annulla");
    N.contoSubito = el("button", { type: "button", class: "chm-conto-subito", onclick: () => inviaSubito() }, "Invia subito");
    N.conto = el("section", { class: "chm-conto", hidden: true, "aria-label": "Invio della frase" },
      N.contoTesto, N.contoSr, el("div", { class: "chm-conto-bottoni" }, N.contoAnnulla, N.contoSubito));
    // il riquadro del permesso
    N.pTit = el("h3", { class: "chm-p-tit", id: "chm-p-tit" }, "Jarvis chiede il permesso");
    N.pRischio = el("span", { class: "chm-p-rischio" });
    N.pRiep = el("p", { class: "chm-p-riep" });
    // 2026-10-03 (REVISIONE-2, F1): il comando INTERO (fino a 4000 caratteri), a capo come arriva, in un riquadro
    // che scorre; Approva resta spento finché il testo non è stato visto fino in fondo
    N.pComando = el("pre", { class: "chm-p-comando", tabindex: "0", "aria-label": "Il testo completo della richiesta" });
    N.pTutto = el("button", { type: "button", class: "chm-p-tutto", hidden: true, onclick: () => apriTesto() }, "Mostra tutto");
    N.pTaglio = el("p", { class: "chm-p-taglio", hidden: true });
    N.pComando.addEventListener("scroll", () => controllaVisto(), { passive: true });
    N.pNo = el("button", { type: "button", class: "chm-p-no", onclick: () => decidi("no") }, "Rifiuta");
    N.pSi = el("button", { type: "button", class: "chm-p-si", onclick: () => decidi("si") }, "Approva");
    N.pNota = el("p", { class: "chm-p-nota", role: "status", "aria-live": "polite" });
    N.pAltre = el("p", { class: "chm-p-altre" });
    N.permesso = el("section", { class: "chm-permesso", role: "group", "aria-labelledby": "chm-p-tit", hidden: true },
      el("div", { class: "chm-p-capo" }, N.pTit, N.pRischio), N.pRiep, N.pTaglio, N.pComando, N.pTutto,
      el("div", { class: "chm-p-bottoni" }, N.pNo, N.pSi), N.pNota, N.pAltre,
      el("p", { class: "chm-p-voce" }, "Si decide solo col tocco: a voce non si approva niente."));
    // i comandi
    const b = (cl, icona, testo, fn) => el("button", { type: "button", class: "chm-b " + cl, onclick: fn },
      el("span", { class: "chm-ico", html: icona }), el("span", { class: "chm-etichetta" }, testo));
    N.mic = b("chm-mic", ICONE.mic, "Microfono", () => { segnaAttivita(); impostaMicMuto(!S.micMuto); });
    N.alt = b("chm-alt", ICONE.alt, "Audio", () => { segnaAttivita(); impostaAltMuto(!S.altMuto); });
    N.riduci = b("chm-riduci", ICONE.riduci, "Riduci", () => riduci());
    N.stop = b("chm-stop", ICONE.stop, "Stop", () => { segnaAttivita(); stop(); });
    N.chiudi = el("button", { type: "button", class: "chm-chiudi", onclick: () => chiudi("utente") },
      el("span", { class: "chm-ico", html: ICONE.giu }), el("span", {}, "Chiudi chiamata"));
    N.riduci.setAttribute("aria-label", "Riduci: torna alla chat, la chiamata resta aperta");
    dlg = el("dialog", { class: "chiamata", "aria-labelledby": "chm-titolo", "data-fase": "avvio" },
      el("div", { class: "chm-colonna" },
        el("header", { class: "chm-capo" }, N.titolo, el("div", { class: "chm-capo-riga" }, el("span", { class: "chm-punto", "aria-hidden": "true" }), N.tempo, el("span", { class: "chm-sep", "aria-hidden": "true" }, "·"), N.stato)),
        el("div", { class: "chm-centro" }, N.avatar, N.suggerimento, N.attivita, N.avviso),
        N.sottotitoli, N.conto, N.permesso,
        el("footer", { class: "chm-comandi" }, el("div", { class: "chm-fila" }, N.mic, N.alt, N.riduci, N.stop), N.chiudi)));
    dlg.addEventListener("cancel", (ev) => { ev.preventDefault(); riduci(); });             // Esc riduce
    dlg.addEventListener("close", () => { if (S.aperta && S.vista && !S.chiudoIo) { S.vista = false; mostraPillola(); } });
    // dentro la chiamata i tasti non vanno alla pagina (la lavagna ha le sue scorciatoie)
    dlg.addEventListener("keydown", (ev) => { if (ev.key !== "Escape" && ev.key !== "Tab") ev.stopPropagation(); });
    document.body.append(dlg);
    pillola = el("button", { type: "button", class: "chiamata-pillola", hidden: true, onclick: () => riapri() },
      el("span", { class: "chm-punto", "aria-hidden": "true" }), el("span", { class: "chm-pil-testo" }, ""));
    document.body.append(pillola);
  }

  function disegna() {
    if (!dlg) return;
    const fase = S.fase;
    dlg.dataset.fase = fase;
    const etichetta = FASI[fase] || fase;
    if (N.stato.textContent !== etichetta) N.stato.textContent = etichetta;
    const tempo = mmss(Date.now() - S.inizio);
    if (N.tempo.textContent !== tempo) N.tempo.textContent = tempo;
    const sugg = fase === "parla" ? "Tocca il cerchio per interrompere e parlare"
      : fase === "fermo" ? (S.micErrore || "Il microfono si è fermato: tocca il cerchio per riprovare")
      : fase === "muto" ? "Microfono spento: tocca «Microfono» per riaccenderlo"
      : fase === "lavora" ? "" : fase === "ascolto" ? "Parla pure: mando la frase dopo un attimo di silenzio" : "";
    if (N.suggerimento.textContent !== sugg) N.suggerimento.textContent = sugg;
    N.suggerimento.classList.toggle("errore", fase === "fermo");
    N.avatar.setAttribute("aria-label", fase === "parla" ? "Interrompi Jarvis e parla" : fase === "fermo" ? "Riprova ad accendere il microfono" : "Jarvis: " + etichetta);
    N.mic.setAttribute("aria-pressed", String(S.micMuto));
    N.mic.setAttribute("aria-label", S.micMuto ? "Microfono spento: tocca per riaccenderlo" : "Spegni il microfono");
    if (N.mic.dataset.muto !== String(S.micMuto)) {
      N.mic.dataset.muto = String(S.micMuto);
      N.mic.querySelector(".chm-ico").innerHTML = S.micMuto ? ICONE.micNo : ICONE.mic;
      N.mic.querySelector(".chm-etichetta").textContent = S.micMuto ? "Muto" : "Microfono";
    }
    N.alt.setAttribute("aria-pressed", String(S.altMuto));
    N.alt.setAttribute("aria-label", S.altMuto ? "Voce di Jarvis spenta: tocca per riaccenderla" : "Spegni la voce di Jarvis (leggi solo i sottotitoli)");
    if (N.alt.dataset.muto !== String(S.altMuto)) {
      N.alt.dataset.muto = String(S.altMuto);
      N.alt.querySelector(".chm-ico").innerHTML = S.altMuto ? ICONE.altNo : ICONE.alt;
      N.alt.querySelector(".chm-etichetta").textContent = S.altMuto ? "Silenzio" : "Audio";
    }
    const puoStop = !!idLavoro() || fase === "parla";
    N.stop.disabled = !puoStop;
    N.stop.setAttribute("aria-label", idLavoro() ? "Ferma il lavoro in corso" : fase === "parla" ? "Ferma la lettura" : "Stop: nessun lavoro in corso");
    disegnaPillola();
  }
  function disegnaPillola() {
    if (!pillola) return;
    const p = permessoAperto();
    const t = `${mmss(Date.now() - S.inizio)} · ${p ? "Permesso da decidere" : FASI[S.fase] || ""}`;
    const testo = pillola.querySelector(".chm-pil-testo");
    if (testo.textContent !== t) testo.textContent = t;
    pillola.dataset.fase = S.fase;
    pillola.classList.toggle("chm-pil-permesso", !!p);
    pillola.setAttribute("aria-label", `Chiamata con Jarvis in corso, ${t}: tocca per riaprirla`);
    posaPillola();
  }
  function imposta(fase) {
    if (S.fase === fase) return;
    S.fase = fase;
    disegna();
  }

  // ---------------------------------------------------------------- aprire, ridurre, chiudere
  function apri() {
    if (!Riconoscimento()) {
      dici(NON_DISPONIBILE, true);
      return;
    }
    costruisci();
    if (S.aperta) { riapri(); return; }
    Object.assign(S, { aperta: true, inizio: Date.now(), fase: "avvio", micMuto: false, micErrore: "", fissa: "", provv: "",
      invio: null, fermato: false, coda: [], parlando: null, riavvii: 0, ultimaAttivita: Date.now(), avvisato: false, chiusura: "" });
    S.appr.attivo = null; S.appr.lista = []; S.appr.locale.clear(); S.appr.conferma.clear(); S.appr.firma = "";
    N.tu.hidden = true; N.lui.hidden = true; N.attivita.textContent = ""; N.avviso.hidden = true; N.permesso.hidden = true;
    proteggiVoce();
    dici("");
    mostraSchermo();
    prendiWake();
    S.tick = setInterval(giro, T().giro);
    sondaPermessi();
    // un lavoro già in corso nella chat aperta (scritto prima della chiamata): lo seguo e leggo la risposta
    if (!adottaLavoro()) avviaAscolto();
    disegna();
  }
  function mostraSchermo() {
    S.vista = true;
    if (pillola) pillola.hidden = true;
    if (!dlg.open) { try { dlg.showModal(); } catch (e) { dlg.setAttribute("open", ""); } }
    disegna();
    requestAnimationFrame(() => { try { N.mic.focus({ preventScroll: true }); } catch (e) { /* niente */ } });
  }
  function riapri() { if (!S.aperta) return; segnaAttivita(); mostraSchermo(); }
  function riduci() {
    if (!S.aperta) return;
    S.vista = false;
    S.chiudoIo = true; try { dlg.close(); } catch (e) { dlg.removeAttribute("open"); } S.chiudoIo = false;
    if (location.hash !== "#chat" && location.hash !== "") location.hash = "#chat";
    mostraPillola();
  }
  // la pillola galleggia sopra i messaggi (non copre la barra in alto con il badge del Mac e le richieste)
  function posaPillola() {
    if (!pillola || pillola.hidden) return;
    const msgs = $("messaggi"), barra = document.querySelector("header.barra");
    const visibile = (n) => n && n.offsetParent !== null && n.getBoundingClientRect().height > 0;
    let top = 8, centro = innerWidth / 2;
    if (visibile(msgs)) { const r = msgs.getBoundingClientRect(); top = r.top + 8; centro = r.left + r.width / 2; }
    else if (visibile(barra)) top = barra.getBoundingClientRect().bottom + 8;
    top = Math.max(8, Math.min(top, innerHeight - 120));
    pillola.style.top = `max(${Math.round(top)}px, calc(env(safe-area-inset-top, 0px) + 8px))`;
    pillola.style.left = Math.round(centro) + "px";
  }
  function mostraPillola() {
    if (!pillola) return;
    pillola.hidden = false;
    posaPillola();
    disegnaPillola();
    requestAnimationFrame(() => { try { pillola.focus({ preventScroll: true }); } catch (e) { /* niente */ } });
  }
  const MOTIVI = { inattivita: "Chiamata chiusa: nessuno parlava da 5 minuti.", sfondo: "Chiamata chiusa: la pagina è rimasta in secondo piano per più di un minuto.",
    utente: "Chiamata chiusa.", pagina: "" };
  function chiudi(motivo) {
    if (!S.aperta) return;
    S.aperta = false;
    S.chiusura = motivo || "utente";
    clearInterval(S.tick); S.tick = null;
    clearTimeout(S.timerSilenzio); clearTimeout(S.timerRiavvio); clearTimeout(S.timerSfondo); clearTimeout(S.timerParla); clearTimeout(S.timerCoda);
    fermaAscolto();
    annullaConto(false);
    S.coda = [];
    if (S.parlando) { S.parlando = null; taciMio(); }
    ripristinaVoce();
    lasciaWake();
    S.invio = null;
    if (dlg) { S.chiudoIo = true; try { dlg.close(); } catch (e) { dlg.removeAttribute("open"); } S.chiudoIo = false; }
    S.vista = false;
    if (pillola) pillola.hidden = true;
    const m = MOTIVI[S.chiusura] != null ? MOTIVI[S.chiusura] : "Chiamata chiusa.";
    if (m) dici(m, S.chiusura !== "utente");
    if (btn && S.chiusura !== "pagina") requestAnimationFrame(() => { try { btn.focus({ preventScroll: true }); } catch (e) { /* niente */ } });
  }
  function segnaAttivita() {
    S.ultimaAttivita = Date.now();
    if (S.avvisato) { S.avvisato = false; if (N.avviso) N.avviso.hidden = true; }
  }

  // ---------------------------------------------------------------- riconoscimento della voce
  function avviaAscolto() {
    clearTimeout(S.timerRiavvio);
    if (!S.aperta || S.rec || S.parlando || S.coda.length || S.invio) return;
    if (S.micMuto) { imposta("muto"); return; }
    if (document.hidden) return;
    const R = Riconoscimento();
    if (!R) { S.micErrore = NON_DISPONIBILE; imposta("fermo"); return; }
    const r = new R();
    r.lang = "it-IT";
    r.continuous = true;
    r.interimResults = true;
    try { r.maxAlternatives = 1; } catch (e) { /* niente */ }
    S.fissa = ""; S.provv = ""; S.recErrore = ""; S.recRisultato = false;
    r.onresult = (ev) => {
      if (S.rec !== r) return;
      let fissa = "", provv = "";
      const ris = ev.results || [];
      if (window.CCDettato) {                                  // dettato.js: niente ripetizioni su Android (le ipotesi crescono)
        const u = window.CCDettato.unisci(ris);
        fissa = u.fissa; provv = u.provv;
      } else {
        for (let i = 0; i < ris.length; i++) {
          const x = ris[i] && ris[i][0] ? ris[i][0].transcript : "";
          if (ris[i].isFinal) fissa += x; else provv += x;
        }
      }
      S.fissa = fissa.replace(/\s+/g, " ").trim();
      S.provv = provv.replace(/\s+/g, " ").trim();
      if (!S.fissa && !S.provv) return;
      S.recRisultato = true;
      S.riavvii = 0;
      segnaAttivita();
      mostraTu(S.fissa, S.provv);
      imposta("sente");
      clearTimeout(S.timerSilenzio);
      S.timerSilenzio = setTimeout(fineFrase, T().silenzio);
    };
    r.onerror = (ev) => { if (S.rec === r) S.recErrore = (ev && ev.error) || "errore"; };
    r.onend = () => { if (S.rec !== r) return; S.rec = null; dopoFineAscolto(); };
    S.rec = r;
    S.recInizio = Date.now();
    try { r.start(); } catch (e) { S.rec = null; S.recErrore = "avvio"; dopoFineAscolto(); return; }
    if (S.fase !== "sente") imposta("ascolto");
  }
  function fermaAscolto() {
    clearTimeout(S.timerSilenzio);
    clearTimeout(S.timerRiavvio);
    const r = S.rec;
    S.rec = null;
    if (r) { try { r.abort ? r.abort() : r.stop(); } catch (e) { /* già fermo */ } }
  }
  function fineFrase() {
    const testo = (S.fissa + " " + S.provv).replace(/\s+/g, " ").trim();
    if (!testo || !S.aperta) return;
    proponiFrase(testo);
  }
  // Chrome chiude il riconoscimento da solo (silenzio lungo, rete, dopo qualche decina di secondi):
  // lo riavvio, ma se si chiude subito per più di «tettoRiavvii» volte di fila mi fermo e lo dico.
  function dopoFineAscolto() {
    if (!S.aperta) return;
    const errore = S.recErrore;
    const testo = (S.fissa + " " + S.provv).trim();
    if (testo && !S.invio) { clearTimeout(S.timerSilenzio); proponiFrase(testo); return; }
    if (S.conto) return;                                 // una frase aspetta «Invia subito» o «Annulla»
    if (S.parlando || S.coda.length || S.invio || S.micMuto) return;
    if (ERRORI_MIC[errore]) { S.micErrore = ERRORI_MIC[errore]; imposta("fermo"); return; }
    if (document.hidden) return;                         // si riprende quando la pagina torna visibile
    const tempi = T();
    const rapido = !S.recRisultato && Date.now() - S.recInizio < tempi.rapido;
    S.riavvii = rapido ? S.riavvii + 1 : 0;
    if (S.riavvii > tempi.tettoRiavvii) {
      S.micErrore = errore === "network" ? "Il riconoscimento della voce ha bisogno della rete: controlla la connessione, poi tocca il cerchio per riprovare."
        : "Il microfono continua a chiudersi da solo: tocca il cerchio per riprovare.";
      imposta("fermo");
      return;
    }
    imposta("ascolto");
    const attesaMs = rapido ? Math.min(tempi.passoRiavvio * 2 ** (S.riavvii - 1), 4000) : 120;
    S.timerRiavvio = setTimeout(avviaAscolto, attesaMs);
  }
  function mostraTu(def, provv) {
    N.tu.hidden = false;
    N.tuDef.textContent = def ? def + (provv ? " " : "") : "";
    N.tuProvv.textContent = provv || "";
  }
  function impostaMicMuto(si) {
    S.micMuto = !!si;
    if (S.micMuto) {
      fermaAscolto();
      if (S.fase === "ascolto" || S.fase === "sente" || S.fase === "fermo") { S.fissa = ""; S.provv = ""; N.tuProvv.textContent = ""; imposta("muto"); }
    } else {
      S.riavvii = 0; S.micErrore = "";
      if (S.fase === "muto" || S.fase === "fermo") { imposta("ascolto"); avviaAscolto(); }
    }
    disegna();
  }
  function impostaAltMuto(si) {
    S.altMuto = !!si;
    if (S.altMuto && S.parlando) interrompiLettura();
    disegna();
  }
  function toccoAvatar() {
    segnaAttivita();
    if (S.fase === "parla") { interrompiLettura(); return; }
    if (S.fase === "fermo") { S.riavvii = 0; S.micErrore = ""; if (S.micMuto) impostaMicMuto(false); else { imposta("ascolto"); avviaAscolto(); } }
  }

  // ---------------------------------------------------------------- la frase sentita: 2 s per ripensarci
  // (REVISIONE-2, punto 6) La frase non parte subito: un conto alla rovescia di 2 s, con «Annulla» e «Invia
  // subito», letto anche dagli screen reader. Una frase che comincia come un'approvazione («sì approva»,
  // «approvo», «autorizzo»…) non parte da sola e non approva MAI niente: resta testo, la manda solo un tocco
  // su «Invia come messaggio». Le richieste di permesso si decidono solo col tocco su Approva.
  const APPROVAZIONE_A_VOCE = /^\s*(s[iì]\s*,?\s*)?(ok\s*,?\s*)?(approv|autorizz|confermo|via libera|procedi)/i;
  function proponiFrase(testo) {
    fermaAscolto();
    annullaConto(false);
    S.fissa = ""; S.provv = "";
    mostraTu(testo, "");
    segnaAttivita();
    const voceDiApprovazione = APPROVAZIONE_A_VOCE.test(testo);
    const tempo = T().contoInvio;
    S.conto = { testo, fino: Date.now() + tempo, ferma: voceDiApprovazione };
    N.contoTesto.textContent = voceDiApprovazione
      ? "A voce non si approva niente: per un permesso tocca «Approva». Questa frase resta testo."
      : "Mando fra 2 secondi…";
    N.contoSr.textContent = voceDiApprovazione
      ? `Ho sentito: ${testo}. A voce non si approva: la frase non parte da sola.`
      : `Ho sentito: ${testo}. La mando fra 2 secondi. Premi Annulla per fermarla.`;
    N.contoSubito.textContent = voceDiApprovazione ? "Invia come messaggio" : "Invia subito";
    N.conto.hidden = false;
    N.conto.dataset.ferma = voceDiApprovazione ? "1" : "";
    if (voceDiApprovazione) { imposta("fermo"); disegna(); return; }
    S.conto.tick = setInterval(() => {
      if (!S.conto) return;
      const resta = Math.max(0, Math.ceil((S.conto.fino - Date.now()) / 1000));
      N.contoTesto.textContent = resta ? `Mando fra ${resta} ${resta === 1 ? "secondo" : "secondi"}…` : "Mando…";
    }, 200);
    S.conto.timer = setTimeout(() => { const c = S.conto; annullaConto(false); if (c && S.aperta) mandaFrase(c.testo); }, tempo);
  }
  function annullaConto(riparti) {
    const c = S.conto;
    if (c) { clearTimeout(c.timer); clearInterval(c.tick); }
    S.conto = null;
    if (N.conto) { N.conto.hidden = true; N.contoSr.textContent = riparti ? "Annullato: la frase non è partita." : ""; }
    if (riparti && c) { N.tuDef.textContent = c.testo + " (annullato)"; riprendi(); }
  }
  function inviaSubito() { const c = S.conto; annullaConto(false); if (c && S.aperta) mandaFrase(c.testo); }

  // ---------------------------------------------------------------- il messaggio, con lo stesso percorso della chat
  function mandaFrase(testo) {
    fermaAscolto();
    S.fissa = ""; S.provv = "";
    mostraTu(testo, "");
    N.tuDef.textContent = testo;
    segnaAttivita();
    const invia_ = globale("invia"), k = globale("chatCon");
    const campo = $("chiedi-testo");
    if (!invia_ || k == null || !campo) { avvisa("La chat non è pronta: riprova fra un attimo."); riprendi(); return; }
    let t = filoDi(k);
    if (!t && globale("filo")) { try { t = globale("filo")(k); } catch (e) { t = null; } }
    if (t && t.attesa) { adottaLavoro(); avvisa("Jarvis sta ancora lavorando: aspetta la risposta, poi ripeti."); return; }
    const prima = ultimo(t);
    const bozza = campo.value;                       // quello che l'utente aveva scritto a mano resta nel campo
    campo.value = testo;
    let p;
    try { p = invia_(); } catch (e) { p = null; }
    campo.value = bozza;
    const aa = globale("autoAltezza"); if (aa) { try { aa(); } catch (e) { /* niente */ } }
    const t2 = filoDi(k);
    const rif = ultimo(t2);
    if (!rif || rif === prima || rif.chi !== "io") {
      avvisa("Il messaggio non è partito: riprova.");
      riprendi();
      return;
    }
    S.invio = { k, rif, id: null, inviando: true, da: Date.now() };
    S.fermato = false;
    N.attivita.textContent = "";
    imposta("lavora");
    Promise.resolve(p).catch(() => {}).then(() => { if (S.invio && S.invio.rif === rif) { S.invio.inviando = false; S.invio.finito = Date.now(); } });
  }
  // un lavoro già in corso nella chat aperta: lo seguo come se l'avessi mandato io
  function adottaLavoro() {
    const k = globale("chatCon"), t = filoDi(k);
    if (!t || !t.attesa || !t.attesa.id) return false;
    if (S.invio && S.invio.id === t.attesa.id) return true;
    fermaAscolto();
    S.invio = { k, rif: ultimo(t), id: t.attesa.id, inviando: false, da: Date.now() };
    imposta("lavora");
    return true;
  }
  const idLavoro = () => { if (!S.invio) return null; const t = filoDi(S.invio.k); return t && t.attesa ? t.attesa.id : null; };
  function avvisa(testo) { N.avviso.textContent = testo; N.avviso.hidden = false; clearTimeout(avvisa.t); avvisa.t = setTimeout(() => { if (!S.avvisato) N.avviso.hidden = true; }, 6000); }
  function riprendi() {
    if (!S.aperta) return;
    if (S.invio || adottaLavoro()) { imposta("lavora"); return; }
    if (S.micMuto) { imposta("muto"); return; }
    imposta("ascolto");
    avviaAscolto();
  }

  // il giro: segue il lavoro, le attività, la risposta, i tempi
  function giro() {
    if (!S.aperta) return;
    const ora = Date.now();
    if (S.invio) {
      const t = filoDi(S.invio.k);
      if (t && t.attesa) {
        if (S.invio.id !== t.attesa.id) { S.invio.id = t.attesa.id; disegna(); }     // lo Stop si accende subito
        segnaAttivita();
        if (S.fase !== "lavora" && !S.parlando) imposta("lavora");
        mostraAttivita(t.attesa);
      } else if (!S.invio.inviando) {
        const m = ultimo(t);
        if (m && m !== S.invio.rif && m.chi === "lui") rispostaArrivata(m);
        else if (S.invio.finito && ora - S.invio.finito > 4000) {      // niente lavoro e niente risposta: torno in ascolto
          S.invio = null; avvisa("Non è arrivata nessuna risposta: riprova."); riprendi();
        }
      }
    } else if (!S.parlando && !S.coda.length && (S.fase === "ascolto" || S.fase === "muto" || S.fase === "fermo")) {
      adottaLavoro();          // qualcuno ha scritto nella chat a chiamata aperta
    }
    // inattività: 5 minuti senza parlato, risposte o tocchi (un lavoro in corso conta come attività)
    const tempi = T();
    const fermo = ora - S.ultimaAttivita;
    if (fermo >= tempi.inattivita) { chiudi("inattivita"); return; }
    if (fermo >= tempi.avviso && !S.avvisato) {
      S.avvisato = true;
      N.avviso.textContent = "Nessuno parla da un po': chiudo la chiamata fra un minuto. Parla o tocca un pulsante per restare.";
      N.avviso.hidden = false;
      parla("Sei ancora lì? Se non parli chiudo la chiamata fra un minuto.", { sottotitolo: false });
    }
    // permessi: ogni 2 s a pagina visibile; subito se approvazioni.js ne vede uno nuovo
    if (!document.hidden && S.appr.attivo !== false) {
      let nuovo = false;
      try {
        const ids = window.CCApprovazioni && window.CCApprovazioni.stato ? window.CCApprovazioni.stato().in_attesa || [] : [];
        nuovo = ids.some((id) => !S.appr.lista.some((a) => a.id === id) && !S.appr.locale.has(id));
      } catch (e) { /* niente */ }
      if (nuovo || ora - S.appr.ultima >= tempi.sonda) sondaPermessi();
    }
    const sec = Math.floor((ora - S.inizio) / 1000);
    if (sec !== S.ultimoSecondo) { S.ultimoSecondo = sec; disegna(); battitoPermesso(); }
  }
  function mostraAttivita(attesa) {
    let voci = null;
    if (window.CCAttivita && typeof window.CCAttivita.voci === "function") {
      try { voci = window.CCAttivita.voci(attesa.id); } catch (e) { voci = null; }
    } else voci = attivitaDaSolo(attesa.id);
    const v = voci && voci.length ? voci[voci.length - 1] : null;
    const sec = Math.round((Date.now() - (attesa.inizio || Date.now())) / 1000);
    const t = v && v.testo ? corto(v.testo, 70) + (v.esito === "in corso" || !v.esito ? "…" : "") : `sta lavorando da ${sec} s`;
    if (N.attivita.textContent !== t) N.attivita.textContent = t;
  }
  // senza attivita.js: leggo io il lavoro ogni 2 s, solo durante la chiamata
  function attivitaDaSolo(id) {
    const F = S.attFallback;
    if (F.id !== id) { F.id = id; F.voci = []; F.ultima = 0; }
    if (Date.now() - F.ultima >= T().attivitaSonda && !document.hidden) {
      F.ultima = Date.now();
      S.richieste++;
      fetch("/api/lavoro/" + encodeURIComponent(id), { headers: { "X-Token": window.CC_TOKEN || "" }, cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null)).then((d) => { if (d && Array.isArray(d.attivita) && F.id === id) F.voci = d.attivita.slice(-5); }).catch(() => {});
    }
    return F.voci;
  }
  function rispostaArrivata(m) {
    S.invio = null;
    N.attivita.textContent = "";
    segnaAttivita();
    if (S.fermato) { S.fermato = false; parla("Ho fermato il lavoro.", { attivita: true }); return; }
    const testo = m.errore ? "Non ci sono riuscito: " + perVoce(m.testo, 200) : perVoce(m.testo);
    parla(testo || "Ho risposto in chat.", { attivita: true });
  }
  async function stop() {
    if (S.parlando && !idLavoro()) { interrompiLettura(); return; }
    const id = idLavoro();
    if (!id) return;
    taciTutto();
    const az = globale("azione");
    if (!az) return;
    S.fermato = true;
    N.attivita.textContent = "fermo il lavoro…";
    S.richieste++;
    const d = await az({ tipo: "ferma", id }, N.stop);
    if (!d) { S.fermato = false; avvisa("Lo stop non è arrivato: riprova."); }
    disegna();
  }

  // ---------------------------------------------------------------- la voce di Jarvis
  // Durante la chiamata parla solo questo file: l'altoparlante di ponte.js (se acceso) leggerebbe la
  // stessa risposta una seconda volta, e il suo «taci» interromperebbe la nostra lettura.
  function proteggiVoce() {
    const ss = window.speechSynthesis;
    if (!ss || S.voceOrig) return;
    const speak0 = ss.speak, cancel0 = ss.cancel;
    S.voceOrig = { ss, speak: Object.getOwnPropertyDescriptor(ss, "speak"), cancel: Object.getOwnPropertyDescriptor(ss, "cancel") };
    try {
      ss.speak = function (u) { if (mie.has(u)) return speak0.call(ss, u); };
      ss.cancel = function () { if (S.ioCancello) return cancel0.call(ss); };
    } catch (e) { S.voceOrig = null; }
  }
  function ripristinaVoce() {
    const o = S.voceOrig;
    if (!o) return;
    S.voceOrig = null;
    try {
      for (const k of ["speak", "cancel"]) { if (o[k]) Object.defineProperty(o.ss, k, o[k]); else delete o.ss[k]; }
    } catch (e) { /* niente */ }
  }
  function taciMio() {
    S.ioCancello = true;
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) { /* niente */ }
    S.ioCancello = false;
  }
  function vocItaliana() {
    try {
      const voci = window.speechSynthesis.getVoices() || [];
      return voci.find((v) => /^it[-_]IT$/i.test(v.lang || "")) || voci.find((v) => /^it([-_]|$)/i.test(v.lang || "")) || null;
    } catch (e) { return null; }
  }
  // parla(testo): in coda; il microfono si chiude mentre parla e riapre 700 ms dopo
  function parla(testo, opz = {}) {
    if (!testo || !S.aperta) return;
    S.coda.push({ testo, opz });
    if (!S.parlando) prossima();
  }
  function prossima() {
    clearTimeout(S.timerCoda);
    if (!S.aperta) return;
    const x = S.coda.shift();
    if (!x) { riprendi(); return; }
    fermaAscolto();
    if (x.opz.sottotitolo !== false) mostraLui(x.testo);
    const ss = window.speechSynthesis, U = window.SpeechSynthesisUtterance;
    if (S.altMuto || !ss || typeof U !== "function") {
      if (x.opz.sottotitolo !== false) segnaLetto(x.testo.length);
      if (x.opz.attivita) segnaAttivita();
      S.parlando = null;
      S.timerCoda = setTimeout(prossima, S.coda.length ? 400 : 0);
      return;
    }
    let u;
    try { u = new U(x.testo); } catch (e) { S.timerCoda = setTimeout(prossima, 0); return; }
    u.lang = "it-IT";
    u.rate = 1.05;
    const v = vocItaliana();
    if (v) { try { u.voice = v; } catch (e) { /* voce di sistema */ } }
    const sotto = x.opz.sottotitolo !== false;
    let finito = false;
    const fine = () => {
      if (finito) return;
      finito = true;
      clearTimeout(S.timerParla);
      if (S.parlando !== u) return;
      S.parlando = null;
      if (sotto) segnaLetto(x.testo.length);
      if (x.opz.attivita) segnaAttivita();
      // coda per l'eco: il microfono non sente la fine della voce di Jarvis
      S.timerCoda = setTimeout(prossima, T().coda);
    };
    u.onend = fine;
    u.onerror = fine;
    u.onboundary = (ev) => { if (sotto && ev && typeof ev.charIndex === "number") segnaLetto(ev.charIndex + (ev.charLength || 0)); };
    mie.add(u);
    S.parlando = u;
    S.letture.push({ testo: x.testo, lang: u.lang, voce: v ? v.name : null });
    imposta("parla");
    if (sotto) segnaLetto(0);
    // rete di sicurezza: se il browser non dice mai «finito», chiudo io (ma non mentre sta ancora parlando)
    let proroghe = 0;
    const tetto = () => {
      let parlaAncora = false;
      try { parlaAncora = !!window.speechSynthesis.speaking; } catch (e) { /* niente */ }
      if (parlaAncora && proroghe++ < 3) { S.timerParla = setTimeout(tetto, 5000); return; }
      fine();
    };
    S.timerParla = setTimeout(tetto, Math.min(60000, 2500 + x.testo.length * 90));
    try { window.speechSynthesis.speak(u); } catch (e) { fine(); }
  }
  function mostraLui(testo) {
    N.lui.hidden = false;
    N.lui.dataset.testo = testo;
    N.luiSr.textContent = testo;
    segnaLetto(0);
  }
  function segnaLetto(n) {
    const t = N.lui.dataset.testo || "";
    let i = Math.max(0, Math.min(t.length, n));
    if (i < t.length) { const sp = t.indexOf(" ", i); i = sp < 0 ? t.length : sp; }
    N.luiLetto.textContent = t.slice(0, i);
    N.luiResto.textContent = t.slice(i);
  }
  function interrompiLettura() {
    if (!S.parlando) return;
    const testo = N.lui.dataset.testo || "";
    S.parlando = null;
    S.coda = S.coda.filter((x) => x.opz.permesso);       // l'annuncio di un permesso resta
    clearTimeout(S.timerParla);
    taciMio();
    segnaLetto(testo.length);
    S.timerCoda = setTimeout(prossima, Math.min(250, T().coda));
  }
  function taciTutto() { S.coda = []; if (S.parlando) { S.parlando = null; clearTimeout(S.timerParla); taciMio(); } }

  // ---------------------------------------------------------------- permessi: si decidono solo col tocco
  async function sondaPermessi() {
    const A = S.appr;
    if (A.inVolo || A.attivo === false || !S.aperta) return;
    A.inVolo = true;
    A.ultima = Date.now();
    S.richieste++;
    try {
      const r = await fetch("/api/approvazioni", { headers: { "X-Token": window.CC_TOKEN || "" }, cache: "no-store" });
      if (r.status === 404) { A.attivo = false; A.lista = []; disegnaPermesso(); return; }
      if (!r.ok) return;
      const d = await r.json().catch(() => null);
      if (!d || !Array.isArray(d.in_attesa)) return;
      A.attivo = true;
      if (Number.isFinite(d.ora)) A.scarto = d.ora - Date.now() / 1000;
      A.lista = d.in_attesa.filter((a) => a && typeof a.id === "string" && /^[\w-]{1,64}$/.test(a.id) && (a.stato || "attesa") === "attesa")
        .sort((x, y) => (x.creata || 0) - (y.creata || 0));
      disegnaPermesso();
    } catch (e) { /* rete giù: al prossimo giro */ } finally { A.inVolo = false; }
  }
  // il testo di un permesso com'è arrivato: comando, percorso, anteprima (fino a 4000 caratteri in tutto)
  function testoPermesso(d) {
    if (!d || typeof d !== "object") return "";
    const parti = [];
    if (d.comando) parti.push(String(d.comando));
    if (d.percorso) parti.push((d.comando ? "Percorso: " : "") + String(d.percorso));
    if (d.anteprima) parti.push((parti.length ? "Anteprima:\n" : "") + String(d.anteprima));
    const t = parti.join("\n");
    return t.length > 4000 ? t.slice(0, 3999) + "…" : t;
  }
  // il server taglia comando e anteprima a 800 caratteri (con «…») e nasconde le righe con un possibile segreto
  function taglioPermesso(d) {
    if (!d || typeof d !== "object") return "";
    const lunghi = [d.comando, d.anteprima].filter((x) => typeof x === "string");
    const tagliato = d.troncato === true || d.comando_troncato === true || lunghi.some((x) => x.length >= 799 && x.endsWith("…"))
      || testoPermesso(d).length >= 4000;
    const nascosto = lunghi.some((x) => x.includes("[riga nascosta"));
    if (tagliato && nascosto) return "Attenzione: il testo è stato tagliato e alcune righe sono nascoste (sembrano segreti). Quello che non vedi non è controllabile.";
    if (tagliato) return "Attenzione: il testo è stato tagliato, la parte finale non arriva fin qui.";
    if (nascosto) return "Attenzione: alcune righe sono nascoste perché sembrano contenere un segreto.";
    return "";
  }
  function apriTesto() {
    const a = permessoAperto();
    if (!a) return;
    S.appr.aperto.add(a.id);
    S.appr.firma = "";
    disegnaPermesso();
    try { N.pComando.focus({ preventScroll: true }); } catch (e) { /* niente */ }
  }
  // visto = il riquadro è aperto (o non serve aprirlo) e la fine del testo è stata sullo schermo
  function controllaVisto() {
    const A = S.appr, a = permessoAperto();
    if (!a || !N.pComando || N.pComando.hidden) return;
    const c = N.pComando, deveAprire = c.dataset.taglio === "1" || c.scrollHeight > c.clientHeight + 2;
    if (N.pTutto) N.pTutto.hidden = !c.classList.contains("chm-chiuso") || !deveAprire;
    if (A.visto.has(a.id)) return;
    if (c.classList.contains("chm-chiuso") && deveAprire) return;
    if (c.scrollTop + c.clientHeight < c.scrollHeight - 2) return;
    A.visto.add(a.id);
    A.firma = "";
    disegnaPermesso();
  }
  function permessoAperto() {
    const A = S.appr;
    return A.lista.find((a) => { const l = A.locale.get(a.id); return !l || l.fase !== "esito"; }) || null;
  }
  function disegnaPermesso() {
    if (!N.permesso) return;
    const A = S.appr, a = permessoAperto();
    // l'esito appena deciso resta visibile qualche secondo
    const esito = [...A.locale.entries()].find(([, l]) => l.fase === "esito" && l.fino > Date.now());
    if (dlg) dlg.classList.toggle("chm-con-permesso", !!(a || esito));
    if (!a && !esito) { N.permesso.hidden = true; A.firma = ""; disegnaPillola(); return; }
    if (!a && esito) {
      const firma = "esito:" + esito[0] + esito[1].testo;
      if (A.firma !== firma) {
        A.firma = firma;
        N.permesso.hidden = false;
        N.permesso.dataset.rischio = "";
        N.pRiep.textContent = esito[1].riep || "";
        N.pComando.hidden = true; N.pTutto.hidden = true; N.pTaglio.hidden = true;
        N.pNo.hidden = true; N.pSi.hidden = true;
        N.pNota.textContent = esito[1].testo;
        N.pAltre.textContent = "";
      }
      disegnaPillola();
      return;
    }
    const loc = A.locale.get(a.id) || {};
    const conf = A.conferma.has(a.id);
    const altre = A.lista.filter((x) => x !== a && !(A.locale.get(x.id) || {}).fase).length;
    const firma = [a.id, a.rischio, a.riepilogo, loc.fase || "", loc.testo || "", conf ? "c" : "", altre,
      A.visto.has(a.id) ? "v" : "", A.aperto.has(a.id) ? "o" : "", JSON.stringify(a.dettagli || {}).length].join("~");
    if (A.firma !== firma) {
      A.firma = firma;
      const rischio = ["basso", "medio", "alto"].includes(a.rischio) ? a.rischio : "medio";
      N.permesso.hidden = false;
      N.permesso.dataset.rischio = rischio;
      N.pRischio.textContent = { basso: "● Rischio basso", medio: "▲ Rischio medio", alto: "■ Rischio alto" }[rischio];
      N.pRiep.textContent = corto(a.riepilogo || "Jarvis chiede un permesso", 220);
      const d = a.dettagli && typeof a.dettagli === "object" ? a.dettagli : {};
      const dett = testoPermesso(d);
      const taglio = taglioPermesso(d);
      N.pComando.textContent = dett;
      N.pComando.hidden = !dett;
      N.pTaglio.textContent = taglio;
      N.pTaglio.hidden = !taglio;
      // chiuso (poche righe) finché l'utente non apre; un testo tagliato o con righe nascoste va aperto sempre
      const aperto = A.aperto.has(a.id);
      N.pComando.classList.toggle("chm-chiuso", !!dett && !aperto);
      N.pComando.dataset.taglio = taglio ? "1" : "";
      N.pComando.scrollTop = 0;
      N.pNo.hidden = false; N.pSi.hidden = permessoTroncato(a);
      const inviando = loc.fase === "invio";
      const visto = !dett || A.visto.has(a.id);
      N.pNo.disabled = inviando; N.pSi.disabled = inviando || !visto;
      N.pSi.title = visto ? "" : "Leggi la richiesta fino in fondo: Approva si accende dopo";
      N.pSi.textContent = conf ? "Tocca ancora per approvare" : "Approva";
      N.pSi.classList.toggle("chm-conferma", conf);
      N.pSi.setAttribute("aria-label", conf ? "Rischio alto: tocca ancora per approvare davvero" : "Approva: " + corto(a.riepilogo || "", 80));
      N.pNo.setAttribute("aria-label", "Rifiuta: " + corto(a.riepilogo || "", 80));
      N.pNota.textContent = loc.testo || (visto ? "" : taglio ? "Apri «Mostra tutto» e scorri fino in fondo: Approva si accende dopo."
        : "Scorri il testo fino in fondo: Approva si accende dopo.");
      N.pNota.classList.toggle("errore", loc.fase === "errore");
      requestAnimationFrame(controllaVisto);
      N.pAltre.textContent = altre ? (altre === 1 ? "C'è un'altra richiesta dopo questa." : `Ci sono altre ${altre} richieste dopo questa.`) : "";
      if (!A.annunciati.has(a.id)) {
        A.annunciati.add(a.id);
        segnaAttivita();
        // a voce solo l'annuncio, mai i comandi; la decisione resta un tocco
        parla("Jarvis chiede un permesso: " + riepilogoVoce(a) + ".", { sottotitolo: false, permesso: true });
        if (S.vista) requestAnimationFrame(() => { try { N.pNo.focus({ preventScroll: false }); N.permesso.scrollIntoView({ block: "nearest" }); } catch (e) { /* niente */ } });
      }
    }
    disegnaPillola();
  }
  function battitoPermesso() {
    const A = S.appr;
    let cambio = false;
    for (const [id, fino] of A.conferma) if (fino <= Date.now()) { A.conferma.delete(id); cambio = true; }
    for (const [id, l] of A.locale) if (l.fase === "esito" && l.fino <= Date.now()) { A.locale.delete(id); cambio = true; }
    if (cambio) { A.firma = ""; disegnaPermesso(); }
  }
  // revisione 3 dei permessi (2026-10-04, CONTRATTO-registro.md sez. 5): per il rischio alto il server accetta il «sì»
  // solo con un codice monouso chiesto al primo tocco ({fase:"prepara"}, valido 5 s, usabile dopo 800 ms)
  async function preparaSi(id) {
    S.richieste++;
    try {
      const r = await fetch("/api/azione", { method: "POST", cache: "no-store",
        headers: { "X-Token": window.CC_TOKEN || "", "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "approva", id, decisione: "si", fase: "prepara" }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d && typeof d.codice === "string") S.appr.codici.set(id, d.codice);
    } catch (e) { /* il secondo tocco riceverà 428 e lo dirà */ }
  }
  const permessoTroncato = (a) => { const d = a && a.dettagli && typeof a.dettagli === "object" ? a.dettagli : {}; return d.troncato === true || d.comando_troncato === true; };
  async function decidi(decisione) {
    const A = S.appr, a = permessoAperto();
    if (!a) return;
    segnaAttivita();
    if ((A.locale.get(a.id) || {}).fase === "invio") return;
    if (decisione === "si" && permessoTroncato(a)) return;   // revisione 4: comando tagliato, si può solo rifiutare
    if (decisione === "si" && !(!testoPermesso(a.dettagli || {}) || A.visto.has(a.id))) return;   // mai Approva su un testo non visto
    if (decisione === "si" && a.rischio === "alto") {
      const fino = A.conferma.get(a.id) || 0, ora = Date.now();
      if (ora > fino) {                                     // rischio alto: serve un secondo tocco dopo 0,8 s ed entro 5 s
        A.conferma.set(a.id, ora + T().conferma);
        A.primo.set(a.id, ora);
        disegnaPermesso();
        N.pNota.textContent = "Rischio alto: tocca di nuovo «Approva» entro 5 secondi per confermare.";
        preparaSi(a.id);                                  // revisione 3 dei permessi: il server vuole il «sì» in due tempi
        return;
      }
      if (ora - (A.primo.get(a.id) || 0) < T().confermaMin) {   // due tocchi troppo vicini: non vale
        N.pNota.textContent = "Rischio alto: aspetta un istante, poi tocca di nuovo «Approva».";
        return;
      }
      A.conferma.delete(a.id); A.primo.delete(a.id);
    }
    A.locale.set(a.id, { fase: "invio", testo: decisione === "si" ? "Approvo…" : "Rifiuto…" });
    disegnaPermesso();
    const ctl = new AbortController();
    const tetto = setTimeout(() => ctl.abort(), 15000);
    let r, d = {};
    S.richieste++;
    try {
      r = await fetch("/api/azione", { method: "POST", signal: ctl.signal, cache: "no-store",
        headers: { "X-Token": window.CC_TOKEN || "", "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ tipo: "approva", id: a.id, decisione },
          decisione === "si" && A.codici.has(a.id) ? { codice: A.codici.get(a.id) } : {})) });
      d = await r.json().catch(() => ({}));
    } catch (e) {
      clearTimeout(tetto);
      A.locale.set(a.id, { fase: "errore", testo: e.name === "AbortError" ? "Il Command Center non ha risposto entro 15 s: riprova."
        : "Rete assente: la decisione non è partita. Riprova." });
      disegnaPermesso();
      return;
    }
    clearTimeout(tetto);
    A.codici.delete(a.id);
    if (r.status === 428) {                               // «sì» in due tempi non valido: troppo presto, scaduto, senza codice
      A.locale.set(a.id, { fase: "errore", testo: "Conferma non valida (" + corto((d && d.errore) || "serve il secondo tocco", 120) + "): tocca di nuovo «Approva», poi ancora dopo un istante." });
      A.firma = "";
      disegnaPermesso();
      return;
    }
    let testo;
    if (r.ok && d && (d.ok || d.stato)) {
      const st = d.stato || (decisione === "si" ? "approvata" : "rifiutata");
      testo = d.gia_deciso ? `Era già ${st} altrove: niente da fare.` : st === "approvata" ? "Approvato: Jarvis continua." : st === "rifiutata" ? "Rifiutato: Jarvis non lo fa." : "Decisione registrata.";
    } else if (r.status === 404) testo = "Questa richiesta non esiste più: la tolgo.";
    else if (r.status === 409) testo = "Troppo tardi: la richiesta è scaduta e Jarvis ha già ricevuto un rifiuto.";
    else {
      A.locale.set(a.id, { fase: "errore", testo: `Non sono riuscito a mandare la decisione (${d && d.errore ? corto(d.errore, 120) : "errore " + r.status}). Riprova.` });
      disegnaPermesso();
      return;
    }
    A.locale.set(a.id, { fase: "esito", testo, riep: corto(a.riepilogo || "", 220), fino: Date.now() + 3500 });
    A.lista = A.lista.filter((x) => x.id !== a.id);
    A.firma = "";
    disegnaPermesso();
    try { if (window.CCApprovazioni && window.CCApprovazioni.rileggi) window.CCApprovazioni.rileggi(); } catch (e) { /* niente */ }
    setTimeout(sondaPermessi, 600);
  }

  // ---------------------------------------------------------------- pagina in secondo piano, schermo acceso
  function visibilita() {
    if (!S.aperta) return;
    if (document.hidden) {
      clearTimeout(S.timerSfondo);
      S.timerSfondo = setTimeout(() => { if (document.hidden) chiudi("sfondo"); }, T().sfondo);
      fermaAscolto();
    } else {
      clearTimeout(S.timerSfondo);
      prendiWake();
      S.riavvii = 0;
      if (!S.invio && !S.parlando && !S.coda.length && (S.fase === "ascolto" || S.fase === "sente")) avviaAscolto();
    }
  }
  async function prendiWake() {
    if (S.wake || !S.aperta || document.hidden) return;
    try {
      if (!navigator.wakeLock || typeof navigator.wakeLock.request !== "function") return;
      const w = await navigator.wakeLock.request("screen");
      if (!S.aperta) { try { w.release(); } catch (e) { /* niente */ } return; }
      S.wake = w;
      if (w && w.addEventListener) w.addEventListener("release", () => { if (S.wake === w) S.wake = null; });
    } catch (e) { S.wake = null; }
  }
  function lasciaWake() { const w = S.wake; S.wake = null; if (w) { try { w.release(); } catch (e) { /* niente */ } } }

  // ---------------------------------------------------------------- per le prove e per altri script
  window.CCChiamata = {
    attiva: () => S.montato,
    stato: () => ({ montato: S.montato, aperta: S.aperta, vista: S.vista, fase: S.fase, micMuto: S.micMuto, altMuto: S.altMuto,
      riavvii: S.riavvii, richieste: S.richieste, letture: S.letture.slice(), chiusura: S.chiusura, wake: !!S.wake,
      lavoro: S.invio ? S.invio.id : null, permesso: (permessoAperto() || {}).id || null }),
    apri: () => apri(), chiudi: () => chiudi("utente"), perVoce,
  };
})();
