// fili.js · la stessa conversazione su Mac e telefono (2026-10-03, cc-fili-opus)
//
// l'utente: «la lavagna non fa aggiornare la chat». Le chat stavano solo nel localStorage di ogni browser
// (THREADS in app.js). Il server ora tiene l'archivio dei fili (fili.py: GET /api/fili, GET /api/fili/<sessione>,
// evento «fili» sul flusso) e qui lo si unisce a THREADS. Il server è la fonte: ogni messaggio suo ha un id
// stabile (q-<lavoro> la domanda, a-<lavoro> la risposta, r-… il reset). Nessuna scrittura verso il server.
//
// Ganci con app.js, senza modificarlo (le globali si leggono per nome, come approvazioni.js):
//  - THREADS, chatCon, AGENTI, FLUSSO, seguiInCorso: lette;
//  - salvaFili: avvolta (window.salvaFili). Prima di salvare dà l'id del server ai messaggi appena nati su
//    questo dispositivo (la domanda ha l'id del lavoro in t.attesa.id), dopo il salvataggio si accorge dei
//    messaggi tolti a mano (✕: non tornano dal server) e delle conversazioni lasciate (svuota, reset);
//  - disegnaMessaggi, aggiornaInvia, segnaAttivi: chiamate per ridisegnare la chat aperta.
// Regole dell'unione:
//  - per ogni interlocutore vale il filo del server aggiornato più di recente (escluse le sessioni che questo
//    dispositivo ha lasciato): se è lo stesso della pagina si uniscono i messaggi, se è un altro la pagina ci passa;
//  - i messaggi locali che il server non ha (domanda non partita, errori di rete, comandi /) restano, nella loro
//    posizione; nessun doppione (stesso id, o stesso testo per i messaggi locali senza id);
//  - una conversazione locale con messaggi solo suoi che viene sostituita si mette da parte in
//    localStorage «cc.fili-da-parte» (le ultime 5), non si perde;
//  - una chat che aspetta una risposta non si tocca finché seguiRisposte() di app.js sta leggendo.
// Ritmo: subito, a ogni evento «fili» del flusso, ogni 10 s senza flusso (60 s col flusso vivo), al ritorno
// sulla scheda. Backend vecchio (404 su /api/fili): si spegne e la pagina resta come prima.
(function () {
  "use strict";
  if (typeof THREADS !== "object" || !THREADS || typeof window.salvaFili !== "function") return;

  const MAX_LOCALI = 120;            // come salvaFili: oltre, i più vecchi escono comunque
  const PREFISSO_LAVAGNA = " (Sulla lavagna dell'utente dipendi da:";
  const S = { attivo: null, versioni: new Map(), inCorso: false, ancora: false, timer: null, giro: null,
    ultimo: 0, letture: 0, unioni: 0, errori: 0 };

  const leggiMem = (k, d) => { try { const v = localStorage.getItem("cc." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  // window.__ccSessioneFinita (ponte.js, sessione scaduta o uscita): le conversazioni appena cancellate non si riscrivono
  const scriviMem = (k, v) => { if (window.__ccSessioneFinita) return true; try { localStorage.setItem("cc." + k, JSON.stringify(v)); return true; } catch (e) { return false; } };
  const LASCIATI = new Set(leggiMem("fili-lasciati", []));     // sessioni lasciate qui: non si riprendono
  const TOLTI = leggiMem("fili-tolti", {});                     // sessione -> [id] tolti a mano
  const VISTO = leggiMem("fili-visto", {});                     // sessione -> ms della prima volta vista qui
  const RIPARTITI = leggiMem("fili-ripartiti", {});             // sessione nata da «svuota» qui -> ms
  const FOTO = {};                                              // k -> {sessione, ids} all'ultimo salvataggio
  const ATTESE = {};                                            // k -> {id, sessione} dell'ultima attesa vista

  const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const chiaveOk = (k) => k === "jarvis" || Object.prototype.hasOwnProperty.call(THREADS, k) ||
    (typeof AGENTI !== "undefined" && AGENTI && typeof AGENTI.has === "function" && AGENTI.has(k));
  const seguendo = () => { try { return typeof seguiInCorso !== "undefined" && !!seguiInCorso; } catch (e) { return false; } };

  function salvaLati() {
    scriviMem("fili-lasciati", [...LASCIATI].slice(-200));
    const sess = Object.keys(TOLTI);
    for (const s of sess.slice(0, Math.max(0, sess.length - 50))) delete TOLTI[s];
    scriviMem("fili-tolti", TOLTI);
    const vis = Object.keys(VISTO);
    for (const s of vis.slice(0, Math.max(0, vis.length - 300))) delete VISTO[s];
    scriviMem("fili-visto", VISTO);
    const rip = Object.keys(RIPARTITI);
    for (const s of rip.slice(0, Math.max(0, rip.length - 100))) delete RIPARTITI[s];
    scriviMem("fili-ripartiti", RIPARTITI);
  }

  // ---------------------------------------------------------------- id ai messaggi nati qui
  function ultimoSenzaId(msgs, chi) {
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m && m.chi === chi && !m.fid && m.tipo !== "comando") return m;
    }
    return null;
  }
  function etichetta() {
    for (const [k, t] of Object.entries(THREADS)) {
      if (!t || !Array.isArray(t.messaggi)) continue;
      if (t.attesa && t.attesa.id && !t.attesa.comando) {
        const id = String(t.attesa.id);
        if (!t.messaggi.some((m) => m && m.fid === "q-" + id)) {
          const q = ultimoSenzaId(t.messaggi, "io");
          if (q) q.fid = "q-" + id;
        }
        ATTESE[k] = { id, sessione: t.sessione };
      } else if (ATTESE[k] && !t.attesa) {
        const a = ATTESE[k];
        delete ATTESE[k];
        if (a.sessione === t.sessione && !t.messaggi.some((m) => m && m.fid === "a-" + a.id)) {
          const r = ultimoSenzaId(t.messaggi, "lui");
          if (r) r.fid = "a-" + a.id;
        }
      }
    }
  }
  function foto(k, t) { FOTO[k] = { sessione: t.sessione, ids: t.messaggi.map((m) => m && m.fid).filter(Boolean) }; }
  function dopoSalva() {
    let cambiato = false;
    for (const [k, t] of Object.entries(THREADS)) {
      if (!t || !Array.isArray(t.messaggi)) continue;
      if (!VISTO[t.sessione]) { VISTO[t.sessione] = Date.now(); cambiato = true; }
      const f = FOTO[k];
      if (f && f.sessione !== t.sessione) {
        LASCIATI.add(f.sessione);              // svuota, reset, sessione mai nata: qui quella non torna
        RIPARTITI[t.sessione] = Date.now();    // e la chat nuova vuota non riprende fili più vecchi di lei
        cambiato = true;
      } else if (f && f.ids.length) {
        const ora = new Set(t.messaggi.map((m) => m && m.fid).filter(Boolean));
        const primo = f.ids.findIndex((id) => ora.has(id));
        // tolti in testa = il taglio di salvaFili (i più vecchi escono); tolti altrove = ✕ dell'utente
        const tolti = f.ids.filter((id, i) => !ora.has(id) && primo >= 0 && i > primo);
        if (primo < 0 && !t.messaggi.length) tolti.push(...f.ids);
        if (tolti.length) {
          TOLTI[t.sessione] = [...new Set([...(TOLTI[t.sessione] || []), ...tolti])].slice(-300);
          cambiato = true;
        }
      }
      foto(k, t);
    }
    if (cambiato) salvaLati();
  }
  const salvaOriginale = window.salvaFili;
  window.salvaFili = function () {
    try { etichetta(); } catch (e) { /* mai fermare il salvataggio */ }
    const r = salvaOriginale.apply(this, arguments);
    try { dopoSalva(); } catch (e) { /* idem */ }
    return r;
  };
  for (const [k, t] of Object.entries(THREADS)) {
    if (!t || !Array.isArray(t.messaggi)) continue;
    if (!VISTO[t.sessione]) VISTO[t.sessione] = Date.now();
    if (t.attesa && t.attesa.id && !t.attesa.comando) ATTESE[k] = { id: String(t.attesa.id), sessione: t.sessione };
    foto(k, t);
  }
  salvaLati();

  // ---------------------------------------------------------------- unione
  function daServer(m) {
    const x = { fid: String(m.id), chi: m.chi === "io" ? "io" : "lui", testo: String(m.testo == null ? "" : m.testo), ora: String(m.ora || "") };
    x.errore = !!m.errore;
    if (m.motore) x.motore = String(m.motore);
    if (m.box) x.box = String(m.box);
    return x;
  }
  function stessoTesto(l, s) {
    if (!l || l.chi !== s.chi) return false;
    const a = norm(l.testo), b = norm(s.testo);
    if (!a) return false;
    if (a === b) return true;
    if (s.chi === "io") return b.startsWith(a + norm(PREFISSO_LAVAGNA));
    return false;
  }
  // Unisce i messaggi del server (in ordine) con quelli locali: torna la lista nuova.
  function unisciMessaggi(locali, filo) {
    const tolti = new Set(TOLTI[filo.sessione] || []);
    const srv = (filo.messaggi || []).filter((m) => m && m.id && !tolti.has(String(m.id))).slice(-MAX_LOCALI).map(daServer);
    const pos = new Map(srv.map((m, j) => [m.fid, j]));
    const abb = locali.map(() => -1);
    const preso = new Set();
    locali.forEach((m, i) => {
      if (m && m.fid && pos.has(m.fid) && !preso.has(m.fid)) { abb[i] = pos.get(m.fid); preso.add(m.fid); }
    });
    // messaggi locali senza id (nati prima di fili.js, o in una corsa): stesso testo = stesso messaggio, dal fondo
    for (let j = srv.length - 1; j >= 0; j--) {
      if (preso.has(srv[j].fid)) continue;
      for (let i = locali.length - 1; i >= 0; i--) {
        if (abb[i] >= 0 || !locali[i] || locali[i].fid) continue;
        if (stessoTesto(locali[i], srv[j])) { abb[i] = j; preso.add(srv[j].fid); break; }
      }
    }
    // Si segue l'ordine locale; un messaggio solo del server entra subito prima del primo messaggio
    // abbinato che lo segue sul server, oppure in fondo. Così i messaggi locali di prima restano prima.
    const abbinati = new Set(abb.filter((j) => j >= 0));
    const emessi = new Set();
    const out = [];
    const fino = (j) => { for (let x = 0; x < j; x++) if (!emessi.has(x) && !abbinati.has(x)) { out.push(srv[x]); emessi.add(x); } };
    locali.forEach((m, i) => {
      if (!m) return;
      if (abb[i] >= 0) { fino(abb[i]); out.push(Object.assign(m, srv[abb[i]])); emessi.add(abb[i]); }
      else out.push(m);
    });
    for (let x = 0; x < srv.length; x++) if (!emessi.has(x)) out.push(srv[x]);
    return out;
  }
  function daParte(k, t) {
    if (!t || !Array.isArray(t.messaggi) || !t.messaggi.some((m) => m && !m.fid)) return;
    const lista = leggiMem("fili-da-parte", []);
    lista.push({ k, sessione: t.sessione, quando: new Date().toISOString(), messaggi: t.messaggi.slice(-MAX_LOCALI) });
    while (lista.length > 5 || (lista.length > 1 && JSON.stringify(lista).length > 400000)) lista.shift();
    scriviMem("fili-da-parte", lista);
  }
  // Applica il filo del server alla chat k: true se qualcosa è cambiato.
  function applica(k, filo) {
    let t = THREADS[k];
    const prima = t ? JSON.stringify([t.sessione, t.messaggi, t.attesa || null]) : "";
    if (!t || t.sessione !== filo.sessione) {
      if (t) daParte(k, t);
      t = { sessione: filo.sessione, avviata: false, messaggi: [] };
      THREADS[k] = t;
      FOTO[k] = { sessione: t.sessione, ids: [] };      // passaggio voluto: la sessione di prima non è «lasciata»
      delete ATTESE[k];
      if (!VISTO[t.sessione]) VISTO[t.sessione] = Date.now();
    }
    t.messaggi = unisciMessaggi(t.messaggi, filo);
    const risposte = new Set(t.messaggi.filter((m) => m.fid && m.fid.startsWith("a-")).map((m) => m.fid.slice(2)));
    if (t.messaggi.some((m) => m.fid && m.fid.startsWith("a-") && !m.errore)) t.avviata = true;
    const inAttesa = (filo.in_attesa || []).map(String);
    if (t.attesa && t.attesa.id && !t.attesa.comando) {
      const id = String(t.attesa.id);
      // la risposta è arrivata dal server prima che seguiRisposte la leggesse: l'attesa finisce qui
      if (risposte.has(id) || (t.attesa.daFili && !inAttesa.includes(id))) {
        t.attesa = null;
        delete ATTESE[k];
      }
    } else if (!t.attesa && inAttesa.length) {
      const id = inAttesa[inAttesa.length - 1];
      if (!risposte.has(id)) {
        const q = (filo.messaggi || []).find((m) => m && m.id === "q-" + id);
        // domanda partita da un altro dispositivo: anche qui «sta lavorando», e seguiRisposte prende la risposta
        t.attesa = { id, inizio: q && q.ts ? Math.round(q.ts * 1000) : Date.now(), comando: false, titolo: "", daFili: true };
      }
    }
    return JSON.stringify([t.sessione, t.messaggi, t.attesa || null]) !== prima;
  }
  // Quale filo del server vale per k (null = nessuno da applicare)
  function scelta(k, f, perSessione) {
    const t = THREADS[k];
    if (!t) return f;
    if (t.sessione === f.sessione) return f;
    if (t.attesa) return null;                                      // sta partendo una domanda da qui
    const mio = perSessione.get(t.sessione);
    if (mio) return (f.aggiornato || 0) >= (mio.aggiornato || 0) ? f : null;
    // chat vuota mai usata (dispositivo nuovo): prende il filo del server; chat svuotata qui: solo fili più nuovi
    if (!Array.isArray(t.messaggi) || !t.messaggi.length) return (f.aggiornato || 0) * 1000 > (RIPARTITI[t.sessione] || 0) ? f : null;
    // chat con messaggi che il server non conosce (di prima di fili.js): solo un filo aggiornato dopo
    return (f.aggiornato || 0) * 1000 > (VISTO[t.sessione] || 0) ? f : null;
  }

  // ---------------------------------------------------------------- lettura dal server
  async function leggi(percorso) {
    const r = await fetch(percorso, { headers: { "X-Token": window.CC_TOKEN || "" }, cache: "no-store" });
    if (r.status === 404 && percorso === "/api/fili") { S.attivo = false; return null; }
    if (!r.ok) throw new Error("fili: " + r.status);
    return r.json();
  }
  async function sincronizza() {
    if (S.attivo === false) return;
    if (S.inCorso) { S.ancora = true; return; }
    S.inCorso = true;
    try {
      const el = await leggi("/api/fili");
      if (!el || !Array.isArray(el.fili)) return;
      S.attivo = true;
      S.letture++;
      S.ultimo = Date.now();
      const perSessione = new Map(el.fili.map((f) => [f.sessione, f]));
      const perK = new Map();
      for (const f of el.fili) {                // già dal più recente
        if (!f || !f.interlocutore || LASCIATI.has(f.sessione) || perK.has(f.interlocutore)) continue;
        perK.set(f.interlocutore, f);
      }
      let ridisegna = false, salva = false, rinvia = false;
      for (const [k, f] of perK) {
        if (!chiaveOk(k)) continue;
        const scelto = scelta(k, f, perSessione);
        if (!scelto) continue;
        const t = THREADS[k];
        const stessa = t && t.sessione === scelto.sessione;
        if (stessa && S.versioni.get(scelto.sessione) === scelto.versione) continue;
        if (t && t.attesa && seguendo()) { rinvia = true; continue; }   // seguiRisposte sta leggendo: dopo
        const filo = await leggi("/api/fili/" + encodeURIComponent(scelto.sessione));
        if (!filo || !Array.isArray(filo.messaggi)) continue;
        if (THREADS[k] && THREADS[k].attesa && seguendo()) { rinvia = true; continue; }
        const cambiato = applica(k, filo);
        S.versioni.set(filo.sessione, filo.versione);
        if (cambiato) { salva = true; S.unioni++; if (k === chatCon) ridisegna = true; }
      }
      if (salva) window.salvaFili();
      if (ridisegna) {
        try { disegnaMessaggi(); } catch (e) { /* niente */ }
        try { aggiornaInvia(); } catch (e) { /* niente */ }
      } else if (salva) {
        try { if (typeof segnaAttivi === "function") segnaAttivi(); } catch (e) { /* niente */ }
      }
      if (rinvia) programma(700);
    } catch (e) {
      S.errori++;                               // rete giù o sessione del ponte scaduta: si riprova al giro dopo
    } finally {
      S.inCorso = false;
      if (S.ancora) { S.ancora = false; programma(150); }
    }
  }
  function programma(ms = 200) {
    clearTimeout(S.timer);
    S.timer = setTimeout(sincronizza, ms);
  }

  // ---------------------------------------------------------------- flusso e ritmo
  // Stesso gancio di approvazioni.js (window.__ccFlusso): ogni EventSource verso /api/flusso, anche i
  // ricollegamenti di app.js, riceve l'ascoltatore prima del primo evento.
  function suFlusso(fn) {
    const H = window.__ccFlusso || (window.__ccFlusso = { fns: [], aperti: [] });
    if (!H.avvolto && typeof window.EventSource === "function") {
      H.avvolto = true;
      const Originale = window.EventSource;
      class EventSourceCC extends Originale {
        constructor(url, conf) {
          super(url, conf);
          try {
            if (/\/api\/flusso(\?|$)/.test(String(url))) {
              H.aperti = H.aperti.filter((e) => e.readyState !== 2).concat(this);
              for (const f of H.fns) { try { f(this); } catch (e) { /* un iscritto rotto non ferma gli altri */ } }
            }
          } catch (e) { /* niente */ }
        }
      }
      window.EventSource = EventSourceCC;
    }
    H.fns.push(fn);
    for (const es of H.aperti) if (es.readyState !== 2) { try { fn(es); } catch (e) { /* niente */ } }
  }
  const agganciati = new WeakSet();
  function aggancia(es) {
    if (!es || agganciati.has(es)) return;
    agganciati.add(es);
    es.addEventListener("fili", () => programma(150));
    es.addEventListener("open", () => programma(300));     // dopo un buco del flusso si rilegge tutto
  }
  suFlusso(aggancia);
  try { if (typeof FLUSSO !== "undefined" && FLUSSO.es && FLUSSO.es.readyState !== 2) aggancia(FLUSSO.es); } catch (e) { /* niente */ }

  const vivo = () => { try { return typeof FLUSSO !== "undefined" && FLUSSO.stato === "live"; } catch (e) { return false; } };
  function giro() {
    clearTimeout(S.giro);
    try { if (typeof FLUSSO !== "undefined" && FLUSSO.es) aggancia(FLUSSO.es); } catch (e) { /* niente */ }
    if (S.attivo !== false && !document.hidden) sincronizza();
    if (S.attivo === false) return;
    S.giro = setTimeout(giro, document.hidden ? 60000 : vivo() ? 60000 : 10000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) giro(); });
  giro();
  setTimeout(() => programma(0), 3000);          // dopo il catalogo: gli agenti ora sono noti

  window.CCFili = {
    sincronizza: () => sincronizza(),
    stato: () => ({ attivo: S.attivo, letture: S.letture, unioni: S.unioni, errori: S.errori, ultimo: S.ultimo,
      versioni: Object.fromEntries(S.versioni), lasciati: [...LASCIATI], tolti: TOLTI }),
  };
})();
