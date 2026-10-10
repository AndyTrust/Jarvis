// L'aspetto uguale su ogni dispositivo (l'utente, 2026-10-04): tema colore e avatar (Dots, Volti, Iniziali) si scelgono una volta e valgono
// su computer e telefono. Prima stavano solo nel localStorage di ogni browser, quindi i due potevano essere diversi.
// Dati: GET/POST /api/aspetto (aspetto.py, anche dal sito: è solo l'aspetto). Si aggancia da solo a CCTemi (temi.js) e CCDots (dots.js):
//  - all'avvio e ogni 45 s a pagina visibile legge l'aspetto condiviso e, se è diverso da quello locale, lo applica;
//  - quando l'utente cambia tema o avatar (eventi «cc-tema» e «cc-avatar») lo salva sul server;
//  - se sul server non c'è ancora una scelta, la prima pagina che si apre la scrive (così tutti partono uguali).
// Se la rotta non risponde 200 non fa niente: l'aspetto resta quello del dispositivo.
(function aspetto() {
  "use strict";
  if (window.CCAspetto) return;
  let server = null, pronto = false, applicando = false, timerSalva = null, timerPoll = null;
  // «pronto» = la pagina ha già letto l'aspetto condiviso: prima di allora NON scrive niente (all'avvio temi.js e dots.js lanciano
  // eventi con i valori locali: se partissero verso il server, ogni pagina che si apre sovrascriverebbe la scelta degli altri dispositivi)
  const token = () => window.CC_TOKEN || "";
  async function chiama(metodo, corpo) {
    const r = await fetch("/api/aspetto", { method: metodo, cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "X-Token": token(), Accept: "application/json" }, corpo ? { "Content-Type": "application/json" } : {}),
      body: corpo ? JSON.stringify(corpo) : undefined });
    let d = null;
    try { d = await r.json(); } catch (e) { /* non JSON */ }
    return { stato: r.status, d: d && typeof d === "object" ? d : {} };
  }
  const locale = () => {
    const T = window.CCTemi, D = window.CCDots;
    if (!T || !D) return null;
    return { tema: T.tema(), avatar: D.modo(), fermi: !!D.fermi() };
  };
  function applica(a) {
    const T = window.CCTemi, D = window.CCDots, l = locale();
    if (!T || !D || !l) return;
    applicando = true;
    try {
      if (a.tema !== l.tema) T.scegli(a.tema);
      if (a.avatar !== l.avatar) D.scegli(a.avatar);
      if (a.fermi !== l.fermi) D.fermi(a.fermi);
    } catch (e) { /* un valore non valido non rompe la pagina */ }
    setTimeout(() => { applicando = false; }, 300);
  }
  async function leggi() {
    try {
      const r = await chiama("GET");
      if (r.stato !== 200) return;
      server = r.d;
      if (server.predefinito) { pronto = true; salva(); return; }   // nessuna scelta condivisa: la scrive questa pagina
      applica(server);
      setTimeout(() => { pronto = true; }, 1200);               // dopo gli eventi dell'applicazione (dots.js li manda in ritardo)
    } catch (e) { /* rete assente: resta l'aspetto del dispositivo */ }
  }
  function salva() {
    clearTimeout(timerSalva);
    timerSalva = setTimeout(async () => {
      const l = locale();
      if (!l || applicando || !pronto) return;
      if (server && !server.predefinito && l.tema === server.tema && l.avatar === server.avatar && l.fermi === server.fermi) return;
      try {
        const r = await chiama("POST", l);
        if (r.stato === 200) server = r.d;
      } catch (e) { /* riproverà alla prossima modifica */ }
    }, 500);
  }
  window.addEventListener("cc-tema", () => { if (!applicando && pronto) salva(); });
  window.addEventListener("cc-avatar", () => { if (!applicando && pronto) salva(); });
  function avvia() {
    let n = 0;
    const attesa = setInterval(() => {                        // CCTemi e CCDots partono con i loro script: si aspetta
      if (locale() || ++n > 30) { clearInterval(attesa); if (locale()) leggi(); }
    }, 200);
    clearInterval(timerPoll);
    timerPoll = setInterval(() => { if (!document.hidden && locale()) leggi(); }, 45000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && locale()) leggi(); });
  }
  window.CCAspetto = { leggi, salva, server: () => server };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia, { once: true }); else avvia();
})();
