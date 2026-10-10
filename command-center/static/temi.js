// Temi del Command Center (2026-10-03, richiesta dell'utente: «inserisci anche i temi nero, chiaro e Claude»).
// Vale sul Mac e dentro il ponte. Nessuna dipendenza, nessuna richiesta di rete.
//  - un solo interruttore: <html data-tema="scuro|nero|chiaro|claude|auto">; con «auto» anche
//    data-auto="chiaro|scuro", che segue matchMedia('(prefers-color-scheme: light)');
//  - la scelta sta in localStorage «cc.tema» (sempre dentro try/catch: in navigazione privata o con i
//    dati bloccati può lanciare; allora resta Scuro, senza errori);
//  - lo snippet nel <head> di index.html (INTEGRA-TEMI.md) applica il tema PRIMA dei fogli di stile:
//    qui si riapplica (idempotente) e si costruisce il selettore;
//  - selettore: pulsante in alto accanto allo stato (menu a pallini, radiogroup da tastiera) e una
//    riga «Tema» nel foglio «Altro» del telefono (lo crea mobile.js; se arriva dopo, lo aspetto);
//  - <meta name="theme-color"> segue il tema (barra del browser sul telefono).
(() => {
  "use strict";
  if (window.CCTemi) return;
  const CHIAVE = "cc.tema";
  const TEMI = [
    { id: "scuro", nome: "Scuro", nota: "grigio, quello di sempre", pallini: ["#181818", "#f0f0f0", "#599ce7"], meta: "#141414" },
    { id: "nero", nome: "Nero", nota: "nero vero, per OLED", pallini: ["#000000", "#ffffff", "#6aaefc"], meta: "#000000" },
    { id: "chiaro", nome: "Chiaro", nota: "leggibile al sole", pallini: ["#f7f8fa", "#111418", "#1a52a8"], meta: "#eceef2" },
    { id: "claude", nome: "Claude", nota: "crema e terracotta", pallini: ["#faf9f5", "#1f1e1b", "#c6613f"], meta: "#f0eee6" },
    { id: "auto", nome: "Automatico", nota: "chiaro o scuro come il sistema", pallini: ["#f7f8fa", "#181818", "#599ce7"], meta: null },
  ];
  const PER_ID = Object.fromEntries(TEMI.map((t) => [t.id, t]));
  const radice = document.documentElement;
  let mq = null;
  try { mq = window.matchMedia("(prefers-color-scheme: light)"); } catch (e) { mq = null; }

  const valido = (t) => typeof t === "string" && Object.prototype.hasOwnProperty.call(PER_ID, t);
  function leggi() {
    try { const t = localStorage.getItem(CHIAVE); return valido(t) ? t : "scuro"; } catch (e) { return "scuro"; }
  }
  function scrivi(t) {
    try { if (t === "scuro") localStorage.removeItem(CHIAVE); else localStorage.setItem(CHIAVE, t); return true; } catch (e) { return false; }
  }
  const sistemaChiaro = () => !!(mq && mq.matches);
  const effettivo = (t) => (t === "auto" ? (sistemaChiaro() ? "chiaro" : "scuro") : t);

  let scelto = "scuro";
  function applica(t) {
    if (!valido(t)) t = "scuro";
    scelto = t;
    radice.setAttribute("data-tema", t);
    if (t === "auto") radice.setAttribute("data-auto", effettivo(t)); else radice.removeAttribute("data-auto");
    const eff = effettivo(t);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", PER_ID[eff].meta);
    aggiornaControlli();
    try { window.dispatchEvent(new CustomEvent("cc-tema", { detail: { tema: t, effettivo: eff } })); } catch (e) { /* niente */ }
  }
  function scegli(t) {
    if (!valido(t)) return;
    scrivi(t);
    applica(t);
  }

  // ---------------------------------------------------------------- elementi
  function crea(tag, attr = {}, testo) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attr)) e.setAttribute(k, v);
    if (testo != null) e.textContent = testo;
    return e;
  }
  function pallini(t) {
    const s = crea("span", { class: "tema-pallini", "aria-hidden": "true" });
    for (const c of t.pallini) { const i = crea("i"); i.style.background = c; s.append(i); }
    return s;
  }
  // un gruppo di scelte con la tastiera dei radio: frecce = sposta e sceglie, Home/Fine, Invio/Spazio
  function gruppo(classe, etichetta, compatto) {
    const g = crea("div", { class: classe, role: "radiogroup", "aria-label": etichetta });
    for (const t of TEMI) {
      const b = crea("button", { type: "button", class: "tema-voce", role: "radio", "aria-checked": "false", "data-tema": t.id, tabindex: "-1",
        "aria-label": `${t.nome}: ${t.nota}` });
      const testi = crea("span");
      testi.append(crea("b", {}, t.nome));
      if (!compatto) testi.append(crea("small", {}, t.nota));
      b.append(pallini(t), testi, crea("span", { class: "tema-segno", "aria-hidden": "true" }, "✓"));
      g.append(b);
    }
    g.addEventListener("click", (ev) => {
      const b = ev.target.closest(".tema-voce");
      if (!b) return;
      scegli(b.dataset.tema);
      b.focus();
      g.dispatchEvent(new CustomEvent("tema-scelto", { bubbles: true }));
    });
    g.addEventListener("keydown", (ev) => {
      const voci = [...g.querySelectorAll(".tema-voce")];
      const i = voci.indexOf(document.activeElement);
      if (i < 0) return;
      let j = null;
      if (ev.key === "ArrowDown" || ev.key === "ArrowRight") j = (i + 1) % voci.length;
      else if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") j = (i - 1 + voci.length) % voci.length;
      else if (ev.key === "Home") j = 0;
      else if (ev.key === "End") j = voci.length - 1;
      else if (ev.key === " " || ev.key === "Enter") {
        ev.preventDefault();
        scegli(voci[i].dataset.tema);
        if (ev.key === "Enter") g.dispatchEvent(new CustomEvent("tema-scelto", { bubbles: true }));
        return;
      }
      if (j == null) return;
      ev.preventDefault();
      voci[j].focus();
      scegli(voci[j].dataset.tema);
    });
    return g;
  }
  const gruppi = [];
  let btn = null, menu = null;

  function aggiornaControlli() {
    for (const g of gruppi) {
      for (const b of g.querySelectorAll(".tema-voce")) {
        const si = b.dataset.tema === scelto;
        b.setAttribute("aria-checked", String(si));
        b.tabIndex = si ? 0 : -1;
      }
    }
    if (btn) {
      const t = PER_ID[scelto];
      btn.setAttribute("aria-label", `Tema dei colori: ${t.nome}. Cambia tema`);
      btn.title = `Tema: ${t.nome}`;
      const vecchi = btn.querySelector(".tema-pallini");
      if (vecchi) vecchi.replaceWith(pallini(t));
      const n = btn.querySelector(".tema-nome");
      if (n) n.textContent = t.nome;
    }
  }

  // ---------------------------------------------------------------- pulsante in alto e menu
  function apriMenu(si) {
    if (!btn || !menu) return;
    if (!si) {
      if (menu.hidden) return;
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      return;
    }
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    const r = btn.getBoundingClientRect();
    const w = menu.offsetWidth;
    menu.style.top = Math.round(r.bottom + 6) + "px";
    menu.style.left = Math.round(Math.max(8, Math.min(r.right - w, innerWidth - w - 8))) + "px";
    const att = menu.querySelector('.tema-voce[aria-checked="true"]') || menu.querySelector(".tema-voce");
    if (att) att.focus();
  }
  function montaBarra() {
    const barra = document.querySelector("header.barra");
    if (!barra || barra.querySelector(".tema-btn")) return;
    btn = crea("button", { type: "button", class: "icona tema-btn", "aria-haspopup": "true", "aria-expanded": "false", "aria-controls": "tema-menu" });
    btn.append(pallini(PER_ID[scelto]), crea("span", { class: "tema-nome" }, PER_ID[scelto].nome));
    const stato = barra.querySelector(".stato-generale");
    barra.insertBefore(btn, stato || null);
    menu = crea("div", { class: "tema-menu", id: "tema-menu", hidden: "" });
    menu.append(crea("span", { class: "tema-menu-titolo", id: "tema-menu-titolo" }, "Tema"));
    const g = gruppo("tema-gruppo", "Tema dei colori", false);
    menu.append(g);
    document.body.append(menu);
    gruppi.push(g);
    btn.addEventListener("click", () => apriMenu(menu.hidden));
    g.addEventListener("tema-scelto", () => { apriMenu(false); btn.focus(); });
    menu.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); apriMenu(false); btn.focus(); }
      else if (ev.key === "Tab") apriMenu(false);
    });
    document.addEventListener("pointerdown", (ev) => {
      if (!menu.hidden && !menu.contains(ev.target) && !btn.contains(ev.target)) apriMenu(false);
    }, true);
    window.addEventListener("resize", () => apriMenu(false));
  }

  // ---------------------------------------------------------------- foglio «Altro» (mobile.js)
  function montaFoglio() {
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (!griglia || griglia.querySelector(".tema-foglio")) return !!griglia;
    const box = crea("div", { class: "tema-foglio" });
    box.append(crea("b", { id: "tema-foglio-titolo" }, "Tema"));
    const g = gruppo("tema-foglio-scelte", "Tema dei colori", true);
    box.append(g);
    griglia.append(box);
    gruppi.push(g);
    return true;
  }

  // ---------------------------------------------------------------- avvio
  applica(leggi());
  function monta() {
    montaBarra();
    if (!montaFoglio()) {
      // mobile.js costruisce il foglio a pagina letta: se non c'è ancora, lo aspetto (al massimo 10 s)
      const os = new MutationObserver(() => { if (montaFoglio()) os.disconnect(); });
      os.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => os.disconnect(), 10000);
    }
    aggiornaControlli();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", monta, { once: true });
  else monta();

  // «Automatico»: il sistema passa da chiaro a scuro (sera, risparmio energetico)
  const cambioSistema = () => { if (scelto === "auto") applica("auto"); };
  if (mq) {
    if (mq.addEventListener) mq.addEventListener("change", cambioSistema);
    else if (mq.addListener) mq.addListener(cambioSistema);
  }
  // un'altra scheda ha cambiato tema
  window.addEventListener("storage", (ev) => { if (ev.key === CHIAVE || ev.key === null) applica(leggi()); });

  window.CCTemi = {
    elenco: () => TEMI.map((t) => t.id),
    tema: () => scelto,
    effettivo: () => effettivo(scelto),
    scegli,
    apriMenu: (si = true) => apriMenu(si),
  };
})();
