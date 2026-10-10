// Prova di static/voce-chat.js e static/dettato.js senza browser (2026-10-05, riquadro «Chat a voce»).
// Uso: node command-center/prove/prova_voce_chat.js
// Finti: DOM minimo, riconoscimento vocale, sintesi, azione() del pannello e le battute di app.js.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const STATIC = path.join(__dirname, "..", "static");

const esiti = [];
const v = (nome, cond) => { esiti.push(!!cond); console.log((cond ? "  ok   " : "  NO   ") + nome); };
const dorme = (ms) => new Promise((r) => setTimeout(r, ms));

function nodo(id) {
  const ascolta = {};
  const classi = new Set();
  return {
    id, hidden: id === "chat-voce-mic" || id === "chat-voce-nota", value: "", textContent: "", attr: {},
    classList: { add: (c) => classi.add(c), remove: (c) => classi.delete(c), contains: (c) => classi.has(c),
      toggle: (c, si) => { if (si === undefined ? !classi.has(c) : si) classi.add(c); else classi.delete(c); } },
    setAttribute(k, x) { this.attr[k] = String(x); }, getAttribute(k) { return this.attr[k]; },
    addEventListener(t, f) { (ascolta[t] = ascolta[t] || []).push(f); },
    click() { for (const f of ascolta.click || []) f({}); },
  };
}

