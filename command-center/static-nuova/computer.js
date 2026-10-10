// Gli «occhi» di Jarvis nella web app (2026-10-03): lo schermo del Mac visto dal telefono, in SOLA VISIONE.
// Contratto: command-center/CONTRATTO-approvazioni.md, sezione 3. Va con computer.css; aggancio in INTEGRA-COMPUTER.md.
//
// Vale SOLO dentro il ponte (cc-ponte sulla VPS): all'avvio chiede /_ponte/stato e, se non risponde 200 con il
// campo «schermo», non fa niente (sul Mac locale non compare nulla e non parte nessun'altra richiesta).
// Dentro il ponte aggiunge la pagina «Schermo» (#schermo) al menu in alto e al foglio «Altro» del telefono.
//
// Cosa mostra:
//  - ponte con lo schermo «spento» (manca /etc/cc-ponte/schermo-on): la spiegazione e come si accende;
//  - acceso ma il Mac non concede la cattura (503): il passo da fare in Impostazioni di Sistema;
//  - altrimenti lo schermo, riletto ogni 2 s con fetch + X-Token (il ponte non accetta ?token=),
//    mostrato con URL.createObjectURL e l'URL precedente revocato. Un solo fetch in volo; si ferma con la
//    scheda del browser nascosta, fuori da #schermo, in pausa o dopo «Nascondi» (che interrompe anche il
//    fetch in corso). Qualità piccola/media/grande (640/960/1280 px, ricordata nel browser), zoom con due
//    dita, doppio tocco e trascinamento, schermo intero;
//  - sotto: «Cosa sta facendo Jarvis» (GET /api/computer/stato → ultimo_lavoro → GET /api/lavoro/<id>) e gli
//    ultimi file toccati, solo come testo (mai aperti).
// Niente clic né tasti sul Mac: nessun controllo remoto. Testi sempre con textContent.
(function computer() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STATO_PONTE = "/_ponte/stato";
  const QUALITA = [["piccola", 640], ["media", 960], ["grande", 1280]];
  const CHIAVE_QUALITA = "cc.schermo.qualita";
  const PASSO_MS = 2000, PASSO_ATTESA_MS = 10000, PASSO_INFO_MS = 5000, PASSO_PONTE_MS = 15000, TETTO_MS = 15000;
  const ZOOM_MAX = 5;
  const TIPI = {
    leggo: ["◧", "Lettura"], scrivo: ["✎", "Scrittura"], lancio: ["▶", "Comando"], cerco: ["⌕", "Ricerca"],
    web: ["◍", "Web"], agente: ["◉", "Agente"], penso: ["…", "Ragiono"],
  };
  const ESITI = { "in corso": "in corso", ok: "fatto", errore: "errore" };

  // stato della pagina (si legge anche dalle prove: window.CCComputer)
  const S = {
    ponte: null, modo: "attesa", messaggio: "", pausa: false, nascosto: false,
    inVolo: null, timer: null, url: null, vivi: new Set(), creati: 0, revocati: 0,
    richieste: 0, maxInVolo: 0, inVoloOra: 0, ultimo: 0, infoTimer: null, ponteTimer: null, tick: null,
    zoom: { z: 1, x: 0, y: 0 },
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
  const memoria = {
    leggi(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } },
    scrivi(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* navigazione privata: resta per questa visita */ } },
  };

  async function leggiPonte() {
    try {
      const r = await fetch(STATO_PONTE, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
      if (r.status !== 200) return null;
      const d = await r.json();
      return d && d.ponte === true && typeof d.schermo === "string" ? d : null;
    } catch (e) {
      return null;
    }
  }

  // ---------------------------------------------------------------- pagina e voce di menu
  const N = {};
  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="schermo"]')) {
      const a = el("a", { href: "#schermo", "data-vista": "schermo", title: "Lo schermo del Mac, in sola visione" },
        el("i", { class: "spia grigia" }), "Schermo");
      const prima = menu.querySelector('a[data-vista="lavagna"]');
      if (prima) menu.insertBefore(a, prima); else menu.append(a);
    }
    // il foglio «Altro» del telefono (mobile.js) si costruisce all'avvio dalle voci del menu: questa arriva dopo
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="schermo"]')) {
      const b = el("a", { href: "#schermo", "data-vista": "schermo" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "▣"),
        el("span", {}, "Schermo"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    // app.js mostra solo le viste che conosce (TITOLI): questa si aggiunge qui, senza toccare app.js
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.schermo) TITOLI.schermo = "Schermo"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }

  function creaVista() {
    const main = document.querySelector("main");
    if (!main) return false;
    N.avviso = el("div", { class: "pc-avviso", role: "note" },
      el("span", { class: "pc-avviso-ico", "aria-hidden": "true" }, "!"),
      el("p", {}, el("b", {}, "Questo è il tuo schermo reale: chiunque abbia accesso al sito lo vede."), " ",
        el("span", {}, "Sola visione: da qui non si clicca e non si scrive sul Mac.")),
      N.nascondi = el("button", { type: "button", class: "pc-nascondi", onclick: () => nascondi(!S.nascosto) }, "Nascondi"));

    N.dot = el("span", { class: "pc-dot", "aria-hidden": "true" });
    N.diretta = el("span", { class: "pc-diretta" }, "ferma");
    N.eta = el("span", { class: "pc-eta" }, "");
    N.pausa = el("button", { type: "button", class: "pc-btn", "aria-pressed": "false", onclick: () => pausa(!S.pausa) }, "Pausa");
    N.qualita = el("select", { id: "pc-qualita", class: "pc-select" },
      ...QUALITA.map(([nome, w]) => el("option", { value: nome }, `${nome[0].toUpperCase() + nome.slice(1)} (${w} px)`)));
    const q = memoria.leggi(CHIAVE_QUALITA, "media");
    N.qualita.value = QUALITA.some(([n]) => n === q) ? q : "media";
    N.qualita.addEventListener("change", () => { memoria.scrivi(CHIAVE_QUALITA, N.qualita.value); if (vivo()) avanti(0); });
    N.intero = el("button", { type: "button", class: "pc-btn", "aria-pressed": "false", onclick: () => schermoIntero() }, "Schermo intero");
    const barra = el("div", { class: "pc-barra" },
      el("span", { class: "pc-stato", role: "status", "aria-live": "polite" }, N.dot, N.diretta, N.eta),
      el("span", { class: "pc-comandi" }, N.pausa,
        el("span", { class: "pc-q" }, el("label", { class: "pc-etichetta", for: "pc-qualita" }, "Qualità"), N.qualita), N.intero));

    N.img = el("img", { class: "pc-img", alt: "Schermo del Mac", draggable: "false", decoding: "async" });
    N.cornice = el("div", { class: "pc-cornice", tabindex: "0", "aria-label": "Schermo del Mac: due dita o doppio tocco per ingrandire, trascina per muoverti" }, N.img);
    N.esci = el("button", { type: "button", class: "pc-esci-intero", onclick: () => schermoIntero(false) }, "Chiudi schermo intero");
    N.vela = el("div", { class: "pc-vela" });          // spento, permesso, nascosto, errori: sopra la cornice
    N.zoomMeno = el("button", { type: "button", class: "pc-btn pc-z", "aria-label": "Rimpicciolisci", onclick: () => zoomA(S.zoom.z / 1.5) }, "−");
    N.zoomTesto = el("button", { type: "button", class: "pc-btn pc-z pc-z-testo", "aria-label": "Torna al 100%", onclick: () => zoomA(1) }, "100%");
    N.zoomPiu = el("button", { type: "button", class: "pc-btn pc-z", "aria-label": "Ingrandisci", onclick: () => zoomA(S.zoom.z * 1.5) }, "+");
    N.schermo = el("div", { class: "pc-schermo" }, N.cornice, N.vela, N.esci);
    const zoomRiga = el("div", { class: "pc-zoom" }, el("span", { class: "pc-zoom-tasti" }, N.zoomMeno, N.zoomTesto, N.zoomPiu),
      el("small", { class: "pc-sola" }, "Sola visione · niente clic né tasti sul Mac"));

    N.lavoro = el("div", { class: "pc-lavoro" }, el("p", { class: "pc-vuoto" }, "lettura…"));
    N.file = el("ol", { class: "pc-file" });
    N.fileVuoto = el("p", { class: "pc-vuoto" }, "lettura…");

    N.vista = el("section", { class: "vista vista-schermo", "data-vista": "schermo", "aria-labelledby": "pc-titolo" },
      el("div", { class: "pc-colonna-schermo" },
        N.riq = el("div", { class: "pc-riq pc-riq-schermo" },
          el("h2", { id: "pc-titolo", class: "pc-titolo" }, "Schermo del Mac"),
          N.avviso, barra, N.schermo, zoomRiga)),
      el("div", { class: "pc-colonna-info" },
        el("section", { class: "pc-riq", "aria-labelledby": "pc-t-lavoro" },
          el("h2", { id: "pc-t-lavoro", class: "pc-titolo" }, "Cosa sta facendo Jarvis"), N.lavoro),
        el("section", { class: "pc-riq", "aria-labelledby": "pc-t-file" },
          el("h2", { id: "pc-t-file", class: "pc-titolo" }, "Ultimi file toccati"),
          el("p", { class: "pc-nota" }, "Solo i percorsi: da qui i file non si aprono."), N.fileVuoto, N.file)));
    main.append(N.vista);
    zoomInit();
    return true;
  }

  // ---------------------------------------------------------------- stati della vela sopra lo schermo
  function vela(titolo, ...corpo) {
    N.vela.replaceChildren(el("div", { class: "pc-vela-dentro" }, el("h3", {}, titolo), ...corpo));
    N.vela.hidden = false;
    N.schermo.classList.add("pc-con-vela");
    // senza immagine i comandi dello schermo (pausa, qualità, zoom…) non servono: restano solo avviso e spiegazione
    N.riq.classList.toggle("pc-senza-comandi", !N.schermo.classList.contains("pc-attesa"));
  }
  function togliVela() {
    N.vela.hidden = true; N.vela.replaceChildren();
    N.schermo.classList.remove("pc-con-vela"); N.riq.classList.remove("pc-senza-comandi");
  }
  const codice = (t) => el("code", { class: "pc-codice" }, t);
  const bottone = (testo, fn, classe = "pc-btn") => el("button", { type: "button", class: classe, onclick: fn }, testo);

  function disegna() {
    if (!N.vista) return;
    const m = S.modo;
    N.vista.dataset.modo = m;
    const acceso = S.ponte && S.ponte.schermo === "acceso";
    N.schermo.classList.toggle("pc-attesa", !!acceso && !S.nascosto && m === "attesa" && !S.url);
    N.nascondi.hidden = !acceso;
    for (const b of [N.pausa, N.qualita, N.intero, N.zoomMeno, N.zoomPiu, N.zoomTesto]) b.disabled = !acceso || S.nascosto;
    N.nascondi.textContent = S.nascosto ? "Mostra di nuovo" : "Nascondi";
    N.nascondi.setAttribute("aria-pressed", String(S.nascosto));
    N.nascondi.disabled = !acceso;
    N.pausa.textContent = S.pausa ? "Riprendi" : "Pausa";
    N.pausa.setAttribute("aria-pressed", String(S.pausa));
    aggiornaEta();
    if (!acceso) {
      // anche /api/computer/stato è dietro l'interruttore: niente «lettura…» che non arriva mai
      N.lavoro.replaceChildren(el("p", { class: "pc-vuoto" }, "Si vede quando lo schermo è acceso."));
      N.file.replaceChildren();
      N.fileVuoto.hidden = false;
      N.fileVuoto.textContent = "Si vedono quando lo schermo è acceso.";
      vela("Lo schermo è spento",
        el("p", {}, "Da internet lo schermo del Mac non si vede finché l'utente non lo accende sul server (VPS). È spento di proposito: è lo schermo vero."),
        el("p", {}, "Per accenderlo, sulla VPS: ", codice("touch /etc/cc-ponte/schermo-on")),
        el("p", {}, "Per spegnerlo: ", codice("rm /etc/cc-ponte/schermo-on")),
        S.ponte && S.ponte.comandi === "spenti"
          ? el("p", { class: "pc-attenzione" }, "Adesso è acceso anche l'interruttore di emergenza (comandi-off): finché c'è, lo schermo resta spento.")
          : null,
        el("p", { class: "pc-nota" }, "Questa pagina lo ricontrolla da sola ogni 15 secondi."));
      return;
    }
    if (S.nascosto) {
      vela("Schermo nascosto", el("p", {}, "Non scarico più lo schermo. L'ultima immagine è stata tolta."),
        bottone("Mostra di nuovo", () => nascondi(false), "pc-btn pc-primario"));
      return;
    }
    if (m === "permesso") {
      vela("Il Mac non concede la cattura dello schermo",
        el("p", {}, "Il programma che fa girare il Command Center non ha il permesso «Registrazione schermo». Lo dà l'utente, sul Mac:"),
        el("ol", { class: "pc-passi" },
          el("li", {}, "apri Impostazioni di Sistema → Privacy e sicurezza → Registrazione schermo (e audio di sistema);"),
          el("li", {}, "accendi l'interruttore di «python3» (o «Python»): è il programma che lancia il Command Center (launchd, /opt/homebrew/bin/python3). Se non è in elenco, premi «+» e sceglilo;"),
          el("li", {}, "macOS chiede di riaprire il programma: riavvia il Command Center dal Mac;"),
          el("li", {}, "torna qui e tocca «Riprova».")),
        S.messaggio ? el("p", { class: "pc-nota" }, "Messaggio del Mac: " + corto(S.messaggio, 240)) : null,
        bottone("Riprova", () => { S.modo = "attesa"; disegna(); avanti(0); }, "pc-btn pc-primario"));
      return;
    }
    if (m === "bloccato") {
      vela("Il Mac è bloccato", el("p", {}, "Lo schermo si vede quando il Mac viene sbloccato. Riprovo da solo ogni 10 secondi."));
      return;
    }
    if (m === "sessione") {
      vela("Sessione scaduta", el("p", {}, "Per rivedere lo schermo rientra con password e codice."),
        el("a", { class: "pc-btn pc-primario", href: "/_ponte/entra" }, "Rientra"));
      return;
    }
    if (m === "token") {
      vela("Il Command Center è ripartito", el("p", {}, "Il Mac ha riavviato il pannello: ricarica la pagina per continuare."),
        bottone("Ricarica la pagina", () => location.reload(), "pc-btn pc-primario"));
      return;
    }
    if (m === "errore" || m === "rete") {
      vela(m === "rete" ? "Connessione assente" : "Schermo non disponibile adesso",
        el("p", {}, S.messaggio || "Il Mac non risponde."), el("p", { class: "pc-nota" }, "Riprovo da solo ogni 10 secondi."));
      return;
    }
    if (m === "attesa" && !S.url) { vela("Collego lo schermo…", el("p", { class: "pc-nota" }, "Il primo fotogramma arriva in un paio di secondi.")); return; }
    togliVela();
  }

  function aggiornaEta() {
    if (!N.eta) return;
    const acceso = S.ponte && S.ponte.schermo === "acceso";
    const s = S.ultimo ? Math.max(0, Math.round((Date.now() - S.ultimo) / 1000)) : null;
    const diretta = acceso && !S.pausa && !S.nascosto && S.modo === "diretta" && s != null && s < 8 && attiva();
    N.dot.className = "pc-dot " + (diretta ? "pc-dot-diretta" : "pc-dot-ferma");
    N.diretta.textContent = diretta ? "in diretta" : S.pausa ? "ferma (pausa)" : "ferma";
    N.eta.textContent = s == null || S.nascosto ? "" : ` · aggiornato ${s} s fa`;
  }

  // ---------------------------------------------------------------- lo schermo
  const attiva = () => location.hash === "#schermo" && !document.hidden;
  const vivo = () => attiva() && S.ponte && S.ponte.schermo === "acceso" && !S.pausa && !S.nascosto
    && !["permesso", "sessione", "token"].includes(S.modo);
  const larghezza = () => (QUALITA.find(([n]) => n === N.qualita.value) || QUALITA[1])[1];

  function avanti(ms) {
    clearTimeout(S.timer);
    S.timer = null;
    if (vivo()) S.timer = setTimeout(giro, ms);
  }
  function ferma() {
    clearTimeout(S.timer);
    S.timer = null;
    if (S.inVolo) { try { S.inVolo.abort(); } catch (e) { /* già chiusa */ } }
  }
  async function giro() {
    S.timer = null;
    if (!vivo() || S.inVolo) return;              // un solo fetch in volo
    const t0 = Date.now();
    await scarica();
    const lento = ["bloccato", "errore", "rete"].includes(S.modo);
    avanti(lento ? PASSO_ATTESA_MS : Math.max(250, PASSO_MS - (Date.now() - t0)));
  }
  function revoca(u) { if (u && S.vivi.delete(u)) { URL.revokeObjectURL(u); S.revocati++; } }
  function mostraImmagine(blob) {
    const u = URL.createObjectURL(blob);
    S.vivi.add(u); S.creati++;
    const vecchio = S.url;
    S.url = u;
    N.img.src = u;
    const via = () => { if (vecchio && vecchio !== S.url) revoca(vecchio); };
    if (N.img.decode) N.img.decode().then(via, via); else setTimeout(via, 0);
    N.img.alt = "Schermo del Mac alle " + new Date().toLocaleTimeString("it-IT");
  }
  function togliImmagine() {
    N.img.removeAttribute("src");
    const u = S.url;
    S.url = null;
    revoca(u);
    for (const x of [...S.vivi]) revoca(x);
  }
  async function scarica() {
    const ctl = new AbortController();
    S.inVolo = ctl; S.richieste++; S.inVoloOra++; S.maxInVolo = Math.max(S.maxInVolo, S.inVoloOra);
    const tetto = setTimeout(() => ctl.abort(), TETTO_MS);
    try {
      const r = await fetch("/api/computer/schermo?w=" + larghezza(), {
        headers: { "X-Token": token(), Accept: "image/jpeg" }, cache: "no-store", credentials: "same-origin", signal: ctl.signal });
      if (r.status === 200 && /^image\/jpeg/.test(r.headers.get("Content-Type") || "")) {
        const blob = await r.blob();
        if (S.inVolo !== ctl || S.nascosto || !attiva()) return;      // nascosto o uscito nel frattempo: si butta
        mostraImmagine(blob);
        S.ultimo = Date.now(); S.modo = "diretta"; S.messaggio = "";
      } else {
        let d = {};
        try { d = await r.json(); } catch (e) { /* non JSON */ }
        errore(r.status, d || {});
      }
    } catch (e) {
      if (ctl.signal.aborted) { if (!S.nascosto && attiva() && !S.pausa) { S.modo = "rete"; S.messaggio = "Il Mac ci mette troppo a rispondere."; } }
      else { S.modo = "rete"; S.messaggio = "Il telefono non raggiunge il sito adesso."; }
    } finally {
      clearTimeout(tetto);
      S.inVoloOra--;
      if (S.inVolo === ctl) S.inVolo = null;
      disegna();
    }
  }
  function errore(stato, d) {
    const msg = typeof d.errore === "string" ? d.errore : "";
    S.messaggio = msg;
    if (stato === 403 && (d.schermo === "spento" || /spento/i.test(msg))) { spento(); return; }
    if (stato === 403 && d.token_scaduto) { S.modo = "token"; return; }
    if (stato === 401) { S.modo = "sessione"; return; }
    if (stato === 429) return;                                        // il ponte ne tiene già 2: al prossimo giro
    if (stato === 503 && /permess|registrazione/i.test(msg)) { S.modo = "permesso"; return; }
    if (stato === 503 && /bloccat/i.test(msg)) { S.modo = "bloccato"; return; }
    S.modo = "errore";
    if (!msg) S.messaggio = stato === 503 ? "Il Mac non è raggiungibile adesso." : "Risposta inattesa dal Mac (" + stato + ").";
  }
  function spento() {
    if (S.ponte) S.ponte.schermo = "spento";
    S.modo = "attesa";
    ferma();
    togliImmagine();
    S.ultimo = 0;
    pianificaPonte();
  }

  function pausa(si) {
    S.pausa = !!si;
    if (S.pausa) ferma(); else avanti(0);
    disegna();
  }
  function nascondi(si) {
    S.nascosto = !!si;
    if (S.nascosto) { ferma(); togliImmagine(); S.ultimo = 0; zoomA(1); schermoIntero(false); }
    else { S.modo = "attesa"; avanti(0); }
    disegna();
  }

  // ---------------------------------------------------------------- schermo intero
  function schermoIntero(si) {
    const dentro = document.fullscreenElement === N.schermo || N.schermo.classList.contains("pc-intero");
    const vuole = si === undefined ? !dentro : si;
    if (vuole === dentro) return;
    if (vuole) {
      const pieno = N.schermo.requestFullscreen || N.schermo.webkitRequestFullscreen;
      // iPhone non ha lo schermo intero degli elementi: lì si copre la pagina
      if (pieno) Promise.resolve(pieno.call(N.schermo)).catch(() => N.schermo.classList.add("pc-intero")).finally(statoIntero);
      else N.schermo.classList.add("pc-intero");
    } else {
      N.schermo.classList.remove("pc-intero");
      if (document.fullscreenElement === N.schermo && document.exitFullscreen) document.exitFullscreen().catch(() => {});
    }
    statoIntero();
  }
  function statoIntero() {
    const dentro = document.fullscreenElement === N.schermo || N.schermo.classList.contains("pc-intero");
    N.intero.setAttribute("aria-pressed", String(dentro));
    N.intero.textContent = dentro ? "Esci da schermo intero" : "Schermo intero";
    document.body.classList.toggle("pc-intero-aperto", N.schermo.classList.contains("pc-intero"));
    requestAnimationFrame(() => zoomA(S.zoom.z));
  }

  // ---------------------------------------------------------------- zoom: due dita, doppio tocco, trascinamento
  function zoomApplica() {
    const { z, x, y } = S.zoom;
    N.img.style.transform = z === 1 ? "" : `translate(${x}px, ${y}px) scale(${z})`;
    N.cornice.classList.toggle("pc-zoomato", z > 1.001);
    N.zoomTesto.textContent = Math.round(z * 100) + "%";
  }
  function limita() {
    const r = N.cornice.getBoundingClientRect(), z = S.zoom;
    z.x = Math.min(0, Math.max(r.width - r.width * z.z, z.x));
    z.y = Math.min(0, Math.max(r.height - r.height * z.z, z.y));
  }
  function zoomA(z2, cx, cy) {
    const r = N.cornice.getBoundingClientRect(), z = S.zoom;
    z2 = Math.max(1, Math.min(ZOOM_MAX, z2 || 1));
    if (cx == null) { cx = r.width / 2; cy = r.height / 2; }
    const px = (cx - z.x) / z.z, py = (cy - z.y) / z.z;      // il punto sotto le dita resta sotto le dita
    z.z = z2; z.x = cx - px * z2; z.y = cy - py * z2;
    if (z2 === 1) { z.x = 0; z.y = 0; }
    limita();
    zoomApplica();
  }
  function zoomInit() {
    const dita = new Map();
    let pinza = null, trascina = null, ultimoTocco = null, zoomDaTocco = 0;
    const loc = (ev) => { const r = N.cornice.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; };
    N.cornice.addEventListener("pointerdown", (ev) => {
      if (ev.button !== undefined && ev.button > 0) return;
      dita.set(ev.pointerId, loc(ev));
      try { N.cornice.setPointerCapture(ev.pointerId); } catch (e) { /* niente */ }
      if (dita.size === 2) {
        const [a, b] = dita.values();
        pinza = { d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, z0: S.zoom.z, mosso: false };
        trascina = null;
      } else if (dita.size === 1) {
        trascina = { x0: ev.clientX, y0: ev.clientY, zx: S.zoom.x, zy: S.zoom.y, mosso: false };
      }
    });
    N.cornice.addEventListener("pointermove", (ev) => {
      if (!dita.has(ev.pointerId)) return;
      dita.set(ev.pointerId, loc(ev));
      if (pinza && dita.size >= 2) {
        const [a, b] = dita.values();
        const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        pinza.mosso = true;
        ev.preventDefault();
        zoomA(pinza.z0 * d / pinza.d0, (a.x + b.x) / 2, (a.y + b.y) / 2);
      } else if (trascina && S.zoom.z > 1.001) {
        const dx = ev.clientX - trascina.x0, dy = ev.clientY - trascina.y0;
        if (Math.abs(dx) + Math.abs(dy) > 4) trascina.mosso = true;
        ev.preventDefault();
        S.zoom.x = trascina.zx + dx; S.zoom.y = trascina.zy + dy;
        limita(); zoomApplica();
      } else if (trascina && Math.abs(ev.clientX - trascina.x0) + Math.abs(ev.clientY - trascina.y0) > 10) trascina.mosso = true;
    });
    const fine = (ev) => {
      if (!dita.has(ev.pointerId)) return;
      const p = dita.get(ev.pointerId);
      dita.delete(ev.pointerId);
      if (pinza) { if (dita.size < 2) { pinza = null; trascina = null; ultimoTocco = null; } return; }
      if (ev.type === "pointerup" && ev.pointerType !== "mouse" && trascina && !trascina.mosso) {
        // doppio tocco (o doppio clic): 2,5x dove si tocca, oppure di nuovo 100%
        const ora = Date.now();
        if (ultimoTocco && ora - ultimoTocco.t < 350 && Math.hypot(p.x - ultimoTocco.x, p.y - ultimoTocco.y) < 30) {
          zoomA(S.zoom.z > 1.001 ? 1 : 2.5, p.x, p.y);
          ultimoTocco = null;
          zoomDaTocco = Date.now();
        } else ultimoTocco = { t: ora, x: p.x, y: p.y };
      }
      trascina = null;
    };
    // col mouse il doppio clic è quello del sistema (rispetta la velocità scelta in macOS/Windows)
    // (il browser del telefono manda un dblclick anche dopo il doppio tocco: quello è già stato gestito sopra)
    N.cornice.addEventListener("dblclick", (ev) => {
      if (Date.now() - zoomDaTocco < 800) return;
      const p = loc(ev); zoomA(S.zoom.z > 1.001 ? 1 : 2.5, p.x, p.y);
    });
    N.cornice.addEventListener("pointerup", fine);
    N.cornice.addEventListener("pointercancel", fine);
    N.cornice.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey && S.zoom.z <= 1.001) return;           // senza zoom la rotella scorre la pagina
      ev.preventDefault();
      const p = loc(ev);
      if (ev.ctrlKey) zoomA(S.zoom.z * Math.exp(-ev.deltaY / 300), p.x, p.y);
      else { S.zoom.x -= ev.deltaX; S.zoom.y -= ev.deltaY; limita(); zoomApplica(); }
    }, { passive: false });
    N.cornice.addEventListener("keydown", (ev) => {
      const passo = 40;
      if (ev.key === "+" || ev.key === "=") zoomA(S.zoom.z * 1.25);
      else if (ev.key === "-") zoomA(S.zoom.z / 1.25);
      else if (ev.key === "0") zoomA(1);
      else if (S.zoom.z > 1.001 && /^Arrow/.test(ev.key)) {
        S.zoom.x += ev.key === "ArrowLeft" ? passo : ev.key === "ArrowRight" ? -passo : 0;
        S.zoom.y += ev.key === "ArrowUp" ? passo : ev.key === "ArrowDown" ? -passo : 0;
        limita(); zoomApplica();
      } else return;
      ev.preventDefault();
    });
    window.addEventListener("resize", () => { if (S.zoom.z > 1) zoomA(S.zoom.z); });
  }

  // ---------------------------------------------------------------- cosa sta facendo Jarvis, ultimi file
  async function info() {
    clearTimeout(S.infoTimer);
    S.infoTimer = null;
    if (!attiva() || !S.ponte || S.ponte.schermo !== "acceso" || ["sessione", "token"].includes(S.modo)) return;
    try {
      const r = await fetch("/api/computer/stato", { headers: { "X-Token": token(), Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
      let d = {};
      try { d = await r.json(); } catch (e) { /* non JSON */ }
      if (r.status !== 200) {
        if (r.status === 403 && (d.schermo === "spento" || /spento/i.test(d.errore || ""))) { spento(); disegna(); return; }
        if (r.status === 401) { S.modo = "sessione"; disegna(); return; }
        if (r.status === 403 && d.token_scaduto) { S.modo = "token"; disegna(); return; }
        N.lavoro.replaceChildren(el("p", { class: "pc-vuoto" }, "Non disponibile adesso."));
      } else {
        disegnaFile(Array.isArray(d.ultimi_file) ? d.ultimi_file : []);
        await disegnaLavoro(typeof d.ultimo_lavoro === "string" ? d.ultimo_lavoro : null);
      }
    } catch (e) {
      N.lavoro.replaceChildren(el("p", { class: "pc-vuoto" }, "Connessione assente: riprovo."));
    }
    if (attiva() && S.ponte && S.ponte.schermo === "acceso") S.infoTimer = setTimeout(info, PASSO_INFO_MS);
  }
  const casa = (p) => String(p).replace(/^\/Users\/[^/]+(?=\/|$)/, "~");
  function disegnaFile(lista) {
    const voci = lista.filter((p) => typeof p === "string" && p).slice(0, 10);
    N.fileVuoto.hidden = voci.length > 0;
    N.fileVuoto.textContent = "Nessun file toccato dall'avvio del Command Center.";
    N.file.replaceChildren(...voci.map((p) => {
      const pieno = casa(p), i = pieno.lastIndexOf("/");
      return el("li", { title: pieno }, el("span", { class: "pc-file-dir" }, i > 0 ? pieno.slice(0, i + 1) : ""),
        el("span", { class: "pc-file-nome" }, i >= 0 ? pieno.slice(i + 1) : pieno));
    }));
  }
  async function disegnaLavoro(id) {
    if (!id || !/^[\w-]{1,64}$/.test(id)) {
      N.lavoro.replaceChildren(el("p", { class: "pc-vuoto" }, "Nessun lavoro dall'avvio del Command Center."));
      return;
    }
    let d = null;
    try {
      const r = await fetch("/api/lavoro/" + encodeURIComponent(id), { headers: { "X-Token": token(), Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
      if (r.ok) d = await r.json();
    } catch (e) { /* sotto */ }
    if (!d || typeof d !== "object") { N.lavoro.replaceChildren(el("p", { class: "pc-vuoto" }, "Non leggo l'ultimo lavoro adesso.")); return; }
    const stato = typeof d.stato === "string" ? d.stato : "";
    const voci = (Array.isArray(d.attivita) ? d.attivita : []).filter((v) => v && typeof v === "object" && v.testo != null)
      .slice(-50).sort((a, b) => (Number(a.ts) || 0) - (Number(b.ts) || 0)).slice(-6);
    const testa = el("div", { class: "pc-lavoro-testa" },
      el("b", { class: "pc-lavoro-titolo" }, corto(d.titolo || d.chi || "Lavoro " + id, 140)),
      el("span", { class: "pc-badge pc-b-" + (stato === "in corso" ? "corso" : stato === "errore" ? "errore" : "fatto") }, stato || "—"),
      el("small", { class: "pc-nota" }, [d.chi ? "di " + corto(d.chi, 40) : "", d.inizio ? "dalle " + corto(d.inizio, 10) : ""].filter(Boolean).join(" · ")));
    const lista = voci.length
      ? el("ol", { class: "pc-attivita", "aria-label": "Ultime attività" }, ...voci.map((v, i) => {
        const [segno, parola] = TIPI[v.tipo] || ["•", "Attività"];
        const e = ESITI[v.esito] ? v.esito : "in corso";
        return el("li", { class: "pc-voce pc-e-" + (e === "in corso" ? "corso" : e) + (i === voci.length - 1 ? " pc-ultima" : "") },
          el("span", { class: "pc-ico", "aria-hidden": "true" }, segno), el("span", { class: "pc-sr" }, parola + ": "),
          el("span", { class: "pc-voce-testo" }, corto(v.testo, 140)),
          el("span", { class: "pc-voce-esito" }, el("span", { "aria-hidden": "true" }, e === "ok" ? "✓" : e === "errore" ? "✕" : "…"),
            el("span", { class: "pc-sr" }, " (" + ESITI[e] + ")")));
      }))
      : el("p", { class: "pc-vuoto" }, stato === "in corso" ? "Sta partendo: nessuna attività ancora." : "Nessuna attività registrata per questo lavoro.");
    N.lavoro.replaceChildren(testa, lista);
  }

  // ---------------------------------------------------------------- l'interruttore del ponte, riletto
  function pianificaPonte() {
    clearTimeout(S.ponteTimer);
    S.ponteTimer = attiva() ? setTimeout(rileggiPonte, PASSO_PONTE_MS) : null;
  }
  async function rileggiPonte() {
    S.ponteTimer = null;
    if (!attiva()) return;
    const d = await leggiPonte();
    if (d) {
      const prima = S.ponte && S.ponte.schermo;
      S.ponte = d;
      if (prima !== "acceso" && d.schermo === "acceso") { S.modo = "attesa"; entra(); }
      else if (prima === "acceso" && d.schermo !== "acceso") { spento(); disegna(); }
      else disegna();
    }
    pianificaPonte();
  }

  // ---------------------------------------------------------------- entrata e uscita dalla pagina
  function entra() {
    disegna();
    if (!attiva()) return;
    if (S.ponte.schermo === "acceso") { avanti(0); info(); }
    pianificaPonte();
    clearInterval(S.tick);
    S.tick = setInterval(() => { if (attiva()) aggiornaEta(); }, 1000);
  }
  function esci() {
    ferma();
    // REVISIONE-2 (R7, 2026-10-03): fuori da #schermo o con la scheda nascosta l'ultima immagine non resta in
    // pagina: blob revocato, <img> vuota, variabile azzerata (come «Nascondi»)
    togliImmagine();
    S.ultimo = 0;
    clearTimeout(S.infoTimer); S.infoTimer = null;
    clearTimeout(S.ponteTimer); S.ponteTimer = null;
    clearInterval(S.tick); S.tick = null;
    schermoIntero(false);
    aggiornaEta();
  }
  function cambio() { if (attiva()) entra(); else esci(); }

  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    const d = await leggiPonte();
    if (!d) return;                         // sul Mac (o ponte vecchio senza «schermo»): niente, nessuna richiesta
    S.ponte = d;
    creaVoceMenu();
    if (!creaVista()) return;
    document.documentElement.classList.add("con-schermo");
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    document.addEventListener("fullscreenchange", statoIntero);
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && N.schermo.classList.contains("pc-intero")) schermoIntero(false); });
    // aperta già su #schermo: app.js l'ha portata alla chat perché non la conosceva ancora
    if (location.hash === "#schermo" && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    disegna();
    cambio();
  })();

  window.CCComputer = {
    stato: () => ({ modo: S.modo, schermo: S.ponte && S.ponte.schermo, pausa: S.pausa, nascosto: S.nascosto, richieste: S.richieste,
      inVolo: !!S.inVolo, maxInVolo: S.maxInVolo, creati: S.creati, revocati: S.revocati, vivi: S.vivi.size,
      zoom: Object.assign({}, S.zoom), larghezza: N.qualita ? larghezza() : null, ultimo: S.ultimo }),
  };
})();
