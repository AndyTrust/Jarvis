// Eliminazione in blocco nel Vault (2026-10-10): tutta una categoria, una sezione o un tag. File a parte, usa
// window.VaultPagina (chiama, apriModale, chiudiModale, avviso, el, dopoImport). Conferma scrivendo il numero di voci;
// backup cifrato prima; «Annulla» rimette tutto il lotto. Nessun valore passa di qui: solo filtro e conteggi.
(function vaultGruppi() {
  "use strict";
  const P = () => window.VaultPagina;
  const nomeFiltro = (f, etichetta) => (f.tipo ? "la categoria" : f.sezione ? "la sezione" : "il tag") + ` «${etichetta}»`;

  async function svuota(filtro, etichetta) {
    const { chiama, apriModale, chiudiModale, el, avviso } = P();
    const q = Object.entries(filtro).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    const c = await chiama("GET", "gruppo/conta?" + q);
    if (c.stato !== 200) { avviso(c.d.errore || "errore " + c.stato, "rosso"); return; }
    const n = c.d.voci;
    if (!n) { avviso(`Nessuna voce in ${nomeFiltro(filtro, etichetta)}.`); return; }
    const campo = el("input", { type: "text", inputmode: "numeric", class: "vt-input", id: "vt-svuota", autocomplete: "off", "aria-label": "Numero di voci" });
    const togli = el("input", { type: "checkbox", id: "vt-svuota-sez" });
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    apriModale("Elimina tutte le voci", el("form", { class: "vt-modulo", onsubmit: async (e) => {
      e.preventDefault();
      if (campo.value.trim() !== String(n)) { err.textContent = `Scrivi ${n} per confermare.`; err.hidden = false; return; }
      const r = await chiama("POST", "gruppo/elimina", Object.assign({ conferma: n, togli_sezione: togli.checked }, filtro));
      if (r.stato !== 200) { err.textContent = r.d.errore || "errore " + r.stato; err.hidden = false; return; }
      chiudiModale();
      await P().dopoImport();
      annullabile(r.d);
    } },
      el("p", {}, `Stai per eliminare ${n} voci: tutta ${nomeFiltro(filtro, etichetta)}.`),
      el("p", { class: "vt-tenue" }, "Prima si fa un backup cifrato del Vault. Le voci restano nello storico e «Annulla» le rimette tutte. Il file .env.jarvis non si tocca."),
      el("label", { for: "vt-svuota" }, `Scrivi ${n} per confermare`), campo,
      filtro.sezione ? el("label", { class: "vt-spunta", for: "vt-svuota-sez" }, togli, "Togli anche la sezione dall'elenco") : null,
      err,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, `Elimina ${n} voci`))));
    requestAnimationFrame(() => campo.focus());
  }

  function annullabile(d) {
    const { el, avviso } = P();
    avviso(`Eliminate ${d.eliminate} voci (backup cifrato fatto prima).`);
    const contenitore = document.querySelector(".vt-avvisi");
    if (!contenitore || !d.lotto) return;
    const a = el("div", { class: "vt-avviso", role: "status" }, `Eliminate ${d.eliminate} voci. `,
      el("button", { type: "button", class: "vt-link", onclick: async () => { a.remove(); await ripristina(d.lotto); } }, "Annulla"));
    contenitore.append(a);
    setTimeout(() => a.remove(), 15000);
  }

  async function ripristina(lotto) {
    const { chiama, avviso } = P();
    const r = await chiama("POST", "gruppo/ripristina", { lotto });
    if (r.stato !== 200) { avviso(r.d.errore || "errore " + r.stato, "rosso"); return; }
    await P().dopoImport();
    avviso(`Rimesse ${r.d.ripristinate} voci.`);
  }

  async function recenti() {
    const { chiama, apriModale, chiudiModale, el } = P();
    const r = await chiama("GET", "gruppo/lotti");
    const lotti = (r.d && r.d.lotti) || [];
    apriModale("Eliminazioni recenti", el("div", { class: "vt-modulo" },
      lotti.length ? el("ul", { class: "vt-storico" }, ...lotti.map((x) => el("li", {},
        el("span", {}, `${x.quando} · ${x.voci} voci · ${Object.entries(x.filtro).map(([k, v]) => `${k} «${v}»`).join("")}`),
        el("button", { type: "button", class: "vt-secondario", onclick: async () => { chiudiModale(); await ripristina(x.lotto); } }, "Annulla"))))
        : el("p", { class: "vt-tenue" }, "Nessuna eliminazione in blocco da annullare."),
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Chiudi"))));
  }

  window.VaultGruppi = { svuota, ripristina, recenti };
})();
