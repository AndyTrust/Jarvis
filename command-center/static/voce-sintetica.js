// La voce sintetica di Jarvis nel browser (MODIFICA LOCALE — l'utente, 2026-10-04).
// «Quando usiamo l'audio di Jarvis deve essere sintetico: non deve dire le stringhe di comando.»
//
// Stessa logica di backtalk/backtalk/sintesi_voce.py (per_la_voce): toglie codice, comandi di shell,
// percorsi, URL, IP, hash, JSON, tabelle, markdown, emoji e le frasi che raccontano solo l'esecuzione;
// poi tiene al massimo 2 frasi o circa 220 caratteri, l'esito per primo, e aggiunge «Il resto è nella
// chat.» solo quando c'è altro da leggere. Non inventa niente: toglie e accorcia.
//
// Aggancio: avvolge speechSynthesis.speak (sul prototipo), così chiamata.js e ponte.js restano come
// sono e cambia SOLO il parlato: il testo in chat e i messaggi non si toccano.
// Prove: node command-center/prove/prova_voce_sintetica.js (se presente) o window.CCVoceSintetica.perLaVoce.
(function voceSintetica(radice) {
  "use strict";
  const MAX_CARATTERI = 220, MAX_FRASI = 2;
  const CODA_RESTO = "Il resto è nella chat.";
  const NIENTE_DA_DIRE = "Fatto, i dettagli sono nella chat.";
  const X = "\u0000";                 // segno di «qui c'era qualcosa che si è tolto»
  const B = "(?<![\\p{L}\\p{N}_])", E = "(?![\\p{L}\\p{N}_])";   // \b che capisce le lettere accentate
  const W = (corpo, f = "iu") => new RegExp(B + "(?:" + corpo + ")" + E, f);

  const COMANDI = new Set(("$ #! ssh scp rsync git gh python python3 pip pip3 uv curl wget docker docker-compose " +
    "systemctl journalctl sudo cd ls cat head tail grep rg find sed awk echo export source chmod chown mkdir rm mv " +
    "cp touch kill pkill killall ps top brew npm npx node yarn pnpm launchctl rclone adb fastboot vercel open " +
    "osascript defaults crontab tmux screen make cargo go java gradle ./gradlew bash sh zsh env lsof netstat ping " +
    "dig nslookup tar unzip zip ffmpeg say pm2 caddy nginx psql mysql sqlite3 kubectl terraform jq xargs nohup " +
    "which whoami df du uname date diff patch less more vim nano code codegraph graphify notebooklm").split(" "));
  const AMBIGUI = new Set(("date open make code more less top say go find which source patch diff env screen kill " +
    "touch head tail export java node ping zip").split(" "));

  const NARRAZIONE = new RegExp("^\\s*(?:(?:ok|bene|allora|ora|adesso|intanto|poi|prima|quindi|perfetto)[,!.]?\\s+)*(?:" +
    "(?:lancio|rilancio|eseguo|avvio|faccio\\s+partire|apro|leggo|rileggo|controllo|ricontrollo|verifico|cerco|guardo|" +
    "provo|riprovo|scrivo|modifico|aggiorno|installo|scarico|copio|sposto|riavvio|passo\\s+a|vado\\s+a|mi\\s+collego|uso|" +
    "interrogo|chiedo|confronto|analizzo|esamino|preparo|creo|aggiungo|sistemo|correggo|ricarico|compilo|testo|" +
    "do\\s+un'?occhiata|dò\\s+un'?occhiata|faccio\\s+un\\s+(?:controllo|giro|tentativo|test))" + E +
    "|(?:sto|stiamo)\\s+\\p{L}+(?:ando|endo)" + E +
    "|(?:ora|adesso)\\s+(?:provo|vedo|guardo|controllo)" + E +
    "|un\\s+(?:momento|attimo|secondo)" + E +
    "|let\\s+me" + E + "|let's" + E + "|i'll\\s+(?:run|check|look|read|open|try|grab|search|start|use|fetch|write|edit|update)" + E +
    "|i'm\\s+(?:going\\s+to|now\\s+)?\\p{L}+ing" + E +
    "|(?:now\\s+)?(?:running|checking|reading|looking|opening|searching|fetching|writing|editing|trying|grabbing|loading)" + E +
    "|one\\s+(?:moment|sec(?:ond)?)" + E + ")", "iu");
  const ESITO = W("fatto|fatta|fatti|ok|okay|pronto|pronta|pronti|finito|finita|completat[oaie]|riuscit[oaie]|" +
    "funziona(?:no)?|risolt[oaie]|sistemat[oaie]|salvat[oaie]|aggiornat[oaie]|attiv[oaie]|acces[oaie]|spent[oaie]|" +
    "partit[oaie]|chius[oaie]|a\\s+posto|tutto\\s+bene|verde|ross[oaie]|errore|errori|fallit[oaie]|fallisce|" +
    "non\\s+riesco|non\\s+(?:funziona|va|parte)|bloccat[oaie]|manca|mancano|trovat[oaie]|esito|risultato|sì|no|done|" +
    "ready|fixed|finished|failed|error|works|working|passed|success(?:ful)?|all\\s+set|broken");
  const PROSSIMO_P = W("serve|servono|ti\\s+serve|devi|dovresti|vuoi|preferisci|posso|procedo|conferm\\p{L}*|dimmi|" +
    "decidi|scegli|prossim[oa]|domani|poi|resta|restano|da\\s+fare|aspetto|attendo|should|want\\s+me|do\\s+you|next|" +
    "need|confirm|let\\s+me\\s+know");
  const PROSSIMO = { test: (f) => f.includes("?") || PROSSIMO_P.test(f) };
  const ESITO_NARR = W("fatto|finito|completat\\p{L}*|riuscit\\p{L}*|ok|pronto|errore|done|ready|failed|error|works");
  const NUMERO = /(?<![\p{L}])\d/u;
  const PAROLA = /[A-Za-zÀ-ÿ]{2,}|\d/;

  const FENCE = /```[\s\S]*?(?:```|$(?![\s\S]))|~~~[\s\S]*?(?:~~~|$(?![\s\S]))/g;
  const INLINE_CODE = /`[^`\n]*`/g;
  const MD_IMG = /!\[[^\]]*\]\([^)]*\)/g, MD_LINK = /\[([^\]]+)\]\([^)]+\)/g;
  const URL_ = /\b(?:(?:https?|ftp|ssh|file|wss?):\/\/|www\.)\S+?(?=[.,;:!?)»"']*(?:\s|$))/gi;
  const EMAIL = /\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g;
  const IP = /\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b|\[?\b[0-9a-f]{0,4}::[0-9a-f:]*[0-9a-f]\b\]?/gi;
  const DOMINIO = /\b[\w-]+(?:\.[\w-]+)*\.(?:com|it|net|org|io|dev|app|cloud|ai|co|eu|me|info|xyz|sh|local|lan)\b(?::\d+)?(?:\/\S*)?/gi;
  const HOST_LUNGO = /\b[a-z][\w-]*(?:\.[\w-]+)+\.[a-z]{2,}\b(?::\d+)?/gi;
  const PERCORSO_ASSOLUTO = /(?:(?<=^)|(?<=[\s("'«:=]))(?:~|\.{1,2})?\/[^\s,;)"'»]*/g;
  const PERCORSO_WIN = /\b[A-Za-z]:\\[^\s,;)"'»]*/g;
  const PERCORSO_RELATIVO = /(?<![\w/])[\w.@-]*[\w@](?:\/[\w.@-]*[\w@])+\/?/g;
  const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
  const HEX = /\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b/gi;
  const ID_LUNGO = /\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{16,}\b/g;
  const OPZIONE = /(?<!\w)--?[a-zA-Z][\w-]*(?:=\S+)?/g;
  let EMOJI;
  try { EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u2190-\u21FF\u2300-\u23FF\u2B00-\u2BFF\uFE0F\u200D\u20E3]/gu; }
  catch (e) { EMOJI = /[\u2600-\u27BF\uFE0F\u200D]/g; }
  const APPESA_PRIMA = new RegExp("(?:" + B + "(?:in|su|a|da|di|con|per|nel|nella|nello|nei|nelle|sul|sulla|sui|al|alla|ai|" +
    "dal|dalla|dai|del|della|dei|tra|fra|come|tipo|cioè|ovvero|at|on|to|from|into|of|with|via|the|a|an|il|lo|la|l'|i|" +
    "gli|le|un|una|uno|un'|file|cartella|comando|indirizzo|percorso|link)\\s*)+" + X, "giu");
  const FINE_FRASE = /(?<=[.!?…])\s+/;
  const RIGA_TABELLA = /^\s*\|.*\|?\s*$|^\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
  const RIGA_JSON = /^\s*(?:[{}[\]],?\s*$|"[^"]*"\s*:|[{[]\s*")/;
  const RIGA_LOG = /^\s*(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?\S*\s+\[|(?:Traceback|File "|\s+at\s+\S+\(|[A-Z]\w*(?:Error|Exception):))/;
  const PUNTO_ELENCO = /^\s*(?:[-*+•·▪►]|\d{1,2}[.)])\s+/;

  function eComando(riga) {
    let r = String(riga).trim();
    if (!r) return false;
    if (/^[$%#>] \S/.test(r)) {                    // prompt di shell davanti
      const lead = r[0];
      r = r.slice(2).trim();
      if (COMANDI.has(r.split(/\s+/)[0].toLowerCase()) || lead === "$" || lead === "%") return true;
    }
    const primo = r.split(/\s+/)[0];
    if (!COMANDI.has(primo.toLowerCase()) && !COMANDI.has(primo)) return false;
    if (AMBIGUI.has(primo.toLowerCase())) return /\s-{1,2}\w|[|>&;$/~=]|\.\w{1,4}\b/.test(r);
    if (/\s-{1,2}\w|[|&;$/~=\\'"]|\.\w{1,4}\b|@/.test(r)) return true;
    return r.split(/\s+/).length <= 4 && !/[.!?]$/.test(r);
  }
  function togliRelativo(s) {
    const pezzi = s.split("/").filter(Boolean);
    if (pezzi.every((p) => /^\d+$/.test(p))) return s;                       // date: 04/10/2026, 24/7
    if (pezzi.length === 2 && pezzi.every((p) => p.length <= 3 && /^\p{L}+$/u.test(p))) return s;  // e/o, km/h
    if (pezzi.length >= 3 || /\.\w{1,5}$/.test(s) || s.endsWith("/")) return " " + X + " ";
    if (pezzi.length === 2 && /[-_.]/.test(s)) return " " + X + " ";
    return s;                                                                // Mac/VPS, sì/no
  }
  function pulisciRiga(r) {
    const T = " " + X + " ";
    r = r.replace(MD_IMG, T).replace(MD_LINK, "$1").replace(URL_, T).replace(EMAIL, T).replace(UUID, T)
      .replace(IP, T).replace(PERCORSO_WIN, T).replace(PERCORSO_ASSOLUTO, T).replace(PERCORSO_RELATIVO, togliRelativo)
      .replace(DOMINIO, T).replace(HOST_LUNGO, (m) => (/^[\d.]+$/.test(m) ? m : T)).replace(HEX, T).replace(ID_LUNGO, T)
      .replace(OPZIONE, T).replace(EMOJI, " ");
    r = r.replace(/\*\*|__|~~/g, "")
      .replace(/(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])/g, "$1")
      .replace(/(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])/g, "$1")
      .replace(/`/g, " ");
    r = r.replace(/\s+/g, " ")
      .replace(new RegExp(X + "(?:\\s*" + X + ")+", "g"), X)
      .replace(APPESA_PRIMA, X)
      .replace(new RegExp(X + "\\s*(?:e|o|ed|and|or)\\s*" + X, "g"), X)
      .replace(new RegExp("\\(\\s*" + X + "?\\s*\\)", "g"), " ")
      .split(X).join(" ");
    r = r.replace(/(?<!\d)\/|\/(?!\d)/g, " ")          // la barra resta solo fra cifre (date)
      .replace(/\s*(?:—|–)\s*/g, ", ")
      .replace(/->|=>|<-|<=|>=|\|/g, " ")
      .replace(/[_\\#*~^{}[\]<>=]/g, " ")
      .replace(/\(\s*[,.;:]*\s*\)/g, " ")
      .replace(/\s+/g, " ").trim()
      .replace(/\s+([.,;:!?…])/g, "$1")
      .replace(/([,;:])(?:\s*[,;:])+/g, "$1")
      .replace(/^[\s,;:.-]+/, "")
      .replace(/[\s,;:]+([.!?…])/g, "$1")
      .replace(/[\s,;]+$/, "");
    return r.trim();
  }
  function togliPresentazione(righe) { if (righe.length && righe[righe.length - 1].endsWith(":")) righe.pop(); }
  function eNarrazione(f) {
    if (!NARRAZIONE.test(f)) return false;
    if (NUMERO.test(f) || ESITO_NARR.test(f)) return false;
    return true;
  }
  function filtra(testo) {
    let tolto = false;
    let t = String(testo).replace(/\r\n?/g, "\n").replace(/<<[^<>]{1,80}>>/g, " ");
    // i segnaposto di ponte.js e chiamata.js valgono come cose tolte
    t = t.replace(/\((?:codice|link)\)/gi, () => { tolto = true; return " "; });
    if (FENCE.test(t)) { tolto = true; FENCE.lastIndex = 0; t = t.replace(FENCE, "\n\u0001\n"); }
    FENCE.lastIndex = 0;
    const buone = [];
    for (const riga of t.split("\n")) {
      let r = riga.replace(/\s+$/, "");
      if (!r.trim()) continue;
      if (r.trim() === "\u0001" || RIGA_TABELLA.test(r) || RIGA_JSON.test(r) || RIGA_LOG.test(r)) {
        tolto = true; togliPresentazione(buone); continue;
      }
      if (/^\s{0,3}#{1,6}\s/.test(r)) continue;                    // titoli
      r = r.replace(/^\s*>\s?/, "");
      const elenco = PUNTO_ELENCO.test(r);
      r = r.replace(PUNTO_ELENCO, "");
      if ((/^\s{4,}\S/.test(riga) && !elenco) || eComando(r)) { tolto = true; togliPresentazione(buone); continue; }
      if (!r.replace(INLINE_CODE, "").replace(/^[\s:.,;-]+|[\s:.,;-]+$/g, "")) { tolto = true; togliPresentazione(buone); continue; }
      r = pulisciRiga(r.replace(INLINE_CODE, " " + X + " "));
      if (!PAROLA.test(r)) continue;
      if (!/[.!?…:;]$/.test(r)) r += ".";
      buone.push(r);
    }
    const frasi = [];
    for (let b of buone) {
      if (/[:;]$/.test(b)) b = b.slice(0, -1) + ".";
      for (let f of b.split(FINE_FRASE)) {
        f = f.trim();
        if (!f || !PAROLA.test(f) || eNarrazione(f)) continue;
        frasi.push(f);
      }
    }
    return { frasi, tolto };
  }
  function valeLaCoda(testo) {
    const t = String(testo);
    FENCE.lastIndex = 0;
    if (FENCE.test(t)) { FENCE.lastIndex = 0; return true; }
    FENCE.lastIndex = 0;
    if (/\((?:codice|link)\)/i.test(t)) return true;
    const pesanti = t.split("\n").filter((r) => r.trim() &&
      (RIGA_TABELLA.test(r) || RIGA_JSON.test(r) || eComando(r.replace(PUNTO_ELENCO, "")))).length;
    return pesanti >= 2;
  }
  function accorcia(f, max) {
    if (f.length <= max) return f;
    const p = f.slice(0, max);
    let taglio = Math.max(p.lastIndexOf(", "), p.lastIndexOf("; "), p.lastIndexOf(": "));
    if (taglio < max * 0.5) taglio = p.lastIndexOf(" ");
    if (taglio <= 0) taglio = max;
    return p.slice(0, taglio).replace(/[ ,;:]+$/, "") + ".";
  }
  function perLaVoce(testo, maxCar = MAX_CARATTERI, maxFrasi = MAX_FRASI) {
    if (testo == null || !String(testo).trim()) return "";
    testo = String(testo);
    let giaCoda = false;
    for (const coda of [CODA_RESTO, "Il resto è in chat."]) {
      const t = testo.replace(/\s+$/, "");
      if (t.endsWith(coda)) { testo = t.slice(0, -coda.length); giaCoda = true; }
    }
    const { frasi, tolto } = filtra(testo);
    if (!frasi.length) return NIENTE_DA_DIRE;
    const tutto = frasi.join(" ");
    if (frasi.length <= maxFrasi && tutto.length <= maxCar + 20) {
      return giaCoda || (tolto && valeLaCoda(testo)) ? tutto + " " + CODA_RESTO : tutto;
    }
    const esiti = frasi.map((f, i) => (ESITO.test(f) || NUMERO.test(f) ? i : -1)).filter((i) => i >= 0);
    let scelte;
    if (esiti.length) {
      scelte = [esiti[0]];
      if (maxFrasi >= 2) {
        const dopo = frasi.map((f, i) => i).filter((i) => !scelte.includes(i) && PROSSIMO.test(frasi[i]));
        const altri = esiti.filter((i) => !scelte.includes(i));
        const resto = frasi.map((f, i) => i).filter((i) => !scelte.includes(i));
        for (const c of [dopo, altri, resto]) if (c.length) { scelte.push(c[0]); break; }
      }
    } else {
      scelte = frasi.slice(0, maxFrasi).map((f, i) => i);
    }
    let detto = "", usate = 0;
    scelte.forEach((i, k) => {
      const f = frasi[i];
      if (k === 0) { detto = accorcia(f, maxCar); usate = 1; return; }
      if (detto.length + 1 + f.length <= maxCar) { detto += " " + f; usate++; }
    });
    const intero = scelte.slice(0, usate).map((i) => frasi[i]).join(" ");
    if (usate < frasi.length || giaCoda || (tolto && valeLaCoda(testo)) || detto !== intero) detto += " " + CODA_RESTO;
    return detto.trim();
  }

  const api = { perLaVoce, CODA_RESTO, NIENTE_DA_DIRE, MAX_CARATTERI };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // prove con node
  if (!radice) return;
  radice.CCVoceSintetica = api;

  // ---------------------------------------------------------------- l'aggancio: solo il parlato cambia
  try {
    const ss = radice.speechSynthesis;
    if (!ss || typeof radice.SpeechSynthesisUtterance !== "function") return;
    const proto = Object.getPrototypeOf(ss);
    const speak0 = proto && proto.speak;
    if (typeof speak0 !== "function" || speak0.__sintetica) return;
    const speak = function (u) {
      try {
        if (u && typeof u.text === "string" && !u.__sintetica) {
          u.__sintetica = true;
          const t = perLaVoce(u.text);
          if (t && t !== u.text) u.text = t;
        }
      } catch (e) { /* in caso di guaio si legge il testo com'era */ }
      return speak0.call(this, u);
    };
    speak.__sintetica = true;
    proto.speak = speak;
  } catch (e) { /* browser senza sintesi: niente da agganciare */ }
})(typeof window !== "undefined" ? window : null);
