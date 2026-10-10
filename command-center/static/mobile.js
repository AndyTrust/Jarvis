// Command Center sul telefono (2026-10-03, richiesta dell'utente: «ottimizzata in TUTTE le pagine»).
// Va con mobile.css. Si carica dopo app.js (defer) e ne usa le funzioni globali solo se ci sono.
// Fa quattro cose:
//  1. la barra di schede in basso e il foglio «Impostazioni». 2026-10-05 (l'utente): la barra scorre col dito e ha TUTTE
//     le pagine, nello stesso ordine della barra in alto del desktop (barra.js, menu-barra.json: prima le voci «in barra»,
//     poi quelle di «Altro»), con l'ultima voce «Impostazioni»; la voce attiva si porta in vista da sola. Le voci si
//     ricostruiscono dal menu in alto quando cambia (stesse pagine, spie e contatori: una sola fonte). Il foglio non ha
//     più pagine: tema, avatar (temi.js, dots.js), agenti e motore, e nell'app Android «Voce, telefono e impostazioni»;
//  2. l'altezza della pagina segue la tastiera (visualViewport): il campo della chat resta sopra;
//  3. sulla lavagna lo zoom a due dita (spostare schede e foglio con un dito lo fa già app.js);
//  4. un tocco su un messaggio mostra le sue azioni (copia, modifica, togli), che sul desktop
//     compaiono al passaggio del mouse.
// Sopra 820 px col mouse non cambia niente: gli elementi nuovi sono nascosti da mobile.css e qui non si tocca nessuno
// stile della pagina. 2026-10-05: col dito (pointer: coarse, senza hover) vale l'impaginazione del telefono a ogni
// larghezza, così il tablet è uguale al telefono dell'utente (prima fra 821 e 1100 px restava la colonna degli agenti fissa
// e la lavagna ne perdeva 248 px).
(function mobile() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const menu = document.querySelector(".schede.menu");
  if (!app || !menu) return;
  const telefono = matchMedia("(max-width: 820px), (pointer: coarse) and (hover: none)");   // come il blocco «TELEFONO» di mobile.css
  const dito = matchMedia("(max-width: 820px), (pointer: coarse)");   // come il blocco «DITO» di mobile.css
  const svg = (corpo, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"${extra}>${corpo}</svg>`;
  const ICONE = {
    chat: svg('<path d="M4 5.5h16v10H9l-5 4z"/>'),
    lavagna: svg('<rect x="3" y="4" width="7" height="5" rx="1.5"/><rect x="14" y="15" width="7" height="5" rx="1.5"/><rect x="14" y="4" width="7" height="5" rx="1.5"/><path d="M10 6.5h4M17.5 9v6"/>'),
    agenti: svg('<circle cx="9" cy="8" r="3"/><path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6"/><circle cx="17" cy="9" r="2.3"/><path d="M16 14.4c2.3 0 4 1.3 4.5 3.8"/>'),
    home: svg('<path d="M3 12h4l2.5-6 5 12 2.5-6h4"/>'),
    missioni: svg('<path d="M7 4.5v15l12-7.5z"/>'),
    incarichi: svg('<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M8 9h8M8 13h8M8 17h5"/>'),
    piani: svg('<path d="M9 6h11M9 12h11M9 18h11"/><path d="M3.5 6l1.3 1.3L7 5M3.5 12l1.3 1.3L7 11M3.5 18l1.3 1.3L7 17"/>'),
    scadenze: svg('<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 2M9.5 2.5h5"/>'),
    registro: svg('<path d="M6 3.5h9l3 3v14H6z"/><path d="M9 10h6M9 14h6M9 18h4"/>'),
    memoria: svg('<path d="M12 5.5c-1.4-1.6-4.6-1.8-6 .4-1.8.4-2.6 2.6-1.6 4-1.2 1.4-.6 3.8 1 4.3.2 2.4 2.8 3.6 4.6 2.6.8.8 1.4.9 2 .7V5.5zM12 5.5c1.4-1.6 4.6-1.8 6 .4 1.8.4 2.6 2.6 1.6 4 1.2 1.4.6 3.8-1 4.3-.2 2.4-2.8 3.6-4.6 2.6-.8.8-1.4.9-2 .7"/>'),
    connessioni: svg('<path d="M4 8h13l-3-3M20 16H7l3 3"/>'),
    computer: svg('<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>'),
    telefono: svg('<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>'),
    impostazioni: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>'),
    altro: svg('<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>'),   // pagina che non ha un'icona sua
  };
  const nomeVoce = (a) => [...a.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim() || a.dataset.vista;
  // le pagine del menu in alto nell'ordine in cui le vede il desktop: barra.js le mette in fila (prima «in barra», poi la
  // tendina «Altro», che sta dentro .menu). Senza i doppioni che barra.js segna e senza quelle che un foglio di stile
  // nasconde fuori dal telefono (dentro il ponte senza «tutto»): su questa si decide con la classe del ponte, non col display
  // del menu in alto, che sul telefono è nascosto tutto.
  const nascostaDalPonte = (v) => document.documentElement.classList.contains("dentro-ponte")
    && !document.documentElement.classList.contains("ponte-tutto") && ["terminale", "vps", "tecnico"].includes(v);
  function pagine() {
    const viste = new Map();
    for (const a of menu.querySelectorAll("a[data-vista]")) {
      const v = a.dataset.vista;
      if (viste.has(v) || a.hidden || a.classList.contains("bm-doppione") || nascostaDalPonte(v)) continue;
      viste.set(v, a);
    }
    return viste;
  }

  // ------------------------------------------------ 1. barra in basso, foglio «Impostazioni», nome in alto
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

  const barra = crea("nav", { class: "m-schede", "aria-label": "Pagine" });
  const scorre = crea("div", { class: "m-schede-scorre" });
  barra.append(scorre);
  const tab = (vista, testo) => {
    const a = crea("a", { href: "#" + vista, "data-m": vista }, ICONE[vista] || ICONE.altro);
    a.append(crea("span", {}, ""), crea("i", { class: "spia grigia", "aria-hidden": "true" }), crea("b", { class: "conta" }));
    a.querySelector("span").textContent = testo;
    return a;
  };
  const bImp = crea("button", { type: "button", "data-m": "impostazioni", "aria-haspopup": "dialog", "aria-expanded": "false", "aria-controls": "m-foglio" }, ICONE.impostazioni);
  bImp.append(crea("span", {}, ""), crea("i", { class: "spia grigia", "aria-hidden": "true" }));
  bImp.querySelector("span").textContent = "Impostazioni";

  const velo = crea("div", { class: "m-foglio-velo" });
  const foglio = crea("div", { class: "m-foglio", role: "dialog", "aria-modal": "true", "aria-label": "Impostazioni", id: "m-foglio" });
  const testa = crea("div", { class: "m-foglio-testa" });
  testa.append(crea("b", {}, "Impostazioni"));
  const chiudi = crea("button", { type: "button", class: "icona", "aria-label": "Chiudi" }, "✕");
  testa.append(chiudi);
  // .m-foglio-griglia resta il nome: temi.js e dots.js ci montano le righe «Tema» e «Avatar». Le voci di pagina che
  // registro, connessioni, piani e incarichi ci aggiungono ancora non si vedono (mobile.css): stanno nella barra in basso.
  const griglia = crea("div", { class: "m-foglio-griglia" });
  foglio.append(crea("div", { class: "m-foglio-maniglia", "aria-hidden": "true" }), testa, griglia);
  const largo = (ico, testo) => {
    const b = crea("button", { type: "button", class: "m-foglio-largo" });
    b.append(crea("span", { class: "m-ico", "aria-hidden": "true" }), crea("span"));
    b.querySelector(".m-ico").textContent = ico;
    b.querySelector("span:not(.m-ico)").textContent = testo;
    griglia.append(b);
    return b;
  };
  const bAgenti = largo("☰", "Agenti, motore e nuova chat");
  // dentro l'app Android (WebActivity, ponte window.JarvisApp): la schermata nativa con voce, permessi e impostazioni dell'app
  const appAndroid = window.JarvisApp && typeof window.JarvisApp.apriVoceETelefono === "function";
  const bApp = appAndroid ? largo("⚙", "Voce, telefono e impostazioni dell'app") : null;
  app.append(barra, velo, foglio);

  function apriFoglio(si) {
    foglio.classList.toggle("aperto", si);
    velo.classList.toggle("aperto", si);
    bImp.setAttribute("aria-expanded", String(si));
    bImp.classList.toggle("attiva", si);
    allinea();
    if (si) { const primo = griglia.querySelector("a,button,[tabindex]"); if (primo) primo.focus({ preventScroll: true }); vediAttiva(bImp, true); }
  }
  bImp.addEventListener("click", () => apriFoglio(!foglio.classList.contains("aperto")));
  chiudi.addEventListener("click", () => apriFoglio(false));
  velo.addEventListener("click", () => apriFoglio(false));
  griglia.addEventListener("click", (ev) => { if (ev.target.closest("a")) apriFoglio(false); });
  bAgenti.addEventListener("click", () => { apriFoglio(false); app.classList.add("lato-aperto"); });
  if (bApp) bApp.addEventListener("click", () => { apriFoglio(false); try { window.JarvisApp.apriVoceETelefono(); } catch (e) { /* app vecchia */ } });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && foglio.classList.contains("aperto")) apriFoglio(false); });
  // un tocco sulla scheda già aperta riporta in cima la pagina (come nelle app)
  scorre.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-m]");
    if (!a) return;
    apriFoglio(false);
    if (a.classList.contains("attiva")) { const m = app.querySelector("main"); if (m) m.scrollTo({ top: 0, behavior: "smooth" }); }
  });

  // le voci della barra: ricostruite solo quando cambiano le pagine o il loro ordine (non a ogni spia)
  let firma = "";
  function costruisci() {
    const viste = pagine();
    const nuova = [...viste].map(([v, a]) => v + ":" + nomeVoce(a)).join("|");
    if (nuova === firma) return false;
    firma = nuova;
    scorre.replaceChildren(...[...viste].map(([v, a]) => tab(v, nomeVoce(a))), bImp);
    return true;
  }
  // porta in vista la voce attiva (al centro se si può), scorrendo solo la barra e mai la pagina
  function vediAttiva(el, liscio) {
    if (!el || !telefono.matches || !scorre.clientWidth) return;
    const voluto = el.offsetLeft - (scorre.clientWidth - el.offsetWidth) / 2;
    const max = scorre.scrollWidth - scorre.clientWidth;
    const x = Math.max(0, Math.min(max, voluto));
    if (Math.abs(scorre.scrollLeft - x) > 2) scorre.scrollTo({ left: x, behavior: liscio ? "smooth" : "auto" });
    bordi();
  }
  // le sfumature ai lati dicono che la barra continua da quella parte
  function bordi() {
    const max = scorre.scrollWidth - scorre.clientWidth;
    barra.classList.toggle("m-continua-sx", scorre.scrollLeft > 4);
    barra.classList.toggle("m-continua-dx", scorre.scrollLeft < max - 4);
  }
  scorre.addEventListener("scroll", bordi, { passive: true });

  // spie, contatori e scheda attiva: copiati dal menu in alto, che app.js tiene aggiornato
  const classeSpia = (a) => { const s = a && a.querySelector(".spia"); return s ? s.className : "spia grigia"; };
  let ultimaAttiva = null;
  function allinea() {
    const nuove = costruisci();
    const attiva = (menu.querySelector("a.attiva") || {}).dataset?.vista || "chat";
    const aperto = foglio.classList.contains("aperto");
    let el = null;
    for (const a of scorre.querySelectorAll("a[data-m]")) {
      const v = a.dataset.m, orig = menu.querySelector(`a[data-vista="${v}"]:not(.bm-doppione)`);
      const si = v === attiva && !aperto;
      if (a.classList.contains("attiva") !== si) a.classList.toggle("attiva", si);
      if (si) { a.setAttribute("aria-current", "page"); el = a; } else a.removeAttribute("aria-current");
      const c = classeSpia(orig);
      if (a.querySelector("i").className !== c) a.querySelector("i").className = c;
      const conta = orig && orig.querySelector(".conta");
      const n = conta ? conta.textContent.trim() : "";
      if (a.querySelector(".conta").textContent !== n) a.querySelector(".conta").textContent = n;
    }
    const titolo = $("vista-titolo");
    $("m-pagina").textContent = titolo ? titolo.textContent : "";
    if (aperto) { ultimaAttiva = null; return; }   // alla chiusura del foglio si torna a mostrare la pagina attiva
    if (nuove || attiva !== ultimaAttiva) { vediAttiva(el, !nuove); ultimaAttiva = attiva; }
    else bordi();
  }
  new MutationObserver(allinea).observe(menu, { subtree: true, attributes: true, attributeFilter: ["class", "hidden"], childList: true, characterData: true });
  // ponte.js mette «dentro-ponte» e «ponte-tutto» su <html> dopo l'avvio: cambia quali pagine ci sono
  new MutationObserver(allinea).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  const h1 = $("vista-titolo");
  if (h1) new MutationObserver(allinea).observe(h1, { childList: true, characterData: true, subtree: true });
  window.addEventListener("hashchange", () => {
    apriFoglio(false);
    // sul telefono il cassetto degli agenti si chiude quando si cambia pagina: restava aperto sopra la nuova (lavagna compresa)
    if (telefono.matches) app.classList.remove("lato-aperto");
    allinea();
  });
  window.addEventListener("resize", () => { const a = scorre.querySelector(".attiva"); vediAttiva(a); });
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
    // Lavagna e le schede Terminale e Desktop VPS di Computer, a pagina intera, partono sotto la barra in alto (paginaIntera in app.js)
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