async function main() {
  const nodi = {};
  for (const id of ["chat-voce-testo", "chat-voce-mic", "chat-voce-parla", "chat-voce-nota"]) nodi[id] = nodo(id);
  const eventi = {};
  let rec = null;
  const parlato = [], mandati = [];
  function Riconoscimento() { rec = this; this.start = () => {}; this.stop = () => { if (this.onend) this.onend(); }; this.abort = () => {}; }
  const finestra = {
    document: { readyState: "complete", hidden: false, getElementById: (id) => nodi[id] || null, addEventListener() {} },
    addEventListener: (t, f) => { (eventi[t] = eventi[t] || []).push(f); },
    webkitSpeechRecognition: Riconoscimento,
    speechSynthesis: { speak: (u) => { parlato.push(u.text); setTimeout(() => u.onend && u.onend(), 10); }, cancel() {}, getVoices: () => [] },
    SpeechSynthesisUtterance: function (t) { this.text = t; },
    CustomEvent: function (t, o) { this.type = t; this.detail = o && o.detail; },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, String, Object, Array, Math,
    __VOCE_CHAT: { silenzio: 50 },
  };
  finestra.window = finestra;
  finestra.azione = async (c) => { mandati.push(c); return c.tipo === "chat_voce_parla" ? { messaggio: "ti ascolto" } : { messaggio: "mandato" }; };
  const ctx = vm.createContext(finestra);
  vm.runInContext(fs.readFileSync(path.join(STATIC, "dettato.js"), "utf8"), ctx);
  vm.runInContext(fs.readFileSync(path.join(STATIC, "voce-chat.js"), "utf8"), ctx);
  const batti = (battute, macchina) => { for (const f of eventi["cc:chat-voce"] || []) f({ detail: { battute: battute.slice(), macchina, voce: true } }); };
  const stato = () => finestra.__VOCE_CHAT_STATO();

  v("il 🎤 compare quando il browser sa dettare", nodi["chat-voce-mic"].hidden === false);
  // 🎤 dettato
  nodi["chat-voce-mic"].click();
  v("🎤: dettato acceso", stato().dettato && nodi["chat-voce-mic"].classList.contains("attivo"));
  rec.onresult({ results: [Object.assign([{ transcript: "Ascolta" }], { isFinal: false }), Object.assign([{ transcript: "Ascolta ti voglio" }], { isFinal: false })] });
  v("🎤: il testo va nel campo senza ripetizioni", nodi["chat-voce-testo"].value === "Ascolta ti voglio");
  v("🎤: niente parte da solo", mandati.length === 0);
  nodi["chat-voce-mic"].click();
  v("🎤: secondo tocco ferma", !stato().dettato && !nodi["chat-voce-mic"].classList.contains("attivo"));
  nodi["chat-voce-testo"].value = "";

  // 📞 sul Mac: azione chat_voce_parla, la risposta la dice backtalk
  const storia = [{ chi: "jarvis", testo: "vecchia", ts: "2026-10-05T15:00:00", origine: "mac" }];
  batti(storia, "mac");
  nodi["chat-voce-parla"].click();
  await dorme(20);
  v("📞 Mac: manda chat_voce_parla", mandati.length === 1 && mandati[0].tipo === "chat_voce_parla");
  v("📞 Mac: il tasto resta acceso mentre ascolta", nodi["chat-voce-parla"].classList.contains("attivo"));
  storia.push({ chi: "utente", testo: "mi senti", ts: "2026-10-05T15:01:00", origine: "mac" },
    { chi: "jarvis", testo: "sì", ts: "2026-10-05T15:01:02", origine: "mac" });
  batti(storia, "mac");
  v("📞 Mac: alla risposta il tasto si spegne e il browser non legge niente", !nodi["chat-voce-parla"].classList.contains("attivo") && parlato.length === 0);
  // secondo tocco mentre il Mac ascolta: ferma, non rimanda chat_voce_parla (verificatore, 2026-10-05)
  mandati.length = 0;
  nodi["chat-voce-parla"].click();
  await dorme(20);
  v("📞 Mac: primo tocco ascolta", mandati.length === 1 && stato().ascoltoMac && nodi["chat-voce-parla"].classList.contains("attivo"));
  nodi["chat-voce-parla"].click();
  await dorme(20);
  v("📞 Mac: secondo tocco ferma, senza un altro chat_voce_parla", mandati.length === 1 && !stato().ascoltoMac &&
    !nodi["chat-voce-parla"].classList.contains("attivo") && !stato().attesa && nodi["chat-voce-nota"].hidden);

  // 📞 sul sito: conversazione dal browser
  mandati.length = 0;
  const sito = [{ chi: "jarvis", testo: "vecchia", ts: "2026-10-05T15:00:00", origine: "telefono" }];
  batti(sito, "vps");
  nodi["chat-voce-parla"].click();
  v("📞 sito: conversazione aperta, ascolta", stato().conv && stato().fase === "ascolto");
  rec.onresult({ results: [Object.assign([{ transcript: "che ore sono" }], { isFinal: true })] });
  await dorme(120);
  v("📞 sito: dopo il silenzio la frase parte con chat_voce_manda", mandati.length === 1 && mandati[0].tipo === "chat_voce_manda" && mandati[0].testo === "che ore sono");
  v("📞 sito: aspetta la risposta", stato().fase === "pensa" && stato().attesa);
  sito.push({ chi: "utente", testo: "che ore sono", ts: "2026-10-05T15:20:00", origine: "sito" },
    { chi: "jarvis", testo: "dal Mac", ts: "2026-10-05T15:20:01", origine: "mac" });
  batti(sito, "vps");
  v("📞 sito: una battuta della voce del Mac non è la risposta", stato().attesa && parlato.length === 0);
  // la finestra di 150 battute scorre: la più vecchia esce mentre entra la risposta
  sito.shift();
  sito.push({ chi: "jarvis", testo: "Sono le tre e venti", ts: "2026-10-05T15:20:03", origine: "sito" });
  batti(sito, "vps");
  await dorme(900);
  v("📞 sito: la risposta si legge a voce (anche con la finestra che scorre)", parlato.join("|") === "Sono le tre e venti");
  v("📞 sito: dopo la lettura torna ad ascoltare", stato().conv && stato().fase === "ascolto");
  nodi["chat-voce-parla"].click();
  v("📞 sito: secondo tocco chiude", !stato().conv && !nodi["chat-voce-parla"].classList.contains("attivo"));

  // 2026-10-05 scheda «Voce»: dove c'è la chiamata di chiamata.js (ponte), «Chiama» apre quella
  mandati.length = 0;
  let aperte = 0;
  finestra.CCChiamata = { attiva: () => true, apri: () => { aperte++; } };
  nodi["chat-voce-parla"].click();
  await dorme(20);
  v("Chiama nel ponte: apre la chiamata di chiamata.js, nessuna azione al server", aperte === 1 && mandati.length === 0 && !stato().conv);
  v("CCVoceChat esposto (apri, chiudi, attiva)", typeof finestra.CCVoceChat.apri === "function" && typeof finestra.CCVoceChat.attiva === "function");

  console.log(esiti.every(Boolean) ? "tutto ok" : `${esiti.filter((x) => !x).length} prove fallite`);
  process.exit(esiti.every(Boolean) ? 0 : 1);
}
main().catch((e) => { console.error(e); process.exit(1); });
