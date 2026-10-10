// Importazione «Da Chrome (CSV)» nel Vault (2026-10-10). File a parte: lo usa vault.js tramite window.VaultPagina
// (chiama, apriModale, chiudiModale, avviso, el, dopoImport). Qui passano SOLO il nome del file scelto, il piano
// (conteggi) e il rapporto (conteggi): password, utenti e note del CSV restano nel server e vanno dritti alla cifratura.
(function vaultChrome() {
  "use strict";
  function P() { return window.VaultPagina; }

  async function apri() {
    const { chiama, apriModale, el, avviso } = P();
    const corpo = el("div", { class: "vt-modulo" }, el("p", { class: "vt-tenue" }, "Cerco i file .csv in Download, Scrivania e Documenti…"));
    apriModale("Da Chrome (CSV)", corpo);
    const r = await chiama("GET", "chrome/file");
    if (r.stato !== 200) { corpo.replaceChildren(el("p", { class: "vt-errore" }, r.d.errore || "errore " + r.stato)); return; }
    if (r.d.carica) { daComputer(corpo); return; }
    if (!r.d.file.length) {
      corpo.replaceChildren(el("p", {}, "Nessun file .csv in Download, Scrivania o Documenti. In Chrome: Impostazioni → Compilazione automatica → Gestore delle password → Impostazioni → Esporta password."));
      return;
    }
    const scelta = el("select", { class: "vt-input", id: "vt-csv", "aria-label": "File CSV di Chrome" },
      ...r.d.file.map((f, i) => el("option", { value: String(i) }, `${f.cartella} / ${f.nome} (${f.kb} KB)`)));
    const esito = el("div", {});
    const vedi = el("button", { type: "button", class: "vt-primario" }, "Prepara il piano");
    vedi.addEventListener("click", async () => {
      const f = r.d.file[Number(scelta.value)];
      vedi.disabled = true; esito.replaceChildren(el("p", { class: "vt-tenue" }, "Leggo il file su questo computer (non esce da qui)…"));
      const p = await chiama("GET", "chrome/piano?cartella=" + encodeURIComponent(f.cartella) + "&nome=" + encodeURIComponent(f.nome));
      vedi.disabled = false;
      if (p.stato !== 200) { esito.replaceChildren(el("p", { class: "vt-errore" }, p.d.errore || "errore " + p.stato)); return; }
      esito.replaceChildren(piano(p.d, f));
    });
    corpo.replaceChildren(
      el("p", {}, "Il file di Chrome è in chiaro: il Command Center lo legge su questo computer e cifra subito ogni accesso nel Vault. La pagina vede solo i conteggi."),
      el("label", { for: "vt-csv" }, "File"), scelta, el("div", { class: "vt-bottoni" }, vedi), esito);
    void avviso;
  }

  // Modo VPS (avanzato): il CSV sta sul computer del proprietario. Lo legge il browser e lo manda a pezzi al
  // server (HTTPS, dietro il login del sito e la sessione del Vault): resta solo in memoria nel server fino all'importazione.
  const PEZZO = 100000;
  function daComputer(corpo) {
    const { el } = P();
    const file = el("input", { type: "file", accept: ".csv,text/csv", class: "vt-input", id: "vt-csv-file", "aria-label": "File CSV di Chrome" });
    const esito = el("div", {});
    const vedi = el("button", { type: "button", class: "vt-primario" }, "Prepara il piano");
    vedi.addEventListener("click", async () => {
      const scelto = file.files && file.files[0];
      if (!scelto) { esito.replaceChildren(el("p", { class: "vt-errore", role: "alert" }, "Scegli il file .csv esportato da Chrome.")); return; }
      if (scelto.size > 12 * 1024 * 1024) { esito.replaceChildren(el("p", { class: "vt-errore", role: "alert" }, "File troppo grande (massimo 12 MB).")); return; }
      vedi.disabled = true;
      try {
        const cid = await manda(await scelto.text(), (n, tot) => esito.replaceChildren(el("p", { class: "vt-tenue" }, `Invio al Vault del server (HTTPS)… ${n}/${tot}`)));
        const p = await P().chiama("POST", "chrome/piano", { caricamento: cid });
        if (p.stato !== 200) throw new Error(p.d.errore || "errore " + p.stato);
        esito.replaceChildren(piano(p.d, { nome: scelto.name, caricamento: cid }));
      } catch (e) { esito.replaceChildren(el("p", { class: "vt-errore", role: "alert" }, String(e.message || e))); }
      finally { vedi.disabled = false; file.value = ""; }
    });
    corpo.replaceChildren(
      el("p", {}, "Scegli il file esportato da Chrome (Impostazioni → Password → Esporta password). Il browser lo manda al Vault del tuo server dietro il login del sito: il server lo tiene solo in memoria, cifra ogni accesso e lo butta. La pagina vede solo i conteggi."),
      el("label", { for: "vt-csv-file" }, "File CSV"), file, el("div", { class: "vt-bottoni" }, vedi), esito);
  }
  async function manda(testo, avanzamento) {
    const tot = Math.max(1, Math.ceil(testo.length / PEZZO));
    let cid = "";
    for (let i = 0; i < tot; i++) {
      avanzamento(i + 1, tot);
      const r = await P().chiama("POST", "chrome/carica", { caricamento: cid || undefined, parte: i, totale: tot, pezzo: testo.slice(i * PEZZO, (i + 1) * PEZZO) });
      if (r.stato !== 200) throw new Error(r.d.errore || "errore " + r.stato);
      cid = r.d.caricamento;
    }
    return cid;
  }

  function tabella(titolo, dati) {
    const { el } = P();
    return [el("h4", { class: "vt-sotto-titolo" }, titolo),
      el("ul", { class: "vt-piano" }, ...Object.entries(dati).map(([k, n]) => el("li", { class: "vt-piano-riga" }, el("span", {}, k), el("b", {}, String(n)))))];
  }

  function piano(p, f) {
    const { el, chiama, chiudiModale, avviso, dopoImport } = P();
    const vai = el("button", { type: "button", class: "vt-primario" }, "Importa ora");
    vai.addEventListener("click", async () => {
      vai.disabled = true; vai.textContent = "Importo (backup cifrato prima)…";
      const r = await chiama("POST", "chrome/importa", f.caricamento ? { caricamento: f.caricamento } : { cartella: f.cartella, nome: f.nome });
      if (r.stato !== 200) { avviso(r.d.errore || "errore " + r.stato, "rosso"); vai.disabled = false; vai.textContent = "Riprova"; return; }
      chiudiModale();
      await dopoImport();
      rapporto(r.d, f);
    });
    return el("div", { class: "vt-modulo" },
      el("p", { class: "vt-nota" }, `${p.righe} righe, ${p.domini} domini → ${p.voci} accessi dopo l'unione dei doppioni (stesso sito e stesso utente).`),
      ...tabella("Sezioni", p.per_sezione), ...tabella("Problemi", p.problemi),
      el("p", { class: "vt-tenue" }, `Password uguali su più siti: ${p.gruppi_password_riusata} gruppi (fino a ${p.siti_max_stessa_password} siti). Non si uniscono: ogni accesso porta l'avviso.`),
      el("p", { class: "vt-tenue vt-piccolo" }, "«Accedo con Google» non si deduce dal file: resta da impostare voce per voce. Una voce che modifichi a mano non viene sovrascritta da un'importazione successiva."),
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: () => {
        if (f.caricamento) chiama("POST", "chrome/scarta", { caricamento: f.caricamento }).catch(() => {});
        chiudiModale(); } }, "Annulla"), vai));
  }

  function rapporto(r, f) {
    const { el, apriModale, chiudiModale } = P();
    const righe = { "Importate": r.importate, "Aggiornate": r.aggiornate, "Già presenti": r.gia_presenti,
      "Modificate a mano (lasciate stare)": r.modificate_a_mano, "Doppioni uniti": r.unite, "In «Da riordinare»": r.da_riordinare,
      "Con password riusata": r.password_riusate, "Senza password o passkey": r.senza_password, "Conflitti di password (vecchia nello storico)": r.conflitti };
    if (f.caricamento) {           // modo VPS: il file è sul computer del proprietario, il server non lo ha mai scritto su disco
      apriModale("Importazione da Chrome: rapporto", el("div", { class: "vt-modulo" },
        ...tabella("Conteggi", righe),
        el("p", { class: "vt-nota" }, "Backup cifrato del Vault fatto prima dell'importazione. Il server ha già buttato il contenuto del file."),
        el("p", {}, `Il file «${f.nome}» è ancora sul tuo computer, in chiaro, con tutte le password: cancellalo e svuota il Cestino.`),
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-primario", onclick: chiudiModale }, "Ho capito"))));
      return;
    }
    apriModale("Importazione da Chrome: rapporto", el("div", { class: "vt-modulo" },
      ...tabella("Conteggi", righe),
      el("p", { class: "vt-nota" }, "Backup cifrato del Vault fatto prima dell'importazione."),
      el("p", {}, `Il file «${f.nome}» è ancora su questo computer, in chiaro, con tutte le password.`),
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Lo tengo per ora"),
        el("button", { type: "button", class: "vt-primario", onclick: () => elimina(f) }, "Elimina il file CSV in chiaro"))));
  }

  function elimina(f) {
    // Doppia conferma del proprietario: 1) spiega il rischio e chiede «Sì», 2) chiede di scrivere ELIMINA. Solo allora il server
    // sovrascrive e toglie il file. Mai da solo.
    const { el, apriModale, chiudiModale } = P();
    apriModale("Eliminare il file in chiaro?", el("div", { class: "vt-modulo" },
      el("p", {}, `«${f.nome}» contiene tutte le password in chiaro: chiunque lo legga (backup, sincronie, altre app) le ha tutte. Ora sono nel Vault, cifrate.`),
      el("p", { class: "vt-tenue" }, "Il file verrà sovrascritto e tolto. Non si recupera."),
      el("div", { class: "vt-bottoni" },
        el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "button", class: "vt-primario", onclick: () => secondaConferma(f) }, "Sì, voglio eliminarlo"))));
  }

  function secondaConferma(f) {
    const { el, apriModale, chiudiModale, chiama, avviso } = P();
    const campo = el("input", { type: "text", class: "vt-input", id: "vt-elimina", autocomplete: "off", "aria-label": "Scrivi ELIMINA" });
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    const invia = async (e) => {
      e.preventDefault();
      if (campo.value.trim() !== "ELIMINA") { err.textContent = "Scrivi ELIMINA in maiuscolo per confermare."; err.hidden = false; return; }
      const r = await chiama("POST", "chrome/elimina", { cartella: f.cartella, nome: f.nome, conferma_1: true, conferma_2: "ELIMINA" });
      if (r.stato !== 200) { err.textContent = r.d.errore || "errore " + r.stato; err.hidden = false; return; }
      chiudiModale();
      avviso("File eliminato. Svuota anche il Cestino e cancella l'esportazione da Chrome se l'hai salvata altrove.");
    };
    apriModale("Seconda conferma", el("form", { class: "vt-modulo", onsubmit: invia },
      el("label", { for: "vt-elimina" }, "Scrivi ELIMINA per confermare"), campo, err,
      el("p", { class: "vt-tenue vt-piccolo" }, "Dopo: svuota il Cestino e, se l'hai salvato altrove (Drive, mail), cancella anche quella copia."),
      el("div", { class: "vt-bottoni" },
        el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, "Elimina il file"))));
    requestAnimationFrame(() => campo.focus());
  }

  window.VaultChrome = { apri };
})();
