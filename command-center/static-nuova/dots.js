// Dots: le mascotte di OpenDots al posto dei volti degli agenti (2026-10-04, cc-dots-opus).
// Richiesta dell'utente: «usa i dots avatar nel nostro Jarvis CRM». Immagini e scelta del colore da
// CopilotKit/OpenDots (licenza MIT, Copyright (c) Atai Barkai): static/dots/LICENSE-OpenDots.txt.
//
// Come lavora, senza toccare app.js:
//  - window.avatar (la funzione di app.js che disegna il volto «beam») viene avvolta: il volto di
//    prima resta dentro lo span, e accanto si aggiungono un <img class="dot-img"> e uno
//    <span class="dot-ini"> (le iniziali). Quale dei tre si vede lo decide solo il CSS, da
//    <html data-avatar="dots|volti|iniziali">: il cambio a caldo è un attributo, niente ridisegno;
//  - un MutationObserver copre quello che app.js e gli altri script disegnano da soli: la «J» di
//    Jarvis (testa della chat, catena, messaggi), l'avatar della barra in alto, gli avatarini dei
//    lavori, la scheda di una nota di casa, la schermata di chiamata, la scheda di approvazione,
//    il registro e la nota «Jarvis» della lavagna;
//  - il colore: lo stesso hash di OpenDots (src/client/Mascot.tsx) sulla chiave dell'agente
//    «progetto:nome» (a.key, la stessa che usa tutta la pagina), quindi stesso Dot dopo una
//    ricarica e in ogni vista. Jarvis ha sempre il viola, con un anello;
//  - gli stati (riposo, lavora, ascolta, parla, allarme, fuori servizio) li legge il CSS dalle classi
//    che la pagina mette già (.al-lavoro, .attivo, .spento, data-fase della chiamata, stato della
//    voce); l'allarme viene dai lavori finiti in errore negli ultimi 30 minuti;
//  - preferenza «Avatar» in localStorage cc.avatar (sempre in try/catch: se non va, restano i Dots),
//    nel menu dei temi (temi.js) sul desktop e nel foglio «Altro» sul telefono.
// Nessuna richiesta esterna: le immagini sono in /static/dots/, una per colore e per misura.
(() => {
  "use strict";
  if (window.CCDots) return;

  const COLORI = ["blue", "mint", "orange", "purple"];
  const BASE = "/static/dots/";
  const CHIAVE = "cc.avatar", CHIAVE_FERMI = "cc.avatar.fermi";
  const MODI = [
    { id: "dots", nome: "Dots", nota: "le mascotte di OpenDots" },
    { id: "volti", nome: "Volti", nota: "i volti di prima" },
    { id: "iniziali", nome: "Iniziali", nota: "solo le lettere" },
  ];
  const valido = (m) => MODI.some((x) => x.id === m);
  const radice = document.documentElement;
  const JARVIS = { chi: "jarvis", colore: "purple", nome: "Jarvis", jarvis: true };
  const ERRORE_PER_MS = 30 * 60 * 1000;

  // ---------------------------------------------------------------- colore (OpenDots, Mascot.tsx)
  function coloreDi(identita) {
    if (!identita) return COLORI[0];
    let hash = 0;
    for (const c of String(identita)) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    return COLORI[hash % COLORI.length];
  }

  // ---------------------------------------------------------------- preferenza
  function leggi() {
    try { const m = localStorage.getItem(CHIAVE); return valido(m) ? m : "dots"; } catch (e) { return "dots"; }
  }
  function leggiFermi() {
    try { return localStorage.getItem(CHIAVE_FERMI) === "1"; } catch (e) { return false; }
  }
  let modo = leggi();
  let fermi = leggiFermi();
  radice.setAttribute("data-avatar", modo);
  radice.toggleAttribute("data-dots-fermi", fermi);

  // ---------------------------------------------------------------- chi è (le variabili globali di app.js)
  // let/const/function di app.js stanno nello scope globale degli script: si leggono per nome, mai si scrivono
  const g = (fn, riserva = null) => { try { const v = fn(); return v === undefined ? riserva : v; } catch (e) { return riserva; } };
  const agenti = () => g(() => AGENTI);                                   // eslint-disable-line no-undef
  const nomeVisto = (a) => g(() => nomeDi(a), a && a.nome) || (a && a.nome) || "";   // eslint-disable-line no-undef
  function infoAgente(a) {
    const chi = a.key || a.nome;
    return { chi, colore: coloreDi(chi), nome: nomeVisto(a), spento: a.attivo === false };
  }
  // una chiave «progetto:nome», un nome di profilo o il nome dato dall'utente → l'agente
  function risolvi(x) {
    if (x == null) return null;
    const s = String(x).trim();
    if (!s) return null;
    if (/^jarvis$/i.test(s)) return JARVIS;
    const A = agenti();
    if (A && A.size) {
      if (A.has(s)) return infoAgente(A.get(s));
      const b = s.toLowerCase();
      for (const a of A.values()) if (String(a.nome).toLowerCase() === b) return infoAgente(a);
      for (const a of A.values()) if (nomeVisto(a).toLowerCase() === b) return infoAgente(a);
    }
    return null;
  }
  // l'oggetto passato a avatar(a) da app.js
  function daOggetto(a) {
    if (!a) return null;
    const A = agenti();
    if (a.key && A && A.has(a.key)) return infoAgente(A.get(a.key));
    // la catena «Claude adesso» passa { key: "catena:<nome>" }: se il nome è di un agente vero, il suo Dot
    if (a.key && /^catena:/.test(a.key)) {
      const r = risolvi(a.nome);
      if (r) return r;
    }
    const chi = a.key || a.nome;
    return chi ? { chi, colore: coloreDi(chi), nome: a.nome || chi, spento: a.attivo === false } : null;
  }
  const eJ = (el) => el.textContent.trim() === "J" && (el.classList.contains("avatar-j") || /--c:\s*#f0f0f0/i.test(el.getAttribute("style") || ""));
  // uno span .avatar disegnato senza passare da qui (prima che dots.js partisse, o da altro codice)
  function daContesto(el) {
    if (eJ(el)) return JARVIS;
    if (el.id === "sa-avatar") return risolvi(g(() => schedaKey));               // eslint-disable-line no-undef
    if (el.id === "sc-avatar") {                                                  // nota di casa: jarvis, esecutore, ricercatore-web, memoria
      const n = g(() => schedaCasaNome);                                          // eslint-disable-line no-undef
      if (!n || /^memoria$/i.test(n)) return null;
      return risolvi(n) || { chi: "casa:" + n, colore: coloreDi("casa:" + n), nome: n };
    }
    if (el.id === "chat-avatar" || el.closest("#messaggi, .messaggi, .msg")) {
      const c = g(() => chatCon);                                                 // eslint-disable-line no-undef
      if (el.closest(".msg.comando")) return null;
      return c === "jarvis" ? JARVIS : risolvi(c);
    }
    const r = el.closest("[data-agente]");
    if (r) return risolvi(r.dataset.agente) || { chi: r.dataset.agente, colore: coloreDi(r.dataset.agente), nome: r.dataset.agente.split(":").pop(), spento: true };
    return null;
  }

  // ---------------------------------------------------------------- allarme: lavori finiti in errore
  const FORZATI = new Map();          // CCDots.allarme(chi, true|false): per le prove e per chi vorrà usarlo
  const SCOSSI = new Set();           // lo scuotimento si fa una volta sola per agente
  function inErrore() {
    const out = new Set();
    const L = g(() => ultimiLavori, []) || [];                                    // eslint-disable-line no-undef
    const ora = Date.now();
    for (const l of L) {
      if (!l || l.stato !== "errore") continue;
      const t = (l.fine_ts || l.inizio_ts || 0) * 1000;
      if (t && ora - t > ERRORE_PER_MS) continue;
      const r = risolvi(l.chi);
      if (r) out.add(r.chi);
    }
    for (const [k, v] of FORZATI) { if (v) out.add(k); else out.delete(k); }
    return out;
  }
  let errori = new Set();
  function segnaAllarme(host, chi) {
    const si = !!chi && errori.has(chi);
    host.classList.toggle("dot-allarme", si);
    if (si && !SCOSSI.has(chi)) {
      SCOSSI.add(chi);
      host.classList.add("dot-scuoti");
      setTimeout(() => host.classList.remove("dot-scuoti"), 1200);
    }
    // l'allarme non è solo un colore: il puntino ha il «!» e il nome dice «in errore» al passaggio del mouse
    if (si) host.setAttribute("title", "in errore");
    else if (host.getAttribute("title") === "in errore") host.removeAttribute("title");
  }

  // ---------------------------------------------------------------- le immagini
  // La misura più vicina per densità, scelta qui (al posto di srcset): fino a 48 px 64 su 1x e 128 su 2x/3x,
  // fino a 100 px 128/256, oltre 256. server.py manda /static/ con «Cache-Control: no-store», quindi ogni <img>
  // riscaricherebbe il file (misurato: 50 richieste di blue-64.png con 50 agenti): ogni file si scarica UNA volta
  // con fetch(), diventa un blob: e tutti gli <img> dello stesso colore e misura lo usano.
  const png = (c, n) => `${BASE}${c}-${n}.png`;
  const webp = (c) => `${BASE}${c}-256.webp`;
  function sorgente(c, w, riserva) {
    const d = window.devicePixelRatio || 1;
    const lato = w <= 48 ? (d < 1.5 ? 64 : 128) : w <= 100 ? (d < 1.5 ? 128 : 256) : 256;
    return lato === 256 ? (riserva ? png(c, 256) : webp(c)) : png(c, lato);
  }
  const BLOB = new Map();          // indirizzo → Promise dell'indirizzo blob: (o dell'indirizzo vero, se fetch non va)
  function blobDi(url) {
    if (!BLOB.has(url)) {
      BLOB.set(url, fetch(url, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
        .then((b) => URL.createObjectURL(new Blob([b], { type: url.endsWith(".webp") ? "image/webp" : "image/png" })))
        .catch(() => url));
    }
    return BLOB.get(url);
  }
  const daMisurare = new Set();
  let misuraInCoda = false;
  function misuraPoi(host) {
    daMisurare.add(host);
    if (misuraInCoda) return;
    misuraInCoda = true;
    queueMicrotask(misuraTutti);
  }
  // un solo giro di stili per tutto il gruppo (50 schede della lavagna = una lettura), poi le scritture
  function misuraTutti() {
    misuraInCoda = false;
    if (modo !== "dots") return;              // con Volti e Iniziali non si scarica niente; scegli("dots") rimette in coda
    const lista = [...daMisurare];
    daMisurare.clear();
    const larghe = lista.map((h) => {
      const w = parseFloat(getComputedStyle(h).width);
      return Number.isFinite(w) && w > 0 ? w : 40;
    });
    lista.forEach((h, i) => {
      const img = h.querySelector(":scope > .dot-img");
      if (!img) return;
      const w = larghe[i];
      const url = sorgente(h.dataset.dot, w, img.dataset.riserva === "1");
      if (img.dataset.url === url) return;
      img.dataset.url = url;
      img.width = Math.round(w); img.height = Math.round(w);
      blobDi(url).then((b) => { if (img.dataset.url === url) img.src = b; });
    });
  }
  function nuovaImg() {
    const img = document.createElement("img");
    img.className = "dot-img";
    img.alt = "";
    img.decoding = "async";
    img.draggable = false;
    img.setAttribute("aria-hidden", "true");
    // WebP non aperto (un browser vecchio): il PNG da 256
    img.addEventListener("error", () => {
      if (img.dataset.riserva === "1" || !/\.webp$/.test(img.dataset.url || "")) return;
      img.dataset.riserva = "1";
      const h = img.parentElement;
      if (h) misuraPoi(h);
    });
    return img;
  }
  function iniziali(nome) {
    const p = String(nome || "?").split(/[\s\-_:.·/]+/).filter(Boolean);
    const l = (s) => ((s.match(/[\p{L}\p{N}]/u) || [""])[0] || "").toUpperCase();
    return ((l(p[0] || "?") + (p[1] ? l(p[1]) : "")) || "?").slice(0, 2);
  }

  // ---------------------------------------------------------------- un host: lo span dell'avatar, o un suo simile
  // tipo: "av" (span .avatar e la scheda di casa), "lav" (avatarino dei lavori), "aj" (barra in alto),
  // "chm" (chiamata), "extra" (Dot aggiunto dove oggi non c'è avatar: approvazioni, registro, lavagna)
  function decora(host, info, tipo) {
    if (!info) return;
    const img0 = host.querySelector(":scope > .dot-img");
    if (img0 && host.dataset.dotChi === info.chi) {
      segnaAllarme(host, info.chi);
      return;
    }
    host.classList.add("dot-host", "dot-" + tipo);
    host.classList.toggle("dot-jarvis", !!info.jarvis);
    host.classList.toggle("dot-spento", !!info.spento);
    host.dataset.dot = info.colore;
    host.dataset.dotChi = info.chi;
    let img = img0;
    if (!img) { img = nuovaImg(); host.append(img); }
    else { delete img.dataset.url; delete img.dataset.riserva; }
    if (tipo === "av" || tipo === "lav") {
      let ini = host.querySelector(":scope > .dot-ini");
      if (!ini) { ini = document.createElement("span"); ini.className = "dot-ini"; ini.setAttribute("aria-hidden", "true"); host.append(ini); }
      ini.textContent = info.jarvis ? "J" : iniziali(info.nome);
    }
    segnaAllarme(host, info.chi);
    misuraPoi(host);
  }

  // ---------------------------------------------------------------- avatar(a) di app.js, avvolta
  const PER_AGENTE = new WeakMap();
  const originale = typeof window.avatar === "function" ? window.avatar : null;
  if (originale) {
    const avvolta = function (a, classe) {
      const span = originale.apply(this, arguments);
      try {
        const info = daOggetto(a);
        if (info && span && span.nodeType === 1) { PER_AGENTE.set(span, info); decora(span, info, "av"); }
      } catch (e) { /* il volto di prima resta */ }
      return span;
    };
    try { window.avatar = avvolta; } catch (e) { /* non scrivibile: resta il MutationObserver */ }
  }

  // ---------------------------------------------------------------- tutto il resto, dal DOM
  function infoLavoro(el) {
    const li = el.closest("[data-lid]");
    const L = g(() => ultimiLavori, []) || [];                                    // eslint-disable-line no-undef
    const l = li && L.find((x) => x && x.id === li.dataset.lid);
    return l ? risolvi(l.chi) : null;           // «sentinella», «verifica CRM»…: non sono agenti, resta la lettera
  }
  function extra(dove, prima, info, classe) {
    let x = dove.querySelector(":scope > .dot-extra");
    if (!x) {
      x = document.createElement("span");
      x.className = "dot-extra " + classe;
      x.setAttribute("aria-hidden", "true");
      if (prima) dove.insertBefore(x, prima); else dove.append(x);
    }
    decora(x, info, "extra");
  }
  function guarda(el) {
    if (el.classList.contains("avatar")) {
      decora(el, PER_AGENTE.get(el) || daContesto(el), "av");
    } else if (el.classList.contains("lav-avatar")) {
      decora(el, infoLavoro(el), "lav");
    } else if (el.classList.contains("aj-cerchio")) {
      decora(el, JARVIS, "aj");
    } else if (el.classList.contains("chm-avatar")) {
      decora(el, JARVIS, "chm");
    } else if (el.classList.contains("apv-scheda")) {
      const chi = el.querySelector(".apv-capo > .apv-chi");
      if (!chi) return;
      const nome = chi.textContent.split(" · ")[0].trim();
      const info = risolvi(nome) || (nome ? { chi: "nome:" + nome, colore: coloreDi(nome), nome } : JARVIS);
      extra(chi.parentElement, chi, info, "dot-apv");
    } else if (el.classList.contains("rg-evento")) {
      const dt = [...el.querySelectorAll(".rg-dettagli dt")].find((x) => x.textContent.trim() === "Agente");
      const testa = el.querySelector(".rg-evento-testa");
      if (!dt || !testa || !dt.nextElementSibling) return;
      const nome = dt.nextElementSibling.textContent.trim();
      const info = risolvi(nome) || (nome ? { chi: "nome:" + nome, colore: coloreDi(nome), nome } : null);
      if (info) extra(testa, testa.querySelector(".rg-fonte"), info, "dot-rg");
    } else if (el.classList.contains("nodo") && el.classList.contains("nota")) {
      const t = el.querySelector(".testo-nota");
      const j = t && /^jarvis(\s|—|-|$)/i.test(t.textContent.trim());
      const x = el.querySelector(":scope > .dot-extra");
      if (j) extra(el, null, JARVIS, "dot-nota-jarvis");
      else if (x) x.remove();
    }
  }
  const SEL = ".avatar, .lav-avatar, .aj-cerchio, .chm-avatar, .apv-scheda, .rg-evento, .nodo.nota";
  const SEL_SU = ".nodo.nota, .apv-scheda, .rg-evento";
  function scansiona(radiceDom) {
    if (radiceDom.nodeType !== 1) return;
    if (radiceDom.matches(SEL)) guarda(radiceDom);
    for (const el of radiceDom.querySelectorAll(SEL)) guarda(el);
  }
  const mo = new MutationObserver((righe) => {
    const visti = new Set();
    for (const r of righe) {
      const t = r.target;
      // i nodi aggiunti da qui (immagine, iniziali) non vanno riguardati
      let solo = true;
      for (const n of r.addedNodes) {
        if (n.nodeType !== 1) { if (n.nodeType === 3) solo = false; continue; }
        if (n.classList.contains("dot-img") || n.classList.contains("dot-ini") || n.classList.contains("dot-extra")) continue;
        solo = false;
        if (!visti.has(n)) { visti.add(n); try { scansiona(n); } catch (e) { /* una vista strana non ferma le altre */ } }
      }
      if (solo && !r.removedNodes.length) continue;
      if (t.nodeType === 1 && !visti.has(t)) {
        // un host a cui qualcuno ha riscritto il contenuto (textContent), o un testo dentro una nota/scheda
        if (t.matches(SEL)) { visti.add(t); try { guarda(t); } catch (e) { /* niente */ } }
        else { const su = t.closest(SEL_SU); if (su && !visti.has(su)) { visti.add(su); try { guarda(su); } catch (e) { /* niente */ } } }
      }
    }
  });

  function aggiornaErrori() {
    const prima = [...errori].join("|");
    errori = inErrore();
    if ([...errori].join("|") === prima) return;
    for (const h of document.querySelectorAll(".dot-host[data-dot-chi]")) segnaAllarme(h, h.dataset.dotChi);
  }

  // ---------------------------------------------------------------- il controllo «Avatar»
  const gruppi = [];
  function crea(tag, attr = {}, testo) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attr)) e.setAttribute(k, v);
    if (testo != null) e.textContent = testo;
    return e;
  }
  function anteprima(id) {
    const s = crea("span", { class: "dots-anteprima", "aria-hidden": "true" });
    if (id === "dots") {
      for (const c of ["purple", "mint", "orange"]) {
        const i = crea("img", { alt: "", width: "18", height: "18", decoding: "async", draggable: "false" });
        blobDi(sorgente(c, 18)).then((b) => { i.src = b; });     // stessa misura delle liste: nessun file in più
        s.append(i);
      }
    } else if (id === "volti") {
      // un volto vero, con le funzioni di app.js; senza, tre cerchi
      const svg = g(() => svgBeam("capogruppo", paletteDaColore("#9386f2")));     // eslint-disable-line no-undef
      const i = crea("i", { class: "dots-volto" });
      if (svg) i.innerHTML = svg;
      s.append(i);
    } else {
      s.append(crea("i", { class: "dots-lettere" }, "AB"));
    }
    return s;
  }
  function gruppo(classe, compatto) {
    const gr = crea("div", { class: classe, role: "radiogroup", "aria-label": "Avatar degli agenti" });
    for (const m of MODI) {
      const b = crea("button", { type: "button", class: "tema-voce dots-voce", role: "radio", "aria-checked": "false", "data-avatar": m.id,
        tabindex: "-1", "aria-label": `${m.nome}: ${m.nota}` });
      const testi = crea("span");
      testi.append(crea("b", {}, m.nome));
      if (!compatto) testi.append(crea("small", {}, m.nota));
      b.append(anteprima(m.id), testi, crea("span", { class: "tema-segno", "aria-hidden": "true" }, "✓"));
      gr.append(b);
    }
    gr.addEventListener("click", (ev) => {
      const b = ev.target.closest(".dots-voce");
      if (!b) return;
      scegli(b.dataset.avatar);
      b.focus();
    });
    gr.addEventListener("keydown", (ev) => {
      const voci = [...gr.querySelectorAll(".dots-voce")];
      const i = voci.indexOf(document.activeElement);
      if (i < 0) return;
      let j = null;
      if (ev.key === "ArrowDown" || ev.key === "ArrowRight") j = (i + 1) % voci.length;
      else if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") j = (i - 1 + voci.length) % voci.length;
      else if (ev.key === "Home") j = 0;
      else if (ev.key === "End") j = voci.length - 1;
      else if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); scegli(voci[i].dataset.avatar); return; }
      if (j == null) return;
      ev.preventDefault();
      voci[j].focus();
      scegli(voci[j].dataset.avatar);
    });
    gruppi.push(gr);
    return gr;
  }
  function interruttoreFermi() {
    const l = crea("label", { class: "dots-fermi" });
    const c = crea("input", { type: "checkbox" });
    c.checked = !fermi;
    c.addEventListener("change", () => impostaFermi(!c.checked));
    l.append(c, crea("span", {}, "Dots in movimento"));
    return l;
  }
  function aggiornaControlli() {
    for (const gr of gruppi) {
      for (const b of gr.querySelectorAll(".dots-voce")) {
        const si = b.dataset.avatar === modo;
        b.setAttribute("aria-checked", String(si));
        b.tabIndex = si ? 0 : -1;
      }
    }
    for (const c of document.querySelectorAll(".dots-fermi input")) c.checked = !fermi;
  }

  // nel menu dei temi (temi.js), sotto i temi
  function montaMenuTemi() {
    const menu = document.getElementById("tema-menu");
    if (!menu || menu.querySelector(".dots-sezione")) return !!menu;
    const sez = crea("div", { class: "dots-sezione" });
    sez.append(crea("span", { class: "tema-menu-titolo", id: "dots-menu-titolo" }, "Avatar"), gruppo("tema-gruppo dots-gruppo", false), interruttoreFermi());
    menu.append(sez);
    // Tab dai temi porta qui (temi.js chiude il menu col Tab: qui lo intercetto prima, solo fra i due gruppi)
    menu.addEventListener("keydown", (ev) => {
      if (ev.key !== "Tab") return;
      const temi = menu.querySelector(".tema-gruppo:not(.dots-gruppo)");
      const mio = sez.querySelector(".dots-gruppo");
      const att = document.activeElement;
      let dest = null;
      if (!ev.shiftKey && temi && temi.contains(att)) dest = mio.querySelector('[aria-checked="true"]') || mio.querySelector(".dots-voce");
      else if (!ev.shiftKey && mio.contains(att)) dest = sez.querySelector(".dots-fermi input");
      else if (ev.shiftKey && mio.contains(att) && temi) dest = temi.querySelector('[aria-checked="true"]') || temi.querySelector(".tema-voce");
      else if (ev.shiftKey && att && att.closest(".dots-fermi")) dest = mio.querySelector('[aria-checked="true"]');
      if (!dest) return;
      ev.preventDefault();
      ev.stopPropagation();
      dest.focus();
    }, true);
    aggiornaControlli();
    return true;
  }
  // nel foglio «Altro» del telefono (mobile.js), dopo la riga «Tema»
  function montaFoglio() {
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (!griglia) return false;
    if (griglia.querySelector(".dots-foglio")) return true;
    const box = crea("div", { class: "dots-foglio" });
    box.append(crea("b", {}, "Avatar"), gruppo("dots-foglio-scelte", true), interruttoreFermi());
    griglia.append(box);
    aggiornaControlli();
    return true;
  }
  // senza temi.js: un pulsante tutto mio accanto allo stato generale, sul desktop
  function montaPulsanteMio() {
    const barra = document.querySelector("header.barra");
    if (!barra || barra.querySelector(".dots-btn")) return;
    const btn = crea("button", { type: "button", class: "icona dots-btn", "aria-haspopup": "true", "aria-expanded": "false", "aria-controls": "dots-menu",
      "aria-label": "Avatar degli agenti", title: "Avatar degli agenti" });
    const ib = crea("img", { alt: "", width: "18", height: "18", decoding: "async" });
    blobDi(sorgente("purple", 18)).then((b) => { ib.src = b; });
    btn.append(ib);
    const menu = crea("div", { class: "tema-menu dots-menu", id: "dots-menu", hidden: "" });
    menu.append(crea("span", { class: "tema-menu-titolo" }, "Avatar"), gruppo("tema-gruppo dots-gruppo", false), interruttoreFermi());
    document.body.append(menu);
    barra.insertBefore(btn, barra.querySelector(".stato-generale") || null);
    const apri = (si) => {
      menu.hidden = !si;
      btn.setAttribute("aria-expanded", String(si));
      if (!si) return;
      const r = btn.getBoundingClientRect();
      menu.style.top = Math.round(r.bottom + 6) + "px";
      menu.style.left = Math.round(Math.max(8, Math.min(r.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))) + "px";
      (menu.querySelector('[aria-checked="true"]') || menu.querySelector(".dots-voce")).focus();
    };
    btn.addEventListener("click", () => apri(menu.hidden));
    menu.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { ev.preventDefault(); apri(false); btn.focus(); } });
    document.addEventListener("pointerdown", (ev) => { if (!menu.hidden && !menu.contains(ev.target) && !btn.contains(ev.target)) apri(false); }, true);
    window.addEventListener("resize", () => apri(false));
    aggiornaControlli();
  }

  // ---------------------------------------------------------------- scelta
  function scegli(m) {
    if (!valido(m)) return;
    modo = m;
    try { if (m === "dots") localStorage.removeItem(CHIAVE); else localStorage.setItem(CHIAVE, m); } catch (e) { /* resta per questa pagina */ }
    radice.setAttribute("data-avatar", m);
    if (m === "dots") for (const h of document.querySelectorAll(".dot-host")) misuraPoi(h);   // le misure prese mentre erano nascoste
    aggiornaControlli();
    try { window.dispatchEvent(new CustomEvent("cc-avatar", { detail: { avatar: m } })); } catch (e) { /* niente */ }
  }
  function impostaFermi(si) {
    fermi = !!si;
    try { if (fermi) localStorage.setItem(CHIAVE_FERMI, "1"); else localStorage.removeItem(CHIAVE_FERMI); } catch (e) { /* niente */ }
    radice.toggleAttribute("data-dots-fermi", fermi);
    aggiornaControlli();
  }

  // ---------------------------------------------------------------- avvio
  function avvia() {
    errori = inErrore();
    scansiona(document.body);
    mo.observe(document.body, { childList: true, subtree: true });
    if (!montaMenuTemi()) {
      // temi.js parte dopo di me (stesso defer, ordine di index.html) o non c'è: aspetto il suo menu un attimo
      setTimeout(() => { if (!montaMenuTemi() && !window.CCTemi) montaPulsanteMio(); }, 0);
    }
    if (!montaFoglio()) {
      const os = new MutationObserver(() => { if (montaFoglio()) os.disconnect(); });
      os.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => os.disconnect(), 10000);
    }
    setInterval(aggiornaErrori, 10000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia, { once: true });
  else avvia();
  // la riga «Tema» del foglio la mette temi.js: la mia va dopo, quindi se arriva dopo la sposto in fondo
  window.addEventListener("load", () => {
    const f = document.querySelector("#m-foglio .m-foglio-griglia .dots-foglio");
    if (f && f.nextElementSibling) f.parentElement.append(f);
    montaMenuTemi();
  });
  // un'altra scheda ha cambiato preferenza
  window.addEventListener("storage", (ev) => {
    if (ev.key === CHIAVE || ev.key === null) { const m = leggi(); if (m !== modo) scegli(m); }
    if (ev.key === CHIAVE_FERMI || ev.key === null) impostaFermi(leggiFermi());
  });

  window.CCDots = {
    colore: coloreDi,
    modo: () => modo,
    elenco: () => MODI.map((m) => m.id),
    scegli,
    fermi: (si) => { if (si === undefined) return fermi; impostaFermi(si); return fermi; },
    allarme: (chi, si = true) => { FORZATI.set(String(chi), !!si); errori = new Set(["\u0000"]); aggiornaErrori(); },
    risolvi,
    avvolta: () => !!originale && window.avatar !== originale,
  };
})();
