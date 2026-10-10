// Gli «Incarichi» del Command Center (2026-10-04, docs/incarichi-contratto.md): la coda sulla VPS fra Jarvis dell'utente
// e gli agenti del CRM. In alto i battiti degli agenti, poi gli ultimi incarichi, il modulo per mandarne uno e il tasto
// «Annulla» sui «nuovo». Dati: GET/POST /api/incarichi (strumenti/incarichi.py, via ssh: può durare qualche secondo).
// Come piani.js: si aggancia da sola al menu, al foglio del telefono e a TITOLI. Testi sempre con textContent.
(function incarichi() {
  "use strict";
  const S = { dati: null, errore: "", avviso: "", occupato: false, timer: null, attivo: false, aperti: new Set(), bozza: { a: "", tipo: "domanda", testo: "" } };
  const N = {};
  const MAX = 4000;
  const FASE2 = "jarvis-giuseppe";
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
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 25000);
    try {
      const r = await fetch("/api/incarichi", { method: metodo, cache: "no-store", credentials: "same-origin", signal: ctl.signal,
        headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
        body: corpo ? JSON.stringify(corpo) : undefined });
      let d = null;
      try { d = await r.json(); } catch (e) { /* non JSON */ }
      return { stato: r.status, d: d && typeof d === "object" ? d : {} };
    } finally { clearTimeout(t); }
  }
  function fa(t) {
    if (!t) return "";
    const s = Math.max(0, Math.round(Date.now() / 1000 - t));
    if (s < 60) return "adesso";
    if (s < 3600) return Math.floor(s / 60) + " min fa";
    if (s < 86400) return Math.floor(s / 3600) + " h fa";
    return Math.floor(s / 86400) + " g fa";
  }
  const STATI = {
    nuovo: ["Nuovo", "attenzione"], preso: ["Preso", "lavora"], fatto: ["Fatto", "ok"], fallito: ["Fallito", "guasto"],
    annullato: ["Annullato", "grigia"], scaduto: ["Scaduto", "grigia"],
  };
  const TIPI = { domanda: "Domanda", lavoro: "Lavoro", messaggio: "Messaggio" };
  const corto = (s, n) => { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };

  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="incarichi"]')) {
      const a = el("a", { href: "#incarichi", "data-vista": "incarichi", title: "La coda degli incarichi verso gli agenti sulla VPS" },
        el("i", { class: "spia grigia", id: "in-spia" }), "Incarichi");
      const prima = menu.querySelector('a[data-vista="piani"]') || menu.querySelector('a[data-vista="connessioni"]') || menu.querySelector('a[data-vista="registro"]');
      if (prima) menu.insertBefore(a, prima); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="incarichi"]')) {
      const b = el("a", { href: "#incarichi", "data-vista": "incarichi" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "✉"),
        el("span", {}, "Incarichi"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.incarichi) TITOLI.incarichi = "Incarichi"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }
  function segnaSpia() {
    const d = S.dati || {};
    const aperti = (d.incarichi || []).filter((x) => x.stato === "nuovo" || x.stato === "preso").length;
    const vivi = (d.battiti || []).some((b) => b.vivo);
    const classe = S.errore ? "guasto" : aperti ? "lavora" : vivi ? "ok" : "grigia";
    for (const sp of document.querySelectorAll('.menu a[data-vista="incarichi"] .spia, #m-foglio a[data-vista="incarichi"] .spia')) sp.className = "spia " + classe;
  }

  async function manda(ev) {
    ev.preventDefault();
    if (S.occupato) return;
    const a = N.a.value, tipo = N.tipo.value, testo = N.testo.value;
    if (!a) { S.errore = "Scegli a chi mandarlo."; disegna(); return; }
    if (!testo.trim()) { S.errore = "Scrivi il testo dell'incarico."; disegna(); return; }
    S.occupato = true; S.errore = ""; S.avviso = "Mando l'incarico alla VPS…"; disegna();
    try {
      const r = await chiama("POST", { azione: "nuovo", a, tipo, testo });
      if (r.stato === 200) { S.bozza.testo = ""; N.testo.value = ""; S.avviso = "Incarico mandato a " + a + "."; await aggiorna(true); }
      else { S.errore = r.d.errore || ("errore " + r.stato); S.avviso = ""; }
    } catch (e) { S.errore = "Rete assente o VPS lenta: l'incarico potrebbe non essere partito, ricarica l'elenco."; S.avviso = ""; }
    S.occupato = false; disegna(); segnaSpia();
  }
  async function annulla(id) {
    if (S.occupato) return;
    S.occupato = true; S.errore = ""; S.avviso = ""; disegna();
    try {
      const r = await chiama("POST", { azione: "annulla", id });
      if (r.stato === 200) { S.avviso = "Incarico annullato."; await aggiorna(true); } else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente: l'annullamento non è partito."; }
    S.occupato = false; disegna(); segnaSpia();
  }

  function battiti() {
    const b = (S.dati && S.dati.battiti) || [];
    if (!b.length) return el("p", { class: "in-nota" }, "Nessun battito: gli agenti della VPS non si sono ancora fatti sentire.");
    return el("ul", { class: "in-battiti" }, ...b.map((x) => el("li", { class: "in-battito" + (x.vivo ? " in-vivo" : ""), title: x.nota || "" },
      el("i", { class: "spia " + (x.vivo ? "ok" : "grigia"), "aria-hidden": "true" }),
      el("span", { class: "in-agente" }, x.agente),
      el("span", { class: "in-dove" }, [x.macchina, fa(x.il)].filter(Boolean).join(" · ")),
      el("span", { class: "in-sr" }, x.vivo ? " (vivo)" : " (fermo)"))));
  }
  function riga(x) {
    const [parola, spia] = STATI[x.stato] || [x.stato, "grigia"];
    const aperto = S.aperti.has(x.id);
    const testa = el("div", { class: "in-testa" }, el("i", { class: "spia " + spia, "aria-hidden": "true" }),
      el("span", { class: "in-chi" }, (x.da || "?") + " → " + (x.a || "?")),
      el("span", { class: "in-tipo" }, TIPI[x.tipo] || x.tipo || ""),
      el("span", { class: "in-stato" }, parola),
      el("span", { class: "in-quando" }, fa(x.creato)));
    const corpo = [el("p", { class: "in-testo" }, aperto ? x.testo : corto(x.testo, 220))];
    const r = x.risposta;
    if (r && typeof r === "object") {
      const bt = el("button", { type: "button", class: "in-apri", "aria-expanded": aperto ? "true" : "false",
        onclick: () => { if (S.aperti.has(x.id)) S.aperti.delete(x.id); else S.aperti.add(x.id); disegna(); } },
        aperto ? "Nascondi la risposta" : "Leggi la risposta" + (r.esito === "fallito" ? " (fallita)" : ""));
      corpo.push(bt);
      if (aperto) {
        corpo.push(el("div", { class: "in-risposta" + (r.esito === "fallito" ? " in-fallita" : "") },
          el("p", { class: "in-meta" }, [r.da, fa(r.il), r.token_stimati ? "~" + r.token_stimati + " token" : ""].filter(Boolean).join(" · ")),
          el("pre", { tabindex: "0" }, r.testo || "")));
      }
    } else if (x.stato === "preso") {
      corpo.push(el("p", { class: "in-meta" }, "Ci lavora " + (x.preso_da || "un agente") + (x.preso_il ? ", da " + fa(x.preso_il) : "") + "."));
    }
    if (x.stato === "nuovo") {
      corpo.push(el("div", { class: "in-azioni" }, el("button", { type: "button", class: "in-btn in-no", disabled: S.occupato ? "" : null,
        onclick: () => annulla(x.id) }, "Annulla")));
    }
    return el("li", { class: "in-scheda in-s-" + x.stato }, testa, ...corpo);
  }
  function opzioniA() {
    const nomi = [...new Set(((S.dati && S.dati.battiti) || []).map((b) => b.agente).filter((n) => n && n !== FASE2 && n !== "jarvis-utente"))].sort();
    const scelto = S.bozza.a || N.a.value;
    N.a.textContent = "";
    N.a.append(el("option", { value: "" }, "Scegli l'agente…"));
    for (const n of nomi) N.a.append(el("option", { value: n }, n));
    N.a.append(el("option", { value: FASE2, disabled: "" }, FASE2 + " — Fase 2: serve il sì di l'amministratore"));
    N.a.value = nomi.includes(scelto) ? scelto : "";
  }

  function disegna() {
    if (!N.lista) return;
    N.errore.textContent = S.errore; N.errore.hidden = !S.errore;
    N.avviso.textContent = S.avviso; N.avviso.hidden = !S.avviso;
    N.battiti.textContent = "";
    N.lista.textContent = "";
    N.manda.disabled = S.occupato;
    N.conta.textContent = N.testo.value.length + " / " + MAX;
    if (!S.dati) { N.battiti.append(el("p", { class: "in-nota" }, "Carico dalla VPS…")); return; }
    N.battiti.append(battiti());
    opzioniA();
    const elenco = S.dati.incarichi || [];
    if (!elenco.length) N.lista.append(el("li", { class: "in-nota" }, "Nessun incarico. Mandane uno con il modulo qui sotto."));
    for (const x of elenco) N.lista.append(riga(x));
  }
  function creaVista() {
    const main = document.querySelector("main");
    if (!main || document.querySelector('section[data-vista="incarichi"]')) return false;
    N.battiti = el("div", { class: "in-blocco-battiti", "aria-live": "polite" });
    N.lista = el("ul", { class: "in-lista" });
    N.errore = el("p", { class: "in-errore", role: "alert", hidden: "" });
    N.avviso = el("p", { class: "in-avviso", role: "status", hidden: "" });
    N.a = el("select", { id: "in-a", required: "", onchange: () => { S.bozza.a = N.a.value; } });
    N.tipo = el("select", { id: "in-tipo", onchange: () => { S.bozza.tipo = N.tipo.value; } },
      ...Object.entries(TIPI).map(([v, t]) => el("option", { value: v }, t)));
    N.tipo.value = S.bozza.tipo;
    N.testo = el("textarea", { id: "in-testo", rows: "5", maxlength: String(MAX), placeholder: "Cosa chiedi all'agente (in sola lettura: risponde, non scrive nel CRM)",
      oninput: () => { S.bozza.testo = N.testo.value; N.conta.textContent = N.testo.value.length + " / " + MAX; } });
    N.conta = el("span", { class: "in-conta" });
    N.manda = el("button", { type: "submit", class: "in-btn in-si" }, "Manda l'incarico");
    const modulo = el("form", { class: "in-modulo", onsubmit: manda },
      el("h3", { class: "in-sez" }, "Manda un incarico"),
      el("div", { class: "in-campi" },
        el("label", { for: "in-a" }, "A chi"), N.a,
        el("label", { for: "in-tipo" }, "Tipo"), N.tipo),
      el("label", { for: "in-testo", class: "in-et-testo" }, "Testo"), N.testo,
      el("div", { class: "in-piede" }, N.conta, N.manda));
    N.vista = el("section", { class: "vista vista-incarichi", "data-vista": "incarichi", "aria-labelledby": "in-titolo-pagina" },
      el("div", { class: "in-intro" }, el("h2", { id: "in-titolo-pagina", class: "in-pagina" }, "Incarichi"),
        el("p", { class: "in-sotto" }, "La coda sulla VPS: mandi una domanda o un lavoro a un agente del CRM, lui lo prende entro un paio di minuti e risponde qui.")),
      N.errore, N.avviso,
      el("h3", { class: "in-sez" }, "Agenti"), N.battiti,
      modulo,
      el("h3", { class: "in-sez" }, "Ultimi incarichi"), N.lista,
      el("p", { class: "in-nota" }, "Fase 1: gli agenti lavorano in sola lettura, non scrivono nel CRM e non mandano messaggi. Gli incarichi si mandano solo dal Mac."));
    main.append(N.vista);
    disegna();
    return true;
  }
  async function aggiorna(silenzioso) {
    try {
      const r = await chiama("GET");
      if (r.stato === 200) { S.dati = r.d; S.errore = ""; if (!silenzioso) S.avviso = ""; } else S.errore = r.d.errore || ("errore " + r.stato);
    } catch (e) { S.errore = "Rete assente o VPS lenta."; }
    disegna(); segnaSpia();
  }
  const attiva = () => location.hash === "#incarichi" && !document.hidden;
  function cambio() {
    if (attiva() && !S.attivo) { S.attivo = true; aggiorna(); clearInterval(S.timer); S.timer = setInterval(() => { if (!S.occupato) aggiorna(); }, 15000); }
    else if (!attiva() && S.attivo) { S.attivo = false; clearInterval(S.timer); S.timer = null; }
  }
  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let r;
    try { r = await chiama("GET"); } catch (e) { r = null; }
    // 404/403 = dal sito o server vecchio: niente voce. 502 (VPS giù) la voce c'è lo stesso, con l'errore in pagina.
    if (!r || (r.stato !== 200 && r.stato !== 502)) return;
    if (r.stato === 200) S.dati = r.d; else S.errore = r.d.errore || "VPS non raggiungibile";
    creaVoceMenu();
    if (!creaVista()) return;
    segnaSpia();
    setInterval(() => { if (!S.attivo) aggiorna(true); }, 120000);   // la spia nel menu, anche a pagina chiusa
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    if (location.hash === "#incarichi" && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
  })();
})();
