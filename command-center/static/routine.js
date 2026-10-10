// La pagina «Routine» del Command Center (2026-10-05, l'utente): tutti i lavori automatici di VPS (systemd e cron) e Mac
// (launchd), con «Avvia ora» (senza conferma), «Log», «Modifica» e «Nuova» (doppio passo: «Prepara» mostra il comando
// esatto, «Conferma ed esegui» lo lancia). In più, sulla lavagna, i comandi rapidi per gruppo «Controlli» e «Scarica
// dati». Dati: GET/POST /api/routine, GET /api/routine/log (server.py → routine.py).
// Come piani.js: si aggancia da sola al menu, a TITOLI e alla barra della lavagna. Testi sempre con textContent.
(function routine() {
  "use strict";
  const S = { dati: null, errore: "", filtro: "tutte", gruppo: "", occupato: false, timer: null, attivo: false,
    log: {}, rapidi: null, ed: null, salvato: null };   // ed: l'editor aperto (stato dei campi), salvato: esito per routine
  // 2026-10-05 sera (verificatore): l'effetto della routine, letto negli script (routine-gruppi.json)
  const EFFETTO = { scrive: ["scrive in produzione", "ro-eff-scrive"], invia: ["manda messaggi", "ro-eff-invia"],
    "": ["effetto da verificare", "ro-eff-ignoto"] };
  const etichettaEffetto = (r) => r.effetto === "lettura" ? null :
    el("span", { class: "ro-eff " + (EFFETTO[r.effetto || ""] || EFFETTO[""])[1] }, (EFFETTO[r.effetto || ""] || EFFETTO[""])[0]);
  // il campo a cui appartiene un errore del server, dalle prime parole del messaggio
  function campoDiErrore(msg) {
    const m = (msg || "").toLowerCase();
    if (m.startsWith("avanzato")) return "avanzato";
    if (/^(orario|l'orario|campo cron|valore cron|passo cron|intervallo)/.test(m)) return "orario";
    for (const c of ["comando", "descrizione", "nome", "tipo", "gruppo", "attivo"]) if (m.startsWith(c)) return c;
    return "";
  }
  const N = {};
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
  async function chiama(metodo, percorso, corpo) {
    const r = await fetch(percorso, { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
      body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }
  const ora = (t) => t ? new Date(t * 1000).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Rome" }) : "";
  const durata = (s) => s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  const nomeGruppo = (g) => ((S.dati && S.dati.nomi_gruppi) || {})[g] || g;
  const SEGNO = { ok: "✅", errore: "❌", in_corso: "⏳" };

  // ---------------------------------------------------------------- voce di menu e vista
  function creaVoceMenu() {
    const menu = document.querySelector(".schede.menu");
    if (menu && !menu.querySelector('a[data-vista="routine"]')) {
      const a = el("a", { href: "#routine", "data-vista": "routine", title: "I lavori automatici di VPS e Mac: avvia, log, modifica" },
        el("i", { class: "spia grigia" }), "Routine");
      const dopo = menu.querySelector('a[data-vista="scadenze"]');
      if (dopo && dopo.nextSibling) menu.insertBefore(a, dopo.nextSibling); else menu.append(a);
    }
    const griglia = document.querySelector("#m-foglio .m-foglio-griglia");
    if (griglia && !griglia.querySelector('a[data-vista="routine"]')) {
      const b = el("a", { href: "#routine", "data-vista": "routine" },
        el("i", { class: "spia grigia", "aria-hidden": "true" }), el("span", { class: "m-ico", "aria-hidden": "true" }, "⏱"),
        el("span", {}, "Routine"), el("b", { class: "conta" }));
      const largo = griglia.querySelector(".m-foglio-largo");
      if (largo) griglia.insertBefore(b, largo); else griglia.append(b);
    }
    try { if (typeof TITOLI === "object" && TITOLI && !TITOLI.routine) TITOLI.routine = "Routine"; } catch (e) { /* app.js vecchio */ } // eslint-disable-line no-undef
  }
  function segnaSpia() {
    const rr = (S.dati && S.dati.routine) || [];
    const errori = rr.filter((r) => r.esito === "errore" && r.attivo).length;
    const lavora = (S.dati && S.dati.esecuzioni || []).some((e) => e.stato === "in_corso" || e.stato === "partenza");
    for (const sp of document.querySelectorAll('.menu a[data-vista="routine"] .spia, #m-foglio a[data-vista="routine"] .spia'))
      sp.className = "spia " + (lavora ? "lavora" : errori ? "attenzione" : "ok");
  }

  function spia(r) {
    if (r.in_corso || r.esito === "in_corso") return "lavora";
    if (!r.attivo) return "grigia";
    if (r.esito === "errore") return "guasto";
    return r.esito === "ok" ? "ok" : "grigia";
  }
  function orarioBreve(r) {
    const o = r.orario || "";
    return o.startsWith("ogni giorno ") && o.length < 22 ? `${r.dove} ${o.slice(12)}` : `${r.dove} · ${o}`;
  }
  function ultimaEsec(id) {
    return ((S.dati && S.dati.esecuzioni) || []).find((e) => e.id === id) || null;
  }
  function testoEsec(e) {
    if (!e) return null;
    const fine = e.finito || Date.now() / 1000;
    if (e.stato === "partenza" || e.stato === "in_corso") return el("span", { class: "ro-esec ro-lavora" }, `⏳ avviata alle ${ora(e.partito)}, in corso da ${durata(fine - e.partito)}`);
    if (e.stato === "lunga") return el("span", { class: "ro-esec ro-lavora" }, `⏳ ${e.esito}`);
    return el("span", { class: "ro-esec " + (e.stato === "ok" ? "ro-ok" : "ro-ko") },
      `${e.stato === "ok" ? "✅" : "❌"} avvio a mano delle ${ora(e.partito)}: ${e.esito} (${durata(fine - e.partito)})`);
  }

  // ---------------------------------------------------------------- azioni
  async function avvia(r, bottone) {
    if (bottone) bottone.disabled = true;
    S.errore = "";
    try {
      const x = await chiama("POST", "/api/routine", { azione: "avvia", id: r.id });
      if (x.stato === 200) {
        S.dati.esecuzioni = [x.d, ...((S.dati.esecuzioni || []).filter((e) => e.eid !== x.d.eid))];
      } else S.errore = x.d.errore || ("errore " + x.stato);
    } catch (e) { S.errore = "Rete assente: la routine non è partita."; }
    disegna(); segnaSpia(); pianifica();
  }
  async function apriLog(r) {
    if (S.log[r.id] !== undefined) { delete S.log[r.id]; disegna(); return; }
    S.log[r.id] = "Leggo il log…"; disegna();
    try {
      const x = await chiama("GET", "/api/routine/log?id=" + encodeURIComponent(r.id));
      S.log[r.id] = x.stato === 200 ? (x.d.testo || "(vuoto)") : (x.d.errore || ("errore " + x.stato));
    } catch (e) { S.log[r.id] = "Rete assente."; }
    disegna();
    const pre = N.lista && N.lista.querySelector(`li[data-id="${CSS.escape(r.id)}"] .ro-log`);
    if (pre) pre.scrollTop = pre.scrollHeight;
  }
  // ---------------------------------------------------------------- l'editor (2026-10-05 pomeriggio, l'utente)
  // «Salva» applica subito (il server valida, fa il backup, applica, verifica e se non torna ripristina) e lo dice a
  // Jarvis nel filo Notifiche. Orari come le attività pianificate di Claude Code: frequenza, fasce, giorni, periodo,
  // anteprima con le prossime 3 esecuzioni vere, «Avanzato» con il grezzo. La «Regola» in italiano: Jarvis la
  // trasforma in uno script (routine/compiti/), che si vede PRIMA di salvare.
  const OGNI = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30];
  const GG = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];
  const FREQ = [["minuti", "Ogni N minuti"], ["ora", "Ogni ora"], ["giorno", "Ogni giorno"], ["settimana", "Ogni settimana"], ["una_volta", "Una volta"]];
  const copia = (x) => JSON.parse(JSON.stringify(x == null ? null : x));
  const PIANO_NUOVO = () => ({ frequenza: "giorno", orari: ["07:00"], giorni: [] });

  function apriEditor(r) {
    S.ed = { chiave: r.id, r, fonte: r.fonte, piano: copia(r.piano), pianoIniziale: JSON.stringify(r.piano),
      grezzo: r.grezzo || "", grezzoIniziale: r.grezzo || "", grezzoToccato: false, avanzato: !r.piano,
      regola: r.regola || "", regolaIniziale: r.regola || "", compito: r.compito || "", compitoIniziale: r.compito || "",
      descrizione: r.descrizione || "", attivo: !!r.attivo, script: null, errore: null, esito: null, ant: null, occupato: false };
    disegna();
    anteprima();
  }
  function apriNuova(pre) {
    pre = pre || {};
    S.ed = { chiave: "nuova", r: null, fonte: pre.fonte || "vps", nome: pre.nome || "", gruppo: pre.gruppo || "", tipo: pre.tipo || "",
      piano: PIANO_NUOVO(), pianoIniziale: "", grezzo: "", grezzoIniziale: "", grezzoToccato: false, avanzato: false,
      regola: "", regolaIniziale: "", compito: "", compitoIniziale: "", descrizione: "", attivo: true,
      script: null, errore: null, esito: null, ant: null, occupato: false };
    disegna();
    anteprima();
    if (N.nuova) N.nuova.scrollIntoView({ block: "start" });
  }
  function chiudiEditor() { S.ed = null; disegna(); }
  function erroreEd(campo) {
    const e = S.ed && S.ed.errore;
    return e && e.campo === campo ? el("small", { class: "ro-errore-campo", role: "alert" }, e.testo) : null;
  }
  function campo(etichetta, input, aiuto, nomeCampo) {
    const errore = nomeCampo != null ? erroreEd(nomeCampo) : null;
    if (errore) input.setAttribute("aria-invalid", "true");
    return el("label", { class: "ro-campo" + (errore ? " ro-campo-ko" : "") }, el("span", { class: "ro-et" }, etichetta), input,
      aiuto ? el("small", { class: "ro-aiuto" }, aiuto) : null, errore);
  }
  function ridisegnaEditor() {
    const vecchio = document.querySelector(".ro-editor");
    if (!vecchio || !S.ed) { disegna(); return; }
    vecchio.replaceWith(editor());
  }

  // anteprima: il server converte (systemd-analyze per i timer) e dice le prossime 3 esecuzioni
  let attesaAnt = null;
  function anteprima(daGrezzo) {
    clearTimeout(attesaAnt);
    attesaAnt = setTimeout(async () => {
      const ed = S.ed;
      if (!ed) return;
      const corpo = { azione: "anteprima", fonte: ed.fonte };
      if (daGrezzo) corpo.grezzo = ed.grezzo; else if (ed.piano) corpo.piano = ed.piano; else if (ed.grezzo) corpo.grezzo = ed.grezzo; else return;
      if (ed.chiave !== "nuova") corpo.id = ed.chiave;      // per i timer a intervallo: prossime dall'ultimo giro vero
      if (!daGrezzo) { ed.grezzoToccato = false; ed.grezzoErrore = null; }   // i campi ora comandano il grezzo
      try {
        const x = await chiama("POST", "/api/routine", corpo);
        if (S.ed !== ed) return;
        if (x.stato === 200) {
          ed.ant = x.d;
          if (daGrezzo) ed.grezzoErrore = null;
          if (ed.errore && ["orario", "frequenza", "fasce", "giorni", "orari", "ogni", "data", "ora", "dal", "al", "avanzato"].includes(ed.errore.campo)) ed.errore = null;
          if (!daGrezzo) ed.grezzo = x.d.grezzo;
          else if (x.d.piano) { ed.piano = x.d.piano; ridisegnaEditor(); return; }
          else ed.piano = null;
        } else {
          ed.ant = { errore: x.d.errore || ("errore " + x.stato) };
          if (daGrezzo) { ed.grezzoErrore = ed.ant.errore; ed.errore = { campo: "avanzato", testo: ed.ant.errore }; ridisegnaEditor(); return; }
        }
      } catch (e) { ed.ant = { errore: "Rete assente: anteprima non calcolata." }; }
      aggiornaAnteprima();
    }, 350);
  }
  function aggiornaAnteprima() {
    const box = document.querySelector(".ro-editor .ro-anteprima");
    if (box) box.replaceWith(nodoAnteprima());
    const g = document.querySelector(".ro-editor textarea.ro-grezzo");
    if (g && document.activeElement !== g && S.ed) g.value = S.ed.grezzo;
  }
  function nodoAnteprima() {
    const a = S.ed && S.ed.ant;
    if (!a) return el("div", { class: "ro-anteprima ro-nota" }, "Anteprima…");
    if (a.errore) return el("div", { class: "ro-anteprima ro-ko", role: "alert" }, a.errore);
    return el("div", { class: "ro-anteprima", "aria-live": "polite" },
      el("b", {}, a.testo), a.prossime_testo && a.prossime_testo.length ? el("span", { class: "ro-prossime" }, " · prossime: " + a.prossime_testo.join(", ")) : null,
      ...(a.avvisi || []).map((t) => el("small", { class: "ro-aiuto ro-avviso" }, t)));
  }

  async function ricavaRegola() {
    const ed = S.ed;
    ed.ricavando = true; ridisegnaEditor();
    try {
      const x = await chiama("POST", "/api/routine", { azione: "descrivi", id: ed.chiave });
      if (S.ed !== ed) return;
      if (x.stato === 200) { if (!ed.regola) { ed.regola = x.d.regola; ed.regolaIniziale = x.d.regola; } }
      else ed.errore = { campo: "regola", testo: x.d.errore || ("errore " + x.stato) };
    } catch (e) { /* resta vuota */ }
    ed.ricavando = false; ridisegnaEditor();
  }
  async function scriviScript() {
    const ed = S.ed;
    ed.occupato = true; ed.errore = null; ed.script = null; ridisegnaEditor();
    const corpo = { azione: "scrivi-script", regola: ed.regola };
    if (ed.chiave === "nuova") Object.assign(corpo, { nuova: true, fonte: ed.fonte, nome: ed.nome.trim(), orario_testo: (ed.ant || {}).testo || "" });
    else corpo.id = ed.chiave;
    try {
      const x = await chiama("POST", "/api/routine", corpo);
      if (S.ed !== ed) return;
      if (x.stato === 200) ed.script = x.d; else ed.errore = { campo: campoDiErrore(x.d.errore || "") || "regola", testo: x.d.errore || ("errore " + x.stato) };
    } catch (e) { ed.errore = { campo: "regola", testo: "Rete assente: script non scritto." }; }
    ed.occupato = false; ridisegnaEditor();
  }
  async function salva() {
    const ed = S.ed;
    if (!ed || ed.occupato) return;
    const nuova = ed.chiave === "nuova";
    const corpo = { azione: "salva" };
    if (nuova) Object.assign(corpo, { nuova: true, fonte: ed.fonte, nome: ed.nome.trim(), gruppo: ed.gruppo, tipo: ed.tipo, attivo: ed.attivo });
    else corpo.id = ed.chiave;
    // 2026-10-05 (verificatore): mai applicare un valore diverso da quello che l'utente vede. Se ha scritto in «Avanzato»
    // si manda il grezzo (il server lo valida e lo rifiuta con «avanzato: …»); altrimenti il piano dei campi.
    if (ed.grezzoToccato) {
      if (ed.grezzoErrore) { ed.errore = { campo: "avanzato", testo: ed.grezzoErrore }; ed.avanzato = true; ridisegnaEditor(); return; }
      if (nuova || ed.grezzo.trim() !== ed.grezzoIniziale.trim()) corpo.grezzo = ed.grezzo;
    } else if (ed.piano && (nuova || JSON.stringify(ed.piano) !== ed.pianoIniziale)) corpo.piano = ed.piano;
    const regolaCambiata = ed.regola.trim() && ed.regola.trim() !== ed.regolaIniziale.trim();
    const compitoCambiato = ed.compito.trim() !== ed.compitoIniziale.trim();
    if (regolaCambiata && !compitoCambiato) {
      // lo script si vede PRIMA di applicare: se manca (o la regola è cambiata dopo), lo si scrive e ci si ferma qui
      if (!ed.script || ed.script.regola !== ed.regola.trim()) {
        await scriviScript();
        if (S.ed && S.ed.script) { S.ed.errore = { campo: "script", testo: "Controlla lo script qui sotto, poi premi di nuovo «Salva»." }; ridisegnaEditor(); }
        return;
      }
      if (!ed.script.ok) { ed.errore = { campo: "script", testo: (ed.script.avvisi || [])[0] || "script non valido" }; ridisegnaEditor(); return; }
      corpo.script = ed.script.script;
    } else if (compitoCambiato) corpo.compito = ed.compito;
    if (nuova ? ed.descrizione.trim() : ed.descrizione.trim() !== (ed.r.descrizione || "").trim()) corpo.descrizione = ed.descrizione;
    if (!nuova && ed.attivo !== !!ed.r.attivo) corpo.attivo = ed.attivo;
    ed.occupato = true; ed.errore = null; ed.esito = null; ridisegnaEditor();
    try {
      const x = await chiama("POST", "/api/routine", corpo);
      if (S.ed !== ed) return;
      if (x.stato === 200) {
        ed.esito = x.d;
        if (x.d.ok) {
          S.salvato = Object.assign({}, S.salvato || {}, { [x.d.id]: x.d });
          S.ed = null; ed.occupato = false; await aggiorna(true);
          const li = N.lista && N.lista.querySelector(`li[data-id="${CSS.escape(x.d.id)}"]`);
          if (li) li.scrollIntoView({ block: "nearest" });
          return;
        }
      } else ed.errore = { campo: campoDiErrore(x.d.errore || ""), testo: x.d.errore || ("errore " + x.stato) };
    } catch (e) { ed.errore = { campo: "", testo: "Rete assente: non so se è stato applicato. Rileggi l'elenco prima di riprovare." }; }
    ed.occupato = false; ridisegnaEditor();
  }
  async function pausa(r) {
    S.salvato = Object.assign({}, S.salvato || {}, { [r.id]: { ok: true, id: r.id, attesa: true, avvisi: [r.attivo ? "Metto in pausa e verifico…" : "Riattivo e verifico…"] } });
    disegna();
    try {
      const x = await chiama("POST", "/api/routine", { azione: "salva", id: r.id, attivo: !r.attivo });
      S.salvato[r.id] = x.stato === 200 ? x.d : { ok: false, id: r.id, errori: [x.d.errore || ("errore " + x.stato)] };
    } catch (e) { S.salvato[r.id] = { ok: false, id: r.id, errori: ["Rete assente"] }; }
    await aggiorna(true);
  }

  function nodoEsito(x) {
    if (!x) return null;
    const titolo = x.attesa ? (x.avvisi || [""])[0] : x.a_jarvis ? "📨 " + x.messaggio : x.ok ? `✅ Salvato e verificato: ${x.id}`
      : `❌ Non salvato: ${(x.errori || []).join("; ")}${x.ripristinato ? " · rimessa com'era" : ""}`;
    return el("div", { class: "ro-esito " + (x.attesa ? "ro-lavora" : x.ok ? "ro-ok" : "ro-ko"), role: "status" },
      el("h4", {}, titolo),
      x.prima || x.ora ? el("p", { class: "ro-nota" }, `Prima: ${x.prima || "—"} · Ora: ${x.ora || "—"}`) : null,
      ...(x.attesa ? [] : (x.avvisi || []).map((t) => el("p", { class: "ro-nota" }, t))),
      !x.ok && x.uscita ? el("details", {}, el("summary", {}, "Cosa ha fatto"), el("pre", { tabindex: "0" }, x.uscita)) : null);
  }
  function nodoScript() {
    const s = S.ed.script;
    if (!s) return null;
    const rosso = !s.ok || s.effetto !== "lettura";
    const eff = s.effetto === "lettura" ? ["solo lettura", "ro-eff-lettura"] : s.effetto === "invia" ? ["manda messaggi", "ro-eff-invia"] : ["scrive in produzione", "ro-eff-scrive"];
    return el("div", { class: "ro-script" + (rosso ? " ro-script-attento" : "") },
      el("h4", {}, `Script di Jarvis: routine/compiti/${s.file} `, el("span", { class: "ro-eff " + eff[1] }, eff[0])),
      rosso ? el("p", { class: "ro-ko" }, s.ok ? "Attenzione: questo script cambia qualcosa fuori (scrive o manda messaggi). Leggilo prima di salvare." : "Lo script non passa i controlli: non si può salvare.") : null,
      ...(s.avvisi || []).map((t) => el("p", { class: "ro-ko" }, t)),
      s.diff ? el("details", { open: "" }, el("summary", {}, "Differenze dallo script di prima"), el("pre", { tabindex: "0", class: "ro-diff" }, s.diff)) : null,
      el("details", { open: s.diff ? null : "" }, el("summary", {}, "Script intero"), el("pre", { tabindex: "0" }, s.script)));
  }

  function editor() {
    const ed = S.ed;
    const nuova = ed.chiave === "nuova";
    const m = nuova ? { orario: true, comando: true, descrizione: true, attivo: true } : (ed.r.modifica || {});
    const p = ed.piano;
    const figli = [];
    if (nuova) {
      const gruppi = Object.entries((S.dati && S.dati.nomi_gruppi) || {});
      for (const g of (S.dati && S.dati.gruppi) || []) if (!gruppi.some(([id]) => id === g.id)) gruppi.push([g.id, g.nome]);
      if (!ed.gruppo && gruppi.length) ed.gruppo = gruppi[0][0];
      const fonte = el("select", { onchange: (ev) => { ed.fonte = ev.target.value; anteprima(); ridisegnaEditor(); } },
        ...[["vps", "VPS · timer systemd (consigliato)"], ["cron", "VPS · riga di cron (UTC)"], ["mac", "Mac · launchd"]]
          .map(([v, t]) => el("option", { value: v, selected: ed.fonte === v ? "" : null }, t)));
      const nome = el("input", { type: "text", maxlength: "40", value: ed.nome, placeholder: "controllo-giro", autocapitalize: "off",
        oninput: (ev) => { ed.nome = ev.target.value; } });
      const gruppo = el("select", { onchange: (ev) => { ed.gruppo = ev.target.value; } },
        ...gruppi.map(([id, t]) => el("option", { value: id, selected: ed.gruppo === id ? "" : null }, t)));
      const tipo = el("select", { onchange: (ev) => { ed.tipo = ev.target.value; } },
        ...[["", "nessuno"], ["controllo", "controllo"], ["dati", "scarica dati"]].map(([v, t]) => el("option", { value: v, selected: ed.tipo === v ? "" : null }, t)));
      figli.push(el("h3", { class: "ro-titolo" }, "Nuova routine"),
        el("div", { class: "ro-riga2" }, campo("Dove", fonte, null, "dove"), campo("Nome", nome, "minuscole, cifre e trattini", "nome")),
        el("div", { class: "ro-riga2" }, campo("Gruppo", gruppo), campo("Tipo", tipo, "«controllo» va nei comandi rapidi solo se lo script è di sola lettura.", "tipo")));
    }
    if (m.descrizione) figli.push(campo("Descrizione", el("input", { type: "text", maxlength: "120", value: ed.descrizione, oninput: (ev) => { ed.descrizione = ev.target.value; } }), null, "descrizione"));

    // ---- quando
    if (m.orario) {
      if (p) {
        const radio = el("div", { class: "ro-freq", role: "radiogroup", "aria-label": "Frequenza" },
          ...FREQ.map(([v, t]) => {
            const r = el("input", { type: "radio", name: "ro-freq-" + ed.chiave, value: v });
            r.checked = p.frequenza === v;
            r.addEventListener("change", () => {
              const vecchi = p.orari && p.orari.length ? p.orari : ["07:00"];
              ed.piano = v === "minuti" ? { frequenza: v, ogni: p.ogni && p.ogni < 60 ? p.ogni : 30, fasce: p.fasce || [], giorni: p.giorni || [] }
                : v === "ora" ? { frequenza: v, ogni: 60, fasce: p.fasce || [], giorni: p.giorni || [] }
                  : v === "una_volta" ? { frequenza: v, data: new Date(Date.now() + 864e5).toISOString().slice(0, 10), ora: vecchi[0] }
                    : { frequenza: v, orari: vecchi, giorni: v === "settimana" && !(p.giorni || []).length ? ["lun"] : (p.giorni || []) };
              ridisegnaEditor(); anteprima();
            });
            return el("label", { class: "ro-radio" }, r, el("span", {}, t));
          }));
        const errOrario = ["orario", "frequenza", "fasce", "giorni", "orari", "ogni", "data", "ora", "dal", "al"].map(erroreEd).find(Boolean);
        figli.push(el("fieldset", { class: "ro-quando" }, el("legend", {}, "Quando"), radio, ...corpoFrequenza(p), errOrario || null));
      } else {
        figli.push(el("p", { class: "ro-avviso-ed" }, "Questo orario non si rappresenta con i campi: si modifica in «Avanzato»."),
          el("div", { class: "ro-azioni" }, el("button", { type: "button", class: "ro-btn", onclick: () => { ed.piano = PIANO_NUOVO(); ridisegnaEditor(); anteprima(); } }, "Rifallo con i campi")));
      }
      figli.push(nodoAnteprima());
    } else figli.push(el("p", { class: "ro-nota" }, "L'orario di questa routine non si cambia da qui (" + (ed.r && ed.r.orario) + ")."));

    // ---- cosa: la regola in italiano
    if (m.comando) {
      // 2026-10-05 (verificatore): il pulsante segue il campo mentre si scrive, non solo al disegno
      const bScrivi = el("button", { type: "button", class: "ro-btn ro-scrivi", disabled: ed.occupato || !ed.regola.trim() ? "" : null, onclick: scriviScript },
        ed.occupato && !ed.script ? "Jarvis scrive lo script…" : "✍ Scrivi lo script");
      const regola = el("textarea", { rows: "3", maxlength: "2000", placeholder: ed.ricavando ? "Jarvis sta ricavando la regola dal comando attuale…" : "Es.: ogni sera controlla che il giro Odoo sia verde e se no mandami un avviso nella chat Postino",
        oninput: (ev) => { ed.regola = ev.target.value; bScrivi.disabled = ed.occupato || !ed.regola.trim(); } });
      regola.value = ed.regola;
      // la regola di una routine esistente si ricava SOLO su richiesta (chiama Jarvis e salva <nome>.regola), mai all'apertura
      const bRicava = !nuova && !ed.regola.trim() && !(ed.r && ed.r.regola) ? el("button", { type: "button", class: "ro-btn ro-ricava",
        disabled: ed.ricavando ? "" : null, onclick: ricavaRegola }, ed.ricavando ? "Jarvis legge lo script…" : "🔎 Ricava la regola dallo script") : null;
      figli.push(campo("Regola: scrivi in italiano cosa deve fare, Jarvis la trasforma in script", regola,
        ed.ricavando ? "Jarvis sta leggendo il comando attuale per scriverla…" : ed.r && ed.r.regola_da_script ? "Lo script attuale viene da questa regola." : ed.r && ed.r.regola ? "Ricavata dal comando attuale: correggila e Jarvis riscrive lo script." : null, "regola"),
        el("div", { class: "ro-azioni" }, bScrivi, bRicava), erroreEd("script"), nodoScript());
    }
    // ---- avanzato
    const grezzo = el("textarea", { class: "ro-grezzo", rows: "3", spellcheck: "false", disabled: m.orario ? null : "",
      oninput: (ev) => { ed.grezzo = ev.target.value; ed.grezzoToccato = true; anteprima(true); } });
    grezzo.value = ed.grezzo;
    const compito = el("textarea", { class: "ro-compito", rows: "2", spellcheck: "false", disabled: m.comando ? null : "", oninput: (ev) => { ed.compito = ev.target.value; } });
    compito.value = ed.compito;
    const av = el("details", { class: "ro-avanzato" }, el("summary", {}, "Avanzato"),
      campo(ed.fonte === "vps" ? "OnCalendar (una riga per orario) o OnUnitActiveSec=…" : ed.fonte === "cron" ? "Cron: 5 campi in UTC" : "StartCalendarInterval (JSON) o «ogni N min»", grezzo,
        "Segue i campi; se lo cambi qui, i campi seguono lui.", "avanzato"),
      campo("Comando (il compito vero: con una regola nuova lo sostituisce lo script)", compito, null, "compito"));
    if (ed.avanzato) av.open = true;
    av.addEventListener("toggle", () => { ed.avanzato = av.open; });
    figli.push(av);
    if (m.attivo) {
      const attivo = el("input", { type: "checkbox", onchange: (ev) => { ed.attivo = ev.target.checked; } });
      attivo.checked = ed.attivo;
      figli.push(el("label", { class: "ro-spunta" }, attivo, el("span", {}, nuova ? "Attiva subito" : "Attiva (togli la spunta per metterla in pausa)")));
    }
    figli.push(erroreEd("") || erroreEd("attivo") || erroreEd("compito") || erroreEd("descrizione") || null,
      el("div", { class: "ro-azioni" },
        el("button", { type: "submit", class: "ro-btn ro-si", disabled: ed.occupato ? "" : null }, ed.occupato ? "Un attimo…" : "Salva"),
        el("button", { type: "button", class: "ro-btn", onclick: chiudiEditor }, "Annulla")),
      el("p", { class: "ro-nota" }, "«Salva» applica subito, controlla che il valore nuovo sia attivo e, se non lo è, rimette com'era. Jarvis riceve l'avviso nel filo Notifiche."),
      nodoEsito(ed.esito));
    return el("form", { class: "ro-form ro-editor" + (nuova ? " ro-nuova" : ""), onsubmit: (ev) => { ev.preventDefault(); salva(); } }, ...figli.filter(Boolean));
  }

  const oraInput = (v, onv) => el("input", { type: "time", value: v, step: "60", onchange: (ev) => onv(ev.target.value) });
  function corpoFrequenza(p) {
    const out = [];
    if (p.frequenza === "minuti") {
      out.push(el("label", { class: "ro-inline" }, el("span", {}, "Ogni"),
        el("select", { onchange: (ev) => { p.ogni = +ev.target.value; anteprima(); } }, ...OGNI.map((n) => el("option", { value: n, selected: p.ogni === n ? "" : null }, n))),
        el("span", {}, "minuti")));
    }
    if (p.frequenza === "minuti" || p.frequenza === "ora") {
      if (p.monotono) out.push(el("small", { class: "ro-aiuto" }, "Conta dalla fine del giro prima. Con fasce o giorni diventa a orari fissi."));
      const fasce = p.fasce || (p.fasce = []);
      out.push(el("div", { class: "ro-fasce" }, el("span", { class: "ro-et" }, "Fasce orarie"),
        ...fasce.map((f, i) => el("span", { class: "ro-fascia" },
          oraInput(f[0], (v) => { f[0] = v; delete p.monotono; anteprima(); }), el("span", {}, "–"), oraInput(f[1], (v) => { f[1] = v; delete p.monotono; anteprima(); }),
          el("button", { type: "button", class: "ro-x", "aria-label": "Togli la fascia", onclick: () => { fasce.splice(i, 1); ridisegnaEditor(); anteprima(); } }, "×"))),
        fasce.length < 6 ? el("button", { type: "button", class: "ro-btn ro-piccolo", onclick: () => { fasce.push(["09:00", "18:00"]); delete p.monotono; ridisegnaEditor(); anteprima(); } }, "+ fascia") : null,
        !fasce.length ? el("small", { class: "ro-aiuto" }, "Nessuna fascia: tutto il giorno.") : null));
    }
    if (p.frequenza === "giorno" || p.frequenza === "settimana") {
      const orari = p.orari || (p.orari = ["07:00"]);
      out.push(el("div", { class: "ro-fasce" }, el("span", { class: "ro-et" }, "Alle"),
        ...orari.map((o, i) => el("span", { class: "ro-fascia" }, oraInput(o, (v) => { orari[i] = v; anteprima(); }),
          orari.length > 1 ? el("button", { type: "button", class: "ro-x", "aria-label": "Togli l'orario", onclick: () => { orari.splice(i, 1); ridisegnaEditor(); anteprima(); } }, "×") : null)),
        orari.length < 24 ? el("button", { type: "button", class: "ro-btn ro-piccolo", onclick: () => { orari.push("19:00"); ridisegnaEditor(); anteprima(); } }, "+ orario") : null));
    }
    if (p.frequenza === "una_volta") {
      out.push(el("div", { class: "ro-fasce" }, el("span", { class: "ro-et" }, "Il"),
        el("input", { type: "date", value: p.data, onchange: (ev) => { p.data = ev.target.value; anteprima(); } }),
        el("span", {}, "alle"), oraInput(p.ora, (v) => { p.ora = v; anteprima(); })));
      return out;
    }
    const giorni = p.giorni || (p.giorni = []);
    const tutti = !giorni.length && p.frequenza !== "settimana";
    const feriali = giorni.join() === "lun,mar,mer,gio,ven", weekend = giorni.join() === "sab,dom";
    const sel = el("select", { "aria-label": "Giorni", onchange: (ev) => {
      const v = ev.target.value;
      p.giorni = v === "tutti" ? [] : v === "feriali" ? GG.slice(0, 5) : v === "weekend" ? ["sab", "dom"] : (giorni.length ? giorni.slice() : ["lun"]);
      delete p.monotono; ridisegnaEditor(); anteprima();
    } }, ...(p.frequenza === "settimana" ? [] : [["tutti", "Tutti i giorni"]]).concat([["feriali", "Lun–ven"], ["weekend", "Sab e dom"], ["scegli", "Scegli i giorni"]])
      .map(([v, t]) => el("option", { value: v, selected: (v === "tutti" && tutti) || (v === "feriali" && feriali) || (v === "weekend" && weekend) || (v === "scegli" && !tutti && !feriali && !weekend) ? "" : null }, t)));
    const spunte = el("div", { class: "ro-giorni" }, ...GG.map((g) => {
      const c = el("input", { type: "checkbox", "aria-label": g });
      c.checked = giorni.includes(g);
      c.addEventListener("change", () => {
        p.giorni = GG.filter((x) => (x === g ? c.checked : p.giorni.includes(x)));
        if (p.giorni.length === 7) p.giorni = [];
        delete p.monotono; anteprima();
      });
      return el("label", { class: "ro-giorno" }, c, el("span", {}, g[0].toUpperCase() + g.slice(1)));
    }));
    out.push(el("div", { class: "ro-fasce" }, el("span", { class: "ro-et" }, "Giorni"), sel), tutti ? null : spunte);
    out.push(el("div", { class: "ro-fasce" }, el("span", { class: "ro-et" }, "Dal"),
      el("input", { type: "date", value: p.dal || "", onchange: (ev) => { if (ev.target.value) p.dal = ev.target.value; else delete p.dal; anteprima(); } }),
      el("span", {}, "al"), el("input", { type: "date", value: p.al || "", onchange: (ev) => { if (ev.target.value) p.al = ev.target.value; else delete p.al; anteprima(); } }),
      el("small", { class: "ro-aiuto" }, "facoltativo")));
    return out.filter(Boolean);
  }

  function scheda(r) {
    const e = ultimaEsec(r.id);
    const inCorso = e && (e.stato === "partenza" || e.stato === "in_corso");
    const testa = el("div", { class: "ro-testa" },
      el("i", { class: "spia " + (inCorso ? "lavora" : spia(r)), "aria-hidden": "true" }),
      el("h3", { class: "ro-titolo", title: r.nome }, r.descrizione || r.nome),
      el("span", { class: "ro-dove", title: r.orario_grezzo ? `${r.orario}\n${r.orario_grezzo}` : r.orario }, orarioBreve(r)));
    const ultimo = r.ultimo_testo ? `ultimo ${r.ultimo_testo} ${SEGNO[r.esito] || (r.fonte === "cron" ? "" : "")}`.trim() : (r.fonte === "cron" ? "" : "mai partita");
    const sotto = el("p", { class: "ro-sotto" },
      el("span", { class: "ro-nome" }, `${r.nome} · ${nomeGruppo(r.gruppo)}${r.tipo ? " · " + (r.tipo === "dati" ? "scarica dati" : "controllo") : ""}`),
      etichettaEffetto(r),
      !r.attivo ? el("span", { class: "ro-fermo" }, r.fonte === "mac" && !r.caricato ? "(fermo: non caricato)" : "(in pausa)") : null,
      ultimo ? el("span", {}, ultimo + (r.fonte === "cron" ? " (da orario)" : "")) : null,
      r.fonte === "cron" && r.log_aggiornato ? el("span", {}, `log scritto ${ora(r.log_aggiornato)}`) : null,
      r.esito === "errore" && r.codice != null ? el("span", { class: "ro-ko" }, `codice ${r.codice}${r.risultato && r.risultato !== "success" ? " · " + r.risultato : ""}`) : null,
      r.prossimo_testo ? el("span", {}, `prossimo ${r.prossimo_testo}`) : null);
    const azioni = el("div", { class: "ro-azioni" },
      el("button", { type: "button", class: "ro-btn ro-avvia", disabled: !r.avviabile || inCorso ? "" : null,
        title: r.avviabile ? "Parte subito, senza conferma" : r.perche_no, onclick: (ev) => avvia(r, ev.currentTarget) }, inCorso ? "⏳ In corso" : "▶ Avvia ora"),
      el("button", { type: "button", class: "ro-btn", "aria-expanded": S.ed && S.ed.chiave === r.id ? "true" : "false",
        onclick: () => { if (S.ed && S.ed.chiave === r.id) chiudiEditor(); else apriEditor(r); } }, "✎ Modifica"),
      (r.modifica || {}).attivo ? el("button", { type: "button", class: "ro-btn",
        title: r.attivo ? "Mette in pausa subito (e lo verifica)" : "Riattiva subito (e lo verifica)",
        onclick: () => pausa(r) }, r.attivo ? "⏸ Pausa" : "▶ Riattiva") : null,
      el("button", { type: "button", class: "ro-btn", "aria-expanded": S.log[r.id] !== undefined ? "true" : "false", onclick: () => apriLog(r) }, "Log"));
    const li = el("li", { class: "ro-scheda" + (r.attivo ? "" : " ro-spenta"), "data-id": r.id }, testa, sotto,
      el("div", { class: "ro-vivo", "data-esec": r.id }, testoEsec(e)), azioni);
    if (S.log[r.id] !== undefined) li.append(el("pre", { class: "ro-log", tabindex: "0" }, S.log[r.id]));
    if (S.salvato && S.salvato[r.id] && !(S.ed && S.ed.chiave === r.id)) li.append(nodoEsito(S.salvato[r.id]));
    if (S.ed && S.ed.chiave === r.id) li.append(editor());
    return li;
  }
  function filtrate() {
    const rr = (S.dati && S.dati.routine) || [];
    return rr.filter((r) => (S.filtro === "tutte" || (S.filtro === "vps" && r.dove === "VPS") || (S.filtro === "mac" && r.dove === "Mac") ||
      (S.filtro === "errori" && r.esito === "errore")) && (!S.gruppo || r.gruppo === S.gruppo));
  }
  function disegnaFiltri() {
    const rr = (S.dati && S.dati.routine) || [];
    const n = { tutte: rr.length, vps: rr.filter((r) => r.dove === "VPS").length, mac: rr.filter((r) => r.dove === "Mac").length,
      errori: rr.filter((r) => r.esito === "errore").length };
    const etich = { tutte: "Tutte", vps: "VPS", mac: "Mac", errori: "⚠ errori" };
    N.filtri.textContent = "";
    for (const k of Object.keys(etich)) N.filtri.append(el("button", { type: "button", class: "ro-filtro", "aria-pressed": S.filtro === k ? "true" : "false",
      onclick: () => { S.filtro = k; disegna(); } }, `${etich[k]} (${n[k]})`));
    const gruppi = [...new Set(rr.map((r) => r.gruppo))].sort((a, b) => nomeGruppo(a).localeCompare(nomeGruppo(b)));
    const sel = el("select", { class: "ro-sel-gruppo", "aria-label": "Gruppo", onchange: (ev) => { S.gruppo = ev.target.value; disegna(); } },
      el("option", { value: "" }, "tutti i gruppi"), ...gruppi.map((g) => el("option", { value: g, selected: S.gruppo === g ? "" : null }, nomeGruppo(g))));
    N.filtri.append(sel);
  }
  function disegna() {
    if (!N.lista) return;
    N.errore.textContent = S.errore; N.errore.hidden = !S.errore;
    const d = S.dati;
    N.stato.textContent = d ? `lette alle ${ora(d.letto)} · ${Object.entries(d.conta || {}).map(([k, v]) => `${v} ${k === "vps" ? "timer VPS" : k === "cron" ? "cron VPS" : "Mac"}`).join(", ")}` : "carico…";
    N.avvisi.textContent = "";
    for (const a of (d && d.avvisi) || []) N.avvisi.append(el("p", { class: "ro-errore" }, a));
    N.nuova.textContent = "";
    if (S.ed && S.ed.chiave === "nuova") N.nuova.append(editor());
    if (!d) { N.lista.textContent = ""; N.lista.append(el("li", { class: "ro-nota" }, "Carico le routine di VPS e Mac…")); return; }
    disegnaFiltri();
    N.lista.textContent = "";
    const voci = filtrate();
    if (!voci.length) N.lista.append(el("li", { class: "ro-nota" }, "Nessuna routine con questo filtro."));
    for (const r of voci) N.lista.append(scheda(r));
    N.registro.textContent = "";
    for (const x of (d.registro || []).slice(0, 20)) N.registro.append(el("li", {},
      el("span", { class: "ro-et" }, new Date(x.ts * 1000).toLocaleString("it-IT", { timeZone: "Europe/Rome", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })),
      el("span", {}, `${x.azione} · ${x.id} · ${x.esito}${x.chi ? " · " + x.chi : ""}${x.riepilogo ? " · " + x.riepilogo : ""}${x.motivo ? " · " + x.motivo : ""}`)));
  }
  function aggiornaVivi() {        // solo le righe «in corso», senza ridisegnare i moduli aperti
    for (const box of document.querySelectorAll(".ro-vivo[data-esec]")) {
      box.textContent = "";
      const t = testoEsec(ultimaEsec(box.dataset.esec));
      if (t) box.append(t);
    }
  }
  function creaVista() {
    const main = document.querySelector("main");
    if (!main || document.querySelector('section[data-vista="routine"]')) return false;
    N.lista = el("ul", { class: "ro-lista" });
    N.errore = el("p", { class: "ro-errore", role: "alert", hidden: "" });
    N.avvisi = el("div", {});
    N.filtri = el("div", { class: "ro-filtri", role: "group", "aria-label": "Filtro" });
    N.stato = el("small", { class: "ro-stato", "aria-live": "polite" }, "carico…");
    N.nuova = el("div", { class: "ro-nuova-box" });
    N.registro = el("ol", { class: "ro-registro" });
    N.vista = el("section", { class: "vista vista-routine", "data-vista": "routine", "aria-labelledby": "ro-titolo-pagina" },
      el("div", { class: "ro-intro" },
        el("div", { class: "ro-intro-testa" }, el("h2", { id: "ro-titolo-pagina", class: "ro-pagina" }, "Routine"),
          el("button", { type: "button", class: "ro-btn", onclick: () => aggiorna(true), title: "Rilegge VPS e Mac adesso" }, "⟳ Rileggi"),
          el("button", { type: "button", class: "ro-btn ro-si", onclick: () => { apriNuova({}); } }, "+ Nuova")),
        el("p", { class: "ro-sotto-titolo" }, "I lavori automatici di VPS (timer e cron) e Mac. «Avvia ora» parte subito; «Salva» applica subito, verifica e avvisa Jarvis. Ore di Roma."),
        N.stato),
      N.filtri, N.errore, N.avvisi, N.nuova, N.lista,
      el("details", { class: "ro-reg" }, el("summary", {}, "Registro delle routine (ultime 20)"), N.registro));
    main.append(N.vista);
    disegna();
    return true;
  }

  // ---------------------------------------------------------------- dati e tempi
  async function aggiorna(forza) {
    try {
      const x = await chiama("GET", "/api/routine" + (forza ? "?forza=1" : ""));
      if (x.stato === 200) { S.dati = x.d; if (S.errore.startsWith("Rete")) S.errore = ""; } else S.errore = x.d.errore || ("errore " + x.stato);
    } catch (e) { S.errore = "Rete assente."; }
    // con un modulo aperto si aggiornano solo gli stati vivi: non si perde quello che l'utente sta scrivendo
    if (S.ed) { aggiornaVivi(); if (!N.lista.childElementCount) disegna(); } else disegna();
    segnaSpia(); disegnaRapidi(); pianifica();
  }
  const attiva = () => location.hash.startsWith("#routine") && !document.hidden;
  const inCorso = () => ((S.dati && S.dati.esecuzioni) || []).some((e) => e.stato === "partenza" || e.stato === "in_corso");
  function pianifica() {
    clearTimeout(S.timer);
    const ms = inCorso() ? 2000 : attiva() ? 30000 : 120000;
    S.timer = setTimeout(() => aggiorna(false), ms);
  }
  function cambio() {
    if (location.hash.startsWith("#routine/nuova")) {
      const pre = window.ccRoutineNuova || {};
      window.ccRoutineNuova = null;
      history.replaceState(null, "", "#routine");
      apriNuova(pre);
    }
    if (attiva() && !S.attivo) { S.attivo = true; aggiorna(false); }
    else if (!attiva() && S.attivo) { S.attivo = false; }
  }

  // ---------------------------------------------------------------- comandi rapidi sulla lavagna
  function menuRapido(tipo, etichetta) {
    const lista = el("div", { class: "ro-menu-lista", role: "menu" });
    const d = el("details", { class: "ro-menu" }, el("summary", { class: "piccolo", title: etichetta + " per gruppo" }, etichetta + " ▾"), lista);
    d.addEventListener("toggle", () => { if (d.open) riempi(); });
    function riempi() {
      lista.textContent = "";
      const gruppi = (S.dati && S.dati.gruppi) || [];
      const tutti = gruppi.flatMap((g) => g[tipo] || []);
      for (const g of gruppi) {
        const ids = g[tipo] || [];
        if (ids.length) {
          lista.append(el("button", { type: "button", role: "menuitem", class: "ro-voce", title: ids.join(", "),
            onclick: () => { d.open = false; lanciaRapido(ids, `${etichetta} · ${g.nome}`); } }, `${g.nome} (${ids.length})`,
          tipo === "dati" ? el("span", { class: "ro-eff ro-eff-scrive" }, "scrive in produzione") : null));
        } else {
          lista.append(el("a", { href: "#routine/nuova", role: "menuitem", class: "ro-voce ro-voce-vuota", title: "Nessuna routine di questo tipo: apre «Nuova» già compilata",
            onclick: () => { d.open = false; window.ccRoutineNuova = { gruppo: g.id, tipo, fonte: "vps", nome: `${g.id}-${tipo === "dati" ? "dati" : "controllo"}`.slice(0, 40) }; } },
          el("span", {}, g.nome), el("small", {}, " nessuna routine: creala")));
        }
      }
      lista.append(el("button", { type: "button", role: "menuitem", class: "ro-voce ro-voce-tutti", disabled: tutti.length ? null : "",
        onclick: () => { d.open = false; lanciaRapido(tutti, `${etichetta} · tutti`); } }, `Tutti, in sequenza (${tutti.length})`,
        tipo === "dati" ? el("span", { class: "ro-eff ro-eff-scrive" }, "scrive in produzione") : el("span", { class: "ro-eff ro-eff-lettura" }, "solo lettura")));
      if (!S.dati) lista.append(el("p", { class: "ro-nota" }, "Carico le routine…"));
    }
    return d;
  }
  async function lanciaRapido(ids, titolo) {
    S.rapidi = { ids, titolo, da: Date.now() / 1000 - 2, errore: "" };
    disegnaRapidi();
    try {
      const x = await chiama("POST", "/api/routine", { azione: "avvia-molte", ids });
      if (x.stato !== 200) S.rapidi.errore = x.d.errore || ("errore " + x.stato);
    } catch (e) { S.rapidi.errore = "Rete assente: non partito."; }
    setTimeout(() => aggiorna(false), 800);
  }
  function disegnaRapidi() {
    const box = document.getElementById("ro-rapidi-stato");
    if (!box || !S.rapidi) return;
    const r = S.rapidi;
    if (r.errore) { box.textContent = `${r.titolo}: ${r.errore}`; box.className = "lav-stato ro-ko"; return; }
    const es = ((S.dati && S.dati.esecuzioni) || []).filter((e) => r.ids.includes(e.id) && e.partito >= r.da);
    const ok = es.filter((e) => e.stato === "ok").length, ko = es.filter((e) => e.stato === "errore").length;
    const vive = es.filter((e) => e.stato === "in_corso" || e.stato === "partenza");
    const finito = ok + ko === r.ids.length;
    box.className = "lav-stato " + (finito ? (ko ? "ro-ko" : "ro-ok") : "");
    box.textContent = `${r.titolo}: ${ok + ko}/${r.ids.length} finite` + (ko ? `, ${ko} con errore` : "") +
      (vive.length ? ` · in corso: ${vive.map((e) => e.nome).join(", ")}` : finito ? (ko ? " ❌" : " ✅") : " · in coda");
    box.title = es.map((e) => `${e.nome}: ${e.esito}`).join("\n");
  }
  function creaRapidi() {
    const barra = document.querySelector(".lavagna-barra");
    if (!barra || document.getElementById("ro-rapidi")) return;
    const box = el("span", { class: "ro-rapidi", id: "ro-rapidi", role: "group", "aria-label": "Comandi rapidi per gruppo" },
      menuRapido("controllo", "✔ Controlli"), menuRapido("dati", "⬇ Scarica dati"),
      el("small", { id: "ro-rapidi-stato", class: "lav-stato", "aria-live": "polite" }));
    const accanto = document.getElementById("lav-aggiorna-ultime") || document.getElementById("lav-aggiorna-agenti");
    if (accanto && accanto.parentNode === barra) barra.insertBefore(box, accanto.nextSibling); else barra.append(box);
    document.addEventListener("click", (ev) => {
      for (const d of box.querySelectorAll("details[open]")) if (!d.contains(ev.target)) d.open = false;
    });
  }

  (async function avvio() {
    if (document.readyState === "loading") await new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true }));
    let r;
    try { r = await chiama("GET", "/api/routine"); } catch (e) { return; }
    if (r.stato !== 200) return;                    // dal sito senza la rotta o con un server vecchio: niente voce
    S.dati = r.d;
    creaVoceMenu();
    if (!creaVista()) return;
    creaRapidi();
    segnaSpia();
    window.addEventListener("hashchange", cambio);
    document.addEventListener("visibilitychange", cambio);
    if (location.hash.startsWith("#routine") && typeof mostraVista === "function") { try { mostraVista(); } catch (e) { /* niente */ } } // eslint-disable-line no-undef
    cambio();
    pianifica();
  })();
})();
