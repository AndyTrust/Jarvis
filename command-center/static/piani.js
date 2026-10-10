// I «Piani» del Command Center (2026-10-04, decisione dell'utente): «decido una volta, poi procede, e una sola conferma
// finale dettagliata». Jarvis scrive il piano (strumenti/piano.py), l'utente lo approva qui UNA volta (si aprono le
// finestre delle Connessioni per i servizi dichiarati), e prima dei passi irreversibili compare la conferma finale
// con i comandi veri. Dati: GET/POST /api/piani. Dal sito (ponte) la rotta non c'è: niente voce, niente richieste.
// Come connessioni.js: si aggancia da sola al menu e a TITOLI. Testi sempre con textContent.
(function piani() {
  "use strict";
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
    const r = await fetch("/api/piani", { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
      body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }
  const ora = (t) => t ? new Date(t * 1000).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) : "";
  const STATI = {
    da_approvare: ["Da approvare", "attenzione"], approvato: ["In corso", "ok"], attesa_finale: ["Conferma finale", "attenzione"],
    concluso: ["Concluso", "grigia"], annullato: ["Fermato", "grigia"], scaduto: ["Scaduto", "grigia"],
  };
  const TIPI = { lettura: "lettura", scrittura: "scrittura", irreversibile: "irreversibile" };

  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="piani"]')) {
      const a = el("a", { href: "#piani", "data-vista": "piani", title: "I piani che Jarvis ti chiede di approvare" },
        el("i", { class: "spia grigia", id: "pi-spia" }), "Piani");
      const prima = menu.querySelector('a[data-vista="connessioni"]') || menu.querySelector('a[data-vista="registro"]');
      if (prima) menu.insertBefore(a, prima); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="piani"]')) {
      const b = el("a", { href: "#piani", "data-vista": "piani" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "☑"),
        el("span", {}, "Piani"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.piani) TITOLI.piani = "Piani"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }
  function segnaAttesa() {
    const aspettano = (S.dati || []).filter((p) => p.stato === "da_approvare" || p.stato === "attesa_finale").length;
    for (const sp of document.querySelectorAll('.menu a[data-vista="piani"] .spia')) sp.className = "spia " + (aspettano ? "attenzione" : "grigia");
  }

  async function azione(id, nome) {
    if (S.occupato) return;
    S.occupato = true; S.errore = ""; disegna();
    try {
      const r = await chiama("POST", { id, azione: nome });
      if (r.stato === 200) S.dati = r.d.piani; else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente: la decisione non è partita."; }
    S.occupato = false; disegna(); segnaAttesa();
  }

  function lista(titolo, voci) {
    return voci && voci.length ? el("p", { class: "pi-riga" }, el("span", { class: "pi-et" }, titolo), el("span", {}, voci.join(", "))) : null;
  }
  function passo(x) {
    const segno = x.stato === "fatto" ? "✓" : x.stato === "saltato" ? "–" : String(x.n);
    return el("li", { class: "pi-passo pi-" + x.tipo + (x.stato !== "da_fare" ? " pi-fatto" : "") },
      el("span", { class: "pi-n", "aria-hidden": "true" }, segno), el("span", { class: "pi-testo" }, x.testo),
      el("span", { class: "pi-tipo" }, TIPI[x.tipo] || x.tipo));
  }
  const bottone = (testo, classe, f) => el("button", { type: "button", class: "pi-btn " + classe, disabled: S.occupato ? "" : null, onclick: f }, testo);

  function scheda(p) {
    const [parola, spia] = STATI[p.stato] || [p.stato, "grigia"];
    const testa = el("div", { class: "pi-testa" }, el("i", { class: "spia " + spia, "aria-hidden": "true" }),
      el("h3", { class: "pi-titolo" }, p.titolo), el("span", { class: "pi-stato" }, parola));
    const corpo = [el("p", { class: "pi-scopo" }, p.scopo),
      lista("Servizi", p.servizi), lista("Cartelle", p.cartelle),
      p.stato === "da_approvare" || p.stato === "approvato" || p.stato === "attesa_finale"
        ? el("p", { class: "pi-riga" }, el("span", { class: "pi-et" }, "Durata"),
          el("span", {}, p.scade ? `${p.durata_min} minuti, fino alle ${ora(p.scade)}` : `${p.durata_min} minuti dall'approvazione`)) : null,
      el("ol", { class: "pi-passi" }, ...p.passi.map(passo)),
      lista("Non tocco", p.non_tocco)];
    const azioni = [];
    if (p.stato === "da_approvare") {
      azioni.push(bottone("Approva il piano", "pi-si", () => azione(p.id, "approva")), bottone("Rifiuta", "pi-no", () => azione(p.id, "rifiuta")));
    } else if (p.stato === "attesa_finale") {
      const finale = el("div", { class: "pi-finale", role: "group", "aria-label": "Conferma finale" },
        el("h4", {}, "Conferma finale: sto per fare, in quest'ordine"),
        el("ol", { class: "pi-cmd" }, ...p.conferma_finale.map((x) => el("li", {}, el("span", {}, x.testo),
          x.comando ? el("pre", { tabindex: "0" }, x.comando) : el("p", { class: "pi-senza" }, "Nessun comando indicato: non lo posso fermare io, decidi sul testo.")))),
        el("p", { class: "pi-nota" }, "Il resto del piano è già stato eseguito. Un solo sì vale per tutti questi passi."));
      corpo.push(finale);
      azioni.push(bottone("Conferma e procedi", "pi-si", () => azione(p.id, "conferma-finale")), bottone("Fermati", "pi-no", () => azione(p.id, "ferma")));
    } else if (p.stato === "approvato") {
      azioni.push(bottone("Ferma il piano", "pi-no", () => azione(p.id, "ferma")));
    }
    if (p.esito) corpo.push(el("p", { class: "pi-esito" }, "Esito: " + p.esito));
    return el("li", { class: "pi-scheda pi-s-" + p.stato }, testa, ...corpo, azioni.length ? el("div", { class: "pi-azioni" }, ...azioni) : null);
  }

  function disegna() {
    if (!N.lista) return;
    N.lista.textContent = "";
    N.errore.textContent = S.errore; N.errore.hidden = !S.errore;
    if (!S.dati) { N.lista.append(el("li", { class: "pi-nota" }, "Carico…")); return; }
    if (!S.dati.length) { N.lista.append(el("li", { class: "pi-nota" }, "Nessun piano. Quando Jarvis ha un lavoro in più passi che tocca servizi, lo scrive qui e aspetta il tuo sì.")); return; }
    for (const p of S.dati) N.lista.append(scheda(p));
  }
  function creaVista() {
    const main = document.querySelector("main");
    if (!main || document.querySelector('section[data-vista="piani"]')) return false;
    N.lista = el("ul", { class: "pi-lista" });
    N.errore = el("p", { class: "pi-errore", role: "alert", hidden: "" });
    N.vista = el("section", { class: "vista vista-piani", "data-vista": "piani", "aria-labelledby": "pi-titolo-pagina" },
      el("div", { class: "pi-intro" }, el("h2", { id: "pi-titolo-pagina", class: "pi-pagina" }, "Piani"),
        el("p", { class: "pi-sotto" }, "Approvi un piano una volta: Jarvis lavora senza chiederti altro, e prima dei passi irreversibili ti mostra cosa sta per fare.")),
      N.errore, N.lista,
      el("p", { class: "pi-nota" }, "Un piano apre le finestre delle Connessioni solo per i servizi dichiarati e per il tempo scelto. Restano fuori: segreti, cancellazioni gravi, push forzati. Si approva solo dal Mac."));
    main.append(N.vista);
    disegna();
    return true;
  }
  async function aggiorna() {
    try {
      const r = await chiama("GET");
      if (r.stato === 200) { S.dati = r.d.piani; S.errore = ""; } else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente."; }
    disegna(); segnaAttesa();
  }
  const attiva = () => location.hash === "#piani" && !document.hidden;
  function cambio() {
    if (attiva() && !S.attivo) { S.attivo = true; aggiorna(); clearInterval(S.timer); S.timer = setInterval(aggiorna, 5000); }
    else if (!attiva() && S.attivo) { S.attivo = false; clearInterval(S.timer); S.timer = null; }
  }
  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let r;
    try { r = await chiama("GET"); } catch (e) { return; }
    if (r.stato !== 200) return;                    // dal sito o con un server vecchio: niente voce, niente richieste
    S.dati = r.d.piani;
    creaVoceMenu();
    if (!creaVista()) return;
    segnaAttesa();
    setInterval(() => { if (!S.attivo) aggiorna(); }, 30000);   // il pallino «in attesa» si aggiorna anche a pagina chiusa
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    if (location.hash === "#piani" && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
  })();
})();
