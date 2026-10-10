// Il Vault del Command Center: accessi, carte, PIN, variabili e note sicure, cifrati sul tuo computer.
// File a parte (con vault.css e command-center/vault_cc.py). Parte VUOTO. Guida: docs/wiki/Vault.md.
// Dati: /api/vault/* (server.py → vault_cc.py). All'avvio chiede GET /api/vault/stato: se non risponde 200 (da fuori
// del computer, con un server vecchio) non crea né la voce del menu né la vista.
// Regole di sicurezza della pagina:
//  - la sessione del Vault sta solo in una variabile di questo script (mai localStorage, mai cookie);
//  - i valori segreti arrivano solo dalla risposta di «Mostra»/«Copia», restano a schermo 20 s e poi si rimascherano;
//  - con il Vault bloccato la vista viene ricostruita da zero: nel DOM non resta nessun valore e nessun titolo;
//  - gli appunti si svuotano dopo 30 s; il blocco scatta dopo 5 minuti senza tocchi o 1 minuto con la scheda nascosta;
//  - testi sempre con textContent, mai innerHTML.
(function vault() {
  "use strict";
  const VISTA = "vault";
  const MASCHERA = "••••••••";
  const TIPI = [["accesso", "Accesso web"], ["carta", "Carta"], ["pin", "PIN"], ["variabile", "Variabile"], ["nota", "Nota sicura"]];
  const NOME_TIPO = Object.fromEntries(TIPI);
  const ICONA = { accesso: "◍", carta: "▭", pin: "#", variabile: "$", nota: "✎" };
  const METODI = [["password", "Mail e password"], ["google", "Google"], ["apple", "Apple"], ["passkey", "Passkey"]];
  const DUE_FA = [["nessuno", "Nessuno"], ["sms", "SMS"], ["mail", "Mail"], ["totp", "App di codici (TOTP)"], ["push", "Conferma push"], ["passkey", "Passkey"], ["chiave", "Chiave hardware"]];
  const ETICHETTE = {
    link: "Link", domini: "Domini", utente: "Utente", mail: "Mail", password: "Password", metodo: "Metodo",
    account_collegato: "Account collegato", due_fa: "2FA", due_fa_dove: "Dove arriva", due_fa_chi: "Chi legge il codice",
    codici_recupero: "Codici di recupero", note: "Note", intestatario: "Intestatario", circuito: "Circuito", numero: "Numero",
    scadenza_mese: "Mese", scadenza_anno: "Anno", cvv: "CVV", pin_carta: "PIN carta", banca: "Banca", iban: "IBAN",
    assistenza: "Assistenza", limite: "Limite", tre_ds: "3-D Secure", colore: "Colore", uso: "A cosa serve", codice: "Codice",
    nome: "Nome", valore: "Valore", scadenza: "Scadenza", alias: "Alias", descrizione: "Descrizione", riuso: "Riusata da", destinazione: "File", servizi: "Servizi", testo: "Testo",
  };
  const STATI = { allineata: "verde", "cambiata nel file": "giallo", "da scrivere": "giallo", diversa: "giallo",
    "assente nel file": "giallo", "file assente": "giallo", conflitto: "rosso", nessuna: "grigio" };

  let sessione = null;                 // il gettone del Vault: solo qui
  const S = {
    stato: null, voci: [], sezioni: [], categorie: {}, pinAttivo: false, errore: "", occupato: false,
    filtro: { cat: null, sezione: null, tag: null, q: "" }, sel: null, det: null, pannello: "lista", cassetto: false,
    ambiente: null, firmaAmb: "", modoSblocco: "frase", recupero: false, codiceNuovo: null,
    ultimaAttivita: Date.now(), ultimoTocco: Date.now(), nascostaDa: 0,
  };
  const N = {};
  const T = { orologio: null, osservatore: null, nascosta: null };
  const token = () => window.CC_TOKEN || "";
  const nomeA = () => (S.stato && S.stato.assistente) || "l'assistente";
  // Lo stesso file in locale (macOS, Windows) e nel modo VPS (avanzato). «Dove» cambia solo i testi; i controlli stanno sul server.
  const VPS = () => !!(S.stato && S.stato.modo === "vps");
  const WIN = () => !!(S.stato && S.stato.piattaforma === "win32");
  const QUI = () => (VPS() ? "sul tuo server" : "su questo computer");
  const DISP = () => (VPS() ? "questo Vault" : "questo computer");
  const PORTACHIAVI = () => (VPS() ? "un file protetto sul server" : (S.stato && S.stato.portachiavi) || "il portachiavi del sistema");
  const WEBVIEW = () => /; wv\)|\bwv\b.*Chrome/i.test(navigator.userAgent || "");

  // ------------------------------------------------------------------------------------------------ utilità
  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const f of figli.flat()) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  async function chiama(metodo, percorso, corpo, sfondo) {
    const h = { "X-Token": token(), Accept: "application/json" };
    if (sessione) h["X-Vault-Sessione"] = sessione;
    if (sfondo) h["X-Vault-Sfondo"] = "1";
    if (corpo) h["Content-Type"] = "application/json";
    const r = await fetch("/api/vault/" + percorso, { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: h, body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    d = d && typeof d === "object" ? d : {};
    if (r.status === 401 && d.bloccato && sessione) { blocca(true); }
    if (!sfondo && sessione && r.status === 200) S.ultimoTocco = Date.now();
    return { stato: r.status, d };
  }
  const errore = (r) => r.d.errore || ("errore " + r.stato);
  function avviso(testo, tipo) {
    if (!N.avvisi) return;
    const a = el("div", { class: "vt-avviso" + (tipo ? " vt-avviso-" + tipo : ""), role: "status" }, testo);
    N.avvisi.append(a);
    setTimeout(() => a.remove(), 4500);
  }
  function dominio(link) {
    try { return new URL(/^https?:\/\//.test(link) ? link : "https://" + link).hostname.replace(/^www\./, ""); } catch (e) { return link || ""; }
  }
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.max(0, s % 60)).padStart(2, "0")}`;

  // ------------------------------------------------------------------------------------------------ appunti
  let svuotaAppunti = null;
  async function copia(valore) {
    try {
      await navigator.clipboard.writeText(valore);
    } catch (e) { avviso("Il browser non ha concesso gli appunti.", "rosso"); return false; }
    clearTimeout(svuotaAppunti);
    const s = (S.stato && S.stato.svuota_appunti_s) || 30;
    svuotaAppunti = setTimeout(() => { navigator.clipboard.writeText("").catch(() => {}); }, s * 1000);
    avviso(`Copiato. Gli appunti si svuotano fra ${s} secondi.`);
    return true;
  }

  // ------------------------------------------------------------------------------------------------ menu e vista
  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="vault"]')) {
      const a = el("a", { href: "#vault", "data-vista": VISTA, title: "Accessi, carte, PIN e variabili, cifrati" },
        el("i", { class: "spia grigia" }), "Vault");
      const dopo = menu.querySelector('a[data-vista="connessioni"]') || menu.querySelector('a[data-vista="registro"]');
      if (dopo) menu.insertBefore(a, dopo.nextSibling); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="vault"]')) {
      const b = el("a", { href: "#vault", "data-vista": VISTA },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "🔒"),
        el("span", {}, "Vault"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.vault) TITOLI.vault = "Vault"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }
  function creaVista() {
    const main = document.querySelector("main") || document.body;
    if (document.querySelector('section[data-vista="vault"]')) return false;
    N.radice = el("div", { class: "vt" });
    N.avvisi = el("div", { class: "vt-avvisi", "aria-live": "polite" });
    N.vista = el("section", { class: "vista vista-vault", "data-vista": VISTA, "aria-label": "Vault" }, N.radice, N.avvisi);
    main.append(N.vista);
    N.vista.addEventListener("pointerdown", attivita, true);
    N.vista.addEventListener("keydown", attivita, true);
    return true;
  }

  // ------------------------------------------------------------------------------------------------ blocco automatico
  function attivita() {
    S.ultimaAttivita = Date.now();
    if (sessione && Date.now() - S.ultimoTocco > 60000) chiama("POST", "tocca", {}).catch(() => {});
  }
  function orologio() {
    if (!sessione) return;
    const minuti = (S.stato && S.stato.blocco_minuti) || 5;
    const resta = Math.round((minuti * 60000 - (Date.now() - S.ultimaAttivita)) / 1000);
    if (resta <= 0) { blocca(); return; }
    if (N.timer) N.timer.textContent = "🔓 " + mmss(resta);
  }
  function blocca(daServer) {
    const avevo = sessione;
    if (avevo && !daServer) chiama("POST", "blocca", {}).catch(() => {});
    sessione = null;
    Object.assign(S, { voci: [], sezioni: [], categorie: {}, det: null, sel: null, ambiente: null, firmaAmb: "",
      pannello: "lista", cassetto: false, codiceNuovo: null });
    S.filtro = { cat: null, sezione: null, tag: null, q: "" };
    clearInterval(T.orologio); clearInterval(T.osservatore); T.orologio = T.osservatore = null;
    chiudiModale();
    if (S.stato) S.stato.sbloccato = false;
    disegna();
  }
  function aperto(gettone) {
    sessione = gettone;
    S.ultimaAttivita = S.ultimoTocco = Date.now();
    clearInterval(T.orologio);
    T.orologio = setInterval(orologio, 1000);
    clearInterval(T.osservatore);
    T.osservatore = setInterval(osserva, 5000);
  }
  document.addEventListener("visibilitychange", () => {
    if (!sessione) return;
    if (document.hidden) { clearTimeout(T.nascosta); T.nascosta = setTimeout(() => { if (document.hidden) blocca(); }, 60000); }
    else clearTimeout(T.nascosta);
  });
  window.addEventListener("pagehide", () => {
    if (!sessione) return;
    try {
      fetch("/api/vault/blocca", { method: "POST", keepalive: true, credentials: "same-origin",
        headers: { "X-Token": token(), "X-Vault-Sessione": sessione, "Content-Type": "application/json" }, body: "{}" });
    } catch (e) { /* niente */ }
  });

  // ------------------------------------------------------------------------------------------------ dati
  async function caricaStato() {
    const r = await chiama("GET", "stato");
    if (r.stato === 200) S.stato = r.d;
    return r.stato;
  }
  async function caricaVoci() {
    const r = await chiama("GET", "voci");
    if (r.stato !== 200) { S.errore = errore(r); return false; }
    S.voci = r.d.voci || []; S.sezioni = r.d.sezioni || []; S.categorie = r.d.categorie || {}; S.pinAttivo = !!r.d.pin_attivo;
    S.errore = "";
    return true;
  }
  async function caricaDettaglio(id) {
    const r = await chiama("GET", "voce?id=" + encodeURIComponent(id));
    if (r.stato === 200) { S.det = r.d; S.sel = id; } else { S.det = null; S.sel = null; avviso(errore(r), "rosso"); }
  }
  async function caricaAmbiente(sfondo) {
    const r = await chiama("GET", "ambiente?giro=1", null, sfondo);
    if (r.stato !== 200) return false;
    S.ambiente = r.d;
    return true;
  }
  async function osserva() {                    // l'osservatore: ogni 5 s, non sposta il blocco automatico
    if (!sessione || document.hidden || location.hash.split("/")[0] !== "#vault") return;
    if (!S.voci.some((v) => v.tipo === "variabile") && !N.ambiente) return;
    const prima = S.firmaAmb;
    if (!(await caricaAmbiente(true))) return;
    S.firmaAmb = JSON.stringify(S.ambiente.variabili) + "|" + S.ambiente.vero.quante + "|" + S.ambiente.prova.quante;
    if (prima && prima !== S.firmaAmb) {
      const r = await chiama("GET", "voci", null, true);
      if (r.stato === 200) { S.voci = r.d.voci || []; }
      if (S.sel) {
        const d = await chiama("GET", "voce?id=" + encodeURIComponent(S.sel), null, true);
        if (d.stato === 200) S.det = d.d;
      }
      disegna();
      if (N.ambiente) disegnaAmbiente();
    } else if (N.ambiente) disegnaAmbiente();
  }

  // ------------------------------------------------------------------------------------------------ disegno
  function disegna() {
    if (!N.radice) return;
    N.radice.replaceChildren();
    N.timer = null;
    const st = S.stato || {};
    if (!st.cifratura) {
      N.radice.append(scheda("Vault spento", el("p", {}, "Manca la libreria di cifratura «cryptography» nel Python del Command Center."),
        el("p", { class: "vt-tenue" }, WIN()
          ? "Su Windows: rilancia INSTALLA.ps1 (la mette nell'ambiente .venv), poi riavvia il Command Center."
          : "Su macOS: python3 -m venv ~/.jarvis/vault-venv && ~/.jarvis/vault-venv/bin/pip install -r requirements/vault.txt, poi riavvia il Command Center."),
        el("p", { class: "vt-tenue vt-piccolo" }, "Guida: docs/wiki/Vault.md.")));
      return;
    }
    if (!st.posto_ok) { N.radice.append(scheda("Vault spento", el("p", {}, st.posto_errore || "Cartella non sicura."))); return; }
    if (st.remoto && !sessione) { N.radice.append(schermoRemoto()); return; }
    if (S.codiceNuovo) { N.radice.append(schermoCodice()); return; }
    if (!st.creato) { N.radice.append(schermoCrea()); return; }
    if (!sessione) {
      if (st.richiesta_uso) N.radice.append(el("p", { class: "vt-nota vt-uso-avviso", role: "status" },
        `${nomeA()} chiede di usare un accesso: sblocca il Vault per decidere (Consenti o Nega).`));
      N.radice.append(S.recupero ? schermoRecupero() : schermoBloccato()); return;
    }
    N.radice.append(schermoAperto());
  }
  // Modo VPS (avanzato, config.json «remoto»): un solo Vault, quello del tuo server. Qui solo il rimando.
  function schermoRemoto() {
    return scheda("Il Vault sta sul tuo server",
      el("p", {}, "C'è un solo Vault: quello del tuo sito. Si apre con lo stesso accesso (login del sito, poi email e password o Google)."),
      el("a", { class: "vt-primario vt-link-bottone", href: S.stato.remoto, target: "_blank", rel: "noopener noreferrer" }, "Apri il Vault sul sito ↗"),
      el("p", { class: "vt-tenue vt-piccolo" }, "Il file del Vault di questo computer resta come archivio cifrato finché non decidi di toglierlo."));
  }

  // ------------------------------------------------------------------------------------------------ richieste di uso (macOS e VPS)
  // Un agente chiede di compilare un campo nel browser con una voce del Vault. Il valore non passa da qui:
  // la pagina dice solo Consenti o Nega, il server compila il campo. Una richiesta alla volta, 5 minuti.
  let usoVisto = "";
  async function controllaUso() {
    if (!(S.stato && S.stato.uso_agenti) || document.hidden) return;
    if (!sessione) {
      const prima = !!(S.stato && S.stato.richiesta_uso);
      const r = await chiama("GET", "stato", null, true);
      if (r.stato === 200) { S.stato = r.d; if (!!r.d.richiesta_uso !== prima && attiva()) disegna(); }
      return;
    }
    const r = await chiama("GET", "uso/attesa", null, true);
    const q = r.stato === 200 ? r.d.richiesta : null;
    if (!q || q.id === usoVisto) return;
    usoVisto = q.id;
    if (!attiva()) location.hash = "#vault";
    finestraUso(q);
  }
  function finestraUso(q) {
    const resta = el("strong", {}, mmss(q.scade_s));
    let s = q.scade_s;
    const t = setInterval(() => { s -= 1; resta.textContent = mmss(Math.max(0, s)); if (s <= 0) { clearInterval(t); chiudiModale(); } }, 1000);
    const decidi = async (consenti, bottone) => {
      bottone.disabled = true; bottone.textContent = consenti ? "Compilo…" : "Nego…";
      const r = await chiama("POST", "uso/decidi", { id: q.id, consenti });
      clearInterval(t); chiudiModale();
      if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
      const e = r.d;
      if (e.stato === "compilata") avviso(`Fatto: «${e.nome}» scritto nel browser «${e.browser}» su ${e.host}.`);
      else if (e.stato === "in corso" && e.campo === "codice") avviso(`Consentito: cerco il codice nella casella ${e.casella || "della voce"} (ultimi 5 minuti, solo mail del sito) e lo scrivo nel campo.`);
      else if (e.stato === "negata") avviso("Richiesta negata.");
      else avviso(`Non compilato: ${e.motivo || e.stato}`, "rosso");
    };
    const nega = el("button", { type: "button", class: "vt-secondario", onclick: (ev) => decidi(false, ev.currentTarget) }, "Nega");
    const ok = el("button", { type: "button", class: "vt-primario", onclick: (ev) => decidi(true, ev.currentTarget) }, "Consenti una volta");
    apriModale("Richiesta di uso", el("div", { class: "vt-modulo vt-uso" },
      el("p", {}, `${q.chi} (${nomeA()}) chiede di usare `, el("strong", {}, `«${q.nome}»`),
        q.campo === "codice" ? " · codice di verifica dalla mail (casella scritta nella voce, ultimi 5 minuti, solo mittenti del sito)" : ` · campo ${q.campo}`),
      el("p", { class: "vt-tenue" }, `Browser «${q.browser}»`, q.host_scheda ? ` · scheda aperta su ${q.host_scheda}` : " · nessuna scheda riconosciuta"),
      el("p", { class: "vt-tenue vt-piccolo" }, "Il valore va solo nel campo del sito, se il sito è uno dei domini scritti nella voce. Chi chiede non lo vede. Scade fra ", resta, "."),
      el("div", { class: "vt-azioni-riga" }, nega, ok)), () => { clearInterval(t); chiudiModale(); });
    requestAnimationFrame(() => { try { nega.focus(); } catch (e) { /* niente */ } });
  }
  function scheda(titolo, ...corpo) {
    return el("div", { class: "vt-centro" }, el("div", { class: "vt-scheda" }, el("h2", { class: "vt-scheda-titolo" }, titolo), ...corpo));
  }
  function campoSegreto(attrs) {
    const i = el("input", Object.assign({ type: "password", autocomplete: "new-password", spellcheck: "false", class: "vt-input" }, attrs));
    const occhio = el("button", { type: "button", class: "vt-ico", "aria-label": "Mostra o nascondi quello che scrivi",
      onclick: () => { i.type = i.type === "password" ? "text" : "password"; } }, "👁");
    return { input: i, nodo: el("div", { class: "vt-riga-input" }, i, occhio) };
  }
  function messaggio() { return el("p", { class: "vt-errore", role: "alert", hidden: !S.errore }, S.errore || ""); }

  // ---------------------------------------------------------------- accesso: email e password oppure Google
  function forza(p) {                      // solo un suggerimento, come forza_password in vault_cc.py
    const classi = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length;
    const punti = p.length + 4 * (classi - 1) - (new Set(p).size < p.length / 2 ? 8 : 0);
    return punti >= 22 ? "buona" : punti >= 15 ? "media" : "debole";
  }
  function campoPassword(id, etichetta, conForza) {
    const c = campoSegreto({ id, "aria-label": etichetta, autocomplete: conForza ? "new-password" : "current-password" });
    const nota = conForza ? el("small", { class: "vt-tenue vt-forza", "aria-live": "polite" }, "Almeno 12 caratteri.") : null;
    if (conForza) c.input.addEventListener("input", () => {
      const v = c.input.value;
      nota.textContent = v.length < 12 ? `Almeno 12 caratteri (ora ${v.length}).` : `Forza: ${forza(v)}.`;
    });
    return { input: c.input, nodo: el("div", {}, el("label", { for: id }, etichetta), c.nodo, nota) };
  }
  // Il giro con Google: finestra di Google, poi la pagina chiede l'esito ogni secondo. Restituisce {biglietto, email}.
  async function accessoGoogle() {
    const r = await chiama("GET", "google/inizio");
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return null; }
    const finestra = window.open(r.d.url, "vault-google", "popup,width=480,height=680");
    if (!finestra) { avviso("Il browser ha bloccato la finestra di Google: consentila per questa pagina.", "rosso"); return null; }
    avviso("Completa l'accesso nella finestra di Google…");
    const fine = Date.now() + 5 * 60000;
    let chiusaDa = 0;
    while (Date.now() < fine) {
      await new Promise((ok) => setTimeout(ok, 1000));
      const e = await chiama("GET", "google/esito?stato=" + encodeURIComponent(r.d.stato));
      if (e.stato === 200 && e.d.biglietto) return { biglietto: e.d.biglietto, email: e.d.email };
      if (e.stato === 200 && e.d.errore) { avviso(e.d.errore, "rosso"); return null; }
      if (finestra.closed) { chiusaDa = chiusaDa || Date.now(); if (Date.now() - chiusaDa > 3000) { avviso("Accesso con Google annullato."); return null; } }
    }
    avviso("Accesso con Google scaduto.", "rosso");
    return null;
  }
  function bottoneGoogle(testo, azione) {
    const pronto = S.stato && S.stato.google_pronto;
    return el("div", { class: "vt-google" },
      el("button", { type: "button", class: "vt-secondario vt-google-bottone", disabled: pronto ? null : true,
        title: pronto ? "" : S.stato.google_motivo, onclick: azione }, el("span", { class: "vt-g", "aria-hidden": "true" }, "G"), " ", testo),
      pronto ? null : el("small", { class: "vt-tenue" }, S.stato.google_motivo || "Accesso con Google non configurato."));
  }
  const notaGoogle = () => el("div", {},
    el("p", { class: "vt-tenue vt-piccolo" }, VPS()
      ? "Google conferma chi sei, non cifra i dati: la chiave del dispositivo sta in un file protetto sul server. Per un muro anche contro chi amministra il server attiva «Con Google chiedi anche la password» (menu ⋯). Conserva le 24 parole di recupero."
      : `Google conferma chi sei, non cifra i dati: la chiave sta in ${PORTACHIAVI()} di questo computer. Conserva le 24 parole di recupero.`),
    VPS() && WEBVIEW() ? el("p", { class: "vt-nota vt-piccolo" }, "Dentro l'app Google non permette l'accesso: usa email e password o il PIN, oppure apri il sito in Chrome.") : null);

  function schermoCrea() {
    const email = el("input", { type: "email", class: "vt-input", id: "vt-email", autocomplete: "email", required: true, "aria-label": "Email" });
    const p1 = campoPassword("vt-f1", "Password", true);
    const p2 = campoPassword("vt-f2", "Ripeti la password", false);
    const err = messaggio();
    const bottone = el("button", { type: "submit", class: "vt-primario" }, "Crea il Vault");
    const fatto = async (r) => {
      p1.input.value = p2.input.value = "";
      if (r.stato !== 200) { S.errore = errore(r); disegna(); return; }
      S.errore = ""; aperto(r.d.sessione); S.codiceNuovo = r.d.codice_recupero; S.stato.creato = true;
      await caricaStato(); disegna();
    };
    const vai = async (e) => {
      e.preventDefault();
      if (p1.input.value.length < 12) { S.errore = "La password deve avere almeno 12 caratteri."; disegna(); return; }
      if (p1.input.value !== p2.input.value) { S.errore = "Le due password non sono uguali."; disegna(); return; }
      bottone.disabled = true; bottone.textContent = "Creo il Vault…";
      await fatto(await chiama("POST", "crea", { email: email.value, password: p1.input.value }));
    };
    return scheda("Crea il tuo Vault",
      el("p", { class: "vt-stato-iniziale", role: "status" }, "Vault non ancora creato."),
      bottoneGoogle("Crea con Google", async () => {
        const g = await accessoGoogle();
        if (g) await fatto(await chiama("POST", "crea", { biglietto: g.biglietto }));
      }),
      notaGoogle(),
      el("p", { class: "vt-oppure" }, el("span", {}, "oppure con email e password")),
      el("form", { class: "vt-modulo", onsubmit: vai },
        el("label", { for: "vt-email" }, "Email"), email, p1.nodo, p2.nodo, err, bottone,
        el("p", { class: "vt-tenue vt-piccolo" }, `Dati cifrati ${QUI()} (AES-256-GCM), chiave del dispositivo in ${PORTACHIAVI()}. ${nomeA()} vede solo nomi e stato, mai i valori.`),
        S.stato.portachiavi_debole ? el("p", { class: "vt-nota vt-piccolo" }, "Ripiego: la chiave del dispositivo sta in un file con i permessi del tuo utente (il portachiavi del sistema non è disponibile). Il Vault resta cifrato con la tua password, ma chi copia la cartella del Vault può provare a indovinarla: scegli una password lunga.") : null));
  }
  function schermoCodice() {
    const ok = el("input", { type: "checkbox", id: "vt-ok" });
    const avanti = el("button", { type: "button", class: "vt-primario", disabled: true,
      onclick: async () => { S.codiceNuovo = null; await dopoSblocco(); } }, "Continua");
    ok.addEventListener("change", () => { avanti.disabled = !ok.checked; });
    const parole = String(S.codiceNuovo || "").split(" ");
    return scheda("Le 24 parole di recupero",
      el("p", {}, "Scrivile su carta, in ordine, e tienile in un posto sicuro. Aprono il Vault se perdi la password, l'accesso Google o " + (VPS() ? "la chiave del server" : "questo computer") + ". Non le rivedrai."),
      el("ol", { class: "vt-parole", "aria-label": "Parole di recupero" }, ...parole.map((p) => el("li", {}, p))),
      el("label", { class: "vt-spunta", for: "vt-ok" }, ok, "Le ho scritte su carta"), avanti);
  }
  function schermoBloccato() {
    const acc = S.stato.accesso || {};
    const pin = S.modoSblocco === "pin" && acc.pin;
    const err = messaggio();
    const bottone = el("button", { type: "submit", class: "vt-primario" }, "Sblocca");
    let campi, leggi, input;
    if (pin) {
      input = el("input", { type: "password", inputmode: "numeric", autocomplete: "off", class: "vt-input", id: "vt-sb", maxlength: "8", "aria-label": "PIN" });
      campi = [el("label", { for: "vt-sb" }, "PIN di " + DISP()), input];
      leggi = () => ({ pin: input.value });
    } else {
      const email = el("input", { type: "email", class: "vt-input", id: "vt-email", autocomplete: "email", value: S.stato.email || "", "aria-label": "Email" });
      const p = campoPassword("vt-sb", "Password", false);
      input = p.input;
      campi = acc.password || acc.google_con_password ? [el("label", { for: "vt-email" }, "Email"), email, p.nodo] : [];
      leggi = () => ({ email: email.value, password: input.value });
    }
    const invia = async (corpo) => {
      bottone.disabled = true; bottone.textContent = "Apro…";
      const r = await chiama("POST", "sblocca", corpo);
      if (input) input.value = "";
      if (r.stato !== 200) {
        S.errore = errore(r);
        if (r.d.serve_recupero) S.recupero = true;
        if (pin && /spento/.test(S.errore)) { S.stato.accesso.pin = false; S.modoSblocco = "password"; }
        disegna(); return;
      }
      S.errore = ""; aperto(r.d.sessione); await dopoSblocco();
    };
    const nodo = scheda("🔒 Vault bloccato",
      acc.google && !pin ? bottoneGoogle("Accedi con Google", async () => {
        const g = await accessoGoogle();
        if (g) await invia(Object.assign({ biglietto: g.biglietto }, acc.google_con_password ? { password: input.value } : {}));
      }) : null,
      acc.google && acc.google_con_password && !pin ? el("p", { class: "vt-tenue vt-piccolo" }, "Con Google serve anche la password: scrivila qui sotto prima di premere il pulsante.") : null,
      acc.google && !pin ? notaGoogle() : null,
      acc.google && (acc.password || pin) ? el("p", { class: "vt-oppure" }, el("span", {}, "oppure")) : null,
      campi.length ? el("form", { class: "vt-modulo", onsubmit: (e) => { e.preventDefault(); if (input.value) invia(leggi()); } }, ...campi, err, bottone) : err,
      el("div", { class: "vt-modulo" },
        acc.pin ? el("button", { type: "button", class: "vt-secondario",
          onclick: () => { S.modoSblocco = pin ? "password" : "pin"; S.errore = ""; disegna(); } }, pin ? (acc.password ? "Usa email e password" : "Usa Google") : "Usa il PIN") : null,
        el("p", { class: "vt-tenue vt-piccolo" }, `Si blocca dopo ${S.stato.blocco_minuti || 5} minuti fermo o con la scheda nascosta per 1 minuto.`),
        el("button", { type: "button", class: "vt-link", onclick: () => { S.recupero = true; S.errore = ""; disegna(); } }, "Ho perso l'accesso")));
    requestAnimationFrame(() => { try { if (input && (pin || S.stato.email)) input.focus(); } catch (e) { /* niente */ } });
    return nodo;
  }
  function schermoRecupero() {
    const acc = S.stato.accesso || {};
    const c = el("textarea", { class: "vt-input", id: "vt-rc", rows: "4", autocomplete: "off", spellcheck: "false", placeholder: "24 parole, separate da spazi" });
    const p1 = campoPassword("vt-r1", acc.google ? "Password nuova (facoltativa con Google)" : "Password nuova", true);
    const p2 = campoPassword("vt-r2", "Ripeti la password nuova", false);
    const err = messaggio();
    const vai = async (e) => {
      e.preventDefault();
      if (p1.input.value !== p2.input.value) { S.errore = "Le due password non sono uguali."; disegna(); return; }
      const r = await chiama("POST", "recupera", { codice: c.value, nuova_password: p1.input.value });
      c.value = p1.input.value = p2.input.value = "";
      if (r.stato !== 200) { S.errore = errore(r); disegna(); return; }
      S.errore = ""; S.recupero = false; aperto(r.d.sessione); await caricaStato(); await dopoSblocco();
      avviso(`Vault riaperto ${QUI()}. Il PIN va reimpostato.`);
    };
    return scheda("Recupero del Vault",
      el("form", { class: "vt-modulo", onsubmit: vai },
        el("label", { for: "vt-rc" }, "Le 24 parole di recupero (quelle su carta)"), c, p1.nodo, p2.nodo, err,
        el("button", { type: "submit", class: "vt-primario" }, "Riapri il Vault"),
        el("button", { type: "button", class: "vt-link", onclick: () => { S.recupero = false; S.errore = ""; disegna(); } }, "Torna allo sblocco")));
  }
  async function dopoSblocco() {
    await caricaVoci();
    S.stato.sbloccato = true;
    if (S.voci.some((v) => v.tipo === "variabile")) await caricaAmbiente(true);
    disegna();
  }

  // ------------------------------------------------------------------------------------------------ Vault aperto
  function filtrate() {
    const f = S.filtro, q = f.q.trim().toLowerCase();
    return S.voci.filter((v) => {
      if (f.cat === "preferiti" && !v.preferito) return false;
      if (f.cat && f.cat !== "preferiti" && v.tipo !== f.cat) return false;
      if (f.sezione && !(v.sezione === f.sezione || v.sezione.startsWith(f.sezione + " / "))) return false;
      if (f.tag && !v.tag.includes(f.tag)) return false;
      if (!q) return true;
      const dove = [v.titolo, v.sezione, v.tag.join(" "), v.campi.link || "", dominio(v.campi.link || ""), v.campi.domini || "", v.campi.nome || ""]
        .join(" ").toLowerCase();
      return dove.includes(q);
    });
  }
  function schermoAperto() {
    const cerca = el("input", { type: "search", class: "vt-input vt-cerca", placeholder: "Cerca per nome, sito, tag, variabile…",
      "aria-label": "Cerca nel Vault", value: S.filtro.q,
      oninput: (e) => { S.filtro.q = e.target.value; disegnaLista(); } });
    N.timer = el("span", { class: "vt-timer", title: "Tempo prima del blocco automatico" }, "🔓");
    const testa = el("div", { class: "vt-testa" },
      el("button", { type: "button", class: "vt-ico vt-solo-stretto", "aria-label": "Categorie e sezioni",
        onclick: () => { S.cassetto = !S.cassetto; disegna(); } }, "☰"),
      el("h2", { class: "vt-titolo" }, "Vault"), cerca,
      el("button", { type: "button", class: "vt-primario vt-nuova", "aria-label": "Nuova voce", onclick: () => sceltaTipo() }, "+", el("span", { class: "vt-largo" }, " Nuova")),
      N.timer,
      el("button", { type: "button", class: "vt-secondario vt-blocca", "aria-label": "Blocca il Vault", onclick: () => blocca() },
        el("span", { class: "vt-stretto", "aria-hidden": "true" }, "🔒"), el("span", { class: "vt-largo" }, "Blocca")),
      el("button", { type: "button", class: "vt-ico", "aria-label": "Altre azioni", onclick: menuAltro }, "⋯"));
    N.lato = el("nav", { class: "vt-lato" + (S.cassetto ? " vt-cassetto-aperto" : ""), "aria-label": "Categorie e sezioni" });
    N.lista = el("div", { class: "vt-lista", role: "list" });
    N.det = el("div", { class: "vt-det" });
    const corpo = el("div", { class: "vt-corpo", "data-pannello": S.pannello }, N.lato, N.lista, N.det);
    if (S.cassetto) corpo.append(el("div", { class: "vt-velo", onclick: () => { S.cassetto = false; disegna(); } }));
    disegnaLato(); disegnaLista(); disegnaDettaglio();
    setTimeout(orologio, 0);
    return el("div", { class: "vt-aperto" }, testa, S.errore ? messaggio() : null, corpo);
  }
  function voceLato(testo, conta, attivo, onclick, extra) {
    return el("li", {}, el("button", { type: "button", class: "vt-lato-voce" + (attivo ? " vt-attiva" : ""), onclick, "aria-pressed": attivo ? "true" : "false" },
      el("span", {}, testo), conta != null ? el("b", { class: "vt-conta" }, conta) : null), extra || null);
  }
  function disegnaLato() {
    const f = S.filtro;
    const scegli = (k, v) => () => { S.filtro = Object.assign({ cat: null, sezione: null, tag: null, q: S.filtro.q }, { [k]: v }); S.cassetto = false; S.pannello = "lista"; disegna(); };
    const conta = (fn) => S.voci.filter(fn).length;
    const cat = el("ul", { class: "vt-lato-elenco" },
      voceLato("Tutte le voci", S.voci.length, !f.cat && !f.sezione && !f.tag, scegli("cat", null)),
      voceLato("★ Preferiti", conta((v) => v.preferito), f.cat === "preferiti", scegli("cat", "preferiti")),
      ...TIPI.map(([t]) => voceLato(S.categorie[t] || NOME_TIPO[t], conta((v) => v.tipo === t), f.cat === t, scegli("cat", t),
        el("button", { type: "button", class: "vt-ico vt-mini", "aria-label": "Rinomina la categoria", onclick: () => rinominaCategoria(t) }, "✎"))));
    const sez = el("ul", { class: "vt-lato-elenco" },
      ...S.sezioni.map((s) => voceLato(s, conta((v) => v.sezione === s || v.sezione.startsWith(s + " / ")), f.sezione === s, scegli("sezione", s),
        el("button", { type: "button", class: "vt-ico vt-mini", "aria-label": "Rinomina o togli la sezione " + s, onclick: () => modificaSezione(s) }, "✎"))));
    const tutti = [...new Set(S.voci.flatMap((v) => v.tag))].sort();
    const tag = el("div", { class: "vt-tag-elenco" }, ...tutti.map((t) => el("button", { type: "button", class: "vt-tag" + (f.tag === t ? " vt-attiva" : ""), onclick: scegli("tag", f.tag === t ? null : t) }, "#" + t)));
    N.lato.replaceChildren(...[
      el("h3", { class: "vt-lato-titolo" }, "Categorie"), cat,
      el("h3", { class: "vt-lato-titolo" }, "Sezioni", el("button", { type: "button", class: "vt-ico vt-mini", "aria-label": "Aggiungi una sezione", onclick: nuovaSezione }, "+")), sez,
      tutti.length ? el("h3", { class: "vt-lato-titolo" }, "Tag") : null, tutti.length ? tag : null].filter(Boolean));
  }
  function sottotitolo(v) {
    const c = v.campi;
    if (v.tipo === "accesso") {
      const parti = [dominio(c.link) || "senza link"];
      if (c.metodo === "google") parti.push("con Google"); else if (c.metodo === "passkey") parti.push("passkey");
      if (c.due_fa && c.due_fa !== "nessuno") parti.push("2FA: " + c.due_fa);
      return parti.join(" · ");
    }
    if (v.tipo === "carta") return `•••• ${c.ultime4 || "----"} · ${c.scadenza_mese || "--"}/${c.scadenza_anno || "--"}`;
    if (v.tipo === "pin") return c.uso || "PIN";
    if (v.tipo === "variabile") {
      const s = S.ambiente && S.ambiente.variabili[v.id];
      return (c.nome || "") + (s ? " · " + s.stato : "");
    }
    return "Nota sicura";
  }
  function disegnaLista() {
    if (!N.lista) return;
    const voci = filtrate();
    const f = S.filtro;
    const titolo = f.cat === "preferiti" ? "Preferiti" : f.cat ? (S.categorie[f.cat] || NOME_TIPO[f.cat]) : f.sezione ? f.sezione : f.tag ? "#" + f.tag : "Tutte le voci";
    N.lista.replaceChildren(el("div", { class: "vt-lista-testa" }, titolo, el("span", { class: "vt-tenue" }, " · " + voci.length)));
    if (!voci.length) {
      N.lista.append(el("p", { class: "vt-vuoto" }, S.voci.length ? "Nessuna voce con questo filtro." : "Il Vault è vuoto. Premi «+ Nuova» per aggiungere la prima voce."));
      return;
    }
    for (const v of voci) {
      const s = v.tipo === "variabile" && S.ambiente && S.ambiente.variabili[v.id];
      N.lista.append(el("button", { type: "button", role: "listitem", class: "vt-voce" + (S.sel === v.id ? " vt-attiva" : ""),
        onclick: async () => { await caricaDettaglio(v.id); S.pannello = "dettaglio"; disegna(); } },
        el("span", { class: "vt-voce-ico", "aria-hidden": "true" }, ICONA[v.tipo]),
        el("span", { class: "vt-voce-testo" },
          el("span", { class: "vt-voce-titolo" }, v.preferito ? "★ " : "", v.titolo),
          el("span", { class: "vt-voce-sotto" }, sottotitolo(v))),
        s ? el("i", { class: "vt-pallino vt-" + (STATI[s.stato] || "grigio"), title: s.stato }) : null,
        el("span", { class: "vt-freccia", "aria-hidden": "true" }, "›")));
    }
  }

  // ------------------------------------------------------------------------------------------------ dettaglio
  function rigaCampo(v, nome, campo) {
    const etichetta = ETICHETTE[nome] || (nome.startsWith("extra:") ? nome.slice(6) : nome);
    if (campo && typeof campo === "object" && campo.segreto) {
      if (!campo.presente) return null;
      const val = el("span", { class: "vt-valore vt-mono", "data-segreto": "1" }, MASCHERA);
      let rimaschera = null;
      const mostra = el("button", { type: "button", class: "vt-ico", "aria-label": "Mostra " + etichetta,
        onclick: async () => {
          if (val.dataset.visibile === "1") { val.textContent = MASCHERA; val.dataset.visibile = ""; mostra.textContent = "👁"; return; }
          const valore = await chiediValore(v.id, nome, campo.a_parte, false);
          if (valore == null) return;
          val.textContent = valore || "(vuoto)"; val.dataset.visibile = "1"; mostra.textContent = "🙈";
          clearTimeout(rimaschera);
          rimaschera = setTimeout(() => { val.textContent = MASCHERA; val.dataset.visibile = ""; mostra.textContent = "👁"; }, 20000);
        } }, "👁");
      const cp = el("button", { type: "button", class: "vt-ico", "aria-label": "Copia " + etichetta,
        onclick: async () => { const valore = await chiediValore(v.id, nome, campo.a_parte, true); if (valore != null) await copia(valore); } }, "⧉");
      return el("div", { class: "vt-campo" }, el("span", { class: "vt-etichetta" }, etichetta),
        el("span", { class: "vt-campo-valore" }, val, campo.a_parte ? el("small", { class: "vt-tenue" }, " sblocco a parte") : null),
        el("span", { class: "vt-azioni" }, mostra, cp));
    }
    if (!campo) return null;
    let testo = String(campo);
    if (nome === "metodo") testo = (METODI.find((m) => m[0] === campo) || [0, campo])[1];
    if (nome === "due_fa") testo = (DUE_FA.find((m) => m[0] === campo) || [0, campo])[1];
    if (nome === "due_fa_chi") testo = campo === "assistente" ? `${nomeA()} da solo (solo la casella automatica)` : "Con un tuo «Consenti»";
    if (nome === "circuito") testo = { visa: "Visa", mastercard: "Mastercard", amex: "American Express", altro: "Altro" }[campo] || campo;
    if (nome === "tre_ds") testo = { app: "App della banca", sms: "SMS", nessuno: "Nessuno" }[campo] || campo;
    if (nome === "destinazione") testo = campo === "prova" ? "copia di prova" : campo === "vero" ? "file vero" : "nessuno";
    if (nome === "account_collegato") { const a = S.voci.find((x) => x.id === campo); testo = a ? a.titolo : "(voce tolta)"; }
    const azioni = [];
    if (nome === "link") {
      const url = /^https?:\/\//.test(testo) ? testo : "https://" + testo;
      azioni.push(el("a", { class: "vt-ico", href: url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Apri il sito" }, "↗"));
    }
    if (["utente", "mail", "link", "assistenza", "nome"].includes(nome)) {
      azioni.push(el("button", { type: "button", class: "vt-ico", "aria-label": "Copia " + etichetta, onclick: () => copia(String(campo)) }, "⧉"));
    }
    return el("div", { class: "vt-campo" }, el("span", { class: "vt-etichetta" }, etichetta),
      el("span", { class: "vt-campo-valore vt-valore" }, testo), el("span", { class: "vt-azioni" }, ...azioni));
  }
  async function chiediValore(id, campo, aParte, perCopia) {
    let extra = {};
    if (aParte) {
      extra = await chiediConferma("Sblocco a parte", "Questo campo vuole una conferma ogni volta: password, PIN o Google.");
      if (!extra) return null;
    }
    const r = await chiama("POST", "mostra", Object.assign({ id, campo, copia: !!perCopia }, extra));
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return null; }
    return r.d.valore;
  }
  function chiediConferma(titolo, testo) {
    // Conferma a parte: password, PIN o un nuovo accesso con Google (quello che il Vault ha attivo).
    return new Promise((fatto) => {
      const acc = (S.stato && S.stato.accesso) || {};
      const modi = [acc.password && "password", acc.pin && "pin"].filter(Boolean);
      const f = campoSegreto({ id: "vt-conf", "aria-label": "Password", autocomplete: "current-password" });
      const p = el("input", { type: "password", inputmode: "numeric", class: "vt-input", id: "vt-conf-pin", autocomplete: "off", maxlength: "8", "aria-label": "PIN" });
      let modo = modi[0] || "";
      const mostra = () => { f.nodo.hidden = modo !== "password"; p.hidden = modo !== "pin"; };
      let risolto = false;
      const fine = (v) => { if (risolto) return; risolto = true; f.input.value = ""; p.value = ""; chiudiModale(); fatto(v); };
      apriModale(titolo, el("form", { class: "vt-modulo", onsubmit: (e) => { e.preventDefault(); fine(modo === "password" ? { password: f.input.value } : { pin: p.value }); } },
        el("p", {}, testo),
        modi.length ? f.nodo : null, modi.length ? p : null,
        modi.length > 1 ? el("button", { type: "button", class: "vt-link", onclick: (e) => { modo = modo === "password" ? "pin" : "password"; mostra(); e.currentTarget.textContent = modo === "password" ? "Usa il PIN" : "Usa la password"; } }, "Usa il PIN") : null,
        acc.google ? bottoneGoogle("Conferma con Google", async () => { const g = await accessoGoogle(); if (g) fine({ biglietto: g.biglietto }); }) : null,
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: () => fine(null) }, "Annulla"),
          modi.length ? el("button", { type: "submit", class: "vt-primario" }, "Conferma") : null)), () => fine(null));
      mostra();
      requestAnimationFrame(() => { try { (modo === "pin" ? p : f.input).focus(); } catch (e) { /* niente */ } });
    });
  }
  function bloccoAlias(v) {
    // Una voce unita (stesso valore sotto più nomi): chi la usa, l'avviso di riuso e «Separa» per ogni alias.
    const alias = String(v.campi.alias || "").split(",").map((x) => x.trim()).filter(Boolean);
    const tutti = [v.campi.nome, ...alias];
    const riuso = Number(v.campi.riuso || 0);
    return el("div", { class: "vt-gruppo" },
      riuso > 1 ? el("p", { class: "vt-nota vt-nota-riuso", role: "note" }, `⚠ Password riusata da ${riuso} account. Se uno la cambia, separalo prima.`) : null,
      el("p", { class: "vt-tenue vt-piccolo" }, "Usata da: " + tutti.join(", ")),
      el("ul", { class: "vt-alias" }, ...alias.map((a) => el("li", {}, el("span", { class: "vt-mono" }, a),
        el("button", { type: "button", class: "vt-secondario", onclick: () => separa(v, a) }, "Separa un alias")))));
  }
  async function separa(v, a) {
    const ok = await new Promise((fatto) => {
      apriModale("Separa un alias", el("div", { class: "vt-modulo" },
        el("p", {}, `${a} diventa una voce sua, con lo stesso valore di adesso. Da lì in poi i cambi di ${a} riguardano solo lui; ${v.campi.nome} e gli altri nomi restano come sono.`),
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: () => { chiudiModale(); fatto(false); } }, "Annulla"),
          el("button", { type: "button", class: "vt-primario", onclick: () => { chiudiModale(); fatto(true); } }, "Separa"))), () => { chiudiModale(); fatto(false); });
    });
    if (!ok) return;
    const r = await chiama("POST", "separa", { id: v.id, alias: a });
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    await caricaVoci(); await caricaAmbiente(); await caricaDettaglio(v.id); disegna();
    avviso(`${a} ora è una voce a parte.`);
  }
  function confermaCambioAlias(d) {
    return new Promise((fatto) => {
      apriModale("Cambia il valore di più nomi", el("div", { class: "vt-modulo" },
        el("p", {}, "Il valore cambierà in: " + (d.cambiera_in || []).join(", ") + "."),
        el("p", { class: "vt-tenue" }, d.file_vero_scrivibile ? "Attenzione: la scrittura sul file vero è accesa." :
          "Nel Vault soltanto: la scrittura sul file vero è spenta, ~/.env.jarvis non cambia."),
        el("p", { class: "vt-tenue vt-piccolo" }, "Se è cambiato solo per un account, annulla e usa «Separa un alias»."),
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: () => { chiudiModale(); fatto(false); } }, "Annulla"),
          el("button", { type: "button", class: "vt-primario", onclick: () => { chiudiModale(); fatto(true); } }, "Cambia per tutti"))), () => { chiudiModale(); fatto(false); });
    });
  }
  function bloccoSincronia(v) {
    const s = S.ambiente && S.ambiente.variabili[v.id];
    const dest = v.campi.destinazione || "nessuna";
    const righe = [];
    if (dest === "nessuna") righe.push(el("p", { class: "vt-tenue" }, "Questa variabile non è collegata a un file."));
    else if (!s) righe.push(el("p", { class: "vt-tenue" }, "Controllo il file…"));
    else {
      const percorso = dest === "prova" ? S.ambiente.prova.percorso : S.ambiente.vero.percorso;
      righe.push(el("div", { class: "vt-campo" }, el("span", { class: "vt-etichetta" }, "Sincronia"),
        el("span", { class: "vt-campo-valore" }, el("i", { class: "vt-pallino vt-" + (STATI[s.stato] || "grigio") }), " ", s.stato,
          el("small", { class: "vt-tenue vt-blocco" }, percorso + (s.riga ? " · riga " + s.riga : "") + (s.impronta_file ? " · impronta " + s.impronta_file : ""))),
        el("span", {})));
      if (!s.scrivibile) righe.push(el("p", { class: "vt-nota" }, "Sola lettura: la scrittura sul file vero è spenta. Si accende solo a mano, nel config.json del Vault."));
      if (s.stato === "conflitto" || s.stato === "diversa") {
        righe.push(el("div", { class: "vt-bottoni" },
          el("button", { type: "button", class: "vt-secondario", onclick: () => risolvi(v.id, "file") }, "Tieni il file"),
          s.scrivibile ? el("button", { type: "button", class: "vt-secondario", onclick: () => risolvi(v.id, "app") }, "Tieni il Vault") : null));
      } else if (s.scrivibile && ["assente nel file", "file assente", "da scrivere"].includes(s.stato)) {
        righe.push(el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: () => risolvi(v.id, "app") }, "Scrivi nel file")));
      }
    }
    return el("div", { class: "vt-gruppo" }, ...righe);
  }
  async function risolvi(id, tieni) {
    const r = await chiama("POST", "ambiente/risolvi", { id, tieni });
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    avviso(tieni === "file" ? "Tenuto il valore del file." : "Scritto nel file (con copia di prima).");
    await caricaAmbiente(); await caricaVoci(); await caricaDettaglio(id); disegna();
  }
  function disegnaDettaglio() {
    if (!N.det) return;
    const v = S.det;
    if (!v) { N.det.replaceChildren(el("p", { class: "vt-vuoto" }, "Scegli una voce dall'elenco.")); return; }
    const c = v.campi;
    const testa = el("div", { class: "vt-det-testa" },
      el("button", { type: "button", class: "vt-ico vt-solo-stretto", "aria-label": "Torna all'elenco", onclick: () => { S.pannello = "lista"; disegna(); } }, "←"),
      el("div", { class: "vt-det-titoli" }, el("h3", { class: "vt-det-titolo" }, v.titolo),
        el("p", { class: "vt-tenue" }, [S.categorie[v.tipo] || NOME_TIPO[v.tipo], v.sezione, "classe " + v.classe].filter(Boolean).join(" · "))),
      el("button", { type: "button", class: "vt-ico" + (v.preferito ? " vt-stella" : ""), "aria-label": v.preferito ? "Togli dai preferiti" : "Metti nei preferiti", "aria-pressed": v.preferito ? "true" : "false", onclick: () => preferito(v) }, v.preferito ? "★" : "☆"),
      el("button", { type: "button", class: "vt-ico", "aria-label": "Modifica", onclick: () => modulo(v.tipo, v) }, "✎"),
      el("button", { type: "button", class: "vt-ico", "aria-label": "Altro sulla voce", onclick: () => menuVoce(v) }, "⋯"));
    const corpo = [];
    if (v.tipo === "carta") {
      corpo.push(el("div", { class: "vt-carta", style: c.colore ? `--vt-carta:${/^#[0-9a-f]{3,6}$/i.test(c.colore) ? c.colore : "#3a4a6b"}` : null },
        el("div", { class: "vt-carta-riga" }, el("span", {}, c.banca || "Banca"), el("b", {}, (c.circuito || "").toUpperCase())),
        el("div", { class: "vt-carta-numero vt-mono" }, "•••• •••• •••• " + (c.ultime4 || "----")),
        el("div", { class: "vt-carta-riga" }, el("span", {}, (c.intestatario || "").toUpperCase()), el("span", {}, `scade ${c.scadenza_mese || "--"}/${c.scadenza_anno || "--"}`))));
    }
    const ordine = Object.keys(c).filter((k) => k !== "ultime4");
    const nascosti = v.tipo === "accesso" && c.metodo === "google" ? ["password"] : [];
    for (const k of ordine) {
      if (nascosti.includes(k)) continue;
      if (v.tipo === "accesso" && k === "account_collegato" && c.metodo !== "google") continue;
      if (v.tipo === "carta" && ["scadenza_mese", "scadenza_anno", "colore"].includes(k)) continue;
      if (v.tipo === "variabile" && ["alias", "riuso"].includes(k)) continue;
      const r = rigaCampo(v, k, c[k]);
      if (r) corpo.push(r);
    }
    if (v.tipo === "carta") corpo.splice(2, 0, rigaCampo(v, "scadenza", `${c.scadenza_mese || "--"}/${c.scadenza_anno || "--"}`));
    for (const e of v.extra || []) {
      corpo.push(e.segreto ? rigaCampo(v, "extra:" + e.nome, { segreto: true, presente: e.presente, a_parte: false })
        : rigaCampo(v, e.nome, e.valore));
    }
    if (v.tipo === "carta") corpo.push(el("p", { class: "vt-nota" }, `${nomeA()} e gli agenti non usano mai questa carta: serve a te per vederla e copiarla. I pagamenti passano da un servizio di pagamento, con la tua conferma.`));
    if (v.tipo === "accesso" && c.metodo === "google") corpo.push(el("p", { class: "vt-nota" }, `${nomeA()} non scrive password su «Accedi con Google»: usa la sessione del browser e si ferma se serve una conferma.`));
    if (v.tipo === "accesso" && c.due_fa && c.due_fa !== "nessuno") corpo.push(el("p", { class: "vt-nota" }, "Codici di verifica: solo con il tuo «Consenti», mai da soli (tranne la casella automatica scritta da te in config.json, nel modo VPS)."));
    if (v.tipo === "variabile" && c.alias) corpo.push(bloccoAlias(v));
    if (v.tipo === "variabile") corpo.push(bloccoSincronia(v));
    const usi = el("div", { class: "vt-gruppo" }, el("h4", { class: "vt-sotto-titolo" }, "Usi recenti"),
      ...(v.usi && v.usi.length ? v.usi.slice(0, 6).map((u) => el("p", { class: "vt-uso" }, `${u.quando.slice(5, 16)} · ${u.azione}${u.campo ? " · " + (ETICHETTE[u.campo] || u.campo) : ""}${u.esito !== "ok" ? " · " + u.esito : ""}`))
        : [el("p", { class: "vt-tenue" }, "Nessun uso registrato.")]));
    const versioni = el("div", { class: "vt-gruppo vt-riga-versioni" }, el("span", {}, `Versioni: ${v.versioni}`),
      el("button", { type: "button", class: "vt-secondario", onclick: () => storico(v) }, "Storico"),
      v.versioni > 1 ? el("button", { type: "button", class: "vt-secondario", onclick: () => annulla(v.id) }, "Annulla l'ultima modifica") : null);
    N.det.replaceChildren(testa, el("div", { class: "vt-gruppo" }, ...corpo.filter(Boolean)), usi, versioni);
  }
  async function preferito(v) {
    const r = await chiama("POST", "salva", { id: v.id, versione_base: v.versione, tipo: v.tipo, titolo: v.titolo, classe: v.classe,
      sezione: v.sezione, tag: v.tag, preferito: !v.preferito, campi: {}, extra: (v.extra || []).map((e) => ({ nome: e.nome, segreto: e.segreto, valore: e.segreto ? { invariato: true } : e.valore })) });
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    await caricaVoci(); await caricaDettaglio(v.id); disegna();
  }
  async function annulla(id, versione) {
    const r = await chiama("POST", "annulla", versione != null ? { id, versione } : { id });
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    avviso("Rimessa la versione di prima.");
    chiudiModale();
    await caricaVoci();
    if (S.voci.some((x) => x.id === id)) await caricaDettaglio(id); else { S.det = null; S.sel = null; }
    if (S.voci.some((x) => x.tipo === "variabile")) await caricaAmbiente();
    disegna();
  }
  async function storico(v) {
    const r = await chiama("GET", "storico?id=" + encodeURIComponent(v.id));
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    apriModale("Storico di «" + v.titolo + "»", el("div", { class: "vt-modulo" },
      el("p", { class: "vt-tenue" }, "Ultime 20 versioni, cifrate. «Rimetti» crea una versione nuova uguale a quella scelta."),
      el("ul", { class: "vt-storico" }, ...r.d.versioni.map((x) => el("li", {},
        el("span", {}, `v${x.versione} · ${x.quando || ""} · ${x.origine}${x.eliminata ? " · eliminata" : ""}${x.attuale ? " · attuale" : ""}`),
        x.attuale ? null : el("button", { type: "button", class: "vt-secondario", onclick: () => annulla(v.id, x.versione) }, "Rimetti")))),
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Chiudi"))));
  }
  function menuVoce(v) {
    apriModale(v.titolo, el("div", { class: "vt-menu" },
      el("button", { type: "button", class: "vt-menu-voce", onclick: () => { chiudiModale(); storico(v); } }, "Storico delle versioni"),
      v.versioni > 1 ? el("button", { type: "button", class: "vt-menu-voce", onclick: () => annulla(v.id) }, "Annulla l'ultima modifica") : null,
      el("button", { type: "button", class: "vt-menu-voce vt-pericolo", onclick: async () => {
        const r = await chiama("POST", "elimina", { id: v.id });
        chiudiModale();
        if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
        S.det = null; S.sel = null; S.pannello = "lista";
        await caricaVoci(); disegna();
        avviso("Voce eliminata. Si può rimettere: riaprila dallo storico con «Annulla».");
        ultimaEliminata = v.id;
        mostraAnnullaEliminazione();
      } }, "Elimina la voce")));
  }
  let ultimaEliminata = null;
  function mostraAnnullaEliminazione() {
    if (!N.avvisi || !ultimaEliminata) return;
    const id = ultimaEliminata;
    const a = el("div", { class: "vt-avviso", role: "status" }, "Voce eliminata. ",
      el("button", { type: "button", class: "vt-link", onclick: async () => { a.remove(); await annulla(id); } }, "Annulla"));
    N.avvisi.append(a);
    setTimeout(() => a.remove(), 10000);
  }

  // ------------------------------------------------------------------------------------------------ modale
  function apriModale(titolo, contenuto, suChiudi) {
    chiudiModale();
    const chiudi = () => { if (suChiudi) suChiudi(); else chiudiModale(); };
    N.modale = el("div", { class: "vt-modale-velo", onclick: (e) => { if (e.target === N.modale) chiudi(); } },
      el("div", { class: "vt-modale", role: "dialog", "aria-modal": "true", "aria-label": titolo },
        el("div", { class: "vt-modale-testa" }, el("h3", {}, titolo), el("button", { type: "button", class: "vt-ico", "aria-label": "Chiudi", onclick: chiudi }, "×")),
        contenuto));
    N.modale.addEventListener("keydown", (e) => { if (e.key === "Escape") chiudi(); });
    (N.vista || document.body).append(N.modale);
  }
  function chiudiModale() {
    if (N.modale) { N.modale.querySelectorAll("input,textarea").forEach((i) => { i.value = ""; }); N.modale.remove(); }
    N.modale = null; N.ambiente = null;
  }

  // ------------------------------------------------------------------------------------------------ nuova voce / modifica
  function sceltaTipo() {
    apriModale("Nuova voce", el("div", { class: "vt-menu" },
      el("p", { class: "vt-tenue" }, "Che cosa vuoi salvare?"),
      ...TIPI.map(([t, nome]) => el("button", { type: "button", class: "vt-menu-voce", onclick: () => modulo(t, null) },
        el("span", { class: "vt-voce-ico", "aria-hidden": "true" }, ICONA[t]), " ", nome))));
  }
  function modulo(tipo, voce) {
    const nuovo = !voce;
    const c = voce ? voce.campi : {};
    const ctl = {};
    const segreti = {};
    const riga = (nome, nodo, nota) => el("div", { class: "vt-modulo-riga", "data-campo": nome },
      el("label", { for: "vtm-" + nome }, ETICHETTE[nome] || nome), nodo, nota ? el("small", { class: "vt-tenue" }, nota) : null);
    const testo = (nome, attrs) => { ctl[nome] = el("input", Object.assign({ type: "text", class: "vt-input", id: "vtm-" + nome, value: c[nome] && typeof c[nome] !== "object" ? c[nome] : "", autocomplete: "off" }, attrs || {})); return riga(nome, ctl[nome]); };
    const area = (nome) => { ctl[nome] = el("textarea", { class: "vt-input", id: "vtm-" + nome, rows: "3" }); if (c[nome] && typeof c[nome] !== "object") ctl[nome].value = c[nome]; return riga(nome, ctl[nome]); };
    const scelta = (nome, opzioni, valore) => { ctl[nome] = el("select", { class: "vt-input", id: "vtm-" + nome }, ...opzioni.map(([k, n]) => el("option", { value: k, selected: k === (valore || "") ? true : null }, n))); return riga(nome, ctl[nome]); };
    const segreto = (nome, conGenera, area_) => {
      const presente = c[nome] && c[nome].presente;
      const i = area_ ? el("textarea", { class: "vt-input", id: "vtm-" + nome, rows: "3", spellcheck: "false", placeholder: presente ? "invariato: scrivi per cambiare" : "" })
        : el("input", { type: "password", class: "vt-input", id: "vtm-" + nome, autocomplete: "new-password", spellcheck: "false", placeholder: presente ? "invariato: scrivi per cambiare" : "" });
      segreti[nome] = { input: i, svuota: false };
      const pezzi = [i];
      if (!area_) pezzi.push(el("button", { type: "button", class: "vt-ico", "aria-label": "Mostra o nascondi", onclick: () => { i.type = i.type === "password" ? "text" : "password"; } }, "👁"));
      if (conGenera) pezzi.push(el("button", { type: "button", class: "vt-secondario", onclick: () => { i.value = genera(20); i.type = "text"; } }, "Genera"));
      if (presente) pezzi.push(el("button", { type: "button", class: "vt-ico", "aria-label": "Svuota il campo", onclick: (e) => { segreti[nome].svuota = !segreti[nome].svuota; e.currentTarget.classList.toggle("vt-attiva", segreti[nome].svuota); i.placeholder = segreti[nome].svuota ? "sarà svuotato" : "invariato: scrivi per cambiare"; } }, "⌫"));
      return riga(nome, el("div", { class: "vt-riga-input" }, ...pezzi));
    };
    const tipoRadio = nuovo ? el("fieldset", { class: "vt-tipi" }, el("legend", {}, "Tipo"),
      ...TIPI.map(([t, n]) => el("label", { class: "vt-radio" }, el("input", { type: "radio", name: "vtm-tipo", value: t, checked: t === tipo ? true : null, onchange: () => modulo(t, null) }), n))) : null;
    // comuni
    ctl.titolo = el("input", { type: "text", class: "vt-input", id: "vtm-titolo", value: voce ? voce.titolo : "", required: true, maxlength: "200", autocomplete: "off" });
    const sezioni = [...new Set([...(S.sezioni || []), voce && voce.sezione].filter(Boolean))];
    ctl.sezione = el("select", { class: "vt-input", id: "vtm-sezione" }, el("option", { value: "" }, "(nessuna)"),
      ...sezioni.map((s) => el("option", { value: s, selected: voce && voce.sezione === s ? true : (!voce && S.filtro.sezione === s ? true : null) }, s)),
      el("option", { value: "__nuova__" }, "Nuova sezione…"));
    ctl.sezioneNuova = el("input", { type: "text", class: "vt-input", placeholder: "Nome della sezione (es. Casa / Spesa)", hidden: true, "aria-label": "Nome della sezione nuova" });
    ctl.sezione.addEventListener("change", () => { ctl.sezioneNuova.hidden = ctl.sezione.value !== "__nuova__"; });
    ctl.tag = el("input", { type: "text", class: "vt-input", id: "vtm-tag", value: voce ? voce.tag.join(", ") : "", placeholder: "cibo, mensile", autocomplete: "off" });
    ctl.preferito = el("input", { type: "checkbox", id: "vtm-pref", checked: voce && voce.preferito ? true : null });
    const righe = [
      el("div", { class: "vt-modulo-riga" }, el("label", { for: "vtm-titolo" }, "Titolo"), ctl.titolo),
      el("div", { class: "vt-modulo-riga" }, el("label", { for: "vtm-sezione" }, "Sezione"), ctl.sezione, ctl.sezioneNuova),
      el("div", { class: "vt-modulo-riga" }, el("label", { for: "vtm-tag" }, "Tag (separati da virgola)"), ctl.tag),
      el("label", { class: "vt-spunta" }, ctl.preferito, "Preferito"),
    ];
    // per tipo
    if (tipo === "accesso") {
      const accessi = S.voci.filter((x) => x.tipo === "accesso" && (!voce || x.id !== voce.id));
      righe.push(testo("link", { type: "url", placeholder: "https://…" }),
        scelta("metodo", METODI, c.metodo || "password"));
      const perPassword = el("div", { class: "vt-gruppo-campi" }, testo("utente"), testo("mail", { type: "email" }), segreto("password", true));
      const perGoogle = el("div", { class: "vt-gruppo-campi" }, scelta("account_collegato", [["", "(scegli la voce Google)"], ...accessi.map((x) => [x.id, x.titolo])], c.account_collegato),
        el("p", { class: "vt-nota" }, `${nomeA()} usa «Accedi con Google» solo con la sessione del browser, dopo il tuo «Consenti».`));
      const aggiorna = () => { const g = ctl.metodo.value === "google"; perPassword.hidden = g; perGoogle.hidden = !g; };
      ctl.metodo.addEventListener("change", aggiorna);
      righe.push(perPassword, perGoogle,
        scelta("due_fa", DUE_FA, c.due_fa || "nessuno"), testo("due_fa_dove", { placeholder: "es. SMS al +39 …, casella …" }),
        scelta("due_fa_chi", [["proprietario", "Con un tuo «Consenti»"], ["assistente", `${nomeA()} da solo (solo la casella automatica)`]], c.due_fa_chi === "assistente" ? "assistente" : "proprietario"),
        testo("domini", { placeholder: "deliveroo.it, deliveroo.com" }), segreto("codici_recupero", false, true), segreto("note", false, true));
      setTimeout(aggiorna, 0);
    } else if (tipo === "carta") {
      righe.push(testo("intestatario"), scelta("circuito", [["", "(scegli)"], ["visa", "Visa"], ["mastercard", "Mastercard"], ["amex", "American Express"], ["altro", "Altro"]], c.circuito),
        segreto("numero"),
        el("div", { class: "vt-due" }, testo("scadenza_mese", { inputmode: "numeric", maxlength: "2", placeholder: "MM" }), testo("scadenza_anno", { inputmode: "numeric", maxlength: "4", placeholder: "AA" })),
        segreto("cvv"), segreto("pin_carta"), testo("banca"), segreto("iban"), testo("assistenza"), testo("limite"),
        scelta("tre_ds", [["", "(non so)"], ["app", "App della banca"], ["sms", "SMS"], ["nessuno", "Nessuno"]], c.tre_ds),
        testo("colore", { placeholder: "#3a4a6b" }), segreto("note", false, true),
        el("p", { class: "vt-nota" }, "CVV e PIN sono facoltativi e si vedono solo con uno sblocco a parte."));
    } else if (tipo === "pin") {
      righe.push(testo("uso", { placeholder: "porta, SIM, PUK, allarme…" }), segreto("codice"), segreto("note", false, true));
    } else if (tipo === "variabile") {
      const vero = S.stato && S.stato.scrittura_file_vero;
      righe.push(testo("nome", { placeholder: "SERVIZIO__CHIAVE", pattern: "[A-Za-z_][A-Za-z0-9_]*", class: "vt-input vt-mono" }), segreto("valore"),
        scelta("destinazione", [["nessuna", "Nessun file"], ["prova", "Copia di prova (scrivibile)"], ["vero", vero ? "File vero" : "File vero (sola lettura)"]], c.destinazione || "prova"),
        testo("servizi", { placeholder: "giro-odoo, waha…" }), segreto("note", false, true));
    } else if (tipo === "nota") {
      righe.push(segreto("testo", false, true));
    }
    // campi personalizzati
    const extra = el("div", { class: "vt-extra" });
    const aggiungiExtra = (e) => {
      const n = el("input", { type: "text", class: "vt-input", placeholder: "Nome", value: e ? e.nome : "", "aria-label": "Nome del campo" });
      const val = el("input", { type: e && e.segreto ? "password" : "text", class: "vt-input", autocomplete: "new-password", placeholder: e && e.segreto && e.presente ? "invariato" : "Valore", value: e && !e.segreto ? (e.valore || "") : "", "aria-label": "Valore del campo" });
      const s = el("input", { type: "checkbox", checked: e && e.segreto ? true : null, "aria-label": "Segreto", onchange: () => { val.type = s.checked ? "password" : "text"; } });
      const r = el("div", { class: "vt-extra-riga", "data-segreto-prima": e && e.segreto ? "1" : "" }, n, val, el("label", { class: "vt-spunta" }, s, "segreto"),
        el("button", { type: "button", class: "vt-ico", "aria-label": "Togli il campo", onclick: () => r.remove() }, "×"));
      r._ctl = { n, val, s };
      extra.append(r);
    };
    for (const e of (voce && voce.extra) || []) aggiungiExtra(e);
    righe.push(el("div", { class: "vt-modulo-riga" }, el("span", { class: "vt-etichetta" }, "Campi personalizzati"), extra,
      el("button", { type: "button", class: "vt-secondario", onclick: () => aggiungiExtra(null) }, "+ Campo personalizzato")));
    // classe
    let classe = voce ? voce.classe : (tipo === "variabile" ? "servizio" : "personale");
    if (tipo !== "variabile") {
      righe.push(el("fieldset", { class: "vt-tipi", disabled: voce ? true : null }, el("legend", {}, "Classe"),
        el("label", { class: "vt-radio" }, el("input", { type: "radio", name: "vtm-classe", value: "personale", checked: classe === "personale" ? true : null, onchange: () => { classe = "personale"; } }), "Personale (solo tu)"),
        el("label", { class: "vt-radio" }, el("input", { type: "radio", name: "vtm-classe", value: "servizio", checked: classe === "servizio" ? true : null, onchange: () => { classe = "servizio"; } }), "Servizio (programmi)")));
    }
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    const salva = async (e) => {
      e.preventDefault();
      const campi = {};
      for (const [k, i] of Object.entries(ctl)) if (!["titolo", "sezione", "sezioneNuova", "tag", "preferito"].includes(k)) campi[k] = i.value;
      for (const [k, s] of Object.entries(segreti)) {
        if (s.svuota) campi[k] = "";
        else if (s.input.value) campi[k] = s.input.value;
        else if (voce) campi[k] = { invariato: true };
        else campi[k] = "";
      }
      const sezione = ctl.sezione.value === "__nuova__" ? ctl.sezioneNuova.value.trim() : ctl.sezione.value;
      const corpo = { tipo, titolo: ctl.titolo.value, classe, sezione, preferito: ctl.preferito.checked,
        tag: ctl.tag.value.split(",").map((t) => t.trim()).filter(Boolean), campi,
        extra: [...extra.children].map((r) => ({ nome: r._ctl.n.value, segreto: r._ctl.s.checked,
          valore: r._ctl.val.value ? r._ctl.val.value : (r.dataset.segretoPrima ? { invariato: true } : "") })) };
      if (voce) { corpo.id = voce.id; corpo.versione_base = voce.versione; }
      let r = await chiama("POST", "salva", corpo);
      if (r.stato === 409 && r.d.serve_conferma_alias) {
        const modale = N.modale; N.modale = null; modale.hidden = true;     // il modulo resta, nascosto, per riprovare
        const ok = await confermaCambioAlias(r.d);
        N.modale = modale; modale.hidden = false;
        if (!ok) return;
        corpo.conferma_alias = true;
        r = await chiama("POST", "salva", corpo);
      }
      if (r.stato !== 200) { err.textContent = errore(r); err.hidden = false; return; }
      chiudiModale();
      await caricaVoci();
      if (tipo === "variabile") await caricaAmbiente();
      await caricaDettaglio(r.d.id);
      if (!filtrate().some((x) => x.id === r.d.id)) S.filtro = { cat: null, sezione: null, tag: null, q: "" };
      S.pannello = "dettaglio";
      disegna();
      if (r.d.sincronia && r.d.sincronia.stato === "conflitto") avviso("Il file è cambiato nel frattempo: scegli quale valore tenere.", "rosso");
      else avviso(nuovo ? "Voce salvata." : "Modifica salvata.");
    };
    apriModale(nuovo ? "Nuova voce · " + NOME_TIPO[tipo] : "Modifica · " + voce.titolo,
      el("form", { class: "vt-modulo", onsubmit: salva, autocomplete: "off" }, tipoRadio, ...righe, err,
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
          el("button", { type: "submit", class: "vt-primario" }, "Salva"))));
    requestAnimationFrame(() => ctl.titolo.focus());
  }
  function genera(n) {
    const alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.!?";
    const b = new Uint32Array(n);
    crypto.getRandomValues(b);
    return [...b].map((x) => alfabeto[x % alfabeto.length]).join("");
  }

  // ------------------------------------------------------------------------------------------------ sezioni e categorie
  function chiediTesto(titolo, etichetta, valore, azioni) {
    const i = el("input", { type: "text", class: "vt-input", id: "vt-chiedi", value: valore || "", autocomplete: "off" });
    apriModale(titolo, el("form", { class: "vt-modulo", onsubmit: (e) => { e.preventDefault(); azioni[0][1](i.value); } },
      el("label", { for: "vt-chiedi" }, etichetta), i,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        ...azioni.map(([n, fn, cls], k) => el("button", { type: k === 0 ? "submit" : "button", class: cls || "vt-primario", onclick: k === 0 ? null : () => fn(i.value) }, n)))));
    requestAnimationFrame(() => i.focus());
  }
  async function dopoSezione(r) {
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    chiudiModale(); await caricaVoci(); if (S.sel) await caricaDettaglio(S.sel); disegna();
  }
  function nuovaSezione() {
    chiediTesto("Nuova sezione", "Nome (per una sottosezione: «Casa / Spesa»)", "", [["Aggiungi", async (v) => dopoSezione(await chiama("POST", "sezione", { nome: v }))]]);
  }
  function modificaSezione(s) {
    chiediTesto("Sezione «" + s + "»", "Nome nuovo", s, [
      ["Rinomina", async (v) => { if (S.filtro.sezione === s) S.filtro.sezione = v; await dopoSezione(await chiama("POST", "sezione", { azione: "rinomina", nome: s, nuovo: v })); }],
      ["Togli (se vuota)", async () => { if (S.filtro.sezione === s) S.filtro.sezione = null; await dopoSezione(await chiama("POST", "sezione", { azione: "togli", nome: s })); }, "vt-secondario vt-pericolo"],
      ...(window.VaultGruppi ? [["Elimina tutte le voci", () => { chiudiModale(); if (S.filtro.sezione === s) S.filtro.sezione = null; window.VaultGruppi.svuota({ sezione: s }, s); }, "vt-secondario vt-pericolo"]] : [])]);
  }
  function rinominaCategoria(t) {
    chiediTesto("Categoria", "Nome mostrato (vuoto = quello di partenza)", S.categorie[t] || NOME_TIPO[t], [["Salva", async (v) => {
      const r = await chiama("POST", "categoria", { tipo: t, nome: v });
      if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
      S.categorie = r.d.categorie; chiudiModale(); disegna();
    }], ...(window.VaultGruppi ? [["Elimina tutte le voci", () => { chiudiModale(); window.VaultGruppi.svuota({ tipo: t }, S.categorie[t] || NOME_TIPO[t]); }, "vt-secondario vt-pericolo"]] : [])]);
  }

  // ------------------------------------------------------------------------------------------------ menu «⋯»
  async function registroUsi() {
    const r = await chiama("GET", "usi");
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    const titolo = (id) => { const v = S.voci.find((x) => x.id === id); return v ? v.titolo : id; };
    apriModale("Registro degli usi", el("div", { class: "vt-modulo" },
      el("p", { class: "vt-tenue" }, "Chi ha fatto cosa e quando. Qui non c'è mai un valore."),
      el("ul", { class: "vt-storico" }, ...(r.d.usi.length ? r.d.usi.map((u) => el("li", {}, el("span", {},
        `${u.quando} · ${u.azione}${u.id ? " · " + titolo(u.id) : ""}${u.campo ? " · " + (ETICHETTE[u.campo] || u.campo) : ""}${u.esito !== "ok" ? " · " + u.esito : ""}`)))
        : [el("li", {}, "Ancora nessun uso.")]))));
  }
  function esporta() {
    const f1 = campoSegreto({ id: "vt-e1" }), f2 = campoSegreto({ id: "vt-e2" });
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    apriModale("Esporta", el("form", { class: "vt-modulo", onsubmit: async (e) => {
      e.preventDefault();
      if (f1.input.value !== f2.input.value) { err.textContent = "Le due password non sono uguali."; err.hidden = false; return; }
      const r = await chiama("POST", "esporta", { frase: f1.input.value });
      if (r.stato !== 200) { err.textContent = errore(r); err.hidden = false; return; }
      const url = URL.createObjectURL(new Blob([r.d.contenuto], { type: "application/json" }));
      const a = el("a", { href: url, download: r.d.nome, hidden: true });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      chiudiModale(); avviso("Esportazione cifrata scaricata. Senza la sua password non si apre.");
    } }, el("p", { class: "vt-tenue" }, "Un file cifrato con una password scelta adesso (almeno 12 caratteri). Mai un elenco in chiaro."),
      el("label", { for: "vt-e1" }, "Password dell'esportazione"), f1.nodo, el("label", { for: "vt-e2" }, "Ripeti"), f2.nodo, err,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, "Esporta"))));
  }
  function importa() {
    const file = el("input", { type: "file", accept: ".json,.csv,application/json,text/csv", class: "vt-input", id: "vt-if" });
    const f = campoSegreto({ id: "vt-ip" });
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    apriModale("Importa", el("form", { class: "vt-modulo", onsubmit: async (e) => {
      e.preventDefault();
      if (!file.files[0]) { err.textContent = "Scegli il file."; err.hidden = false; return; }
      if (/\.csv$/i.test(file.files[0].name) && window.VaultChrome) { chiudiModale(); window.VaultChrome.apri(); return; }
      const contenuto = await file.files[0].text();
      const r = await chiama("POST", "importa", { contenuto, frase: f.input.value });
      if (r.stato !== 200) { err.textContent = errore(r); err.hidden = false; return; }
      chiudiModale(); await caricaVoci(); disegna(); avviso(`Importate ${r.d.nuove} voci, saltate ${r.d.saltate}.`);
    } }, el("label", { for: "vt-if" }, "File dell'esportazione"), file, el("label", { for: "vt-ip" }, "Password dell'esportazione"), f.nodo, err,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, "Importa"))));
  }
  async function backup() {
    const r = await chiama("POST", "backup", {});
    chiudiModale();
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    avviso("Backup cifrato salvato in " + r.d.file);
  }
  function menuAltro() {
    const acc = (S.stato && S.stato.accesso) || {};
    apriModale("Vault", el("div", { class: "vt-menu" },
      el("button", { type: "button", class: "vt-menu-voce", onclick: importaAttuali }, "Importa le chiavi di .env.jarvis"),
      window.VaultChrome ? el("button", { type: "button", class: "vt-menu-voce", onclick: () => window.VaultChrome.apri() }, "Da Chrome (CSV)") : null,
      el("button", { type: "button", class: "vt-menu-voce", onclick: apriAmbiente }, "Ambiente e .env.jarvis"),
      el("button", { type: "button", class: "vt-menu-voce", onclick: registroUsi }, "Registro degli usi"),
      el("button", { type: "button", class: "vt-menu-voce", onclick: esporta }, "Esporta (file cifrato)"),
      el("button", { type: "button", class: "vt-menu-voce", onclick: importa }, "Importa un'esportazione del Vault"),
      el("button", { type: "button", class: "vt-menu-voce", onclick: backup }, "Backup ora"),
      window.VaultGruppi ? el("button", { type: "button", class: "vt-menu-voce", onclick: () => { chiudiModale(); window.VaultGruppi.recenti(); } }, "Eliminazioni recenti (annulla)") : null,
      el("p", { class: "vt-tenue vt-piccolo" }, `Accesso: ${S.stato.email || ""}${acc.password ? " · password" : ""}${acc.google ? " · Google" : ""}${acc.pin ? " · PIN" : ""}`),
      el("button", { type: "button", class: "vt-menu-voce", onclick: impostaPin }, acc.pin ? "Cambia il PIN di " + DISP() : "Imposta un PIN per " + DISP()),
      el("button", { type: "button", class: "vt-menu-voce", onclick: impostaPassword }, acc.password ? "Cambia la password" : "Aggiungi una password"),
      !acc.google ? el("button", { type: "button", class: "vt-menu-voce", disabled: S.stato.google_pronto ? null : true, title: S.stato.google_motivo || "", onclick: collegaGoogle }, "Collega l'account Google") : null,
      acc.google && acc.password ? el("button", { type: "button", class: "vt-menu-voce", onclick: () => googleConPassword(!acc.google_con_password) },
        acc.google_con_password ? "Con Google non chiedere più la password" : "Con Google chiedi anche la password") : null));
  }
  // Importazione delle chiavi di ~/.env.jarvis: prima il piano (solo nomi, dal server), poi «Importa ora». I valori passano
  // solo nel server (file → cifratura): né il piano né la risposta dell'importazione contengono valori.
  async function importaAttuali() {
    const corpo = el("div", { class: "vt-modulo" }, el("p", { class: "vt-tenue" }, "Preparo il piano…"));
    apriModale("Importa le chiavi di .env.jarvis", corpo);
    const r = await chiama("GET", "piano-import");
    if (r.stato !== 200) { corpo.replaceChildren(el("p", { class: "vt-errore" }, errore(r))); return; }
    const p = r.d, st = p.stati || {};
    const righe = Object.entries(p.conteggi).map(([sez, n]) => el("li", { class: "vt-piano-riga" }, el("span", {}, sez), el("b", {}, String(n))));
    const bottone = el("button", { type: "button", class: "vt-primario" }, (st["nuova nel file"] || 0) + (st.diversa || 0) ? "Importa ora" : "Riallinea ora");
    bottone.addEventListener("click", async () => {
      bottone.disabled = true; bottone.textContent = "Importo…";
      const x = await chiama("POST", "importa-attuali", {});
      if (x.stato !== 200) { avviso(errore(x), "rosso"); bottone.disabled = false; bottone.textContent = "Riprova"; return; }
      chiudiModale(); await caricaVoci(); await caricaAmbiente(); disegna();
      avviso(`Importate ${x.d.nuove} nuove, ${x.d.aggiornate} aggiornate, ${x.d.unite} unite, ${x.d.gia_presenti} già presenti.${x.d.backup_prima ? " Backup cifrato fatto prima dell'unione." : ""}`);
    });
    if (!p.env_presente) {
      corpo.replaceChildren(el("p", {}, `Il file ${p.fonte_env} non c'è: niente da importare. Per le password dei siti usa «Da Chrome (CSV)» o aggiungi le voci a mano.`),
        el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Chiudi")));
      return;
    }
    corpo.replaceChildren(...[
      el("p", {}, `Fonte: ${p.fonte_env}, ${p.righe_env} righe. Diventano ${p.voci.length} voci (${p.doppioni.length} con alias).`),
      el("p", { class: "vt-nota" }, `Nel Vault: ${st.importata || 0} già importate, ${st.diversa || 0} diverse, ${st["nuova nel file"] || 0} nuove nel file, ${st["da unire"] || 0} da unire (stesso valore: una voce con alias, backup cifrato prima). Il file non si tocca: resta la fonte.`),
      el("h4", { class: "vt-sotto-titolo" }, "Sezioni"), el("ul", { class: "vt-piano" }, ...righe),
      p.da_riordinare.length ? el("p", { class: "vt-tenue" }, `Da riordinare: ${p.da_riordinare.length}.`) : null,
      el("p", { class: "vt-tenue" }, `Doppioni: ${p.voci_unite} nomi uniti come alias in ${p.doppioni.length} voci.`),
      p.riusi.length ? el("p", { class: "vt-tenue" }, `Password riusata da più account: ${p.riusi.length} voci, con avviso e «Separa un alias».`) : null,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"), bottone)].filter(Boolean));
  }
  async function dopoAccesso(r, testo) {
    if (r.stato !== 200) { avviso(errore(r), "rosso"); return; }
    await caricaStato(); S.pinAttivo = !!(S.stato.accesso || {}).pin; chiudiModale(); avviso(testo);
  }
  async function impostaPin() {
    const conf = await chiediConferma("PIN di " + DISP(), "Prima conferma che sei tu.");
    if (!conf) return;
    const p1 = el("input", { type: "password", inputmode: "numeric", class: "vt-input", id: "vt-p1", maxlength: "8", autocomplete: "off" });
    const p2 = el("input", { type: "password", inputmode: "numeric", class: "vt-input", id: "vt-p2", maxlength: "8", autocomplete: "off" });
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    apriModale("PIN di " + DISP(), el("form", { class: "vt-modulo", onsubmit: async (e) => {
      e.preventDefault();
      if (p1.value !== p2.value) { err.textContent = "I due PIN non sono uguali."; err.hidden = false; return; }
      await dopoAccesso(await chiama("POST", "pin", Object.assign({ nuovo_pin: p1.value }, conf)), "PIN impostato. Dopo 5 errori si spegne.");
    } }, el("p", { class: "vt-tenue" }, VPS() ? "4-8 cifre. Vale per il Vault del server, insieme alla sua chiave del dispositivo; dopo 5 errori si spegne." : `4-8 cifre. Vale solo su questo computer, insieme alla chiave in ${PORTACHIAVI()}; dopo 5 errori si spegne.`),
      el("label", { for: "vt-p1" }, "PIN nuovo"), p1, el("label", { for: "vt-p2" }, "Ripeti il PIN"), p2, err,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, "Imposta"))));
  }
  async function impostaPassword() {
    const conf = await chiediConferma("Password del Vault", "Prima conferma che sei tu.");
    if (!conf) return;
    const n1 = campoPassword("vt-cn1", "Password nuova", true), n2 = campoPassword("vt-cn2", "Ripeti la password nuova", false);
    const err = el("p", { class: "vt-errore", role: "alert", hidden: true });
    apriModale("Password del Vault", el("form", { class: "vt-modulo", onsubmit: async (e) => {
      e.preventDefault();
      if (n1.input.value !== n2.input.value) { err.textContent = "Le due password non sono uguali."; err.hidden = false; return; }
      await dopoAccesso(await chiama("POST", "password", Object.assign({ nuova: n1.input.value }, conf)), "Password salvata.");
    } }, n1.nodo, n2.nodo, err,
      el("div", { class: "vt-bottoni" }, el("button", { type: "button", class: "vt-secondario", onclick: chiudiModale }, "Annulla"),
        el("button", { type: "submit", class: "vt-primario" }, "Salva"))));
  }
  async function collegaGoogle() {
    chiudiModale();
    const g = await accessoGoogle();
    if (g) await dopoAccesso(await chiama("POST", "google/collega", { biglietto_google: g.biglietto }), "Account Google collegato.");
  }
  async function googleConPassword(acceso) {
    const conf = await chiediConferma("Accesso con Google", acceso ? "Da ora con Google servirà anche la password." : (VPS() ? "Da ora basterà Google (la chiave resta nel file protetto del server)." : `Da ora basterà Google (la chiave resta in ${PORTACHIAVI()} di questo computer).`));
    if (conf) await dopoAccesso(await chiama("POST", "google/con-password", Object.assign({ acceso }, conf)), acceso ? "Con Google serve anche la password." : "Con Google basta l'accesso Google.");
  }

  // ------------------------------------------------------------------------------------------------ ambiente
  async function apriAmbiente() {
    N.ambienteCorpo = el("div", { class: "vt-modulo" }, el("p", { class: "vt-tenue" }, "Leggo i file…"));
    apriModale("Ambiente e .env.jarvis", N.ambienteCorpo);
    N.ambiente = true;
    await caricaAmbiente();
    disegnaAmbiente();
  }
  function tabellaFile(q, quale) {
    const righe = q.righe.map((r) => {
      const azioni = [el("button", { type: "button", class: "vt-ico", "aria-label": "Mostra " + r.nome, onclick: async (e) => {
        const cella = e.currentTarget.closest("li").querySelector(".vt-valore");
        if (cella.dataset.visibile === "1") { cella.textContent = MASCHERA; cella.dataset.visibile = ""; return; }
        const x = await chiama("POST", "mostra", { file: quale, nome: r.nome });
        if (x.stato !== 200) { avviso(errore(x), "rosso"); return; }
        cella.textContent = x.d.valore || "(vuoto)"; cella.dataset.visibile = "1";
        setTimeout(() => { cella.textContent = MASCHERA; cella.dataset.visibile = ""; }, 20000);
      } }, "👁")];
      if (quale === "prova" && r.nel_vault === "nuova nel file") azioni.push(el("button", { type: "button", class: "vt-secondario", onclick: async () => {
        const x = await chiama("POST", "ambiente/importa", { nome: r.nome });
        if (x.stato !== 200) { avviso(errore(x), "rosso"); return; }
        await caricaVoci(); await caricaAmbiente(); disegna(); disegnaAmbiente(); avviso(r.nome + " portata nel Vault.");
      } }, "Nel Vault"));
      return el("li", { class: "vt-amb-riga" },
        el("span", { class: "vt-mono vt-amb-nome" }, r.nome),
        el("span", { class: "vt-valore vt-mono", "data-segreto": "1" }, MASCHERA),
        el("span", { class: "vt-tenue vt-mono" }, r.impronta),
        el("span", { class: "vt-amb-stato" }, el("i", { class: "vt-pallino vt-" + (r.nel_vault === "importata" ? "verde" : r.nel_vault === "diversa" ? "giallo" : "grigio") }), " ", r.nel_vault),
        el("span", { class: "vt-azioni" }, ...azioni));
    });
    return el("div", { class: "vt-gruppo" },
      el("h4", { class: "vt-sotto-titolo" }, quale === "vero" ? "File vero" : "Copia di prova", " ",
        el("span", { class: "vt-tenue" }, q.scrivibile ? "· scrivibile" : "· sola lettura")),
      el("p", { class: "vt-tenue vt-mono vt-piccolo" }, q.percorso + (q.presente ? ` · ${q.quante} variabili · ${q.conti.importata} importate · ${q.conti.diversa} diverse · ${q.conti["nuova nel file"]} nuove nel file` : " · file assente")),
      righe.length ? el("ul", { class: "vt-amb" }, ...righe) : null);
  }
  function disegnaAmbiente() {
    if (!N.ambiente || !N.ambienteCorpo || !S.ambiente) return;
    if (N.ambienteCorpo.querySelector('[data-visibile="1"]')) return;   // non ridisegnare sopra un valore aperto
    const a = S.ambiente;
    N.ambienteCorpo.replaceChildren(
      el("p", { class: "vt-nota" }, a.scrittura_file_vero ? "Scrittura sul file vero ACCESA." :
        "Scrittura sul file vero spenta: il Vault lo legge soltanto (nomi, presenza, impronta). Si accende solo a mano, scrivendo \"scrittura_file_vero\": true nel config.json del Vault."),
      el("p", { class: "vt-tenue vt-piccolo" }, "Impronta = HMAC con una chiave del Vault (primi 8 caratteri): dice se due valori sono uguali senza mostrarli. Il controllo gira ogni 5 secondi."),
      tabellaFile(a.prova, "prova"), tabellaFile(a.vero, "vero"));
  }

  // per vault_chrome.js (file a parte): solo questi strumenti, mai la sessione in chiaro
  window.VaultPagina = { chiama, apriModale, chiudiModale, avviso, el,
    dopoImport: async () => { await caricaVoci(); await caricaAmbiente(true); disegna(); } };

  // ------------------------------------------------------------------------------------------------ avvio
  const attiva = () => location.hash.split("/")[0] === "#vault";
  async function cambio() {
    if (!attiva()) return;
    const prima = S.stato && S.stato.creato;
    await caricaStato();
    if (S.stato && S.stato.creato !== prima && !sessione) disegna();
  }
  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let codice;
    try { codice = await caricaStato(); } catch (e) { return; }
    if (codice !== 200) return;                         // da fuori del computer o con un server vecchio: niente voce, niente vista
    creaVoceMenu();
    if (!creaVista()) return;
    disegna();
    window.addEventListener("hashchange", cambio);
    setInterval(() => { controllaUso().catch(() => {}); }, 5000);   // fa qualcosa solo se l'uso dagli agenti è acceso
    if (attiva() && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
  })();
})();
