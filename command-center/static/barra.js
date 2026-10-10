// La barra in alto del Command Center (2026-10-04, disegno approvato dall'utente): le voci scelte stanno nella barra,
// il resto in «Altro ▾»; ✎ apre la modalità Modifica (maniglia ⋮⋮ per trascinare, ↑ ↓ da tastiera, «in barra / in Altro»).
// Dati: GET/POST /api/menu (server.py → menu_barra.py, file ~/.locale-onedrive/jarvis-cc/menu-barra.json).
// All'avvio chiede GET /api/menu: se non risponde 200 (per esempio dentro il ponte) non fa niente e la barra resta com'è.
// Le voci restano <a href="#…" data-vista="…"> dentro .menu (app.js ci mette la classe «attiva»); «Altro» e la sua tendina stanno dentro .menu.
// Altri script creano le loro voci dopo (registro, connessioni, piani, incarichi, computer): un MutationObserver le
// rimette in ordine; le voci che il file non conosce vanno in «Altro», in coda. Sul telefono la barra in alto è nascosta
// da mobile.css e la barra in basso / il foglio «Altro» li costruisce mobile.js: qui non si toccano. Testi con textContent.
(function barra() {
  "use strict";
  const menu = document.querySelector(".schede.menu");
  if (!menu) return;
  const ID = /^[a-z0-9-]{1,30}$/;
  const PARTENZA = {
    ordine: ["chat", "lavagna", "agenti", "home", "missioni", "incarichi", "piani",
      "scadenze", "registro", "memoria", "connessioni", "computer", "telefono"],
    in_barra: ["chat", "lavagna", "agenti", "home", "missioni", "incarichi", "piani"],
  };
  // 2026-10-05 (l'utente): pagine unite. Un menu-barra.json salvato prima può avere le voci vecchie: diventano «computer»
  // (al posto della prima che si incontra, in barra se una di loro lo era) o spariscono (tecnico sta in «telefono»).
  const UNITE = { server: "computer", vps: "computer", terminale: "computer", schermo: "computer", tecnico: "telefono" };
  function aggiornaVoci(ordine, inBarra) {
    const nuovo = [], barra = new Set();
    for (const id of ordine) {
      const n = UNITE[id] || id;
      if (!nuovo.includes(n)) nuovo.push(n);
      if (inBarra.includes(id)) barra.add(n);
    }
    return { ordine: nuovo, inBarra: barra };
  }
  const S = { ordine: [], inBarra: new Set(), aperto: false, modifica: false, occupato: false, errore: "", drag: null };
  const N = {};
  const token = () => window.CC_TOKEN || "";
  const inserisci = Node.prototype.insertBefore;
  let osservatore = null;

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
    const r = await fetch("/api/menu", { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
      body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }

  // ---------------------------------------------------------------- le voci e il loro posto
  const nomeVoce = (a) => [...a.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim() || a.dataset.vista;
  // 2026-10-05 (l'utente: «in Altro mancano pagine che vedo in Modifica»): barra, «Altro» e Modifica leggono questa sola lista.
  // Una voce che un foglio di stile nasconde (prima del 2026-10-05 mobile.css dentro il ponte: Terminale, VPS, Tecnico) non
  // conta: non sta né in «Altro» né in Modifica. Un doppione (stesso data-vista) prende la classe bm-doppione e sparisce.
  const nascosta = (a) => a.hidden || getComputedStyle(a).display === "none";
  function vociPresenti() {           // id -> <a>: una voce per pagina, solo quelle che si possono vedere
    const m = new Map();
    for (const a of menu.querySelectorAll("a[data-vista]")) {
      const id = a.dataset.vista;
      const doppione = m.has(id);
      if (a.classList.contains("bm-doppione") !== doppione) a.classList.toggle("bm-doppione", doppione);
      if (!doppione && !nascosta(a)) m.set(id, a);
    }
    return m;
  }
  function conosci(presenti) {          // le voci nuove entrano nel modello in coda, in «Altro»
    for (const id of presenti.keys()) if (ID.test(id) && !S.ordine.includes(id) && S.ordine.length < 40) S.ordine.push(id);
  }
  function gruppi(presenti) {
    const barra = [], altro = [];
    for (const id of S.ordine) if (presenti.has(id)) (S.inBarra.has(id) ? barra : altro).push(id);
    for (const id of presenti.keys()) if (!S.ordine.includes(id)) altro.push(id);   // id fuori regola: in Altro, mai salvati
    return { barra, altro };
  }
  function metti(genitore, nodi) {     // sposta solo se l'ordine non è già quello: niente mutazioni inutili
    const ora = [...genitore.children].filter((c) => nodi.includes(c));
    if (ora.length === nodi.length && ora.every((c, i) => c === nodi[i])) return;
    for (const n of nodi) inserisci.call(genitore, n, null);
  }
  function riordina() {
    if (osservatore) osservatore.disconnect();
    try {
      const presenti = vociPresenti();
      conosci(presenti);
      const g = gruppi(presenti);
      metti(menu, [...g.barra.map((id) => presenti.get(id)), N.altro, N.matita, N.pop]);
      metti(N.pop, g.altro.map((id) => presenti.get(id)));
      N.altro.hidden = !g.altro.length;
      if (!g.altro.length) chiudi(false);
      evidenzia();
      if (S.modifica) disegnaModifica();
    } finally {
      if (osservatore) { osservatore.takeRecords(); osservatore.observe(menu, OSSERVA); }
    }
  }
  function evidenzia() {
    const dentro = !!N.pop.querySelector("a.attiva");
    if (N.bAltro.classList.contains("attiva") !== dentro) N.bAltro.classList.toggle("attiva", dentro);
    const a = N.pop.querySelector("a.attiva");
    const testo = a ? "Altro: " + nomeVoce(a) : "Altre pagine";
    if (N.bAltro.title !== testo) N.bAltro.title = testo;
  }
  const OSSERVA = { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] };
  function osserva(lista) {
    let serve = false, classe = false;
    for (const m of lista) {
      if (m.type === "attributes") { if (m.target.matches && m.target.matches("a[data-vista]")) classe = true; continue; }
      for (const n of m.addedNodes) if (n.nodeType === 1 && (n.matches("a[data-vista]") || n.querySelector("a[data-vista]"))) serve = true;
      for (const n of m.removedNodes) if (n === N.altro || n === N.matita || n === N.pop) serve = true;
    }
    if (serve) riordina(); else if (classe) evidenzia();
  }

  // ---------------------------------------------------------------- «Altro ▾»
  function posiziona() {
    const r = N.bAltro.getBoundingClientRect();
    N.pop.style.top = Math.round(r.bottom + 4) + "px";
    const larg = N.pop.offsetWidth || 200;
    N.pop.style.left = Math.round(Math.max(8, Math.min(r.left, window.innerWidth - larg - 8))) + "px";
  }
  function apri(fuoco) {
    if (S.aperto) return;
    S.aperto = true; N.pop.hidden = false; N.bAltro.setAttribute("aria-expanded", "true"); posiziona();
    if (fuoco) { const a = N.pop.querySelector("a.attiva") || N.pop.querySelector("a"); if (a) a.focus(); }
  }
  function chiudi(fuoco) {
    if (!S.aperto) return;
    S.aperto = false; N.pop.hidden = true; N.bAltro.setAttribute("aria-expanded", "false");
    if (fuoco) N.bAltro.focus();
  }
  function tastiPop(e) {
    const voci = [...N.pop.querySelectorAll("a[data-vista]")];
    const i = voci.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); chiudi(true); }
    else if (e.key === "ArrowDown") { e.preventDefault(); (voci[i + 1] || voci[0]).focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (voci[i - 1] || voci[voci.length - 1]).focus(); }
    else if (e.key === "Home") { e.preventDefault(); voci[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); voci[voci.length - 1].focus(); }
    else if (e.key === "Tab") chiudi(false);
  }

  // ---------------------------------------------------------------- salvataggio
  function istantanea() { return { ordine: [...S.ordine], inBarra: new Set(S.inBarra) }; }
  async function salva(prima) {
    S.occupato = true; S.errore = "";
    riordina();
    let msg = "";
    try {
      const r = await chiama("POST", { ordine: S.ordine.filter((id) => ID.test(id)), in_barra: S.ordine.filter((id) => S.inBarra.has(id)) });
      if (r.stato === 200 && Array.isArray(r.d.ordine)) { S.ordine = r.d.ordine; S.inBarra = new Set(r.d.in_barra || []); }
      else msg = "La barra non è stata salvata: " + (r.d.errore || "errore " + r.stato) + ". Torna com'era.";
    } catch (e) { msg = "Rete assente: la barra non è stata salvata. Torna com'era."; }
    if (msg) {
      S.ordine = prima.ordine; S.inBarra = prima.inBarra; S.errore = msg;
      try { if (typeof toast === "function") toast(msg, true); } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
    }
    S.occupato = false;
    riordina();
  }
  // nuova disposizione delle voci visibili; quelle non presenti nella pagina restano al loro posto in «ordine»
  function applica(barra, altro, fuoco) {
    const prima = istantanea();
    const presenti = vociPresenti();
    const visibili = [...barra, ...altro];
    let k = 0;
    const nuovo = S.ordine.map((id) => (presenti.has(id) ? visibili[k++] : id));
    while (k < visibili.length) nuovo.push(visibili[k++]);
    const inB = new Set(barra);
    for (const id of S.inBarra) if (!presenti.has(id)) inB.add(id);
    S.ordine = nuovo.filter((id) => ID.test(id)); S.inBarra = inB; S.fuoco = fuoco || null;
    salva(prima);
  }
  function sposta(id, verso) {
    const g = gruppi(vociPresenti());
    const lista = S.inBarra.has(id) ? g.barra : g.altro;
    const i = lista.indexOf(id), j = i + verso;
    if (i < 0 || j < 0 || j >= lista.length) return;
    [lista[i], lista[j]] = [lista[j], lista[i]];
    applica(g.barra, g.altro, { id, azione: verso < 0 ? "su" : "giu" });
  }
  function scambia(id) {
    const g = gruppi(vociPresenti());
    if (S.inBarra.has(id)) { g.barra.splice(g.barra.indexOf(id), 1); g.altro.unshift(id); }
    else { g.altro.splice(g.altro.indexOf(id), 1); g.barra.push(id); }
    applica(g.barra, g.altro, { id, azione: "lista" });
  }
  function partenza() {
    const prima = istantanea();
    const extra = S.ordine.filter((id) => !PARTENZA.ordine.includes(id));
    S.ordine = [...PARTENZA.ordine, ...extra]; S.inBarra = new Set(PARTENZA.in_barra); S.fuoco = null;
    salva(prima);
  }

  // ---------------------------------------------------------------- modalità Modifica
  function riga(id, a, inBarra, i, quanti) {
    const nome = nomeVoce(a);
    return el("li", { class: "bm-riga", "data-id": id },
      el("span", { class: "bm-maniglia", "aria-hidden": "true", title: "Trascina per spostare", onpointerdown: (e) => iniziaDrag(e, id) }, "⋮⋮"),
      el("span", { class: "bm-nome" }, nome),
      el("button", { type: "button", class: "bm-mini", "data-bm": "su", "aria-label": "Sposta " + nome + " su", disabled: i === 0 || S.occupato ? "" : null,
        onclick: () => sposta(id, -1) }, "↑"),
      el("button", { type: "button", class: "bm-mini", "data-bm": "giu", "aria-label": "Sposta " + nome + " giù", disabled: i === quanti - 1 || S.occupato ? "" : null,
        onclick: () => sposta(id, 1) }, "↓"),
      el("button", { type: "button", class: "bm-dove" + (inBarra ? " bm-in-barra" : ""), "data-bm": "lista", role: "switch", "aria-checked": inBarra ? "true" : "false",
        "aria-label": nome + " in barra", disabled: S.occupato ? "" : null, onclick: () => scambia(id) }, inBarra ? "in barra" : "in Altro"));
  }
  function disegnaModifica() {
    if (!N.pannello) return;
    const presenti = vociPresenti();
    const g = gruppi(presenti);
    N.lBarra.replaceChildren(...g.barra.map((id, i) => riga(id, presenti.get(id), true, i, g.barra.length)));
    N.lAltro.replaceChildren(...g.altro.map((id, i) => riga(id, presenti.get(id), false, i, g.altro.length)));
    N.errore.textContent = S.errore; N.errore.hidden = !S.errore;
    if (S.fuoco && !S.occupato) {
      const r = N.pannello.querySelector(`li[data-id="${S.fuoco.id}"]`);
      const b = r && (r.querySelector(`[data-bm="${S.fuoco.azione}"]:not(:disabled)`) || r.querySelector("button:not(:disabled)"));
      if (b) b.focus();
      S.fuoco = null;
    }
  }
  function apriModifica() {
    if (S.modifica) return chiudiModifica(true);
    chiudi(false);
    S.modifica = true; S.errore = "";
    N.matita.setAttribute("aria-pressed", "true"); N.matita.classList.add("attiva");
    N.pannello.hidden = false;
    disegnaModifica();
    const b = N.pannello.querySelector("button.bm-fatto");
    if (b) b.focus();
  }
  function chiudiModifica(fuoco) {
    S.modifica = false; N.pannello.hidden = true;
    N.matita.setAttribute("aria-pressed", "false"); N.matita.classList.remove("attiva");
    if (fuoco) N.matita.focus();
  }

  // trascinare: eventi pointer sulla maniglia, movimento e rilascio seguiti sulla finestra
  function iniziaDrag(e, id) {
    if (S.occupato || (e.button != null && e.button !== 0)) return;
    const li = e.target.closest("li");
    if (!li) return;
    e.preventDefault();
    S.drag = { id, li };
    li.classList.add("bm-trascino");
    N.pannello.classList.add("bm-trascinando");
    window.addEventListener("pointermove", muoviDrag);
    window.addEventListener("pointerup", fineDrag);
    window.addEventListener("pointercancel", annullaDrag);
  }
  function muoviDrag(e) {
    const d = S.drag;
    if (!d) return;
    e.preventDefault();
    let lista = null;
    for (const ul of [N.lBarra, N.lAltro]) {
      const r = ul.getBoundingClientRect();
      if (e.clientY >= r.top - 14 && e.clientY <= r.bottom + 14) lista = ul;
    }
    if (!lista) return;
    const prima = [...lista.children].find((c) => c !== d.li && e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2) || null;
    if (d.li.parentNode !== lista || d.li.nextSibling !== prima) lista.insertBefore(d.li, prima);
    d.mosso = true;
  }
  function smetti() {
    window.removeEventListener("pointermove", muoviDrag);
    window.removeEventListener("pointerup", fineDrag);
    window.removeEventListener("pointercancel", annullaDrag);
    N.pannello.classList.remove("bm-trascinando");
    const d = S.drag; S.drag = null;
    if (d) d.li.classList.remove("bm-trascino");
    return d;
  }
  function fineDrag() {
    const d = smetti();
    if (!d || !d.mosso) return disegnaModifica();
    const ids = (ul) => [...ul.children].map((li) => li.dataset.id);
    applica(ids(N.lBarra), ids(N.lAltro), null);
  }
  function annullaDrag() { smetti(); disegnaModifica(); }

  // ---------------------------------------------------------------- avvio
  function costruisci() {
    N.bAltro = el("button", { type: "button", class: "bm-altro-btn", "aria-haspopup": "true", "aria-expanded": "false", "aria-controls": "bm-pop",
      onclick: () => (S.aperto ? chiudi(false) : apri(false)),
      onkeydown: (e) => { if (e.key === "ArrowDown") { e.preventDefault(); apri(true); } else if (e.key === "Escape") chiudi(true); } },
    "Altro", el("span", { class: "bm-freccia", "aria-hidden": "true" }, "▾"));
    N.pop = el("div", { class: "bm-pop", id: "bm-pop", hidden: "", "aria-label": "Altre pagine", onkeydown: tastiPop });
    N.pop.addEventListener("click", (e) => { if (e.target.closest("a[data-vista]")) chiudi(false); });
    N.altro = el("div", { class: "bm-altro" }, N.bAltro);   // la tendina sta fuori: «sticky» la chiuderebbe sotto la lavagna
    N.matita = el("button", { type: "button", class: "bm-matita", "aria-pressed": "false", "aria-controls": "bm-modifica",
      title: "Modifica la barra: ordine e voci in «Altro»", "aria-label": "Modifica la barra", onclick: apriModifica }, "✎");
    N.lBarra = el("ul", { class: "bm-lista", "aria-label": "Voci in barra" });
    N.lAltro = el("ul", { class: "bm-lista", "aria-label": "Voci in Altro" });
    N.errore = el("p", { class: "bm-errore", role: "alert", hidden: "" });
    N.pannello = el("div", { class: "bm-pannello", id: "bm-modifica", role: "dialog", "aria-label": "Modifica la barra", hidden: "",
      onkeydown: (e) => { if (e.key === "Escape" && !S.drag) { e.preventDefault(); chiudiModifica(true); } } },
    el("div", { class: "bm-testa" }, el("b", {}, "Modifica la barra"),
      el("button", { type: "button", class: "bm-fatto", onclick: () => chiudiModifica(true) }, "Fatto")),
    el("p", { class: "bm-nota" }, "Trascina con ⋮⋮ o usa ↑ ↓. Si salva da solo."),
    N.errore,
    el("h3", { class: "bm-sotto" }, "In barra"), N.lBarra,
    el("h3", { class: "bm-sotto" }, "In «Altro»"), N.lAltro,
    el("button", { type: "button", class: "bm-partenza", onclick: partenza }, "Torna alle voci di partenza"));
    document.body.append(N.pannello);

    // le voci che altri script inseriscono «prima di» una voce finita in «Altro» non devono rompersi
    menu.insertBefore = function (nodo, rif) {
      if (rif && rif.parentNode !== this) return inserisci.call(rif.parentNode, nodo, rif);
      return inserisci.call(this, nodo, rif);
    };
    document.addEventListener("pointerdown", (e) => { if (S.aperto && !N.altro.contains(e.target) && !N.pop.contains(e.target)) chiudi(false); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.aperto) chiudi(true); });
    window.addEventListener("resize", () => chiudi(false));
    window.addEventListener("hashchange", () => chiudi(false));
    menu.addEventListener("scroll", () => chiudi(false), { passive: true });
    menu.classList.add("bm-attiva");
    osservatore = new MutationObserver(osserva);
    // ponte.js mette «dentro-ponte» e «ponte-tutto» su <html> dopo l'avvio: cambia quali voci si vedono
    new MutationObserver(() => riordina()).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    riordina();
  }

  async function avvia() {
    let r;
    try { r = await chiama("GET"); } catch (e) { return; }      // niente risposta: la barra resta com'è
    if (r.stato !== 200 || !Array.isArray(r.d.ordine) || !Array.isArray(r.d.in_barra)) return;
    const v = aggiornaVoci(r.d.ordine.filter((id) => typeof id === "string" && ID.test(id)), r.d.in_barra);
    S.ordine = v.ordine;
    S.inBarra = v.inBarra;
    costruisci();
  }
  avvia();
})();
