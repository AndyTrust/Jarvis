// Approvazioni e segnalazioni (2026-10-03, contratto in command-center/CONTRATTO-approvazioni.md, sezione 1).
//
// Niente bypass dei permessi (decisione dell'utente): quando Jarvis chiede un permesso rischioso il
// backend crea una «approvazione» e qui compare una scheda «Rifiuta / Approva»:
//  - in chat, sotto la bolla «sta lavorando» del lavoro giusto (lavoro_id = t.attesa.id della chat aperta);
//  - altrimenti in un riquadro fisso in basso (sopra la barra di schede del telefono);
//  - sulla lavagna, in un riquadro sovrapposto di sola visualizzazione (non si salva in pannello.json);
//  - un badge nell'intestazione col numero di richieste in attesa e «(N)» nel titolo della scheda.
// In più le segnalazioni aperte della sentinella (s.sentinella.anomalie di /api/stato, già letto da
// app.js in «ultimoStato») e i raccoglitori in errore (s.salute) diventano schede informative con
// «Ok, visto», ricordato solo in questo browser (localStorage «apv.visti»).
//
// Ganci con app.js (nessuna modifica a app.js): le sue globali si leggono per nome
// (FLUSSO, THREADS, chatCon, ultimoStato sono const/let di uno script classico, non stanno su window).
// Se mancano, il file ripiega da solo: EventSource suo, nessuna scheda in chat, solo il riquadro.
// Backend vecchio (404 su /api/approvazioni): non compare niente e non si scrive niente in console.
(function approvazioni() {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const RISCHI = {
    basso: { parola: "Rischio basso", segno: "●" },
    medio: { parola: "Rischio medio", segno: "▲" },
    alto: { parola: "Rischio alto", segno: "■" },
  };
  const DECISO = { approvata: "Approvata", rifiutata: "Rifiutata", scaduta: "Scaduta" };
  const DA = { web: "da qui", mac: "dal Mac", telegram: "da Telegram", nessuno: "" };
  const CHIAVE_VISTI = "apv.visti";
  const SONDA_SENZA_FLUSSO = 5000, SONDA_CON_FLUSSO = 30000, SONDA_NASCOSTA = 30000;

  // ---------------------------------------------------------------- stato
  const S = {
    attivo: null,            // null = non so ancora, false = backend senza approvazioni (404), true = c'è
    lista: new Map(),        // id -> A (dal server)
    locale: new Map(),       // id -> {fase:"invio"|"esito"|"errore", testo, quando, chiudiDopo}
    scarto: 0,               // ora del server - ora del browser, in secondi
    esFlusso: null,          // l'EventSource su cui ho messo i miei ascoltatori
    mioEs: null,             // EventSource mio, solo se app.js non ne espone uno
    timer: null,
    ridotto: false,          // il riquadro in basso ridotto a una riga
    annunciati: new Set(),
    conferma: new Map(),     // id -> scadenza del secondo tocco su «Approva» (rischio alto)
    daEvento: new Map(),     // id -> quando è arrivata dal flusso (ms)
    lavAperto: null,         // riquadro sulla lavagna: null = aperto solo se c'è da decidere; si riapre a ogni richiesta nuova
    dettAperti: new Set(),   // «Dettagli» aperti, per scheda e posto: restano aperti dopo un ridisegno
    primo: new Map(),        // id -> quando è arrivato il primo «Approva» (rischio alto: il secondo vale dopo 800 ms)
    codici: new Map(),       // id -> codice monouso del «sì» in due tempi (revisione 3)
    visti: new Set(),        // id con i dettagli letti fino in fondo (REVISIONE-2: mai Approva su un testo non visto)
  };
  const CONFERMA_MIN = 800, CONFERMA_MAX = 5000;
  try { S.ridotto = sessionStorage.getItem("apv.ridotto") === "1"; } catch (e) { /* niente */ }

  const ora = () => Date.now() / 1000 + S.scarto;
  const hhmm = (ts) => new Date((ts ? ts - S.scarto : Date.now() / 1000) * 1000)
    .toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  // le globali di app.js (const/let di uno script classico): si leggono per nome, niente eval
  const G = {
    FLUSSO: () => (typeof FLUSSO !== "undefined" ? FLUSSO : undefined),          // eslint-disable-line no-undef
    THREADS: () => (typeof THREADS !== "undefined" ? THREADS : undefined),       // eslint-disable-line no-undef
    chatCon: () => (typeof chatCon !== "undefined" ? chatCon : undefined),       // eslint-disable-line no-undef
    ultimoStato: () => (typeof ultimoStato !== "undefined" ? ultimoStato : undefined),   // eslint-disable-line no-undef
  };
  const globale = (nome) => { try { return G[nome](); } catch (e) { return undefined; } };

  function el(tag, attrs, ...figli) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const f of figli) if (f != null && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }
  const testoCorto = (s, max) => { s = String(s == null ? "" : s); return s.length > max ? s.slice(0, max - 1) + "…" : s; };

  // ---------------------------------------------------------------- aggancio al flusso SSE (comune con attivita.js)
  // Avvolgo il costruttore di EventSource una volta sola: ogni EventSource verso /api/flusso (quello
  // di app.js e i suoi ricollegamenti) passa a chi si è iscritto, prima che arrivi il primo evento.
  // La classe resta un EventSource vero (instanceof, readyState, close: tutto come prima).
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

  // ---------------------------------------------------------------- annunci per i lettori di schermo
  const annuncio = el("div", { class: "apv-sr", role: "status", "aria-live": "polite", "aria-atomic": "true" });
  function annuncia(testo) { annuncio.textContent = ""; setTimeout(() => { annuncio.textContent = testo; }, 60); }

  // ---------------------------------------------------------------- lettura dal server
  async function leggi() {
    let r;
    try { r = await fetch("/api/approvazioni", { headers: { "X-Token": window.CC_TOKEN || "" }, cache: "no-store" }); }
    catch (e) { return; }                                   // rete giù: riprova al prossimo giro, in silenzio
    if (r.status === 404) { S.attivo = false; S.lista.clear(); disegna(); return; }
    if (!r.ok) return;
    let d;
    try { d = await r.json(); } catch (e) { return; }
    if (!d || !Array.isArray(d.in_attesa)) return;
    S.attivo = true;
    if (Number.isFinite(d.ora)) S.scarto = d.ora - Date.now() / 1000;
    const viste = new Set();
    // una scheda già chiusa qui (esito mostrato) non torna «in attesa» per una lettura arrivata in ritardo
    const tieni = (a) => valida(a) && !((S.locale.get(a.id) || {}).fase === "esito" && a.stato === "attesa");
    for (const a of d.in_attesa) if (tieni(a)) { S.lista.set(a.id, a); viste.add(a.id); }
    for (const a of d.recenti || []) if (valida(a) && S.lista.has(a.id)) { if (tieni(a)) S.lista.set(a.id, a); viste.add(a.id); }
    // una richiesta in attesa che il server non elenca più è stata decisa altrove o è sparita
    // (non quella appena arrivata col flusso: la lettura può essere partita prima dell'evento)
    for (const [id, a] of S.lista) if (!viste.has(id) && a.stato === "attesa" && !S.locale.has(id)
      && Date.now() - (S.daEvento.get(id) || 0) > 15000) S.lista.delete(id);
    disegna();
  }
  const valida = (a) => a && typeof a.id === "string" && /^[\w-]{1,64}$/.test(a.id);

  function riceviEvento(dati) {
    let a;
    try { a = typeof dati === "string" ? JSON.parse(dati) : dati; } catch (e) { return; }
    if (a && a.approvazione) a = a.approvazione;
    if (!valida(a)) return;
    S.attivo = true;
    S.lista.set(a.id, a);
    S.daEvento.set(a.id, Date.now());
    disegna();
  }

  // ---------------------------------------------------------------- flusso SSE
  // app.js tiene il suo EventSource in FLUSSO.es e lo ricrea a ogni ricollegamento: ogni secondo
  // guardo se è cambiato e ci rimetto i miei ascoltatori. Il contratto dice «evento approvazione»:
  // accetto sia l'evento con nome (event: approvazione) sia un messaggio normale con tipo/chiavi.
  const agganciati = new WeakSet();
  function ascolta(es) {
    if (!es || agganciati.has(es)) return;
    agganciati.add(es);
    es.addEventListener("approvazione", (ev) => riceviEvento(ev.data));
    es.addEventListener("message", (ev) => {
      let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d && (d.tipo === "approvazione" || d.evento === "approvazione") && (d.approvazione || d.dati)) riceviEvento(d.approvazione || d.dati);
      else if (d && Array.isArray(d.chiavi) && d.chiavi.some((c) => /^approvazion/.test(c))) leggi();
    });
    es.addEventListener("open", () => { if (S.attivo !== false) leggi(); });   // dopo un buco del flusso si riallinea
  }
  // Gli eventi arrivano appena il flusso si apre: per non perderli mi aggancio quando l'EventSource
  // nasce (costruttore avvolto, condiviso con attivita.js), e in più guardo FLUSSO.es per quello già aperto.
  suFlusso(ascolta);
  function agganciaFlusso() {
    const F = globale("FLUSSO");
    if (F && typeof F === "object") {
      if (F.es && F.es !== S.esFlusso) { S.esFlusso = F.es; if (!agganciati.has(F.es)) { ascolta(F.es); leggi(); } }
      return;
    }
    // app.js senza FLUSSO: un EventSource mio, con lo stesso indirizzo (token nell'indirizzo)
    if (!S.mioEs && "EventSource" in window && window.CC_TOKEN && S.attivo) {
      const es = new EventSource("/api/flusso?token=" + encodeURIComponent(window.CC_TOKEN));
      S.mioEs = es;
      ascolta(es);
      es.onerror = () => { es.close(); setTimeout(() => { S.mioEs = null; }, 15000); };
    }
  }
  function flussoVivo() {
    const F = globale("FLUSSO");
    if (F && F.es && F.es === S.esFlusso && F.stato === "live") return true;
    return !!(S.mioEs && S.mioEs.readyState === 1);
  }

  function giro() {
    clearTimeout(S.timer);
    agganciaFlusso();
    if (S.attivo !== false) leggi();
    const ogni = document.hidden ? SONDA_NASCOSTA : flussoVivo() ? SONDA_CON_FLUSSO : SONDA_SENZA_FLUSSO;
    S.timer = setTimeout(giro, ogni);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && S.attivo !== false) giro(); });

  // ---------------------------------------------------------------- la decisione
  // revisione 3 (2026-10-04): per il rischio alto il server accetta il «sì» solo con un codice monouso chiesto al
  // primo tocco (valido 5 s, usabile dopo 800 ms): lo stesso ritmo dei due tocchi della scheda.
  async function prepara(id) {
    try {
      const r = await fetch("/api/azione", { method: "POST", cache: "no-store",
        headers: { "X-Token": window.CC_TOKEN || "", "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "approva", id, decisione: "si", fase: "prepara" }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d && typeof d.codice === "string") S.codici.set(id, d.codice);
    } catch (e) { /* il secondo tocco riceverà 428 e lo dirà */ }
  }
  async function decidi(id, decisione) {
    const a = S.lista.get(id);
    if (!a || (S.locale.get(id) || {}).fase === "invio") return;
    if (a.stato !== "attesa") return;
    if (decisione === "si" && soloRifiuto(a)) {
      annuncia("Il comando è stato tagliato e la parte finale non si vede: si può solo rifiutare.");
      return;
    }
    if (decisione === "si" && !vistoTutto(a)) {        // mai Approva su un testo che non si è visto per intero
      annuncia("Apri «Dettagli» e leggi la richiesta fino in fondo: Approva si accende dopo.");
      return;
    }
    if (decisione === "si" && a.rischio === "alto") {
      const fino = S.conferma.get(id) || 0, ora = Date.now();
      if (ora > fino) {                             // rischio alto: secondo tocco dopo 0,8 s ed entro 5 s
        S.conferma.set(id, ora + CONFERMA_MAX);
        S.primo.set(id, ora);
        setTimeout(() => { if ((S.conferma.get(id) || 0) <= Date.now()) { S.conferma.delete(id); disegna(); } }, CONFERMA_MAX + 100);
        disegna();
        annuncia("Rischio alto: premi di nuovo Approva per confermare.");
        prepara(id);                                  // revisione 3: il server vuole il «sì» in due tempi
        return;
      }
      if (ora - (S.primo.get(id) || 0) < CONFERMA_MIN) {  // due tocchi troppo vicini (doppio clic, tasto ripetuto): non vale
        annuncia("Rischio alto: aspetta un istante, poi premi di nuovo Approva.");
        return;
      }
      S.conferma.delete(id); S.primo.delete(id);
    }
    S.locale.set(id, { fase: "invio", testo: decisione === "si" ? "Approvo…" : "Rifiuto…" });
    disegna();
    const ctl = new AbortController();
    const tetto = setTimeout(() => ctl.abort(), 15000);
    let r, d = {};
    try {
      r = await fetch("/api/azione", {
        method: "POST", signal: ctl.signal, cache: "no-store",
        headers: { "X-Token": window.CC_TOKEN || "", "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ tipo: "approva", id, decisione },
          decisione === "si" && S.codici.has(id) ? { codice: S.codici.get(id) } : {})),
      });
      d = await r.json().catch(() => ({}));
    } catch (e) {
      clearTimeout(tetto);
      const testo = e.name === "AbortError" ? "Il Command Center non ha risposto entro 15 s: la decisione potrebbe non essere arrivata. Riprova."
        : "Rete assente: la decisione non è partita. Controlla la connessione e riprova.";
      S.locale.set(id, { fase: "errore", testo });
      disegna(); annuncia(testo);
      return;
    }
    clearTimeout(tetto);
    S.codici.delete(id);
    if (r.status === 428) {                         // il «sì» in due tempi non è valido (troppo presto, scaduto, codice mancante)
      const testo = "Conferma non valida (" + testoCorto((d && d.errore) || "serve il secondo tocco", 120) + "): premi di nuovo Approva, poi ancora dopo un istante.";
      S.locale.set(id, { fase: "errore", testo });
      disegna(); annuncia(testo);
      return;
    }
    if (r.ok && d && (d.ok || d.stato)) {
      const stato = d.stato || (decisione === "si" ? "approvata" : "rifiutata");
      S.lista.set(id, Object.assign({}, a, { stato, deciso: d.deciso || ora(), deciso_da: d.gia_deciso ? a.deciso_da || "" : "web" }));
      const testo = d.gia_deciso ? `Era già ${stato} ${DA[a.deciso_da] || "altrove"}: niente da fare.` : "";
      chiudiPoi(id, testo, 4000);
      return;
    }
    let testo;
    if (r.status === 404) {
      testo = "Questa richiesta non esiste più: il Command Center potrebbe essere ripartito. La tolgo.";
      S.lista.set(id, Object.assign({}, a, { stato: "sparita" }));
      chiudiPoi(id, testo, 6000);
      return;
    }
    if (r.status === 409) {
      testo = "Troppo tardi: la richiesta è scaduta e Jarvis ha già ricevuto un rifiuto.";
      S.lista.set(id, Object.assign({}, a, { stato: "scaduta", deciso: ora() }));
      chiudiPoi(id, testo, 6000);
      return;
    }
    if (r.status === 403 && d && d.token_scaduto) testo = "Il Command Center è ripartito: ricarica la pagina e decidi di nuovo.";
    else testo = `Non sono riuscito a mandare la decisione (${d && d.errore ? testoCorto(d.errore, 160) : "errore " + r.status}). Riprova.`;
    S.locale.set(id, { fase: "errore", testo });
    disegna(); annuncia(testo);
  }
  function chiudiPoi(id, nota, ms) {
    const a = S.lista.get(id);
    S.locale.set(id, { fase: "esito", testo: nota || "", chiudiDopo: Date.now() + ms });
    const fuoco = document.activeElement && document.activeElement.closest && document.activeElement.closest(`.apv-scheda[data-id="${CSS.escape(id)}"]`);
    disegna();
    annuncia(`${riga(a)}${nota ? ". " + nota : ""}`);
    if (fuoco) spostaFuoco(id);
    setTimeout(() => {
      S.locale.delete(id);
      const b = S.lista.get(id);
      if (b && b.stato !== "attesa") S.lista.delete(id);
      disegna();
    }, ms);
  }
  // dopo una decisione presa con il fuoco nella scheda, il fuoco va alla prossima richiesta (o resta dov'è)
  function spostaFuoco(idDeciso) {
    requestAnimationFrame(() => {
      const prossima = [...document.querySelectorAll('.apv-scheda[data-stato="attesa"]')]
        .find((s) => s.dataset.id !== idDeciso && s.offsetParent !== null);
      if (prossima) prossima.focus({ preventScroll: false });
      else { const s = document.querySelector(`.apv-scheda[data-id="${CSS.escape(idDeciso)}"]`); if (s && s.offsetParent !== null) s.focus(); }
    });
  }
  const riga = (a) => {
    if (!a) return "";
    const st = a.stato === "attesa" ? "" : DECISO[a.stato] || "";
    return st ? `${st} alle ${hhmm(a.deciso)}${DA[a.deciso_da] ? " " + DA[a.deciso_da] : ""}` : "";
  };

  // ---------------------------------------------------------------- disegno di una scheda
  function scade(a) {
    const resta = Math.max(0, Math.round((a.scade || 0) - ora()));
    return { resta, testo: `${String(Math.floor(resta / 60)).padStart(2, "0")}:${String(resta % 60).padStart(2, "0")}` };
  }
  function scheda(a, dove) {
    const loc = S.locale.get(a.id) || {};
    const rischio = RISCHI[a.rischio] ? a.rischio : "medio";
    const attesa = a.stato === "attesa";
    const idTit = `apv-t-${dove}-${a.id}`;
    const s = el("section", {
      class: `apv-scheda apv-r-${rischio}` + (attesa ? "" : " apv-decisa apv-s-" + a.stato),
      "data-id": a.id, "data-stato": attesa ? (loc.fase === "invio" ? "invio" : "attesa") : a.stato,
      tabindex: "0", role: "group", "aria-labelledby": idTit,
      "aria-describedby": attesa ? `apv-k-${dove}-${a.id}` : null,
    });
    const capo = el("div", { class: "apv-capo" },
      el("span", { class: "apv-rischio" }, el("span", { "aria-hidden": "true" }, RISCHI[rischio].segno + " "), RISCHI[rischio].parola),
      el("span", { class: "apv-chi" }, testoCorto([a.agente || "Jarvis", a.strumento].filter(Boolean).join(" · "), 60)),
      attesa && a.scade ? el("span", { class: "apv-scade", "data-scade": a.id }, "scade tra ", el("b", {}, scade(a).testo)) : "");
    const titolo = el("h3", { class: "apv-titolo", id: idTit },
      el("span", { class: "apv-sr" }, "Richiesta di permesso: "), testoCorto(a.riepilogo || "Jarvis chiede un permesso", 300));
    s.append(capo, titolo);
    const det = dettagli(a, dove);
    if (det) s.append(det);
    if (attesa) {
      const inviando = loc.fase === "invio";
      const confermare = S.conferma.has(a.id);
      const visto = vistoTutto(a);
      const no = el("button", { type: "button", class: "apv-no", disabled: inviando, onclick: () => decidi(a.id, "no") }, "Rifiuta");
      const si = el("button", { type: "button", class: "apv-si" + (confermare ? " apv-conferma" : ""), disabled: inviando || !visto,
        title: visto ? null : "Apri «Dettagli» e leggi la richiesta fino in fondo",
        "aria-label": confermare ? "Conferma: approva davvero" : null, onclick: () => decidi(a.id, "si") },
        confermare ? "Tocca ancora per approvare" : "Approva");
      s.append(el("div", { class: "apv-bottoni" }, no, soloRifiuto(a) ? null : si));
      if (soloRifiuto(a)) s.append(el("p", { class: "apv-leggi" }, "Il comando è troppo lungo: la parte finale non arriva fin qui, quindi si può solo rifiutare."));
      else if (!visto) s.append(el("p", { class: "apv-leggi" }, "Apri «Dettagli» e leggi fino in fondo: Approva si accende dopo."));
      s.append(el("p", { class: "apv-tasti", id: `apv-k-${dove}-${a.id}` },
        rischio === "alto" ? "Con la scheda selezionata: tasto R rifiuta. Il rischio alto si approva solo col tocco o col clic."
          : "Con la scheda selezionata: tasto A approva, R rifiuta."));
      if (loc.fase === "invio") s.append(el("p", { class: "apv-nota" }, loc.testo));
      if (loc.fase === "errore") s.append(el("p", { class: "apv-errore", role: "alert" }, loc.testo));
    } else {
      s.append(el("p", { class: "apv-esito" }, el("b", {}, a.stato === "sparita" ? "Non più valida" : riga(a) || DECISO[a.stato] || a.stato),
        loc.testo ? el("span", {}, " · " + loc.testo) : ""));
    }
    s.addEventListener("keydown", (ev) => {
      ev.stopPropagation();                         // la lavagna ha le sue scorciatoie: qui non arrivano
      if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.repeat) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      // solo con la scheda (o un suo pulsante) a fuoco; il rischio alto non si approva da tastiera
      if (!s.contains(document.activeElement)) return;
      const k = ev.key.toLowerCase();
      if (k === "a") {
        ev.preventDefault();
        if (rischio === "alto") { annuncia("Rischio alto: si approva solo col tocco o col clic su Approva."); return; }
        decidi(a.id, "si");
      } else if (k === "r") { ev.preventDefault(); decidi(a.id, "no"); }
    });
    // la lavagna sposta il foglio col puntatore e la rotella: dentro la scheda non deve succedere
    for (const tipo of ["pointerdown", "mousedown", "touchstart", "wheel", "dblclick", "contextmenu"])
      s.addEventListener(tipo, (ev) => ev.stopPropagation(), { passive: true });
    return s;
  }
  // c'è qualcosa da leggere prima di approvare? (comando, percorso, anteprima)
  const daLeggere = (a) => { const d = a && a.dettagli && typeof a.dettagli === "object" ? a.dettagli : {}; return !!(d.comando || d.percorso || d.anteprima); };
  // revisione 4: comando tagliato dal server = la coda non si vede: resta solo «Rifiuta» (il server rifiuta comunque il «sì»)
  const soloRifiuto = (a) => { const d = a && a.dettagli && typeof a.dettagli === "object" ? a.dettagli : {}; return d.troncato === true || d.comando_troncato === true; };
  const vistoTutto = (a) => !daLeggere(a) || S.visti.has(a.id);
  // il server taglia a 800 caratteri (con «…») e nasconde le righe con un possibile segreto: lo si dice
  function taglio(d) {
    const lunghi = [d.comando, d.anteprima].filter((x) => typeof x === "string");
    const tagliato = d.troncato === true || d.comando_troncato === true || lunghi.some((x) => x.length >= 799 && x.endsWith("…") || x.length > 4000);
    const nascosto = lunghi.some((x) => x.includes("[riga nascosta"));
    if (tagliato && nascosto) return "Attenzione: il testo è stato tagliato e alcune righe sono nascoste (sembrano segreti): quello che non vedi non è controllabile.";
    if (tagliato) return "Attenzione: il testo è stato tagliato, la parte finale non arriva fin qui.";
    if (nascosto) return "Attenzione: alcune righe sono nascoste perché sembrano contenere un segreto.";
    return "";
  }
  function dettagli(a, dove) {
    const d = a.dettagli && typeof a.dettagli === "object" ? a.dettagli : {};
    const righe = [];
    const avviso = taglio(d);
    if (avviso) righe.push(el("p", { class: "apv-taglio", role: "note" }, avviso));
    if (d.comando) righe.push(el("div", { class: "apv-d" }, el("span", {}, "Comando"), el("pre", { tabindex: "0" }, testoCorto(d.comando, 4000))));
    if (d.percorso) righe.push(el("div", { class: "apv-d" }, el("span", {}, "Percorso"), el("code", {}, testoCorto(d.percorso, 400))));
    if (Number.isFinite(d.righe_aggiunte) || Number.isFinite(d.righe_tolte))
      righe.push(el("div", { class: "apv-d" }, el("span", {}, "Righe"),
        el("span", { class: "apv-righe" }, el("b", { class: "apv-piu" }, "+" + (d.righe_aggiunte || 0)), " ", el("b", { class: "apv-meno" }, "−" + (d.righe_tolte || 0)))));
    if (d.anteprima) righe.push(el("div", { class: "apv-d" }, el("span", {}, "Anteprima"), el("pre", { tabindex: "0" }, testoCorto(d.anteprima, 4000))));
    if (!righe.length) return null;
    const chiaveD = a.id + "@" + dove;
    const d2 = el("details", { class: "apv-dettagli", open: S.dettAperti.has(chiaveD) ? true : null }, el("summary", {}, "Dettagli"), ...righe);
    // letto fino in fondo: dettagli aperti e ogni riquadro che scorre arrivato in fondo
    const controlla = () => {
      if (S.visti.has(a.id) || !d2.open || !d2.isConnected) return;
      if ([...d2.querySelectorAll("pre, code")].some((x) => x.scrollTop + x.clientHeight < x.scrollHeight - 2)) return;
      S.visti.add(a.id);
      disegna();
    };
    d2.addEventListener("toggle", () => { if (d2.open) S.dettAperti.add(chiaveD); else S.dettAperti.delete(chiaveD); requestAnimationFrame(controlla); });
    d2.addEventListener("scroll", () => controlla(), { capture: true, passive: true });
    if (d2.open) requestAnimationFrame(controlla);
    return d2;
  }

  // ---------------------------------------------------------------- segnalazioni (sentinella e salute)
  let visti = {};
  try { visti = JSON.parse(localStorage.getItem(CHIAVE_VISTI) || "{}") || {}; } catch (e) { visti = {}; }
  function segnaVisto(chiave) {
    visti[chiave] = Math.round(Date.now() / 1000);
    const voci = Object.entries(visti).sort((x, y) => y[1] - x[1]).slice(0, 200);
    visti = Object.fromEntries(voci);
    try { localStorage.setItem(CHIAVE_VISTI, JSON.stringify(visti)); } catch (e) { /* solo per questa visita */ }
    disegna();
  }
  function gravita(testo) {
    if (/🔴/.test(testo)) return "guasto";
    if (/🟡/.test(testo)) return "attenzione";
    return /gi[uù]|errore|guast|fermo|mort[oa]|down\b|rott[oa]|fallit|non esiste|non aggancia|non risponde|timeout/i.test(testo) ? "guasto" : "attenzione";
  }
  function segnalazioni() {
    const s = globale("ultimoStato");
    if (!s || typeof s !== "object") return [];
    const fuori = [];
    const an = (s.sentinella && Array.isArray(s.sentinella.anomalie)) ? s.sentinella.anomalie : [];
    for (const x of an) {
      const testo = String((x && x.testo) || (x && x.chiave) || "");
      if (!testo) continue;
      const chiave = "sent:" + (x.chiave || testo.slice(0, 80)) + ":" + Math.round(x.da_ts || 0);
      fuori.push({ chiave, fonte: "Sentinella", tipo: String(x.tipo || "anomalia"), testo, da_ts: x.da_ts || 0, gravita: gravita(testo) });
    }
    const rac = (s.salute && Array.isArray(s.salute.raccoglitori)) ? s.salute.raccoglitori : [];
    for (const r of rac) {
      if (!r || !r.errore) continue;
      const nome = String(r.nome || r.chiave || "raccoglitore").replace(/^raccogli_/, "");
      fuori.push({ chiave: "sal:" + nome + ":" + String(r.errore).slice(0, 60), fonte: "Salute del pannello", tipo: nome,
        testo: String(r.errore), da_ts: 0, gravita: "guasto" });
    }
    return fuori.filter((x) => !visti[x.chiave]);
  }
  function schedaSegnalazione(x) {
    const s = el("section", { class: "apv-segn apv-g-" + x.gravita, tabindex: "-1", role: "group", "aria-label": `${x.fonte}: ${x.testo}` },
      el("div", { class: "apv-capo" },
        el("span", { class: "apv-rischio" }, el("span", { "aria-hidden": "true" }, x.gravita === "guasto" ? "■ " : "▲ "), x.gravita === "guasto" ? "Guasto" : "Attenzione"),
        el("span", { class: "apv-chi" }, testoCorto(`${x.fonte} · ${x.tipo}`, 60)),
        x.da_ts ? el("span", { class: "apv-scade" }, "dalle " + hhmm(x.da_ts)) : ""),
      el("p", { class: "apv-segn-testo" }, testoCorto(x.testo, 400)),
      el("div", { class: "apv-bottoni" }, el("button", { type: "button", class: "apv-visto", onclick: () => segnaVisto(x.chiave) }, "Ok, visto")));
    for (const tipo of ["pointerdown", "mousedown", "touchstart", "wheel", "dblclick", "contextmenu"])
      s.addEventListener(tipo, (ev) => ev.stopPropagation(), { passive: true });
    s.addEventListener("keydown", (ev) => ev.stopPropagation());
    return s;
  }

  // ---------------------------------------------------------------- contenitori
  const badge = el("button", { type: "button", class: "apv-badge nascosto", id: "apv-badge", onclick: vaiAllaPrima },
    el("span", { class: "apv-badge-segno", "aria-hidden": "true" }, "⚑"), el("b", { class: "apv-badge-n" }, "0"),
    el("span", { class: "apv-badge-parola" }, " da approvare"));
  const vassoio = el("aside", { class: "apv-vassoio nascosto", id: "apv-vassoio", "aria-label": "Richieste di permesso" });
  const vassoioCapo = el("div", { class: "apv-vassoio-capo" });
  const vassoioCorpo = el("div", { class: "apv-vassoio-corpo" });
  vassoio.append(vassoioCapo, vassoioCorpo);
  const sopraLav = el("aside", { class: "apv-lavagna nascosto", id: "apv-lavagna", "aria-label": "Richieste e segnalazioni sulla lavagna" });
  for (const tipo of ["pointerdown", "mousedown", "touchstart", "wheel", "dblclick", "contextmenu", "keydown"])
    sopraLav.addEventListener(tipo, (ev) => ev.stopPropagation(), { passive: tipo !== "keydown" });

  function monta() {
    document.body.append(annuncio, vassoio);
    const barra = document.querySelector("header.barra");
    if (barra) {
      const prima = barra.querySelector(".stato-generale") || barra.querySelector("#flusso");
      if (prima) barra.insertBefore(badge, prima); else barra.append(badge);
    } else document.body.append(badge);
    const lavagna = $("lavagna");
    if (lavagna) lavagna.append(sopraLav);
    // il titolo: app.js lo riscrive a ogni cambio di vista, io rimetto «(N)» davanti
    const t = document.querySelector("title") || document.head.appendChild(el("title", {}, document.title));
    new MutationObserver(aggiornaTitolo).observe(t, { childList: true, characterData: true, subtree: true });
    // la chat si ridisegna intera (disegnaMessaggi): rimetto le schede dove vanno
    const box = $("messaggi");
    // (le mie schede dentro #messaggi non contano: altrimenti il ridisegno si richiamerebbe da solo)
    const mia = (n) => n.nodeType === 1 && n.classList.contains("apv-in-chat");
    if (box) new MutationObserver((muta) => {
      if (muta.every((m) => [...m.addedNodes, ...m.removedNodes].every(mia))) return;
      pianifica();
    }).observe(box, { childList: true });
    addEventListener("hashchange", () => pianifica());
  }

  function inAttesa() {
    return [...S.lista.values()].filter((a) => a.stato === "attesa").sort((x, y) => (x.creata || 0) - (y.creata || 0));
  }
  function aggiornaTitolo() {
    const n = S.attivo ? inAttesa().length : 0;
    const base = document.title.replace(/^\(\d+\)\s*/, "");
    const voluto = n ? `(${n}) ${base}` : base;
    if (document.title !== voluto) document.title = voluto;
  }
  function vaiAllaPrima() {
    const visibili = [...document.querySelectorAll('.apv-scheda[data-stato="attesa"]')].filter((s) => s.offsetParent !== null)
      .sort((x, y) => (x.closest(".apv-lavagna") ? 1 : 0) - (y.closest(".apv-lavagna") ? 1 : 0));   // prima la chat e il riquadro
    if (S.ridotto && !visibili.length) { S.ridotto = false; salvaRidotto(); disegna(); return vaiAllaPrima(); }
    const s = visibili[0];
    if (s) { s.scrollIntoView({ block: "center", behavior: "smooth" }); s.focus({ preventScroll: true }); }
  }
  function salvaRidotto() { try { sessionStorage.setItem("apv.ridotto", S.ridotto ? "1" : "0"); } catch (e) { /* niente */ } }

  // la chat aperta aspetta proprio il lavoro di questa richiesta?
  function bollaDelLavoro(lavoroId) {
    if (!lavoroId) return null;
    const T = globale("THREADS"), k = globale("chatCon");
    if (!T || !k || !T[k] || !T[k].attesa || T[k].attesa.id !== lavoroId) return null;
    const box = $("messaggi");
    if (!box || box.offsetParent === null) return null;       // chat non visibile (altra vista)
    const dur = box.querySelector("#durata-attesa");
    return dur ? dur.closest(".msg") : null;
  }
  const lavagnaIntera = () => location.hash === "#lavagna";
  const lavagnaVisibile = () => { const l = $("lavagna"); return !!(l && l.offsetParent !== null && l.offsetWidth > 0); };

  let pianificato = false;
  function pianifica() {
    if (pianificato) return;
    pianificato = true;
    requestAnimationFrame(() => { pianificato = false; disegna(); });
  }

  const firmaDi = (lista) => lista.map((a) => {
    const l = S.locale.get(a.id) || {};
    return [a.id, a.stato, a.rischio, a.riepilogo, a.deciso, l.fase || "", l.testo || "", S.conferma.has(a.id) ? "c" : "",
      S.visti.has(a.id) ? "v" : "", JSON.stringify(a.dettagli || {}).length].join("~");
  }).join("^");

  function disegna() {
    const attive = S.attivo ? [...S.lista.values()].sort((x, y) => (x.creata || 0) - (y.creata || 0)) : [];
    const pendenti = attive.filter((a) => a.stato === "attesa");
    const segn = segnalazioni();
    // annuncio delle richieste nuove (una volta sola per id)
    for (const a of pendenti) if (!S.annunciati.has(a.id)) {
      S.annunciati.add(a.id);
      S.lavAperto = true;
      if (S.attivo) annuncia(`Nuova richiesta di permesso, ${(RISCHI[a.rischio] || RISCHI.medio).parola.toLowerCase()}: ${testoCorto(a.riepilogo || "", 120)}`);
    }
    // badge e titolo
    badge.classList.toggle("nascosto", !pendenti.length);
    badge.querySelector(".apv-badge-n").textContent = String(pendenti.length);
    badge.setAttribute("aria-label", pendenti.length === 1 ? "1 richiesta da approvare: vai alla scheda" : `${pendenti.length} richieste da approvare: vai alla prima`);
    badge.classList.toggle("apv-badge-alto", pendenti.some((a) => a.rischio === "alto"));
    aggiornaTitolo();

    // 1) in chat sotto la bolla del lavoro, 2) nel riquadro in basso
    const box = $("messaggi");
    const vicinoAlFondo = box ? box.scrollHeight - box.scrollTop - box.clientHeight < 120 : false;
    const fuocoId = document.activeElement && document.activeElement.closest && (document.activeElement.closest(".apv-scheda") || {}).dataset;
    const fuocoDove = document.activeElement && document.activeElement.closest && document.activeElement.closest(".apv-in-chat, .apv-vassoio, .apv-lavagna");
    const inChat = [], nelVassoio = [];
    for (const a of attive) {
      const bolla = bollaDelLavoro(a.lavoro_id);
      if (bolla) inChat.push({ a, bolla }); else nelVassoio.push(a);
    }
    // in chat: un contenitore per bolla, subito dopo
    // (si ridisegna solo se cambia qualcosa: un tocco su un pulsante che sparisce sotto il dito va perso)
    if (box) {
      const perBolla = new Map();
      for (const { a, bolla } of inChat) { if (!perBolla.has(bolla)) perBolla.set(bolla, []); perBolla.get(bolla).push(a); }
      const vecchi = [...box.querySelectorAll(".apv-in-chat")];
      const uguale = vecchi.length === perBolla.size && [...perBolla].every(([bolla, lista]) => {
        const c = bolla.nextElementSibling;
        return c && c.classList.contains("apv-in-chat") && c.dataset.firma === firmaDi(lista);
      });
      if (!uguale) {
        for (const vecchio of vecchi) vecchio.remove();
        for (const [bolla, lista] of perBolla) {
          const c = el("div", { class: "apv-in-chat", "aria-live": "off", "data-firma": firmaDi(lista) }, ...lista.map((a) => scheda(a, "chat")));
          bolla.after(c);
        }
        if (inChat.length && vicinoAlFondo) box.scrollTop = box.scrollHeight;
      }
    }
    // riquadro in basso: le richieste non agganciate a una chat visibile (le segnalazioni stanno
    // solo sulla lavagna: in chat sarebbero rumore fisso sopra il campo di scrittura)
    const mostraVassoio = !lavagnaIntera() && nelVassoio.length > 0;
    // nella vista Chat il riquadro si mette in fila fra i messaggi e il campo di scrittura (non copre
    // né l'ultima risposta né il campo); nelle altre viste resta fisso in basso
    const comp = document.querySelector(".vista-chat .compositore");
    const inFila = !!(comp && comp.offsetParent !== null);
    if (inFila && vassoio.nextElementSibling !== comp) comp.before(vassoio);
    else if (!inFila && vassoio.parentNode !== document.body) document.body.append(vassoio);
    vassoio.classList.toggle("apv-in-fila", inFila);
    vassoio.classList.toggle("nascosto", !mostraVassoio);
    vassoio.classList.toggle("apv-ridotto", S.ridotto);
    document.body.classList.toggle("apv-con-vassoio", mostraVassoio && !S.ridotto);
    const firmaV = mostraVassoio ? firmaDi(nelVassoio) + "|" + S.ridotto : "";
    if (firmaV === vassoio.dataset.firma) { /* niente da cambiare */ } else if (mostraVassoio) {
      vassoio.dataset.firma = firmaV;
      const nP = nelVassoio.filter((a) => a.stato === "attesa").length;
      vassoioCapo.replaceChildren(
        el("b", {}, nP === 1 ? "1 richiesta da decidere" : nP ? `${nP} richieste da decidere` : "Decisione registrata"),
        el("button", { type: "button", class: "apv-riduci", "aria-expanded": S.ridotto ? "false" : "true",
          onclick: () => { S.ridotto = !S.ridotto; salvaRidotto(); disegna(); } }, S.ridotto ? "Apri" : "Riduci"));
      vassoioCorpo.replaceChildren(...nelVassoio.map((a) => scheda(a, "vass")));
    } else { vassoio.dataset.firma = ""; vassoioCorpo.replaceChildren(); }
    // lavagna: tutte le richieste e tutte le segnalazioni non viste (sola visualizzazione)
    const suLav = attive.length + segn.length > 0 && !!$("lavagna");
    sopraLav.classList.toggle("nascosto", !suLav);
    const firmaL = suLav ? firmaDi(attive) + "|" + segn.map((x) => x.chiave).join(",") + "|" + S.lavAperto : "";
    if (suLav && firmaL !== sopraLav.dataset.firma) {
      sopraLav.dataset.firma = firmaL;
      const parti = [];
      if (pendenti.length) parti.push(pendenti.length === 1 ? "1 da decidere" : `${pendenti.length} da decidere`);
      if (segn.length) parti.push(segn.length === 1 ? "1 segnalazione" : `${segn.length} segnalazioni`);
      const box = el("details", { class: "apv-lav-box", open: (S.lavAperto == null ? pendenti.length > 0 : S.lavAperto) ? true : null },
        el("summary", {}, el("b", {}, parti.join(" · ") || "Decisione registrata")),
        el("div", { class: "apv-lav-corpo" }, ...attive.map((a) => scheda(a, "lav")), ...segn.map(schedaSegnalazione)));
      box.addEventListener("toggle", () => { S.lavAperto = box.open; });
      sopraLav.replaceChildren(box);
    } else if (!suLav) sopraLav.dataset.firma = "";
    // il fuoco resta sulla stessa scheda dopo un ridisegno
    if (fuocoId && fuocoId.id && fuocoDove) {
      const dove = fuocoDove.classList.contains("apv-in-chat") ? ".apv-in-chat" : fuocoDove.classList.contains("apv-vassoio") ? ".apv-vassoio" : ".apv-lavagna";
      const s = document.querySelector(`${dove} .apv-scheda[data-id="${CSS.escape(fuocoId.id)}"]`) || document.querySelector(`.apv-scheda[data-id="${CSS.escape(fuocoId.id)}"]`);
      if (s && document.activeElement !== s && !s.contains(document.activeElement)) s.focus({ preventScroll: true });
    }
  }

  // il conto alla rovescia, senza ridisegnare le schede
  function battito() {
    let scaduta = false;
    for (const n of document.querySelectorAll("[data-scade]")) {
      const a = S.lista.get(n.dataset.scade);
      if (!a) continue;
      const { resta, testo } = scade(a);
      const b = n.querySelector("b");
      if (b && b.textContent !== testo) b.textContent = testo;
      n.classList.toggle("apv-poco", resta <= 60);
      if (resta <= 0 && a.stato === "attesa") scaduta = true;
    }
    if (scaduta) {
      for (const a of S.lista.values()) if (a.stato === "attesa" && a.scade && a.scade - ora() <= 0) {
        S.lista.set(a.id, Object.assign({}, a, { stato: "scaduta", deciso: a.scade, deciso_da: "nessuno" }));
        chiudiPoi(a.id, "nessuna risposta in tempo: Jarvis ha ricevuto un rifiuto", 8000);
      }
      leggi();
    }
  }

  // ---------------------------------------------------------------- avvio
  function avvio() {
    monta();
    giro();
    setInterval(battito, 1000);
    setInterval(agganciaFlusso, 1000);
    // le segnalazioni arrivano con /api/stato (letto da app.js): ricontrollo ogni 3 s senza chiamate nuove
    let firma = "";
    setInterval(() => {
      const f = segnalazioni().map((x) => x.chiave).join("|");
      if (f !== firma) { firma = f; disegna(); }
    }, 3000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvio); else avvio();

  // per le prove e per altri script (sola lettura + forzare una rilettura)
  window.CCApprovazioni = { rileggi: leggi, stato: () => ({ attivo: S.attivo, in_attesa: inAttesa().map((a) => a.id) }) };
})();
