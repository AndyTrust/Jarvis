// Attività in diretta nella chat (2026-10-03, contratto in command-center/CONTRATTO-approvazioni.md, sezione 2).
//
// Al posto dei tre puntini «sta scrivendo» la bolla del lavoro in corso mostra cosa sta facendo
// Jarvis adesso: «leggo posta.py», «lancio il giro Odoo»… con un'icona per tipo (con la parola per
// i lettori di schermo), l'esito (in corso / ok / errore) e l'ultima voce evidenziata. Si vedono le
// ultime 3; «mostra tutte» apre l'elenco intero (max 50, quelle che manda il server).
//
// Da dove arrivano i dati, senza chiamate in più:
//  - app.js segue già il lavoro con api("/api/lavoro/<id>") ogni 1,5 s (seguiRisposte): avvolgo
//    window.api e leggo il campo «attivita» delle risposte (il resto passa intatto);
//  - l'evento SSE «attivita» {lavoro_id, voce} sul flusso di app.js (FLUSSO.es);
//  - se app.js non espone api(), leggo io /api/lavoro/<id> ogni 2 s, solo per la chat aperta.
// Backend vecchio (nessun campo «attivita»): resta la bolla di prima, nessun errore.
// Al massimo una voce nuova ogni 250 ms: niente tremolii quando ne arrivano dieci insieme.
// Testi sempre con textContent.
(function attivita() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const TIPI = {
    leggo: { segno: "◧", parola: "Lettura" }, scrivo: { segno: "✎", parola: "Scrittura" },
    lancio: { segno: "▶", parola: "Comando" }, cerco: { segno: "⌕", parola: "Ricerca" },
    web: { segno: "◍", parola: "Web" }, agente: { segno: "◉", parola: "Agente" }, penso: { segno: "…", parola: "Ragiono" },
  };
  const ESITI = { "in corso": "in corso", ok: "fatto", errore: "errore" };
  const CHIUSE = 3, PASSO_MS = 250, MAX_RITARDO = 10;
  const L = new Map();               // lavoroId -> { voci: [], mostrate, aperto, nodo, sporco, ultimaLettura }
  let esFlusso = null;

  const G = {
    FLUSSO: () => (typeof FLUSSO !== "undefined" ? FLUSSO : undefined),          // eslint-disable-line no-undef
    THREADS: () => (typeof THREADS !== "undefined" ? THREADS : undefined),       // eslint-disable-line no-undef
    chatCon: () => (typeof chatCon !== "undefined" ? chatCon : undefined),       // eslint-disable-line no-undef
  };
  const globale = (n) => { try { return G[n](); } catch (e) { return undefined; } };

  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, String(v));
    }
    for (const f of figli) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  const corto = (s, max) => { s = String(s == null ? "" : s); return s.length > max ? s.slice(0, max - 1) + "…" : s; };
  const chiave = (v) => `${v.ts}|${v.tipo}|${v.testo}`;
  const lavoroAperto = () => {
    const T = globale("THREADS"), k = globale("chatCon");
    return T && k && T[k] && T[k].attesa ? T[k].attesa.id : null;
  };
  function di(id) {
    if (!L.has(id)) L.set(id, { voci: [], mostrate: 0, aperto: false, nodo: null, sporco: true });
    return L.get(id);
  }
  const voceValida = (v) => v && typeof v === "object" && v.testo != null;

  // ---------------------------------------------------------------- ingressi
  function riceviLavoro(id, d) {
    if (!d || !Array.isArray(d.attivita)) return;          // backend vecchio: niente
    const x = di(id);
    const prima = new Map(x.voci.map((v) => [chiave(v), v]));
    const nuove = [];
    for (const v of d.attivita.slice(-50)) {
      if (!voceValida(v)) continue;
      const k = chiave(v), vecchia = prima.get(k);
      if (vecchia) { if (vecchia.esito !== v.esito) { vecchia.esito = v.esito; x.sporco = true; } nuove.push(vecchia); }
      else nuove.push({ ts: v.ts, tipo: v.tipo, testo: v.testo, esito: v.esito });
    }
    // l'elenco del server è la verità; tengo l'ordine per tempo
    nuove.sort((a, b) => (a.ts || 0) - (b.ts || 0));
    if (nuove.length !== x.voci.length || nuove.some((v, i) => v !== x.voci[i])) {
      const quanteGiaViste = x.voci.slice(0, x.mostrate).filter((v) => nuove.includes(v)).length;
      x.voci = nuove;
      x.mostrate = Math.min(quanteGiaViste, nuove.length);
      x.sporco = true;
    }
  }
  function riceviVoce(dati) {
    let d;
    try { d = typeof dati === "string" ? JSON.parse(dati) : dati; } catch (e) { return; }
    if (!d || !d.lavoro_id || !voceValida(d.voce)) return;
    const x = di(String(d.lavoro_id)), v = d.voce, k = chiave(v);
    const c = x.voci.find((w) => chiave(w) === k);
    if (c) { if (c.esito !== v.esito) { c.esito = v.esito; x.sporco = true; } return; }
    // una voce «in corso» dello stesso tipo e testo che si chiude arriva con lo stesso ts: già gestita sopra
    x.voci.push({ ts: v.ts, tipo: v.tipo, testo: v.testo, esito: v.esito });
    x.voci.sort((a, b) => (a.ts || 0) - (b.ts || 0));
    if (x.voci.length > 50) { const via = x.voci.length - 50; x.voci.splice(0, via); x.mostrate = Math.max(0, x.mostrate - via); }
    x.sporco = true;
  }

  // avvolgo api() di app.js: è una dichiarazione di funzione di uno script classico, quindi sta su
  // window e le chiamate interne di app.js passano da qui. Se qualcosa va storto qui dentro, la
  // risposta torna comunque intatta a chi l'ha chiesta.
  let avvolta = false;
  function avvolgiApi() {
    if (avvolta || typeof window.api !== "function" || window.api.__attivita) return avvolta;
    const originale = window.api;
    const nuova = async function (percorso, corpo) {
      const d = await originale.apply(this, arguments);
      try {
        if (!corpo && typeof percorso === "string") {
          const m = percorso.match(/^\/api\/lavoro\/([\w.-]+)$/);
          if (m && d && Array.isArray(d.attivita)) riceviLavoro(m[1], d);
          if (m && d && d.stato && d.stato !== "in corso") L.delete(m[1]);
        }
      } catch (e) { /* mai rompere api() */ }
      return d;
    };
    nuova.__attivita = true;
    window.api = nuova;
    avvolta = window.api === nuova;
    return avvolta;
  }
  // ripiego: app.js senza api() globale. Leggo io, solo il lavoro della chat aperta, ogni 2 s.
  let ultimaLettura = 0;
  async function leggiDaSolo() {
    if (avvolta || Date.now() - ultimaLettura < 2000 || document.hidden) return;
    const id = lavoroAperto();
    if (!id) return;
    ultimaLettura = Date.now();
    try {
      const r = await fetch("/api/lavoro/" + encodeURIComponent(id), { headers: { "X-Token": window.CC_TOKEN || "" }, cache: "no-store" });
      if (!r.ok) return;
      riceviLavoro(id, await r.json());
    } catch (e) { /* rete giù: al prossimo giro */ }
  }
  // stesso aggancio di approvazioni.js (costruttore di EventSource avvolto una volta sola, chi arriva
  // secondo si iscrive e basta) più FLUSSO.es per un flusso aperto prima di questo file
  const agganciati = new WeakSet();
  function ascolta(es) {
    if (!es || agganciati.has(es)) return;
    agganciati.add(es);
    es.addEventListener("attivita", (ev) => riceviVoce(ev.data));
  }
  (function suFlusso(fn) {
    const H = window.__ccFlusso || (window.__ccFlusso = { fns: [], aperti: [] });
    if (!H.avvolto && typeof window.EventSource === "function") {
      H.avvolto = true;
      const Originale = window.EventSource;
      class EventSourceCC extends Originale {
        constructor(url, conf) {
          super(url, conf);
          try {
            if (/\/api\/flusso(\?|$)/.test(String(url))) {
              H.aperti = H.aperti.filter((e) => e.readyState !== 2).concat(this);
              for (const f of H.fns) { try { f(this); } catch (e) { /* niente */ } }
            }
          } catch (e) { /* niente */ }
        }
      }
      window.EventSource = EventSourceCC;
    }
    H.fns.push(fn);
    for (const es of H.aperti) if (es.readyState !== 2) { try { fn(es); } catch (e) { /* niente */ } }
  })(ascolta);
  function agganciaFlusso() {
    const F = globale("FLUSSO");
    if (F && F.es && F.es !== esFlusso) { esFlusso = F.es; ascolta(F.es); }
  }

  // ---------------------------------------------------------------- disegno
  function bolla() {
    const box = $("messaggi");
    const dur = box && box.querySelector("#durata-attesa");
    return dur ? dur.closest(".msg") : null;
  }
  function riga(v, ultima) {
    const t = TIPI[v.tipo] || { segno: "•", parola: String(v.tipo || "Attività") };
    const esito = ESITI[v.esito] ? v.esito : "in corso";
    const quando = v.ts ? new Date(v.ts * 1000).toLocaleTimeString("it-IT") : "";
    return el("li", { class: "atv-voce atv-e-" + (esito === "in corso" ? "corso" : esito) + (ultima ? " atv-ultima" : ""), title: quando || null },
      el("span", { class: "atv-ico", "aria-hidden": "true" }, t.segno),
      el("span", { class: "atv-sr" }, t.parola + ": "),
      el("span", { class: "atv-testo" }, corto(v.testo, 120)),
      el("span", { class: "atv-esito" },
        esito === "in corso" ? el("i", { class: "atv-gira", "aria-hidden": "true" }) : el("span", { "aria-hidden": "true" }, esito === "ok" ? "✓" : "✕"),
        el("span", { class: "atv-sr" }, " (" + ESITI[esito] + ")")));
  }
  function disegna(id) {
    const x = L.get(id), b = bolla();
    if (!b) return;
    const corpo = b.querySelector(".corpo") || b;
    if (!x || !x.mostrate) {
      corpo.classList.remove("atv-con");
      if (x && x.nodo) x.nodo.remove();
      return;
    }
    if (!x.nodo) {
      // elenco e pulsante restano gli stessi elementi: si cambia solo il contenuto (un tocco non va perso)
      x.lista = el("ol", { class: "atv-lista", "aria-label": "Cosa sta facendo Jarvis" });
      x.tutto = el("button", { type: "button", class: "atv-tutto", "aria-expanded": "false",
        onclick: () => { x.aperto = !x.aperto; x.sporco = true; disegna(id); } });
      x.nodo = el("div", { class: "atv", "aria-live": "off" }, x.lista, x.tutto);
    }
    const viste = x.voci.slice(0, x.mostrate);
    const elenco = x.aperto ? viste : viste.slice(-CHIUSE);
    x.lista.replaceChildren(...elenco.map((v, i) => riga(v, i === elenco.length - 1)));
    x.tutto.hidden = viste.length <= CHIUSE;
    x.tutto.setAttribute("aria-expanded", x.aperto ? "true" : "false");
    x.tutto.textContent = x.aperto ? "mostra solo le ultime" : `mostra tutte (${viste.length})`;
    if (x.nodo.parentNode !== corpo) {
      const dopo = corpo.querySelector(".bolla-scrive");
      if (dopo) dopo.after(x.nodo); else corpo.append(x.nodo);
    }
    corpo.classList.add("atv-con");
    const box = $("messaggi");
    if (box && box.scrollHeight - box.scrollTop - box.clientHeight < 140) box.scrollTop = box.scrollHeight;
  }

  // ogni 250 ms al massimo una voce nuova in vista
  function passo() {
    agganciaFlusso();
    if (!avvolta) avvolgiApi();
    leggiDaSolo();
    const id = lavoroAperto();
    if (!id) return;
    const x = L.get(id);
    if (!x) return;
    if (x.mostrate < x.voci.length) {
      if (x.voci.length - x.mostrate > MAX_RITARDO) x.mostrate = x.voci.length - MAX_RITARDO;
      x.mostrate++;
      x.sporco = true;
    }
    const b = bolla();
    const fuori = x.nodo && b && !b.contains(x.nodo);       // la chat è stata ridisegnata: rimetto l'elenco
    if (x.sporco || fuori || (b && x.mostrate && !x.nodo)) { x.sporco = false; disegna(id); }
  }

  function avvio() {
    avvolgiApi();
    setInterval(passo, PASSO_MS);
    const box = $("messaggi");
    if (box) new MutationObserver(() => { const id = lavoroAperto(); if (id && L.has(id)) disegna(id); }).observe(box, { childList: true });
    // i lavori chiusi da tempo non servono più
    setInterval(() => {
      const T = globale("THREADS") || {};
      const vivi = new Set(Object.values(T).map((t) => t && t.attesa && t.attesa.id).filter(Boolean));
      for (const id of L.keys()) if (!vivi.has(id)) L.delete(id);
    }, 60000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvio); else avvio();

  window.CCAttivita = { avvolta: () => avvolta, voci: (id) => ((L.get(id) || {}).voci || []).slice() };
})();
