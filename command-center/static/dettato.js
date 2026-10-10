// Il dettato del browser senza ripetizioni (l'utente, 2026-10-04): «Ascolta Ascolta ti Ascolta ti voglio…».
// Su Android, Chrome manda ogni ipotesi provvisoria come un NUOVO risultato, e la frase cresce («Ascolta», «Ascolta ti»,
// «Ascolta ti voglio»…): sommarli tutti, come faceva la pagina, ripete le stesse parole. Qui un risultato provvisorio che
// ricomincia dal testo del precedente provvisorio lo SOSTITUISCE; i risultati finali restano frasi separate.
// Uso: CCDettato.unisci(ev.results) -> { fissa, provv, testo }. Usato da ponte.js (microfono della chat) e chiamata.js.
(function (radice) {
  "use strict";
  function unisci(risultati) {
    const parti = [];                                         // { t: testo, fin: bool }
    const n = risultati ? risultati.length : 0;
    for (let i = 0; i < n; i++) {
      const r = risultati[i];
      const x = String((r && r[0] && r[0].transcript) || "").replace(/\s+/g, " ").trim();
      if (!x) continue;
      const fin = !!(r && r.isFinal);
      const ult = parti.length ? parti[parti.length - 1] : null;
      if (ult && !ult.fin) {
        const a = x.toLowerCase(), b = ult.t.toLowerCase();
        if (a.startsWith(b)) { ult.t = x; ult.fin = fin; continue; }     // la frase è cresciuta: sostituisce la precedente
        if (b.startsWith(a)) { if (fin) ult.fin = true; continue; }       // ripetizione più corta: niente di nuovo
      }
      parti.push({ t: x, fin });
    }
    const unisciTesti = (v) => v.map((p) => p.t).join(" ");
    return { fissa: unisciTesti(parti.filter((p) => p.fin)), provv: unisciTesti(parti.filter((p) => !p.fin)), testo: unisciTesti(parti) };
  }
  // Il dettato in un campo di testo (2026-10-05, l'utente: «gli stessi tasti della chat principale» anche nel riquadro
  // «Chat a voce»): un solo codice per il microfono della chat (ponte.js) e quello del riquadro (voce-chat.js).
  // avvia(campo, { onTesto(valore, u), onErrore(testo, codice), onFine() }) -> il riconoscitore acceso, o null.
  // Il testo va nel campo, non parte da solo. Riconoscitore: il dettato dell'app Android (CCRiconoscimentoNativo,
  // messo da ponte.js) o quello del browser.
  const ERRORI = {
    "not-allowed": "Il microfono è bloccato per questo sito: consentilo nelle impostazioni del browser (il lucchetto accanto all'indirizzo) e riprova.",
    "service-not-allowed": "Il dettato non è permesso in questo browser: usa il microfono della tastiera.",
    "audio-capture": "Nessun microfono trovato: usa il microfono della tastiera.",
    "no-speech": "Non ho sentito niente: tocca il microfono e riprova.",
    network: "Il dettato ha bisogno della rete: riprova quando la connessione torna.",
    "language-not-supported": "Il dettato in italiano non è disponibile su questo browser.",
  };
  function riconoscitore() {
    const w = radice;
    return (w.JarvisApp && w.CCRiconoscimentoNativo) || w.SpeechRecognition || w.webkitSpeechRecognition || null;
  }
  function avvia(campo, opz) {
    opz = opz || {};
    const R = riconoscitore();
    if (!R || !campo) return null;
    const r = new R();
    r.lang = "it-IT";
    r.interimResults = true;
    r.continuous = true;
    r.maxAlternatives = 1;
    const base = campo.value.trim() ? campo.value.replace(/\s*$/, " ") : "";
    // 2026-10-07 (l'utente): mentre detta il campo non cresce. Prima il testo provvisorio allungava la textarea e la
    // chat la faceva salire di ~115 px: il secondo tocco per fermare non trovava più il microfono. L'altezza resta
    // quella di partenza e il campo scorre fino all'ultima parola; a dettato finito torna libera.
    const alta = campo.tagName === "TEXTAREA" ? campo.offsetHeight : 0;
    const blocca = () => {
      if (!alta) return;
      campo.style.height = alta + "px";
      campo.scrollTop = campo.scrollHeight;
    };
    r.onresult = (ev) => {
      const u = unisci(ev.results);
      campo.value = (base + (u.fissa ? u.fissa + " " : "") + u.provv).replace(/\s+/g, " ").replace(/^\s/, "");
      if (opz.onTesto) opz.onTesto(campo.value, u);
      blocca();
    };
    r.onerror = (ev) => {
      const e = ev && ev.error;
      if (e !== "aborted" && opz.onErrore) opz.onErrore(ERRORI[e] || "Il dettato si è fermato: riprova.", e);
    };
    r.onend = () => { if (opz.onFine) opz.onFine(); };
    try {
      r.start();
    } catch (e) {
      if (opz.onErrore) opz.onErrore("Il dettato non è partito: riprova.", "start");
      return null;
    }
    return r;
  }
  const api = { unisci, avvia, riconoscitore, ERRORI };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else radice.CCDettato = api;
})(typeof window !== "undefined" ? window : globalThis);
