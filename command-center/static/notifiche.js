// notifiche.js · le schede «Jarvis» e «Postino» in testa alla chat (2026-10-05, programmatore-postino)
// e, dal 2026-10-05 15:20 (l'utente), la terza scheda «Voce»: la chat a voce, aperta e chiusa da voce-chat.js (CCVoceChat)
//
// Storia: la mattina del 05/10/2026 (commit efc574e) le notifiche stavano in un pannello laterale «Notifiche» con
// bolle ridotte e la risposta la dava Jarvis. L'utente, 05/10/2026 13:20: «dentro la chat ci deve essere la chat Jarvis
// e la chat Postino. E lì devo avere la stessa chat identica per il postino, in modo che comunico con il postino,
// con tutti i report che tu mi mandi, mentre con Jarvis continuo a lavorare come sempre.»
//
// Ora la chat Postino è un interlocutore di app.js (chatCon = "postino"): stesse bolle, markdown, allegati,
// dettato, Dots, stop, cronologia. app.js la disegna unendo il filo «postino» e le notifiche del filo
// «notifiche-jarvis» (FILI_UNITI) in ordine di tempo; ci risponde l'agente postino (server.py, chiedi).
// Da dove arrivano i report: strumenti/notifica.py → POST /api/notifica → fili.py; fili.js li porta in THREADS.
// Questo file:
//  - crea THREADS["notifiche-jarvis"] e THREADS["postino"] se mancano (fili.js li riempie dal server);
//  - le due schede in testa alla pagina Chat: «Jarvis» (l'ultima chat di lavoro: Jarvis o l'agente scelto) e
//    «Postino» con il numero dei non letti; lo stesso numero sulla voce «Chat» della barra;
//  - arricchisci(): il titolo del report e le bozze del Postino apribili dentro la bolla di app.js
//    (▸ Bozza 1, con «Scrivi “invia la 1”» che prepara il testo nella casella: non spedisce);
//  - i non letti: localStorage cc.notifiche-viste (gli id già visti per filo), come prima;
//  - ?filo=postino nell'indirizzo apre la chat Postino, ?filo=notifiche-jarvis la chat di Jarvis: lo usa la notifica
//    del telefono (NotificheWorker dell'app).
// 2026-10-05 15:05 (l'utente: «non intasare il Postino»): ogni notifica ha una classe (fili.py, classifica): «report» nella
// chat Postino, «avviso» nella chat di Jarvis. I non letti si contano per classe: il numero sulla scheda Postino sono
// i report non visti, quello sulla scheda Jarvis gli avvisi non visti; la voce «Chat» li somma.
(function () {
  "use strict";
  if (typeof THREADS !== "object" || !THREADS) return;

  const CHIAVI = ["postino", "notifiche-jarvis"];              // i fili che finiscono nella chat Postino
  const POSTINO = "postino";
  window.FILI_SPECIALI = { "notifiche-jarvis": { nome: "Jarvis", mittente: "Jarvis" }, postino: { nome: "Postino", mittente: "Postino" } };
  const g = (fn, d) => { try { const v = fn(); return v === undefined ? d : v; } catch (e) { return d; } };
  const leggi = (k, d) => { try { const v = localStorage.getItem("cc." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  const scrivi = (k, v) => { try { localStorage.setItem("cc." + k, JSON.stringify(v)); } catch (e) { /* niente */ } };
  const mk = (tag, attr, ...figli) => {
    const n = document.createElement(tag);
    for (const [a, v] of Object.entries(attr || {})) {
      if (a.startsWith("on") && typeof v === "function") n.addEventListener(a.slice(2), v);
      else if (v != null && v !== false) n.setAttribute(a, v === true ? "" : String(v));
    }
    for (const f of figli) if (f != null && f !== "") n.append(f instanceof Node ? f : String(f));
    return n;
  };
  const nuovoId = () => g(() => uuid(), null) || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));   // eslint-disable-line no-undef
  for (const k of CHIAVI) if (!THREADS[k]) THREADS[k] = { sessione: nuovoId(), avviata: false, messaggi: [] };
  const chatAttuale = () => g(() => chatCon, "jarvis");                                            // eslint-disable-line no-undef
  const sezioneChat = () => document.querySelector('section[data-vista="chat"]');

  // ---------------------------------------------------------------- non letti
  const VISTE = leggi("notifiche-viste", {});
  // la classe di una notifica: quella del server, altrimenti report nel filo del Postino e avviso altrove (= app.js)
  const classeDi = (m, k) => g(() => window.classeNotifica(m, k), null) ||
    (m.classe === "report" || m.classe === "avviso" ? m.classe : k === POSTINO ? "report" : "avviso");
  const notificheDi = (k, classe) => ((THREADS[k] && THREADS[k].messaggi) || [])
    .filter((m) => m && m.notifica && m.fid && (!classe || classeDi(m, k) === classe));
  const nonLette = (k, classe) => { const v = new Set(VISTE[k] || []); return notificheDi(k, classe).filter((m) => !v.has(m.fid)).length; };
  const nonLetteClasse = (classe) => CHIAVI.reduce((s, k) => s + nonLette(k, classe), 0);
  const totale = () => nonLetteClasse("report") + nonLetteClasse("avviso");
  // letta = la chat della sua classe è quella aperta, la pagina Chat si vede e la scheda del browser è davanti
  // 2026-10-05: con la scheda «Voce» aperta (voce-chat.js) le chat Jarvis e Postino non si vedono
  const voceAperta = () => !!g(() => window.CCVoceChat.attiva(), false);
  const chatVisibile = () => !document.hidden && !voceAperta() && !!g(() => sezioneChat().offsetParent, null);
  const postinoAVista = () => chatAttuale() === POSTINO && chatVisibile();
  const jarvisAVista = () => chatAttuale() === "jarvis" && chatVisibile();
  function segnaLette(classe) {
    let cambiato = false;
    for (const k of CHIAVI) {
      const ids = notificheDi(k, classe).map((m) => m.fid), prima = new Set(VISTE[k] || []);
      if (ids.every((id) => prima.has(id))) continue;
      VISTE[k] = [...new Set([...(VISTE[k] || []), ...ids])].slice(-300);
      cambiato = true;
    }
    if (cambiato) scrivi("notifiche-viste", VISTE);
  }

  // ---------------------------------------------------------------- avatar
  function avatarDi(k) {
    if (k === POSTINO) {
      const a = g(() => window.avatar({ key: "casa:postino", nome: "Postino" }, "avatar mini"), null);
      return a || mk("span", { class: "avatar mini", style: "--c:#d08770", "aria-hidden": "true" }, "P");
    }
    if (k === "voce") {
      const n = mk("span", { class: "avatar mini avatar-voce", style: "--c:#a3be8c", "aria-hidden": "true" });
      // il microfono costruito con createElementNS: niente markup scritto a testo nella pagina
      const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
      for (const [k2, v] of [["viewBox", "0 0 24 24"], ["width", "14"], ["height", "14"], ["fill", "none"],
                              ["stroke", "currentColor"], ["stroke-width", "2"], ["stroke-linecap", "round"]]) svg.setAttribute(k2, v);
      const rect = document.createElementNS(NS, "rect");
      for (const [k2, v] of [["x", "9"], ["y", "3"], ["width", "6"], ["height", "11"], ["rx", "3"]]) rect.setAttribute(k2, v);
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", "M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21");
      svg.append(rect, path);
      n.appendChild(svg);
      return n;
    }
    return mk("span", { class: "avatar mini avatar-j", style: "--c:#f0f0f0", "aria-hidden": "true" }, "J");
  }

  // ---------------------------------------------------------------- schede in testa alla chat
  let SCHEDE = null;
  function costruisci() {
    if (SCHEDE) return true;
    const sez = sezioneChat(), testa = sez && sez.querySelector(".chat-testa");
    if (!sez || !testa) return false;
    SCHEDE = mk("div", { class: "chat-schede", role: "tablist", "aria-label": "Con chi parli" });
    SCHEDE.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-scheda]");
      if (!b) return;
      if (b.dataset.scheda === "voce") { g(() => window.CCVoceChat.apri(), null); poi(); return; }
      g(() => window.CCVoceChat.chiudi(), null);
      if (b.dataset.scheda === POSTINO) apri(POSTINO);
      else g(() => apriChat(leggi("chatLavoro", "jarvis")), null);                                 // eslint-disable-line no-undef
    });
    sez.insertBefore(SCHEDE, testa);
    return true;
  }
  function disegna() {
    if (!costruisci()) return;
    if (postinoAVista()) segnaLette("report");
    if (jarvisAVista()) segnaLette("avviso");
    const suVoce = voceAperta();
    const nReport = nonLetteClasse("report"), nAvvisi = nonLetteClasse("avviso"), suPostino = !suVoce && chatAttuale() === POSTINO;
    const lavoro = leggi("chatLavoro", "jarvis");
    const nomeLavoro = g(() => nomeDi(AGENTI.get(lavoro)), "Jarvis");                             // eslint-disable-line no-undef
    const scheda = (k, attiva, nome, faccia, conta) => mk("button", { type: "button", role: "tab", "data-scheda": k,
      class: "chat-scheda" + (attiva ? " attiva" : ""), "aria-selected": String(attiva),
      title: k === POSTINO ? "La chat del Postino: report, briefing, routine e posta, e le tue risposte"
        : k === "voce" ? "La chat a voce: la stessa conversazione della voce di Jarvis (widget, Cmd destro, telefono)"
        : "La chat di lavoro di sempre, con gli avvisi e gli avanzamenti di Jarvis" },
    faccia, mk("span", { class: "nome" }, nome),
    conta ? mk("span", { class: "conta", "aria-label": `${conta} non letti` }, conta > 99 ? "99+" : String(conta)) : "");
    SCHEDE.replaceChildren(
      scheda("lavoro", !suPostino && !suVoce, nomeLavoro, g(() => lavoro === "jarvis" ? avatarDi("jarvis") : window.avatar(AGENTI.get(lavoro), "avatar mini"), avatarDi("jarvis")),   // eslint-disable-line no-undef
        nAvvisi),
      scheda(POSTINO, suPostino, "Postino", avatarDi(POSTINO), nReport),
      g(() => document.getElementById("chat-voce"), null) ? scheda("voce", suVoce, "Voce", avatarDi("voce"), 0) : "");
    const voce = document.querySelector('a[data-vista="chat"]');
    if (voce) {
      let b = voce.querySelector(".conta-notifiche");
      if (!b) { b = mk("span", { class: "conta-notifiche", "aria-label": "notifiche non lette" }); voce.append(b); }
      const visti = nReport + nAvvisi;
      b.hidden = !visti;
      b.textContent = visti > 99 ? "99+" : String(visti);
    }
    window.CCNotifiche.nonLette = totale();
  }
  let inCoda = false;
  function poi() {
    if (inCoda) return;
    inCoda = true;
    requestAnimationFrame(() => { inCoda = false; disegna(); });
  }
  function apri(k) {
    g(() => window.CCVoceChat.chiudi(), null);
    if (!/^#chat\b/.test(location.hash || "")) location.hash = "#chat";
    g(() => apriChat(k === "notifiche-jarvis" ? "jarvis" : k), null);                              // eslint-disable-line no-undef
    poi();
  }

  // ---------------------------------------------------------------- dentro la bolla di app.js
  const APERTE = new Set();
  function prepara(testo) {
    const c = document.getElementById("chiedi-testo");
    if (!c) return;
    c.value = testo;
    g(() => autoAltezza(), null);                                                                  // eslint-disable-line no-undef
    c.focus();
    c.setSelectionRange(testo.length, testo.length);
  }
  function arricchisci(testo, m) {
    if (m.titolo) testo.prepend(mk("div", { class: "notifica-titolo" }, m.titolo));
    const voci = m.dati && Array.isArray(m.dati.voci) ? m.dati.voci : [];
    for (const v of voci) {
      if (!v || typeof v !== "object" || !v.bozza || typeof v.bozza !== "object") continue;
      const n = String(v.numero == null ? "" : v.numero), b = v.bozza, chiave = `${m.fid || ""}#${n}`;
      const det = mk("details", { class: "notifica-bozza", open: APERTE.has(chiave) },
        mk("summary", {}, `Bozza ${n}` + (b.destinatario ? ` · a ${b.destinatario}` : "")),
        mk("div", { class: "campi" },
          b.destinatario ? mk("div", {}, mk("b", {}, "A: "), String(b.destinatario)) : "",
          b.oggetto ? mk("div", {}, mk("b", {}, "Oggetto: "), String(b.oggetto)) : "",
          v.codice ? mk("div", {}, `casella·uid ${v.codice}`) : ""),
        mk("div", { class: "corpo-bozza" }, String(b.testo || "(testo non disponibile)")),
        mk("div", { class: "azioni-bozza" },
          mk("button", { type: "button", onclick: () => prepara(`invia la bozza ${n}`) }, `Scrivi «invia la ${n}»`),
          mk("button", { type: "button", onclick: () => prepara(`cambia la bozza ${n}: `) }, "Cambia"),
          mk("button", { type: "button", onclick: () => prepara(`cestina la ${n}`) }, "Cestina")));
      // la chat si ridisegna a ogni sincronia: una bozza aperta resta aperta
      det.addEventListener("toggle", () => { if (det.open) APERTE.add(chiave); else APERTE.delete(chiave); });
      testo.append(det);
    }
  }

  // ---------------------------------------------------------------- ganci
  const salvaOriginale = window.salvaFili;
  if (typeof salvaOriginale === "function") {
    window.salvaFili = function () { const r = salvaOriginale.apply(this, arguments); poi(); return r; };
  }
  document.addEventListener("cc:testa-chat", poi);
  window.addEventListener("hashchange", poi);
  document.addEventListener("visibilitychange", poi);

  window.CCNotifiche = { apri, arricchisci, nonLette: 0, conta: (k) => nonLette(k), speciali: CHIAVI };

  function avvio() {
    if (!costruisci()) return;
    let k = null;
    try { k = new URLSearchParams(location.search).get("filo"); } catch (e) { /* niente */ }
    if (k && CHIAVI.includes(k)) {
      apri(k);
      try {
        const u = new URL(location.href);
        u.searchParams.delete("filo");
        history.replaceState(history.state, "", u.pathname + (u.search || "") + (location.hash || "#chat"));
      } catch (e) { /* niente */ }
    } else if (chatAttuale() === POSTINO) g(() => { aggiornaTestaChat(); disegnaMessaggi(); }, null);   // eslint-disable-line no-undef
    disegna();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvio); else avvio();
})();
