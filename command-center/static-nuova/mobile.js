// Command Center sul telefono (2026-10-03, richiesta dell'utente: «ottimizzata in TUTTE le pagine»).
// Va con mobile.css. Si carica dopo app.js (defer) e ne usa le funzioni globali solo se ci sono.
// Fa quattro cose:
//  1. la barra di schede in basso «Chat · Lavagna · Stato · Altro» e il foglio «Altro», costruiti
//     dalle voci del menu in alto (stesse pagine, stesse spie, stessi contatori: una sola fonte);
//  2. l'altezza della pagina segue la tastiera (visualViewport): il campo della chat resta sopra;
//  3. sulla lavagna lo zoom a due dita (spostare schede e foglio con un dito lo fa già app.js);
//  4. un tocco su un messaggio mostra le sue azioni (copia, modifica, togli), che sul desktop
//     compaiono al passaggio del mouse.
// Sopra 820 px (col mouse) non cambia niente: gli elementi nuovi sono nascosti da mobile.css e qui non si
// tocca nessuno stile della pagina.
(function mobile() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const menu = document.querySelector(".schede.menu");
  if (!app || !menu) return;
  const telefono = matchMedia("(max-width: 820px), (max-height: 500px) and (pointer: coarse)");   // come il blocco «TELEFONO» di mobile.css
  const dito = matchMedia("(max-width: 820px), (max-width: 1100px) and (pointer: coarse)");   // come il blocco «DITO» di mobile.css
  const PRINCIPALI = ["chat", "lavagna", "home"];
  const ICONE = {
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5.5h16v10H9l-5 4z"/></svg>',
    lavagna: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="7" height="5" rx="1.5"/><rect x="14" y="15" width="7" height="5" rx="1.5"/><rect x="14" y="4" width="7" height="5" rx="1.5"/><path d="M10 6.5h4M17.5 9v6"/></svg>',
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 12h4l2.5-6 5 12 2.5-6h4"/></svg>',
    altro: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  };
  const ICONE_FOGLIO = { agenti: "◎", missioni: "◆", scadenze: "⏱", memoria: "❖", server: "▤", telefono: "☏",
    tecnico: "⚙", vps: "⧉", terminale: ">_" };
  const SOLO_MAC = ["terminale", "vps", "tecnico"];   // il ponte li blocca: dal telefono non si aprono
  const voci = () => [...menu.querySelectorAll("a[data-vista]")];
  const nomeVoce = (a) => [...a.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();

  // ------------------------------------------------ 1. barra in basso, foglio «Altro», nome in alto
  const crea = (tag, attrs = {}, html = "") => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (html) n.innerHTML = html;      // solo testo e icone scritti qui sopra, mai dati del server
    return n;
  };
  const marca = crea("span", { class: "m-marca" });
  marca.append(crea("b", {}, "Jarvis"), crea("small", { id: "m-pagina" }));
  const apriLato = $("apri-lato");
  if (apriLato) apriLato.after(marca); else menu.before(marca);

  const barra = crea("nav", { class: "m-schede", "aria-label": "Sezioni principali" });
  const tab = (vista, testo) => {
    const a = crea("a", { href: "#" + vista, "data-m": vista }, ICONE[vista]);
    a.append(crea("span", {}, ""), crea("i", { class: "spia grigia", "aria-hidden": "true" }));
    a.querySelector("span").textContent = testo;
    return a;
  };
  const bAltro = crea("button", { type: "button", "data-m": "altro", "aria-haspopup": "dialog", "aria-expanded": "false" }, ICONE.altro);
  bAltro.append(crea("span", {}, ""), crea("i", { class: "spia grigia", "aria-hidden": "true" }));
  bAltro.querySelector("span").textContent = "Altro";
  barra.append(tab("chat", "Chat"), tab("lavagna", "Lavagna"), tab("home", "Stato"), bAltro);

  const velo = crea("div", { class: "m-foglio-velo" });
  const foglio = crea("div", { class: "m-foglio", role: "dialog", "aria-modal": "true", "aria-label": "Altre pagine", id: "m-foglio" });
  const testa = crea("div", { class: "m-foglio-testa" });
  testa.append(crea("b", {}, "Altre pagine"));
  const chiudi = crea("button", { type: "button", class: "icona", "aria-label": "Chiudi" }, "✕");
  testa.append(chiudi);
  const griglia = crea("div", { class: "m-foglio-griglia" });
  foglio.append(crea("div", { class: "m-foglio-maniglia", "aria-hidden": "true" }), testa, griglia);
  for (const a of voci()) {
    const v = a.dataset.vista;
    if (PRINCIPALI.includes(v)) continue;
    const b = crea("a", { href: "#" + v, "data-vista": v, class: a.classList.contains("tecnico") ? "tecnico" : "" });
    b.append(crea("i", { class: "spia grigia", "aria-hidden": "true" }), crea("span", { class: "m-ico", "aria-hidden": "true" }),
      crea("span", {}), crea("b", { class: "conta" }));
    b.querySelector(".m-ico").textContent = ICONE_FOGLIO[v] || "•";
    b.querySelector("span:not(.m-ico)").textContent = nomeVoce(a);
    if (SOLO_MAC.includes(v)) { const s = crea("small", { class: "m-solo-mac" }); s.textContent = "solo sul Mac"; b.append(s); }
    griglia.append(b);
  }
  const bAgenti = crea("button", { type: "button", class: "m-foglio-largo" });
  bAgenti.append(crea("span", { class: "m-ico", "aria-hidden": "true" }), crea("span"));
  bAgenti.querySelector(".m-ico").textContent = "☰";
  bAgenti.querySelector("span:not(.m-ico)").textContent = "Agenti, motore e nuova chat";
  griglia.append(bAgenti);
  app.append(barra, velo, foglio);

  function apriFoglio(si) {
    foglio.classList.toggle("aperto", si);
    velo.classList.toggle("aperto", si);
    bAltro.setAttribute("aria-expanded", String(si));
    if (si) { const primo = griglia.querySelector("a,button"); if (primo) primo.focus({ preventScroll: true }); }
  }
  bAltro.addEventListener("click", () => apriFoglio(!foglio.classList.contains("aperto")));
  chiudi.addEventListener("click", () => apriFoglio(false));
  velo.addEventListener("click", () => apriFoglio(false));
  griglia.addEventListener("click", (ev) => { if (ev.target.closest("a")) apriFoglio(false); });
  bAgenti.addEventListener("click", () => { apriFoglio(false); app.classList.add("lato-aperto"); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && foglio.classList.contains("aperto")) apriFoglio(false); });
  // un tocco sulla scheda già aperta riporta in cima la pagina (come nelle app)
  barra.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-m]");
    if (!a) return;
    apriFoglio(false);
    if (a.classList.contains("attiva")) { const m = app.querySelector("main"); if (m) m.scrollTo({ top: 0, behavior: "smooth" }); }
  });

  // spie, contatori e scheda attiva: copiati dal menu in alto, che app.js tiene aggiornato
  const PESO = { guasto: 4, attenzione: 3, lavora: 2, ok: 1 };
  const classeSpia = (a) => { const s = a && a.querySelector(".spia"); return s ? s.className : "spia grigia"; };
  function allinea() {
    const attiva = (menu.querySelector("a.attiva") || {}).dataset?.vista || "chat";
    for (const a of barra.querySelectorAll("a[data-m]")) {
      const v = a.dataset.m;
      a.classList.toggle("attiva", v === attiva);
      if (v === attiva) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      a.querySelector("i").className = classeSpia(menu.querySelector(`a[data-vista="${v}"]`));
    }
    let peggiore = "", p = 0;
    for (const b of griglia.querySelectorAll("a[data-vista]")) {
      const orig = menu.querySelector(`a[data-vista="${b.dataset.vista}"]`);
      const c = classeSpia(orig);
      b.querySelector("i").className = c;
      const conta = orig && orig.querySelector(".conta");
      b.querySelector(".conta").textContent = conta ? conta.textContent : "";
      b.classList.toggle("attiva", b.dataset.vista === attiva);
      for (const [k, w] of Object.entries(PESO)) if (c.includes(k) && w > p) { p = w; peggiore = k; }
    }
    bAltro.classList.toggle("attiva", !PRINCIPALI.includes(attiva));
    bAltro.querySelector("i").className = "spia " + (peggiore || "grigia");
    const titolo = $("vista-titolo");
    $("m-pagina").textContent = titolo ? titolo.textContent : "";
  }
  new MutationObserver(allinea).observe(menu, { subtree: true, attributes: true, attributeFilter: ["class"], childList: true, characterData: true });
  const h1 = $("vista-titolo");
  if (h1) new MutationObserver(allinea).observe(h1, { childList: true, characterData: true, subtree: true });
  window.addEventListener("hashchange", () => { apriFoglio(false); allinea(); });
  allinea();

  // ------------------------------------------------ 2. tastiera: la pagina è alta quanto la parte visibile
  const vv = window.visualViewport;
  let altezzaPiena = 0, orientamento = screen.orientation ? screen.orientation.type : "";
  const campoAttivo = () => {
    const a = document.activeElement;
    return !!a && (a.isContentEditable || a.tagName === "TEXTAREA" || a.tagName === "SELECT"
      || (a.tagName === "INPUT" && !/^(checkbox|radio|range|button|submit|color)$/.test(a.type)));
  };
  function altezza() {
    const root = document.documentElement;
    if (!telefono.matches) {
      if (root.style.getPropertyValue("--app-h")) { root.style.removeProperty("--app-h"); root.style.removeProperty("--vv-top"); }
      document.body.classList.remove("tastiera");
      return;
    }
    const o = screen.orientation ? screen.orientation.type : "";
    if (o !== orientamento) { orientamento = o; altezzaPiena = 0; }
    const h = vv ? vv.height : innerHeight;
    const campo = campoAttivo();
    if (!campo) altezzaPiena = Math.max(altezzaPiena, h, innerHeight);
    root.style.setProperty("--app-h", Math.round(h) + "px");
    root.style.setProperty("--vv-top", Math.round(vv ? vv.offsetTop : 0) + "px");
    const tastiera = campo && altezzaPiena > 0 && h < altezzaPiena - 120;
    document.body.classList.toggle("tastiera", tastiera);
    // Lavagna, VPS e Terminale a pagina intera partono sotto la barra in alto (paginaIntera in app.js)
    if (app.classList.contains("destra-intera")) {
      const b = document.querySelector(".barra"), d = $("destra");
      if (b && d) d.style.top = b.getBoundingClientRect().height + "px";
    }
  }
  if (vv) { vv.addEventListener("resize", altezza); vv.addEventListener("scroll", altezza); }
  window.addEventListener("resize", altezza);
  document.addEventListener("focusin", () => setTimeout(altezza, 50));
  document.addEventListener("focusout", () => setTimeout(altezza, 250));
  (telefono.addEventListener ? telefono.addEventListener("change", altezza) : telefono.addListener(altezza));
  window.addEventListener("hashchange", () => requestAnimationFrame(altezza));
  altezza();
  // iOS sposta la pagina per mostrare il campo: con l'altezza già giusta la si rimette a posto
  window.addEventListener("scroll", () => { if (telefono.matches && (scrollX || scrollY)) window.scrollTo(0, 0); }, { passive: true });

  // ------------------------------------------------ 3. lavagna: zoom a due dita
  const tela = $("lavagna");
  if (tela) {
    const dita = new Map();
    let pinza = null;
    const distanza = (a, b) => Math.hypot(a.x - b.x, a.y - b.y) || 1;
    const centro = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    window.addEventListener("pointerdown", (ev) => {
      if (ev.pointerType !== "touch" || !ev.isTrusted || !tela.contains(ev.target)) return;
      dita.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (dita.size === 2 && typeof vista === "function" && typeof applicaVista === "function") {
        ev.stopPropagation();       // app.js non comincia un secondo gesto con il secondo dito
        // il gesto del primo dito (spostare il foglio o una scheda) si chiude come un rilascio annullato
        const [primo] = dita.keys();
        window.dispatchEvent(new PointerEvent("pointercancel", { pointerId: primo, pointerType: "touch", bubbles: true }));
        const [a, b] = dita.values(), v = vista(), r = tela.getBoundingClientRect(), c = centro(a, b);
        pinza = { d0: distanza(a, b), z0: v.zoom, mx: (c.x - r.left - v.x) / v.zoom, my: (c.y - r.top - v.y) / v.zoom, mosso: false };
      } else if (dita.size > 2 || pinza) ev.stopPropagation();
    }, true);
    window.addEventListener("pointermove", (ev) => {
      if (!dita.has(ev.pointerId) || !ev.isTrusted) return;
      dita.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (!pinza) return;
      ev.stopPropagation();
      if (dita.size < 2) return;
      const [a, b] = dita.values(), v = vista(), r = tela.getBoundingClientRect(), c = centro(a, b);
      const z = Math.max(0.2, Math.min(2.5, pinza.z0 * distanza(a, b) / pinza.d0));
      // il punto del foglio che stava fra le due dita resta fra le due dita
      v.zoom = z;
      v.x = c.x - r.left - pinza.mx * z;
      v.y = c.y - r.top - pinza.my * z;
      pinza.mosso = true;
      applicaVista();
      if (typeof disegnaFili === "function") requestAnimationFrame(disegnaFili);
    }, true);
    const fine = (ev) => {
      if (!ev.isTrusted || !dita.has(ev.pointerId)) return;
      dita.delete(ev.pointerId);
      if (!pinza) return;
      ev.stopPropagation();
      if (dita.size === 0) {
        if (pinza.mosso && typeof salvaPannello === "function") salvaPannello();
        pinza = null;
      }
    };
    window.addEventListener("pointerup", fine, true);
    window.addEventListener("pointercancel", fine, true);
  }

  // ------------------------------------------------ 4. azioni dei messaggi con un tocco
  const msgs = $("messaggi");
  if (msgs) msgs.addEventListener("click", (ev) => {
    if (!dito.matches || ev.target.closest("a, button, pre, code, [contenteditable=true]")) return;
    if (getSelection && String(getSelection()).length) return;      // sta selezionando del testo
    const m = ev.target.closest(".msg");
    for (const x of msgs.querySelectorAll(".msg.m-azioni")) if (x !== m) x.classList.remove("m-azioni");
    if (m) m.classList.toggle("m-azioni");
  });
})();
