// Le «Connessioni» del Command Center (2026-10-04, decisione dell'utente): ogni servizio che Jarvis può usare ha tre
// posizioni, «Consentito», «Chiedi prima», «Spento». Valgono anche con il bypass dei permessi: le fa rispettare
// l'hook ~/.claude/hooks/connessioni_guardia.py leggendo ~/.locale-onedrive/jarvis-cc/connessioni.json.
// Dati: GET/POST /api/connessioni (server.py → strumenti/connessioni.py). Dal sito (ponte) la rotta non c'è:
// all'avvio chiede GET /api/connessioni e, se non risponde 200, non crea né la voce né la vista.
// Come registro.js: si aggancia da sola al menu e a TITOLI, senza toccare app.js. Testi sempre con textContent.
(function connessioni() {
  "use strict";
  const POSIZIONI = [["consentito", "Consentito"], ["chiedi", "Chiedi prima"], ["spento", "Spento"]];
  const S = { dati: null, errore: "", occupato: false, timer: null, attivo: false };
  const N = {};
  const token = () => window.CC_TOKEN || "";
  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, String(v));
    }
    for (const f of figli) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  async function chiama(metodo, corpo) {
    const r = await fetch("/api/connessioni", { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
      body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }
  const quando = (t) => {
    if (!t) return "mai";
    const d = new Date(t * 1000), oggi = new Date();
    const hm = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === oggi.toDateString() ? "oggi " + hm : d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }) + " " + hm;
  };

  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="connessioni"]')) {
      const a = el("a", { href: "#connessioni", "data-vista": "connessioni", title: "Cosa può usare Jarvis senza chiederti ogni volta" },
        el("i", { class: "spia grigia" }), "Connessioni");
      const prima = menu.querySelector('a[data-vista="registro"]') || menu.querySelector('a[data-vista="memoria"]');
      if (prima) menu.insertBefore(a, prima.nextSibling); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="connessioni"]')) {
      const b = el("a", { href: "#connessioni", "data-vista": "connessioni" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "⇄"),
        el("span", {}, "Connessioni"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.connessioni) TITOLI.connessioni = "Connessioni"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }

  async function imposta(id, stato) {
    if (S.occupato) return;
    S.occupato = true; S.errore = ""; disegna();
    try {
      const r = await chiama("POST", { id, stato });
      if (r.stato === 200) S.dati = r.d; else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente: la modifica non è partita."; }
    S.occupato = false; disegna();
  }
  async function finestra(id, azione) {
    if (S.occupato) return;
    S.occupato = true; S.errore = ""; disegna();
    try {
      const r = await chiama("POST", azione === "apri" ? { id, via_minuti: 30 } : { id, chiudi: true });
      if (r.stato === 200) S.dati = r.d; else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente: la modifica non è partita."; }
    S.occupato = false; disegna();
  }

  function riga(s) {
    const gruppo = el("div", { class: "cn-tre", role: "radiogroup", "aria-label": "Posizione di " + s.nome });
    for (const [chiave, testo] of POSIZIONI) {
      const attivo = s.stato === chiave;
      gruppo.append(el("button", { type: "button", role: "radio", "aria-checked": attivo ? "true" : "false",
        class: "cn-pos cn-pos-" + chiave + (attivo ? " cn-attiva" : ""), disabled: S.occupato ? "" : null,
        onclick: () => { if (!attivo) imposta(s.id, chiave); } }, testo));
    }
    const extra = [];
    if (s.stato === "chiedi") {
      extra.push(s.finestra_fino
        ? el("button", { type: "button", class: "cn-mini", onclick: () => finestra(s.id, "chiudi") },
          "Finestra aperta fino alle " + new Date(s.finestra_fino * 1000).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) + " · chiudi")
        : el("button", { type: "button", class: "cn-mini", onclick: () => finestra(s.id, "apri") }, "Apri 30 minuti"));
    }
    return el("li", { class: "cn-riga cn-s-" + s.stato },
      el("div", { class: "cn-nome" }, el("i", { class: "spia " + (s.stato === "consentito" ? "ok" : s.stato === "chiedi" ? "attenzione" : "grigia"), "aria-hidden": "true" }),
        el("b", {}, s.nome), el("span", { class: "cn-uso" }, "ultimo uso: " + quando(s.ultimo_uso))),
      el("div", { class: "cn-destra" }, gruppo, ...extra));
  }

  function disegna() {
    if (!N.lista) return;
    N.lista.textContent = "";
    const d = S.dati;
    if (!d) { N.lista.append(el("li", { class: "cn-nota" }, "Carico…")); return; }
    for (const s of d.servizi) N.lista.append(riga(s));
    N.errore.textContent = S.errore;
    N.errore.hidden = !S.errore;
    N.nota.textContent = d.creato ? "" : "Il file delle connessioni non c'è ancora: valgono le impostazioni di partenza (tutto «Chiedi prima»). Si crea al primo cambio.";
    N.nota.hidden = !!d.creato;
  }

  function creaVista() {
    const main = document.querySelector("main");
    if (!main || document.querySelector('section[data-vista="connessioni"]')) return false;
    N.lista = el("ul", { class: "cn-lista" });
    N.errore = el("p", { class: "cn-errore", role: "alert", hidden: "" });
    N.nota = el("p", { class: "cn-nota", hidden: "" });
    N.vista = el("section", { class: "vista vista-connessioni", "data-vista": "connessioni", "aria-labelledby": "cn-titolo" },
      el("div", { class: "cn-testa" }, el("h2", { id: "cn-titolo", class: "cn-titolo" }, "Connessioni"),
        el("p", { class: "cn-sotto" }, "Decidi cosa può usare Jarvis senza chiederti ogni volta.")),
      N.errore, N.nota, N.lista,
      el("p", { class: "cn-fisso" }, "Restano sempre fuori da qui: segreti, cancellazioni gravi, push forzati. Non si sbloccano da questa pagina."),
      el("p", { class: "cn-fisso" }, "«Chiedi prima»: con il bypass Jarvis si ferma e ti scrive cosa sta per fare; dopo il tuo sì apre una finestra di 30 minuti. Si cambia solo dal Mac."));
    main.append(N.vista);
    disegna();
    return true;
  }

  async function aggiorna() {
    try {
      const r = await chiama("GET");
      if (r.stato === 200) { S.dati = r.d; S.errore = ""; } else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente."; }
    disegna();
  }
  const attiva = () => location.hash === "#connessioni" && !document.hidden;
  function cambio() {
    if (attiva() && !S.attivo) { S.attivo = true; aggiorna(); clearInterval(S.timer); S.timer = setInterval(aggiorna, 15000); }
    else if (!attiva() && S.attivo) { S.attivo = false; clearInterval(S.timer); S.timer = null; }
  }

  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let r;
    try { r = await chiama("GET"); } catch (e) { return; }
    if (r.stato !== 200) return;                    // dal sito o con un server vecchio: niente voce, niente richieste
    S.dati = r.d;
    creaVoceMenu();
    if (!creaVista()) return;
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    if (location.hash === "#connessioni" && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
  })();
})();
