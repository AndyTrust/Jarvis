// Il «Registro» del Command Center (2026-10-03, idea presa da OpenBot, decisione dell'utente): l'elenco unico di
// ciò che Jarvis ha fatto o tentato, con l'esito e, per ogni rifiuto, la regola che l'ha causato.
// Contratto: command-center/CONTRATTO-registro.md. Va con registro.css; aggancio in INTEGRA-REGISTRO.md.
//
// Vale sul Mac e dentro il ponte. All'avvio chiede GET /api/registro?limite=1: se risponde 404 (server senza
// la patch) non crea niente e non fa altre richieste. Altrimenti, senza toccare app.js:
//  - aggiunge la voce «Registro» (#registro) al menu in alto, al foglio «Altro» del telefono e a TITOLI;
//  - crea <section class="vista vista-registro" data-vista="registro"> dentro <main>.
// Due schede: «Registro» (elenco a schede, filtri per esito e fonte, ricerca, proposte) e «Regole» (le regole del
// file, in SOLA LETTURA). Filtri anche dall'indirizzo: #registro?esito=rifiutato&fonte=guardia&q=push&vista=regole
// (la pagina li legge e riporta l'indirizzo a #registro, perché app.js conosce solo i nomi delle viste).
// Aggiornamento ogni 10 s solo a vista aperta e scheda del browser visibile. Solo GET: nessuna regola si crea
// da qui, la politica di permesso si cambia soltanto modificando il file sul Mac. Testi sempre con textContent.
(function registro() {
  "use strict";
  const PASSO_MS = 10000, PASSO_REGOLE_MS = 60000, LIMITE = 200;
  const ESITI = {
    permesso: { segno: "✓", parola: "Permesso" }, rifiutato: { segno: "✕", parola: "Rifiutato" },
    fallito: { segno: "!", parola: "Fallito" }, scaduto: { segno: "⏱", parola: "Scaduto" },
  };
  const FONTI = {
    approvazione: { parola: "Scheda", lunga: "Schede «Approva / Rifiuta»" },
    regola: { parola: "Regola", lunga: "Regole del file" },
    guardia: { parola: "Guardia", lunga: "Guardia dei comandi" },
    ponte: { parola: "Sito", lunga: "Dal sito (ponte sulla VPS)" },
    schermo: { parola: "Schermo", lunga: "Schermo visto dal sito" },
  };
  const AZIONI_REGOLA = { consenti: "Consenti", chiedi: "Chiedi", nega: "Nega" };
  const ETICHETTE = {
    id: "Scheda", rischio: "Rischio", agente: "Agente", lavoro_id: "Lavoro", deciso_da: "Deciso da", motivo: "Motivo",
    comando: "Comando", percorso: "Percorso", righe_aggiunte: "Righe aggiunte", righe_tolte: "Righe tolte", cartella: "Cartella",
    codice: "Risposta HTTP", sessione: "Sessione (impronta)", modo: "Modo della chat", durata_s: "Durata (s)",
    richieste: "Richieste", dal: "Dalle", byte: "Byte", in_uso: "Regole in uso",
  };
  const S = {
    attivo: false, vista: "registro", esito: new Set(), fonte: new Set(), q: "",
    dati: null, regole: null, timer: null, timerRegole: null, inVolo: null, aperti: new Set(),
    richieste: 0, errore: "", ultimo: 0, contaPrima: null,
  };
  const token = () => window.CC_TOKEN || "";
  const corto = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, String(v));
    }
    for (const f of figli) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  async function leggi(percorso, segnale) {
    const r = await fetch(percorso, { headers: { "X-Token": token(), Accept: "application/json" }, cache: "no-store",
      credentials: "same-origin", signal: segnale });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }

  // ---------------------------------------------------------------- indirizzo: #registro?esito=…&fonte=…&q=…&vista=…
  function leggiIndirizzo() {
    const h = location.hash || "";
    if (!/^#registro(\?|$)/.test(h)) return false;
    const i = h.indexOf("?");
    if (i < 0) return false;
    const p = new URLSearchParams(h.slice(i + 1));
    const lista = (k, ammessi) => new Set((p.get(k) || "").split(",").filter((x) => Object.prototype.hasOwnProperty.call(ammessi, x)));
    if (p.has("esito")) S.esito = lista("esito", ESITI);
    if (p.has("fonte")) S.fonte = lista("fonte", FONTI);
    if (p.has("q")) S.q = corto(p.get("q") || "", 100);
    if (p.get("vista") === "regole" || p.get("vista") === "registro") S.vista = p.get("vista");
    history.replaceState(null, "", "#registro");         // app.js conosce solo «#registro»
    return true;
  }

  // ---------------------------------------------------------------- menu, foglio del telefono, vista
  const N = {};
  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="registro"]')) {
      const a = el("a", { href: "#registro", "data-vista": "registro", title: "Cosa ha fatto o tentato Jarvis, e con quale regola" },
        el("i", { class: "spia grigia" }), "Registro");
      const prima = menu.querySelector('a[data-vista="memoria"]') || menu.querySelector('a[data-vista="lavagna"]');
      if (prima) menu.insertBefore(a, prima); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="registro"]')) {
      const b = el("a", { href: "#registro", "data-vista": "registro" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "≡"),
        el("span", {}, "Registro"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.registro) TITOLI.registro = "Registro"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }

  function chip(gruppo, chiave, testo, segno) {
    return el("button", { type: "button", class: "rg-chip" + (segno ? " rg-chip-" + chiave : ""), "data-gruppo": gruppo, "data-chiave": chiave,
      "aria-pressed": "false", onclick: () => cambiaFiltro(gruppo, chiave) },
    segno ? el("span", { class: "rg-chip-segno", "aria-hidden": "true" }, segno) : null, testo);
  }

  function creaVista() {
    const main = document.querySelector("main");
    if (!main) return false;
    N.tabRegistro = el("button", { type: "button", role: "tab", id: "rg-tab-registro", "aria-controls": "rg-pannello-registro", class: "rg-tab", onclick: () => scegliVista("registro") }, "Registro");
    N.tabRegole = el("button", { type: "button", role: "tab", id: "rg-tab-regole", "aria-controls": "rg-pannello-regole", class: "rg-tab", onclick: () => scegliVista("regole") }, "Regole");
    const tabs = el("div", { class: "rg-tabs", role: "tablist", "aria-label": "Registro o regole" }, N.tabRegistro, N.tabRegole);
    tabs.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      ev.preventDefault();
      scegliVista(S.vista === "registro" ? "regole" : "registro");
      (S.vista === "registro" ? N.tabRegistro : N.tabRegole).focus();
    });
    N.aggiornato = el("span", { class: "rg-aggiornato" }, "");

    N.cerca = el("input", { type: "search", id: "rg-cerca", class: "rg-cerca", placeholder: "comando, file, regola…", autocomplete: "off", maxlength: "100", enterkeyhint: "search" });
    let attesaCerca = null;
    N.cerca.addEventListener("input", () => { clearTimeout(attesaCerca); attesaCerca = setTimeout(() => { S.q = N.cerca.value.trim(); aggiorna(true); }, 300); });
    const riga = el("div", { class: "rg-cerca-riga" }, el("label", { for: "rg-cerca", class: "rg-etichetta" }, "Cerca"), N.cerca);
    N.chipEsito = el("div", { class: "rg-chips", role: "group", "aria-label": "Filtra per esito" },
      chip("esito", "", "Tutti"), ...Object.entries(ESITI).map(([k, v]) => chip("esito", k, v.parola, v.segno)));
    N.chipFonte = el("div", { class: "rg-chips", role: "group", "aria-label": "Filtra per fonte" },
      chip("fonte", "", "Tutte"), ...Object.entries(FONTI).map(([k, v]) => chip("fonte", k, v.parola)));
    const filtri = el("div", { class: "rg-filtri" }, riga,
      el("div", { class: "rg-filtro" }, el("span", { class: "rg-etichetta", "aria-hidden": "true" }, "Esito"), N.chipEsito),
      el("div", { class: "rg-filtro" }, el("span", { class: "rg-etichetta", "aria-hidden": "true" }, "Fonte"), N.chipFonte));
    N.fonti = el("div", { class: "rg-fonti", role: "note" });
    N.conta = el("p", { class: "rg-conta", role: "status", "aria-live": "polite" }, "");
    // REVISIONE-2 F3: gli eventi con una data impossibile si scartano (e si contano) invece di fermare la vista
    N.scartati = el("p", { class: "rg-scartati", role: "note", hidden: true });
    N.lista = el("ol", { class: "rg-lista", "aria-label": "Eventi del registro, dal più recente" });
    N.vuoto = el("p", { class: "rg-vuoto" }, "lettura…");
    N.proposte = el("section", { class: "rg-riq rg-proposte", "aria-labelledby": "rg-t-proposte" });
    N.pannelloRegistro = el("div", { class: "rg-pannello", role: "tabpanel", id: "rg-pannello-registro", "aria-labelledby": "rg-tab-registro" },
      el("div", { class: "rg-colonna" }, el("div", { class: "rg-riq" }, filtri, N.fonti, N.conta, N.scartati, N.vuoto, N.lista)),
      el("div", { class: "rg-colonna rg-colonna-lato" }, N.proposte));
    N.regole = el("div", { class: "rg-riq" });
    N.pannelloRegole = el("div", { class: "rg-pannello rg-pannello-regole", role: "tabpanel", id: "rg-pannello-regole", "aria-labelledby": "rg-tab-regole" }, N.regole);
    N.vista = el("section", { class: "vista vista-registro", "data-vista": "registro", "aria-labelledby": "rg-titolo" },
      el("div", { class: "rg-testa" }, el("h2", { id: "rg-titolo", class: "rg-titolo" }, "Registro"), tabs, N.aggiornato),
      N.pannelloRegistro, N.pannelloRegole);
    main.append(N.vista);
    N.cerca.value = S.q;
    disegnaChips();
    disegnaVista();
    return true;
  }

  function scegliVista(v) {
    S.vista = v;
    disegnaVista();
    if (v === "regole" || !S.regole) leggiRegole();
  }
  function disegnaVista() {
    const reg = S.vista === "registro";
    N.tabRegistro.setAttribute("aria-selected", String(reg));
    N.tabRegole.setAttribute("aria-selected", String(!reg));
    N.tabRegistro.tabIndex = reg ? 0 : -1;
    N.tabRegole.tabIndex = reg ? -1 : 0;
    N.pannelloRegistro.hidden = !reg;
    N.pannelloRegole.hidden = reg;
    if (reg && N.chipEsito) disegnaChips();
  }
  function cambiaFiltro(gruppo, chiave) {
    const insieme = S[gruppo];
    if (!chiave) insieme.clear();
    else if (insieme.has(chiave)) insieme.delete(chiave);
    else insieme.add(chiave);
    disegnaChips();
    aggiorna(true);
  }
  function disegnaChips() {
    for (const b of N.vista.querySelectorAll(".rg-chip")) {
      const insieme = S[b.dataset.gruppo];
      b.setAttribute("aria-pressed", String(b.dataset.chiave ? insieme.has(b.dataset.chiave) : insieme.size === 0));
    }
    // sul telefono i filtri scorrono di lato: il primo scelto deve restare in vista
    for (const riga of [N.chipEsito, N.chipFonte]) {
      const b = riga.querySelector('.rg-chip[aria-pressed="true"]');
      if (!b || riga.scrollWidth <= riga.clientWidth) continue;           // nascosta o tutta in vista
      const br = b.getBoundingClientRect(), rr = riga.getBoundingClientRect();
      if (br.left < rr.left || br.right > rr.right) riga.scrollLeft = Math.max(0, riga.scrollLeft + br.left - rr.left - 12);
    }
  }

  // ---------------------------------------------------------------- elenco
  // una data plausibile: numero, dopo il 2000, non oltre un anno nel futuro (un ts enorme o negativo fa lanciare toISOString)
  const tsValido = (ts) => typeof ts === "number" && Number.isFinite(ts) && ts >= 946684800 && ts <= Date.now() / 1000 + 366 * 86400;
  const ora = (ts) => {
    const d = new Date(ts * 1000), oggi = new Date();
    const hm = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === oggi.toDateString() ? hm : d.toLocaleDateString("it-IT", { day: "numeric", month: "short" }) + " " + hm;
  };
  const chiaveEvento = (e) => [e.ts, e.fonte, e.esito, e.azione, e.riepilogo, (e.dettagli || {}).id || ""].join("|");
  function testoRegola(e) {
    if (e.regola === "predefinita") return "nessuna regola del file: si chiede all'utente (predefinita)";
    if (e.regola) return e.regola;
    if (e.fonte === "approvazione") return "non registrata (scheda di prima del registro)";
    return null;
  }
  function valore(k, v) {
    if (k === "dal" && typeof v === "number") return ora(v);
    return corto(typeof v === "object" ? JSON.stringify(v) : v, 300);
  }
  function scheda(e) {
    const es = ESITI[e.esito] || { segno: "•", parola: e.esito || "?" };
    const fo = FONTI[e.fonte] || { parola: e.fonte || "?" };
    const regola = testoRegola(e);
    const d = e.dettagli && typeof e.dettagli === "object" ? e.dettagli : {};
    const k = chiaveEvento(e);
    const righe = Object.entries(d).filter(([, v]) => v != null && v !== "");
    let dett = null;
    if (righe.length) {
      dett = el("details", { class: "rg-dettagli" }, el("summary", {}, "Dettagli"),
        el("dl", {}, ...righe.flatMap(([kk, v]) => [el("dt", {}, ETICHETTE[kk] || kk),
          el("dd", { class: kk === "comando" || kk === "percorso" ? "rg-mono" : null }, valore(kk, v))])));
      if (S.aperti.has(k)) dett.open = true;
      dett.addEventListener("toggle", () => { if (dett.open) S.aperti.add(k); else S.aperti.delete(k); });
    }
    const rifiuto = e.esito === "rifiutato" || e.esito === "fallito";
    // per le schede la regola ha solo chiesto: decide l'utente (o il tempo), scritto in «deciso da»
    const etichetta = e.fonte === "approvazione" ? "Regola che ha chiesto la scheda: " : rifiuto ? "Regola che l'ha deciso: " : "Regola: ";
    const forte = rifiuto && e.regola && e.fonte !== "approvazione";
    return el("li", { class: `rg-evento rg-e-${e.esito}` },
      el("div", { class: "rg-evento-testa" },
        el("span", { class: `rg-esito rg-esito-${e.esito}` }, el("span", { "aria-hidden": "true" }, es.segno + " "), es.parola),
        el("span", { class: "rg-fonte" }, fo.parola),
        el("span", { class: "rg-azione" }, corto(e.azione, 60)),
        el("time", { class: "rg-ora", datetime: new Date(e.ts * 1000).toISOString() }, ora(e.ts))),
      el("p", { class: "rg-riepilogo" }, corto(e.riepilogo, 160)),
      regola ? el("p", { class: "rg-regola" + (forte ? " rg-regola-forte" : "") },
        el("span", { class: "rg-etichetta" }, etichetta), el("b", {}, regola),
        d.deciso_da ? el("span", { class: "rg-deciso" }, " · " + corto(d.deciso_da, 60)) : null) : null,
      dett);
  }
  const STATI_BUONI = new Set(["ok", "vuota", "non chiesta"]);
  function disegnaElenco() {
    const d = S.dati;
    if (S.errore) {
      N.vuoto.hidden = false;
      N.vuoto.textContent = S.errore;
      if (!d) { N.lista.replaceChildren(); return; }
    }
    if (!d) return;
    const avvisi = [];
    const visti = new Set();
    for (const [f, st] of Object.entries(d.fonti || {})) {
      if (STATI_BUONI.has(st)) continue;
      const chi = f === "ponte" || f === "schermo" ? "Ponte e schermo (VPS)" : (FONTI[f] || { lunga: f }).lunga;
      if (visti.has(chi)) continue;
      visti.add(chi);
      avvisi.push(el("li", {}, el("b", {}, chi + ": "), corto(st, 120),
        /non raggiungibile|in lettura/.test(st) ? " — l'elenco mostra le altre fonti." : ""));
    }
    N.fonti.replaceChildren(...(avvisi.length ? [el("ul", {}, ...avvisi)] : []));
    N.fonti.hidden = !avvisi.length;
    const tutti = Array.isArray(d.eventi) ? d.eventi : [];
    const ev = tutti.filter((e) => e && typeof e === "object" && tsValido(e.ts));
    let scartati = tutti.length - ev.length;
    const tot = typeof d.totale === "number" ? d.totale : tutti.length;
    const testo = ev.length ? (tot > ev.length ? `${ev.length} eventi più recenti su ${tot}` : ev.length === 1 ? "1 evento" : `${ev.length} eventi`) : "";
    if (N.conta.textContent !== testo) N.conta.textContent = testo;
    if (!S.errore) {
      N.vuoto.hidden = ev.length > 0;
      N.vuoto.textContent = S.q || S.esito.size || S.fonte.size ? "Nessun evento con questi filtri." : "Il registro è vuoto: niente è stato ancora deciso.";
    }
    const main = document.querySelector("main"), y = main ? main.scrollTop : 0;
    // una scheda che non si riesce a disegnare non ferma le altre
    const schede = [];
    for (const e of ev) { try { schede.push(scheda(e)); } catch (x) { scartati++; } }
    N.lista.replaceChildren(...schede);
    const testoScartati = scartati ? (scartati === 1 ? "1 evento scartato per data non valida" : `${scartati} eventi scartati per data non valida`) : "";
    if (N.scartati && N.scartati.textContent !== testoScartati) { N.scartati.textContent = testoScartati; N.scartati.hidden = !scartati; }
    if (main) main.scrollTop = y;
  }
  function disegnaAggiornato() {
    if (!N.aggiornato) return;
    const s = S.ultimo ? Math.max(0, Math.round((Date.now() - S.ultimo) / 1000)) : null;
    N.aggiornato.textContent = s == null ? "" : `aggiornato ${s < 3 ? "adesso" : s + " s fa"}`;
  }

  async function aggiorna(subito) {
    clearTimeout(S.timer);
    S.timer = null;
    if (!attiva()) return;
    if (S.inVolo) { if (!subito) return pianifica(); try { S.inVolo.abort(); } catch (e) { /* già chiusa */ } }
    const ctl = new AbortController();
    S.inVolo = ctl;
    const q = new URLSearchParams({ limite: String(LIMITE) });
    if (S.esito.size) q.set("esito", [...S.esito].join(","));
    if (S.fonte.size) q.set("fonte", [...S.fonte].join(","));
    if (S.q) q.set("q", S.q);
    const tetto = setTimeout(() => ctl.abort(), 20000);
    try {
      S.richieste++;
      const { stato, d } = await leggi("/api/registro?" + q.toString(), ctl.signal);
      if (S.inVolo !== ctl) return;
      if (stato === 200 && Array.isArray(d.eventi)) {
        S.dati = d; S.errore = ""; S.ultimo = Date.now();
      } else if (stato === 403 && d.token_scaduto) {
        S.errore = "Il Command Center è ripartito: ricarica la pagina per continuare.";
      } else if (stato === 401) {
        S.errore = "Sessione scaduta: rientra dalla pagina di accesso.";
      } else {
        S.errore = typeof d.errore === "string" ? "Registro non disponibile: " + corto(d.errore, 160) : `Registro non disponibile (risposta ${stato}).`;
      }
    } catch (e) {
      if (S.inVolo !== ctl) return;
      S.errore = "Il Command Center non risponde: riprovo fra 10 secondi.";
    } finally {
      clearTimeout(tetto);
      if (S.inVolo === ctl) S.inVolo = null;
    }
    disegnaElenco();
    disegnaAggiornato();
    pianifica();
  }
  function pianifica() {
    clearTimeout(S.timer);
    S.timer = attiva() ? setTimeout(() => aggiorna(false), PASSO_MS) : null;
  }

  // ---------------------------------------------------------------- regole (sola lettura) e proposte
  async function leggiRegole() {
    clearTimeout(S.timerRegole);
    S.timerRegole = null;
    if (!attiva()) return;
    try {
      const { stato, d } = await leggi("/api/registro/regole");
      if (stato === 200 && Array.isArray(d.regole)) S.regole = d;
      else S.regole = S.regole || { errore_lettura: typeof d.errore === "string" ? d.errore : `risposta ${stato}` };
    } catch (e) {
      S.regole = S.regole || { errore_lettura: "il Command Center non risponde" };
    }
    disegnaRegole();
    disegnaProposte();
    if (attiva()) S.timerRegole = setTimeout(leggiRegole, PASSO_REGOLE_MS);
  }
  function corrispondenzaTesto(c) {
    const pezzi = [];
    if (!c || typeof c !== "object") return "ogni uso";
    if (c.segreti) pezzi.push("tocca un file di segreti");
    const lista = (v) => (Array.isArray(v) ? v : [v]).map((x) => corto(x, 120)).join(" · ");
    if (c.comando_inizia != null) pezzi.push("il comando comincia con: " + lista(c.comando_inizia));
    if (c.comando_regex != null) pezzi.push("il comando corrisponde a /" + corto(c.comando_regex, 120) + "/");
    if (c.percorso_glob != null) pezzi.push("il percorso è " + lista(c.percorso_glob));
    if (c.percorso_regex != null) pezzi.push("il percorso corrisponde a /" + corto(c.percorso_regex, 120) + "/");
    if (c.url_dominio != null) pezzi.push("il sito è " + lista(c.url_dominio) + " (solo https)");
    return pezzi.length ? pezzi.join("; ") : "ogni uso";
  }
  function disegnaRegole() {
    const d = S.regole;
    if (!d) { N.regole.replaceChildren(el("p", { class: "rg-vuoto" }, "lettura…")); return; }
    if (d.errore_lettura) { N.regole.replaceChildren(el("p", { class: "rg-vuoto" }, "Regole non disponibili: " + corto(d.errore_lettura, 160))); return; }
    const origine = { file: "dal file", "ultimo valido": "dall'ULTIMO FILE VALIDO", predefinite: "PREDEFINITE (il file non si legge)" }[d.origine] || d.origine;
    const testa = el("div", { class: "rg-regole-testa" },
      el("h3", { class: "rg-sotto" }, "Regole in vigore"),
      el("p", { class: "rg-nota" }, "Si leggono in ordine: la prima che corrisponde decide. Regole ", el("b", {}, origine), "."),
      el("p", { class: "rg-nota" }, "Sola lettura. Le regole si cambiano soltanto modificando sul Mac il file ",
        el("code", { class: "rg-mono" }, corto(d.file || "", 200)), ": da qui, e dal sito, non si cambia niente."),
      d.errore ? el("p", { class: "rg-attenzione", role: "alert" }, el("b", {}, "Il file delle regole non è valido: "), corto(d.errore, 300),
        ". Finché non si corregge vale " + (d.origine === "ultimo valido" ? "l'ultimo file valido." : "il predefinito.")) : null);
    const lista = el("ol", { class: "rg-regole", "aria-label": "Regole, nell'ordine in cui si provano" },
      ...(d.regole || []).map((r, i) => el("li", { class: `rg-regola-voce rg-a-${r.azione}` },
        el("div", { class: "rg-evento-testa" },
          el("span", { class: "rg-num", "aria-hidden": "true" }, String(i + 1)),
          el("b", { class: "rg-regola-id rg-mono" }, corto(r.id, 48)),
          el("span", { class: `rg-azione-regola rg-a-${r.azione}` }, AZIONI_REGOLA[r.azione] || r.azione),
          r.rischio ? el("span", { class: "rg-fonte" }, "rischio " + r.rischio) : null),
        r.descrizione ? el("p", { class: "rg-riepilogo" }, corto(r.descrizione, 300)) : null,
        el("p", { class: "rg-regola" }, el("span", { class: "rg-etichetta" }, "Strumento: "),
          el("span", { class: "rg-mono" }, (Array.isArray(r.strumento) ? r.strumento : [r.strumento]).map((s) => s === "*" ? "tutti" : corto(s, 60)).join(", "))),
        el("p", { class: "rg-regola" }, el("span", { class: "rg-etichetta" }, "Quando: "), corrispondenzaTesto(r.corrispondenza)),
        r.nota ? el("p", { class: "rg-nota-regola" }, corto(r.nota, 500)) : null)),
      el("li", { class: "rg-regola-voce rg-a-chiedi rg-ultima" },
        el("div", { class: "rg-evento-testa" }, el("span", { class: "rg-num", "aria-hidden": "true" }, "∞"),
          el("b", { class: "rg-regola-id rg-mono" }, "predefinita"), el("span", { class: "rg-azione-regola rg-a-chiedi" }, "Chiedi")),
        el("p", { class: "rg-riepilogo" }, "Nessuna regola corrisponde: si chiede all'utente con una scheda.")));
    N.regole.replaceChildren(testa, lista);
  }
  function disegnaProposte() {
    const d = S.regole;
    const p = d && Array.isArray(d.proposte) ? d.proposte : [];
    if (!p.length) {
      N.proposte.replaceChildren(el("h3", { id: "rg-t-proposte", class: "rg-sotto" }, "Proposte"),
        el("p", { class: "rg-nota" }, d ? "Nessuna proposta: compaiono le azioni che l'utente ha approvato almeno 5 volte nella stessa forma." : "lettura…"));
      return;
    }
    N.proposte.replaceChildren(
      el("h3", { id: "rg-t-proposte", class: "rg-sotto" }, `Proposte (${p.length})`),
      el("p", { class: "rg-nota" }, "Solo suggerimenti. Per usarne una, copia il testo nel file delle regole sul Mac, nel punto giusto dell'elenco: da qui non si crea niente."),
      el("ul", { class: "rg-proposte-lista" }, ...p.map((x, i) => {
        const pre = el("pre", { class: "rg-mono rg-testo-regola", id: "rg-prop-" + i, tabindex: "0" }, corto(x.testo_regola, 2000));
        const esito = el("span", { class: "rg-copiato", role: "status", "aria-live": "polite" }, "");
        const copia = el("button", { type: "button", class: "rg-btn", "aria-describedby": "rg-prop-" + i, onclick: async () => {
          let ok = false;
          try { await navigator.clipboard.writeText(x.testo_regola); ok = true; } catch (e) { /* senza permesso: si seleziona */ }
          if (!ok) { const r = document.createRange(); r.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
          esito.textContent = ok ? "copiato" : "selezionato: copia con ⌘C";
          setTimeout(() => { esito.textContent = ""; }, 4000);
        } }, "Copia il testo");
        return el("li", { class: "rg-proposta" },
          el("p", { class: "rg-riepilogo" }, "proponi regola: consenti ", el("b", { class: "rg-mono" }, corto(x.forma, 160))),
          el("p", { class: "rg-nota" }, `approvata ${x.volte} volte` + (x.ultima ? ", l'ultima " + ora(x.ultima) : "")),
          el("details", { class: "rg-dettagli" }, el("summary", {}, "Testo della regola"), pre, el("div", { class: "rg-copia" }, copia, esito)));
      })));
  }

  // ---------------------------------------------------------------- entrata e uscita
  const attiva = () => (location.hash === "#registro" || location.hash.startsWith("#registro?")) && !document.hidden;
  let tick = null;
  function entra() {
    if (S.attivo) return;
    S.attivo = true;
    disegnaChips();                 // a vista nascosta i filtri non hanno misure: si rimette in vista quello scelto
    aggiorna(true);
    leggiRegole();
    clearInterval(tick);
    tick = setInterval(disegnaAggiornato, 1000);
  }
  function esci() {
    S.attivo = false;
    clearTimeout(S.timer); S.timer = null;
    clearTimeout(S.timerRegole); S.timerRegole = null;
    if (S.inVolo) { try { S.inVolo.abort(); } catch (e) { /* già chiusa */ } S.inVolo = null; }
    clearInterval(tick); tick = null;
  }
  function cambio() { if (attiva()) entra(); else esci(); }

  // #registro?…: si leggono i filtri, l'indirizzo torna «#registro» e si ridisegna la vista. mostraVista() si
  // richiama qui perché l'ascoltatore di app.js può essere già passato con l'indirizzo lungo (e aver aperto la chat).
  window.addEventListener("hashchange", () => {
    if (!leggiIndirizzo() || !N.vista) return;
    N.cerca.value = S.q; disegnaChips(); disegnaVista(); S.attivo = false;
    if (typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
  }, true);

  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let r;
    try { r = await leggi("/api/registro?limite=1"); } catch (e) { r = { stato: 0 }; }
    if (r.stato === 404) return;                    // server senza la patch: niente voce, niente richieste
    leggiIndirizzo();
    creaVoceMenu();
    if (!creaVista()) return;
    document.documentElement.classList.add("con-registro");
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    // aperta già su #registro: app.js l'ha portata alla chat perché non la conosceva ancora
    if (location.hash === "#registro" && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
  })();

  window.CCRegistro = {
    stato: () => ({ attivo: S.attivo, vista: S.vista, esito: [...S.esito], fonte: [...S.fonte], q: S.q, richieste: S.richieste,
      eventi: S.dati && Array.isArray(S.dati.eventi) ? S.dati.eventi.length : null, errore: S.errore, regole: S.regole ? (S.regole.regole || []).length : null }),
    rileggi: () => aggiorna(true),
  };
})();
