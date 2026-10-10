// Dots vivi: l'avanzata delle richieste sulla lavagna (2026-10-04, agente «dots-vivi»).
// l'utente: «gli agenti stanno nel menu laterale collegato con la lavagna, e devono vedersi avanzare ogni
// avatar Dots mentre le richieste passano da un agente all'altro». Disegno approvato:
//   A manda a B   il Dot di A si «apre», un impulso corre sul filo verso B con il testo corto dell'incarico
//   B lavora      anello attorno al Dot di B che si riempie, e il tempo che passa («da 12 s»)
//   C risponde    lampo verde e ✓ su C, l'impulso torna verso chi ha chiesto
//   errore        Dot rosso con «!», il filo si spezza
// L'anello si riempie sulla mediana delle ultime durate (durata_s) di quell'agente se ce ne sono almeno 3;
// altrimenti gira senza percentuale. Filo e Dot restano accesi qualche secondo dopo la fine.
//
// Come lavora, senza toccare app.js:
//  - i dati: il registro delle attività (attivita.py) che il server serve. Il flusso in tempo reale della
//    pagina (FLUSSO.es di app.js, o un EventSource suo se manca) dice quando c'è una riga nuova (chiave
//    «attivita»); allora si legge /api/agenti-attivita (il sommario per agente) e, solo per gli agenti
//    cambiati o con richieste aperte, /api/agente-attivita?agente=… (le righe ricomposte, con da/a canonici);
//  - una transizione si anima solo se è successa negli ultimi 20 s (ora del server): una pagina aperta
//    dopo, o tornata visibile, mostra lo stato e non rigioca la storia;
//  - i nodi: `#lav-mondo .nodo[data-agente="progetto:nome"]` (disegnaLavagna in app.js), Jarvis e l'utente
//    con schedaDiChiave() di app.js (le loro note); i fili: `#lav-fili path.filo[data-da][data-a]` (id dei nodi);
//  - quello che si vede: un <svg class="dv-strato"> e un <div class="dv-testi"> dentro #lav-mondo (seguono
//    zoom e spostamenti), pointer-events: none; sul nodo uno <span class="dv-segno"> (anello, ✓, «!»,
//    tempo come attributo: il textContent del nodo non cambia). Niente di questo entra nel pannello salvato:
//    si scrive solo nel DOM, mai in PAN / lav();
//  - leggero: un timer di 1 s solo mentre qualcosa è vivo; un MutationObserver su #lav-mondo e #lav-fili
//    (solo childList) rimette i segni dopo un ridisegno della lavagna. Testi sempre con textContent.
(() => {
  "use strict";
  if (window.CCDottiVivi) return;

  const SVGNS = "http://www.w3.org/2000/svg";
  const RECENTE_S = 20;        // una transizione più vecchia non si anima
  const TIENI_OK_S = 6;        // ✓ e filo verde dopo la risposta
  const TIENI_ERR_S = 14;      // «!» e filo spezzato dopo un errore
  const TIENI_SENZA_S = 6;     // etichetta di una richiesta senza destinatario
  const IMPULSO_MS = 1100;
  const MIN_DURATE = 3;
  const MAX_AGENTI_GIRO = 8;

  // ---------------------------------------------------------------- le globali di app.js (si leggono, mai si scrivono)
  const g = (fn, riserva = null) => { try { const v = fn(); return v === undefined ? riserva : v; } catch (e) { return riserva; } };
  /* eslint-disable no-undef */
  const lavagnaOra = () => g(() => lavagnaAttiva, "generale");
  const demo = () => g(() => eDemo(lavagnaOra()), false);
  const fili = () => g(() => lav().fili, []) || [];
  const schedaApp = (k) => g(() => schedaDiChiave(k), null);
  const flussoApp = () => g(() => FLUSSO, null);
  const apiApp = () => g(() => api, null);
  const curvaApp = (ra, rb) => g(() => curva(puntoVersoAltro(ra, rb.cx, rb.cy), puntoVersoAltro(rb, ra.cx, ra.cy)), null);
  /* eslint-enable no-undef */

  const stat = { disegni: 0, ms_ultimo: 0, ms_totale: 0, letture: 0, errori: 0 };
  const REQ = new Map();        // id -> riga ricomposta (da, a, testo, stato, inizio, partito, fine, durata_s)
  const DURATE = new Map();     // chiave agente -> [durate_s delle ricevute finite, le più recenti prima]
  let sommario = null, offset = 0, primo = true;

  const adesso = () => Date.now() / 1000 + offset;          // ora del server
  const ridotto = () => g(() => matchMedia("(prefers-reduced-motion: reduce)").matches, false);
  const corto = (t, n) => { t = String(t || "").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 1) + "…" : t; };
  const aperta = (r) => (r.stato === "in corso" || r.stato === "al lavoro") && !r.senza_risposta;
  const ignota = (k) => !k || String(k).startsWith("?:") || k === "?";

  // ---------------------------------------------------------------- lettura dal server
  async function chiedi(percorso) {
    const f = apiApp();
    if (f) return f(percorso);
    const r = await fetch(percorso, { headers: { "X-Token": window.CC_TOKEN || "" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  let inVolo = false, ancora = false, ultimaLettura = 0, timerLettura = null;
  function chiediGiro(subito) {
    clearTimeout(timerLettura);
    const attesa = subito ? 0 : Math.max(250, 1200 - (Date.now() - ultimaLettura));
    timerLettura = setTimeout(giro, attesa);
  }

  async function giro() {
    // 2026-10-05 (prova sul sito): prima una pagina «nascosta» (scheda in secondo piano, finestra coperta,
    // Chrome comandato da un altro programma) non leggeva mai niente: stat {letture: 0, disegni: 0} per sempre.
    // Ora legge e disegna lo STATO anche nascosta; le animazioni dei passaggi (impulsi) solo se si vede.
    const nascosta = document.hidden;
    if (inVolo) { ancora = true; return; }
    inVolo = true; ultimaLettura = Date.now();
    try {
      const lavagna = lavagnaOra();
      const s = await chiedi(`/api/agenti-attivita?lavagna=${encodeURIComponent(lavagna)}`);
      stat.letture++;
      if (s && s.ora_ts) offset = s.ora_ts - Date.now() / 1000;
      const prima = (sommario && sommario.agenti) || {};
      const ora = (s && s.agenti) || {};
      const da = new Set();
      for (const [k, x] of Object.entries(ora)) {
        if (ignota(k)) continue;
        const p = prima[k];
        if (primo ? (x.in_corso > 0 || adesso() - (x.ultima_ts || 0) < 60)
          : (!p || p.ultima_ts !== x.ultima_ts || p.in_corso !== x.in_corso || p.ricevute !== x.ricevute
             || p.inviate !== x.inviate || p.errori_24h !== x.errori_24h)) da.add(k);
      }
      // 2026-10-05 (prova dal vivo sul sito): chi il server dà «in corso» ma qui non ha una richiesta aperta si
      // legge sempre, anche se i contatori non sono cambiati (pagina aperta mentre l'agente lavora già, primo
      // giro andato a vuoto, flusso perso): lo stato «al lavoro» si disegna anche senza aver visto il «partito»
      const aperteQui = new Set([...REQ.values()].filter(aperta).map((r) => r.a));
      for (const [k, x] of Object.entries(ora)) if (!ignota(k) && x.in_corso > 0 && !aperteQui.has(k)) da.add(k);
      // un «partito» non cambia i contatori: chi ha richieste aperte si rilegge sempre
      for (const r of REQ.values()) if (aperta(r)) { if (!ignota(r.a)) da.add(r.a); else if (!ignota(r.da)) da.add(r.da); }
      sommario = s;
      const chiavi = [...da].slice(0, MAX_AGENTI_GIRO);
      const risposte = await Promise.all(chiavi.map((k) =>
        chiedi(`/api/agente-attivita?agente=${encodeURIComponent(k)}&lavagna=${encodeURIComponent(lavagna)}&limite=40`).catch(() => null)));
      const visteOra = new Set();
      risposte.forEach((d, i) => {
        if (!d || !Array.isArray(d.righe)) return;
        const k = chiavi[i];
        const durate = d.righe.filter((r) => r.verso === "ricevuta" && r.stato === "finito" && r.durata_s > 0)
          .sort((x, y) => (y.fine || 0) - (x.fine || 0)).slice(0, 20).map((r) => r.durata_s);
        DURATE.set(k, durate);
        for (const r of d.righe) { if (!visteOra.has(r.id)) { visteOra.add(r.id); unisci(r, primo || nascosta); } }
      });
      if (da.size > MAX_AGENTI_GIRO) ancora = true;
      primo = nascosta;          // tornata visibile: di nuovo lo stato, non la storia
      pota();
      disegna();
    } catch (e) {
      stat.errori++;
    } finally {
      inVolo = false;
      if (ancora) { ancora = false; chiediGiro(); }
    }
  }

  // una riga nuova o cambiata: quello che è successo negli ultimi 20 s si anima
  function unisci(r, silenzioso) {
    const vecchia = REQ.get(r.id);
    const riga = { id: r.id, da: r.da, a: r.a, testo: r.testo || "", stato: r.stato, inizio: r.inizio, partito: r.partito,
                   fine: r.fine, durata_s: r.durata_s, errore: r.errore || "", senza_risposta: !!r.senza_risposta,
                   visto: vecchia ? vecchia.visto : adesso() };
    REQ.set(r.id, riga);
    if (silenzioso) return;
    const t = adesso();
    const recente = (ts) => ts && t - ts < RECENTE_S;
    const era = vecchia ? vecchia.stato : null;
    const nuova = !vecchia;
    if (nuova && recente(r.inizio)) mandata(riga);
    if (r.stato === "finito" && era !== "finito" && recente(r.fine)) setTimeout(() => risposta(riga), nuova && recente(r.inizio) ? IMPULSO_MS : 0);
    if (r.stato === "errore" && era !== "errore" && recente(r.fine)) setTimeout(() => sveglia(), 0);
  }

  function pota() {
    const t = adesso();
    for (const [id, r] of REQ) {
      if (aperta(r)) continue;
      if (t - (r.fine || r.inizio || 0) > 600 && t - r.visto > 600) REQ.delete(id);
    }
    if (REQ.size > 400) for (const id of [...REQ.keys()].slice(0, REQ.size - 400)) REQ.delete(id);
  }

  // ---------------------------------------------------------------- dove stanno nodi e fili
  function nodoDiChiave(k) {
    if (ignota(k)) return null;
    const x = String(k).toLowerCase();
    let d = null;
    if (x !== "jarvis" && x !== "utente") d = document.querySelector(`#lav-mondo .nodo[data-agente="${CSS.escape(k)}"]`);
    if (!d) d = schedaApp(k);
    return d && d.isConnected && d.dataset.id ? d : null;
  }
  const rett = (d) => { const x = d.offsetLeft, y = d.offsetTop, w = d.offsetWidth, h = d.offsetHeight; return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 }; };
  function filoFra(idA, idB) {
    const dritto = document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(idA)}"][data-a="${CSS.escape(idB)}"]`);
    if (dritto) return { p: dritto, rovescio: false };
    const r = document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(idB)}"][data-a="${CSS.escape(idA)}"]`);
    return r ? { p: r, rovescio: true } : null;
  }
  // i passi (fino a 5 fili) fra due schede, come accendiPercorso() di app.js; null se non si arriva
  function percorso(idA, idB) {
    const uno = filoFra(idA, idB);
    if (uno) return [uno];
    const vicini = new Map();
    for (const f of fili()) {
      if (!vicini.has(f.da)) vicini.set(f.da, []);
      if (!vicini.has(f.a)) vicini.set(f.a, []);
      vicini.get(f.da).push(f.a); vicini.get(f.a).push(f.da);
    }
    const prima = new Map([[idA, null]]), coda = [idA];
    while (coda.length && !prima.has(idB)) {
      const x = coda.shift();
      for (const y of vicini.get(x) || []) if (!prima.has(y)) { prima.set(y, x); coda.push(y); }
    }
    if (!prima.has(idB)) return null;
    const passi = [];
    for (let y = idB; prima.get(y) != null; y = prima.get(y)) passi.unshift([prima.get(y), y]);
    if (passi.length > 5) return null;
    const out = passi.map(([a, b]) => filoFra(a, b));
    return out.every(Boolean) ? out : null;
  }
  // le schede che stanno in mezzo fra due (cartella del progetto, capogruppo): id, senza i due estremi
  function inMezzo(idA, idB) {
    const p = percorso(idA, idB);
    if (!p) return [];
    const ids = new Set();
    for (const { p: path } of p) { ids.add(path.dataset.da); ids.add(path.dataset.a); }
    ids.delete(idA); ids.delete(idB);
    return [...ids];
  }
  const GRUPPO = new Set();
  // il filo provvisorio (nessun collegamento sulla lavagna): la stessa curva dei fili veri
  function curvaTra(A, B) {
    const ra = rett(A), rb = rett(B);
    return curvaApp(ra, rb) || `M${ra.cx},${ra.cy} L${rb.cx},${rb.cy}`;
  }
  // i tratti da A a B: [{d, rovescio}], lungo i fili veri o con una curva provvisoria (temp: true)
  function tratti(A, B) {
    const p = percorso(A.dataset.id, B.dataset.id);
    if (p) {
      // il verso di ogni tratto: dal nodo di partenza a quello di arrivo
      let da = A.dataset.id;
      return p.map(({ p: path }) => {
        const rovescio = path.dataset.da !== da;
        da = rovescio ? path.dataset.da : path.dataset.a;
        return { d: path.getAttribute("d"), rovescio };
      });
    }
    return [{ d: curvaTra(A, B), rovescio: false, temp: true }];
  }

  // ---------------------------------------------------------------- lo strato sopra la lavagna
  let strato = null, testi = null;
  function strati() {
    const mondo = document.getElementById("lav-mondo");
    if (!mondo) return false;
    if (!strato || !strato.isConnected) {
      strato = document.createElementNS(SVGNS, "svg");
      strato.setAttribute("class", "dv-strato");
      strato.setAttribute("aria-hidden", "true");
      const fili_ = document.getElementById("lav-fili");
      if (fili_ && fili_.parentNode === mondo) fili_.after(strato); else mondo.prepend(strato);
    }
    if (!testi || !testi.isConnected) {
      testi = document.createElement("div");
      testi.className = "dv-testi";
      testi.setAttribute("aria-hidden", "true");
      mondo.append(testi);
    }
    return true;
  }
  function pathSvg(d, classe) {
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", d);
    p.setAttribute("pathLength", "100");
    p.setAttribute("class", classe);
    return p;
  }
  function etichetta(x, y, testo, classe) {
    const e = document.createElement("div");
    e.className = "dv-etichetta " + (classe || "");
    e.style.left = x + "px"; e.style.top = y + "px";
    e.textContent = testo;
    testi.append(e);
    return e;
  }
  function apri(nodo) {
    if (!nodo) return;
    nodo.classList.remove("dv-apre");
    void nodo.offsetWidth;                   // l'animazione riparte anche se era appena finita
    nodo.classList.add("dv-apre");
    setTimeout(() => nodo.classList.remove("dv-apre"), 900);
  }
  // un impulso che corre lungo i tratti, uno dopo l'altro; poi via
  function impulso(lista, classe) {
    if (!lista.length) return;
    const passo = Math.max(320, IMPULSO_MS / lista.length);
    lista.forEach((t, i) => {
      const p = pathSvg(t.d, "dv-impulso " + classe + (t.rovescio ? " dv-rovescio" : "") + (t.temp ? " dv-temp" : ""));
      p.style.animationDuration = passo + "ms";
      p.style.animationDelay = (i * passo) + "ms";
      strato.append(p);
      setTimeout(() => p.remove(), i * passo + passo + 500);
    });
  }
  function puntoMezzo(d) {
    try {
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("d", d);
      strato.append(p);
      const n = p.getTotalLength(), q = p.getPointAtLength(n / 2);
      p.remove();
      return q;
    } catch (e) { return null; }
  }

  // A manda a B
  function mandata(r) {
    if (demo() || !strati()) return;
    const A = nodoDiChiave(r.da), B = nodoDiChiave(r.a);
    apri(A);
    if (A && B && A !== B) {
      const lista = tratti(A, B);
      impulso(lista, "dv-andata");
      const q = puntoMezzo(lista[0].d);
      if (q && r.testo) {
        const e = etichetta(q.x, q.y, corto(r.testo, 48), "dv-andata");
        setTimeout(() => e.remove(), 3800);
      }
    } else if (A && ignota(r.a)) {          // senza destinatario: lo dice accanto a chi l'ha mandata
      const ra = rett(A);
      const chi = String(r.a || "?").replace(/^\?:/, "");
      const e = etichetta(ra.cx, ra.y, `→ ${chi}? nessuna scheda · ${corto(r.testo, 36)}`, "dv-senza");
      setTimeout(() => e.remove(), TIENI_SENZA_S * 1000);
    }
    sveglia();
  }
  // C risponde: l'impulso torna verso chi aveva chiesto
  function risposta(r) {
    if (demo() || !strati()) return;
    const A = nodoDiChiave(r.da), B = nodoDiChiave(r.a);
    if (A && B && A !== B) impulso(tratti(B, A), "dv-ritorno");
    if (B) { B.classList.remove("dv-lampo"); void B.offsetWidth; B.classList.add("dv-lampo"); setTimeout(() => B.classList.remove("dv-lampo"), 1200); }
    sveglia();
  }

  // ---------------------------------------------------------------- lo stato di ogni Dot, ogni secondo
  function mediana(v) {
    if (!v || v.length < MIN_DURATE) return null;
    const s = [...v].sort((a, b) => a - b), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  const durataTesto = (s) => s < 60 ? `da ${Math.max(0, Math.round(s))} s` : s < 3600 ? `da ${Math.floor(s / 60)} min` : `da ${Math.floor(s / 3600)} h`;

  function statiAgenti(t) {
    const out = new Map();     // chiave -> {lavora: inizio, n, ok, errore, testo}
    const di = (k) => { let x = out.get(k); if (!x) out.set(k, x = { lavora: null, n: 0, ok: false, errore: "" }); return x; };
    for (const r of REQ.values()) {
      if (aperta(r) && !ignota(r.a)) {
        const x = di(r.a), da = r.partito || r.inizio || t;
        x.lavora = x.lavora == null ? da : Math.min(x.lavora, da);
        x.n++;
      } else if (r.stato === "finito" && t - (r.fine || 0) < TIENI_OK_S && !ignota(r.a)) di(r.a).ok = true;
      else if (r.stato === "errore" && t - (r.fine || 0) < TIENI_ERR_S) {
        const k = !ignota(r.a) ? r.a : r.da;
        if (!ignota(k)) di(k).errore = r.errore || "errore";
      }
    }
    return out;
  }
  // i fili che restano accesi: aperte (blu tenue), finite da poco (verde), errori (rosso, spezzato)
  function filiAccesi(t) {
    const out = [];
    for (const r of REQ.values()) {
      if (ignota(r.da) || ignota(r.a) || r.da === r.a) continue;
      let tipo = null;
      if (aperta(r)) tipo = "dv-aperto";
      else if (r.stato === "finito" && t - (r.fine || 0) < TIENI_OK_S) tipo = "dv-fatto";
      else if (r.stato === "errore" && t - (r.fine || 0) < TIENI_ERR_S) tipo = "dv-rotto";
      if (tipo) out.push({ r, tipo });
    }
    return out;
  }

  const SEGNATI = new Set();     // nodi con classi o segno nostri
  function segno(nodo) {
    let s = nodo.querySelector(":scope > .dv-segno");
    if (s) return s;
    s = document.createElement("span");
    s.className = "dv-segno";
    s.setAttribute("aria-hidden", "true");
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 36 36");
    svg.setAttribute("class", "dv-anello");
    const fondo = document.createElementNS(SVGNS, "circle");
    fondo.setAttribute("class", "dv-anello-fondo");
    const pieno = document.createElementNS(SVGNS, "circle");
    pieno.setAttribute("class", "dv-anello-pieno");
    pieno.setAttribute("pathLength", "100");
    for (const c of [fondo, pieno]) { c.setAttribute("cx", "18"); c.setAttribute("cy", "18"); c.setAttribute("r", "16"); }
    svg.append(fondo, pieno);
    s.append(svg);
    // sopra il Dot (o l'avatar); una nota senza avatar: l'angolo in alto a sinistra
    const av = nodo.querySelector(":scope > .avatar, :scope > .dot-extra, :scope .dot-extra");
    if (av && av.offsetWidth) {
      const r = av.getBoundingClientRect(), rn = nodo.getBoundingClientRect(), z = rn.width / (nodo.offsetWidth || rn.width) || 1;
      const lato = r.width / z + 10;
      Object.assign(s.style, { left: ((r.left - rn.left) / z - 5) + "px", top: ((r.top - rn.top) / z - 5) + "px", width: lato + "px", height: lato + "px" });
    } else s.classList.add("dv-angolo");
    nodo.append(s);
    return s;
  }
  function togliSegni(nodo) {
    nodo.classList.remove("dv-lavora", "dv-ok", "dv-errore", "dv-percento", "dv-oltre");
    const s = nodo.querySelector(":scope > .dv-segno");
    if (s) s.remove();
  }

  const FILI_NOSTRI = new Map();   // chiave id|tipo -> [path]
  let timer = null;
  function disegna() {
    const t0 = performance.now();
    try { disegnaDavvero(); } catch (e) { stat.errori++; }
    const ms = performance.now() - t0;
    stat.disegni++; stat.ms_ultimo = ms; stat.ms_totale += ms;
  }
  function disegnaDavvero() {
    const t = adesso();
    const stati = demo() ? new Map() : statiAgenti(t);
    const vivi = new Set();
    for (const [k, x] of stati) {
      const nodo = nodoDiChiave(k);
      if (!nodo) continue;
      vivi.add(nodo);
      SEGNATI.add(nodo);
      const s = segno(nodo);
      const lavora = x.lavora != null;
      nodo.classList.toggle("dv-lavora", lavora && !x.errore);
      nodo.classList.toggle("dv-errore", !!x.errore);
      nodo.classList.toggle("dv-ok", x.ok && !lavora && !x.errore);
      if (lavora) {
        const passati = Math.max(0, t - x.lavora);
        const med = mediana(DURATE.get(k));
        nodo.classList.toggle("dv-percento", med != null);
        nodo.classList.toggle("dv-oltre", med != null && passati > med);
        if (med != null) s.style.setProperty("--dv-pieno", String(Math.min(97, Math.max(3, Math.round(passati / med * 100)))));
        const tx = durataTesto(passati) + (x.n > 1 ? ` · ${x.n}` : "");
        if (s.dataset.t !== tx) s.dataset.t = tx;
      } else {
        nodo.classList.remove("dv-percento", "dv-oltre");
        if (s.dataset.t) delete s.dataset.t;
      }
    }
    for (const n of [...SEGNATI]) if (!vivi.has(n)) { togliSegni(n); SEGNATI.delete(n); }
    // 2026-10-05 (lavagna viva): il gruppo si accende con i suoi agenti. Le schede fra Jarvis e chi lavora
    // (la cartella 📁 del progetto e il suo capogruppo) prendono «dv-gruppo» finché c'è qualcuno al lavoro.
    const accesi = new Set();
    const J = nodoDiChiave("jarvis");
    for (const [k, x] of stati) {
      if (x.lavora == null) continue;
      const N = nodoDiChiave(k);
      if (!N || !J || N === J) continue;
      for (const id of inMezzo(J.dataset.id, N.dataset.id)) {
        const d = document.querySelector(`#lav-mondo .nodo[data-id="${CSS.escape(id)}"]`);
        if (d) accesi.add(d);
      }
    }
    for (const d of [...GRUPPO]) if (!accesi.has(d) || !d.isConnected) { d.classList.remove("dv-gruppo"); GRUPPO.delete(d); }
    for (const d of accesi) { d.classList.add("dv-gruppo"); GRUPPO.add(d); }
    // fili accesi
    const voglio = new Map();
    if (!demo() && strati()) {
      for (const { r, tipo } of filiAccesi(t)) {
        const A = nodoDiChiave(r.da), B = nodoDiChiave(r.a);
        if (!A || !B || A === B) continue;
        const lista = tipo === "dv-rotto" ? tratti(A, B).slice(-1) : tratti(A, B);
        voglio.set(r.id + "|" + tipo, { lista, tipo });
      }
    }
    for (const [k, paths] of FILI_NOSTRI) if (!voglio.has(k)) { paths.forEach((p) => p.remove()); FILI_NOSTRI.delete(k); }
    for (const [k, { lista, tipo }] of voglio) {
      let paths = FILI_NOSTRI.get(k);
      // 2026-10-05 (lavagna viva): sul filo di una richiesta aperta un Dot cammina avanti e indietro finché
      // l'agente non finisce (dv-viaggio), un tratto dopo l'altro da chi chiede a chi lavora
      const voci = lista.flatMap((x, i) => tipo === "dv-aperto"
        ? [{ d: x.d, cls: "dv-filo dv-aperto" + (x.temp ? " dv-temp" : "") },
           { d: x.d, cls: "dv-viaggio" + (x.rovescio ? " dv-rovescio" : ""), ritardo: i * 0.35 }]
        : [{ d: x.d, cls: "dv-filo " + tipo + (x.temp ? " dv-temp" : "") }]);
      if (!paths || paths.length !== voci.length || !paths.every((p) => p.isConnected)) {
        if (paths) paths.forEach((p) => p.remove());
        paths = voci.map((x) => {
          const p = pathSvg(x.d, x.cls);
          if (x.ritardo) p.style.animationDelay = x.ritardo + "s";
          strato.append(p);
          return p;
        });
        FILI_NOSTRI.set(k, paths);
      } else voci.forEach((x, i) => { if (paths[i].getAttribute("d") !== x.d) paths[i].setAttribute("d", x.d); });
    }
    // finché qualcosa è vivo, si ricontrolla ogni secondo (il tempo che passa, le scadenze dei ✓ e degli errori)
    const vivo = vivi.size > 0 || voglio.size > 0;
    if (vivo && !timer) timer = setInterval(disegna, 1000);
    else if (!vivo && timer) { clearInterval(timer); timer = null; }
  }
  function sveglia() { disegna(); }

  // ---------------------------------------------------------------- ridisegni della lavagna e flusso in tempo reale
  let mo = null, moMondo = null, moFili = null, inCoda = false;
  function guardaLavagna() {
    const mondo = document.getElementById("lav-mondo"), fili_ = document.getElementById("lav-fili");
    if (!mondo || (moMondo === mondo && moFili === fili_)) return;
    if (mo) mo.disconnect();
    mo = new MutationObserver(() => {
      if (inCoda || (!SEGNATI.size && !FILI_NOSTRI.size && !REQ.size)) return;
      inCoda = true;
      // anche con sole richieste in memoria (REQ): il primo disegno può arrivare prima delle schede della lavagna
      queueMicrotask(() => { inCoda = false; if (SEGNATI.size || FILI_NOSTRI.size || timer || REQ.size) disegna(); });
    });
    mo.observe(mondo, { childList: true });
    if (fili_) mo.observe(fili_, { childList: true });
    moMondo = mondo; moFili = fili_;
  }

  let esAgganciato = null, esMio = null;
  function alMessaggio(ev) {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d && Array.isArray(d.chiavi) && d.chiavi.includes("attivita")) chiediGiro();
  }
  function agganciaFlusso() {
    const F = flussoApp();
    if (F) {
      if (F.es && F.es !== esAgganciato) {
        esAgganciato = F.es;
        F.es.addEventListener("message", alMessaggio);
        chiediGiro();                       // ricollegato: si riallinea
      }
      return;
    }
    if (esMio || !window.EventSource) return;        // app.js senza flusso: uno nostro
    try {
      esMio = new EventSource("/api/flusso?token=" + encodeURIComponent(window.CC_TOKEN || ""));
      esMio.addEventListener("message", alMessaggio);
      esMio.onerror = () => { try { esMio.close(); } catch (e) { /* già chiuso */ } esMio = null; };
    } catch (e) { esMio = null; }
  }

  // 2026-10-05 (prova sul sito, dentro il ponte): l'avvio non dipende dall'ordine degli eventi né dalla
  // visibilità. Ogni pezzo è protetto (uno che si rompe non ferma gli altri), il primo giro si ripete a tempo
  // (il ponte può far aspettare api() fino a 4 s) e un giro ogni 5 s c'è sempre: il flusso è solo un acceleratore.
  const prova_ = (fn) => { try { fn(); } catch (e) { stat.errori++; } };
  function parti() {
    prova_(guardaLavagna);
    prova_(agganciaFlusso);
    prova_(() => chiediGiro(true));
    for (const ms of [1500, 4500, 9000]) setTimeout(() => prova_(() => chiediGiro(true)), ms);
    setInterval(() => { prova_(guardaLavagna); prova_(agganciaFlusso); }, 3000);
    let conta = 0;
    setInterval(() => prova_(() => {
      conta++;
      // nascosta: ogni 15 s; visibile: ogni 5 s (e un disegno, che fa scadere ✓ ed errori)
      if (document.hidden && conta % 3) return;
      chiediGiro();
    }), 5000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { primo = true; chiediGiro(true); } });
  }

  window.CCDottiVivi = {
    stat, REQ,
    // per le prove: lo stesso giro che parte da un evento del flusso
    giro: () => chiediGiro(true),
    disegna,
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", parti, { once: true });
  else parti();
})();
