"use strict";
const $ = (id) => document.getElementById(id);
const HDR = { "X-Token": window.CC_TOKEN, "Content-Type": "application/json" };
const VOCE = { idle: "in attesa", listening: "ascolto", thinking: "sto pensando", speaking: "parlo" };
let lavoroScelto = null;
let agenti = [];
// 2026-10-10 (Jarvis da zero): i nomi vengono dal profilo (profilo-jarvis.md: nome_assistente, chiamami), via /api/spazi
let ASSISTENTE = "Jarvis", UTENTE = "";
const nomeUtente = () => UTENTE || "Tu";
const etichettaOrchestratore = () => `${ASSISTENTE} — orchestratore`;
const eNotaOrchestratore = (t) => /—\s*orchestratore/i.test(String(t || "")) || /^jarvis(\s|—|-|$)/i.test(String(t || "").trim());
const eNotaUtente = (t) => t === "L'utente" || (UTENTE && t === UTENTE) || t === "Tu";

function el(tag, attrs = {}, ...figli) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;          // attributo assente (es. disabled: null)
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  for (const f of figli) n.append(f instanceof Node ? f : document.createTextNode(f ?? ""));
  return n;
}

function toast(testo, errore = false) {
  const t = $("toast");
  t.textContent = testo;
  t.className = "toast visibile" + (errore ? " errore" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.className = "toast"), 4200);
}

// Ogni chiamata ha un tetto di tempo: se un gestore del server rallenta, le richieste non si
// accumulano aperte (ognuna tiene un thread del server). 10 s per le letture; le azioni che
// aspettano apposta (scegliere un file, il giro della memoria) hanno il loro tetto in azione().
const TETTO_API = 10000;

// ---- Dentro il ponte (2026-10-03, coerenza del sito). Da internet il Command Center passa da cc-ponte
// (vps/cc-ponte/cc_ponte.py). Lo decide ponte.js (GET /_ponte/stato = 200), che chiama PONTE.decidi() e
// PONTE.prendiAzioni(stato.azioni) a ogni lettura (all'avvio, poi ogni 15 s e al ritorno sulla scheda).
// «azioni» è la tabella che il ponte usa davvero (elenco_per_pagina): post_percorsi, azione_tipi
// («tipo» o «tipo:cosa»), solo_no (con comandi-off passano solo per dire no), get_bloccati,
// get_bloccati_parole, get_senza_forza. Spiegazione di ogni voce: vps/cc-ponte/AZIONI-SITO.md.
// Le chiamate che il ponte rifiuterebbe non partono (errore «Disponibile solo dal Mac»); ponte.js
// spegne i pulsanti la cui azione non è nell'elenco. Senza elenco (non ancora arrivato, lettura
// fallita, ponte vecchio) non si spegne e non si blocca niente: decide il ponte, e l'errore si vede.
// Sul Mac (404) PONTE.dentro resta false: lì non cambia niente.
// 2026-10-03 sera (l'utente: «niente in sola lettura dal sito»): fino alla prima versione qui c'erano elenchi
// copiati a mano (solo chiedi/ferma/approva) e la lavagna non salvava dal sito. Tolti.
const SOLO_MAC = "Disponibile solo dal Mac";
const PONTE = { dentro: false, deciso: null, decidi: null, azioni: null };
PONTE.deciso = new Promise((ok) => {
  PONTE.decidi = (si) => { PONTE.dentro = !!si; PONTE.fatto = true; ok(PONTE.dentro); };
  setTimeout(() => { PONTE.fatto = true; ok(PONTE.dentro); }, 4000);   // ponte.js non c’è o non risponde: si va avanti come sul Mac
});
PONTE.prendiAzioni = (a) => {
  PONTE.azioni = a && Array.isArray(a.post_percorsi) && Array.isArray(a.azione_tipi) ? a : null;
  if (typeof statoSalva === "function" && panPronto) { if (SALVA.sporco || SALVA.avviso) salvaPannello(); else statoSalva(); }
};
// Restrizioni sui valori che il ponte applica dentro le regole (v_modo_chat, v_missione, v_interruttore,
// v_telefono in cc_ponte.py) e che l'elenco «azioni» non porta: classe C in AZIONI-SITO.md.
// 2026-10-04: cc_ponte.py (terza tornata) vieta anche il gruppo nato col capogruppo o con la squadra del CEO
// (v_agente crea_gruppo) e le istruzioni persistenti degli agenti in /api/agente-profilo (description, tools, tono).
// Se il ponte un giorno manda «valori_vietati» in /_ponte/stato.azioni, contano anche quelli.
const PONTE_VALORI_VIETATI = ["modo_chat=lavoro", "missione=lavoro", "interruttore=schermo_telefono+acceso", "telefono:chiama",
  "agente:crea_gruppo=capogruppo", "/api/agente-profilo=istruzioni"];
// schede di «Computer» che da internet (ponte senza «tutto») non funzionano. Dal 2026-10-05 il terminale non c'è più:
// dal sito la scheda Terminale mostra quello root della VPS (/term/vps/, Caddy). Il banco tecnico (in Telefono) lo nasconde index.html.
const PONTE_VISTE_MAC = ["vps", "pc"];
const ponteRistretto = () => PONTE.dentro && !(PONTE.azioni && PONTE.azioni.tutto === true);
// La chiave di un'azione: «tipo», «tipo:cosa», «/api/percorso» (POST) o «GET /percorso?query».
function chiaveAzione(percorso, corpo) {
  if (!corpo) return "GET " + percorso;
  if (percorso !== "/api/azione") return percorso;
  return corpo.cosa != null ? `${corpo.tipo}:${corpo.cosa}` : String(corpo.tipo);
}
function valoriVietati(corpo) {
  if (!corpo || typeof corpo !== "object") return false;
  if (corpo.tipo === "modo_chat" && corpo.modo === "lavoro") return true;
  if (corpo.tipo === "missione" && (corpo.modalita || "lettura") === "lavoro") return true;
  if (corpo.tipo === "interruttore" && corpo.nome === "schermo_telefono" && corpo.acceso) return true;
  if (corpo.tipo === "agente" && corpo.cosa === "crea_gruppo" && (corpo.crea_capogruppo || corpo.squadra_ceo)) return true;
  if (corpo.file && ["description", "tools", "tono"].some((k) => k in corpo) && !("tipo" in corpo)) return true;   // /api/agente-profilo
  return false;
}
// true se il ponte lascia passare la chiave (sempre true fuori dal ponte o senza elenco)
function ponteConsente(chiave, corpo = null) {
  if (!PONTE.dentro) return true;
  const a = PONTE.azioni;
  if (a && a.tutto === true) return true;      // 2026-10-05 (l'utente): dal sito passa tutto, il ponte lo dice con «tutto»
  if (PONTE_VALORI_VIETATI.includes(chiave) || (a && Array.isArray(a.valori_vietati) && a.valori_vietati.includes(chiave)) || valoriVietati(corpo)) return false;
  if (!a) return true;
  if (chiave.startsWith("GET ")) {
    const [p, q = ""] = chiave.slice(4).toLowerCase().split("?");
    if ((a.get_bloccati || []).some((b) => p === b || p.startsWith(b))) return false;
    if ((a.get_bloccati_parole || []).some((w) => p.includes(w))) return false;
    return !((a.get_senza_forza || []).includes(p) && /(^|&)forza(=|&|$)/.test(q));
  }
  if (chiave.startsWith("/")) return a.post_percorsi.includes(chiave);
  if (!a.post_percorsi.includes("/api/azione")) return false;
  if (!a.azione_tipi.includes(chiave)) return false;
  // con comandi-off approva e conferma passano solo per dire no
  if (corpo && (a.solo_no || []).includes(corpo.tipo)) return corpo.decisione === "no" || corpo.ok === false;
  return true;
}
function rifiutataDalPonte(percorso, corpo) {
  return !ponteConsente(chiaveAzione(percorso, corpo), corpo);
}

// Letture condizionali (2026-10-03, prestazioni da internet). Per questi GET la pagina tiene in memoria
// l'ultima risposta (testo e ETag) e la richiede con If-None-Match: se il server risponde 304 (niente corpo)
// si riusa il testo tenuto, riletto con JSON.parse come se fosse appena arrivato. Solo memoria JavaScript:
// il server manda sempre Cache-Control: no-store e niente finisce nella cache del browser. Server senza
// ETag: nessuna copia, tutto come prima.
const CONDIZ = { percorsi: /^\/api\/(pannello|catalogo|spazi|chat\/storia|scadenze)(\?|$)/, copie: new Map() };
function condizionale(percorso) {
  const c = CONDIZ.copie.get(percorso);
  return c ? Object.assign({}, HDR, { "If-None-Match": c.etag }) : HDR;
}
async function testoCondizionale(percorso, r) {
  // 304: la copia tenuta (c'è per forza: If-None-Match parte solo con una copia); 200: si tiene la nuova
  if (r.status === 304 && CONDIZ.copie.has(percorso)) return CONDIZ.copie.get(percorso).testo;
  const testo = await r.text();
  const etag = r.ok && r.headers.get("ETag");
  if (etag) CONDIZ.copie.set(percorso, { etag, testo }); else CONDIZ.copie.delete(percorso);
  return testo;
}

async function api(percorso, corpo, tetto = TETTO_API) {
  if (!PONTE.fatto) await PONTE.deciso;          // sul Mac il 404 di /_ponte/stato arriva in pochi ms
  if (rifiutataDalPonte(percorso, corpo)) throw new Error(SOLO_MAC);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), tetto);
  const cond = !corpo && CONDIZ.percorsi.test(percorso);
  let r;
  try {
    r = await fetch(percorso, corpo ? { method: "POST", headers: HDR, body: JSON.stringify(corpo), signal: ctl.signal }
      : { headers: cond ? condizionale(percorso) : HDR, signal: ctl.signal });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? `il Command Center non ha risposto entro ${Math.round(tetto / 1000)} s` : "Command Center non raggiungibile");
  } finally {
    clearTimeout(timer);
  }
  let d;
  try { d = JSON.parse(cond ? await testoCondizionale(percorso, r) : await r.text()); } catch (e) { d = {}; }
  if (cond && r.status === 304) {
    if (CONDIZ.copie.has(percorso)) return d;
    throw new Error("errore 304");
  }
  // Il token cambia a ogni avvio del server: una pagina aperta prima (anche l'app installata)
  // riceverebbe 403 per sempre. Si ricarica da sola, al massimo una volta ogni 15 secondi.
  if (r.status === 403 && d.token_scaduto) {
    const ultimo = Number(sessionStorage.getItem("cc.ricarica") || 0);
    if (Date.now() - ultimo > 15000) {
      sessionStorage.setItem("cc.ricarica", String(Date.now()));
      location.reload();
    }
    throw new Error("il Command Center è ripartito: ricarico la pagina");
  }
  if (!r.ok) throw new Error(d.errore || `errore ${r.status}`);
  return d;
}

// azioni che per natura aspettano a lungo sul server (tetto in ms)
const TETTO_AZIONE = { scegli_allegato: 130000, vps_desktop: 45000, terminale: 30000,
  interruttore: 45000, android: 40000, telefono: 100000, telegram_riaggancia: 40000, tecnico: 40000,
  aggiorna: 65000, sentinella: 120000, portiere: 30000 };   // aggiorna: il server aspetta il raccoglitore fino a 60 s

// opz.zitto (2026-10-05): niente toast del messaggio, quando chi chiama lo scrive già al suo posto (scheda Voce:
// il toast «ti ascolto» copriva la prima battuta della storia). Gli errori restano in toast.
async function azione(corpo, bottone, opz) {
  // il bottone resta spento e gira finché il server non risponde (↻ «aggiorna» può aspettare 60 s)
  if (bottone) { bottone.disabled = true; bottone.classList.add("in-attesa"); }
  try {
    const d = await api("/api/azione", corpo, TETTO_AZIONE[corpo.tipo] || 30000);
    if (d.errori && d.errori.length) toast((d.messaggio ? d.messaggio + " · " : "") + "errori: " + d.errori.join(", "), true);
    else if (d.messaggio && !(opz && opz.zitto)) toast(d.messaggio);
    if (d.lavoro) { lavoroScelto = d.lavoro.id; firmaDettaglio = ""; toast("Avviato: " + d.lavoro.titolo); }
    setTimeout(aggiorna, 800);
    return d;
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (bottone) { bottone.disabled = false; bottone.classList.remove("in-attesa"); }
  }
}

function pallino(colore) { return el("span", { class: "pallino " + colore }); }

function disegnaLocale(l) {
  for (const riga of document.querySelectorAll("[data-int]")) {
    if (riga.dataset.tg) continue;  // le righe di Telegram le disegna disegnaTelegram
    riga.querySelector(".switch").classList.toggle("on", !!l[riga.dataset.int]);
  }
  const chiede = $("ind-chiede").querySelector(".spia");
  chiede.className = "spia " + (l.chiede_prima ? "on" : "attenzione");
  $("ind-chiede-t").textContent = l.chiede_prima ? "ti chiede il sì prima di cancellare, pubblicare, pagare, scrivere" : "agisce senza chiedere";
  $("ind-alpc").querySelector(".spia").className = "spia " + (l.al_pc ? "on" : "");
  $("ind-alpc-t").textContent = l.al_pc ? "può usare schermo, mouse e tastiera del PC" : "lavora solo con comandi e file";
  $("avviso-fidata").classList.toggle("nascosto", l.fidata !== false);

  const sfera = $("sfera");
  const vs = l.voce ? (l.voce_stato || "idle") : "spenta";
  sfera.className = "sfera " + vs;
  const voceTesto = l.voce ? (VOCE[vs] || vs) : "voce spenta";
  $("voce-stato").textContent = voceTesto;
  // lo stesso stato, nell'intestazione di ogni scheda (mockup 26/09/2026, idea 1)
  const aj = $("avatar-jarvis");
  if (aj) {
    aj.className = "avatar-jarvis " + vs;
    aj.title = "Jarvis · " + voceTesto + " — clic: scheda Stato";
    $("aj-testo").textContent = voceTesto;
  }
  vocePensa = l.voce && vs === "thinking";
  disegnaAttesaVoce();

  const a = l.android || {};
  if (a.spento) $("and-stato").textContent = "non attivo in questa installazione";
  else if (!a.installato) $("and-stato").textContent = "adb non installato";
  else if (!a.dispositivi.length) $("and-stato").textContent = "nessun telefono collegato";
  else {
    // Si dice sempre **quale** apparecchio, e se ce n'è più d'uno si dicono
    // tutti: con un emulatore acceso accanto al telefono vero, mostrarne uno
    // solo fa credere di star guardando l'altro.
    const chi = a.dispositivi.map((d) => d.modello).join(" + ");
    const altri = a.dispositivi.length > 1 ? ` · ${a.dispositivi.length} collegati, i comandi vanno al primo` : "";
    $("and-stato").textContent = `● ${chi}` + (a.batteria != null ? ` · batteria ${a.batteria}%` : "") +
      (a.schermo ? " · schermo aperto" : "") + altri;
  }

  if (cambiato("vociAndroid", l.voci, l.android)) disegnaVociAndroid(l);
  if (cambiato("sessioni", l.agenti_sessioni)) disegnaSessioni(l.agenti_sessioni);
  if (l.mac) {
    $("mac-cpu").textContent = l.mac.cpu != null ? l.mac.cpu + "%" : "—";
    $("mac-ram").textContent = l.mac.ram != null ? l.mac.ram + "%" : "—";
  }

}

// Telegram: verde = bot agganciato, giallo = sta ripartendo, rosso = giù, grigio = spento dall'utente.

// ---- Telefono: come parla Jarvis (dalla configurazione vera) e informazioni Android ----
function disegnaVociAndroid(l) {
  const v = l.voci || {}, lista = $("voci-lista");
  if (lista) {
    lista.replaceChildren();
    const riga = (titolo, dettaglio, stato, acceso) => el("li", { style: "cursor:default" },
      el("span", {}, titolo, el("br"), el("small", {}, dettaglio)),
      el("span", { class: "etichetta " + (acceso ? "in-corso" : "chiusa") }, stato));
    lista.append(riga("Ascolto · " + ((v.ascolto || {}).nome || "Whisper"), ((v.ascolto || {}).dettaglio || "") + " · lingua " + ((v.ascolto || {}).lingua || "it"), v.voce_accesa ? "voce accesa" : "voce spenta", !!v.voce_accesa));
    lista.append(riga("Cervello · Claude", "capisce e risponde", "sempre", true));
    for (const m of (v.motori || [])) {
      const ultimo = v.ultimo_motore === m.id;
      const quando = ultimo && v.ultimo_ts ? " · ha parlato per ultimo alle " + new Date(v.ultimo_ts * 1000).toTimeString().slice(0, 5) : "";
      lista.append(riga("Voce · " + m.nome, (m.nota || "") + quando, ultimo ? "sta parlando" : (m.attivo ? "attivo" : "spento"), ultimo || m.attivo));
    }
    const s = $("voci-stato");
    if (s) s.textContent = v.ultimo_motore ? "ultima frase detta da " + v.ultimo_motore : "ordine: Azure, poi Edge, poi Kokoro";
  }
  const a = l.android || {}, info = $("and-info");
  if (info) {
    info.replaceChildren();
    const p = a.ponte || {};
    const riga = (titolo, dettaglio, stato, acceso) => el("li", { style: "cursor:default" },
      el("span", {}, titolo, el("br"), el("small", {}, dettaglio)),
      el("span", { class: "etichetta " + (acceso ? "in-corso" : "chiusa") }, stato));
    info.append(riga("Collegamento al Mac (ADB)", a.dispositivi && a.dispositivi.length ? a.dispositivi.map((d) => d.modello).join(" + ") : "nessun telefono: serve il Debug wireless acceso sul telefono, come qui sotto in «Collega il telefono»", a.dispositivi && a.dispositivi.length ? "collegato" : "non collegato", !!(a.dispositivi && a.dispositivi.length)));
    info.append(riga("App Jarvis sul telefono", p.raggiungibile ? (p.app_collegata ? "l'app è collegata al ponte" : "il ponte funziona ma l'app non è collegata: apri l'app Jarvis sul telefono") : "il ponte sulla VPS non risponde", p.app_collegata ? "collegata" : "non collegata", !!p.app_collegata));
    if (p.versione_offerta) info.append(riga("Versione offerta dal ponte", p.versione_offerta + " (l'app si aggiorna da qui)", "info", true));
  }
}

function disegnaTelegram(t) {
  for (const riga of document.querySelectorAll("[data-tg]")) {
    const s = (t || {})[riga.dataset.tg];
    // 2026-10-10: Telegram si vede solo se è configurato su questa macchina (prodotto pubblico: di base non c'è)
    const via = !s || !!s.non_configurato || /non configurat|manca il token|nessun bot/i.test(String(s.errore || ""));
    riga.classList.toggle("nascosto", via);
    if (via) continue;
    riga.querySelector(".switch").classList.toggle("on", !s.errore && !s.spento);
    let colore, testo;
    if (s.errore) { colore = "rosso"; testo = "non risponde: " + s.errore; }
    else if (s.spento) { colore = "grigio"; testo = s.bot + " · spento"; }
    else if (s.occupato && !s.lettore) { colore = "giallo"; testo = s.bot + " · aspetta: il bot è ancora in mano a un'altra sessione Claude, si libera quando la chiudi"; }
    else if (s.lettore) { colore = "verde"; testo = s.bot + " · agganciato" + (s.avviato ? " dalle " + s.avviato.slice(11) : ""); }
    else if (s.sessione) { colore = "giallo"; testo = s.bot + " · si sta agganciando"; }
    else { colore = "rosso"; testo = s.bot + " · giù" + (s.guardia === false ? ", guardiano non installato" : ", il guardiano lo riavvia entro un minuto"); }
    riga.querySelector(".tg-stato").replaceChildren(pallino(colore), " " + testo);
  }
}

// n8n Jarvis si spegne apposta: non conta come «giù» né nello stato generale né nella spia di Server
const SITI_IGNORATI = [];          // nomi di siti da non contare come «giù» (di base nessuno)

function disegnaVps(v) {
  if (!v || !("siti" in v)) return;
  // 🔴 2026-10-03 (segnalato dall'agente dei temi): firstChild dopo boxInit è la maniglia ⠿, e il nome finiva
  // DENTRO il pulsante (opacità .45, aria-label sbagliato). Si cambia il primo nodo di testo del titolo.
  if (v.nome) {
    const h = $("vps-titolo"), t = [...h.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
    if (t) t.textContent = v.nome + " "; else h.insertBefore(document.createTextNode(v.nome + " "), $("vps-letto"));
  }
  $("vps-letto").textContent = v.letto ? "letto alle " + v.letto : "";
  const siti = $("vps-siti");
  siti.replaceChildren();
  if (v.configurata === false) siti.append(el("div", { style: "cursor:default" }, el("span", {}, pallino("grigio"), " nessun server configurato"),
    el("small", {}, "aggiungi la VPS in spazi.json per vederla qui")));
  else if (!v.raggiungibile) siti.append(el("div", {
    onclick: () => chiediJarvis("La VPS non risponde via SSH. Controlla perché e dimmi cosa sappiamo, senza riavviare niente senza il mio sì.", "vps"),
  }, el("span", {}, pallino("rosso"), " SSH non risponde"), el("small", {}, "clic: chiedi a Jarvis di controllare")));
  for (const [nome, codice] of Object.entries(v.siti || {})) {
    const ok = /^[23]/.test(codice);
    siti.append(el("div", {
      title: "clic: chiedi a Jarvis di " + nome,
      onclick: () => chiediJarvis(ok ? `Verifica ${nome} sulla VPS, il codice è ${codice}: è tutto a posto?`
        : `${nome} sulla VPS non risponde (codice ${codice}). Controlla perché, senza riavviare niente senza il mio sì.`, "vps"),
    }, el("span", {}, pallino(ok ? "verde" : "rosso"), " " + nome), el("small", {}, codice === "000" ? "non raggiungibile" : codice)));
  }
  const cont = $("vps-cont");
  cont.replaceChildren();
  const attivi = (v.contenitori || []).filter((c) => c.attivo).length;
  $("vps-conta").textContent = `(${attivi}/${(v.contenitori || []).length} attivi)`;
  for (const c of v.contenitori || []) cont.append(el("div", {
    title: "clic: chiedi a Jarvis di " + c.nome,
    onclick: () => chiediJarvis(c.attivo ? `Il contenitore ${c.nome} sulla VPS è attivo: dimmi lo stato e i log recenti.`
      : `Il contenitore ${c.nome} sulla VPS è giù. Controlla il log e dimmi perché, senza riavviarlo senza il mio sì.`, "vps"),
  }, el("span", {}, pallino(c.attivo ? "verde" : "rosso"), " " + c.nome), el("small", {}, c.dettaglio)));
  for (const k of ["disco", "ram"]) {
    $("vps-" + k).value = v[k] ?? 0;
    $("vps-" + k + "-t").textContent = v[k] != null ? v[k] + "%" : "—";
  }
}

// Una riga per progetto: quando è stata scritta l'ultima nota di memoria, quante caselle aperte,
// quando si è lavorato l'ultima volta. È l'unica cosa che dice se la memoria è
// davvero aggiornata; i tre numeri qui sopra salgono comunque.
function disegnaBattito(b) {
  const corpo = $("mem-progetti").querySelector("tbody");
  const cap = $("mem-battito");
  if (!b || !b.quando) {
    cap.textContent = b && b.perche ? b.perche : "il battito non è mai passato";
    cap.className = "battito no";
    corpo.replaceChildren(el("tr", {}, el("td", { colspan: 5 }, "nessun giro registrato")));
    return;
  }
  cap.textContent = `ultimo giro ${b.quando.slice(11)} · ${b.minuti_fa} min fa` +
    (b.acceso ? "" : " · fermo");
  cap.className = "battito " + (b.acceso ? "ok" : "no");
  const ora = (t) => (t ? t.slice(11, 16) : "—");
  const giorno = (t) => (t && t.slice(0, 10) === oggiISO() ? "oggi" : t ? t.slice(8, 10) + "/" + t.slice(5, 7) : "");
  corpo.replaceChildren(...(b.progetti || []).map((p) => {
    const tardi = p.ore_indietro != null && p.ore_indietro >= 6;
    const apriFile = (percorso) => percorso ? { onclick: (ev) => { ev.stopPropagation(); azione({ tipo: "apri_percorso_sincronia", percorso }, ev.currentTarget); }, class: "cliccabile", "data-solo-mac": "apri_percorso_sincronia" } : {};
    const riga = el("tr", { class: tardi ? "tardi" : "" },
      el("td", {}, (p.semaforo || "") + " " + p.progetto),
      el("td", { title: p.memoria_file ? "clic: apri " + p.memoria_file : (p.memoria || ""), ...apriFile(p.memoria_file) }, giorno(p.memoria) + " " + ora(p.memoria)),
      el("td", { title: `${p.errori ?? "—"} errori da non ripetere` }, p.da_fare != null ? `${p.da_fare} da fare` : "—"),
      el("td", { title: p.lavoro_file ? "clic: apri " + p.lavoro_file : "", ...apriFile(p.lavoro_file) }, ora(p.lavoro)),
      el("td", {}, p.esito || ""));
    if (tardi) {
      riga.lastChild.replaceChildren(
        el("button", {
          class: "icona",
          title: "prepara il comando di salvataggio, senza lanciarlo", "data-solo-mac": "sincronia_comando",
          onclick: async (ev) => {
            const d = await azione({ tipo: "sincronia_comando", progetto: p.progetto }, ev.target);
            if (d && d.comando) {
              const box = $("mem-comando");
              box.hidden = false;
              // un ✕ per richiuderlo (27/09/2026: restava aperto fino alla ricarica)
              box.replaceChildren(el("span", {}, d.comando), " ",
                el("button", { type: "button", class: "icona", title: "Chiudi", onclick: () => { box.hidden = true; } }, "✕"));
            }
          },
        }, "prepara il salvataggio"));
    }
    return riga;
  }));
  if (b.copie && b.copie.length) {
    corpo.append(el("tr", { class: "nota" },
      el("td", { colspan: 5 }, `${b.copie.length} copie di sicurezza dei vecchi MEMORIA.md`)));
  }
}

// Chiavi e anomalie del portiere, nella Squadra (26/09/2026). Il server nuovo manda
// s.portiere (contratto, punto 3): l'elenco intero, con pid, nome, cartella e comando.
// Il server vecchio lo teneva nel battito (memoria.battito.portiere, «note» al posto di
// «da_guardare»): si legge anche quello, così la pagina regge finché il server non riparte.
// Togliere una chiave a chi lavora resta un comando di Jarvis; da qui si ritirano solo le
// prese dei processi già morti (FANTASMA), che non rompono il lavoro di nessuno.
const TIPI_GUASTO = ["FANTASMA", "ABUSIVO"], TIPI_ATTENZIONE = ["MUTO", "SCADUTA", "LUNGA"];
// Richiesta dell'utente (26/09/2026): una shell ssh sulla VPS senza chiave non è un «abusivo» da allarme,
// è un terminale VPS aperto; le note del pannello stesso (del_pannello) si mostrano in grigio e non contano.
function vpsShell(n) { return String(n.tipo || "").toUpperCase() === "ABUSIVO" && (n.chiavi || []).includes("vps-shell"); }
function gravita(n) {
  if (n.del_pannello) return "";
  if (vpsShell(n)) return "attenzione";
  const t = String(n.tipo || "").toUpperCase();
  return TIPI_GUASTO.includes(t) ? "guasto" : TIPI_ATTENZIONE.includes(t) ? "attenzione" : "";
}
function portiereDi(s) {
  const p = s.portiere;
  if (p && Array.isArray(p.da_guardare)) return Object.assign({ vecchio: false }, p);
  const b = s.memoria && s.memoria.battito, v = b && b.portiere;
  if (!v) return null;
  return { vecchio: true, quando: b.quando || "", acceso: !!b.acceso, chiavi_in_giro: v.chiavi ?? 0,
    da_guardare: (v.note || []).map((n) => ({ tipo: n.tipo || "", chiavi: n.chiavi || [], perche: n.perche || "",
      pid: Number((String(n.perche || "").match(/\bpid (\d+)/) || [])[1]) || null })) };
}
function statoPortiere(p) {
  if (!p) return "grigia";
  const g = new Set((p.da_guardare || []).map(gravita));
  return g.has("guasto") ? "guasto" : g.has("attenzione") ? "attenzione" : "ok";
}

function disegnaChiavi(p, perche) {
  const cap = $("chiavi-quando");
  const lista = $("chiavi-note");
  if (!p) {
    cap.textContent = perche || "il portiere non è ancora passato";
    cap.className = "battito no";
    $("chiavi-giro").textContent = "—";
    $("chiavi-guardare").textContent = "—";
    lista.replaceChildren();
    return;
  }
  cap.replaceChildren(p.quando_ts ? etaNodo(p.quando_ts, "visto ") : p.quando ? `visto alle ${p.quando.slice(11)}` : "letto");
  cap.className = "battito " + (p.vecchio && !p.acceso ? "no" : "ok");
  const voci = p.da_guardare || [];
  $("chiavi-giro").textContent = p.chiavi_in_giro ?? 0;
  $("chiavi-guardare").textContent = voci.length;
  if (!voci.length) { lista.replaceChildren(el("li", { class: "vuoto" }, "niente da guardare")); return; }
  lista.replaceChildren(...voci.map((n) => {
    const tipo = String(n.tipo || "—").toUpperCase();
    const shell = vpsShell(n);
    const etichetta = shell ? "VPS" : tipo;
    const motivo = shell ? "terminale VPS aperto senza chiave" : n.perche || "";
    const chi = [n.nome, [n.agente, n.cosa].filter(Boolean).join(": ")].filter(Boolean).join(" · ");
    const domanda = n.pid
      ? `Chi è il processo pid ${n.pid}${n.comando ? ` («${n.comando}»)` : ""}${n.cwd ? ` nella cartella ${n.cwd}` : ""}? ` +
        `Il portiere lo segna ${tipo}: ${n.perche || ""}. Dimmi chi è, cosa sta facendo e se va fermato; non fermarlo senza il mio sì.`
      : `Il portiere segna ${tipo}: ${n.perche || ""}. Cosa vuol dire e cosa va fatto?`;
    return el("li", { class: n.del_pannello ? "n-pannello" : shell ? "n-vps" : "n-" + tipo.toLowerCase() },
      el("b", { class: "cn-tipo" }, etichetta),
      el("span", { class: "cn-pid" }, n.pid ? "pid " + n.pid : ""),
      el("div", { class: "cn-dettagli" },
        chi ? el("b", { class: "cn-chi" }, chi) : "",
        n.del_pannello ? el("small", { class: "cn-pannello" }, "del pannello") : "",
        el("span", {}, (n.chiavi && n.chiavi.length && !shell ? n.chiavi.join(", ") + " · " : "") + motivo),
        n.comando ? el("code", { class: "cn-cmd", title: n.comando }, n.comando) : "",
        n.cwd ? el("small", { class: "cn-cwd", title: n.cwd }, "📁 " + n.cwd) : ""),
      el("div", { class: "cn-azioni" },
        el("button", { class: "piccolo", type: "button", "data-chiedi": domanda, "data-box": "portiere" },
          n.pid ? "Chiedi a Jarvis: chi è?" : "Chiedi a Jarvis"),
        tipo === "FANTASMA" ? el("button", { class: "piccolo pericolo", type: "button", "data-ritira-fantasmi": "",
          disabled: p.vecchio ? "" : null,
          title: p.vecchio ? "Serve il server nuovo del Command Center" : "Toglie le prese dei processi già morti: nessuno perde il lavoro" },
        "Ritira i fantasmi") : ""));
  }));
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-ritira-fantasmi]");
  if (b) azione({ tipo: "portiere", cosa: "ritira_fantasmi" }, b);
});

// Una riga sola in «Claude adesso»: il dettaglio della sincronia sta in Memoria (unica fonte)
function disegnaSincroRiga(b) {
  const a = $("claude-sincro");
  const pr = (b && b.progetti) || [];
  if (!pr.length) { a.textContent = "Sincronia: nessun giro registrato → Memoria"; a.className = "sincro-riga"; return; }
  let ok = 0, att = 0, gua = 0;
  for (const p of pr) { const s = p.semaforo || ""; if (s.includes("🔴")) gua++; else if (s.includes("🟡")) att++; else ok++; }
  a.textContent = `Sincronia: ${ok} in ordine · ${att} attenzione · ${gua} guasto → Memoria`;
  a.className = "sincro-riga " + (gua ? "guasto" : att ? "attenzione" : "ok");
}

function oggiISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function disegnaMemoria(m) {
  if (!m || !("note" in m)) return;
  $("mem-note").textContent = m.note;
  $("mem-sessioni").textContent = m.sessioni;
  $("mem-diario").textContent = m.diario_oggi ? "✓" : "—";
  disegnaBattito(m.battito);
  disegnaSincroRiga(m.battito);
  const lista = $("mem-task");
  lista.replaceChildren();
  if (!(m.sviluppi || []).length) lista.append(el("li", { class: "gruppo" }, "nessuno sviluppo aperto in 02 Sviluppi"));
  for (const s of m.sviluppi || []) {
    lista.append(el("li", { class: "gruppo" }, `${s.nome} · ${s.stato}`));
    if (!s.task.length) lista.append(el("li", {}, "nessun task aperto"));
    for (const t of s.task) lista.append(el("li", {}, t));
  }
}

// «Cosa succede» in cima a Stato (26/09/2026): gli ultimi 25 fatti, i finiti in verde, gli errori
// in rosso, quelli appena avviati con un pallino che pulsa.
function classeEvento(testo) {
  const t = String(testo || "");
  if (/errore|fallit|non risponde|non riesc|rifiutat|non mandat|giù\b/i.test(t)) return "ev-errore";
  if (/^finito\b|rientrata/i.test(t)) return "ev-finito";
  if (/^avviato\b|nuova:/i.test(t)) return "ev-avviato";
  return "";
}
function disegnaEventi(eventi) {
  const voci = (eventi || []).slice(0, 25);
  if (!voci.length) { $("eventi").replaceChildren(el("li", { class: "vuoto" }, "ancora niente")); return; }
  $("eventi").replaceChildren(...voci.map((e) => el("li", { class: classeEvento(e.testo) },
    el("time", {}, e.ora), el("i", { class: "ev-punto", "aria-hidden": "true" }), el("span", {}, e.testo))));
}

// ---------------------------------------------------------------- lavori
// Lista a sinistra (filtri, ricerca, badge chi/durata), dettaglio a destra: richiesta
// intera, risultato grande, e le azioni sul singolo lavoro (26/09/2026).
let ultimiLavori = [];
let filtroLavori = "", cercaLavori = "";
let firmaDettaglio = "";

function durataLavoro(l) {
  if (!l || !l.inizio_ts) return "";
  const s = Math.max(0, Math.round((l.fine_ts || Date.now() / 1000) - l.inizio_ts));
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
function badge(testo, classe = "", titolo = "") {
  return testo ? el("span", Object.assign({ class: "badge " + classe }, titolo ? { title: titolo } : {}), testo) : "";
}

function disegnaLavori(lavori) {
  ultimiLavori = lavori || [];
  const lista = $("lavori");
  const tutti = ultimiLavori;
  const q = cercaLavori.toLowerCase();
  const visti = tutti.filter((l) => (!filtroLavori || l.stato === filtroLavori) &&
    (!q || [l.titolo, l.chi, l.tipo, l.richiesta, l.dove].join(" ").toLowerCase().includes(q)));
  const conta = { "in corso": 0, finito: 0, errore: 0 };
  for (const l of tutti) conta[l.stato] = (conta[l.stato] || 0) + 1;
  $("lavori-conta").textContent = tutti.length ? `${tutti.length} · ${conta["in corso"]} in corso` : "";
  for (const b of document.querySelectorAll("#lavori-filtri button")) {
    const n = b.dataset.filtro ? conta[b.dataset.filtro] || 0 : tutti.length;
    b.dataset.n = n || "";
  }
  $("lavori-pulisci").disabled = !tutti.some((l) => l.stato !== "in corso");
  lista.replaceChildren();
  if (!tutti.length) {
    lista.append(el("li", { class: "vuoto-lavori" }, el("small", {},
      "Nessun lavoro avviato. Un lavoro parte da qui: un comando rapido in ", el("a", { href: "#home" }, "Stato"),
      ", una domanda in ", el("a", { href: "#chat" }, "Chat"), ". Quando parte, lo vedi qui con lo stato in tempo reale.")));
  } else if (!visti.length) {
    lista.append(el("li", { class: "vuoto-lavori" }, el("small", {}, "Nessun lavoro con questo filtro.")));
  }
  for (const l of visti) {
    const classe = l.stato.replace(" ", "-");
    const inCorso = l.stato === "in corso";
    const li = el("li", { class: "lavoro " + classe + (l.id === lavoroScelto ? " scelto" : ""), tabindex: "0", "data-lid": l.id,
      title: l.richiesta || l.titolo, onclick: () => scegliLavoro(l.id),
      onkeydown: (ev) => { if (ev.key === "Enter") scegliLavoro(l.id); } },
      // l'avatarino gira mentre il lavoro è in corso (mockup 26/09/2026, idea 2)
      el("span", { class: "lav-avatar " + classe, "aria-hidden": "true" }, el("b", {}, inizialeLavoro(l))),
      el("span", { class: "lavoro-titolo" }, l.titolo),
      el("span", { class: "etichetta " + classe }, l.stato),
      el("span", { class: "lavoro-badge" },
        badge(l.chi, "chi"), badge(l.tipo, "tipo"), badge("⏱ " + durataLavoro(l), "durata"),
        el("small", {}, l.inizio + (l.fine ? " → " + l.fine : ""))));
    if (inCorso) li.append(barraLavoro(l));
    if (inCorso) {
      li.append(el("button", { class: "icona ferma-lavoro", title: "Ferma il lavoro",
        onclick: (ev) => { ev.stopPropagation(); azione({ tipo: "ferma", id: l.id }, ev.currentTarget); } }, "■ ferma"));
    }
    lista.append(li);
  }
  // il lavoro scelto è sparito (tolto, o il server è ripartito): si torna al vuoto
  if (lavoroScelto && !tutti.some((l) => l.id === lavoroScelto)) mostraDettaglio(null);
}

function inizialeLavoro(l) {
  const n = String(l.chi || l.tipo || l.titolo || "?").trim();
  return (n.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase();
}

// Barra di avanzamento: vera se il lavoro dice a che punto è (percentuale 0-100, oggi il
// server non la manda ancora), altrimenti indeterminata, va e viene.
function barraLavoro(l) {
  const p = Number(l.percentuale ?? l.progresso);
  const vera = Number.isFinite(p) && p >= 0;
  const pc = vera ? Math.min(100, Math.round(p)) : null;
  return el("span", Object.assign({ class: "lav-barra" + (vera ? "" : " indeterminata"), role: "progressbar",
    "aria-label": "avanzamento" }, vera ? { "aria-valuenow": pc, "aria-valuemin": 0, "aria-valuemax": 100 } : {}),
  el("i", vera ? { style: `width:${pc}%` } : {}));
}

function scegliLavoro(id) {
  lavoroScelto = id;
  firmaDettaglio = "";
  disegnaLavori(ultimiLavori);
  caricaLavoro(true);
}

function mostraDettaglio(d) {
  const vista = $("blocco-lavori");
  vista.classList.toggle("con-scelto", !!d);
  $("ris-vuoto").classList.toggle("nascosto", !!d);
  $("ris-dettaglio").classList.toggle("nascosto", !d);
  if (!d) { lavoroScelto = null; firmaDettaglio = ""; vista.classList.remove("ris-intero"); }
}

const testoPulito = (d) => (d.testo || "").replace(/^\(cartella: [^\n]*\)\n\n?/, "");

async function caricaLavoro(primo = false) {
  if (!lavoroScelto) return;
  let d;
  try { d = await api("/api/lavoro/" + lavoroScelto); } catch (e) { mostraDettaglio(null); return; }
  if (d.id !== lavoroScelto) return;
  mostraDettaglio(d);
  $("ris-titolo").textContent = d.titolo;
  const st = $("ris-stato");
  st.className = "etichetta " + d.stato.replace(" ", "-");
  st.textContent = d.stato + (d.codice != null && d.stato === "errore" ? ` · esito ${d.codice}` : "");
  $("ris-meta").replaceChildren(
    badge(d.chi, "chi", "chi ha lavorato"), badge(d.tipo, "tipo"), badge(d.dove, "dove", "cartella di lavoro"),
    badge("⏱ " + durataLavoro(d), "durata", `inizio ${d.inizio}` + (d.fine ? ` · fine ${d.fine}` : "")),
    d.turni ? badge(d.turni + " turni", "tipo", "passaggi di Claude Code") : "",
    d.costo ? badge("$" + d.costo, "tipo", "costo stimato da Claude Code") : "");
  $("ris-richiesta").textContent = d.richiesta || "(nessuna)";
  $("ris-richiesta-conta").textContent = d.richiesta ? `${d.richiesta.length} caratteri` : "";
  if (primo) $("ris-richiesta-box").open = (d.richiesta || "").length < 400;
  const pre = $("ris-testo");
  const inFondo = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  const testo = testoPulito(d);
  pre.textContent = testo || (d.stato === "in corso" ? "In corso…" : "(nessuna uscita)");
  pre.classList.toggle("in-corso", d.stato === "in corso");
  $("ris-righe").textContent = testo ? `${testo.split("\n").length} righe` : "";
  if (primo) pre.scrollTop = 0; else if (inFondo && d.stato === "in corso") pre.scrollTop = pre.scrollHeight;
  const firma = [d.id, d.stato, d.sessione, d.rilanciabile].join("|");
  if (firma !== firmaDettaglio) { firmaDettaglio = firma; disegnaAzioniLavoro(d); }
}

function disegnaAzioniLavoro(d) {
  const chiuso = d.stato !== "in corso";
  const puoContinuare = chiuso && d.sessione && d.interlocutore &&
    (d.interlocutore === "jarvis" || AGENTI.has(d.interlocutore));
  const b = (testo, attr, fn) => el("button", Object.assign({ class: "piccolo", type: "button" }, attr, { onclick: fn }), testo);
  $("ris-azioni").replaceChildren(
    b("⧉ Copia risultato", { title: "Copia il risultato negli appunti" }, async () => {
      const x = await api("/api/lavoro/" + d.id).catch(() => d);
      navigator.clipboard.writeText(testoPulito(x)).then(() => toast("Risultato copiato"));
    }),
    b("⧉ Copia richiesta", {}, () => navigator.clipboard.writeText(d.richiesta || "").then(() => toast("Richiesta copiata"))),
    puoContinuare ? b("💬 Continua in chat", { class: "piccolo primario", title: "Riapre in Chat la stessa conversazione di Claude Code, con il filo" }, () => continuaInChat(d)) : "",
    !puoContinuare ? b("💬 Chiedi a Jarvis", { title: "Prepara in Chat una domanda su questo lavoro" }, () => {
      apriChat("jarvis");
      $("chiedi-testo").value = `Sul lavoro «${d.titolo}» (log: ${d.log.replace(/^\/Users\/[^/]+/, "~")}): `;
      autoAltezza(); $("chiedi-testo").focus();
    }) : "",
    d.rilanciabile ? b("↻ Rilancia", { "data-solo-mac": "rilancia", disabled: chiuso ? null : "", title: "Rifà lo stesso lavoro, con la stessa richiesta" },
      async (ev) => { const r = await azione({ tipo: "rilancia", id: d.id }, ev.currentTarget); if (r && r.lavoro) scegliLavoro(r.lavoro.id); }) : "",
    !chiuso ? b("■ Ferma", { class: "piccolo pericolo" }, (ev) => azione({ tipo: "ferma", id: d.id }, ev.currentTarget)) : "",
    b("⌕ Log nel Finder", { "data-solo-mac": "mostra_log", title: d.log }, (ev) => azione({ tipo: "mostra_log", id: d.id }, ev.currentTarget)),
    el("span", { class: "spazio" }),
    b("⤢", { class: "piccolo icona-q", title: "Ingrandisci il risultato (Esc per tornare)", "aria-pressed": "false" }, (ev) => {
      const v = $("blocco-lavori");
      v.classList.toggle("ris-intero");
      ev.currentTarget.setAttribute("aria-pressed", String(v.classList.contains("ris-intero")));
    }),
    b("Togli dalla lista", { class: "piccolo pericolo", "data-solo-mac": "togli_lavoro", disabled: chiuso ? null : "", title: chiuso ? "Toglie la voce dalla lista; il log resta in lavori/" : "Prima fermalo" },
      async (ev) => {
        if (!confirm(`Togliere «${d.titolo}» dalla lista dei lavori?\n\nIl log resta sul disco in lavori/.`)) return;
        const r = await azione({ tipo: "togli_lavoro", id: d.id }, ev.currentTarget);
        if (r) { mostraDettaglio(null); disegnaLavori(ultimiLavori.filter((x) => x.id !== d.id)); }
      }));
}

// Riapre in Chat il filo di Claude Code di un lavoro: stessa sessione (--resume),
// con richiesta e risposta già in pagina, così si continua da lì.
function continuaInChat(d) {
  const k = d.interlocutore;
  const t = filo(k);
  if (t.sessione !== d.sessione) {
    if (t.attesa) { toast("Quella chat sta aspettando una risposta: riprova tra poco", true); return; }
    const nome = k === "jarvis" ? ASSISTENTE : nomeDi(AGENTI.get(k));
    if (t.messaggi.length && !confirm(`La chat con ${nome} ha già un'altra conversazione.\n\nLa sostituisco con il filo di questo lavoro? La vecchia resta in Claude Code, qui non si vede più.`)) return;
    THREADS[k] = { sessione: d.sessione, avviata: true, messaggi: [
      { chi: "io", testo: d.richiesta || d.titolo, ora: (d.inizio || "").slice(0, 5) },
      { chi: "lui", testo: testoPulito(d).trim() || "(nessuna risposta)", ora: (d.fine || "").slice(0, 5), errore: d.stato !== "finito" }] };
    salvaFili();
  }
  apriChat(k);
  toast("Conversazione ripresa: scrivi e continua");
}

$("lavori-filtri").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-filtro]");
  if (!b) return;
  filtroLavori = b.dataset.filtro;
  for (const x of $("lavori-filtri").children) x.classList.toggle("attivo", x === b);
  disegnaLavori(ultimiLavori);
});
$("lavori-cerca").addEventListener("input", (ev) => { cercaLavori = ev.target.value.trim(); disegnaLavori(ultimiLavori); });
$("lavori-pulisci").addEventListener("click", async (ev) => {
  const n = ultimiLavori.filter((l) => l.stato !== "in corso").length;
  if (!n || !confirm(`Togliere dalla lista ${n} lavori chiusi?\n\nI log restano sul disco in lavori/.`)) return;
  const r = await azione({ tipo: "pulisci_lavori" }, ev.currentTarget);
  if (r) { if (!ultimiLavori.some((l) => l.id === lavoroScelto && l.stato === "in corso")) mostraDettaglio(null); }
});
$("ris-acapo").addEventListener("change", (ev) => $("ris-testo").classList.toggle("senza-acapo", !ev.target.checked));
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") $("blocco-lavori")?.classList.remove("ris-intero");
});

function statoGenerale(s) {
  const problemi = [];
  const v = s.vps || {};
  if (v.raggiungibile === false) problemi.push("VPS non raggiungibile");
  for (const [nome, c] of Object.entries(v.siti || {})) if (!/^[23]/.test(c) && !SITI_IGNORATI.includes(nome)) problemi.push(nome);
  for (const c of v.contenitori || []) if (!c.attivo) problemi.push(c.nome);
  if (s.locale && s.locale.fidata === false) problemi.push("cartella non fidata");
  for (const dove of ["mac", "vps"]) {
    const g = (s.telegram || {})[dove];
    if (g && !g.spento && !g.lettore && !g.occupato) problemi.push("Telegram " + dove.toUpperCase());
  }
  const p = $("pallino-generale");
  if (!("siti" in v)) { p.className = "pallino grigio"; $("testo-generale").textContent = "lettura in corso"; return; }
  p.className = "pallino " + (problemi.length ? "giallo" : "verde");
  $("testo-generale").textContent = problemi.length ? "da guardare: " + problemi.join(", ") : "tutto regolare";
}

// Le liste si ridisegnano solo quando i loro dati cambiano (stesso schema di disegnaAgentiSpazi):
// ridisegnarle a ogni giro faceva perdere focus, hover e clic in corso. Le firme vanno azzerate
// quando si vuole un ridisegno forzato (firme = {}).
let firme = {};
function cambiato(chiave, ...dati) {
  const f = JSON.stringify(dati);
  if (firme[chiave] === f) return false;
  firme[chiave] = f;
  return true;
}

// Dati vecchi: ogni chiave dello stato porta letto_ts (quando il server l'ha letta davvero) ed
// errore_ts (quando l'ultima lettura è fallita). Oltre tre giri del suo intervallo, o dopo un
// errore, il riquadro si mostra in grigio invece che come fresco.
const INTERVALLO_S = { catena: 120, memoria: 120, telefono: 10, claude: 300 };
function datoVecchio(chiave, d, oraTs) {
  if (!d) return "";
  if (d.errore_ts && (!d.letto_ts || d.errore_ts >= d.letto_ts)) return "ultima lettura fallita: " + (d.errore || "");
  if (d.letto_ts && oraTs - d.letto_ts > 3 * INTERVALLO_S[chiave])
    return `dato letto ${Math.round((oraTs - d.letto_ts) / 60)} min fa`;
  return "";
}
function marcaVecchio(ids, perche) {
  for (const id of ids) {
    const n = $(id);
    if (!n) continue;
    n.classList.toggle("dato-vecchio", !!perche);
    if (perche) n.title = "⚠ " + perche; else if (n.title.startsWith("⚠ ")) n.title = "";
  }
}

// Un solo numero sulla voce «Squadra»: agenti al lavoro + lavori in corso.
const contaCatena = { agenti: 0, lavori: 0 };
function disegnaContaCatena() {
  const b = $("conta-catena");
  const n = contaCatena.agenti + contaCatena.lavori;
  b.textContent = n || "";
  b.title = `${contaCatena.agenti} agenti al lavoro · ${contaCatena.lavori} lavori in corso`;
}

// ---------------------------------------------------------------- l'ultimo dato di ogni box
// «Chiedi a Jarvis» da un box allega quello che il box sta mostrando (contratto, punto 5):
// ULTIMO[box] si riempie a ogni giro di aggiorna(). Solo il necessario: il server taglia a 4000 caratteri.
const ULTIMO = {};
const TITOLI_BOX = { locale: "Interruttori", vps: "Server remoto", memoria: "Memoria", portiere: "Chiavi e da guardare",
  lavori: "Lavori", missioni: "Missioni", claude_ora: "Claude adesso", catena: "Catena", salute: "Salute del pannello",
  telefono: "Telefono", sentinella: "Sentinella", tecnico: "Tecnico", agenti: "Agenti e lavagna", scadenze: "Scadenze" };
function riempiUltimo(s, portiere) {
  const l = s.locale || {};
  ULTIMO.locale = { stato_generale: $("testo-generale").textContent, voce: l.voce, voce_stato: l.voce_stato, volto: l.volto,
    mani: l.mani, telefono: l.telefono, schermo_telefono: l.schermo_telefono, chiede_prima: l.chiede_prima, al_pc: l.al_pc,
    fidata: l.fidata, mac: l.mac, telegram: s.telegram };
  ULTIMO.vps = s.vps || null;
  const m = s.memoria || {}, b = m.battito || {};
  ULTIMO.memoria = { note: m.note, sessioni: m.sessioni, diario_oggi: m.diario_oggi,
    battito: { quando: b.quando, acceso: b.acceso, indietro: b.indietro,
      progetti: (b.progetti || []).map((p) => ({ progetto: p.progetto, semaforo: p.semaforo, esito: p.esito,
        memoria: p.memoria, lavoro: p.lavoro, da_fare: p.da_fare })) },
    sviluppi: (m.sviluppi || []).map((x) => ({ nome: x.nome, stato: x.stato, task_aperti: (x.task || []).length })) };
  ULTIMO.portiere = portiere;
  // dei lavori solo id, titolo e stato; il log solo per quelli in errore, perché Jarvis lo possa leggere
  ULTIMO.lavori = (s.lavori || []).map((x) => Object.assign({ id: x.id, titolo: x.titolo, stato: x.stato },
    x.stato === "errore" ? { log: x.log } : {}));
  ULTIMO.missioni = (s.missioni || []).map((x) => ({ id: x.id, stato: x.stato, chi: x.chi }));
  ULTIMO.claude_ora = s.claude_ora ? Object.assign({}, s.claude_ora, { agenti: (s.claude_ora.agenti || []).slice(-12) }) : null;
  ULTIMO.catena = s.catena || null;
  ULTIMO.salute = s.salute || null;
  ULTIMO.telefono = s.telefono ? Object.assign({}, s.telefono, { chiamate: (s.telefono.chiamate || []).slice(0, 5) }) : null;
  ULTIMO.sentinella = s.sentinella || null;
  ULTIMO.scadenze = SCAD.dati;
}

// ---------------------------------------------------------------- spie sulle schede e sui box
// Regole del contratto, punto 7 (26/09/2026). Una spia per scheda nella barra e un alone per box
// (data-stato sulla section.pannello). «grigia» vuol dire: il dato non c'è (server vecchio o non letto).
const TESTO_SPIA = { ok: "in ordine", attenzione: "da guardare", guasto: "qualcosa è giù", lavora: "sta lavorando", grigia: "nessun dato" };
let ultimoStato = null;
function statoBox(id, stato) {
  const n = $(id);
  if (!n) return;
  if (!stato || stato === "grigia") delete n.dataset.stato; else n.dataset.stato = stato;
}
function statoServer(v) {
  v = v || {};
  if (!("siti" in v) || v.configurata === false) return "grigia";
  if (v.raggiungibile === false || (v.contenitori || []).some((c) => !c.attivo) ||
    Object.entries(v.siti || {}).some(([nome, c]) => !/^[23]/.test(c) && !SITI_IGNORATI.includes(nome))) return "guasto";
  return (v.disco ?? 0) > 85 || (v.ram ?? 0) > 85 ? "attenzione" : "ok";
}
const PESO_SPIA = { grigia: 0, ok: 1, lavora: 2, attenzione: 3, guasto: 4 };
function spieSchede(s) {
  const portiere = portiereDi(s);
  const st = {};
  st.chat = Object.values(THREADS).some((t) => t.attesa) ? "lavora" : "ok";
  const rac = s.salute && s.salute.raccoglitori;
  st.home = !Array.isArray(rac) ? "grigia" : rac.some((r) => r.errore) ? "guasto" : "ok";
  const lavoriInCorso = (s.lavori || []).some((l) => l.stato === "in corso");
  const alLavoro = (s.claude_ora && s.claude_ora.lavorando) || lavoriInCorso || (s.agenti_attivi || []).length > 0;
  const sp = statoPortiere(portiere);
  st.agenti = alLavoro ? "lavora" : sp === "grigia" ? "ok" : sp;
  const ms = (s.missioni || []).map((m) => m.stato);
  st.missioni = !s.missioni ? "grigia" : ms.some((x) => x === "in corso" || x === "in avvio") ? "lavora"
    : ms.some((x) => x === "attende conferma" || x === "attende istruzioni") ? "attenzione" : "ok";
  const b = s.memoria && s.memoria.battito;
  const sem = ((b && b.progetti) || []).map((p) => p.semaforo || "");
  st.memoria = !b ? "grigia" : sem.some((x) => x.includes("🔴")) ? "guasto"
    : sem.some((x) => x.includes("🟡")) || !b.acceso ? "attenzione" : "ok";
  st.server = statoServer(s.vps);
  const t = s.telefono;
  st.telefono = !t || !("centralino" in t) ? "grigia"
    : t.centralino && String(t.registrazione || "").toLowerCase() !== "registered" ? "attenzione" : "ok";
  st.tecnico = !ULTIMO.tecnico ? "grigia" : (ULTIMO.tecnico.telefono || {}).collegato ? "ok" : "attenzione";
  st.lavagna = panPronto ? "ok" : "grigia";
  st.vps = vpsInfo && vpsInfo.acceso ? "ok" : "grigia";
  st.terminale = termInfo && Object.values(termInfo.modi || {}).some((m) => m && m.acceso) ? "ok" : "grigia";
  st.scadenze = statoScadenze();
  // 2026-10-05: pagine unite. Le schede di Computer hanno la loro spia; la voce di menu prende la peggiore.
  const peggiore = (...l) => l.reduce((a, b) => ((PESO_SPIA[b] || 0) > (PESO_SPIA[a] || 0) ? b : a), "grigia");
  for (const b of document.querySelectorAll("#pc-schede [data-scheda] .spia")) {
    const v = st[b.parentElement.dataset.scheda] || "grigia";
    b.className = "spia " + v; b.title = TESTO_SPIA[v];
  }
  st.computer = peggiore(st.server, st.vps, st.terminale);
  st.telefono = peggiore(st.telefono, st.tecnico);
  for (const a of document.querySelectorAll(".menu a[data-vista]")) {
    const i = a.querySelector(".spia");
    if (!i) continue;
    const v = st[a.dataset.vista] || "grigia";
    i.className = "spia " + v;
    i.title = TESTO_SPIA[v];
  }
  // i box
  statoBox("box-claude-ora", !s.claude_ora ? "grigia" : s.claude_ora.lavorando ? "lavora" : "ok");
  statoBox("box-chiavi", sp);
  statoBox("box-lavori", lavoriInCorso ? "lavora" : (s.lavori || []).some((l) => l.stato === "errore") ? "attenzione" : "ok");
  statoBox("box-missioni", st.missioni);
  statoBox("box-memoria", st.memoria);
  statoBox("box-vps", st.server);
  statoBox("box-salute", st.home);
  const sent = s.sentinella;
  statoBox("box-sentinella", !sent ? "grigia" : (sent.anomalie || []).length ? "guasto" : "ok");
  statoBox("box-telefono", st.telefono);
  statoBox("box-scad-azienda", statoColonna(SCAD.dati && SCAD.dati.azienda));
  statoBox("box-scad-personali", statoColonna(SCAD.dati && SCAD.dati.personali));
  statoBox("box-scad-task", statoColonna(SCAD.dati && SCAD.dati.task));
}
// la spia della Chat cambia appena parte o arriva una risposta, senza aspettare il giro dopo
function aggiornaSpie() { if (ultimoStato) spieSchede(ultimoStato); }

// /api/stato a pezzi (2026-10-03, prestazioni da internet; condizionale.py sul server). La pagina manda le
// impronte delle sezioni che ha già (?parti=catena.<h>,memoria.<h>,…) e il server rimanda solo quelle cambiate,
// più «parti» con le impronte di tutte. Qui lo stato si rimette insieme ed esce identico a quello intero
// (stesse chiavi, niente «parti»). Server vecchio: ignora ?parti, risponde intero e senza «parti» → da lì in
// poi si chiede lo stato intero come prima. Un'impronta che non torna → una lettura intera.
const PARTI = { si: true, copie: new Map() };
function unisciStato(s) {
  const parti = s.parti;
  delete s.parti;
  if (!parti || typeof parti !== "object") { PARTI.si = false; PARTI.copie.clear(); return s; }
  for (const [k, h] of Object.entries(parti)) {
    if (k in s) continue;
    const c = PARTI.copie.get(k);
    if (!c || c.h !== h) return null;                       // il server dice «invariata» ma la copia non c'è
    s[k] = JSON.parse(c.testo);
  }
  const nuove = new Map();
  for (const [k, h] of Object.entries(parti)) {
    const c = PARTI.copie.get(k);
    nuove.set(k, c && c.h === h ? c : { h, testo: JSON.stringify(s[k]) });
  }
  PARTI.copie = nuove;
  return s;
}
async function leggiStato() {
  if (!PARTI.si) return api("/api/stato");
  const note = [...PARTI.copie].map(([k, c]) => k + "." + c.h).join(",");
  const s = unisciStato(await api("/api/stato?parti=" + encodeURIComponent(note)));
  if (s) return s;
  PARTI.copie.clear();
  return unisciStato(await api("/api/stato?parti=")) || api("/api/stato");
}
// Le scadenze (fino a 170 KB) si rileggevano a ogni giro di aggiorna(), cioè a ogni avviso del flusso.
// Col flusso vivo ora si rileggono quando il flusso porta «scadenze» e, come rete di sicurezza (il cambio di
// giorno non dà avvisi), almeno ogni 60 s. Senza flusso: a ogni giro come prima. Con l'ETag la rilettura
// senza cambi costa un 304 senza corpo.
const SCAD_RETE_MS = 60000;

let aggiornaInCorso = false;
let aggiornaDiNuovo = false;
async function aggiorna(ripeti = false) {
  // il giro prima non è ancora tornato: il sondaggio salta questo, il flusso lo rimette in coda
  if (aggiornaInCorso) { if (ripeti === true) aggiornaDiNuovo = true; return; }
  aggiornaInCorso = true;
  try {
    applicaStato(await leggiStato());
  } catch (e) {
    $("pallino-generale").className = "pallino rosso";
    $("testo-generale").textContent = "Command Center non risponde";
  } finally {
    aggiornaInCorso = false;
    if (aggiornaDiNuovo) { aggiornaDiNuovo = false; setTimeout(() => aggiorna(), 0); }
  }
}

// Le sezioni dentro il messaggio del flusso (2026-10-03, prestazioni da internet; stato_spinto() nel server):
// quando TUTTE le chiavi cambiate arrivano col loro valore (claude_ora, locale, vps…, piccole), si ridisegna con lo
// stato di prima e quei valori, senza rileggere /api/stato. Il resto (ora_ts compresa, per i «dati vecchi») resta
// quello dell'ultima lettura, che il giro di sicurezza rifà comunque ogni 15 s. Una lettura già in corso, uno stato
// che manca o un errore: si torna alla lettura normale.
function applicaSpinta(d) {
  if (aggiornaInCorso || !ultimoStato) return false;
  aggiornaInCorso = true;
  try {
    applicaStato(Object.assign({}, ultimoStato, d.stato, { versione: d.versione }));
    return true;
  } catch (e) {
    return false;
  } finally {
    aggiornaInCorso = false;
    if (aggiornaDiNuovo) { aggiornaDiNuovo = false; setTimeout(() => aggiorna(), 0); }
  }
}

function applicaStato(s) {
    if (s.versione != null) FLUSSO.versione = s.versione;
    disegnaLocale(s.locale || {});
    if (cambiato("vps", s.vps)) disegnaVps(s.vps);
    disegnaTelegram(s.telegram);
    if (cambiato("memoria", s.memoria)) disegnaMemoria(s.memoria);
    if (cambiato("eventi", s.eventi)) disegnaEventi(s.eventi);
    if (cambiato("lavori", s.lavori, lavoroScelto)) disegnaLavori(s.lavori); else aggiornaDurate();
    const missioniAttive = (s.missioni || []).some((m) => !["chiusa", "interrotta", "errore"].includes(m.stato));
    if (cambiato("missioni", s.missioni, missioniAttive ? Math.floor(Date.now() / 10000) : 0)) disegnaMissioni(s.missioni);
    if (cambiato("telefono", s.telefono)) disegnaTelefono(s.telefono);
    if (cambiato("attivi", s.agenti_attivi)) disegnaAgentiAttivi(s.agenti_attivi);
    const alLavoro = (s.claude_ora && s.claude_ora.lavorando) || (s.agenti_attivi || []).length;
    if (cambiato("claudeOra", s.claude_ora, s.catena, s.agenti_attivi, alLavoro ? Date.now() : 0))
      disegnaClaudeOra(s.claude_ora, s.catena, s.agenti_attivi);
    disegnaClaude(s.claude);
    const portiere = portiereDi(s);
    if (cambiato("portiere", portiere)) disegnaChiavi(portiere, s.memoria && s.memoria.battito && s.memoria.battito.perche);
    if (cambiato("salute", s.salute)) disegnaSalute(s.salute);
    if (cambiato("sentinella", s.sentinella)) disegnaSentinella(s.sentinella);
    if (cambiato("modoChat", s.modo_chat)) disegnaModoChat(s.modo_chat);
    // sinapsi: si ridisegna solo quando cambia un id o uno stato
    if (cambiato("sinapsi", (s.comunicazioni || []).map((c) => c.id + "|" + c.stato))) aggiornaSinapsi(s.comunicazioni || []);
    const ora = s.ora_ts || Date.now() / 1000;
    marcaVecchio(["claude-sincro", "mem-progetti", "mem-note", "mem-sessioni", "mem-diario", "mem-task"], datoVecchio("memoria", s.memoria, ora));
    marcaVecchio(["tel-stato", "tel-chiamate"], datoVecchio("telefono", s.telefono, ora));
    const claudeVecchio = datoVecchio("claude", s.claude, ora);
    marcaVecchio(["mot-claude"], claudeVecchio);
    if (claudeVecchio) $("mot-claude").className = "pallino grigio";
    statoGenerale(s);
    if (FLUSSO.stato !== "live" || Date.now() - SCAD.letto > SCAD_RETE_MS) caricaScadenze();
    riempiUltimo(s, portiere);
    ultimoStato = s;
    aggiornaAttivita(s);
    seguiCatenaGiro(s);
    spieSchede(s);
    $("conta-missioni").textContent = (s.missioni || []).filter((m) => ["in corso", "attende conferma", "attende istruzioni", "in avvio"].includes(m.stato)).length || "";
    contaCatena.lavori = (s.lavori || []).filter((l) => l.stato === "in corso").length;
    disegnaContaCatena();
    // il dettaglio del lavoro scelto si rilegge solo se è in corso o se il suo stato è cambiato
    const scelto = (s.lavori || []).find((l) => l.id === lavoroScelto);
    if (scelto && (scelto.stato === "in corso" || firmaDettaglio.split("|")[1] !== scelto.stato)) caricaLavoro();
    caricaMissione();
}

// La durata dei lavori in corso avanza anche quando la lista non si ridisegna.
function aggiornaDurate() {
  for (const l of ultimiLavori) {
    if (l.stato !== "in corso") continue;
    const b = document.querySelector(`#lavori [data-lid="${CSS.escape(l.id)}"] .badge.durata`);
    if (b) b.textContent = "⏱ " + durataLavoro(l);
  }
}

let CAT = {};        // l'ultimo /api/catalogo: menu «/», spunti della chat vuota, verifiche
async function catalogo() {
  const c = await api("/api/catalogo");
  CAT = c;
  const box = $("verifiche");
  // 2026-10-10: la sezione «Verifiche e agenti» si vede solo se ci sono verifiche (configurazione.json) o agenti da lanciare
  box.closest(".verifiche")?.classList.toggle("nascosto", !(c.verifiche || []).length && !(c.agenti || []).length);
  box.replaceChildren(...c.verifiche.map((v) =>
    el("button", { "data-solo-mac": "verifica", onclick: (ev) => azione({ tipo: "verifica", id: v.id }, ev.currentTarget) }, v.nome, el("small", {}, v.descrizione))));
  agenti = c.agenti;
  if (Array.isArray(c.spazi)) SPAZI_LETTI = true;          // anche il catalogo porta gli spazi: la pagina non resta «in lettura»
  disegnaSpazi(c.spazi);
  api("/api/spazi").then((d) => disegnaGruppiArchiviati(d.gruppi_archiviati)).catch(() => {});
  disegnaComandi(c.comandi);
  disegnaComandClaudeCode(c.comandi_claude_code);
  disegnaCollegamenti(c.collegamenti);
  const sel = $("agente-scelto");
  sel.replaceChildren(...agenti.map((a) => el("option", { value: a.id }, a.id)));
  // onchange e non addEventListener: catalogo() ora gira anche dopo ogni risposta, i listener si sommavano
  const desc = () => { const a = agenti.find((x) => x.id === sel.value); $("agente-desc").textContent = (a ? a.descrizione : "") + " · lavora in sola lettura."; };
  sel.onchange = desc;
  desc();
  // gli spunti della chat vuota e il menu «/» seguono il catalogo nuovo
  if (!filo(chatCon).messaggi.length && !filo(chatCon).attesa) disegnaMessaggi();
  if (!$("suggerimenti").classList.contains("nascosto")) mostraSuggerimenti();
}

function orologio() {
  const d = new Date();
  $("ora").textContent = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  $("data").textContent = d.toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" });
  aggiornaEta();
}

document.addEventListener("click", (ev) => {
  const riga = ev.target.closest("[data-int]");
  if (riga && ev.target.classList.contains("switch")) {
    azione({ tipo: "interruttore", nome: riga.dataset.int, acceso: !ev.target.classList.contains("on") }, ev.target);
  }
  if (riga && riga.dataset.tg && ev.target.classList.contains("riaggancia")) {
    azione({ tipo: "telegram_riaggancia", dove: riga.dataset.tg }, ev.target);
  }
  const b = ev.target.closest("[data-azione]");
  if (b) azione({ tipo: b.dataset.azione }, b);
  const a = ev.target.closest("[data-android]");
  if (a) azione({ tipo: "android", cosa: a.dataset.android,
    indirizzo: a.dataset.android === "associa" ? $("and-pair").value : $("and-conn").value, codice: $("and-codice").value }, a);
});
// Aggiornamento forzato (contratto, punto 6): il server rilancia subito il raccoglitore e risponde
// quando ha finito; azione() poi rilegge lo stato. «tutto» dal ↻ in alto, «memoria» da Verifica ora,
// una chiave sola dal ↻ di ogni riga di «Salute del pannello».
$("btn-aggiorna").addEventListener("click", (ev) => azione({ tipo: "aggiorna", cosa: "tutto" }, ev.currentTarget));
$("btn-verifica-memoria").addEventListener("click", (ev) => azione({ tipo: "aggiorna", cosa: "memoria" }, ev.currentTarget));
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-aggiorna]");
  if (b) azione({ tipo: "aggiorna", cosa: b.dataset.aggiorna }, b);
});
$("btn-agente")?.addEventListener("click", (ev) =>
  azione({ tipo: "agente", id: $("agente-scelto").value, richiesta: $("agente-richiesta").value }, ev.currentTarget));




// ---------------------------------------------------------------- missioni
// Dal 23/09/2026 una missione = uno spazio + uno o più progetti + un obiettivo.
// Un solo processo: l'orchestratore lancia gli esperti in parallelo (al massimo N),
// poi il capogruppo verifica. L'albero arriva da agenti.json della missione.
let spaziCat = [];
let SPAZI_LETTI = false, SPAZI_API_OK = false;
let PROG_ARCH = [];               // progetti archiviati con «Archivia progetto» (spazi.json «archiviati»): si ripristinano da qui          // /api/spazi è arrivato almeno una volta (per distinguere «vuoto» da «in lettura»)
const aperte = new Set();        // le missioni con la scheda aperta
const registriAperti = new Set();
const schede = new Map();        // id missione -> nodi della scheda, per non perdere quello che scrivi
const ETICHETTE = { "in avvio": "in-avvio", "in corso": "in-corso", "attende conferma": "attende-conferma",
  "attende istruzioni": "attende-istruzioni", chiusa: "chiusa", interrotta: "interrotta", errore: "errore" };
const ICONA = { "in corso": "🟡", "attende conferma": "⚠", "attende istruzioni": "🔵", "in avvio": "⏳",
  chiusa: "🟢", interrotta: "🔴", errore: "🔴" };
const AG = { "in coda": ["⏳", "in coda"], lavora: ["🟡", "lavora"], consegnato: ["🟢", "consegnato"], errore: ["🔴", "errore"] };

function disegnaSpazi(elenco) {
  spaziCat = elenco || [];
  const sel = $("missione-spazio");
  const prima = sel.value;
  sel.replaceChildren(...(spaziCat.length ? spaziCat.map((s) => el("option", { value: s.id }, s.nome))
    : [el("option", { value: "" }, "nessun progetto ancora")]));
  if (prima && spaziCat.some((s) => s.id === prima)) sel.value = prima;
  disegnaProgettiSpazio();
  disegnaAgentiSpazi();
  if (MISSIONI_ULTIME && !MISSIONI_ULTIME.length) disegnaMissioni(MISSIONI_ULTIME);   // lo stato vuoto segue i progetti
  const sc = $("lav-spazio-catena"), primaSc = sc.value;
  sc.replaceChildren(el("option", { value: "tutti" }, "tutti gli spazi"), ...spaziCat.map((s) => el("option", { value: s.id }, s.nome)));
  sc.value = spaziCat.some((s) => s.id === primaSc) ? primaSc : "tutti";
  disegnaGruppi();      // la colonna di sinistra (layout un'app esterna)
}

function disegnaProgettiSpazio() {
  const s = spaziCat.find((x) => x.id === $("missione-spazio").value) || spaziCat[0];
  const box = $("missione-progetti");
  if (!s || !(s.progetti || []).length) { box.replaceChildren(el("small", { class: "nota stato-vuoto" }, testoNessunProgetto())); return; }
  box.replaceChildren(...s.progetti.map((p, i) => el("label", { title: p.cartella },
    el("input", Object.assign({ type: "checkbox", value: p.id }, i === 0 ? { checked: "" } : {}, p.esiste ? {} : { disabled: "" })),
    " " + p.nome)));
}
$("missione-spazio")?.addEventListener("change", disegnaProgettiSpazio);

function minuti(da, a) {
  if (!da) return "";
  const s = Math.max(0, ((a ? new Date(a) : new Date()) - new Date(da)) / 1000);
  return s < 60 ? Math.round(s) + "s" : Math.round(s / 60) + "m";
}

function rigaAgente(m, a, ultimo) {
  const [ic, testo] = AG[a.stato] || ["·", a.stato];
  const riga = el("li", { class: "ag " + a.stato.replace(" ", "-") },
    el("span", { class: "ramo" }, ultimo ? "└─" : "├─"),
    el("span", { class: "nome" }, a.tipo + (a.capogruppo ? " (capogruppo)" : "")),
    el("span", { class: "modello " + (a.modello || "") }, a.modello || "—"),
    el("span", { class: "st" }, `${ic} ${testo}`),
    el("small", { class: "dur" }, a.inizio ? minuti(a.inizio, a.fine) : ""),
    el("small", { class: "cosa", title: a.esito || a.ultima || a.descrizione || "" },
      a.stato === "lavora" ? (a.ultima || a.descrizione || "") : (a.esito || a.descrizione || "").split("\n")[0].replace(/^[#>*\s]+/, "")));
  if (a.stato === "consegnato" || a.stato === "errore") {
    riga.append(el("button", { class: "piccolo", onclick: () => apriEsito(m.id, a) }, "apri"));
  }
  return riga;
}

function alberoMissione(m) {
  const orch = el("div", { class: "orch" }, el("span", { class: "nome" }, "Orchestratore"),
    el("span", { class: "modello sonnet" }, "sonnet"),
    el("span", { class: "st" }, `${ICONA[m.stato] || "·"} ${m.stato}`),
    el("small", {}, m.modalita ? `${m.modalita} · max ${m.max_paralleli} in parallelo` : ""));
  // a missione finita nessuno «lavora» più e nessun capogruppo è «in attesa» (27/09/2026: un capogruppo restava
  // «⏳ dopo gli esperti» per sempre in una missione chiusa, e sembrava un'orchestrazione ancora aperta)
  const finita = ["chiusa", "interrotta", "errore"].includes(m.stato);
  const righe = (m.agenti || []).map((a) => (finita && a.stato === "lavora"
    ? Object.assign({}, a, { stato: "errore", esito: a.esito || "missione chiusa prima della consegna" }) : a));
  // il capogruppo che non è ancora partito: verifica dopo gli esperti
  for (const c of m.capogruppi || []) {
    if (!righe.some((a) => a.tipo === c)) righe.push({ tipo: c, capogruppo: true, modello: "", stato: finita ? "mai" : "attesa", descrizione: "verifica dopo gli esperti" });
  }
  const ul = el("ul", { class: "albero" });
  righe.forEach((a, i) => {
    const ultimo = i === righe.length - 1;
    if (a.stato === "attesa" || a.stato === "mai") {
      ul.append(el("li", { class: "ag attesa" }, el("span", { class: "ramo" }, ultimo ? "└─" : "├─"),
        el("span", { class: "nome" }, a.tipo + " (capogruppo)"),
        el("span", { class: "st" }, a.stato === "mai" ? "— non partito" : "⏳ dopo gli esperti")));
    } else ul.append(rigaAgente(m, a, ultimo));
  });
  if (!righe.length) ul.append(el("li", {}, el("small", {}, "nessun esperto ancora lanciato")));
  return [orch, ul];
}

function confermeMissione(m) {
  return (m.richieste || []).map((r) => {
    const nota = el("input", { placeholder: "Motivo, se dici no (facoltativo)" });
    return el("div", { class: "conferma" },
      el("b", {}, `⚠ Conferma richiesta: ${r.strumento}`),
      el("div", {}, r.sintesi || ""),
      el("code", {}, r.dettaglio || ""),
      nota,
      el("div", { class: "azioni-riga" },
        el("button", { class: "si", onclick: (ev) => rispondi(ev, true) }, "Sì"),
        el("button", { class: "no", onclick: (ev) => rispondi(ev, false) }, "No"),
        el("small", {}, "alle " + (r.ora || ""))));
    // una risposta sola: dopo, i due pulsanti si spengono e dicono cosa è stato risposto (27/09/2026)
    async function rispondi(ev, ok) {
      const riga = ev.currentTarget.parentElement;
      const d = await azione(Object.assign({ tipo: "conferma", missione: m.id, richiesta: r.id, ok }, ok ? {} : { nota: nota.value }), ev.currentTarget);
      if (!d) return;
      riga.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      riga.append(el("b", {}, ok ? " · risposto: sì" : " · risposto: no"));
      nota.disabled = true;
    }
  });
}

function schedaMissione(m) {
  let s = schede.get(m.id);
  if (!s) {
    const testa = el("summary", {});
    const albero = el("div", { class: "albero-box" });
    const conferme = el("div", { class: "conferme" });
    const reg = el("pre", { class: "uscita alta" }, "…");
    const regBox = el("details", { class: "registro" }, el("summary", {}, "Registro"), reg);
    regBox.addEventListener("toggle", () => { regBox.open ? registriAperti.add(m.id) : registriAperti.delete(m.id); caricaRegistri(); });
    const input = el("input", { placeholder: "Scrivi all'orchestratore" });
    const form = el("form", { class: "azioni-riga istruzione" }, input, el("button", { type: "submit", "data-solo-mac": "istruzione" }, "Invia"));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = await azione({ tipo: "istruzione", missione: m.id, testo: input.value }, ev.submitter);
      if (d && d.messaggio) input.value = "";
    });
    const report = el("small", { class: "report" });
    const chiudi = el("button", { type: "button", class: "piccolo", "data-solo-mac": "chiudi_missione", onclick: (ev) => azione({ tipo: "chiudi_missione", missione: m.id }, ev.currentTarget) }, "");
    const root = el("details", { class: "missione" }, testa, albero, conferme, regBox, form,
      el("div", { class: "azioni-riga" }, report, chiudi));
    root.addEventListener("toggle", () => { root.open ? aperte.add(m.id) : aperte.delete(m.id); });
    s = { root, testa, albero, conferme, reg, regBox, form, report, chiudi, chiavi: "" };
    schede.set(m.id, s);
  }
  const ora = (m.id.split("_")[1] || "").replace(/(\d\d)(\d\d).*/, "$1:$2");
  s.testa.replaceChildren(el("time", {}, ora),
    el("span", { class: "titolo" }, `${m.spazio ? m.spazio + " · " : ""}${m.progetto || ""} — «${(m.obiettivo || "").slice(0, 110)}»`),
    el("span", { class: "etichetta " + (ETICHETTE[m.stato] || "in-corso") }, `${ICONA[m.stato] || ""} ${m.stato}` + ((m.richieste || []).length ? ` · ${m.richieste.length}` : "")));
  s.albero.replaceChildren(...alberoMissione(m));
  const chiavi = (m.richieste || []).map((r) => r.id).join(",");
  if (chiavi !== s.chiavi) { s.conferme.replaceChildren(...confermeMissione(m)); s.chiavi = chiavi; }
  const finita = ["chiusa", "interrotta", "errore"].includes(m.stato);
  s.form.classList.toggle("nascosto", finita);
  s.chiudi.textContent = finita ? "Togli dal pannello" : "Chiudi missione";
  s.report.textContent = m.report ? "Report: " + m.report.split("/").slice(-2).join("/") : "";
  s.root.open = aperte.has(m.id);
  return s.root;
}

let idsMissioni = "";
const richiesteViste = new Set();
let MISSIONI_ULTIME = null;
function disegnaMissioni(missioni) {
  MISSIONI_ULTIME = missioni || [];
  const lista = $("missioni-lista");
  const tutte = missioni || [];
  // si apre da sola la prima volta la missione più recente e quella che chiede una conferma
  if (tutte.length && !schede.size) aperte.add(tutte[0].id);
  // si apre da sola solo quando arriva una richiesta NUOVA: se l'utente la chiude, resta chiusa (27/09/2026)
  for (const m of tutte) for (const r of m.richieste || []) if (!richiesteViste.has(m.id + ":" + r.id)) { richiesteViste.add(m.id + ":" + r.id); aperte.add(m.id); }
  if (!tutte.length) { idsMissioni = ""; lista.replaceChildren(el("small", { class: "stato-vuoto" }, nessunProgettoVero() && SPAZI_LETTI ? testoNessunProgetto() : "Nessuna missione. Scegli spazio e progetti, scrivi l'obiettivo e affidala.")); return; }
  const nodi = tutte.map(schedaMissione);          // aggiorna le schede sul posto
  const ids = tutte.map((m) => m.id).join(",");
  // si rimettono nella lista solo se l'elenco è cambiato: rimetterle ogni volta toglieva il
  // focus a chi stava scrivendo all'orchestratore
  if (ids !== idsMissioni) { lista.replaceChildren(...nodi); idsMissioni = ids; }
  for (const id of [...schede.keys()]) if (!tutte.some((m) => m.id === id)) schede.delete(id);
}

async function caricaRegistri() {
  for (const id of registriAperti) {
    const s = schede.get(id);
    if (!s) continue;
    try {
      const d = await api("/api/missione/" + id);
      const inFondo = s.reg.scrollTop + s.reg.clientHeight >= s.reg.scrollHeight - 30;
      s.reg.textContent = d.registro || "(ancora niente)";
      if (inFondo) s.reg.scrollTop = s.reg.scrollHeight;
    } catch (e) { /* missione scomparsa */ }
  }
}
function caricaMissione() { caricaRegistri(); }

async function apriEsito(mid, a) {
  try {
    const d = await api(`/api/missione/${mid}/agente/${a.id}`);
    $("esito-titolo").textContent = `Esito di ${d.tipo} · ${d.descrizione || ""}`;
    $("esito-testo").textContent = d.esito_intero || "(vuoto)";
    $("esito-box").classList.remove("nascosto");
    $("esito-box").scrollIntoView({ behavior: "smooth" });
  } catch (e) { toast(e.message, true); }
}

$("form-missione")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const progetti = [...document.querySelectorAll("#missione-progetti input:checked")].map((x) => x.value);
  const modo = (document.querySelector("input[name=missione-modo]:checked") || {}).value || "lettura";
  const d = await azione({ tipo: "missione", spazio: $("missione-spazio").value, progetti, obiettivo: $("missione-obiettivo").value,
    max_paralleli: Number($("missione-max").value) || 5, modalita: modo }, ev.submitter);
  if (d && d.missione) { aperte.add(d.missione); $("missione-obiettivo").value = ""; }
});

// Agenti per spazio (ridisegnati il 26/09/2026): uno spazio = una sezione a tendina,
// un progetto = una card, il capogruppo in cima alla sua squadra. Niente intestazione di
// tabella ripetuta: ogni riga dice da sola chi è, cosa fa e con che modello. Se lo spazio
// ha un solo progetto con lo stesso nome («Sito» → «Sito») il
// titolo compare una volta sola. Si ridisegna solo quando cambia qualcosa: così una
// tendina chiusa o il puntatore sopra una riga non si perdono ogni 4 secondi.
let firmaSpazi = "";
let filtroSpazi = "";
const spaziChiusi = new Set(mem_leggi("spaziChiusi", []));
function mem_leggi(k, d) { try { const v = localStorage.getItem("cc." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }
function mem_scrivi(k, v) { try { localStorage.setItem("cc." + k, JSON.stringify(v)); } catch (e) { /* pazienza */ } }
const normNome = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9àèéìòù]+/g, " ").trim();
function stessoNome(a, b) { const x = normNome(a), y = normNome(b); return !!x && !!y && (x === y || x.includes(y) || y.includes(x)); }

function rigaAgenteCatena(s, p, a) {
  const key = `${p.id}:${a.nome}`;
  const ag = (typeof AGENTI !== "undefined" && AGENTI.get(key)) || { key, nome: a.nome, spazio: s.id, capogruppo: a.capogruppo, modello: a.modello };
  const riga = el("div", { class: "riga-catena" + (a.capogruppo ? " capo" : ""), "data-agente": key, tabindex: "0", role: "button",
    title: (a.descrizione || "") + "\n\nclic: chatta · doppio clic: la scheda" },
    avatar(ag),
    el("div", { class: "riga-testo" },
      el("b", {}, nomeDi(ag), a.capogruppo ? el("span", { class: "badge capo" }, "capogruppo") : ""),
      el("small", {}, a.descrizione || "—")),
    el("span", { class: "modello " + (a.modello || "") }, a.modello || "—"),
    el("span", { class: "riga-azioni" },
      el("button", { class: "icona", type: "button", title: "Chatta con " + nomeDi(ag), onclick: (ev) => { ev.stopPropagation(); apriChat(key); } }, "💬"),
      el("button", { class: "icona", type: "button", title: "Apri la scheda", onclick: (ev) => { ev.stopPropagation(); apriScheda(key); } }, "ⓘ")));
  riga.addEventListener("click", () => apriChat(key));
  riga.addEventListener("dblclick", (ev) => { ev.preventDefault(); apriScheda(key); });
  riga.addEventListener("keydown", (ev) => { if (ev.key === "Enter") apriChat(key); if (ev.key === " ") { ev.preventDefault(); apriScheda(key); } });
  return riga;
}

function disegnaAgentiSpazi(forza = false) {
  const box = $("agenti-spazi");
  if (!box) return;
  const q = filtroSpazi.toLowerCase();
  const firma = JSON.stringify([spaziCat, (typeof PAN !== "undefined" && PAN.aspetto) || {}, q, PROG_ARCH]);
  if (!forza && firma === firmaSpazi) { segnaAttivi(); return; }
  firmaSpazi = firma;
  const passa = (a) => !q || [a.nome, a.descrizione, a.modello].join(" ").toLowerCase().includes(q);
  let totale = 0, visti = 0;
  const sezioni = [];
  for (const s of spaziCat) {
    const colore = COLORE_SPAZIO[s.id] || "#599ce7";
    const nAgenti = s.progetti.reduce((n, p) => n + p.agenti.length, 0);
    totale += nAgenti;
    const modelli = {};
    for (const p of s.progetti) for (const a of p.agenti) modelli[a.modello || "—"] = (modelli[a.modello || "—"] || 0) + 1;
    const soloUno = s.progetti.length === 1 && stessoNome(s.nome, s.progetti[0].nome);
    const cards = [];
    for (const p of s.progetti) {
      const agenti = [...p.agenti].sort((x, y) => (y.capogruppo ? 1 : 0) - (x.capogruppo ? 1 : 0)).filter(passa);
      visti += agenti.length;
      if (q && !agenti.length) continue;
      const testa = soloUno ? "" : el("header", { class: "card-testa" },
        el("b", { title: p.cartella }, p.nome),
        el("small", {}, p.esiste ? `${p.agenti.length} agenti` : "cartella non trovata"));
      const corpo = agenti.length ? agenti.map((a) => rigaAgenteCatena(s, p, a))
        : [el("p", { class: "nota card-vuota" }, !p.esiste ? "cartella del progetto non trovata" :
            p.agenti.length ? "nessun agente con questo filtro" : "nessun agente ancora: il capogruppo li crea quando servono")];
      cards.push(el("article", { class: "progetto-card" + (soloUno ? " solo" : "") },
        testa, el("div", { class: "card-righe" }, ...corpo),
        el("footer", { class: "card-piede", title: p.cartella }, "📁 " + p.cartella + " ",
          el("button", { class: "piccolo", type: "button", title: "File, nome, descrizione e archivio del progetto",
            onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); apriSchedaProgetto(p.id); } }, "📎 Progetto e file"))));
    }
    if (q && !cards.length) continue;
    const aperto = q ? true : !spaziChiusi.has(s.id);
    const det = el("details", Object.assign({ class: "spazio-catena", style: `--c:${colore}`, "data-spazio": s.id }, aperto ? { open: "" } : {}),
      el("summary", {},
        el("span", { class: "spazio-emoji", "aria-hidden": "true" }, EMOJI_SPAZIO[s.id] || "◆"),
        el("div", { class: "spazio-titolo" }, el("h4", {}, s.nome),
          el("small", {}, soloUno ? `${nAgenti} agenti` : `${s.progetti.length} progetti · ${nAgenti} agenti`)),
        el("span", { class: "spazio-modelli" }, ...Object.entries(modelli).sort().map(([m, n]) =>
          el("span", { class: "modello " + m, title: `${n} su ${m}` }, `${m} ${n}`))),
        el("button", { class: "piccolo spazio-lavagna", type: "button", title: "Apri lo spazio nella lavagna, capogruppo e squadra già collegati",
          onclick: (ev) => { ev.preventDefault(); ev.stopPropagation();
            const gid = "spazio-" + s.id;
            if (gruppiEffettivi().some((g) => g.id === gid)) apriGruppoInLavagna(gid);
            else toast("Questo spazio non è più un gruppo nella colonna di sinistra", true); } }, "▦ Lavagna"),
        el("span", { class: "freccia-spazio", "aria-hidden": "true" }, "›")),
      el("div", { class: "progetti-griglia" + (soloUno ? " uno" : "") }, ...cards));
    det.addEventListener("toggle", () => {
      if (q) return;
      det.open ? spaziChiusi.delete(s.id) : spaziChiusi.add(s.id);
      mem_scrivi("spaziChiusi", [...spaziChiusi]);
    });
    sezioni.push(det);
  }
  if (!sezioni.length) sezioni.push(spaziCat.length ? el("p", { class: "nota stato-vuoto" }, "Nessun agente con questo filtro.")
    : SPAZI_LETTI ? statoVuotoProgetti() : el("p", { class: "nota stato-vuoto" }, "lettura degli agenti…"));
  if (PROG_ARCH.length) sezioni.push(el("details", { class: "progetti-archiviati" },
    el("summary", {}, `Progetti archiviati (${PROG_ARCH.length})`),
    ...PROG_ARCH.map((x) => el("div", { class: "riga-archiviato" },
      el("b", {}, x.nome), el("small", {}, ` · ${x.cartella}` + (x.archiviato ? ` · archiviato il ${x.archiviato}` : "")), " ",
      el("button", { type: "button", class: "piccolo", "data-solo-mac": "/api/progetto/modifica", onclick: async (ev) => {
        try { await api("/api/progetto/modifica", { cosa: "ripristina", progetto: x.id }); toast(`«${x.nome}» ripristinato`); caricaSpazi(); }
        catch (e) { toast("Non ripristinato: " + e.message, true); } } }, "Ripristina")))));
  box.replaceChildren(...sezioni);
  $("spazi-conta").textContent = spaziCat.length ? (q ? `${visti} di ${totale} agenti` : `${spaziCat.length} spazi · ${totale} agenti`) : "";
  segnaAttivi();
}
$("spazi-cerca")?.addEventListener("input", (ev) => { filtroSpazi = ev.target.value.trim(); disegnaAgentiSpazi(); });
$("spazi-apri")?.addEventListener("click", () => { spaziChiusi.clear(); mem_scrivi("spaziChiusi", []); disegnaAgentiSpazi(true); });
$("spazi-chiudi")?.addEventListener("click", () => {
  for (const s of spaziCat) spaziChiusi.add(s.id);
  mem_scrivi("spaziChiusi", [...spaziChiusi]); disegnaAgentiSpazi(true);
});


// ---------------------------------------------------------------- scadenze (26/09/2026, richiesta dell'utente)
// GET /api/scadenze (contratto, punto 9): {azienda, personali, task}, ogni voce {id, entro, testo,
// tipo, chi, eur, scaduta, giorni, fonte, nota}. Si rilegge a ogni aggiorna() e quando il flusso
// porta la chiave «scadenze». Il server vecchio risponde 404: allora «arriva col server nuovo».
const SCAD = { dati: null, stato: "", inCorso: false, annulla: null, timerAnnulla: null, chiuse: new Set(), letto: 0,
  // controllo e pulizia (contratto, punto 12): selezione, proposte di Jarvis, archivio
  pulizia: false, sel: new Set(), proposte: [], dubbi: [], vista: "aperte", controllo: mem_leggi("scadControllo", null) };
const COLONNE_SCAD = [["azienda", "scad-azienda"], ["personali", "scad-personali"], ["task", "scad-task"]];
async function caricaScadenze() {
  if (SCAD.inCorso || SCAD.stato === "assente") return;
  SCAD.inCorso = true;
  try {
    const percorso = "/api/scadenze?chiuse=30";
    const r = await fetch(percorso, { headers: condizionale(percorso) });   // If-None-Match: 304 se invariate
    if (r.status === 404) { SCAD.stato = "assente"; disegnaScadenze(); return; }
    if (!r.ok && r.status !== 304) return;               // 403 e simili: ci pensa aggiorna() con api()
    const d = JSON.parse(await testoCondizionale(percorso, r));
    SCAD.letto = Date.now();
    SCAD.stato = "ok";
    SCAD.dati = { azienda: d.azienda || [], personali: d.personali || [], task: d.task || [] };
    // il server nuovo manda anche «chiuse» (archivio): è lui che sa fare controllo e chiusure in blocco
    SCAD.pulizia = Array.isArray(d.chiuse);
    SCAD.archivio = d.chiuse || [];
    if (cambiato("scadenze", SCAD.dati, SCAD.archivio, [...SCAD.chiuse])) { disegnaScadenze(); aggiornaSpie(); }
  } catch (e) { /* rete giù: il giro dopo riprova */ }
  finally { SCAD.inCorso = false; }
}
function giorniA(v) {
  if (typeof v.giorni === "number") return v.giorni;
  if (!v.entro) return null;
  return Math.round((new Date(v.entro + "T00:00:00") - new Date(oggiISO() + "T00:00:00")) / 86400000);
}
function gravitaScadenza(v) {
  const g = giorniA(v);
  return v.scaduta || (g != null && g < 0) ? "scaduta" : g != null && g <= 3 ? "vicina" : "";
}
function statoColonna(voci) {
  if (!Array.isArray(voci)) return "grigia";
  const g = voci.map(gravitaScadenza);
  return g.includes("scaduta") ? "guasto" : g.includes("vicina") ? "attenzione" : "ok";
}
function statoScadenze() {
  if (!SCAD.dati) return "grigia";
  return statoColonna([...SCAD.dati.azienda, ...SCAD.dati.personali, ...SCAD.dati.task]);
}
function rigaScadenza(v, colonna) {
  const fonte = v.fonte || colonna;
  const g = giorniA(v), grav = gravitaScadenza(v);
  const data = v.entro ? v.entro.split("-").reverse().slice(0, 2).join("/") : "—";
  const quando = g == null ? "" : g < 0 ? `scaduta da ${-g} g` : g === 0 ? "oggi" : g === 1 ? "domani" : `tra ${g} g`;
  const soldi = typeof v.eur === "number" ? (v.eur ? `${v.eur.toLocaleString("it-IT")} €` : "") : v.eur ? String(v.eur).slice(0, 90) : "";
  // la casella seleziona (per chiuderne tante insieme), il ✓ chiude subito questa
  const chiave = fonte + ":" + v.id;
  const casella = el("input", { type: "checkbox", "aria-label": "Seleziona: " + (v.testo || ""), title: "Seleziona" });
  casella.checked = SCAD.sel.has(chiave);
  casella.addEventListener("change", () => { casella.checked ? SCAD.sel.add(chiave) : SCAD.sel.delete(chiave); contaSelezione(); });
  const fatto = el("button", { type: "button", class: "icona scad-fatto", "data-solo-mac": "scadenze:chiudi", title: "Fatto: chiudi questa", "aria-label": "Chiudi: " + (v.testo || "") }, "✓");
  fatto.addEventListener("click", () => chiudiScadenza(v, fonte, fatto));
  return el("li", { class: "scad-riga " + grav + (SCAD.sel.has(chiave) ? " selezionata" : ""), title: v.id || "" },
    casella,
    el("time", { class: "scad-data" }, el("b", {}, data), el("small", {}, quando)),
    el("div", { class: "scad-testo" }, el("span", {}, v.testo || "—"),
      el("small", {}, [v.tipo === "DEC" ? "decisione" : v.tipo === "DOM" ? "domanda" : v.tipo, v.chi, soldi, v.nota].filter(Boolean).join(" · "))),
    fatto);
}
// i filtri della pulizia valgono per le tre colonne
function passaFiltri(v, fonte) {
  const g = giorniA(v);
  if ($("f-scadute").checked && !(v.scaduta || (g != null && g < 0))) return false;
  if ($("f-vecchie").checked && !(g != null && g < -30)) return false;
  if ($("f-tipo").value && v.tipo !== $("f-tipo").value) return false;
  if ($("f-fonte").value && fonte !== $("f-fonte").value) return false;
  return true;
}
function disegnaScadenze() {
  for (const [k, id] of COLONNE_SCAD) {
    const lista = $(id);
    if (SCAD.stato === "assente") { lista.replaceChildren(el("li", { class: "vuoto" }, "arriva col server nuovo")); continue; }
    if (!SCAD.dati) continue;
    const tutte = SCAD.dati[k].filter((v) => !SCAD.chiuse.has((v.fonte || k) + ":" + v.id));
    const voci = tutte.filter((v) => passaFiltri(v, v.fonte || k));
    lista.replaceChildren(...(voci.length ? voci.map((v) => rigaScadenza(v, k))
      : [el("li", { class: "vuoto" }, tutte.length ? "nessuna con questi filtri" : "niente in scadenza")]));
  }
  for (const f of document.querySelectorAll(".scad-aggiungi")) for (const x of f.elements) x.disabled = SCAD.stato === "assente";
  disegnaPulizia();
}

// ---- controllo e pulizia (contratto, punto 12, 26/09/2026 sera, richiesta dell'utente) ----
function voceDi(chiave) {
  const [fonte, ...resto] = chiave.split(":"), id = resto.join(":");
  return ((SCAD.dati || {})[fonte] || []).find((v) => v.id === id) || null;
}
function contaSelezione() {
  // una voce selezionata che nel frattempo è stata chiusa non conta più
  for (const k of [...SCAD.sel]) if (!voceDi(k)) SCAD.sel.delete(k);
  $("scad-n-sel").textContent = SCAD.sel.size;
  $("scad-chiudi-sel").disabled = !SCAD.pulizia || !SCAD.sel.size;
  for (const r of document.querySelectorAll(".scad-riga")) {
    const c = r.querySelector("input[type=checkbox]");
    if (c) r.classList.toggle("selezionata", c.checked);
  }
}
function disegnaPulizia() {
  const nuovo = SCAD.pulizia;
  $("scad-nota-server").textContent = SCAD.stato === "assente" ? "Le scadenze arrivano col server nuovo."
    : nuovo ? "" : "Controllo, chiusura in blocco e archivio arrivano col server nuovo.";
  $("scad-controllo").disabled = !nuovo || !!SCAD.controllo;
  $("scad-fonte").disabled = !nuovo;
  const d = SCAD.dati;
  if (d) {
    const tutte = [...d.azienda, ...d.personali, ...d.task];
    const scadute = tutte.filter((v) => gravitaScadenza(v) === "scaduta").length;
    $("scad-riassunto").textContent = `${tutte.length} aperte · ${scadute} scadute` + (nuovo ? ` · ${SCAD.archivio.length} chiuse in 30 giorni` : "");
  }
  // proposte di Jarvis: solo quelle ancora aperte
  const prop = SCAD.proposte.filter((p) => voceDi(p.fonte + ":" + p.id));
  $("scad-proposte").classList.toggle("nascosto", (!prop.length && !SCAD.dubbi.length) || SCAD.vista !== "aperte");
  // «Da guardare tu»: le righe fuori dal blocco json, in grigio e senza casella (26/09/2026, richiesta dell'utente)
  let dubbi = $("scad-dubbi");
  if (!dubbi) { dubbi = el("div", { id: "scad-dubbi" }); $("scad-proposte").append(dubbi); }
  dubbi.replaceChildren(...(SCAD.dubbi.length ? [el("h3", {}, "Da guardare tu"),
    ...SCAD.dubbi.map((x) => el("p", { class: "nota", style: "white-space:pre-wrap;margin:4px 0" }, x))] : []));
  $("scad-proposte-lista").replaceChildren(...prop.map((p) => {
    const chiave = p.fonte + ":" + p.id, v = voceDi(chiave);
    const c = el("input", { type: "checkbox", "aria-label": "Seleziona: " + v.testo });
    c.checked = SCAD.sel.has(chiave);
    c.addEventListener("change", () => { c.checked ? SCAD.sel.add(chiave) : SCAD.sel.delete(chiave); disegnaScadenze(); });
    return el("li", { class: "scad-riga proposta" }, c,
      el("time", { class: "scad-data" }, el("b", {}, v.entro ? v.entro.split("-").reverse().slice(0, 2).join("/") : "—"), el("small", {}, p.fonte)),
      el("div", { class: "scad-testo" }, el("span", {}, v.testo || "—"), el("small", { class: "scad-perche" }, "perché: " + (p.perche || "—"))));
  }));
  // archivio degli ultimi 30 giorni, con «riapri»
  $("scad-archivio").classList.toggle("nascosto", SCAD.vista !== "archivio");
  if (SCAD.vista === "archivio") {
    const arch = SCAD.archivio || [];
    $("scad-archivio-lista").replaceChildren(...(!nuovo ? [el("li", { class: "vuoto" }, "arriva col server nuovo")]
      : !arch.length ? [el("li", { class: "vuoto" }, "nessuna chiusa negli ultimi 30 giorni")]
      : arch.map((v) => el("li", { class: "scad-riga chiusa" },
        el("span", {}),
        el("time", { class: "scad-data" }, el("b", {}, v.entro ? v.entro.split("-").reverse().slice(0, 2).join("/") : "—"),
          el("small", {}, v.chiusa_ts ? "chiusa " + new Date(v.chiusa_ts * 1000).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }) : "")),
        el("div", { class: "scad-testo" }, el("span", {}, v.testo || "—"),
          el("small", {}, [v.fonte, v.chiusa_da, v.perche].filter(Boolean).join(" · "))),
        el("button", { type: "button", class: "piccolo", "data-solo-mac": "scadenze:riapri", onclick: async (ev) => {
          const r = await azione({ tipo: "scadenze", cosa: "riapri", fonte: v.fonte, id: v.id }, ev.currentTarget);
          if (r) { firme.scadenze = undefined; caricaScadenze(); } } }, "riapri")))));
  }
  for (const b of document.querySelectorAll("[data-scad-vista]")) b.classList.toggle("attivo", b.dataset.scadVista === SCAD.vista);
  for (const id of ["box-scad-azienda", "box-scad-personali", "box-scad-task"]) $(id).classList.toggle("nascosto", SCAD.vista !== "aperte");
  contaSelezione();
}
for (const id of ["f-scadute", "f-vecchie", "f-tipo", "f-fonte"]) $(id).addEventListener("change", disegnaScadenze);
for (const b of document.querySelectorAll("[data-scad-vista]")) b.addEventListener("click", () => { SCAD.vista = b.dataset.scadVista; disegnaScadenze(); });
$("scad-sel-visibili").addEventListener("click", () => {
  for (const [k] of COLONNE_SCAD) for (const v of (SCAD.dati || {})[k] || []) if (passaFiltri(v, v.fonte || k)) SCAD.sel.add((v.fonte || k) + ":" + v.id);
  disegnaScadenze();
});
$("scad-sel-nessuna").addEventListener("click", () => { SCAD.sel.clear(); disegnaScadenze(); });
$("scad-chiudi-sel").addEventListener("click", async (ev) => {
  const voci = [...SCAD.sel].map((k) => { const [fonte, ...r] = k.split(":"); return { fonte, id: r.join(":") }; });
  if (!voci.length) return;
  const daJarvis = SCAD.proposte.filter((p) => SCAD.sel.has(p.fonte + ":" + p.id));
  const perche = (daJarvis.length ? "già fatta secondo Jarvis: " + daJarvis.map((p) => p.perche).filter(Boolean).join("; ") : "chiusa dall'utente nella pulizia").slice(0, 200);
  if (!confirm(`Chiudere ${voci.length} scadenze?\n\n${perche}\n\nLe ritrovi nell'Archivio e si possono riaprire.`)) return;
  const d = await azione({ tipo: "scadenze", cosa: "chiudi_molte", voci, perche }, ev.currentTarget);
  if (d) {
    toast(`Chiuse ${d.chiuse ?? voci.length}` + (d.errori && d.errori.length ? ` · ${d.errori.length} non chiuse` : ""), !!(d.errori && d.errori.length));
    SCAD.sel.clear();
    SCAD.proposte = SCAD.proposte.filter((p) => !voci.some((x) => x.fonte === p.fonte && x.id === p.id));
    firme.scadenze = undefined; caricaScadenze();
  }
});
// «quali sono già fatte?»: un lavoro di Jarvis; si segue finché non chiude, poi si legge il blocco json
$("scad-controllo").addEventListener("click", async (ev) => {
  const d = await azione({ tipo: "scadenze", cosa: "controllo", fonte: $("scad-fonte").value }, ev.currentTarget);
  // su «azienda» o «tutte» il server spezza il registro in più lavori (tetto di 12000 caratteri l'uno):
  // «lavori» li porta tutti, «lavoro» è il primo
  const ids = (d && (d.lavori || (d.lavoro ? [d.lavoro] : [])) || []).map((l) => l && l.id).filter(Boolean);
  if (ids.length) { SCAD.controllo = { ids, da: Date.now() }; mem_scrivi("scadControllo", SCAD.controllo); seguiControllo(); }
});
async function seguiControllo() {
  const c = SCAD.controllo;
  if (c && c.id && !c.ids) c.ids = [c.id];                     // un controllo salvato dalla versione di prima
  if (!c || !(c.ids || []).length) { SCAD.controllo = null; $("scad-controllo-stato").textContent = ""; disegnaPulizia(); return; }
  $("scad-controllo").disabled = true;
  let risposte;
  try { risposte = await Promise.all(c.ids.map((id) => api("/api/lavoro/" + id))); }
  catch (e) { SCAD.controllo = null; mem_scrivi("scadControllo", null); $("scad-controllo-stato").textContent = "controllo perso: " + e.message; disegnaPulizia(); return; }
  const finiti = risposte.filter((d) => d.stato !== "in corso").length;
  if (finiti < risposte.length) {
    const quanti = risposte.length > 1 ? ` · ${finiti} di ${risposte.length} finiti` : "";
    $("scad-controllo-stato").replaceChildren(el("span", { class: "scad-attesa" }), ` Jarvis sta controllando · ${Math.round((Date.now() - c.da) / 1000)} s${quanti}`);
    setTimeout(seguiControllo, 3000);
    return;
  }
  SCAD.controllo = null; mem_scrivi("scadControllo", null);
  // si uniscono i blocchi ```json``` di tutte le risposte; una risposta illeggibile o in errore si dice
  const proposte = [], problemi = [], dubbi = [];
  risposte.forEach((d, i) => {
    const m = String(d.testo || "").match(/```json\s*([\s\S]*?)```/);
    // quello che sta fuori dal blocco json sono le voci su cui Jarvis non è sicuro: si mostrano com'è
    if (d.stato === "finito") String(d.testo || "").replace(/```json[\s\S]*?```/g, "").replace(/^\(cartella: [^\n]*\)/, "")
      .split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean).forEach((x) => dubbi.push(x));
    let lista = null;
    try { lista = m ? JSON.parse(m[1]) : null; } catch (e) { lista = null; }
    if (d.stato !== "finito") problemi.push(`parte ${i + 1} in errore`);
    else if (!Array.isArray(lista)) problemi.push(`parte ${i + 1} senza un elenco leggibile`);
    else proposte.push(...lista);
  });
  const viste = new Set();
  SCAD.proposte = proposte.filter((p) => p && p.fonte && p.id && !viste.has(p.fonte + ":" + p.id) && viste.add(p.fonte + ":" + p.id));
  SCAD.dubbi = dubbi;
  for (const p of SCAD.proposte) SCAD.sel.add(p.fonte + ":" + p.id);          // arrivano già spuntate
  $("scad-controllo-stato").textContent = (SCAD.proposte.length ? `Jarvis propone di chiuderne ${SCAD.proposte.length}` : "Jarvis non ne ha trovate di già fatte") +
    (problemi.length ? ` · ${problemi.join(", ")}: guarda i lavori in Squadra` : "");
  $("scad-proposte-quando").textContent = oraBreve();
  disegnaScadenze();
}
if (SCAD.controllo) seguiControllo();          // un controllo partito prima di ricaricare la pagina
// chiudere è ottimista: la riga sparisce subito, poi si rilegge; per 10 s si può annullare
async function chiudiScadenza(v, fonte, casella) {
  const chiave = fonte + ":" + v.id;
  SCAD.chiuse.add(chiave);
  disegnaScadenze();
  const d = await azione({ tipo: "scadenze", cosa: "chiudi", fonte, id: v.id }, casella);
  if (!d) { SCAD.chiuse.delete(chiave); disegnaScadenze(); return; }
  SCAD.annulla = { fonte, id: v.id, chiave };
  $("scad-annulla-testo").textContent = `Chiusa «${String(v.testo || "").slice(0, 60)}»`;
  $("scad-annulla").classList.remove("nascosto");
  clearTimeout(SCAD.timerAnnulla);
  SCAD.timerAnnulla = setTimeout(() => { $("scad-annulla").classList.add("nascosto"); SCAD.annulla = null; }, 10000);
  firme.scadenze = undefined;
  await caricaScadenze();
  SCAD.chiuse.delete(chiave);          // il server ora non la manda più
}
$("scad-annulla-btn").addEventListener("click", async (ev) => {
  const a = SCAD.annulla;
  if (!a) return;
  const d = await azione({ tipo: "scadenze", cosa: "riapri", fonte: a.fonte, id: a.id }, ev.currentTarget);
  if (d) { SCAD.annulla = null; clearTimeout(SCAD.timerAnnulla); $("scad-annulla").classList.add("nascosto"); SCAD.chiuse.delete(a.chiave); firme.scadenze = undefined; caricaScadenze(); }
});
for (const f of document.querySelectorAll(".scad-aggiungi")) {
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const testo = f.elements.testo.value.trim();
    if (!testo) return;
    const corpo = { tipo: "scadenze", cosa: "aggiungi", fonte: f.dataset.fonte, testo };
    if (f.elements.entro && f.elements.entro.value) corpo.entro = f.elements.entro.value;   // «Da ricordare» non ha la data (27/09/2026)
    const d = await azione(corpo, ev.submitter);
    if (d) { f.reset(); firme.scadenze = undefined; caricaScadenze(); }
  });
}

// ---------------------------------------------------------------- telefono
function disegnaTelefono(t) {
  if (!t || !("centralino" in t)) return;
  const reg = (t.registrazione || "").toLowerCase();
  $("tel-stato").textContent = !t.centralino ? "centralino spento"
    : reg === "registered" ? "linea di casa agganciata"
    : "centralino acceso, linea " + (t.registrazione || "da verificare");
  const valori = { centralino: t.centralino, ponte_locale: t.ponte_locale,
                   ponte_gemini: t.ponte_gemini, risposta: t.risposta_armata };
  for (const riga of document.querySelectorAll("[data-tel]")) {
    riga.querySelector(".switch").classList.toggle("on", !!valori[riga.dataset.tel]);
  }
  const lista = $("tel-chiamate");
  lista.replaceChildren();
  if (!t.chiamate || !t.chiamate.length) {
    lista.append(el("li", { class: "vuoto-lavori" }, el("small", {},
      "Nessuna chiamata registrata. Una chiamata parte dal modulo qui sopra, o quando qualcuno chiama la linea di casa e Jarvis risponde.")));
    return;
  }
  for (const c of t.chiamate) {
    const quando = (c.quando || "").replace("T", " ").slice(0, 16);
    const li = el("li", {},
      el("span", {}, `${c.chi || c.numero || "sconosciuto"} · ${quando}`),
      el("span", { class: "etichetta " + (c.tipo === "uscita" ? "finito" : "in-avvio") }, c.tipo || "chiamata"),
      el("small", { class: "chiamata-esito" }, (c.esito || "").slice(0, 140) + (c.durata ? ` · ${c.durata}s` : "")));
    for (const d of c.domande || []) li.append(el("small", { class: "chiamata-domande" }, "chiede: " + d));
    lista.append(li);
  }
}

function telefonoAzione(cosa, acceso, bottone) {
  const mappa = { centralino: acceso ? "centralino_avvia" : "centralino_ferma" };
  return azione({ tipo: "telefono", cosa: mappa[cosa] || cosa, acceso }, bottone);
}

document.addEventListener("click", (ev) => {
  const riga = ev.target.closest("[data-tel]");
  if (riga && ev.target.classList.contains("switch")) {
    telefonoAzione(riga.dataset.tel, !ev.target.classList.contains("on"), ev.target);
  }
});

// Tempi relativi che avanzano da soli: un nodo con data-da-ts si riscrive ogni secondo
// (lo fa orologio()), così «x s fa» resta vero anche fra un giro e l'altro.
function testoDurata(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return s + " s";
  if (s < 3600) return Math.floor(s / 60) + " min";
  if (s < 86400) return Math.floor(s / 3600) + " h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0") + " min";
  return Math.floor(s / 86400) + " g";
}
function etaNodo(ts, prima = "", dopo = " fa") {
  return el("span", { "data-da-ts": ts, "data-prima": prima, "data-dopo": dopo }, prima + testoDurata(ts) + dopo);
}
function aggiornaEta() {
  for (const n of document.querySelectorAll("[data-da-ts]"))
    n.textContent = (n.dataset.prima || "") + testoDurata(Number(n.dataset.daTs)) + (n.dataset.dopo ?? " fa");
}

// ---------------------------------------------------------------- salute del pannello
// Contratto, punto 2: i raccoglitori del server, ogni quanto girano, l'ultimo giro andato
// bene, l'errore. ↻ su una riga rilancia solo quel raccoglitore (data-aggiorna).
// per nome del giro sul server, senza «raccogli_» (alcuni giri non hanno chiave: niente ↻ per loro)
const NOMI_RACCOGLITORI = { locale: "Mac e interruttori", locale_pesante: "Mac, letture lente", vps: "VPS",
  memoria: "Memoria e battito", catena: "Catena e scadenze", claude: "Claude Code", telefono: "Telefono",
  telegram: "Telegram", agenti: "Agenti e sessioni", portiere: "Portiere", sentinella: "Sentinella",
  aggiorna_cruscotto: "Cruscotto", aggiorna_mappa_agenti: "Mappa degli agenti", archivia_missioni_vecchie: "Archivio delle missioni",
  guardia_mac: "Guardia del Mac", sorveglia_file: "Sorveglianza dei file",
  assistenza_tick: "Assistenza a distanza" };
function disegnaSalute(x) {
  const lista = $("salute-lista");
  if (!x || !Array.isArray(x.raccoglitori)) {
    $("salute-server").textContent = "";
    lista.replaceChildren(el("li", { class: "vuoto" }, "Il server non manda ancora la salute dei raccoglitori: arriva col server nuovo."));
    return;
  }
  $("salute-server").replaceChildren(x.server_da_ts ? etaNodo(x.server_da_ts, "server acceso da ", "") : "", x.pid ? ` · pid ${x.pid}` : "");
  if (!x.raccoglitori.length) { lista.replaceChildren(el("li", { class: "vuoto" }, "nessun raccoglitore")); return; }
  const ora = Date.now() / 1000;
  lista.replaceChildren(...x.raccoglitori.map((r) => {
    const giro = String(r.nome || r.chiave || "?").replace(/^raccogli_/, "");
    const nome = NOMI_RACCOGLITORI[giro] || NOMI_RACCOGLITORI[r.chiave] || giro;
    const tardi = r.ultimo_ok_ts && r.ogni && ora - r.ultimo_ok_ts > 3 * r.ogni;
    const stato = r.errore ? "guasto" : !r.ultimo_ok_ts || tardi ? "attenzione" : "ok";
    return el("li", { class: "sal " + stato, title: r.nome || "" },
      el("i", { class: "spia " + stato }),
      el("div", { class: "sal-testo" },
        el("b", {}, nome),
        el("small", {}, r.ogni ? `ogni ${r.ogni} s · ` : "", r.ultimo_ok_ts ? etaNodo(r.ultimo_ok_ts, "ultimo ok ") : "mai andato bene"),
        r.errore ? el("small", { class: "sal-errore" }, r.errore) : ""),
      r.chiave ? el("button", { class: "icona", type: "button", "data-aggiorna": r.chiave, title: "Rilancia adesso: " + nome }, "↻") : "");
  }));
}

// ---------------------------------------------------------------- sentinella
// Richiesta dell'utente del 26/09/2026: il giro di controllo del server (s.sentinella), le
// anomalie aperte, l'ultima pulizia e l'ultimo rapporto di Jarvis. Senza il campo: «sentinella non attiva».
function classeAnomalia(a) {
  // 28/09/2026: guardava a.tipo (portiere/sincronia/telegram/salute/...), che non contiene mai
  // una di queste parole — quindi ogni anomalia usciva sempre gialla, mai rossa. Ora guarda il
  // testo vero: l'emoji del semaforo se c'è (sincronia), altrimenti le parole di un guasto reale.
  const testo = String((a && a.testo) || a || "");
  if (/🔴/.test(testo)) return "guasto";
  if (/🟡/.test(testo)) return "attenzione";
  return /gi[uù]|errore|guast|fermo|mort[oa]|down\b|rott[oa]|fallit|non esiste|non aggancia|non risponde|timeout/i.test(testo)
    ? "guasto" : "attenzione";
}
function disegnaSentinella(x) {
  const sw = $("sent-interruttore").querySelector(".switch");
  const lista = $("sent-anomalie");
  if (!x) {
    sw.classList.remove("on"); sw.disabled = true; $("sent-giro").disabled = true;
    $("sent-quando").textContent = "";
    lista.replaceChildren(el("li", { class: "vuoto" }, "sentinella non attiva"));
    $("sent-rapporto-box").classList.add("nascosto");
    return;
  }
  sw.disabled = false; $("sent-giro").disabled = false;
  sw.classList.toggle("on", !!x.acceso);
  $("sent-quando").replaceChildren(x.quando_ts ? etaNodo(x.quando_ts, "ultimo giro ") : "nessun giro ancora",
    x.nuove ? ` · ${x.nuove} nuove` : "", x.acceso ? "" : " · spenta");
  const pul = $("sent-pulizia");
  if (pul) pul.replaceChildren(x.ultima_pulizia_ts ? el("span", {}, etaNodo(x.ultima_pulizia_ts, "ultima pulizia "), ": " + (x.ultima_pulizia || "")) : "");
  const an = x.anomalie || [];
  lista.replaceChildren(...(an.length ? an.map((a) => el("li", { class: "n-" + classeAnomalia(a), title: a.chiave || "" },
    el("b", { class: "cn-tipo" }, String(a.tipo || "—").toUpperCase()),
    el("span", {}, a.testo || a.chiave || ""),
    a.da_ts ? el("small", {}, etaNodo(a.da_ts, "da ", "")) : "")) : [el("li", { class: "vuoto" }, "nessuna anomalia")]));
  const box = $("sent-rapporto-box");
  box.classList.toggle("nascosto", !x.ultimo_rapporto);
  if (x.ultimo_rapporto) {
    $("sent-rapporto").replaceChildren(markdown(x.ultimo_rapporto));
    $("sent-rapporto-quando").replaceChildren(x.ultimo_rapporto_ts ? etaNodo(x.ultimo_rapporto_ts) : "");
  }
}
$("sent-interruttore").querySelector(".switch").addEventListener("click", (ev) =>
  azione({ tipo: "sentinella", cosa: "acceso", valore: !ev.currentTarget.classList.contains("on") }, ev.currentTarget));
$("sent-giro").addEventListener("click", (ev) => azione({ tipo: "sentinella", cosa: "giro" }, ev.currentTarget));

function durata(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

// La catena degli agenti (scheda «Schema agenti Jarvis»): Jarvis → i suoi agenti →
// un CEO per progetto → i suoi specialisti. Si accende chi sta lavorando adesso.
function disegnaClaude(c) {
  const p = $("mot-claude");
  if (!c) { p.className = "pallino grigio"; p.title = "lettura in corso"; return; }
  p.className = "pallino " + (c.collegato ? "verde" : "rosso");
  p.title = c.collegato ? "Claude Code collegato (" + c.metodo + ")" : "Claude Code non collegato: " + (c.errore || "fai claude auth login");
}

function disegnaClaudeOra(c, catena, missioni) {
  const p = $("claude-pallino"), t = $("claude-stato"), a = $("claude-azione"), r = $("claude-richiesta");
  const lista = $("claude-catena");
  if (!c) { p.className = "pallino grigio"; t.textContent = "nessun segnale"; a.textContent = ""; r.textContent = ""; }
  else {
    p.className = "pallino " + (c.lavorando ? "verde" : "grigio");
    t.textContent = c.lavorando ? "al lavoro" + (c.richiesta_ts ? " · " + durata(c.richiesta_ts) : "") : "fermo";
    r.textContent = c.richiesta ? "Richiesta: " + c.richiesta : "";
    a.textContent = c.lavorando && c.azione ? `Sta facendo: ${c.azione}${c.dettaglio ? " · " + c.dettaglio : ""}` : "";
  }
  const attivi = {};
  for (const ag of (c && c.agenti) || []) {
    if (ag.stato === "attivo" && !attivi[ag.nodo || ag.tipo]) attivi[ag.nodo || ag.tipo] = ag;
  }
  // il CEO che guida una missione del Command Center lavora anche se la chat è ferma
  for (const m of missioni || []) {
    const chi = m.chi === "orchestratore" ? `orchestratore · ${m.spazio || m.progetto}` : m.chi;
    if (chi && chi !== "Jarvis" && !attivi[chi]) attivi[chi] = { ts: m.ts, descrizione: "missione, " + m.stato + ((m.esperti || []).length ? ` · ${m.esperti.length} esperti al lavoro` : "") };
  }
  const usati = new Set();
  // una lettura della catena fallita prima della prima riuscita porta solo {errore, letto_ts}
  const cat = Object.assign({ jarvis: [], progetti: [], modelli: {} }, catena || {});
  const nodo = (liv, nome, nota, chiave, acceso) => {
    const ag = (chiave && attivi[chiave]) || (acceso ? { ts: 0 } : null);
    if (ag) usati.add(chiave);
    const testo = ag && ag.ts ? `attivo ${durata(ag.ts)}${ag.descrizione ? " · " + ag.descrizione : ""}` : nota;
    const mod = chiave && cat.modelli && cat.modelli[chiave];
    // avatar da 48 px (26/09/2026): Jarvis con la sua J, gli altri col volto «beam» del loro ruolo
    const av = liv === 0 ? el("span", { class: "avatar avatar-j", "aria-hidden": "true" }, "J")
      : avatar({ key: "catena:" + nome, nome, spazio: "" });
    av.classList.toggle("al-lavoro", !!ag);
    return el("li", { class: ag ? "attivo" : "", style: `--liv:${liv}` }, av,
      el("div", { class: "cat-testo" },
        el("span", { class: "cat-riga" }, el("span", { class: "nome" }, nome), mod ? el("span", { class: "modello " + mod }, mod) : ""),
        el("small", {}, testo || "")));
  };
  const righe = [nodo(0, ASSISTENTE, "sessione principale", null, c && c.lavorando)];
  for (const n of cat.jarvis) righe.push(nodo(1, n, "fermo", n));
  // i progetti con capogruppo ed esperti stanno sotto, in «Agenti per spazio» (da spazi.json)
  for (const [k, ag] of Object.entries(attivi)) {          // agenti fuori catena
    if (!usati.has(k)) righe.push(nodo(1, k || "agente", "", k));
  }
  lista.replaceChildren(...righe);
  contaCatena.agenti = Object.keys(attivi).length;
  disegnaContaCatena();
}



function disegnaSessioni(a) {
  const lista = $("sessioni-lista");
  if (!lista) return;
  const s = (a && a.sessioni) || [];
  const q = $("sessioni-quando");
  if (q) q.textContent = (a && a.aggiornato) ? "aggiornato " + new Date(a.aggiornato * 1000).toTimeString().slice(0, 8) : "";
  lista.replaceChildren();
  if (!s.length) {
    lista.append(el("li", {}, el("small", {}, "Nessuna sessione di Claude aperta adesso.")));
    return;
  }
  for (const r of s) {
    // ASCOLTO (l'utente, 26/09/2026): Telegram, telefono, voce, Cloud aspettano apposta; ferma è il loro normale
    const stato = r.ascolto ? "ASCOLTO" : (r.lavora ? "LAVORA" : "FERMA");
    const riga = [
      el("span", {}, "pid " + r.pid + " · " + (r.dove || r.cosa || "—")),
      el("br"),
    ];
    if (r.nome) riga.push(el("small", { style: "font-weight:bold" }, r.nome), el("br"));
    riga.push(el("small", {}, "acceso da " + r.acceso + " · processore " + r.cpu + "s"));
    lista.append(el("li", { style: "cursor:default" },
      el("span", {}, ...riga),
      el("span", { class: "etichetta " + (r.ascolto ? "ascolto" : r.lavora ? "in-corso" : "chiusa") }, stato)));
  }
  if (a && a.orfani) lista.append(el("li", {}, el("small", {}, a.orfani + " recapiti orfani (processi morti)")));
}

function disegnaAgentiAttivi(attivi) {
  const lista = $("agenti-attivi");
  lista.replaceChildren();
  if (!attivi || !attivi.length) {
    lista.append(el("li", { class: "gruppo" }, "nessun agente al lavoro"));
    return;
  }
  for (const a of attivi) {
    lista.append(el("li", { class: "gruppo" }, `${a.chi} · ${a.spazio ? a.spazio + " · " : ""}${a.progetto} · ${a.stato}`));
    for (const e of a.esperti || []) lista.append(el("li", {}, `${e.nome} · ${minuti(e.inizio)} · ${e.ultima || e.descrizione || ""}`));
    if (a.ultimo && !(a.esperti || []).length) lista.append(el("li", {}, a.ultimo));
  }
}

function disegnaCollegamenti(collegamenti) {
  const nomi = { guida_telefono: "Guida telefonate", cruscotto: "Cruscotto", odoo: "Odoo", n8n: "n8n", avvia_cloud: "un'app esterna (apri app)" };
  $("collegamenti").replaceChildren(...(collegamenti || []).map((c) =>
    el("button", { "data-apri": c.id }, nomi[c.id] || c.nome)));
}

function disegnaComandi(comandi) {
  $("comandi").replaceChildren(...(comandi || []).map((c) =>
    el("button", { "data-solo-mac": "comando", onclick: (ev) => azione({ tipo: "comando", id: c.id }, ev.currentTarget) },
      c.nome, el("small", {}, c.descrizione))));
}

function disegnaComandClaudeCode(comandi) {
  $("comandi-claude").replaceChildren(...(comandi || []).map((c) =>
    el("button", { "data-solo-mac": "comando_claude_code", onclick: (ev) => azione({ tipo: "comando_claude_code", id: c.id }, ev.currentTarget),
                   title: c.descrizione },
      c.nome, el("small", {}, c.descrizione))));
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-apri]");
  if (b) azione({ tipo: "apri", id: b.dataset.apri }, b);
  const d = ev.target.closest("[data-azione-diretta]");
  if (d) azione({ tipo: d.dataset.azioneDiretta }, d);
});

$("form-chiamata")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const numero = $("tel-numero").value.trim();
  const chi = $("tel-chi").value.trim();
  const incarico = $("tel-incarico").value.trim();
  if (!confirm(`Chiamo ${numero}${chi ? " (" + chi + ")" : ""}?\n\nIncarico: ${incarico}`)) return;
  const d = await azione({ tipo: "telefono", cosa: "chiama", numero, chi, incarico, conferma: true }, ev.submitter);
  if (d && d.lavoro) { $("tel-numero").value = ""; $("tel-chi").value = ""; $("tel-incarico").value = ""; }
});

// ---- il banco tecnico dell'app Android ----
// Si legge solo quando si apre la sezione: interrogare il telefono con adb costa
// qualche secondo, e chi guarda il resto del pannello non lo deve pagare.

function disegnaTecnico(d) {
  const t = d.telefono || {};
  const schede = $("tec-schede");
  schede.replaceChildren();
  if (!t.collegato) {
    $("tec-stato").textContent = "Telefono non collegato";
    schede.append(el("dt", {}, "Perché"), el("dd", {}, t.perche || "—"));
    document.querySelector('[data-tec="debug"] .switch').classList.remove("on");
    return;
  }
  $("tec-stato").textContent = `${t.modello || "telefono"} · app ${t.versione || "?"} (build ${t.codice || "?"})`;
  const voci = [
    ["Android", t.android || "?"],
    ["Servizio Jarvis", t.servizio ? "acceso" : "spento"],
    ["Può usare il telefono", t.accessibilita ? "sì" : "no"],
    ["Batteria", t.batteria == null ? "?" : t.batteria + "%"],
  ];
  for (const [k, v] of voci) schede.append(el("dt", {}, k), el("dd", {}, v));
  document.querySelector('[data-tec="debug"] .switch').classList.toggle("on", !!t.debug);
  $("tec-log").textContent = (d.log || []).join("\n") || "Nessuna diagnosi. Col modo tecnico spento è normale: l'app non manda niente fuori.";
}

let tecnicoInCorso = false;
async function caricaTecnico() {
  if (tecnicoInCorso) return;
  tecnicoInCorso = true;
  $("tec-stato").textContent = "lettura del telefono…";
  try {
    const d = await api("/api/tecnico", null, 30000);
    ULTIMO.tecnico = Object.assign({}, d, { log: (d.log || []).slice(-40) });
    disegnaTecnico(d);
    aggiornaSpie();
  } catch (e) {
    $("tec-stato").textContent = "Non riesco a leggere il telefono: " + e.message;
  } finally {
    tecnicoInCorso = false;
  }
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-tec]");
  if (!b) return;
  if (b.dataset.tec === "debug" && ev.target.classList.contains("switch")) {
    await azione({ tipo: "tecnico", cosa: "debug", acceso: !ev.target.classList.contains("on") }, ev.target);
    caricaTecnico();
  } else if (b.dataset.tec === "riavvia") {
    await azione({ tipo: "tecnico", cosa: "riavvia" }, b);
    caricaTecnico();
  } else if (b.dataset.tec === "ricarica") {
    caricaTecnico();
  }
});

// ---- La conversazione a voce: la scheda «Voce» della pagina Chat (fino al 2026-10-05 un riquadro di Stato) ----
// L'ultimo messaggio sta in cima: così si vede lo stato senza scorrere in fondo ogni volta.
// La scheda si apre e si chiude in voce-chat.js (CCVoceChat); con la scheda chiusa il riquadro non si rilegge.
let chatVoceUltima = "";
let chatVoceInCorso = false;
// «sto scrivendo» nella chat a voce: mentre la voce dice che Jarvis pensa, oppure dopo un
// messaggio mandato da qui finché non arriva una battuta nuova di Jarvis (tetto 2 minuti).
let vocePensa = false;
// 2026-10-07: si conta dall'ora dell'ultima battuta, non dal numero: la storia è una finestra fissa di 150 righe
// (la copia del Mac ne ha migliaia), quindi il numero non cresceva mai e i puntini restavano per 2 minuti.
let voceAspetta = null;          // { da: ms, segno: ts dell'ultima battuta vista quando hai mandato }
let chatVoceSegno = "";
function disegnaAttesaVoce() {
  const box = $("chat-voce-attesa");
  if (!box) return;
  if (voceAspetta && Date.now() - voceAspetta.da > 120000) voceAspetta = null;
  const si = vocePensa || !!voceAspetta;
  if (si && !box.firstChild) box.append(el("small", {}, ASSISTENTE), bollaScrive(ASSISTENTE));
  box.classList.toggle("nascosto", !si);
}
async function aggiornaChatVoce() {
  const box = $("chat-messages");
  // niente lettura se il riquadro non si vede o la chiamata di prima non è tornata
  if (!box || chatVoceInCorso || (box.offsetParent === null && chatVoceUltima)) return;
  chatVoceInCorso = true;
  let d;
  try { d = await api("/api/chat/storia"); } catch (e) { return; } finally { chatVoceInCorso = false; }
  const battute = (d && d.battute) || [];
  chatVoceSegno = battute.length ? String(battute[battute.length - 1].ts || "") : "";
  // 2026-10-05: da dove arriva la conversazione e dove va «Manda» (voce del Mac o ponte del telefono sulla VPS);
  // voce-chat.js (dettato e 📞 del riquadro) segue le battute da questo evento, senza un secondo giro di letture
  chatVoceDisegnaFonte(d || {});
  try { window.dispatchEvent(new CustomEvent("cc:chat-voce", { detail: { battute, macchina: d && d.macchina, voce: d && d.voce } })); } catch (e) { /* niente */ }
  if (voceAspetta && battute.some((b) => b.chi !== "utente" && String(b.ts || "") > voceAspetta.segno)) voceAspetta = null;
  disegnaAttesaVoce();
  const firma = battute.length + "|" + (battute.length ? battute[battute.length - 1].ts + battute[battute.length - 1].testo : "");
  if (firma === chatVoceUltima) return;
  chatVoceUltima = firma;
  const inAlto = box.scrollTop < 40;
  box.replaceChildren();
  if (!battute.length) {
    box.append(el("div", { style: "color:var(--tenue);font-size:13px" }, "La conversazione a voce compare qui appena parli con Jarvis (dopo l'avvio della voce con Talk to Jarvis)."));
    return;
  }
  // battute di Jarvis vicine (entro 25 secondi) stanno nello stesso fumetto
  const gruppi = [];
  let corrente = null, ultimoTs = 0;
  for (const b of battute) {
    const t = Date.parse(b.ts) || 0;
    if (corrente && corrente.chi === b.chi && (corrente.origine || "") === (b.origine || "") && t - ultimoTs < 25000) {
      corrente.testo += " " + b.testo;
    } else {
      corrente = { chi: b.chi, ts: b.ts, testo: b.testo, origine: b.origine || "" };
      gruppi.push(corrente);
    }
    ultimoTs = t;
  }
  // gli ultimi 40 fumetti (era 5 quando stava in Stato), più recente per primo
  for (const g of gruppi.slice(-40).reverse()) {
    const tuo = g.chi === "utente";
    const nodo = el("div", { class: "chat-voce", style: "margin:6px 0;display:flex;flex-direction:column;align-items:" + (tuo ? "flex-end" : "flex-start") });
    nodo.append(
      el("small", { style: "color:var(--tenue);font-size:11px" }, (tuo ? nomeUtente() : ASSISTENTE) + " · " + (g.ts || "").slice(11, 16) +
        (ORIGINE_VOCE[g.origine] ? " · " + ORIGINE_VOCE[g.origine] : "")),
      el("div", { style: "max-width:80%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;" +
        (tuo ? "background:var(--rialzo-2);border:1px solid var(--linea-2)" : "background:var(--rialzo);border:1px solid var(--linea)") }, g.testo));
    box.append(nodo);
  }
  if (inAlto) box.scrollTop = 0;
}
aggiornaChatVoce();
// da dove viene ogni battuta (chat_ponte.py unisce la voce del Mac e quella della VPS)
const ORIGINE_VOCE = { mac: "voce del Mac", telefono: "telefono", sito: "sito" };
function chatVoceDisegnaFonte(d) {
  const p = $("chat-voce-fonte");
  if (!p || !d.macchina) return;
  const t = d.macchina === "vps"
    ? "voce: telefono (VPS)" + (d.voce ? "" : " · spenta") + " · Scrivi va nella stessa conversazione del telefono"
    : "voce: Mac" + (d.voce ? " · accesa" : " · spenta: la accendo io") + " · ascolto: Cmd destro tenuto premuto";
  if (p.textContent !== t) p.textContent = t;
}

// ---- Scrivere nella stessa chat della voce (arriva a Jarvis come se l'avesse sentito) ----
$("form-chat-voce")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const campo = $("chat-voce-testo");
  const testo = campo.value.trim();
  if (!testo) return;
  const d = await azione({ tipo: "chat_voce_manda", testo }, ev.submitter);
  if (d) { campo.value = ""; voceAspetta = { da: Date.now(), segno: chatVoceSegno }; disegnaAttesaVoce(); aggiornaChatVoce(); }
});

// =====================================================================
// Layout a tre colonne, stile un'app esterna (24/09/2026)
//   sinistra: agenti per spazio, gruppi a tendina, trascinabili
//   centro:   chat con Jarvis o con un agente (Claude Code, sola lettura)
//   destra:   lavagna (dipendenze) e desktop della VPS, anche a pagina intera
// Lo stato della disposizione sta sul server in pannello.json (/api/pannello);
// la conversazione di ogni interlocutore sta nel browser (localStorage).
// =====================================================================

const mem = {
  leggi(k, d) { try { const v = localStorage.getItem("cc." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  scrivi(k, v) {
    if (window.__ccSessioneFinita) return true;     // ponte.js: sessione finita, le chat appena cancellate non si riscrivono
    try { localStorage.setItem("cc." + k, JSON.stringify(v)); return true; }
    catch (e) {
      if (!mem.avvisato) { mem.avvisato = true; console.warn(`Command Center: non riesco a salvare «${k}» nel browser (${e.name}): spazio pieno o bloccato`); }
      return false;
    }
  },
};
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : "10000000-1000-4000-8000-100000000000".replace(/[018]/g,
  (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));

// ------------------------------------------------ pannello.json
// Una lavagna per gruppo (PAN.lavagne[id]), non più una sola: cliccare un
// gruppo apre solo la sua, senza mischiare tutti gli agenti insieme. "generale"
// è quella di chi arriva dal menu senza passare da un gruppo, e quella di
// «Tutta la catena». lav() è quella che si vede adesso (lavagnaAttiva).
const LAVAGNA_VUOTA = () => ({ nodi: [], fili: [], vista: { x: 0, y: 0, zoom: 1 } });
let PAN = { gruppi: [], aspetto: {}, lavagne: { generale: LAVAGNA_VUOTA() } };
let panPronto = false;
let lavagnaAttiva = "generale";
let lavagnaTitolo = "";
function lav() {
  if (!PAN.lavagne) PAN.lavagne = {};
  if (!PAN.lavagne[lavagnaAttiva]) PAN.lavagne[lavagnaAttiva] = LAVAGNA_VUOTA();
  return PAN.lavagne[lavagnaAttiva];
}
function vaiALavagna(id, titolo) {
  if (id !== lavagnaAttiva) { LAV.sel = null; LAV.selFilo = null; }   // una scelta vale solo nella sua lavagna (27/09/2026)
  lavagnaAttiva = id;
  lavagnaTitolo = id === "generale" ? "" : (titolo || (PAN.lavagne[id] || {}).titolo || id);
  mem.scrivi("lavagnaAttiva", id);
  mem.scrivi("lavagnaTitolo:" + id, lavagnaTitolo);
  // audit 02/10/2026: il titolo sta anche in pannello.json, così lo vedono le altre schede e gli altri browser
  if (id !== "generale" && titolo && panPronto && lav().titolo !== titolo) { lav().titolo = titolo; salvaPannello(); }
  const t = $("lav-titolo");
  if (t) t.textContent = lavagnaTitolo;
  aggiornaAllineamento();
}
// ------------------------------------------------ salvataggio per scheda (audit 02/10/2026)
// Prima: tutto il pannello in un POST con la versione letta; con un'altra scheda (o lo zoom, o «Centra»)
// in mezzo il server rispondeva 409 e la pagina ricaricava SCARTANDO la mossa. Una lettura fallita
// lasciava PAN vuoto e il primo zoom lo scriveva sopra quello vero. Ora:
//  - si manda solo quello che è cambiato rispetto all'ultimo pannello confermato (diffPannello), e il
//    server lo applica al pannello attuale (POST /api/pannello/modifica): niente 409, niente perdite;
//  - lasciando una scheda si salva subito; chiudendo la pagina si salva con keepalive; le modifiche non
//    confermate restano in localStorage (panSospeso:<scheda>) e si rimandano al prossimo avvio;
//  - se il pannello non è stato letto non si salva niente;
//  - la vista (zoom e scorrimento) è di questa scheda del browser: sta in localStorage, non nel pannello;
//  - «lav-stato» dice sempre la verità: caricamento, da salvare, salvo, salvata vN, NON salvata.
let PAN_SALVATO = null;     // l'ultimo pannello confermato dal server: base dei diff
let lavDemo = !!mem.leggi("lavDemo", false);
const eDemo = (id) => String(id || "").startsWith("demo-");
let PAN_VER = null;
const istantanea = (x) => JSON.parse(JSON.stringify(x));
const SALVA = { sporco: false, inVolo: null, timer: null, errore: "", tentativi: 0, ancora: false, avviso: "" };
const TAB_ID = (() => { try { let t = sessionStorage.getItem("cc.tab"); if (!t) { t = uuid(); sessionStorage.setItem("cc.tab", t); } return t; } catch (e) { return "tab"; } })();
const CHIAVE_SOSPESE = "panSospeso:" + TAB_ID;
const NODO_K = ["tipo", "agente", "testo", "x", "y"];
const nodoUguale = (a, b) => !!a && !!b && NODO_K.every((k) => (a[k] ?? "") === (b[k] ?? ""));
const filoK = (f) => f.da + "\u0001" + f.a;
function diffPannello(prima, dopo) {
  prima = prima || { gruppi: [], aspetto: {}, lavagne: {} };
  const ops = [], js = JSON.stringify;
  if (js(prima.gruppi || []) !== js(dopo.gruppi || [])) ops.push({ op: "gruppi", gruppi: dopo.gruppi || [] });
  const pa = prima.aspetto || {}, da = dopo.aspetto || {};
  for (const k of new Set([...Object.keys(pa), ...Object.keys(da)])) if (js(pa[k]) !== js(da[k])) ops.push({ op: "aspetto", chiave: k, valore: da[k] ?? null });
  const pl = prima.lavagne || {}, dl = dopo.lavagne || {};
  for (const id of new Set([...Object.keys(pl), ...Object.keys(dl)])) {
    const A = pl[id] || { nodi: [], fili: [] }, B = dl[id];
    if (!B) { ops.push({ op: "togli_lavagna", lavagna: id }); continue; }
    const an = new Map((A.nodi || []).map((n) => [n.id, n])), bn = new Set((B.nodi || []).map((n) => n.id));
    const cambiati = (B.nodi || []).filter((n) => !nodoUguale(an.get(n.id), n))
      .map((n) => Object.fromEntries([["id", n.id], ...NODO_K.filter((k) => n[k] !== undefined).map((k) => [k, n[k]])]));
    const tolti = [...an.keys()].filter((x) => !bn.has(x));
    if (cambiati.length) ops.push({ op: "nodi", lavagna: id, nodi: cambiati });
    if (tolti.length) ops.push({ op: "togli_nodi", lavagna: id, ids: tolti });
    const af = new Set((A.fili || []).map(filoK)), bf = new Set((B.fili || []).map(filoK));
    const piu = (B.fili || []).filter((f) => !af.has(filoK(f))).map(({ da, a }) => ({ da, a }));
    const meno = (A.fili || []).filter((f) => !bf.has(filoK(f))).map(({ da, a }) => ({ da, a }));
    if (piu.length) ops.push({ op: "fili_aggiungi", lavagna: id, fili: piu });
    if (meno.length) ops.push({ op: "fili_togli", lavagna: id, fili: meno });
    if (js(A.bolle || {}) !== js(B.bolle || {})) ops.push({ op: "bolle", lavagna: id, bolle: B.bolle || {} });
    if ((A.titolo || "") !== (B.titolo || "")) ops.push({ op: "titolo", lavagna: id, titolo: B.titolo || "" });
  }
  return ops;
}
// le stesse regole di applica_ops_pannello() in server.py
function applicaOps(d, ops) {
  d.lavagne = d.lavagne || {}; d.aspetto = d.aspetto || {};
  for (const op of ops) {
    const k = op.lavagna;
    if (op.op === "gruppi") d.gruppi = istantanea(op.gruppi);
    else if (op.op === "aspetto") { if (op.valore == null) delete d.aspetto[op.chiave]; else d.aspetto[op.chiave] = istantanea(op.valore); }
    else if (op.op === "togli_lavagna") delete d.lavagne[k];
    else {
      const L = d.lavagne[k] || (d.lavagne[k] = LAVAGNA_VUOTA());
      L.nodi = L.nodi || []; L.fili = L.fili || [];
      if (op.op === "nodi") for (const n of op.nodi) { const x = L.nodi.find((z) => z.id === n.id); if (x) Object.assign(x, n); else if (!(n.tipo === "agente" && L.nodi.some((z) => z.agente === n.agente))) L.nodi.push({ ...n }); }
      else if (op.op === "togli_nodi") { const via = new Set(op.ids); L.nodi = L.nodi.filter((n) => !via.has(n.id)); L.fili = L.fili.filter((f) => !via.has(f.da) && !via.has(f.a)); }
      else if (op.op === "fili_aggiungi") { const ci = new Set(L.fili.map(filoK)); for (const f of op.fili) if (!ci.has(filoK(f))) { L.fili.push({ ...f }); ci.add(filoK(f)); } }
      else if (op.op === "fili_togli") { const via = new Set(op.fili.map(filoK)); L.fili = L.fili.filter((f) => !via.has(filoK(f))); }
      else L[op.op] = istantanea(op[op.op]);
    }
  }
  return d;
}
// quello che c'è da mandare: in dimostrazione solo le lavagne «demo-»
function opsDaMandare() {
  const ops = diffPannello(PAN_SALVATO, PAN);
  // dentro il ponte si salva come sul Mac; solo se il ponte oggi non passa /api/pannello/modifica (comandi
  // spenti dall'interruttore di emergenza) le modifiche restano in questa pagina e partono quando torna
  if (!ponteConsente("/api/pannello/modifica")) { SALVA.avviso = ops.length ? "NON salvata: dal sito i comandi sono spenti, riprovo quando tornano" : ""; return []; }
  if (SALVA.avviso.startsWith("NON salvata: dal sito")) SALVA.avviso = "";
  if (!lavDemo) { SALVA.avviso = ""; return ops; }
  const demo = ops.filter((o) => o.lavagna && eDemo(o.lavagna));
  SALVA.avviso = demo.length < ops.length ? "dimostrazione: fuori dalle lavagne demo non salvo" : "dimostrazione";
  return demo;
}
function scriviSospese() {
  if (!panPronto) return;
  const ops = opsDaMandare();
  mem.scrivi(CHIAVE_SOSPESE, ops.length ? { base: PAN_VER, ops, ts: Date.now() } : null);
}
function statoSalva() {
  const s = $("lav-stato");
  if (!s) return;
  let t, c;
  if (!panPronto) [t, c] = ["non caricata: non salvo niente", "errore"];
  else if (SALVA.inVolo) [t, c] = ["salvo…", "salvo"];
  else if (SALVA.errore) [t, c] = ["NON salvata: " + SALVA.errore + " · riprovo", "errore"];
  else if (SALVA.sporco || SALVA.timer) [t, c] = ["da salvare…", "salvo"];
  else if (SALVA.avviso.startsWith("NON salvata: dal sito")) [t, c] = [SALVA.avviso, "errore"];
  else [t, c] = [(SALVA.avviso ? SALVA.avviso + " · " : "") + "salvata · v" + PAN_VER, "ok"];
  s.textContent = t; s.dataset.stato = c;
}
// subito=true: alla fine di un gesto (scheda lasciata, filo tirato) si salva senza aspettare
function salvaPannello(subito = false) {
  if (!panPronto) { statoSalva(); return; }
  SALVA.sporco = true;
  scriviSospese();
  clearTimeout(SALVA.timer);
  SALVA.timer = setTimeout(scaricaSalvataggi, subito ? 0 : 300);
  statoSalva();
}
function scaricaSalvataggi(keepalive = false) {
  clearTimeout(SALVA.timer); SALVA.timer = null;
  if (!panPronto || !SALVA.sporco) { statoSalva(); return SALVA.inVolo || Promise.resolve(); }
  if (SALVA.inVolo && keepalive !== true) { SALVA.ancora = true; return SALVA.inVolo; }
  const ops = opsDaMandare();
  SALVA.sporco = false;
  if (!ops.length) { scriviSospese(); statoSalva(); return Promise.resolve(); }
  const corpo = JSON.stringify({ base: PAN_VER, ops });
  // la richiesta parte ADESSO, in modo sincrono: vale anche dentro pagehide (keepalive, fino a 64 KB)
  const richiesta = fetch("/api/pannello/modifica", { method: "POST", headers: HDR, body: corpo, keepalive: keepalive === true && corpo.length < 60000 });
  const promessa = (async () => {
    let tetto;
    try {
      const r = await Promise.race([richiesta, new Promise((_, no) => { tetto = setTimeout(() => no(new Error("il server non risponde")), 10000); })]);
      const d = await r.json().catch(() => ({}));
      if (r.status === 403 && d.token_scaduto) throw new Error("Command Center ripartito: ricarica la pagina, le modifiche restano in sospeso");
      if (!r.ok) throw new Error(d.errore || "HTTP " + r.status);
      PAN_SALVATO = applicaOps(PAN_SALVATO ? istantanea(PAN_SALVATO) : { gruppi: [], aspetto: {}, lavagne: {} }, ops);
      SALVA.errore = ""; SALVA.tentativi = 0;
      riallinea(d.pannello);
      scriviSospese();
    } catch (e) {
      SALVA.sporco = true; SALVA.errore = e.message; SALVA.tentativi++;
      clearTimeout(SALVA.timer);
      SALVA.timer = setTimeout(scaricaSalvataggi, Math.min(30000, 1000 * 2 ** SALVA.tentativi));
    } finally {
      clearTimeout(tetto);
      if (SALVA.inVolo === promessa) SALVA.inVolo = null;
      if (SALVA.ancora) { SALVA.ancora = false; if (SALVA.sporco && !SALVA.errore) scaricaSalvataggi(); }
      statoSalva();
      aggiornaAllineamento();
    }
  })();
  SALVA.inVolo = promessa;
  statoSalva();
  return promessa;
}
// il pannello del server, più le modifiche di questa scheda non ancora confermate. Mai durante un gesto
// o una scrittura: si rimanda alla fine (LAV.riallineaDopo).
function modificaInCorso() {   // solo se l'utente sta davvero scrivendo lì (il fuoco è dentro), non per un campo rimasto aperto
  const a = document.activeElement;
  return !!(a && a.isContentEditable && a.closest("#lav-mondo, #gruppi") && document.hasFocus());
}
function riallinea(srv) {
  if (!srv || typeof srv.lavagne !== "object") return;
  if (LAV.gesto || modificaInCorso()) { LAV.riallineaDopo = srv; return; }
  if (Number.isInteger(srv.versione) && PAN_VER != null && srv.versione < PAN_VER) return;   // risposta vecchia
  const locali = diffPannello(PAN_SALVATO, PAN);
  PAN_SALVATO = istantanea({ gruppi: srv.gruppi || [], aspetto: srv.aspetto || {}, lavagne: srv.lavagne });
  PAN_VER = srv.versione;
  const viste = Object.fromEntries(Object.entries(PAN.lavagne || {}).map(([k, L]) => [k, L.vista]));
  PAN = applicaOps(istantanea(PAN_SALVATO), locali);
  for (const [k, v] of Object.entries(viste)) if (PAN.lavagne[k] && v) PAN.lavagne[k].vista = v;   // la vista è di questa scheda
  if (LAV.sel && !nodoDi(LAV.sel)) LAV.sel = null;
  for (const id of [...LAV.multi]) if (!nodoDi(id)) LAV.multi.delete(id);
  if (LAV.selFilo != null && !lav().fili[LAV.selFilo]) LAV.selFilo = null;
  if (lavagnaAttiva !== "generale" && lav().titolo) lavagnaTitolo = lav().titolo;
  disegnaGruppi(); disegnaLavagna(); aggiornaTestaChat(); statoSalva();
}
function dopoInterazione() {
  if (LAV.gesto || modificaInCorso()) return;
  if (LAV.riallineaDopo) { const s = LAV.riallineaDopo; LAV.riallineaDopo = null; riallinea(s); }
  else if (LAV.ridisegnaDopo) { LAV.ridisegnaDopo = false; disegnaLavagna(); }
}
// un'altra scheda (o il server) ha salvato: si prende il pannello nuovo senza perdere le mosse locali
async function ricaricaSeCambiato() {
  if (!panPronto || SALVA.inVolo) return;
  let d;
  try { d = await api("/api/pannello"); } catch (e) { return; }
  if (Number.isInteger(d.versione) && PAN_VER != null && d.versione > PAN_VER) riallinea(d);
}
addEventListener("pagehide", () => scaricaSalvataggi(true));
document.addEventListener("visibilitychange", () => { if (document.hidden) scaricaSalvataggi(true); });
addEventListener("beforeunload", (ev) => {
  scaricaSalvataggi(true);
  if (SALVA.errore) { ev.preventDefault(); ev.returnValue = ""; }   // solo se davvero non salvata
});
async function caricaPannello() {
  let d;
  try { d = await api("/api/pannello"); }
  catch (e) {
    // audit 02/10/2026: prima qui si andava avanti con PAN vuoto e il primo zoom lo salvava sopra quello vero
    panPronto = false; statoSalva();
    toast("Non leggo la lavagna salvata (" + e.message + "): riprovo fra 3 s e intanto non salvo niente", true);
    clearTimeout(caricaPannello.t); caricaPannello.t = setTimeout(caricaPannello, 3000);
    return;
  }
  const sospese = mem.leggi(CHIAVE_SOSPESE, null);   // modifiche di questa scheda mai confermate (pagina chiusa, server ripartito)
  if (sospese && Array.isArray(sospese.ops) && sospese.ops.length) {
    try {
      const r = await api("/api/pannello/modifica", { base: sospese.base, ops: sospese.ops });
      d = r.pannello; mem.scrivi(CHIAVE_SOSPESE, null);
      toast("Ho salvato le ultime modifiche rimaste in sospeso");
    } catch (e) {
      // dentro il ponte non si salverebbero mai: si buttano, e lo si dice una volta sola
      toast("Modifiche in sospeso non ancora salvate: " + e.message, true);
    }
  }
  let lavagne = d.lavagne;
  if (!lavagne) lavagne = { generale: Object.assign(LAVAGNA_VUOTA(), d.lavagna || {}) };   // dati vecchi: una sola lavagna, diventa "generale"
  PAN = { gruppi: d.gruppi || [], aspetto: d.aspetto || {}, lavagne };
  PAN_VER = Number.isInteger(d.versione) ? d.versione : null;
  PAN_SALVATO = istantanea(PAN);
  SALVA.sporco = false; SALVA.errore = ""; VISTE_LETTE.clear();
  lavagnaAttiva = mem.leggi("lavagnaAttiva", "generale");
  lavagnaTitolo = lavagnaAttiva === "generale" ? "" : ((PAN.lavagne[lavagnaAttiva] || {}).titolo || mem.leggi("lavagnaTitolo:" + lavagnaAttiva, ""));
  panPronto = true;
  statoSalva();
  LAV.sel = null; LAV.selFilo = null;   // i fili ricaricati hanno altri indici: nessuna scelta vecchia
  pulisciSchedeOrfane();    // se il catalogo degli agenti è arrivato prima della disposizione
  disegnaGruppi();
  disegnaLavagna();
  aggiornaTestaChat();      // emoji e colore salvati valgono anche nella testa della chat
  disegnaMessaggi();
  aggiornaAllineamento();
}

// ------------------------------------------------ gli agenti (da spazi.json, via /api/catalogo)
// 2026-10-10 (Jarvis da zero): nessuno spazio è scritto qui. Colore ed emoji di uno spazio nascono dal suo id
// (stesso spazio, stesso colore ovunque); si cambiano dalla scheda del gruppo («aspetto»).
const _TAVOLOZZA_SPAZI = ["#d08770", "#e0a458", "#599ce7", "#9386f2", "#4fb286", "#c56b9a", "#5fb3b3", "#b48ead"];
const _EMOJI_SPAZI = ["📁", "🧩", "🌐", "📊", "🛠️", "📣", "🔬", "💼"];
const COLORE_SPAZIO = new Proxy({}, { get: (_o, k) => (typeof k === "string" && k ? _TAVOLOZZA_SPAZI[hashCode(k) % _TAVOLOZZA_SPAZI.length] : undefined) });
const EMOJI_SPAZIO = new Proxy({}, { get: (_o, k) => (typeof k === "string" && k ? _EMOJI_SPAZI[hashCode(k) % _EMOJI_SPAZI.length] : undefined) });
// lo stato vuoto (nessun progetto): una frase sola, uguale in ogni pagina
function testoNessunProgetto() {
  return `Nessun progetto ancora: di' a ${ASSISTENTE} di crearne uno («apri il progetto …», oppure /nuovo-progetto <nome> in Claude Code).`;
}
// lo stato vuoto con il pulsante primario «Crea il tuo primo progetto» (stesso modulo di «＋ Nuovo gruppo»)
function statoVuotoProgetti(piccolo = false) {
  return el("div", { class: "stato-vuoto-box" + (piccolo ? " piccolo" : "") },
    el("p", { class: "stato-vuoto" }, testoNessunProgetto()),
    el("button", { type: "button", class: "primario crea-primo", "data-solo-mac": "agente:crea_gruppo=capogruppo",
      onclick: () => apriNuovoGruppo() }, "Crea il tuo primo progetto"));
}
function nessunProgettoVero() { return !(spaziCat || []).some((s) => !s.sistema && (s.progetti || []).length); }
// una riga per ruolo: emoji per il vecchio stile, categoria per il seed dell'avatar
// (stessa faccia per lo stesso ruolo ovunque, il colore cambia solo per spazio)
const RUOLI = [
  [/seo|google|search/, "seo", "🔎"], [/x-|social|linkedin|post/, "social", "📣"], [/legal|avvoc|contratt|norm/, "legale", "⚖️"],
  [/fisc|contab|bilanc|finanz|cost|prezz/, "finanza", "📊"], [/dati|sql|odoo|crm/, "dati", "🗄️"], [/design|grafic|ui|ux/, "design", "🎨"],
  [/android|app|mobile/, "mobile", "📱"], [/web|sito|front/, "web", "🌐"], [/test|verific|qa|revis/, "revisione", "✅"], [/ricerc|analist/, "ricerca", "🔬"],
  [/person|hr|turn|staff/, "persone", "👥"], [/cucina|menu|chef|food/, "cucina", "🍳"], [/market|vend|commerc/, "commerciale", "💼"], [/dev|code|svilupp|backend/, "sviluppo", "🛠️"],
  [/manuten/, "manutenzione", "🔧"],
];
function ruoloDi(a) {
  const n = a.nome.toLowerCase();
  if (a.capogruppo) return { cat: "capogruppo", emoji: "🧭" };
  for (const [re, cat, e] of RUOLI) if (re.test(n)) return { cat, emoji: e };
  return { cat: a.modello || "generico", emoji: { opus: "🛠️", haiku: "⚡" }[a.modello] || "🧠" };
}
function emojiDi(a) { return ruoloDi(a).emoji; }

// ---- Avatar "beam" — stesso algoritmo di Boring Avatars (MIT), riscritto qui in
// vanilla JS: niente servizio esterno, gira anche senza internet. Il seed è il
// ruolo (non il nome): stessa faccia per «avvocato» ovunque, cambia solo il colore.
function hashCode(s) { let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0; } return Math.abs(h); }
const _digit = (n, i) => Math.floor(n / 10 ** i) % 10;
const _bool = (n, i) => _digit(n, i) % 2 === 0;
const _unit = (n, range, i) => { const v = n % range; return i && _digit(n, i) % 2 === 0 ? -v : v; };
function contrastoDi(hex) {
  hex = hex.replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16), g = parseInt(hex.slice(2, 4), 16), b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 >= 128 ? "#000000" : "#ffffff";
}
function hslAHex(h, s, l) {
  s /= 100; l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const t = (x) => Math.round(255 * x).toString(16).padStart(2, "0");
  return `#${t(f(0))}${t(f(8))}${t(f(4))}`;
}
// 5 tonalità a partire dal colore dello spazio: varietà senza perdere l'identità del progetto
function paletteDaColore(hex) {
  hex = hex.replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16) / 255, g = parseInt(hex.slice(2, 4), 16) / 255, b = parseInt(hex.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l0 = (max + min) / 2, d = max - min;
  let h = 0, s0 = d === 0 ? 0 : d / (1 - Math.abs(2 * l0 - 1));
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6; else if (max === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  s0 *= 100; const l = l0 * 100;
  const mk = (dh, ds, dl) => hslAHex((h + dh + 360) % 360, Math.max(25, Math.min(85, s0 + ds)), Math.max(22, Math.min(78, l + dl)));
  return [mk(-25, -5, -10), mk(0, 15, 6), mk(20, -20, 22), mk(-45, 10, -14), mk(40, 5, 12)];
}
function svgBeam(seed, colori) {
  const SZ = 36, n = hashCode(seed), range = colori.length;
  const wrapperColor = colori[n % range], faceColor = contrastoDi(wrapperColor), backgroundColor = colori[(n + 13) % range];
  const preX = _unit(n, 10, 1), wrapperTranslateX = preX < 5 ? preX + SZ / 9 : preX;
  const preY = _unit(n, 10, 2), wrapperTranslateY = preY < 5 ? preY + SZ / 9 : preY;
  const wrapperRotate = _unit(n, 360), wrapperScale = 1 + _unit(n, SZ / 12) / 10;
  const isMouthOpen = _bool(n, 2), isCircle = _bool(n, 1), eyeSpread = _unit(n, 5), mouthSpread = _unit(n, 3);
  const faceRotate = _unit(n, 10, 3);
  const faceTranslateX = wrapperTranslateX > SZ / 6 ? wrapperTranslateX / 2 : _unit(n, 8, 1);
  const faceTranslateY = wrapperTranslateY > SZ / 6 ? wrapperTranslateY / 2 : _unit(n, 7, 2);
  const bocca = isMouthOpen
    ? `<path d="M15 ${19 + mouthSpread}c2 1 4 1 6 0" stroke="${faceColor}" fill="none" stroke-linecap="round"/>`
    : `<path d="M13,${19 + mouthSpread} a1,0.75 0 0,0 10,0" fill="${faceColor}"/>`;
  return `<svg viewBox="0 0 ${SZ} ${SZ}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
    <rect width="${SZ}" height="${SZ}" fill="${backgroundColor}"/>
    <rect x="0" y="0" width="${SZ}" height="${SZ}" fill="${wrapperColor}" rx="${isCircle ? SZ : SZ / 6}"
      transform="translate(${wrapperTranslateX} ${wrapperTranslateY}) rotate(${wrapperRotate} ${SZ / 2} ${SZ / 2}) scale(${wrapperScale})"/>
    <g transform="translate(${faceTranslateX} ${faceTranslateY}) rotate(${faceRotate} ${SZ / 2} ${SZ / 2})">
      ${bocca}
      <rect x="${14 - eyeSpread}" y="14" width="1.5" height="2" rx="1" fill="${faceColor}"/>
      <rect x="${20 + eyeSpread}" y="14" width="1.5" height="2" rx="1" fill="${faceColor}"/>
    </g>
  </svg>`;
}
function tuttiAgenti() {
  const out = [];
  for (const s of spaziCat || []) for (const p of s.progetti || []) for (const a of p.agenti || []) {
    out.push({ key: `${p.id}:${a.nome}`, nome: a.nome, progetto: p.id, progettoNome: p.nome, spazio: s.id, spazioNome: s.nome,
      modello: a.modello, capogruppo: a.capogruppo, descrizione: a.descrizione || "", cartella: p.cartella,
      file: a.file, strumenti: a.strumenti || [],
      // punto 13 del contratto: il server nuovo li manda; col vecchio restano ai valori di sempre
      nuovo: "attivo" in a, tono: a.tono || "", umorismo: Number.isFinite(+a.umorismo) ? +a.umorismo : 1,
      serieta: a.serieta == null ? 2 : +a.serieta,
      attivo: a.attivo !== false, comunica: Array.isArray(a.comunica) ? a.comunica : null, aggiornato_ts: a.aggiornato_ts || 0,
      riporta_a: a.riporta_a || "" });          // punto 14: il sotto-agente riporta a uno specialista (terzo livello)
  }
  return out;
}
let AGENTI = new Map();
// 🔴 2026-10-03 (REVISIONE-2, F4): «colore» arriva da pannello.json e finisce in style="--c:…": un valore come
// «#123456;background-image:url(https://…)» faceva partire richieste verso altri siti. Si accetta solo una lista
// stretta (#rgb, #rrggbb, #rrggbbaa, rgb()/hsl() con numeri, pochi nomi); il resto diventa il colore di riserva.
const COLORI_NOMI = ["black", "white", "gray", "grey", "silver", "red", "maroon", "orange", "gold", "yellow", "olive", "lime", "green",
  "teal", "cyan", "aqua", "blue", "navy", "indigo", "purple", "violet", "magenta", "fuchsia", "pink", "brown", "coral", "salmon", "tomato", "crimson", "turquoise"];
const COLORE_NUM = String.raw`\s*\d{1,3}(?:\.\d+)?%?\s*`;
const COLORE_FUNZ = new RegExp(`^(rgb|hsl)a?\\((?:${COLORE_NUM},){2}${COLORE_NUM}(?:,\\s*(?:0|1|0?\\.\\d+)\\s*)?\\)$`, "i");
function coloreSicuro(c, riserva = "#599ce7") {
  const s = typeof c === "string" ? c.trim() : "";
  if (s.length > 40) return riserva;
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(s)) return s;
  if (COLORE_FUNZ.test(s)) return s;
  if (COLORI_NOMI.includes(s.toLowerCase())) return s.toLowerCase();
  return riserva;
}
function aspettoDi(a) {
  const x = PAN.aspetto[a.key] || {};
  const riserva = COLORE_SPAZIO[a.spazio] || "#599ce7";
  return { emoji: x.emoji || emojiDi(a), colore: coloreSicuro(x.colore, riserva), riserva };
}
// Nomi e note li decide l'utente dal pannello (aspetto in pannello.json); il nome del profilo
// resta quello vero e serve solo a chiamare l'agente.
const nomeDi = (a) => (a && (PAN.aspetto[a.key] || {}).nome) || (a ? a.nome : ASSISTENTE);
const notaDi = (a) => (a && (PAN.aspetto[a.key] || {}).nota) || "";
const progettoDi = (a) => (a && (PAN.aspetto["progetto:" + a.progetto] || {}).nome) || (a ? a.progettoNome : "");
function rinominaProgetto(nodo, pid) {
  nodo.contentEditable = "true"; nodo.focus();
  document.getSelection().selectAllChildren(nodo);
  nodo.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") { ev.preventDefault(); nodo.blur(); } if (ev.key === "Escape") { nodo.dataset.annulla = "1"; nodo.blur(); } });
  nodo.addEventListener("blur", () => {
    nodo.contentEditable = "false";
    const k = "progetto:" + pid, t = nodo.textContent.trim().slice(0, 60);
    if (!nodo.dataset.annulla) { if (t) PAN.aspetto[k] = { ...(PAN.aspetto[k] || {}), nome: t }; else delete PAN.aspetto[k]; salvaPannello(); }
    disegnaGruppi(); disegnaLavagna(); aggiornaTestaChat();
  }, { once: true });
}
function avatar(a, classe = "avatar") {
  const s = aspettoDi(a);
  const span = el("span", { class: classe, style: `--c:${s.colore}`, "aria-hidden": "true" });
  const personalizzata = a && (PAN.aspetto[a.key] || {}).emoji;
  // la tavolozza dell'avatar si calcola solo da un #rrggbb (numeri, mai il testo del colore)
  if (a && a.nome && !personalizzata) span.innerHTML = svgBeam(ruoloDi(a).cat, paletteDaColore(/^#[0-9a-f]{6}$/i.test(s.colore) ? s.colore : s.riserva));
  else span.textContent = s.emoji;
  return span;
}

// ------------------------------------------------ colonna di sinistra: gruppi
function gruppiPredefiniti() {
  return (spaziCat || []).map((s) => ({ id: "spazio-" + s.id, nome: s.nome, chiuso: false,
    agenti: s.progetti.flatMap((p) => p.agenti.map((a) => `${p.id}:${a.nome}`)) }));
}
// I gruppi salvati, più gli agenti nuovi (arrivati dopo il salvataggio) nel gruppo del loro spazio
// 02/10/2026 (audit menu, P4/P5): un gruppo spazio-* il cui spazio non c'è più in spazi.json è un «fantasma».
// Non è un gruppo (fissaGruppi lo lascia fuori) ma si vede in fondo al menu con «Togli», insieme alle lavagne orfane.
const spazioVivo = (gid) => !gid.startsWith("spazio-") || !(spaziCat || []).length || spaziCat.some((s) => "spazio-" + s.id === gid);
const spazioDi = (gid) => gid.startsWith("spazio-") ? (spaziCat || []).find((s) => s.id === gid.slice(7)) || null : null;
function gruppiFantasma() {
  if (!(spaziCat || []).length || !PAN || !PAN.gruppi) return [];
  const fuori = new Map();
  for (const g of PAN.gruppi) if (!spazioVivo(g.id)) fuori.set(g.id, { id: g.id, nome: g.nome, lavagna: !!(PAN.lavagne || {})[g.id] });
  for (const k of Object.keys(PAN.lavagne || {})) {
    if (fuori.has(k) || eDemo(k)) continue;
    if ((k.startsWith("spazio-") && !spazioVivo(k)) || (k.startsWith("g-") && !PAN.gruppi.some((g) => g.id === k)))
      fuori.set(k, { id: k, nome: (PAN.lavagne[k] || {}).titolo || k, lavagna: true, soloLavagna: true });
  }
  return [...fuori.values()];
}
function togliFantasma(f) {
  if (!confirm(`«${f.nome}» non ha più uno spazio o un gruppo dietro.\n\nTolgo ${f.soloLavagna ? "la sua lavagna" : "la voce dal menu" + (f.lavagna ? " e la sua lavagna" : "")}? Nessun file e nessun agente si tocca.`)) return;
  PAN.gruppi = PAN.gruppi.filter((x) => x.id !== f.id);
  delete PAN.lavagne[f.id];
  if (lavagnaAttiva === f.id) vaiALavagna("generale", "");
  salvaPannello(true); disegnaGruppi(); disegnaLavagna();
  toast(`«${f.nome}» tolto dal menu`);
}
function gruppiEffettivi() {
  if (!PAN.gruppi.length) return gruppiPredefiniti();
  const gruppi = PAN.gruppi.filter((g) => spazioVivo(g.id))
    .map((g) => ({ ...g, agenti: g.agenti.filter((k) => AGENTI.has(k)) }));
  const messi = new Set(gruppi.flatMap((g) => g.agenti));
  for (const a of AGENTI.values()) {
    if (messi.has(a.key)) continue;
    let g = gruppi.find((x) => x.id === "spazio-" + a.spazio);
    if (!g) { g = { id: "spazio-" + a.spazio, nome: a.spazioNome, chiuso: false, agenti: [] }; gruppi.push(g); }
    g.agenti.push(a.key);
  }
  // 30/09/2026: un gruppo appena nato (cartella senza agenti) resta visibile
  for (const sp of spaziCat || []) if (!sp.sistema && !gruppi.some((x) => x.id === "spazio-" + sp.id)) gruppi.push({ id: "spazio-" + sp.id, nome: sp.nome, chiuso: false, agenti: [] });
  return gruppi;
}
function fissaGruppi() { PAN.gruppi = gruppiEffettivi(); }

let filtro = "";
function disegnaGruppi() {
  AGENTI = new Map(tuttiAgenti().map((a) => [a.key, a]));
  if (modificaInCorso() && document.activeElement.closest("#gruppi")) return;   // rinomina in corso: la fine della rinomina ridisegna
  const box = $("gruppi");
  if (!box) return;
  if (!AGENTI.size) {
    box.replaceChildren(spaziCat.length ? el("p", { class: "vuoto nota" }, "nessun agente nei progetti")
      : SPAZI_LETTI ? statoVuotoProgetti(true) : el("p", { class: "vuoto nota" }, "lettura degli agenti…"));
    return;
  }
  const f = filtro.toLowerCase();
  box.replaceChildren(...gruppiEffettivi().map((g) => {
    const agenti = g.agenti.map((k) => AGENTI.get(k)).filter((a) => a &&
      (!f || [a.nome, nomeDi(a), progettoDi(a), a.descrizione, notaDi(a)].join(" ").toLowerCase().includes(f)));
    if (f && !agenti.length) return document.createComment("");
    const custom = !g.id.startsWith("spazio-");
    const nome = el("span", { class: "nome-gruppo", title: "Doppio clic o ✎ per rinominare" }, g.nome);
    const testa = el("div", { class: "gruppo-testa", role: "button", tabindex: "0", "aria-expanded": String(!g.chiuso) },
      el("span", { class: "freccia" }, "▼"), nome, el("span", { class: "quanti" }, String(agenti.length)),
      el("button", { class: "icona azione-g", title: "Scheda del gruppo: progetti, squadra, azioni",
        onclick: (ev) => { ev.stopPropagation(); apriSchedaGruppo(g.id); } }, "ℹ"),
      el("button", { class: "icona azione-g", title: "Apri il gruppo nella lavagna: capogruppo e squadra, già collegati",
        onclick: (ev) => { ev.stopPropagation(); apriGruppoInLavagna(g.id); } }, "▦"),
      el("button", { class: "icona azione-g", "data-solo-mac": "agente:crea", title: "Nuovo agente in questo gruppo",
        onclick: (ev) => { ev.stopPropagation(); apriNuovoAgente(g.id.startsWith("spazio-") ? g.id.slice(7) : null); } }, "＋"),
      el("button", { class: "icona azione-g", "data-solo-mac": "agente:rinomina_spazio", title: "Rinomina il gruppo",
        onclick: (ev) => { ev.stopPropagation(); rinominaGruppo(nome, g.id); } }, "✎"),
      // 02/10/2026 (audit menu, P5): ✕ anche sui gruppi-spazio (non di sistema), con lo stesso dialogo della lavagna
      custom || (spazioDi(g.id) && !spazioDi(g.id).sistema) ? el("button", { class: "icona azione-g", "data-solo-mac": "agente:togli_gruppo",
        title: custom ? "Togli il gruppo (gli agenti tornano al loro spazio)" : "Elimina o sospendi i progetti di questo spazio (come Canc sulla lavagna)",
        onclick: (ev) => { ev.stopPropagation(); togliGruppoMenu(g.id); } }, "✕") : "");
    // il clic apre/chiude dopo 250 ms: un doppio clic sul nome lo annulla e rinomina (27/09/2026)
    testa.addEventListener("click", (ev) => {
      clearTimeout(testa.__t);
      if (ev.detail > 1) return;
      testa.__t = setTimeout(() => { fissaGruppi(); const x = PAN.gruppi.find((y) => y.id === g.id); x.chiuso = !x.chiuso; salvaPannello(); disegnaGruppi(); },
        ev.target.closest(".nome-gruppo") ? 250 : 0);
    });
    testa.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && ev.target === testa) testa.click(); });
    nome.addEventListener("dblclick", (ev) => { ev.stopPropagation(); clearTimeout(testa.__t); rinominaGruppo(nome, g.id); });
    const lista = el("div", { class: "gruppo-lista" });
    let progettoPrima = null;
    for (const a of agenti) {
      // nei gruppi degli spazi, una riga per progetto quando lo spazio ne ha più d'uno
      if (!custom && a.progetto !== progettoPrima && new Set(agenti.map((x) => x.progetto)).size > 1) {
        const sp = el("div", { class: "sotto-progetto", "data-progetto": a.progetto, title: "Doppio clic per rinominare il progetto" }, progettoDi(a));
        sp.addEventListener("dblclick", () => rinominaProgetto(sp, a.progetto));
        lista.append(sp);
      }
      progettoPrima = a.progetto;
      lista.append(rigaAgenteLato(a, g.id));
    }
    if (!agenti.length) lista.append(el("div", { class: "vuoto-gruppo" }, "trascina qui gli agenti"));
    // gli agenti tolti (archiviati) dello spazio, in grigio, con «Ripristina»
    if (!custom && !f) for (const x of archiviatiDi(g.id.slice(7))) lista.append(el("div", { class: "agente archiviato", title: "Archiviato: il profilo sta in .claude/agents/_archivio" },
      el("span", { class: "avatar" }, "⌫"), el("div", { class: "testo" }, el("b", {}, x.nome), el("small", {}, "archiviato · " + x.progettoNome)),
      el("button", { class: "piccolo", type: "button", "data-solo-mac": "agente:ripristina", onclick: async (ev) => { ev.stopPropagation();
        const d = await azione({ tipo: "agente", cosa: "ripristina", progetto: x.progetto, nome: x.nome }, ev.currentTarget); if (d) caricaSpazi(); } }, "Ripristina"),
      // 02/10/2026 (dal ramo windows): un archiviato si toglie anche dall'elenco; il profilo va in _archivio/_eliminati/
      el("button", { class: "piccolo", type: "button", "data-solo-mac": "agente:elimina_archiviato", title: "Toglie l'agente dall'elenco degli archiviati (copia in _archivio/_eliminati/)",
        onclick: async (ev) => { ev.stopPropagation();
          if (!confirm(`Eliminare ${x.nome} dagli archiviati? Il profilo va in _archivio/_eliminati/ e non torna con «Ripristina».`)) return;
          const d = await azione({ tipo: "agente", cosa: "elimina_archiviato", progetto: x.progetto, nome: x.nome }, ev.currentTarget); if (d) caricaSpazi(); } }, "Elimina")));
    const gruppo = el("section", { class: "gruppo" + (g.chiuso && !f ? " chiuso" : ""), "data-gruppo": g.id },
      testa, el("div", { class: "gruppo-corpo" }, lista));
    // si può lasciare un agente anche sulla testa o sullo spazio vuoto del gruppo
    gruppo.addEventListener("dragover", (ev) => { if (trascinoAgente) { ev.preventDefault(); gruppo.classList.add("sopra"); } });
    gruppo.addEventListener("dragleave", (ev) => { if (!gruppo.contains(ev.relatedTarget)) gruppo.classList.remove("sopra"); });
    gruppo.addEventListener("drop", (ev) => {
      ev.preventDefault(); gruppo.classList.remove("sopra");
      const k = ev.dataTransfer.getData("text/x-agente");
      if (k) spostaAgente(k, g.id, null);
    });
    return gruppo;
  }));
  // gruppi fantasma e lavagne orfane (dati rimasti da prima del 02/10/2026): si vedono e si tolgono, senza toccare file
  if (!f) for (const x of gruppiFantasma()) box.append(el("div", { class: "agente archiviato fantasma", title: "Lo spazio o il gruppo non c'è più: resta solo la disposizione" },
    el("span", { class: "avatar" }, "👻"), el("div", { class: "testo" }, el("b", {}, x.nome), el("small", {}, x.soloLavagna ? "lavagna orfana" : "gruppo fantasma: lo spazio non c'è più")),
    el("button", { class: "piccolo", type: "button", onclick: (ev) => { ev.stopPropagation(); togliFantasma(x); } }, "Togli")));
  disegnaAgentiSpazi();
  segnaAttivi();
}

function rigaAgenteLato(a, gid) {
  const riga = el("div", { class: "agente" + (chatCon === a.key ? " scelto" : "") + (a.attivo === false ? " spento" : ""), draggable: "true", tabindex: "0",
    "data-agente": a.key, title: notaDi(a) || a.descrizione, style: `--c:${aspettoDi(a).colore}` },
    avatar(a),
    el("div", { class: "testo" }, el("b", {}, nomeDi(a)), el("small", {}, (a.capogruppo ? "capogruppo · " : "") + progettoDi(a))),
    el("span", { class: "mod" }, a.modello));
  riga.addEventListener("click", () => apriChat(a.key));
  riga.addEventListener("dblclick", () => apriScheda(a.key));
  riga.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") apriChat(a.key);
    if (ev.key === " ") { ev.preventDefault(); apriScheda(a.key); }
  });
  riga.addEventListener("contextmenu", (ev) => { ev.preventDefault(); apriScheda(a.key); });
  riga.addEventListener("dragstart", (ev) => {
    trascinoAgente = a.key;
    ev.dataTransfer.setData("text/x-agente", a.key);
    ev.dataTransfer.setData("text/plain", a.nome);
    ev.dataTransfer.effectAllowed = "copyMove";
    requestAnimationFrame(() => riga.classList.add("trascinato"));
  });
  riga.addEventListener("dragend", () => { trascinoAgente = null; riga.classList.remove("trascinato"); document.querySelectorAll(".sopra,.inserisci-sopra").forEach((x) => x.classList.remove("sopra", "inserisci-sopra")); });
  riga.addEventListener("dragover", (ev) => { if (trascinoAgente && trascinoAgente !== a.key) { ev.preventDefault(); riga.classList.add("inserisci-sopra"); } });
  riga.addEventListener("dragleave", () => riga.classList.remove("inserisci-sopra"));
  riga.addEventListener("drop", (ev) => {
    ev.preventDefault(); ev.stopPropagation();
    riga.classList.remove("inserisci-sopra");
    document.querySelectorAll(".gruppo.sopra").forEach((x) => x.classList.remove("sopra"));
    const k = ev.dataTransfer.getData("text/x-agente");
    if (k && k !== a.key) spostaAgente(k, gid, a.key);
  });
  return riga;
}
let trascinoAgente = null;

function spostaAgente(k, gid, prima) {
  fissaGruppi();
  for (const g of PAN.gruppi) g.agenti = g.agenti.filter((x) => x !== k);
  const g = PAN.gruppi.find((x) => x.id === gid);
  if (!g) return;
  const i = prima ? g.agenti.indexOf(prima) : -1;
  if (i >= 0) g.agenti.splice(i, 0, k); else g.agenti.push(k);
  g.chiuso = false;
  salvaPannello();
  disegnaGruppi();
}
// 02/10/2026 (audit menu, P7): tolta nuovoGruppo(), che con un secondo listener su «＋ Nuovo gruppo» creava ogni volta
// un gruppo vuoto «Nuovo gruppo» in pannello.json oltre ad aprire il modulo. Il bottone apre solo apriNuovoGruppo().
function rinominaGruppo(nodo, gid) {
  nodo.contentEditable = "true";
  nodo.focus();
  document.getSelection().selectAllChildren(nodo);
  const fine = (salva) => {
    nodo.contentEditable = "false";
    const testo = nodo.textContent.trim().slice(0, 60);
    if (salva && testo && gid.startsWith("spazio-")) {       // il nome dello spazio è in spazi.json: lo scrive il server (D13)
      azione({ tipo: "agente", cosa: "rinomina_spazio", spazio: gid.slice(7), nome: testo }).then((d) => { if (d) { caricaSpazi(); ricaricaSeCambiato(); } });
    } else if (salva && testo) { fissaGruppi(); PAN.gruppi.find((x) => x.id === gid).nome = testo; salvaPannello(); }
    disegnaGruppi();
  };
  nodo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); nodo.blur(); }
    if (ev.key === "Escape") { nodo.textContent = ""; fine(false); }
    ev.stopPropagation();
  });
  nodo.addEventListener("click", (ev) => ev.stopPropagation());
  nodo.addEventListener("blur", () => fine(true), { once: true });
}
function smontaGruppo(gid) {
  fissaGruppi();
  PAN.gruppi = PAN.gruppi.filter((g) => g.id !== gid);   // gli agenti tornano da soli al loro spazio
  delete PAN.lavagne[gid];                                // D14 (02/10/2026): anche la sua lavagna, se no restava per sempre
  if (lavagnaAttiva === gid) vaiALavagna("generale", "");
  salvaPannello();
  disegnaGruppi(); disegnaLavagna();
  toast("Gruppo tolto: gli agenti sono tornati nel loro spazio");
}
// 02/10/2026 (l'utente, audit menu P5): dal menu un gruppo si toglie come dalla lavagna, con lo stesso dialogo e lo stesso
// effetto (togli_gruppo sul server, che pulisce spazi.json e pannello.json insieme). I gruppi personalizzati (g-*) sono
// solo disposizione: si smontano e basta.
function togliGruppoMenu(gid) {
  if (!gid.startsWith("spazio-")) return smontaGruppo(gid);
  const s = spazioDi(gid);
  if (!s) { const f = gruppiFantasma().find((x) => x.id === gid); if (f) togliFantasma(f); return; }
  if (s.sistema) { toast("Gli spazi di sistema non si tolgono", true); return; }
  chiediTogliGruppi([{ nome: s.nome, progetti: s.progetti, etichetta: s.nome }], true);
}
// ---- scheda gruppo (l'utente, 27/09/2026): un solo posto per vedere tutto il gruppo. Un agente si
// modifica sempre dalla sua scheda (qui solo un rimando), per non tenere due copie degli stessi campi.
let schedaGruppoId = null;
function rigaSquadraGruppo(a) {
  const riga = el("div", { class: "agente", style: `--c:${aspettoDi(a).colore}` },
    avatar(a),
    el("div", { class: "testo" }, el("b", {}, nomeDi(a)), el("small", {}, (a.capogruppo ? "capogruppo · " : "") + progettoDi(a))),
    el("span", { class: "mod" }, a.modello));
  riga.addEventListener("click", () => { $("scheda-gruppo").close(); apriScheda(a.key); });
  return riga;
}
function apriSchedaGruppo(gid) {
  fissaGruppi();
  const g = PAN.gruppi.find((x) => x.id === gid);
  if (!g) return;
  schedaGruppoId = gid;
  // se il gruppo è anche uno spazio vero (spazi.json), si vedono le cartelle vere e la memoria
  const spazioVero = gid.startsWith("spazio-") && (spaziCat || []).find((s) => s.id === gid.slice(7));
  const cartellaDi = (pid) => spazioVero && (spazioVero.progetti.find((p) => p.id === pid) || {}).cartella;
  const agenti = g.agenti.map((k) => AGENTI.get(k)).filter(Boolean);
  const perProgetto = new Map();
  for (const a of agenti) { if (!perProgetto.has(a.progetto)) perProgetto.set(a.progetto, []); perProgetto.get(a.progetto).push(a); }
  $("sg-nome").value = g.nome;
  $("sg-sotto").textContent = `${perProgetto.size} ${perProgetto.size === 1 ? "progetto" : "progetti"} · ${agenti.length} ${agenti.length === 1 ? "agente" : "agenti"}`;
  $("sg-memoria").replaceChildren(...(spazioVero ? [
    el("div", {}, "Memoria: ", el("code", {}, spazioVero.memoria)),
    el("div", {}, "Report: ", el("code", {}, spazioVero.report)),
  ] : []));
  $("sg-progetti").replaceChildren(...[...perProgetto.entries()].map(([pid, lista]) => {
    const capo = lista.find((a) => a.capogruppo);
    const primo = capo || lista[0];
    const specialisti = lista.filter((a) => a !== capo);
    const cartella = cartellaDi(pid);
    return el("div", { class: "agente", style: `--c:${aspettoDi(primo).colore}` },
      avatar(primo),
      el("div", { class: "testo" }, el("b", {}, capo ? nomeDi(capo) : progettoDi(primo)),
        el("small", {}, (capo ? "capogruppo · " : "senza capogruppo · ") + progettoDi(primo) +
          (specialisti.length ? ` · ${specialisti.length} specialisti` : "")),
        cartella ? el("small", {}, el("code", {}, cartella)) : ""),
      el("button", { class: "piccolo", type: "button", onclick: () => { $("scheda-gruppo").close(); apriScheda(primo.key); } }, "Apri"),
      capo ? el("button", { class: "piccolo", type: "button", "data-solo-mac": "agente:crea_squadra", title: "Il CEO legge la cartella e crea gli agenti che mancano (mai quelli che hai eliminato)",
        onclick: async (ev) => { const d = await azione({ tipo: "agente", cosa: "crea_squadra", progetto: pid }, ev.currentTarget); if (d) toast(d.messaggio); } }, "Il CEO compone la squadra") : "",
      // 02/10/2026 (audit menu, P5): un progetto solo, anche senza capogruppo, con lo stesso dialogo della lavagna
      bottoneTogliProgetto(spazioVero, pid));
  }));
  // i progetti dello spazio che non hanno ancora agenti (cartella appena nata): si vedono e si tolgono lo stesso
  if (spazioVero) for (const p of spazioVero.progetti) if (!perProgetto.has(p.id)) $("sg-progetti").append(el("div", { class: "agente" },
    el("span", { class: "avatar" }, "📁"),
    el("div", { class: "testo" }, el("b", {}, p.nome), el("small", {}, "nessun agente ancora"), el("small", {}, el("code", {}, p.cartella))),
    bottoneTogliProgetto(spazioVero, p.id)));
  $("sg-quanti").textContent = `(${agenti.length})`;
  $("sg-squadra").replaceChildren(...agenti.map(rigaSquadraGruppo));
  const sv = spazioDi(gid);
  $("sg-togli").style.display = sv && sv.sistema ? "none" : "";
  $("sg-togli").textContent = gid.startsWith("spazio-") ? "✕ Elimina o sospendi lo spazio" : "✕ Togli gruppo";
  $("sg-togli").title = gid.startsWith("spazio-") ? "Stesso dialogo della lavagna: sospendi gli agenti o archivia i progetti (le cartelle restano)"
    : "Gli agenti tornano al loro spazio: i profili non si toccano";
  $("scheda-gruppo").showModal();
}
function bottoneTogliProgetto(sv, pid) {
  const p = sv && !sv.sistema && sv.progetti.find((q) => q.id === pid);
  if (!p) return "";
  return el("button", { class: "piccolo pericolo", type: "button", "data-solo-mac": "agente:togli_gruppo", title: "Elimina o sospendi solo questo progetto (la cartella resta)",
    onclick: () => { $("scheda-gruppo").close(); chiediTogliGruppi([{ nome: p.nome, progetti: [p], etichetta: etichettaCartella(sv, p) }], true); } }, "Togli");
}
$("sg-lavagna").addEventListener("click", () => { $("scheda-gruppo").close(); apriGruppoInLavagna(schedaGruppoId); location.hash = "#lavagna"; });
$("sg-nuovo-agente").addEventListener("click", () => { $("scheda-gruppo").close();
  apriNuovoAgente(schedaGruppoId.startsWith("spazio-") ? schedaGruppoId.slice(7) : null); });
$("sg-togli").addEventListener("click", () => {
  const g = PAN.gruppi.find((x) => x.id === schedaGruppoId);
  if (!g) return;
  if (!schedaGruppoId.startsWith("spazio-") && !confirm(`Togliere il gruppo ${g.nome}?\n\nGli agenti tornano al loro spazio: i profili non si toccano.`)) return;
  $("scheda-gruppo").close();
  togliGruppoMenu(schedaGruppoId);
});
$("form-scheda-gruppo").addEventListener("submit", (ev) => {
  if (!ev.submitter || ev.submitter.value !== "salva") return;
  const g = PAN.gruppi.find((x) => x.id === schedaGruppoId);
  const nome = $("sg-nome").value.trim().slice(0, 60);
  if (g && nome && nome !== g.nome) {
    if (g.id.startsWith("spazio-")) azione({ tipo: "agente", cosa: "rinomina_spazio", spazio: g.id.slice(7), nome }).then((d) => { if (d) { caricaSpazi(); ricaricaSeCambiato(); } });
    else { g.nome = nome; salvaPannello(); disegnaGruppi(); }
  }
});
$("btn-ripristina-gruppi").addEventListener("click", () => {
  if (!confirm("Tornare ai gruppi per spazio? I gruppi creati da te spariscono (emoji, colori e lavagna restano).")) return;
  PAN.gruppi = [];
  salvaPannello();
  disegnaGruppi();
});
$("cerca-agenti").addEventListener("input", (ev) => { filtro = ev.target.value.trim(); disegnaGruppi(); });

// ------------------------------------------------ chi lavora DAVVERO adesso (26/09/2026, richiesta dell'utente)
// Una sola fonte, attivita(s), calcolata a ogni giro di aggiorna() (col flusso: in tempo reale).
// Sorgenti: gli agenti «attivo» della sessione di Claude, gli esperti e il capo delle missioni, i
// lavori in corso (interlocutore «progetto:agente» o «jarvis»), le sessioni di Claude che lavorano
// dentro la cartella di un progetto, le chat di questa pagina che aspettano una risposta.
// segnaAttivi() la mette in pagina: colonna sinistra, catena, lavagna, testa della chat.
let ATTIVITA = { agenti: new Set(), progetti: new Set(), jarvis: false, utente_ts: 0 };
let firmaAttivita = "";
let timerUtente = null;
function trovaAgente(nome) {
  const n = String(nome || "").trim();
  if (!n) return null;
  const tutti = [...AGENTI.values()];
  return tutti.find((a) => a.nome === n || nomeDi(a) === n) || (n.length >= 5 ? tutti.find((a) => stessoNome(a.nome, n)) : null) || null;
}
// ~/… e /Users/<utente>/… sono la stessa cartella; basta anche lo stesso nome dell'ultima cartella
function stessaCartella(dove, cartella) {
  const norm = (x) => String(x || "").replace(/^\/Users\/[^/]+/, "~").replace(/\/+$/, "");
  const d = norm(dove), c = norm(cartella);
  return !!d && !!c && (d === c || d.startsWith(c + "/") || d.split("/").pop() === c.split("/").pop());
}
function attivita(s) {
  const agenti = new Set(), progetti = new Set();
  let jarvis = !!(s.claude_ora && s.claude_ora.lavorando);
  const perNome = (n) => { const a = trovaAgente(n); if (a) agenti.add(a.key); return !!a; };
  for (const g of (s.claude_ora && s.claude_ora.agenti) || []) if (g.stato === "attivo") perNome(g.nodo || g.tipo);
  for (const m of s.agenti_attivi || []) {
    for (const e of m.esperti || []) perNome(e.nome);
    if (m.chi) perNome(m.chi);
  }
  for (const l of s.lavori || []) {
    if (l.stato !== "in corso") continue;
    const k = l.interlocutore || (l.info || {}).interlocutore || "";
    if (k === "jarvis" || /^jarvis$/i.test(l.chi || "")) jarvis = true;
    else if (AGENTI.has(k)) agenti.add(k);
    else if (l.chi) perNome(l.chi);
  }
  for (const [k, t] of Object.entries(THREADS)) if (t.attesa) { if (k === "jarvis") jarvis = true; else if (AGENTI.has(k)) agenti.add(k); }
  if (CATENA_GIRO && CATENA_GIRO.coinvolti) for (const k of CATENA_GIRO.coinvolti) agenti.add(k);
  const sessioni = ((s.locale || {}).agenti_sessioni || {}).sessioni || [];
  for (const x of sessioni) if (x.lavora && x.dove)
    for (const sp of spaziCat || []) for (const p of sp.progetti || []) if (stessaCartella(x.dove, p.cartella)) progetti.add(p.id);
  for (const k of agenti) { const a = AGENTI.get(k); if (a) progetti.add(a.progetto); }
  const rt = s.claude_ora && s.claude_ora.richiesta_ts;
  const utente_ts = rt && Date.now() / 1000 - rt < 8 ? rt : 0;
  return { agenti, progetti, jarvis, utente_ts };
}
function aggiornaAttivita(s) {
  ATTIVITA = attivita(s);
  const firma = JSON.stringify([[...ATTIVITA.agenti].sort(), [...ATTIVITA.progetti].sort(), ATTIVITA.jarvis, !!ATTIVITA.utente_ts]);
  // l'utente resta acceso 8 s dopo la richiesta: poi si ricalcola da solo, anche senza un giro nuovo
  clearTimeout(timerUtente);
  if (ATTIVITA.utente_ts) timerUtente = setTimeout(() => { if (ultimoStato) aggiornaAttivita(ultimoStato); }, Math.max(200, (ATTIVITA.utente_ts + 8) * 1000 - Date.now()));
  if (firma === firmaAttivita) return;             // si ridisegna solo quando cambia qualcosa
  firmaAttivita = firma;
  segnaAttivi();
}
// la nota della lavagna che rappresenta Jarvis, l'utente, uno spazio o un progetto senza capogruppo
function notaAccesa(n) {
  const t = String(n.testo || "");
  if (/^Jarvis\b/.test(t)) return ATTIVITA.jarvis;
  if (/^l'utente$/.test(t)) return !!ATTIVITA.utente_ts;
  for (const s of spaziCat || []) {
    if (t === s.nome) return s.progetti.some((p) => ATTIVITA.progetti.has(p.id));
    for (const p of s.progetti) if (t === p.nome + " · senza capogruppo") return ATTIVITA.progetti.has(p.id);
  }
  return false;
}
function segnaAttivi() {
  const A = ATTIVITA;
  // righe con un agente (colonna sinistra, Agenti per spazio): anello attorno all'avatar e alone
  for (const r of document.querySelectorAll("[data-agente]:not(.nodo)")) r.classList.toggle("attivo", A.agenti.has(r.dataset.agente));
  // gruppi della colonna sinistra: si accendono anche chiusi, con «N al lavoro»
  for (const g of gruppiEffettivi()) {
    const box = document.querySelector(`.gruppo[data-gruppo="${CSS.escape(g.id)}"]`);
    if (!box) continue;
    const n = g.agenti.filter((k) => A.agenti.has(k)).length;
    const progetto = g.agenti.some((k) => A.progetti.has((AGENTI.get(k) || {}).progetto));
    box.classList.toggle("acceso", n > 0 || progetto);
    const testa = box.querySelector(".gruppo-testa");
    let vivo = testa && testa.querySelector(".al-lavoro-n");
    if (testa && !vivo) { vivo = el("small", { class: "al-lavoro-n" }); testa.querySelector(".quanti").before(vivo); }
    if (vivo) vivo.textContent = n ? `${n} al lavoro` : progetto ? "al lavoro" : "";
  }
  for (const sp of document.querySelectorAll(".sotto-progetto[data-progetto]")) sp.classList.toggle("acceso", A.progetti.has(sp.dataset.progetto));
  // lavagna (tutte tranne la dimostrazione, che si accende da sola)
  if (!eDemo(lavagnaAttiva)) {
    for (const n of document.querySelectorAll("#lav-mondo .nodo")) {
      const nodo = nodoDi(n.dataset.id);
      if (!nodo) continue;
      n.classList.toggle("al-lavoro", nodo.tipo === "agente" ? A.agenti.has(nodo.agente) : notaAccesa(nodo));
    }
    marcaFili();
  }
  // testa della chat: l'interlocutore al lavoro
  const av = $("chat-avatar");
  if (av) av.classList.toggle("al-lavoro", !!(THREADS[chatCon] && THREADS[chatCon].attesa) ||
    (chatCon === "jarvis" ? A.jarvis : A.agenti.has(chatCon)));
  applicaSinapsi();
  try { segnaIndicatoriAttivita(); } catch (e) { /* all'avvio, prima che il blocco Attività sia letto */ }   // le righe ridisegnate li perdono
}
// ------------------------------------------------ sinapsi: chi comunica con chi (contratto, punto 11, 26/09/2026 sera)
// s.comunicazioni: le ultime 60, più recenti prima, {ts, da, a, testo, tipo, stato, id}. Chiavi: utente,
// jarvis, sentinella, «progetto:nome» o il solo nome. Sulla lavagna attiva il filo da → a scorre nel
// verso giusto (se il filo non c'è, uno temporaneo tratteggiato per 20 s) e una bolla col testo sta
// sopra la scheda di arrivo finché la comunicazione è in corso («finito» la spegne, «errore» è rossa).
// In colonna la riga di chi riceve dice «← da chi: testo» per 15 s. Il pannello «Sinapsi» tiene le 60.
const SINAPSI = { lista: [], timer: null, chiave: "", chiuse: new Set(), trascino: null };
function agenteDaChiave(k) {
  k = String(k || "");
  if (AGENTI.has(k)) return AGENTI.get(k);
  // utente, jarvis e sentinella non sono agenti: «jarvis» somiglierebbe a «x-ricerca-jarvis»
  if (/^(utente|jarvis|sentinella|memoria)$/i.test(k) || /:orchestratore$/i.test(k)) return null;
  return trovaAgente(k.includes(":") ? k.split(":").pop() : k);
}
// «<progetto>:orchestratore» (missioni): il progetto, per mostrarlo e per trovargli una scheda
function progettoOrchestratore(k) {
  const m = String(k || "").match(/^([^:]+):orchestratore$/i);
  return m ? (spaziCat || []).flatMap((s) => s.progetti).find((p) => p.id === m[1]) || { id: m[1], nome: m[1], agenti: [] } : null;
}
function nomeChiave(k) {
  const x = String(k || "").toLowerCase();
  const orch = progettoOrchestratore(k);
  if (orch) return `orchestratore · ${orch.nome}`;
  if (x === "utente") return nomeUtente();
  if (x === "jarvis") return ASSISTENTE;
  if (x === "sentinella") return "Sentinella";
  if (x === "memoria") return "Memoria";
  const a = agenteDaChiave(k);
  return a ? nomeDi(a) : String(k || "?").split(":").pop();
}
function aggiornaSinapsi(lista) {
  SINAPSI.lista = (lista || []).filter((c) => c && c.id);
  const ol = $("sinapsi-lista");
  $("sinapsi-conta").textContent = SINAPSI.lista.length ? `${SINAPSI.lista.length} · ultima ${oraDi(SINAPSI.lista[0].ts)}` : "nessuna comunicazione ancora";
  ol.replaceChildren(...SINAPSI.lista.map((c) => el("li", { class: "sin-" + String(c.stato || "").replace(" ", "-") },
    el("time", {}, oraDi(c.ts)),
    el("b", {}, nomeChiave(c.da) + " → " + nomeChiave(c.a)),
    el("span", {}, c.testo || ""),
    el("small", {}, [c.tipo, c.stato].filter(Boolean).join(" · ")))));
  applicaSinapsi();
}
const oraDi = (ts) => ts ? new Date(ts * 1000).toTimeString().slice(0, 8) : "--:--";
// la scheda della lavagna per una chiave: agenti per chiave, l'utente e Jarvis per le loro note
function schedaDiChiave(k) {
  const x = String(k || "").toLowerCase();
  const nodi = lav().nodi;
  let n = null;
  if (x === "utente") n = nodi.find((z) => z.tipo === "nota" && /^(l'utente|Umano)/.test(z.testo || ""));
  else if (x === "jarvis") n = nodi.find((z) => z.tipo === "nota" && /^Jarvis\b/.test(z.testo || ""));
  else if (x === "sentinella") n = nodi.find((z) => z.tipo === "nota" && /^Sentinella/i.test(z.testo || ""));
  else if (x === "memoria") n = nodi.find((z) => z.tipo === "nota" && /^Memoria$/i.test(z.testo || ""));
  else if (progettoOrchestratore(k)) {
    // l'orchestratore di una missione non ha una scheda: si usa il capogruppo del progetto, o la sua etichetta
    const p = progettoOrchestratore(k);
    const capo = [...AGENTI.values()].find((a) => a.progetto === p.id && a.capogruppo);
    n = (capo && nodi.find((z) => z.agente === capo.key)) || nodi.find((z) => z.tipo === "nota" && z.testo === p.nome + " · senza capogruppo");
  } else {
    const a = agenteDaChiave(k);
    if (a) n = nodi.find((z) => z.agente === a.key);
    // gli agenti di casa di Jarvis (esecutore, ricercatore-web…) sono note accanto a lui nella catena
    const nome = String(k || "").split(":").pop();
    if (!n) n = nodi.find((z) => z.tipo === "nota" && (z.testo === nome || String(z.testo || "").startsWith(nome + " · ")));
  }
  return n ? document.querySelector(`#lav-mondo .nodo[data-id="${CSS.escape(n.id)}"]`) : null;
}
// «Sentinella» e «Memoria» possono mancare in una lavagna: se servono si mettono solo in pagina, accanto a Jarvis
function schedaTemporanea(nome, dx, dy) {
  const classe = nome.toLowerCase();
  let d = document.querySelector(`#lav-mondo .nodo.sinapsi-tmp.${classe}`);
  if (d) return d;
  const j = schedaDiChiave("jarvis");
  if (!j) return null;
  d = el("div", { class: `nodo nota sinapsi-tmp ${classe}`, title: nome }, el("div", { class: "testo-nota" }, nome));
  d.style.left = (j.offsetLeft + dx) + "px"; d.style.top = (j.offsetTop + dy) + "px";
  $("lav-mondo").append(d);
  return d;
}
const schedaSpeciale = (k) => { const x = String(k || "").toLowerCase();
  if (x === "sentinella") return schedaDiChiave(k) || schedaTemporanea("Sentinella", -230, 0);
  if (x === "memoria") return schedaDiChiave(k) || schedaTemporanea("Memoria", -230, 80);
  return schedaDiChiave(k); };
function rettDom(d) { const x = d.offsetLeft, y = d.offsetTop, w = d.offsetWidth, h = d.offsetHeight; return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 }; }
// ---- le bolle sono schede flottanti della tela (richiesta dell'utente, 26/09/2026 18:32)
// Stanno nel «mondo» (seguono zoom e scorrimento), si trascinano come le schede e ricordano dove le
// metti: scostamento (dx, dy) dalla scheda di arrivo, per agente, in lav().bolle (pannello.json). Il server
// oggi tiene della lavagna solo nodi, fili e vista: una copia resta nel browser finché non tiene anche «bolle».
function chiaveBolla(B) { return B.dataset.agente || "nota:" + (B.dataset.id || [...B.classList].find((x) => x !== "nodo" && x !== "nota" && x !== "sinapsi-tmp") || "?"); }
function bolleSalvate() {
  const L = lav();
  if (!L.bolle) L.bolle = mem.leggi("bolle:" + lavagnaAttiva, {}) || {};
  return L.bolle;
}
function salvaBolle() {
  mem.scrivi("bolle:" + lavagnaAttiva, lav().bolle || {});
  salvaPannello();
}
// il rettangolo del foglio che si vede adesso, in coordinate del mondo
function vistaMondo() {
  const r = $("lavagna").getBoundingClientRect(), v = vista();
  return { x: -v.x / v.zoom, y: -v.y / v.zoom, w: r.width / v.zoom, h: r.height / v.zoom };
}
function posaBolla(B, c) {
  const r = rettDom(B), chiave = chiaveBolla(B);
  const bolla = el("div", { class: "sinapsi-tmp sinapsi-bolla" + (c.stato === "errore" ? " errore" : "") + (B.classList.contains("sinapsi-tmp") ? " temporanea" : ""),
    title: (c.testo || "") + "\n\ntrascina per spostarla: la posizione resta per le prossime" },
    el("div", { class: "bolla-comandi" },
      el("button", { type: "button", class: "icona", title: "Rimettila al posto di partenza", onpointerdown: (ev) => ev.stopPropagation(), onclick: (ev) => { ev.stopPropagation();
        delete bolleSalvate()[chiave]; salvaBolle(); applicaSinapsi(); } }, "⌖"),
      el("button", { type: "button", class: "icona", title: "Chiudi questa bolla", onpointerdown: (ev) => ev.stopPropagation(), onclick: (ev) => { ev.stopPropagation();
        SINAPSI.chiuse.add(c.id); bolla.remove(); } }, "×")),
    el("b", {}, nomeChiave(c.da) + " → "), (c.testo || "").slice(0, 90));
  bolla.__arrivo = B;
  $("lav-mondo").append(bolla);
  const inv = Math.min(1.8, 1 / vista().zoom), bw = bolla.offsetWidth * inv, bh = bolla.offsetHeight * inv;
  const salvata = bolleSalvate()[chiave];
  let x, y;
  if (salvata) { x = r.x + salvata.dx; y = r.y + salvata.dy; }
  else {
    // partenza: sopra la scheda e spostata a destra, così non copre le schede vicine; dentro la parte visibile
    const vm = vistaMondo();
    x = r.x + r.w + 16; y = r.y - bh - 10;
    if (x + bw > vm.x + vm.w - 10) x = r.x - bw - 16;
    x = Math.max(vm.x + 10, Math.min(x, vm.x + vm.w - bw - 10));
    y = Math.max(vm.y + 10, Math.min(y, vm.y + vm.h - bh - 10));
  }
  bolla.style.left = Math.round(x) + "px"; bolla.style.top = Math.round(y) + "px";
  // si trascina come una scheda; lasciandola si salva lo scostamento dalla scheda di arrivo
  bolla.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    ev.stopPropagation();
    const m = puntoMondo(ev.clientX, ev.clientY);
    SINAPSI.trascino = { bolla, dx: m.x - parseFloat(bolla.style.left), dy: m.y - parseFloat(bolla.style.top), mosso: false };
    bolla.classList.add("trascina");
  });
}
addEventListener("pointermove", (ev) => {
  const g = SINAPSI.trascino;
  if (!g) return;
  const m = puntoMondo(ev.clientX, ev.clientY);
  g.bolla.style.left = Math.round(m.x - g.dx) + "px"; g.bolla.style.top = Math.round(m.y - g.dy) + "px";
  g.mosso = true;
});
addEventListener("pointerup", () => {
  const g = SINAPSI.trascino;
  if (!g) return;
  SINAPSI.trascino = null;
  g.bolla.classList.remove("trascina");
  if (!g.mosso) return;
  const B = g.bolla.__arrivo;
  if (!B) return;
  const r = rettDom(B);
  bolleSalvate()[chiaveBolla(B)] = { dx: Math.round(parseFloat(g.bolla.style.left) - r.x), dy: Math.round(parseFloat(g.bolla.style.top) - r.y) };
  salvaBolle();
});

// forza=false (dal timer): si ridisegna solo se cambia cosa va mostrato, così le animazioni non ripartono
// Se fra i due nodi non c'è un filo diretto (Jarvis → gruppo «Agenti di Jarvis» → postino) si cerca il percorso
// più corto sui fili veri della lavagna e si accende ogni tratto, nel verso in cui va la comunicazione (29/09/2026).
function accendiPercorso(idA, idB, c, errore) {
  if (!idA || !idB) return false;
  const fili = lav().fili || [];
  const vicini = new Map();
  for (const f of fili) {
    if (!vicini.has(f.da)) vicini.set(f.da, []);
    if (!vicini.has(f.a)) vicini.set(f.a, []);
    vicini.get(f.da).push(f.a); vicini.get(f.a).push(f.da);
  }
  const prima = new Map([[idA, null]]);
  const coda = [idA];
  while (coda.length && !prima.has(idB)) {
    const x = coda.shift();
    for (const y of vicini.get(x) || []) if (!prima.has(y)) { prima.set(y, x); coda.push(y); }
  }
  if (!prima.has(idB)) return false;
  const passi = [];
  for (let y = idB; prima.get(y) != null; y = prima.get(y)) passi.unshift([prima.get(y), y]);
  if (passi.length < 2 || passi.length > 5) return false;           // 1 passo l'ha già preso il codice sopra
  let acceso = 0;
  for (const [da, a] of passi) {
    const dritto = document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(da)}"][data-a="${CSS.escape(a)}"]`);
    const rovescio = !dritto && document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(a)}"][data-a="${CSS.escape(da)}"]`);
    const p = dritto || rovescio;
    if (!p) continue;
    p.classList.add("sinapsi");
    p.classList.toggle("inverso", !!rovescio);
    p.classList.toggle("errore", errore);
    p.classList.toggle("risposta", c.tipo === "risposta" && !errore);
    acceso++;
  }
  return acceso > 0;
}
function applicaSinapsi(forza = true) {
  clearTimeout(SINAPSI.timer);
  // mentre si trascina una bolla non si ridisegna: si riprova fra poco
  if (SINAPSI.trascino) { SINAPSI.timer = setTimeout(() => applicaSinapsi(forza), 500); return; }
  const adesso = Date.now() / 1000;
  const chiave = lavagnaAttiva + "|" + SINAPSI.chiuse.size + "|" + SINAPSI.lista.filter((c) => c.stato === "in corso" || adesso - (c.ts || 0) < 20)
    .map((c) => [c.id, c.stato, adesso - c.ts < 8, adesso - c.ts < 15].join(":")).join(",");
  if (!forza && chiave === SINAPSI.chiave) { if (chiave.includes(":")) SINAPSI.timer = setTimeout(() => applicaSinapsi(false), 1000); return; }
  SINAPSI.chiave = chiave;
  // via quello che la volta prima era solo delle sinapsi
  document.querySelectorAll(".sinapsi-tmp").forEach((n) => n.remove());
  document.querySelectorAll("#lav-fili path.sinapsi").forEach((p) => p.classList.remove("sinapsi", "inverso", "errore", "risposta"));
  document.querySelectorAll(".agente.riceve").forEach((r) => r.classList.remove("riceve"));
  document.querySelectorAll(".gruppo.sinapsi").forEach((g) => g.classList.remove("sinapsi"));
  const ora = Date.now() / 1000;
  // chi l'utente ha chiuso con la × resta chiuso (27/09/2026: il Set si riempiva ma non si leggeva mai)
  const vive = SINAPSI.lista.filter((c) => !SINAPSI.chiuse.has(c.id) && (c.stato === "in corso" || ora - (c.ts || 0) < 20));
  if (!vive.length) return;
  // lavagna (non la dimostrazione, che ha la sua animazione)
  if (!eDemo(lavagnaAttiva)) {
    const bolle = new Map();                                // una bolla per scheda: la comunicazione più recente
    for (const c of [...vive].reverse()) {                  // le più recenti per ultime: vincono
      const A = schedaSpeciale(c.da), B = schedaSpeciale(c.a);
      const errore = c.stato === "errore";
      if (A && B && A !== B) {
        const idA = A.dataset.id, idB = B.dataset.id;
        const dritto = idA && idB && document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(idA)}"][data-a="${CSS.escape(idB)}"]`);
        const rovescio = !dritto && idA && idB && document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(idB)}"][data-a="${CSS.escape(idA)}"]`);
        const p = dritto || rovescio;
        if (p) { p.classList.add("sinapsi"); p.classList.toggle("inverso", !!rovescio); p.classList.toggle("errore", errore); p.classList.toggle("risposta", c.tipo === "risposta" && !errore); }
        else if (accendiPercorso(idA, idB, c, errore)) { /* acceso lungo i fili veri, passando dai gruppi */ }
        else {                                              // nessun filo: uno temporaneo, tratteggiato
          const ra = rettDom(A), rb = rettDom(B);
          const q = document.createElementNS("http://www.w3.org/2000/svg", "path");
          q.setAttribute("d", curva(puntoVersoAltro(ra, rb.cx, rb.cy), puntoVersoAltro(rb, ra.cx, ra.cy)));
          q.setAttribute("class", "sinapsi-tmp filo-temp sinapsi" + (errore ? " errore" : c.tipo === "risposta" ? " risposta" : ""));
          $("lav-fili").append(q);
        }
      }
      if (B && (c.stato === "in corso" || errore || ora - (c.ts || 0) < 8) && !SINAPSI.chiuse.has(c.id)) bolle.set(B, c);
    }
    for (const [B, c] of bolle) posaBolla(B, c);
  }
  // colonna sinistra: chi riceve, per 15 s
  for (const c of vive) {
    if (ora - (c.ts || 0) >= 15) continue;
    const a = agenteDaChiave(c.a);
    if (!a) continue;
    for (const r of document.querySelectorAll(`.agente[data-agente="${CSS.escape(a.key)}"]`)) {
      if (r.classList.contains("riceve")) continue;           // una riga, la comunicazione più recente
      r.classList.add("riceve");
      const small = r.querySelector(".testo");
      if (small) small.append(el("small", { class: "sinapsi-tmp sinapsi-riga" + (c.stato === "errore" ? " errore" : "") },
        `← da ${nomeChiave(c.da)}: ${(c.testo || "").slice(0, 80)}`));
      const g = r.closest(".gruppo");
      if (g) g.classList.add("sinapsi");
    }
  }
  // finché qualcosa è vivo si ricontrolla ogni secondo: le scadenze (15 s, 20 s) passano col tempo
  SINAPSI.timer = setTimeout(() => applicaSinapsi(false), 1000);
}

// i fili che arrivano a una scheda accesa scorrono (stessa classe della dimostrazione)
function marcaFili() {
  if (eDemo(lavagnaAttiva)) return;
  const accesi = new Set([...document.querySelectorAll("#lav-mondo .nodo.al-lavoro")].map((n) => n.dataset.id));
  for (const p of document.querySelectorAll("#lav-fili path.filo")) p.classList.toggle("acceso", accesi.has(p.dataset.a));
}

// ------------------------------------------------ scheda di un agente
let schedaKey = null;
async function apriScheda(k) {
  const a = AGENTI.get(k);
  if (!a) return;
  schedaKey = k;
  const s = aspettoDi(a);
  $("sa-avatar").replaceWith(Object.assign(avatar(a, "avatar grande"), { id: "sa-avatar" }));
  $("sa-nome").textContent = nomeDi(a);
  $("sa-dove").textContent = `profilo ${a.nome} · ${a.spazioNome} · ${progettoDi(a)} · ${a.modello}${a.capogruppo ? " · capogruppo" : ""}`;
  $("sa-vdescr").value = a.descrizione || "";   // la versione troncata, finché non arriva quella intera
  $("sa-vmodello").value = a.modello;
  $("sa-vstrumenti").value = (a.strumenti || []).join(", ");
  // tono, umorismo, attivo, «comunica con» (punto 13): dal server nuovo; col vecchio si vedono ma non si scrivono
  const nuovo = a.nuovo;
  $("sa-vtono").value = a.tono || "";
  $("sa-vumor").value = a.umorismo; $("sa-vumor-t").textContent = UMORISMO[a.umorismo] || "";
  $("sa-vseri").value = a.serieta; $("sa-vseri-t").textContent = SERIETA[a.serieta] || "";
  disegnaAttivoScheda(a.attivo);
  for (const id of ["sa-vtono", "sa-vumor", "sa-vseri", "sa-attivo", "sa-togli", "sa-sotto", "sa-togli-gruppo"]) $(id).disabled = !nuovo;
  $("sa-togli-gruppo").classList.toggle("nascosto", !a.capogruppo);
  $("sa-nota-server").textContent = nuovo ? "" : "Tono, umorismo, attivo e archivio si scrivono col server nuovo.";
  SA_COMUNICA = a.comunica ? [...a.comunica] : [];
  $("sa-comunica-nomi").replaceChildren(...[...AGENTI.values()].filter((x) => x.key !== k)
    .sort((x, y) => (y.progetto === a.progetto) - (x.progetto === a.progetto)).map((x) => el("option", { value: x.nome }, x.progettoNome)));
  disegnaComunicaScheda();
  $("sa-alias").value = (PAN.aspetto[k] || {}).nome || "";
  $("sa-alias").placeholder = a.nome;
  $("sa-nota").value = notaDi(a);
  $("sa-emoji").value = s.emoji;
  $("sa-colore").value = /^#[0-9a-f]{6}$/i.test(s.colore) ? s.colore : s.riserva;
  const gruppi = gruppiEffettivi();
  const dentro = gruppi.find((g) => g.agenti.includes(k));
  $("sa-gruppo").replaceChildren(...gruppi.map((g) => el("option", { value: g.id }, g.nome)));
  if (dentro) $("sa-gruppo").value = dentro.id;
  disegnaDipendenzeScheda();
  caricaAttivita(k);
  $("sa-vlimiti").value = "";
  caricaDiario(k);
  schedaProfilo = null;
  $("scheda-agente").showModal();
  if (a.file) {
    try {
      const p = await api("/api/agente-profilo?file=" + encodeURIComponent(a.file));
      if (schedaKey === k) {
        $("sa-vdescr").value = p.description; $("sa-vmodello").value = p.model; $("sa-vstrumenti").value = p.tools;
        $("sa-vlimiti").value = p.limiti || "";
        // Il confronto per «Salva» si fa con quello che i campi mostrano ADESSO, con la descrizione
        // intera: prima si confrontava con la versione tagliata a 160 caratteri e ogni apertura e
        // chiusura della scheda riscriveva il file .md anche senza nessuna modifica.
        // «comunica con»: dal campo del server nuovo, altrimenti dal blocco scritto nel corpo del profilo
        if (!a.comunica) { SA_COMUNICA = nomiComunica(p.corpo); disegnaComunicaScheda(); }
        schedaProfilo = { k, descr: $("sa-vdescr").value.trim(), modello: $("sa-vmodello").value, strumenti: $("sa-vstrumenti").value.trim(),
          limiti: $("sa-vlimiti").value.trim(),
          tono: $("sa-vtono").value.trim(), umorismo: +$("sa-vumor").value, serieta: +$("sa-vseri").value, comunica: SA_COMUNICA.join(",") };
      }
    } catch (e) { /* resta la versione troncata già mostrata: il profilo vero in quel caso non si salva */ }
  }
}
let schedaProfilo = null;   // i valori del profilo vero come sono stati letti, per sapere se sono cambiati
function dipendenzeDi(k) {
  const nodi = lav().nodi, suoi = new Set(nodi.filter((n) => n.agente === k).map((n) => n.id));
  const out = new Map();
  for (const f of lav().fili) if (suoi.has(f.da)) {
    const n = nodi.find((x) => x.id === f.a);
    if (n) out.set(n.agente || n.id, n);
  }
  return [...out.values()];
}
function disegnaDipendenzeScheda() {
  const box = $("sa-dipende");
  const dip = dipendenzeDi(schedaKey);
  if (!dip.length) { box.replaceChildren(el("small", { class: "nota" }, "Nessuna. In lavagna tira il pallino di questa scheda su un'altra.")); return; }
  box.replaceChildren(...dip.map((n) => {
    const a = AGENTI.get(n.agente);
    return el("span", { class: "chip" }, a ? nomeDi(a) : (n.testo || "nota").slice(0, 24),
      el("button", { type: "button", title: "Togli la dipendenza", onclick: () => {
        const suoi = new Set(lav().nodi.filter((x) => x.agente === schedaKey).map((x) => x.id));
        lav().fili = lav().fili.filter((f) => !(suoi.has(f.da) && f.a === n.id));
        salvaPannello(); disegnaLavagna(); disegnaDipendenzeScheda();
      } }, "✕"));
  }));
}
// ---- Attività dell'agente (proposta 2026-10-02): «come stanno lavorando ogni singolo agente, come richieste
// inviate e ricevute». Dati da /api/agente-attivita (registro attivita/*.jsonl, 14 giorni). Si rilegge quando
// il flusso dice «attivita» e la scheda è aperta. «filo» accende sulla lavagna il collegamento di quella richiesta.
const ATT = { k: null, dati: null, sommario: null, evidenzia: null };
const STATO_ATT = { "al lavoro": "verde", "in attesa": "giallo", fermo: "grigio", errore: "rosso" };
function durataBreve(s) {
  if (s == null) return "—";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return Math.floor(s / 3600) + " h " + Math.round((s % 3600) / 60) + " min";
}
async function caricaAttivita(k) {
  ATT.k = k;
  const errori = $("sa-att-errori").checked ? "&errori=1" : "";
  try {
    const d = await api(`/api/agente-attivita?agente=${encodeURIComponent(k)}&lavagna=${encodeURIComponent(lavagnaAttiva)}&limite=200${errori}`);
    if (ATT.k !== k) return;                      // nel frattempo l'utente ha aperto un'altra scheda
    ATT.dati = d;
    disegnaAttivita();
  } catch (e) {
    $("sa-att-righe").replaceChildren(el("tr", {}, el("td", { colspan: "7", class: "nota" },
      "Attività non disponibili: " + e.message + " (server senza il registro delle attività?)")));
  }
}
function disegnaAttivita() {
  const d = ATT.dati;
  if (!d) return;
  const c = d.contatori || {};
  $("sa-att-stato").textContent = d.stato;
  $("sa-att-pallino").className = "pallino " + (STATO_ATT[d.stato] || "grigio");
  $("sa-att-conta").textContent = `${c.ricevute} ricevute · ${c.inviate} inviate · ${c.in_corso} in corso · ` +
    `${c.errori} errori · ${c.rimandate} rimandate` + (c.con_avvisi ? ` · ${c.con_avvisi} con avvisi` : "") +
    (c.ultima_ts ? ` · ultima ${oraDi(c.ultima_ts)}` : "") + (c.durata_media_s ? ` · media ${durataBreve(c.durata_media_s)}` : "");
  const verso = $("sa-att-verso").value;
  const righe = (d.righe || []).filter((r) => !verso || r.verso === verso);
  // gli avvisi sui collegamenti, una riga per tipo e controparte
  const avvisi = new Map();
  for (const r of righe) for (const a of r.avvisi || []) if (a.livello !== "info") avvisi.set(a.tipo + "|" + r.controparte, a.testo);
  $("sa-att-avvisi").replaceChildren(...[...avvisi.values()].map((t) => el("li", {}, "⚠ " + t)));
  if (!righe.length) { $("sa-att-righe").replaceChildren(el("tr", {}, el("td", { colspan: "7", class: "nota" }, "Nessuna richiesta negli ultimi 3 giorni."))); return; }
  $("sa-att-righe").replaceChildren(...righe.map((r) => {
    const problemi = (r.avvisi || []).filter((a) => a.livello !== "info");
    const titolo = [r.testo, r.esito && "esito: " + r.esito, r.errore && "errore: " + r.errore,
      r.fonte && "fonte: " + r.fonte + (r.missione ? " · missione " + r.missione : ""), ...problemi.map((a) => "⚠ " + a.testo)].filter(Boolean).join("\n");
    return el("tr", { class: "att-" + String(r.stato).replace(" ", "-") + (problemi.length ? " att-avviso" : ""), title: titolo },
      el("td", {}, el("time", {}, oraDi(r.inizio))),
      el("td", { class: "att-verso" }, r.verso === "ricevuta" ? "←" : "→"),
      el("td", {}, nomeChiave(r.controparte)),
      el("td", { class: "att-testo" }, r.testo || "—", r.errore ? el("small", { class: "att-errore" }, r.errore) : ""),
      el("td", {}, el("span", { class: "badge att-stato" }, r.senza_risposta ? "senza risposta" : r.stato), problemi.length ? el("span", { class: "att-segno", title: problemi.map((a) => a.testo).join("\n") }, "⚠") : ""),
      el("td", {}, durataBreve(r.durata_s)),
      el("td", {}, el("button", { type: "button", class: "piccolo", title: "Mostra questa richiesta sul filo della lavagna", onclick: () => mostraSulFilo(r) }, "filo")));
  }));
}
// accende per 20 s il filo da → a della richiesta (o un filo tratteggiato se manca), con la sua bolla
function mostraSulFilo(r) {
  $("scheda-agente").close();
  scegliPannello("lavagna");
  const A = schedaSpeciale(r.da), B = schedaSpeciale(r.a);
  if (!A || !B) { toast(`Su questa lavagna manca la scheda di ${nomeChiave(!A ? r.da : r.a)}: la richiesta non ha un filo da mostrare`, true); return; }
  const id = "evid:" + r.id;
  SINAPSI.lista = [{ id, ts: Date.now() / 1000, da: r.da, a: r.a, testo: r.testo, tipo: "lancio",
    stato: r.stato === "errore" ? "errore" : "in corso" }, ...SINAPSI.lista.filter((c) => c.id !== id)];
  SINAPSI.chiuse.delete(id);
  applicaSinapsi();
  B.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  clearTimeout(ATT.evidenzia);
  ATT.evidenzia = setTimeout(() => { SINAPSI.lista = SINAPSI.lista.filter((c) => c.id !== id); applicaSinapsi(); }, 20000);
}
$("sa-att-errori").addEventListener("change", () => { if (schedaKey) caricaAttivita(schedaKey); });
$("sa-att-verso").addEventListener("change", disegnaAttivita);
// indicatori nel menu laterale: ●N in corso, rosso se errori nelle ultime 24 ore, giallo se ci sono avvisi
async function caricaSommarioAttivita() {
  try { ATT.sommario = await api(`/api/agenti-attivita?lavagna=${encodeURIComponent(lavagnaAttiva)}`); }
  catch (e) { ATT.sommario = null; }
  segnaIndicatoriAttivita();
}
function segnaIndicatoriAttivita() {
  const s = (ATT.sommario && ATT.sommario.agenti) || {};
  for (const r of document.querySelectorAll(".agente[data-agente]")) {
    const x = s[r.dataset.agente];
    let ind = r.querySelector(".att-ind");
    if (!x) { if (ind) ind.remove(); continue; }
    if (!ind) { ind = el("span", { class: "att-ind" }); r.append(ind); }
    ind.className = "att-ind" + (x.errori_24h ? " errore" : x.avvisi ? " avviso" : x.in_corso ? " lavora" : "");
    ind.textContent = x.in_corso ? "●" + x.in_corso : x.errori_24h ? "!" + x.errori_24h : x.avvisi ? "⚠" : "";
    ind.title = `${x.ricevute} ricevute · ${x.inviate} inviate · ${x.in_corso} in corso · ${x.errori_24h} errori (24 h) · ` +
      `${x.avvisi} con avvisi di collegamento · ultima ${oraDi(x.ultima_ts)}`;
  }
  const n = Object.values((ATT.sommario && ATT.sommario.sconosciuti) || {}).reduce((t, v) => t + v, 0);
  const conta = $("sinapsi-conta");
  if (conta) conta.dataset.sconosciuti = n ? `· ${n} richieste senza destinatario` : "";
}
$("form-scheda").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value !== "salva") return;
  const a = AGENTI.get(schedaKey);
  if (!a) return;
  PAN.aspetto[schedaKey] = { emoji: $("sa-emoji").value.trim().slice(0, 8), colore: $("sa-colore").value,
    nome: $("sa-alias").value.trim().slice(0, 60), nota: $("sa-nota").value.trim().slice(0, 400) };
  const gid = $("sa-gruppo").value;
  const ora = gruppiEffettivi().find((g) => g.agenti.includes(schedaKey));
  if (!ora || ora.id !== gid) spostaAgente(schedaKey, gid, null); else salvaPannello();
  disegnaGruppi(); disegnaLavagna(); aggiornaTestaChat();
  // il profilo vero: solo se qualcosa nella scheda di Claude Code è cambiato davvero
  const descr = $("sa-vdescr").value.trim(), modello = $("sa-vmodello").value, strumenti = $("sa-vstrumenti").value.trim();
  const tono = $("sa-vtono").value.trim(), umorismo = +$("sa-vumor").value, serieta = +$("sa-vseri").value;
  const base = schedaProfilo && schedaProfilo.k === schedaKey ? schedaProfilo : null;
  // «comunica con» ha la sua strada, quella dei fili della lavagna (/api/agente-comunica)
  if (a.file && base && SA_COMUNICA.join(",") !== base.comunica) {
    try { await api("/api/agente-comunica", { file: a.file, comunica: SA_COMUNICA }); base.comunica = SA_COMUNICA.join(","); a.comunica = [...SA_COMUNICA]; }
    catch (e) { toast("«Comunica con» non salvato: " + e.message, true); }
  }
  if (a.file && base && a.nuovo && (tono !== base.tono || umorismo !== base.umorismo || serieta !== base.serieta)) {
    try { await api("/api/agente-profilo", Object.assign({ file: a.file }, tono !== base.tono ? { tono } : {}, umorismo !== base.umorismo ? { umorismo } : {}, serieta !== base.serieta ? { serieta } : {}));
      base.tono = tono; base.umorismo = umorismo; base.serieta = serieta; a.tono = tono; a.umorismo = umorismo; a.serieta = serieta; }
    catch (e) { toast("Tono, serietà e umorismo non salvati: " + e.message, true); }
  }
  if (a.file && !base) {
    toast("Aspetto salvato; il profilo vero non l'ho toccato perché non sono riuscito a leggerlo", true);
  } else if (a.file && (descr !== base.descr || modello !== base.modello || strumenti !== base.strumenti
             || $("sa-vlimiti").value.trim() !== (base.limiti || ""))) {
    // si mandano solo i campi cambiati: il server riscrive solo quelle righe del frontmatter
    const corpo = { file: a.file };
    if ($("sa-vlimiti").value.trim() !== (base.limiti || "")) corpo.limiti = $("sa-vlimiti").value.trim();
    if (descr !== base.descr) corpo.description = descr;
    if (modello !== base.modello) corpo.model = modello;
    if (strumenti !== base.strumenti) corpo.tools = strumenti;
    try {
      await api("/api/agente-profilo", corpo);
      if (descr !== base.descr) a.descrizione = descr.split(". ")[0].slice(0, 160);
      if (modello !== base.modello) a.modello = modello;
      if (strumenti !== base.strumenti) a.strumenti = strumenti.split(",").map((t) => t.trim()).filter(Boolean);
      schedaProfilo = { k: schedaKey, descr, modello, strumenti, limiti: $("sa-vlimiti").value.trim() };
      toast("Salvato: aspetto e profilo di Claude Code");
    } catch (e) { toast("Aspetto salvato, ma il profilo vero no: " + e.message, true); return; }
  } else toast("Salvato");
});
$("sa-chiedi").addEventListener("click", () => { $("scheda-agente").close(); apriChat(schedaKey); });
// ---- scheda agente: attivo (interruttore che scorre), «comunica con» a chip, togli (archivia)
let SA_COMUNICA = [];
function disegnaAttivoScheda(acceso) {
  const b = $("sa-attivo");
  b.classList.toggle("on", !!acceso);
  b.setAttribute("aria-pressed", String(!!acceso));
  $("sa-attivo-t").textContent = acceso ? "lavora nelle missioni" : "spento: le missioni non lo lanciano";
  $("scheda-agente").classList.toggle("spento", !acceso);
}
$("sa-attivo").addEventListener("click", async (ev) => {
  const a = AGENTI.get(schedaKey);
  if (!a) return;
  const valore = !ev.currentTarget.classList.contains("on");
  disegnaAttivoScheda(valore);                                   // l'interruttore scorre subito
  const d = await azione({ tipo: "agente", cosa: "attivo", progetto: a.progetto, nome: a.nome, valore }, ev.currentTarget);
  if (!d) { disegnaAttivoScheda(!valore); return; }
  a.attivo = valore;
  disegnaGruppi(); disegnaLavagna();
});
$("sa-vumor").addEventListener("input", (ev) => { $("sa-vumor-t").textContent = UMORISMO[+ev.target.value]; });
$("sa-vseri").addEventListener("input", (ev) => { $("sa-vseri-t").textContent = SERIETA[+ev.target.value]; });
function disegnaComunicaScheda() {
  const box = $("sa-comunica");
  box.replaceChildren(...(SA_COMUNICA.length ? SA_COMUNICA.map((nome, i) => el("span", { class: "chip" }, nome,
    el("button", { type: "button", title: "Togli", onclick: () => { SA_COMUNICA.splice(i, 1); disegnaComunicaScheda(); } }, "✕")))
    : [el("small", { class: "nota" }, "Nessuno. Aggiungilo qui sotto o tira un filo in lavagna.")]));
}
$("sa-comunica-aggiungi").addEventListener("click", () => {
  const nome = $("sa-comunica-nuovo").value.trim();
  if (nome && !SA_COMUNICA.includes(nome)) SA_COMUNICA.push(nome);
  $("sa-comunica-nuovo").value = "";
  disegnaComunicaScheda();
});
$("sa-sotto").addEventListener("click", () => {
  const a = AGENTI.get(schedaKey);
  if (!a) return;
  $("scheda-agente").close();
  apriNuovoAgente(a.spazio, a.progetto, a.nome);
});
$("sa-togli-gruppo").addEventListener("click", async (ev) => togliGruppo(AGENTI.get(schedaKey), ev.currentTarget));
async function togliGruppo(a, bottone) {
  if (!a || !confirm(`Togliere il gruppo ${a.progettoNome}?\n\nGli agenti del progetto vanno in un archivio dentro il progetto e il progetto esce dagli spazi. La cartella del progetto e la sua memoria restano dove sono.`)) return;
  const d = await azione({ tipo: "agente", cosa: "togli_gruppo", progetto: a.progetto }, bottone);
  if (d) { if ($("scheda-agente").open) $("scheda-agente").close(); caricaSpazi(); }
}
$("sa-togli").addEventListener("click", async (ev) => {
  const a = AGENTI.get(schedaKey);
  if (!a || !confirm(`Togliere ${nomeDi(a)} da ${a.progettoNome}?\n\nIl profilo va in .claude/agents/_archivio (non si cancella) ed esce dai «Comunica con» degli altri. Si ripristina dalla colonna di sinistra.`)) return;
  const d = await azione({ tipo: "agente", cosa: "togli", progetto: a.progetto, nome: a.nome }, ev.currentTarget);
  if (d) { $("scheda-agente").close(); caricaSpazi(); }
});

// ---- «Aggiorna agenti → Jarvis» (richiesta dell'utente, 26/09/2026): la mappa degli agenti la tiene
// Jarvis, non la pagina. La pagina gli manda quello che vede: spazi, progetti e agenti veri
// (da /api/catalogo), i fili della lavagna aperta e, dalla scheda, l'agente scelto.
function datiAgenti(k) {
  const nome = (n) => (n ? (n.tipo === "nota" ? "«" + (n.testo || "nota").slice(0, 30) + "»" : (n.agente || "").split(":").pop()) : "?");
  const a = k && AGENTI.get(k);
  return {
    spazi: (spaziCat || []).map((s) => ({ spazio: s.nome, progetti: s.progetti.map((p) => ({ progetto: p.nome, cartella: p.cartella,
      agenti: p.agenti.map((x) => (x.capogruppo ? "★" : "") + x.nome) })) })),
    lavagna: lavagnaTitolo || lavagnaAttiva,
    fili: lav().fili.map((f) => nome(nodoDi(f.da)) + " → " + nome(nodoDi(f.a))),
    agente: a ? { nome: a.nome, progetto: a.progettoNome, spazio: a.spazioNome, modello: a.modello, capogruppo: !!a.capogruppo,
      file: a.file, collegati: chiaviCollegate(k).map((x) => x.split(":").pop()) } : null,
  };
}
// ================================================ la lavagna come motore degli agenti (contratto, punto 13, 26/09/2026 18:10)
// Fonte di verità è il file di profilo di ogni agente; la lavagna è solo la disposizione. Col server
// vecchio (profili senza «attivo») tono, umorismo, attivo, crea, togli e allineamento restano spenti.
const UMORISMO = ["nessuno", "misurato", "vivace", "sfacciato"];
const SERIETA = ["leggero", "pacato", "professionale", "rigoroso"];   // serietà e umorismo insieme: due manopole indipendenti (l'utente, 29/09/2026)
// 2026-10-10: il server del prodotto crea sempre profili veri (anche con zero progetti e zero agenti)
const profiliNuovi = () => true;
function archiviatiDi(spazioId) {
  const s = (spaziCat || []).find((x) => x.id === spazioId);
  if (!s) return [];
  return s.progetti.flatMap((p) => (p.archiviati || []).map((x) => ({ nome: typeof x === "string" ? x : x.nome, progetto: p.id, progettoNome: p.nome })))
    .filter((x) => x.nome);
}
// la chiave «spazi» del flusso (un profilo è cambiato): si rilegge /api/spazi e si ridisegna, le posizioni restano
// P10 (audit 02/10/2026): una richiesta arrivata durante un'altra non si perde (spaziAncora), si rifà alla fine
let spaziInCorso = false, spaziAncora = false, GRUPPI_ARCH = [];
async function caricaSpazi() {
  if (spaziInCorso) { spaziAncora = true; return; }
  spaziInCorso = true;
  try {
    const d = await api("/api/spazi");
    if (d.memoria_radice) MEMORIA_RADICE = d.memoria_radice;
    if (d.assistente) ASSISTENTE = d.assistente;
    UTENTE = d.utente || "";
    PROG_ARCH = Array.isArray(d.progetti_archiviati) ? d.progetti_archiviati : [];
    SPAZI_LETTI = true; SPAZI_API_OK = true;
    applicaNomi();
    GRUPPI_ARCH = Array.isArray(d.gruppi_archiviati) ? d.gruppi_archiviati : [];
    disegnaSpazi(d.spazi || []);
    disegnaGruppiArchiviati(d.gruppi_archiviati);
    pulisciSchedeOrfane();
    seguiSquadre(d.squadre || {});
    disegnaLavagna();
    requestAnimationFrame(centraSeFuoriVista);
    const vuoto = $("lav-vuoto");
    if (vuoto) { vuoto.hidden = !nessunProgettoVero(); if (!vuoto.hidden) vuoto.replaceChildren(statoVuotoProgetti()); }
    posaNuovoAgente();
    posaNuovoGruppo();
    caricaModifiche();
    aggiornaAllineamento();
  } catch (e) { setTimeout(caricaSpazi, 1500); /* primo caricamento fallito: riprova da solo */ }
  finally { spaziInCorso = false; if (spaziAncora) { spaziAncora = false; caricaSpazi(); } }
}
// Un agente tolto (archiviato) o sparito dai profili esce da TUTTE le lavagne, e con lui i suoi fili
// (l'utente, 27/09/2026: «se cancello un agente la linea deve cancellarsi da sola»). Prima la scheda restava
// nei dati, nascosta, e i fili puntavano a una scheda invisibile. Prudenza: se il catalogo arriva
// monco (meno di 10 agenti, o sparirebbe più di metà di una lavagna) non si tocca niente.
// 02/10/2026 (audit menu, P4/D11): le schede dei progetti che stanno davvero in «Gruppi archiviati» si tolgono sempre,
// anche se sono tutta la lavagna: la soglia di prudenza vale solo per gli agenti spariti senza un motivo noto.
function pulisciSchedeOrfane() {
  if (!PAN || !PAN.lavagne || !(spaziCat || []).length) return;
  const archiviati = new Set((GRUPPI_ARCH || []).map((g) => g.progetto));
  let tolti = 0;
  for (const [id, L] of Object.entries(PAN.lavagne)) {
    if (eDemo(id) || !L || !L.nodi) continue;
    const agenti = L.nodi.filter((n) => n.tipo === "agente");
    const orfani = agenti.filter((n) => !AGENTI.has(n.agente));
    const sicuriIds = orfani.filter((n) => archiviati.has(String(n.agente).split(":")[0])).map((n) => n.id);
    // catalogo forse monco (meno di 10 agenti): si tolgono solo le schede dei gruppi archiviati
    const via = new Set(AGENTI.size < 10 ? sicuriIds : orfani.map((n) => n.id)), sicuri = sicuriIds.length;
    const ids = new Set(L.nodi.map((n) => n.id));
    const filiRotti = (L.fili || []).filter((f) => !ids.has(f.da) || !ids.has(f.a) || via.has(f.da) || via.has(f.a) || f.da === f.a);
    if (via.size - sicuri > Math.max(3, agenti.length / 2)) continue;
    if (!via.size && !filiRotti.length) continue;
    L.nodi = L.nodi.filter((n) => !via.has(n.id));
    L.fili = (L.fili || []).filter((f) => !filiRotti.includes(f));
    tolti += via.size + filiRotti.length;
  }
  if (tolti) { if (LAV.sel && !nodoDi(LAV.sel)) LAV.sel = null; LAV.selFilo = null; salvaPannello(); }
}
// ---- nuovo agente: modulo, poi la scheda nasce sulla lavagna sotto il suo capogruppo
let NASCITA = null;
function apriNuovoAgente(spazioId, progettoId, capoNome) {
  if (!profiliNuovi()) { toast("Creare agenti dal pannello arriva col server nuovo", true); return; }
  const sel = $("na-progetto");
  sel.replaceChildren(...(spaziCat || []).map((s) => el("optgroup", { label: s.nome },
    ...s.progetti.filter((p) => p.esiste).map((p) => el("option", { value: p.id }, p.nome)))));
  const sp = (spaziCat || []).find((s) => s.id === spazioId);
  if (sp && sp.progetti[0]) sel.value = sp.progetti[0].id;
  if (progettoId) sel.value = progettoId;
  riempiCapi();
  if (capoNome) $("na-capo").value = capoNome;
  $("na-nome").value = ""; $("na-descr").value = ""; $("na-tono").value = ""; $("na-umor").value = 1; $("na-umor-t").textContent = UMORISMO[1]; $("na-seri").value = 3; $("na-seri-t").textContent = SERIETA[3];
  $("na-nota").textContent = "";
  $("nuovo-agente").showModal();
}
function riempiCapi() {
  const p = $("na-progetto").value;
  const agenti = [...AGENTI.values()].filter((a) => a.progetto === p);
  $("na-capo").replaceChildren(el("option", { value: "" }, "nessuno"), ...agenti.map((a) => el("option", { value: a.nome }, nomeDi(a))));
  const capo = agenti.find((a) => a.capogruppo);
  $("na-capo").value = capo ? capo.nome : "";
}
$("na-progetto").addEventListener("change", riempiCapi);
$("na-umor").addEventListener("input", (ev) => { $("na-umor-t").textContent = UMORISMO[+ev.target.value]; });
$("na-seri").addEventListener("input", (ev) => { $("na-seri-t").textContent = SERIETA[+ev.target.value]; });
$("lav-nuovo-agente").addEventListener("click", () => apriNuovoAgente(null));
// ---- nuovo gruppo (punto 14): progetto, cartella, memoria e capogruppo; nasce una colonna nuova nella piramide
let NASCITA_GRUPPO = null, idToccato = false;
const inKebab = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
// 27/09/2026 (l'utente): la cartella si può scegliere fra quelle già in Progetti/<spazio>/, non solo
// nascerne sempre una nuova dal nome. L'elenco dipende dallo spazio scelto.
function notaCartellaGruppo() {
  const base = $("ng-base").value.trim(), modo = $("ng-cartella").value;
  $("ng-cartella-nota").textContent = !base ? "Nessuna cartella scelta: ne nasce una nuova col nome del progetto nella cartella dei progetti (~/Progetti, o quella scelta all'installazione)."
    : modo === "@base" ? "Il gruppo è proprio questa cartella: i suoi file restano dove sono."
    : "Nasce una cartella nuova, col nome del gruppo, dentro quella scelta.";
}
// 30/09/2026 (l'utente): «Nuovo gruppo» parte dalla cartella. Si sceglie o si crea con la finestra del Mac,
// la cartella compare subito sulla lavagna, e gli agenti si aggiungono dopo.
$("ng-sfoglia").addEventListener("click", async () => {
  $("ng-sfoglia").disabled = true; $("ng-cartella-nota").textContent = "Scegli o crea la cartella nella finestra che si apre…";
  try {
    if (!ponteConsente("GET /api/scegli-cartella")) { $("ng-cartella-nota").textContent = ""; toast(SOLO_MAC, true); return; }   // il ponte la blocca: finestra sullo schermo del Mac
    const d = await (await fetch("/api/scegli-cartella", { headers: HDR })).json();
    if (d.cartella) {
      $("ng-base").value = d.cartella; $("ng-cartella").value = "@base";
      if (!$("ng-nome").value.trim()) { $("ng-nome").value = d.cartella.split("/").pop(); $("ng-nome").dispatchEvent(new Event("input")); }
    }
    notaCartellaGruppo();
  } finally { $("ng-sfoglia").disabled = false; }
});
$("ng-base").addEventListener("input", notaCartellaGruppo);
$("ng-cartella").addEventListener("change", notaCartellaGruppo);
$("ng-crea-capo").addEventListener("change", () => { $("ng-capo-campi").hidden = !$("ng-crea-capo").checked; });
function apriNuovoGruppo() {
  if (!profiliNuovi()) { toast("Creare gruppi dal pannello arriva col server nuovo", true); return; }
  $("ng-spazio").replaceChildren(el("option", { value: "" }, "Nuovo spazio, col nome del progetto"),
    ...(spaziCat || []).filter((s) => !s.sistema).map((s) => el("option", { value: s.id }, "dentro " + s.nome)));
  for (const id of ["ng-nome", "ng-id", "ng-capo", "ng-descr", "ng-tono", "ng-base"]) $(id).value = "";
  $("ng-umor").value = 1; $("ng-umor-t").textContent = UMORISMO[1]; $("ng-seri").value = 3; $("ng-seri-t").textContent = SERIETA[3];
  $("ng-nota").textContent = ""; idToccato = false; $("ng-crea-capo").checked = true; $("ng-capo-campi").hidden = false; $("ng-squadra").checked = true;
  $("ng-cartella").value = "@base"; notaCartellaGruppo();
  $("nuovo-gruppo").showModal();
}
$("lav-nuovo-progetto").addEventListener("click", apriNuovoGruppo);
$("btn-nuovo-gruppo").addEventListener("click", apriNuovoGruppo);
$("ng-nome").addEventListener("input", () => { if (!idToccato) $("ng-id").value = inKebab($("ng-nome").value); $("ng-capo").placeholder = ($("ng-id").value || "…") + "-ceo"; });
$("ng-id").addEventListener("input", () => { idToccato = true; $("ng-capo").placeholder = ($("ng-id").value || "…") + "-ceo"; });
$("ng-umor").addEventListener("input", (ev) => { $("ng-umor-t").textContent = UMORISMO[+ev.target.value]; });
$("ng-seri").addEventListener("input", (ev) => { $("ng-seri-t").textContent = SERIETA[+ev.target.value]; });
$("form-nuovo-gruppo").addEventListener("submit", async (ev) => {
  if (!ev.submitter || ev.submitter.value !== "crea") return;
  ev.preventDefault();
  const nome = $("ng-nome").value.trim(), id = (inKebab(nome) || $("ng-id").value.trim()), creaCapo = $("ng-crea-capo").checked;
  const idGruppo = creaCapo && $("ng-id").value.trim() ? $("ng-id").value.trim() : id;
  const capo = $("ng-capo").value.trim() || idGruppo + "-ceo";
  if (!nome || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(idGruppo)) { $("ng-nota").textContent = "Dai un nome al gruppo (lettere e numeri)"; return; }
  if (creaCapo && !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(capo)) { $("ng-nota").textContent = "Capogruppo in minuscolo, con i trattini: <progetto>-ceo"; return; }
  if ((spaziCat || []).some((s) => s.id === idGruppo && !$("ng-spazio").value || s.progetti.some((p) => p.id === idGruppo))) { $("ng-nota").textContent = "Questo nome è già di un altro gruppo, scegline un altro"; return; }
  const base = $("ng-base").value.trim();
  const d = await azione({ tipo: "agente", cosa: "crea_gruppo", spazio: $("ng-spazio").value, nome, id: idGruppo, capogruppo: capo, crea_capogruppo: creaCapo, squadra_ceo: creaCapo && $("ng-squadra").checked,
    cartella_esistente: base ? $("ng-cartella").value : "", cartella_base: base,
    description: $("ng-descr").value.trim(), model: $("ng-modello").value, tono: $("ng-tono").value.trim(), umorismo: +$("ng-umor").value, serieta: +$("ng-seri").value }, ev.submitter);
  if (!d) return;
  NASCITA_GRUPPO = { id: idGruppo, capo: creaCapo ? `${idGruppo}:${capo}` : null, nome };
  $("nuovo-gruppo").close();
  caricaSpazi();
});
function posaNuovoGruppo() {
  const g = NASCITA_GRUPPO;
  if (!g || !(spaziCat || []).some((s) => s.progetti.some((p) => p.id === g.id))) return;
  NASCITA_GRUPPO = null;
  // in colonna: il gruppo del suo spazio si apre e la riga del progetto nasce
  const spazio = (spaziCat || []).find((s) => s.progetti.some((p) => p.id === g.id));
  const gr = document.querySelector(`.gruppo[data-gruppo="spazio-${CSS.escape(spazio.id)}"]`);
  if (gr && gr.classList.contains("chiuso")) gr.querySelector(".gruppo-testa").click();
  if (!eDemo(lavagnaAttiva) && lavagnaAttiva === "generale") popolaCatenaCompleta().then(() => {});
  animaNascita(g.capo ? [g.capo] : [], [g.nome, "📁 " + g.nome + " · nessun agente ancora"]);
  setTimeout(() => { const sp = document.querySelector(`.sotto-progetto[data-progetto="${CSS.escape(g.id)}"]`); if (sp) { sp.classList.add("nasce-riga"); setTimeout(() => sp.classList.remove("nasce-riga"), 1600); } }, 200);
  toast(g.capo ? `Gruppo ${g.nome} nato: cartella, memoria e capogruppo pronti` : `Gruppo ${g.nome} nato: la cartella è sulla lavagna, ora aggiungi gli agenti con «＋ Nuovo agente»`);
}
$("form-nuovo-agente").addEventListener("submit", async (ev) => {
  if (!ev.submitter || ev.submitter.value !== "crea") return;
  ev.preventDefault();
  const nome = $("na-nome").value.trim().toLowerCase();
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(nome)) { $("na-nota").textContent = "Il nome va scritto in minuscolo, con i trattini: analista-vendite"; return; }
  const progetto = $("na-progetto").value, capogruppo = $("na-capo").value;
  const d = await azione({ tipo: "agente", cosa: "crea", progetto, nome, description: $("na-descr").value.trim(), model: $("na-modello").value,
    tools: "", tono: $("na-tono").value.trim(), umorismo: +$("na-umor").value, serieta: +$("na-seri").value, capogruppo }, ev.submitter);
  if (!d) return;
  NASCITA = { key: `${progetto}:${nome}`, capo: capogruppo ? `${progetto}:${capogruppo}` : null };
  $("nuovo-agente").close();
  caricaSpazi();
});
function animaNascita(chiavi, note) {
  setTimeout(() => {
    for (const k of chiavi) for (const d of document.querySelectorAll(`[data-agente="${CSS.escape(k)}"]`)) { d.classList.add("nasce"); setTimeout(() => d.classList.remove("nasce"), 1400); }
    for (const t of note || []) for (const d of document.querySelectorAll("#lav-mondo .nodo.nota")) if (d.textContent.trim() === t) { d.classList.add("nasce"); setTimeout(() => d.classList.remove("nasce"), 1400); }
  }, 150);
}
// La squadra che il CEO compone dalla cartella (2/10/2026): ogni agente creato dal CEO compare sulla lavagna da solo.
// Solo quelli creati da lui: una scheda tolta a mano dall'utente non rientra mai (le tombe stanno nel server).
const SQUADRE_VISTE = new Set(), SQUADRE_STATO_VISTO = {};
let SQUADRE_PRIMO_GIRO = true;
function seguiSquadre(squadre) {
  let nuovi = false;
  const primo = SQUADRE_PRIMO_GIRO; SQUADRE_PRIMO_GIRO = false;   // audit 02/10/2026: al primo giro si prende nota e basta
  for (const [pid, s] of Object.entries(squadre)) {
    for (const nome of s.creati || []) {
      const k = `${pid}:${nome}`;
      if (!SQUADRE_VISTE.has(k) && AGENTI.has(k)) { SQUADRE_VISTE.add(k); if (!primo) nuovi = true; }
    }
    if (s.stato !== SQUADRE_STATO_VISTO[pid]) {
      if (SQUADRE_STATO_VISTO[pid] === "in corso" || SQUADRE_STATO_VISTO[pid] === undefined && s.stato !== "in corso") {
        if (s.stato === "fatta") toast(s.messaggio); else if (s.stato === "errore") toast("Squadra non creata: " + s.messaggio, true);
      }
      SQUADRE_STATO_VISTO[pid] = s.stato;
    }
  }
  if (!nuovi || eDemo(lavagnaAttiva)) return;
  // solo le schede nuove, sotto il loro CEO: le altre (anche quelle tolte a mano con «Solo la scheda») non si toccano
  const L = lav();
  for (const k of SQUADRE_VISTE) {
    const a = AGENTI.get(k);
    if (!a || L.nodi.some((z) => z.agente === k)) continue;
    const capo = L.nodi.find((z) => z.agente === `${a.progetto}:${a.riporta_a}`) || L.nodi.find((z) => (AGENTI.get(z.agente) || {}).capogruppo && (AGENTI.get(z.agente) || {}).progetto === a.progetto);
    const x = capo ? capo.x : 40, sotto = capo ? L.nodi.filter((z) => Math.abs(z.x - x) < 10 && z.y > capo.y) : [];
    const y = capo ? Math.max(capo.y + 100, ...sotto.map((z) => z.y + 70)) : 40;
    const n = { id: "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), tipo: "agente", agente: k, x, y };
    L.nodi.push(n);
    if (capo) L.fili.push({ da: capo.id, a: n.id });
  }
  salvaPannello(); disegnaLavagna();
}
function posaNuovoAgente() {
  if (!NASCITA || !AGENTI.has(NASCITA.key) || eDemo(lavagnaAttiva)) return;
  if (lavagnaAttiva === "generale") {                       // la catena intera: la piramide si ridisegna coi livelli giusti
    const k = NASCITA.key; NASCITA = null;
    popolaCatenaCompleta().then(() => {}); animaNascita([k]);
    toast(`${nomeDi(AGENTI.get(k))} è nato: profilo scritto e collegato a chi riporta`);
    return;
  }
  const L = lav();
  let n = L.nodi.find((z) => z.agente === NASCITA.key);
  if (!n) {
    const capo = NASCITA.capo && L.nodi.find((z) => z.agente === NASCITA.capo);
    // sotto il capogruppo, dopo l'ultima scheda della sua colonna
    // sotto un capogruppo: in fondo alla sua colonna; sotto uno specialista: rientrato, subito sotto di lui
    const padreSpecialista = capo && !(AGENTI.get(capo.agente) || {}).capogruppo;
    const x = capo ? capo.x + (padreSpecialista ? 16 : 0) : 40, sotto = capo ? L.nodi.filter((z) => Math.abs(z.x - x) < 10 && z.y > capo.y) : [];
    const y = capo ? Math.max(capo.y + (padreSpecialista ? 70 : 100), ...sotto.map((z) => z.y + 70)) : 40;
    n = { id: "n" + Date.now().toString(36), tipo: "agente", agente: NASCITA.key, x, y };
    L.nodi.push(n);
    if (capo) L.fili.push({ da: capo.id, a: n.id });
    salvaPannello();
    disegnaLavagna();
  }
  const d = document.querySelector(`#lav-mondo .nodo[data-id="${CSS.escape(n.id)}"]`);
  if (d) { d.classList.add("nasce"); setTimeout(() => d.classList.remove("nasce"), 1200); }
  toast(`${nomeDi(AGENTI.get(NASCITA.key))} è nato: profilo scritto e collegato al capogruppo`);
  NASCITA = null;
}
// ---- guida e controllo della lavagna (l'utente, 02/10/2026): «una guida dentro ogni operazione, così capiamo se sbaglio io o sbagliate voi»
const GUIDA_LAVAGNA = [
  { op: "＋ Nuovo gruppo", fa: "Scegli la cartella del progetto: nasce il progetto con il suo capogruppo (<progetto>-ceo), sempre (stessa logica di crea_progetto.py).",
    scrive: "spazi.json · scheda del capogruppo in <cartella>/.claude/agents · <memoria>/<spazio>/Stato.md · File/ e Indice-file.md",
    atteso: "La cartella e il capogruppo compaiono subito. Gli specialisti li crea il capogruppo, uno alla volta, quando servono.",
    verifica: "«Controlla lavagna» non dice niente sul gruppo; il CEO ha sotto 2-8 agenti; poi Jarvis allinea memoria e agenti (Stato e Guida del progetto).",
    sbaglia: "Se il CEO resta solo: il lancio del CEO è fallito (guarda gli eventi). Se la cartella non compare: è un errore della lavagna." },
  { op: "Il CEO compone la squadra", fa: "Rilancia la lettura della cartella da parte del CEO per un gruppo che ha il CEO ma pochi agenti (Scheda gruppo → «Il CEO compone la squadra»).",
    scrive: "Nuovi profili in <cartella>/.claude/agents, mai quelli che hai tolto (tombe in agenti-tolti.json).",
    atteso: "Compaiono solo agenti nuovi. Opus solo per chi programma.", verifica: "«Controlla lavagna»: il CEO non è più «solo».",
    sbaglia: "Se rimette un agente che avevi eliminato: è un bug nostro (le tombe). Segnalalo." },
  { op: "＋ Nuovo agente", fa: "Crea un profilo sotto il capogruppo che scegli.", scrive: "<cartella>/.claude/agents/<nome>.md e il «comunica con» del capogruppo",
    atteso: "La scheda compare sotto il capogruppo, collegata.", verifica: "Il profilo esiste nel Finder (📄 sulla scheda) e il capogruppo lo nomina.",
    sbaglia: "Se non compare ma il file c'è: aggiorna la pagina (lavagna). Se il file non c'è: errore del server." },
  { op: "Togli → Sospendi", fa: "L'agente resta in grigio e le missioni non lo lanciano.", scrive: "attivo: false nel suo profilo",
    atteso: "Scheda grigia, nessun lancio.", verifica: "«Riattiva» lo rimette a lavorare.", sbaglia: "Se una missione lo lancia lo stesso: errore del Command Center." },
  { op: "Togli → Elimina", fa: "Il profilo esce da spazi, lavagna e «comunica con» degli altri. Non torna più.", scrive: "Cancella il profilo (copia in _archivio salvo «definitivo») e scrive la tomba",
    atteso: "La scheda sparisce e non rientra con «Tutta la catena», «Allinea» o dal CEO.", verifica: "«Controlla lavagna»: nessun errore «agente tolto ma presente».",
    sbaglia: "Se rientra: qualcuno ha ricreato il file (una missione o un agente). «Controlla lavagna» lo dice." },
  { op: "Elimina gruppo (lavagna, Canc) / ✕ dal menu", fa: "Il gruppo esce da spazi, menu e lavagna, gli agenti vanno in un archivio dentro la cartella. La cartella e i suoi file non si toccano. Dal menu: ✕ sulla testa di un gruppo-spazio, oppure Scheda gruppo → «Togli» accanto a un progetto (vale anche per un progetto senza capogruppo). Stesso dialogo della lavagna.",
    scrive: "spazi.json (via la voce; via lo spazio se era l'ultimo progetto), gruppi-archiviati.json, _archivio-… nella cartella, pannello.json (il server toglie schede, note-cartella, gruppo-spazio e la sua lavagna)",
    atteso: "Il gruppo sparisce dal menu e da tutte le lavagne, anche nelle altre schede aperte; compare in «Gruppi archiviati».", verifica: "La cartella del progetto è intatta; «Controlla lavagna» non segnala gruppi fantasma né lavagne orfane.",
    sbaglia: "Se i file del progetto spariscono: errore grave nostro. Se il gruppo resta nel menu come 👻: è un dato vecchio, «Togli» sulla riga 👻 lo toglie." },
  { op: "Gruppi archiviati → Ripristina", fa: "Rimette progetto, voce in spazi.json e agenti com'erano. Se lo spazio era uscito, lo ricrea (anche per un gruppo che non è uscito per ultimo).",
    scrive: "spazi.json, gruppi-archiviati.json, _archivio-…/agents → .claude/agents", atteso: "Il gruppo torna nel menu con i suoi agenti.",
    verifica: "Il gruppo è di nuovo nel menu; «Controlla lavagna» senza errori sul gruppo.",
    sbaglia: "«L'archivio degli agenti non c'è più»: qualcuno ha spostato la cartella _archivio-…; non si ripristina, si elimina (⚠ accanto al nome). Niente viene toccato prima del messaggio." },
  { op: "Gruppi archiviati → Elimina definitivamente", fa: "Cancella il gruppo archiviato: prima mostra cosa sparisce e cosa resta, poi chiede di scrivere il nome del gruppo.",
    scrive: "Toglie la voce da gruppi-archiviati.json e le tombe del progetto; la cartella _archivio-… va nel Cestino del Mac (mai cancellata col comando); pulisce le schede rimaste sulle lavagne",
    atteso: "La voce sparisce da «Gruppi archiviati»; nel Cestino c'è «<cartella> _archivio-…».", verifica: "La cartella del progetto e la memoria nel vault sono intatte; la cartella d'archivio si recupera dal Cestino finché non lo svuoti.",
    sbaglia: "Nome scritto diverso: non si cancella niente (è voluto). «Non è dove lo mette Togli gruppo»: il percorso dell'archivio è strano e il server si rifiuta, per prudenza." },
  { op: "Agente archiviato → Ripristina (menu)", fa: "Gli agenti tolti con «Elimina» (copia in _archivio) compaiono in grigio nel loro gruppo con «Ripristina».",
    scrive: ".claude/agents/_archivio/<nome>.md → .claude/agents/<nome>.md; toglie la tomba; se era il capogruppo torna capogruppo in spazi.json",
    atteso: "La riga grigia diventa un agente normale.", verifica: "Il profilo è di nuovo in .claude/agents.", sbaglia: "Se la riga grigia non compare: aggiorna la pagina; se ancora no, errore del server." },
  { op: "Elimina il capogruppo", fa: "Come per ogni agente; in più il gruppo resta senza capogruppo.", scrive: "spazi.json: «capogruppo» esce dalla voce (ricordato in «capogruppo_tolto»)",
    atteso: "«Controlla lavagna» dice «il gruppo non ha un CEO» (avviso), non più un errore.", verifica: "Crea un nuovo CEO con «＋ Nuovo agente», o ripristina quello vecchio.", sbaglia: "Se resta l'errore «il CEO non ha il profilo»: bug nostro." },
  { op: "Pannello Attività (scheda agente)", fa: "Mostra come lavora l'agente: richieste ricevute e inviate, stato (al lavoro, in attesa, fermo, errore), in tempo reale. «filo» accende sulla lavagna il collegamento di quella richiesta.",
    scrive: "Niente: legge il registro delle attività (command-center/attivita/*.jsonl, 14 giorni) da /api/agente-attivita.", atteso: "Le righe nuove arrivano da sole mentre la scheda è aperta.",
    verifica: "«solo errori e avvisi» filtra; il sommario sulla lavagna segna chi è senza risposta.", sbaglia: "Se è vuoto ma l'agente ha lavorato: il registro non è stato scritto (missione o hook), non è la lavagna." },
  { op: "Tirare un filo fra due schede", fa: "Collega due agenti: il nome entra nel «Comunica con» di tutti e due.", scrive: "sezione «Comunica con» dei due profili",
    atteso: "Il filo resta dopo la ricarica della pagina.", verifica: "Pulsante «Profili: …» deve dire «allineati».", sbaglia: "Se il filo c'è e il profilo no (o viceversa): «Allinea» lo sistema; se torna a rompersi è un bug nostro." },
  { op: "Profili: allinea", fa: "Confronta i fili della lavagna con i «Comunica con» dei profili.", scrive: "Solo fili o solo profili, a tua scelta.",
    atteso: "«allineati».", verifica: "Il badge diventa verde.", sbaglia: "Non crea e non toglie agenti: se vedi agenti rientrare non è questo." },
  { op: "Tutta la catena", fa: "Ridisegna la piramide: l'utente → Jarvis → cartella → CEO → squadra.", scrive: "Solo la disposizione (pannello.json).", atteso: "Tutti gli agenti che esistono come profilo.",
    verifica: "Nessun profilo nuovo.", sbaglia: "Mostra anche le schede tolte con «Solo la scheda» (non sono agenti eliminati)." },
  { op: "Aggiorna tutti / ultime modifiche", fa: "Missione: ogni CEO rilegge i profili della sua squadra e li rende coerenti con memoria, «comunica con», tono.", scrive: "Report della missione e correzioni ai profili",
    atteso: "Resoconto in «Missioni».", verifica: "Il badge «ultime modifiche» torna a 0.", sbaglia: "Se un agente tolto rientra: bug nostro, segnalalo." },
  { op: "Controlla lavagna", fa: "Controlla progetti, CEO, agenti, tombe, Stato, schede orfane, gruppi fantasma (👻) e lavagne orfane in pannello.json, gruppi archiviati con l'archivio sparito o senza spazio.", scrive: "Niente: sola lettura.", atteso: "Elenco di problemi con «di chi è».", verifica: "Premi di nuovo dopo aver corretto.", sbaglia: "—" },
];
function apriGuida() {
  $("gl-titolo").textContent = "Guida della lavagna";
  $("gl-corpo").replaceChildren(...GUIDA_LAVAGNA.map((g) => el("details", { class: "gl-op" },
    el("summary", {}, el("b", {}, g.op), " — ", g.fa),
    el("dl", {}, el("dt", {}, "Cosa scrive"), el("dd", {}, g.scrive), el("dt", {}, "Risultato atteso"), el("dd", {}, g.atteso),
      el("dt", {}, "Come lo verifichi"), el("dd", {}, g.verifica), el("dt", {}, "Se non va, di chi è il problema"), el("dd", {}, g.sbaglia)))));
  $("guida-lavagna").showModal();
}
async function controllaLavagna() {
  $("gl-titolo").textContent = "Controllo della lavagna";
  $("gl-corpo").replaceChildren(el("p", {}, "Controllo in corso…"));
  if (!$("guida-lavagna").open) $("guida-lavagna").showModal();
  try {
    const r = await api("/api/lavagna/verifica");
    const c = r.controllati || {};
    const righe = (r.problemi || []).map((x) => el("li", { class: x.livello === "errore" ? "gl-errore" : "gl-avviso" },
      el("b", {}, (x.livello === "errore" ? "🔴 " : "🟡 ") + x.dove), " — ", x.cosa, el("br", {}),
      el("small", {}, "Di chi è: ", x.di_chi, " · Cosa fare: ", x.rimedio)));
    $("gl-sotto").textContent = `${r.quando} · ${c.progetti || 0} progetti, ${c.agenti || 0} agenti · ` + (r.in_ordine ? "nessun errore" : "ci sono errori");
    $("gl-corpo").replaceChildren(righe.length ? el("ul", { class: "chiavi-note" }, ...righe) : el("p", {}, "🟢 Tutto torna: progetti, CEO, agenti, tombe, Stato e schede."));
  } catch (e) { $("gl-corpo").replaceChildren(el("p", {}, "Controllo non riuscito: " + e.message)); }
}
$("lav-guida").addEventListener("click", apriGuida);
$("lav-verifica").addEventListener("click", controllaLavagna);
$("gl-controlla").addEventListener("click", controllaLavagna);
// ---- allineamento fra i fili della lavagna e i «Comunica con» dei profili
const ALLINEA = { differenze: [], assente: false, timer: null };
function aggiornaAllineamento() {
  clearTimeout(ALLINEA.timer);
  ALLINEA.timer = setTimeout(async () => {
    const b = $("lav-allineamento");
    if (eDemo(lavagnaAttiva)) { b.textContent = "Profili: dimostrazione"; b.disabled = true; b.className = "piccolo"; return; }
    try {
      const r = await fetch("/api/agenti/allineamento?lavagna=" + encodeURIComponent(lavagnaAttiva), { headers: HDR });
      if (r.status === 404) { ALLINEA.assente = true; b.textContent = "Profili: arriva col server nuovo"; b.disabled = true; b.className = "piccolo"; return; }
      if (!r.ok) return;
      const d = await r.json();
      ALLINEA.differenze = d.differenze || [];
      const n = ALLINEA.differenze.length;
      b.disabled = false;
      b.textContent = n ? `Profili: ${n} differenze` : "Profili: allineati";
      b.className = "piccolo " + (n ? "allinea-no" : "allinea-ok");
    } catch (e) { /* riprova al prossimo cambio */ }
  }, 400);
}
$("lav-allineamento").addEventListener("click", () => {
  const nomi = { "filo-senza-profilo": "sulla lavagna, non nei profili", "profilo-senza-filo": "nei profili, non sulla lavagna" };
  $("al-lista").replaceChildren(...(ALLINEA.differenze.length ? ALLINEA.differenze.map((x) => el("li", {},
    el("b", { class: "cn-tipo" }, x.tipo === "filo-senza-profilo" ? "LAVAGNA" : "PROFILO"),
    el("span", {}, `${nomeChiave(x.da)} → ${nomeChiave(x.a)} · ${nomi[x.tipo] || x.tipo}`))) : [el("li", { class: "vuoto" }, "nessuna differenza")]));
  $("allineamento").showModal();
});
for (const [id, verso] of [["al-profili", "profili"], ["al-lavagna", "lavagna"]]) $(id).addEventListener("click", async (ev) => {
  const d = await azione({ tipo: "agente", cosa: "allinea", lavagna: lavagnaAttiva, verso }, ev.currentTarget);
  if (!d) return;
  $("allineamento").close();
  if (verso === "lavagna") await caricaPannello(); else caricaSpazi();
  aggiornaAllineamento();
});
// ---- «Aggiorna ultime modifiche» (contratto, punto 15, 26/09/2026 19:10): le modifiche fatte da lavagna e
// scheda dopo l'ultimo aggiornamento aspettano una verifica; la missione lavora solo sugli agenti coinvolti.
const MODIFICHE = { pendenti: [], coinvolti: [], assente: false, inCorso: false };
async function caricaModifiche() {
  if (MODIFICHE.inCorso || MODIFICHE.assente) return;
  MODIFICHE.inCorso = true;
  try {
    const r = await fetch("/api/agenti/modifiche", { headers: HDR });
    if (r.status === 404) { MODIFICHE.assente = true; disegnaModifiche(); return; }
    if (!r.ok) return;
    const d = await r.json();
    MODIFICHE.pendenti = d.pendenti || [];
    MODIFICHE.coinvolti = d.agenti_coinvolti || [];
    disegnaModifiche();
  } catch (e) { /* riprova al prossimo avviso del flusso */ }
  finally { MODIFICHE.inCorso = false; }
}
function disegnaModifiche() {
  const n = MODIFICHE.pendenti.length, b = $("lav-aggiorna-ultime");
  $("lav-n-mod").textContent = n;
  b.disabled = MODIFICHE.assente || !n || !!CATENA_GIRO;
  b.title = MODIFICHE.assente ? "Arriva col server nuovo" : n ? `Una missione sui ${MODIFICHE.coinvolti.length} agenti toccati da ${n} modifiche` : "Nessuna modifica da verificare";
  const badge = $("lav-mod-badge");
  badge.classList.toggle("nascosto", MODIFICHE.assente || !n || eDemo(lavagnaAttiva));
  badge.textContent = `${n} ${n === 1 ? "modifica non ancora aggiornata" : "modifiche non ancora aggiornate"}`;
  $("mod-nota").textContent = MODIFICHE.assente ? "arriva col server nuovo" : n ? "" : "nessuna";
  $("mod-lista").replaceChildren(...MODIFICHE.pendenti.slice().reverse().map((m) => el("li", {},
    el("time", {}, oraDi(m.ts)),
    el("b", {}, `${m.tipo || "?"} · ${nomeChiave(m.progetto && m.agente ? m.progetto + ":" + m.agente : m.agente || m.progetto)}`),
    el("span", {}, (m.con || []).length ? "con " + m.con.map((x) => nomeChiave(String(x).includes(":") || !m.progetto ? x : m.progetto + ":" + x)).join(", ") : ""),
    el("small", {}, m.da || ""))));
}
$("lav-aggiorna-ultime").addEventListener("click", async (ev) => {
  const prima = new Map([...AGENTI.values()].map((a) => [a.key, a.aggiornato_ts]));
  const coinvolti = MODIFICHE.coinvolti.map((k) => (agenteDaChiave(k) || {}).key).filter(Boolean);
  const d = await azione({ tipo: "agente", cosa: "aggiorna_catena", ambito: "ultime", spazio: "tutti" }, ev.currentTarget);
  if (!d) return;
  CATENA_GIRO = { missione: d.missione || (d.lavoro && d.lavoro.id) || null, da: Date.now() / 1000, prima, quanti: coinvolti.length || MODIFICHE.coinvolti.length, coinvolti };
  contaCatenaGiro(); disegnaModifiche();
  if (ultimoStato) aggiornaAttivita(ultimoStato);           // le schede coinvolte si accendono subito
});

// ---- aggiorna catena: la missione dei capigruppo; contatore e, alla fine, le schede cambiate lampeggiano
let CATENA_GIRO = null;
function contaCatenaGiro() {
  const n = $("lav-catena-conta");
  if (!CATENA_GIRO) { n.textContent = ""; return; }
  // verificato = un agente che ha già risposto nella missione (comunicazioni «risposta» finite)
  const visti = new Set();
  for (const c of SINAPSI.lista) if ((c.ts || 0) >= CATENA_GIRO.da && c.stato === "finito") { const a = agenteDaChiave(c.da); if (a) visti.add(a.key); }
  n.textContent = `${visti.size} agenti verificati / ${CATENA_GIRO.quanti}`;
}
function seguiCatenaGiro(s) {
  if (!CATENA_GIRO) return;
  contaCatenaGiro();
  const m = CATENA_GIRO.missione && (s.missioni || []).find((x) => x.id === CATENA_GIRO.missione);
  const finita = m ? ["chiusa", "interrotta", "errore"].includes(m.stato) : Date.now() / 1000 - CATENA_GIRO.da > 1800;
  if (!finita) return;
  const giro = CATENA_GIRO;
  CATENA_GIRO = null;
  api("/api/spazi").then((d) => {
    disegnaSpazi(d.spazi || []);
    disegnaLavagna();
    const cambiati = [...AGENTI.values()].filter((a) => a.aggiornato_ts && a.aggiornato_ts !== giro.prima.get(a.key));
    for (const a of cambiati) for (const x of document.querySelectorAll(`[data-agente="${CSS.escape(a.key)}"]`)) {
      x.classList.add("lampeggia"); setTimeout(() => x.classList.remove("lampeggia"), 1600);
    }
    // il riepilogo è la risalita jarvis → utente della missione, se c'è
    const riepilogo = SINAPSI.lista.find((c) => (c.ts || 0) >= giro.da && String(c.da).toLowerCase() === "jarvis" && String(c.a).toLowerCase() === "utente");
    toast(riepilogo ? riepilogo.testo : `Aggiornamento della catena finito: ${cambiati.length} profili cambiati`);
    caricaModifiche();
    if (ultimoStato) aggiornaAttivita(ultimoStato);
    $("lav-catena-conta").textContent = `finito · ${cambiati.length} profili cambiati`;
    if ($("scheda-agente").open && schedaKey) apriScheda(schedaKey);
  }).catch(() => {});
}

// ---- dimostrazione: la squadra finta, fatta solo di note (nessun profilo vero si tocca) ----
const DEMO = { id: "demo-squadra", titolo: "Squadra dimostrativa",
  colori: { jarvis: "#599ce7", claude: "#9386f2", codex: "#9386f2", gemini: "#9386f2", cursor: "#9386f2", sceglie: "#9386f2",
    capogruppo: "#3fa266", analista: "#3fa266", ricercatore: "#3fa266", programmatore: "#3fa266", revisore: "#3fa266",
    verificatore: "#3fa266", redattore: "#3fa266", report: "#e5b454" } };
const DEMO_SQUADRA = ["analista", "ricercatore", "programmatore", "revisore", "verificatore"];
function disegnaModoDemo() {
  document.body.classList.toggle("lav-demo", lavDemo);
  $("lav-demo").setAttribute("aria-pressed", String(lavDemo));
  $("lav-demo").classList.toggle("attivo", lavDemo);
}
$("lav-demo").addEventListener("click", async () => {
  lavDemo = !lavDemo;
  mem.scrivi("lavDemo", lavDemo);
  disegnaModoDemo();
  // uscendo si butta quello che la dimostrazione ha cambiato solo in pagina
  if (!lavDemo) { if (eDemo(lavagnaAttiva)) vaiALavagna("generale", ""); await caricaPannello(); }
  toast(lavDemo ? "Dimostrazione: la lavagna non manda niente fuori dalla pagina" : "Dimostrazione spenta: lavagna di nuovo vera");
});
function costruisciSquadraDemo() {
  vaiALavagna(DEMO.id, DEMO.titolo);
  const L = lav();
  L.nodi = []; L.fili = [];
  const LARG = 212, centro = 5 * LARG / 2;          // la riga più larga ha 5 schede
  const nota = (id, testo, x, y) => L.nodi.push({ id: "demo-" + id, tipo: "nota", testo, x: Math.round(x), y: Math.round(y) });
  const filo = (a, b) => L.fili.push({ da: "demo-" + a, a: "demo-" + b });
  const riga = (ids, y) => ids.forEach(([id, t], i) => nota(id, t, centro - ids.length * LARG / 2 + i * LARG + 10, y));
  nota("umano", "Umano (l'utente)", centro - 96, 0);
  nota("jarvis", "Jarvis · harness", centro - 140, 110);
  nota("sceglie", "sceglie il migliore per il compito", centro + 170, 122);
  riga([["claude", "Claude Code"], ["codex", "Codex"], ["gemini", "Gemini"], ["cursor", "Cursor"]], 250);
  nota("capogruppo", "capogruppo", centro - 96, 390);
  riga(DEMO_SQUADRA.map((x) => [x, x]), 530);
  nota("redattore", "redattore del report", centro - 96, 670);
  nota("report", "Report finale → Jarvis → Umano", centro - 96, 800);
  filo("umano", "jarvis");
  for (const m of ["claude", "codex", "gemini", "cursor"]) filo("jarvis", m);
  filo("claude", "capogruppo");
  for (const x of DEMO_SQUADRA) filo("capogruppo", x);
  filo("capogruppo", "redattore");
  filo("verificatore", "revisore");
  for (const x of DEMO_SQUADRA) filo(x, "redattore");
  filo("redattore", "report");
  filo("report", "jarvis");
  filo("jarvis", "umano");
  LAV.sel = null; LAV.selFilo = null;
  salvaPannello();
  location.hash = "#lavagna";
  requestAnimationFrame(() => { disegnaLavagna(); centraLavagna(); });
}
$("lav-demo-squadra").addEventListener("click", costruisciSquadraDemo);
// «Fai partire la dimostrazione»: si accendono in fila, ogni 900 ms, chi lavora e i fili che portano
// a lui; alla fine la risposta risale fino all'Umano e si spegne tutto. Serve a registrare la GIF.
let demoInCorso = false;
async function faiPartireDemo() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { toast("Animazione spenta: il sistema chiede meno movimento", true); return; }
  if (demoInCorso) return;
  if (lavagnaAttiva !== DEMO.id || !lav().nodi.some((n) => n.id === "demo-umano")) { costruisciSquadraDemo(); await new Promise((r) => setTimeout(r, 400)); }
  demoInCorso = true;
  $("lav-demo-via").disabled = true;
  const accesi = new Set();
  const pausa = () => new Promise((r) => setTimeout(r, 900));
  const accendi = (ids) => {
    for (const id of ids) {
      const nodo = document.querySelector(`.nodo[data-id="demo-${id}"]`);
      if (nodo) nodo.classList.add("al-lavoro");
      for (const p of document.querySelectorAll(`#lav-fili path.filo[data-a="demo-${id}"]`))
        if (accesi.has(p.dataset.da.slice(5))) p.classList.add("acceso");
    }
    ids.forEach((id) => accesi.add(id));
  };
  try {
    for (const passo of [["umano"], ["jarvis"], ["claude"], ["capogruppo"], ...DEMO_SQUADRA.map((x) => [x]),
      ["redattore"], ["report"], ["jarvis"], ["umano"]]) { accendi(passo); await pausa(); }
    await pausa();
  } finally {
    document.querySelectorAll(".nodo.al-lavoro").forEach((n) => n.classList.remove("al-lavoro"));
    document.querySelectorAll("#lav-fili path.acceso").forEach((p) => p.classList.remove("acceso"));
    demoInCorso = false;
    $("lav-demo-via").disabled = false;
  }
}
$("lav-demo-via").addEventListener("click", faiPartireDemo);
disegnaModoDemo();

$("lav-aggiorna-agenti").addEventListener("click", async (ev) => {
  // server nuovo: una missione vera (punto 13), con le sinapsi orchestratore → capogruppo → specialisti
  const spazio = $("lav-spazio-catena").value;
  if (profiliNuovi()) {
    const prima = new Map([...AGENTI.values()].map((a) => [a.key, a.aggiornato_ts]));
    const d = await azione({ tipo: "agente", cosa: "aggiorna_catena", ambito: "tutti", spazio }, ev.currentTarget);
    if (d) {
      const quanti = [...AGENTI.values()].filter((a) => spazio === "tutti" || a.spazio === spazio).length;
      CATENA_GIRO = { missione: d.missione || (d.lavoro && d.lavoro.id) || null, da: Date.now() / 1000, prima, quanti, coinvolti: null };
      contaCatenaGiro();
    }
    return;
  }
  // server vecchio: come prima, una domanda a Jarvis con la mappa degli agenti
  ULTIMO.agenti = datiAgenti(null);
  chiediJarvis("Aggiorna la skill e la mappa degli agenti: rileggi i profili reali di ogni progetto, verifica che ogni progetto " +
    "abbia i suoi agenti collegati fra loro e al capogruppo, segnala quelli scollegati o doppi, aggiorna Memoria/00 Comune/Agenti/ " +
    "e rigenera la mappa (strumenti/mappa_agenti.py). Riferisci cosa hai cambiato.", "agenti");
});
$("sa-aggiorna").addEventListener("click", () => {
  const a = AGENTI.get(schedaKey);
  if (!a) return;
  ULTIMO.agenti = datiAgenti(schedaKey);
  $("scheda-agente").close();
  chiediJarvis(`Aggiorna il profilo e la scheda dell'agente ${a.nome} del progetto ${a.progettoNome} secondo la lavagna e la memoria; ` +
    "verifica i collegamenti e riferisci.", "agenti");
});
$("sa-lavagna").addEventListener("click", () => { $("scheda-agente").close(); mettiInLavagna(schedaKey); location.hash = "#lavagna"; });

// ------------------------------------------------ chat al centro
// Un filo per interlocutore («jarvis» o la chiave dell'agente), ognuno con la sua
// sessione di Claude Code: la prima domanda la crea, le altre la riprendono.
const THREADS = mem.leggi("fili", {});
let chatCon = mem.leggi("chatCon", "jarvis");
function filo(k) {
  if (!THREADS[k]) THREADS[k] = { sessione: uuid(), avviata: false, messaggi: [] };
  return THREADS[k];
}
// 2026-10-05 (l'utente: «dentro la chat ci deve essere la chat Jarvis e la chat Postino, la stessa chat identica»):
// la chat «postino» è un interlocutore come gli altri, disegnato dalle stesse funzioni. Ci risponde l'agente
// ~/.claude/agents/postino.md (server.py, chiedi con filo «postino»). Dentro ci sono anche gli avvisi del filo
// «notifiche-jarvis» (report di mattino, pranzo, cena, errori, permessi), uniti in ordine di tempo: FILI_UNITI.
// Le schede in testa, i non letti e i report con le bozze apribili stanno in notifiche.js.
// 2026-10-05 15:05 (l'utente: «nel Postino solo i briefing, i report e le routine che ti chiedo; nella chat principale
// riporti tutto quello che stiamo facendo»): ogni notifica ha una «classe» decisa dal server (fili.py, classifica).
// «report» → chat Postino; «avviso» → chat di Jarvis, come messaggio suo (nessuna risposta parte). Le notifiche
// stanno nei fili «postino» e «notifiche-jarvis»: CLASSE_CHAT dice quale classe mostra ogni chat.
const FILO_POSTINO = "postino";
const FILI_NOTIFICHE = ["postino", "notifiche-jarvis"];
const CLASSE_CHAT = { postino: "report", jarvis: "avviso" };
// una notifica senza classe (pagina vecchia, server non aggiornato): nel filo del Postino è un report, altrove un avviso
const classeDi = (m, k) => (m.classe === "report" || m.classe === "avviso" ? m.classe : k === FILO_POSTINO ? "report" : "avviso");
const FILI_UNITI = { postino: FILI_NOTIFICHE.filter((x) => x !== FILO_POSTINO), jarvis: FILI_NOTIFICHE };
window.classeNotifica = classeDi;          // notifiche.js conta i non letti con la stessa regola
const POSTINO_A = { key: "casa:postino", nome: "Postino" };
const chatPostino = () => chatCon === FILO_POSTINO;
const nomeChat = (a) => (chatPostino() ? "Postino" : nomeDi(a));
function avatarChat(a) {
  if (chatPostino()) {
    try { return avatar(POSTINO_A); } catch (e) { return el("span", { class: "avatar", style: "--c:#d08770", "aria-hidden": "true" }, "P"); }
  }
  return a ? avatar(a) : el("span", { class: "avatar", style: "--c:#f0f0f0" }, "J");
}
// i messaggi da mostrare per k: i suoi, più le notifiche dei fili uniti, al loro posto nel tempo (ts del server;
// un messaggio nato qui e non ancora sul server non ha ts e resta dov'è)
// 2026-10-07 (l'utente: «il tasto Ricomincia non funziona»): la chat di Jarvis mostra anche le notifiche dei fili uniti,
// che «Ricomincia» non toccava: la sessione cambiava ma lo schermo restava uguale. Ora «Ricomincia» segna qui l'ora
// (secondi, come m.ts del server) e le notifiche di prima non si mostrano più in quella chat; restano nei loro fili.
const RICOMINCIATE = mem.leggi("ricominciate", {});
const notificaDopo = (m, k) => !RICOMINCIATE[k] || ((m.ts || 0) > RICOMINCIATE[k]);
function messaggiChat(k) {
  const classe = CLASSE_CHAT[k];
  // nel filo proprio restano le domande e le risposte; le sue notifiche solo se sono della classe di questa chat
  const propri = filo(k).messaggi.filter((m) => !(m && m.notifica) || ((!classe || classeDi(m, k) === classe) && notificaDopo(m, k)));
  const altri = (FILI_UNITI[k] || []).filter((x) => x !== k)
    .flatMap((x) => ((THREADS[x] || {}).messaggi || []).filter((m) => m && m.notifica && classeDi(m, x) === classe && notificaDopo(m, k)))
    .sort((p, q) => (p.ts || 0) - (q.ts || 0));
  if (!altri.length) return propri;
  const out = [];
  let j = 0;
  for (const m of propri) {
    if (m && m.ts) while (j < altri.length && (altri[j].ts || 0) <= m.ts) out.push(altri[j++]);
    out.push(m);
  }
  return out.concat(altri.slice(j));
}
// ✕ su una bolla: il messaggio esce dal filo a cui appartiene (quello della chat o uno dei fili uniti)
function togliMessaggio(m) {
  for (const k of [chatCon, ...FILI_NOTIFICHE]) {
    const l = (THREADS[k] || {}).messaggi || [], i = l.indexOf(m);
    if (i >= 0) { l.splice(i, 1); break; }
  }
  salvaFili(); disegnaMessaggi();
}
// Le chat stanno nel localStorage del browser, che tiene circa 5 MB in tutto: 56 interlocutori
// per 120 messaggi da fino a 40 KB l'uno ci stanno stretti, e oltre il salvataggio falliva in
// silenzio. Tetto in caratteri: se si supera, si tengono meno messaggi per filo (i più vecchi escono).
const TETTO_FILI = 2500000;
function salvaFili() {
  let per = 120;
  for (const t of Object.values(THREADS)) if (t.messaggi.length > per) t.messaggi = t.messaggi.slice(-per);
  let testo = JSON.stringify(THREADS);
  while (testo.length > TETTO_FILI && per > 4) {
    per = Math.floor(per / 2);
    for (const t of Object.values(THREADS)) if (t.messaggi.length > per) t.messaggi = t.messaggi.slice(-per);
    testo = JSON.stringify(THREADS);
  }
  if (per < 120) console.warn(`Command Center: chat oltre ${TETTO_FILI} caratteri, tengo gli ultimi ${per} messaggi per interlocutore`);
  // l'attesa resta: dopo un ricaricamento la risposta si va a prendere lo stesso
  if (!mem.scrivi("fili", THREADS) && !salvaFili.avvisato) {
    salvaFili.avvisato = true;
    toast("Le chat non si salvano più nel browser: spazio pieno. Svuota le conversazioni vecchie.", true);
  }
}
function apriChat(k) {
  if (window.CCVoceChat) window.CCVoceChat.chiudi();        // la scheda «Voce» (voce-chat.js) lascia il posto alla chat scelta
  chatCon = AGENTI.has(k) || k === FILO_POSTINO ? k : "jarvis";
  mem.scrivi("chatCon", chatCon);
  if (chatCon !== FILO_POSTINO) mem.scrivi("chatLavoro", chatCon);   // la scheda «Jarvis» torna qui
  if (location.hash !== "#chat") location.hash = "#chat";
  chiudiCassetti();
  aggiornaTestaChat();
  disegnaMessaggi();
  document.querySelectorAll(".agente").forEach((r) => r.classList.toggle("scelto", r.dataset.agente === chatCon));
  // 2026-10-07 (l'utente): sul telefono e nell'app il fuoco al cambio scheda apriva la tastiera sopra metà chat.
  // Col dito (o nella WebView dell'app) il campo prende il fuoco solo quando l'utente lo tocca; col mouse come prima.
  if (!fuocoSoloAlTocco()) $("chiedi-testo").focus({ preventScroll: true });
}
function fuocoSoloAlTocco() {
  return /\bJarvisApp\//.test(navigator.userAgent) || matchMedia("(pointer: coarse)").matches || matchMedia("(max-width: 820px)").matches;
}

// Comando diretto da una sezione qualunque verso la chat di Jarvis: apre la chat
// con Jarvis (mai con un agente scelto per un'altra ragione) e manda subito la
// domanda già pronta, come i «spunti» della chat vuota. Con il box (data-box) la
// domanda porta con sé quello che il box mostrava (contratto, punto 5): Jarvis legge
// i dati e, se serve lavoro su più progetti, lo distribuisce ai capigruppo.
let contestoProssimo = null;
function chiediJarvis(testo, box) {
  if (THREADS.jarvis && THREADS.jarvis.attesa) { toast("Jarvis sta già rispondendo, aspetta un attimo", true); return; }
  apriChat("jarvis");
  $("chiedi-testo").value = testo;
  contestoProssimo = box ? { box, titolo: TITOLI_BOX[box] || box, dati: ULTIMO[box] ?? null } : null;
  invia();
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-chiedi]");
  if (b) chiediJarvis(b.dataset.chiedi, b.dataset.box || "");
});

// ---- modo della chat: lavoro, lettura o approvazione (contratto, punto 4, decisione dell'utente del 26/09/2026;
// «approvazione» dal 2026-10-03: MODI_CHAT in server.py, che lo accetta anche dall'azione «modo_chat»).
// Il server vecchio non manda modo_chat e risponde sempre in plan mode: allora «lavoro» e «approvazione» sono spenti.
// 🔴 2026-10-03: fino a oggi qui valevano solo lavoro e lettura, e «approvazione» (il modo vero del server)
// si mostrava come «lettura» in tutta la pagina, etichetta del ponte compresa.
const MODI_CHAT = ["lavoro", "lettura", "approvazione"];
const TESTO_MODO = { lavoro: "lavora davvero: la guardia blocca l'irreversibile", lettura: "legge e riferisce, non cambia niente",
  approvazione: "Jarvis chiede il tuo permesso prima di scrivere o lanciare comandi" };
let modoChat = null;
const modoEffettivo = () => modoChat || "lettura";
// 2026-09-26: la guardia dei comandi è un hook di Claude Code. Gli altri motori in «lavoro»
// girano nel sandbox del loro CLI (scrivono solo nella cartella di lavoro), senza la guardia.
// In «approvazione» gli altri motori non hanno il gestore dei permessi: il server li fa lavorare in lettura.
const testoModo = (m) => MOTORE.attivo === "claude" ? TESTO_MODO[m]
  : m === "lavoro" ? "lavora nel sandbox: scrive solo in ~/Jarvis, senza la guardia di Claude"
  : m === "approvazione" ? `${nomeMotore(MOTORE.attivo)} non ha il gestore dei permessi: in approvazione lavora in sola lettura` : TESTO_MODO[m];
// il titolo (tooltip) di un modo: «approvazione: Jarvis chiede il tuo permesso…»
const titoloModo = (m) => `${m}: ${testoModo(m)}`;
function disegnaModoChat(m) {
  modoChat = MODI_CHAT.includes(m) ? m : null;
  const eff = modoEffettivo(), box = $("modo-chat");
  for (const b of box.querySelectorAll("[data-modo]")) {
    const si = b.dataset.modo === eff;
    b.classList.toggle("attivo", si);
    b.setAttribute("aria-pressed", String(si));
    b.disabled = !modoChat && b.dataset.modo !== "lettura";
    b.title = modoChat ? titoloModo(b.dataset.modo) : "Il server non conosce ancora il modo: risponde sempre in sola lettura";
  }
  box.dataset.modo = eff;
  $("nota-modo").textContent = testoModo(eff);
  aggiornaTestaChat();
  if (!THREADS[chatCon] || !THREADS[chatCon].messaggi.length) disegnaMessaggi();   // il benvenuto dice il modo
}
$("modo-chat").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-modo]");
  if (!b || b.classList.contains("attivo")) return;
  const d = await azione({ tipo: "modo_chat", modo: b.dataset.modo }, b);
  if (d && d.modo) { firme.modoChat = undefined; disegnaModoChat(d.modo); }
});

// il motore attivo (vedi «motore» più sotto): qui perché la testa della chat lo usa dal primo disegno
const MOTORE = { attivo: "claude", nomi: { claude: "Claude Code", gemini: "Gemini", cursor: "Cursor", codex: "Codex" } };
const nomeMotore = (id) => MOTORE.nomi[id] || id || "Claude Code";
function aggiornaTestaChat() {
  const a = AGENTI.get(chatCon);
  const av = chatPostino() ? avatarChat(a) : a ? avatar(a) : el("span", { class: "avatar avatar-j", "aria-hidden": "true" }, "J");
  av.id = "chat-avatar";
  av.classList.toggle("al-lavoro", !!(THREADS[chatCon] && THREADS[chatCon].attesa) ||
    (chatCon === "jarvis" ? ATTIVITA.jarvis : ATTIVITA.agenti.has(chatCon)));
  $("chat-avatar").replaceWith(av);
  $("chat-chi").textContent = nomeDi(a);
  // il motore che risponderà (2026-09-26): con Claude il modello del profilo, con gli altri il loro
  $("chat-dove").textContent = (a ? `${progettoDi(a)} · ${a.cartella}` + (MOTORE.attivo === "claude" ? ` · ${a.modello}` : "")
    : "~/Jarvis · la chat master") + " · " + nomeMotore(MOTORE.attivo) + " · " + modoEffettivo();
  $("chiedi-testo").placeholder = `Scrivi a ${nomeDi(a)}, oppure / per i comandi`;
  if (chatPostino()) {
    $("chat-chi").textContent = "Postino";
    $("chat-dove").textContent = "report, briefing, routine e posta · ~/.claude/agents/postino.md · " + nomeMotore(MOTORE.attivo) + " · " + modoEffettivo();
    $("chiedi-testo").placeholder = "Scrivi al Postino: «invia la 1», «cestina la 2»…";
  }
  document.dispatchEvent(new CustomEvent("cc:testa-chat", { detail: chatCon }));   // le schede Jarvis/Postino (notifiche.js)
}

// 🔴 Fino al 26/09/2026 markdown() costruiva una stringa HTML per innerHTML e non scappava le
// virgolette: un link con `"onmouseover="…` diventava un attributo vero, e da lì uno script con
// il token della pagina arrivava al terminale del Mac. Ora la risposta diventa solo nodi DOM:
// testo come testo, link creati con createElement dopo aver controllato che siano http/https.
function linkSicuro(indirizzo) {
  let u;
  try { u = new URL(indirizzo); } catch (e) { return null; }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  const a = document.createElement("a");
  a.href = u.href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = indirizzo;
  return a;
}
function nodiInLinea(testo, dove) {
  const re = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|(https?:\/\/[^\s<>"'`)]+)/g;
  let i = 0, m;
  while ((m = re.exec(testo))) {
    if (m.index > i) dove.append(testo.slice(i, m.index));
    if (m[1] != null) dove.append(el("code", {}, m[1]));
    else if (m[2] != null) dove.append(el("b", {}, m[2]));
    else {
      const url = m[3].replace(/[.,;:!?]+$/, "");          // la punteggiatura in fondo non fa parte del link
      dove.append(linkSicuro(url) || url);
      re.lastIndex = m.index + url.length;
    }
    i = re.lastIndex;
  }
  if (i < testo.length) dove.append(testo.slice(i));
}
function markdown(testo) {
  const frag = document.createDocumentFragment();
  String(testo || "").split(/```[\w-]*\n?/).forEach((p, i) => {
    if (i % 2) frag.append(el("pre", {}, el("code", {}, p.replace(/\n$/, ""))));
    else nodiInLinea(p, frag);
  });
  return frag;
}

// La bolla «sto scrivendo» (mockup 26/09/2026, idea 5): tre puntini che saltano in fila
// dentro una bolla scura, con una scia di luce che corre sotto. Serve alla chat scritta
// e alla chat a voce della scheda Stato.
function bollaScrive(chi) {
  return el("div", { class: "bolla-scrive", role: "status", "aria-label": (chi || ASSISTENTE) + " sta scrivendo" },
    el("i"), el("i"), el("i"));
}

function disegnaMessaggi() {
  const box = $("messaggi");
  const t = filo(chatCon);
  const a = AGENTI.get(chatCon);
  const lista = messaggiChat(chatCon);
  if (chatPostino() && !lista.length && !t.attesa) {
    box.replaceChildren(el("div", { class: "benvenuto" }, el("b", {}, "Postino"),
      el("span", {}, "Qui arrivano solo i report e i briefing (mattino, pranzo, cena, pomeriggio, direzione), le routine che hai chiesto e i report della posta, numerati e con le bozze pronte. Errori e avanzamenti stanno nella chat di Jarvis. Rispondi con i numeri: «invia la 1», «cestina la 2», «cambia la bozza 3: …». Risponde il Postino; si spedisce solo con il tuo «invia».")));
    return;
  }
  if (!lista.length && !t.attesa) {
    // spunti (26/09/2026): con Jarvis prima le domande frequenti dell'utente (catalogo, «frequenti»),
    // poi quelli fissi finché le frequenti sono meno di 5; con un agente restano i suoi tre
    const fissi = a ? ["A che punto sei?", "Cosa ti serve da me?", "Quali errori non devo ripetere?"]
      : ["Cosa c'è da fare oggi?", "Riassumi lo stato dei progetti", "Chi sta lavorando adesso?"];
    const frequenti = a ? [] : (CAT.frequenti || []).filter((f) => f && f.testo);
    const manda = (testo) => { $("chiedi-testo").value = testo; invia(); };
    const spunti = [
      ...frequenti.map((f) => el("span", { class: "spunto-freq" },
        el("button", { type: "button", title: f.testo, onclick: () => manda(f.testo) },
          f.testo.length > 60 ? f.testo.slice(0, 58) + "…" : f.testo, f.conta ? el("small", {}, " ×" + f.conta) : ""),
        el("button", { type: "button", class: "togli", "data-solo-mac": "frequenti:togli", title: "Togli dalle frequenti", "aria-label": "Togli dalle frequenti",
          onclick: async (ev) => { const d = await azione({ tipo: "frequenti", cosa: "togli", testo: f.testo }, ev.currentTarget); if (d) catalogo().catch(() => {}); } }, "×"))),
      ...(frequenti.length < 5 ? fissi.map((s) => el("button", { type: "button", onclick: () => manda(s) }, s)) : []),
    ];
    box.replaceChildren(el("div", { class: "benvenuto" },
      el("b", {}, a ? `${aspettoDi(a).emoji} ${nomeDi(a)}` : (UTENTE ? `Ciao ${UTENTE}, su cosa lavoriamo oggi?` : "Ciao, su cosa lavoriamo oggi?")),
      el("span", {}, a ? notaDi(a) || a.descrizione : `Scrivi qui: risponde ${nomeMotore(MOTORE.attivo)}, in modo ${modoEffettivo()} (${testoModo(modoEffettivo())}).` + (ponteConsente("comando_diretto") ? " I comandi con / partono subito." : " I comandi con / partono solo dal Mac.")),
      el("div", { class: "spunti" }, ...spunti)));
    return;
  }
  box.replaceChildren(...lista.map((m, i) => bollaMessaggio(m, i, a)));
  if (t.attesa) {
    box.append(el("div", { class: "msg" }, avatarChat(a),
      el("div", { class: "corpo" }, el("div", { class: "chi" }, nomeChat(a) + " · sta lavorando ",
        el("span", { class: "durata", id: "durata-attesa" }, "")), bollaScrive(nomeChat(a)))));
  }
  box.scrollTop = box.scrollHeight;
}
function bollaMessaggio(m, i, a) {
  const mio = m.chi === "io";
  const testo = el("div", { class: "testo" });
  if (mio || m.tipo === "comando") testo.textContent = m.testo; else testo.replaceChildren(markdown(m.testo));
  // un report o un avviso (notifica.py): titolo e bozze apribili, da notifiche.js
  if (m.notifica && window.CCNotifiche && typeof window.CCNotifiche.arricchisci === "function") {
    try { window.CCNotifiche.arricchisci(testo, m); } catch (e) { /* la bolla resta col solo testo */ }
  }
  const azioni = el("span", { class: "azioni-msg" },
    el("button", { class: "icona", title: "Copia", onclick: () => navigator.clipboard.writeText(m.testo).then(() => toast("Copiato")) }, "⧉"),
    mio ? el("button", { class: "icona", title: "Modifica e rimanda", onclick: () => { $("chiedi-testo").value = m.testo; autoAltezza(); $("chiedi-testo").focus(); } }, "✎") : "",
    el("button", { class: "icona", title: "Togli dalla chat", onclick: () => togliMessaggio(m) }, "✕"));
  const chi = (mio ? nomeUtente() : m.tipo === "comando" ? m.titolo || "comando" : m.notifica ? m.mittente || nomeChat(a) : nomeChat(a))
    + (m.box ? ` · dal box «${m.box}»` : "") + (m.prova ? " · prova" : "")
    + (!mio && m.motore && m.motore !== "claude" ? ` · via ${nomeMotore(m.motore)}` : "");
  // una notifica ha la faccia di chi la manda (il report di Jarvis nella chat Postino, l'avviso del Postino da Jarvis)
  const facciaJ = () => el("span", { class: "avatar", style: "--c:#f0f0f0", "aria-hidden": "true" }, "J");
  const faccia = !m.notifica ? avatarChat(a) : m.mittente === "Jarvis" ? (chatPostino() ? facciaJ() : avatarChat(a))
    : m.mittente === "Postino" && !chatPostino() ? (() => { try { return avatar(POSTINO_A); } catch (e) { return facciaJ(); } })() : avatarChat(a);
  return el("div", { class: "msg" + (mio ? " mio" : "") + (m.errore && m.testo !== "(fermato da te)" ? " errore" : "") + (m.tipo === "comando" ? " comando" : "") + (m.notifica ? " notifica" : "") },
    mio ? "" : (m.tipo === "comando" ? el("span", { class: "avatar", style: "--c:#5a5a5a" }, "/") : faccia),
    el("div", { class: "corpo" }, el("div", { class: "chi" }, chi + " · " + (m.ora || ""), azioni), testo));
}

const COMANDI = [
  { nome: "memoria", arg: "parole", descr: "cerca nella memoria del vault" },
  { nome: "brain", arg: "", descr: "a che punto è il progetto dell'interlocutore" },
  { nome: "lavori", arg: "", descr: "chi sta lavorando adesso (lavori.py chi)" },
  { nome: "verifica", arg: "", descr: "quadro di sincronia di tutti i progetti" },
];
const oraBreve = () => new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

async function invia() {
  const campo = $("chiedi-testo");
  const testo = campo.value.trim();
  if (!testo) return;
  const k = chatCon, t = filo(k), a = AGENTI.get(k);
  const ctx = contestoProssimo;          // il box da cui arriva la domanda vale solo per questa
  contestoProssimo = null;
  if (t.attesa) { toast("Aspetta la risposta in corso", true); return; }
  campo.value = ""; autoAltezza(); nascondiSuggerimenti();
  t.messaggi.push(Object.assign({ chi: "io", testo, ora: oraBreve(), ts: Date.now() / 1000 }, ctx ? { box: ctx.titolo } : {}));
  let corpo;
  const cmd = testo.match(/^\/([\w:.-]+)\s*(.*)$/s);
  // «/verifica:<id>» e «/rapido:<id>» scritti a mano valgono come scelti dal menu
  const daMenu = cmd && /^(verifica|rapido):/.test(cmd[1]) && vociMenu("").find((v) => v.id === cmd[1]);
  if (daMenu) { salvaFili(); lanciaDaMenu(daMenu); return; }
  if (cmd) {
    corpo = { tipo: "comando_diretto", nome: cmd[1].toLowerCase(), arg: cmd[2].trim(), progetto: a ? a.progetto : "" };
  } else {
    // le dipendenze disegnate in lavagna viaggiano con la domanda
    const dip = a ? dipendenzeDi(k).map((n) => (AGENTI.get(n.agente) || {}).nome || n.testo).filter(Boolean) : [];
    const contesto = dip.length ? `\n\n(Sulla lavagna dell'utente dipendi da: ${dip.join(", ")}.)` : "";
    corpo = { tipo: "chiedi", testo: testo + contesto, sessione: t.sessione, continua: t.avviata,
      agente: a ? a.nome : "", progetto: a ? a.progetto : "", motore: MOTORE.attivo };
    if (k === FILO_POSTINO) corpo.filo = FILO_POSTINO;        // risponde l'agente postino (server.py, chiedi)
    if (ctx) corpo.contesto = ctx;
  }
  try {
    const d = await api("/api/azione", corpo, 30000);
    if (d.reset) {          // «nuova conversazione» / «reset»: il server ha chiuso il filo, se ne apre uno nuovo
      THREADS[k] = { sessione: d.sessione, avviata: false, messaggi: [{ chi: "lui", testo: d.messaggio, ora: oraBreve() }] };
      salvaFili(); if (k === chatCon) disegnaMessaggi(); aggiornaInvia();
      return;
    }
    t.attesa = { id: d.lavoro.id, inizio: Date.now(), comando: !!cmd, titolo: cmd ? "/" + cmd[1] : "" };
  } catch (e) {
    t.messaggi.push({ chi: "lui", testo: e.message, errore: true, ora: oraBreve() });
  }
  salvaFili();
  if (k === chatCon) disegnaMessaggi();
  segnaAttivi();
  aggiornaInvia();
}

// Le risposte arrivano come «lavori» del server: si leggono finché non sono chiusi.
let seguiInCorso = false;
async function seguiRisposte() {
  if (seguiInCorso) return;
  seguiInCorso = true;
  try { await seguiRisposteGiro(); } finally { seguiInCorso = false; }
}
async function seguiRisposteGiro() {
  for (const [k, t] of Object.entries(THREADS)) {
    if (!t.attesa) continue;
    try {
      const d = await api("/api/lavoro/" + t.attesa.id);
      if (d.stato === "in corso") continue;
      // 2026-10-07: dopo «■ Ferma» (stop-chat.js, ponte.js segnano attesa.fermato) il lavoro chiude in «errore» senza testo
      const testo = (d.testo || "").replace(/^\(cartella: [^\n]*\)\n\n?/, "").trim() || (t.attesa.fermato ? "(fermato da te)" : "(nessuna risposta)");
      // lo Stop è voluto: niente bollino rosso (il server dal 07/10 lo chiude «finito» con fermato; prima era «errore» 143/-15)
      const fermato = !!(d.fermato || t.attesa.fermato);
      const ok = d.stato === "finito" || fermato;
      if (!t.attesa.comando && d.stato === "finito" && !fermato) t.avviata = true;          // la sessione ora esiste: le prossime la riprendono
      if (!t.attesa.comando && (!ok || fermato) && !t.avviata) t.sessione = uuid();   // sessione mai nata: si riparte pulita
      t.messaggi.push({ chi: "lui", testo, ora: oraBreve(), ts: Date.now() / 1000, errore: !ok, tipo: t.attesa.comando ? "comando" : "", titolo: t.attesa.titolo,
        motore: d.motore || "" });
      catalogo().catch(() => {});          // le domande frequenti cambiano dopo ogni risposta
      t.attesa = null;
      salvaFili();
      if (k === chatCon) disegnaMessaggi();
      segnaAttivi();
      aggiornaInvia();
    } catch (e) {
      // il server è ripartito e il lavoro non c'è più
      if (/non trovato/.test(e.message)) { t.attesa = null; t.messaggi.push({ chi: "lui", testo: "Risposta persa: il Command Center è ripartito. Rimanda la domanda.", errore: true, ora: oraBreve() }); salvaFili(); if (k === chatCon) disegnaMessaggi(); aggiornaInvia(); }
    }
  }
  const t = THREADS[chatCon], dur = $("durata-attesa");
  if (t && t.attesa && dur) dur.textContent = Math.round((Date.now() - t.attesa.inizio) / 1000) + "s";
}

function aggiornaInvia() {
  const attesa = !!(THREADS[chatCon] && THREADS[chatCon].attesa);
  $("btn-invia").disabled = attesa;
  aggiornaSpie();
  if (ultimoStato) aggiornaAttivita(ultimoStato); else segnaAttivi();
}
function autoAltezza() { const c = $("chiedi-testo"); c.style.height = "auto"; c.style.height = Math.min(200, c.scrollHeight) + "px"; }

// Il menu «/» (26/09/2026, richiesta dell'utente): tutti i comandi, in gruppi. Diretti (i quattro di
// sempre), skill e comandi di Claude Code (catalogo, «skills»: il server accetta «/nome …»), le
// verifiche («/verifica:<id>», lanciano l'azione verifica) e i comandi rapidi («/rapido:<id>»).
// Si filtra su nome e descrizione con quello che si scrive dopo la barra.
let sugScelto = 0;
let MENU = [];
function vociMenu(q) {
  q = String(q || "").toLowerCase();
  const gruppi = [
    ["Diretti", COMANDI.map((c) => ({ id: c.nome, descr: c.descr, arg: !!c.arg, tipo: "diretto" }))],
    ["Skill e comandi di Claude Code", (CAT.skills || []).map((s) => ({ id: String(s.id || s.nome || "").replace(/^\//, ""),
      descr: s.descrizione || s.nome || "", etichetta: s.origine || "", arg: true, tipo: "skill" }))],
    ["Verifiche", (CAT.verifiche || []).map((v) => ({ id: "verifica:" + v.id, nome: v.nome, rif: v.id,
      descr: v.nome + (v.descrizione ? " · " + v.descrizione : ""), tipo: "verifica" }))],
    ["Comandi rapidi", (CAT.comandi || []).map((c) => ({ id: "rapido:" + c.id, nome: c.nome, rif: c.id,
      descr: c.nome + (c.descrizione ? " · " + c.descrizione : ""), tipo: "rapido" }))],
  ];
  const out = [];
  for (const [gruppo, voci] of gruppi) for (const v of voci)
    if (v.id && (!q || v.id.toLowerCase().includes(q) || String(v.descr || "").toLowerCase().includes(q))) out.push(Object.assign({ gruppo }, v));
  return out;
}
function nascondiSuggerimenti() { $("suggerimenti").classList.add("nascosto"); }
function mostraSuggerimenti() {
  const box = $("suggerimenti");
  const m = $("chiedi-testo").value.match(/^\/(\S*)$/);
  if (!m || !ponteConsente("comando_diretto")) return nascondiSuggerimenti();   // ponte con i comandi spenti: «/» non passa
  MENU = vociMenu(m[1]);
  if (!MENU.length) return nascondiSuggerimenti();
  sugScelto = Math.max(0, Math.min(sugScelto, MENU.length - 1));
  const nodi = [];
  let gruppo = null;
  MENU.forEach((c, i) => {
    if (c.gruppo !== gruppo) { gruppo = c.gruppo; nodi.push(el("div", { class: "sug-gruppo" }, gruppo)); }
    nodi.push(el("button", { type: "button", "data-i": i, class: i === sugScelto ? "scelto" : "", onclick: () => scegliComando(c) },
      el("b", {}, "/" + c.id + (c.arg ? " …" : "")), el("small", {}, c.descr || ""),
      c.etichetta ? el("span", { class: "sug-etichetta" }, c.etichetta) : ""));
  });
  box.replaceChildren(...nodi);
  box.classList.remove("nascosto");
  const scelto = box.querySelector(`[data-i="${sugScelto}"]`);
  if (scelto) scelto.scrollIntoView({ block: "nearest" });
}
function scegliComando(c) {
  nascondiSuggerimenti();
  if (c.tipo === "verifica" || c.tipo === "rapido") { $("chiedi-testo").value = ""; autoAltezza(); lanciaDaMenu(c); return; }
  $("chiedi-testo").value = "/" + c.id + " ";
  autoAltezza();
  if (c.tipo === "diretto" && !c.arg) invia(); else $("chiedi-testo").focus();
}
// verifiche e comandi rapidi non rispondono in chat: partono come lavori, e la chat lo dice
async function lanciaDaMenu(c) {
  const t = filo(chatCon);
  const d = await azione(c.tipo === "verifica" ? { tipo: "verifica", id: c.rif } : { tipo: "comando", id: c.rif });
  t.messaggi.push({ chi: "lui", tipo: "comando", titolo: "/" + c.id, errore: !d, ora: oraBreve(),
    testo: d ? `Avviato: ${c.nome}. Il risultato arriva in Squadra › Lavori.` : `Non è partito: ${c.nome}.` });
  salvaFili();
  disegnaMessaggi();
}
$("chiedi-testo").addEventListener("input", () => { autoAltezza(); sugScelto = 0; mostraSuggerimenti(); });
$("chiedi-testo").addEventListener("keydown", (ev) => {
  const aperti = !$("suggerimenti").classList.contains("nascosto");
  if (aperti && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
    ev.preventDefault();
    const n = MENU.length;
    sugScelto = (sugScelto + (ev.key === "ArrowDown" ? 1 : n - 1)) % n;
    mostraSuggerimenti();
    return;
  }
  if (aperti && (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey))) {
    const b = $("suggerimenti").querySelector(`[data-i="${sugScelto}"]`);
    const v = $("chiedi-testo").value.trim();
    // «/lavori» già scritto per intero parte con Invio; altrimenti si completa
    if (b && !(ev.key === "Enter" && COMANDI.some((c) => "/" + c.nome === v))) { ev.preventDefault(); b.click(); return; }
  }
  if (ev.key === "Escape") nascondiSuggerimenti();
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); invia(); }
});
$("form-chiedi").addEventListener("submit", (ev) => { ev.preventDefault(); invia(); });
$("comandi-diretti").addEventListener("click", (ev) => {
  if (ev.target.closest("[data-cmd-tutti]")) {           // «/ tutti»: apre il menu intero
    $("chiedi-testo").value = "/"; sugScelto = 0; autoAltezza(); mostraSuggerimenti(); $("chiedi-testo").focus(); return;
  }
  const b = ev.target.closest("[data-cmd]");
  if (!b) return;
  const c = COMANDI.find((x) => x.nome === b.dataset.cmd);
  if (c.arg) { $("chiedi-testo").value = "/" + c.nome + " "; $("chiedi-testo").focus(); autoAltezza(); }
  else { $("chiedi-testo").value = "/" + c.nome; invia(); }
});
$("btn-svuota-chat").addEventListener("click", () => {
  const t = filo(chatCon);
  if (t.attesa) { toast("Aspetta la risposta in corso", true); return; }
  // si conta quello che si vede (anche le notifiche dei fili uniti), non solo il filo proprio
  if (messaggiChat(chatCon).length && !confirm("Ricominciare da zero con questo interlocutore? La conversazione sparisce da qui.")) return;
  RICOMINCIATE[chatCon] = Date.now() / 1000;
  mem.scrivi("ricominciate", RICOMINCIATE);
  // chat Postino: il filo nuovo deve nascere anche sul server, altrimenti i report successivi andrebbero nel filo
  // lasciato e qui non si vedrebbero più. «nuova conversazione» è il reset esplicito che il server conosce (chiedi).
  if (chatPostino()) { $("chiedi-testo").value = "nuova conversazione"; invia(); return; }
  THREADS[chatCon] = { sessione: uuid(), avviata: false, messaggi: [] };
  salvaFili(); disegnaMessaggi(); aggiornaInvia();
  toast("Nuova conversazione");
});
$("btn-nuova-chat").addEventListener("click", () => apriChat("jarvis"));

// ------------------------------------------------ lavagna
const LAV = { sel: null, selFilo: null, multi: new Set() };   // multi: selezione con Ctrl/Cmd/Maiusc (30/09/2026)
function nodoDi(id) { return lav().nodi.find((n) => n.id === id); }
// la vista (zoom e scorrimento) è di questa scheda del browser (audit 02/10/2026): localStorage, non pannello.json
const VISTE_LETTE = new Set();
// 2026-10-05 (l'utente: «sul Mac è perfetta, sugli altri dispositivi la lavagna è tagliata»): pannello.json porta ancora la
// «vista» salvata dal Mac prima del 02/10 (zoom 0,36 per uno schermo da 1700 px). Un dispositivo senza una vista sua
// la prendeva per buona e sul telefono vedeva solo un angolo. Ora quella del server non vale: la lavagna si adatta
// allo schermo la prima volta che si vede (adattaVistaSeServe) e da lì la vista resta di questo dispositivo.
const VISTE_DA_ADATTARE = new Set();
function vista() {
  const L = lav();
  if (!VISTE_LETTE.has(lavagnaAttiva)) {
    VISTE_LETTE.add(lavagnaAttiva);
    const v = mem.leggi("vista:" + lavagnaAttiva, null);
    if (v && [v.x, v.y, v.zoom].every(Number.isFinite)) L.vista = v;
    else { L.vista = { x: 0, y: 0, zoom: 1 }; VISTE_DA_ADATTARE.add(lavagnaAttiva); }
  }
  return L.vista || (L.vista = { x: 0, y: 0, zoom: 1 });
}
// la prima volta che la lavagna è a schermo con le schede disegnate: «Centra» su questo schermo, senza salvare il pannello
// 2026-10-10: se nessuna scheda è nel riquadro visibile (telefono a 375 px, vista salvata vecchia, schede nate
// dopo), la lavagna si centra da sola una volta per caricamento, senza salvare il pannello
const CENTRATE_DA_SOLE = new Set();
function centraSeFuoriVista() {
  const box = $("lavagna"), mondo = $("lav-mondo");
  if (!box || !mondo || CENTRATE_DA_SOLE.has(lavagnaAttiva)) return;
  const r = box.getBoundingClientRect();
  const nodi = [...mondo.querySelectorAll(".nodo")];
  if (r.width < 40 || r.height < 40 || !nodi.length) return;
  const dentro = nodi.some((n) => { const q = n.getBoundingClientRect(); return q.right > r.left && q.left < r.right && q.bottom > r.top && q.top < r.bottom; });
  if (dentro) return;                                   // si vede già qualcosa: non si tocca la vista
  CENTRATE_DA_SOLE.add(lavagnaAttiva);
  centraLavagna(false);
}
// nei primi 20 s dopo l'apertura (pannello, spazi e vista arrivano in momenti diversi) si controlla a ogni disegno
var AVVIO_PAGINA = Date.now();   // var: si può leggere anche prima di questa riga (vale undefined)
function adattaVistaSeServe() {
  if (!VISTE_DA_ADATTARE.has(lavagnaAttiva)) return;
  const r = $("lavagna").getBoundingClientRect();
  if (r.width < 40 || r.height < 40 || !$("lav-mondo").querySelector(".nodo")) return;   // nascosta o vuota: alla prossima
  VISTE_DA_ADATTARE.delete(lavagnaAttiva);
  centraLavagna(false);
}
function applicaVista() {
  const v = vista();
  if (!VISTE_DA_ADATTARE.has(lavagnaAttiva)) mem.scrivi("vista:" + lavagnaAttiva, v);
  $("lav-mondo").style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.zoom})`;
  // le bolle delle sinapsi restano leggibili a ogni zoom: si ingrandiscono al contrario del foglio
  $("lav-mondo").style.setProperty("--inv", String(Math.min(1.8, 1 / v.zoom)));
  $("lavagna").style.backgroundPosition = `${v.x}px ${v.y}px`;
  $("lavagna").style.backgroundSize = `${18 * v.zoom}px ${18 * v.zoom}px`;
}
function puntoMondo(clientX, clientY) {
  const r = $("lavagna").getBoundingClientRect(), v = vista();
  return { x: (clientX - r.left - v.x) / v.zoom, y: (clientY - r.top - v.y) / v.zoom };
}
function disegnaLavagna() {
  const mondo = $("lav-mondo");
  if (!mondo) return;
  if (LAV.gesto || modificaInCorso()) { LAV.ridisegnaDopo = true; return; }   // audit 02/10/2026: si ridisegna a gesto finito
  if ($("lav-titolo")) $("lav-titolo").textContent = lavagnaTitolo;
  for (const n of [...mondo.querySelectorAll(".nodo")]) n.remove();
  for (const n of lav().nodi) {
    if (n.tipo === "agente" && !AGENTI.has(n.agente) && AGENTI.size) continue;   // agente sparito dai profili
    mondo.append(schedaNodo(n));
  }
  $("lav-vuota").classList.toggle("nascosto", lav().nodi.length > 0 || (SPAZI_API_OK && nessunProgettoVero()));   // con zero progetti parla lo stato vuoto
  applicaVista();
  adattaVistaSeServe();
  disegnaFili();
  segnaAttivi();
  $("lav-togli").disabled = !(LAV.sel || LAV.selFilo != null);   // il filo 0 è un filo vero
  if (Date.now() - AVVIO_PAGINA < 20000) requestAnimationFrame(centraSeFuoriVista);
}
// una nota della lavagna che è anche uno spazio vero: il suo gruppo
// nella colonna a sinistra è sempre "spazio-<id>", trovato per nome (le note non portano l'id).
function gruppoDiNota(testo) {
  const s = (spaziCat || []).find((x) => x.nome === testo);
  if (s) return "spazio-" + s.id;
  const pr = progettoDiEtichetta(testo);
  return pr ? "spazio-" + pr.s.id : null;
}
// note che non sono spazi ma sono comunque reali: Memoria (una cartella), esecutore e ricercatore-web
// (agenti veri di Jarvis, fuori da ogni progetto) — 27/09/2026, l'utente: «deve essere certo che sia collegata»
const NOTE_DI_CASA = new Set(["memoria", "esecutore", "ricercatore-web", "jarvis"]);
// la nota «Jarvis — orchestratore, risponde all'utente» è Jarvis: nome della nota di casa da un testo di nota
const nomeNotaDiCasa = (testo) => { const t = String(testo || "").toLowerCase().trim(); return eNotaOrchestratore(testo) ? "jarvis" : t; };
let schedaCasaNome = null;
async function apriNotaDiCasa(nome) {
  try {
    const r = await fetch("/api/nota-di-casa?nome=" + encodeURIComponent(nome), { headers: HDR });
    const d = await r.json();
    if (!r.ok) { toast(d.errore || "non trovata", true); return; }
    if (d.tipo === "cartella") { toast(`Cartella vera, non ha altro da modificare: ${d.percorso}`); return; }
    schedaCasaNome = nome;
    $("sc-avatar").textContent = nome[0].toUpperCase();
    $("sc-nome").textContent = nome;
    $("sc-percorso").textContent = d.percorso;
    $("sc-descr").value = d.descrizione || "";
    $("sc-modello").value = d.modello || "sonnet";
    $("sc-strumenti").value = d.strumenti || "";
    $("sc-tono").value = d.tono || "";
    $("sc-umor").value = d.umorismo == null ? 1 : d.umorismo;
    $("sc-umor-t").textContent = UMORISMO[$("sc-umor").value];
    $("sc-seri").value = d.serieta == null ? 2 : d.serieta;
    $("sc-seri-t").textContent = SERIETA[$("sc-seri").value];
    $("scheda-casa").showModal();
  } catch (e) { toast("Non sono riuscito a verificarla: " + e.message, true); }
}
$("sc-umor").addEventListener("input", (ev) => { $("sc-umor-t").textContent = UMORISMO[+ev.target.value]; });
$("sc-seri").addEventListener("input", (ev) => { $("sc-seri-t").textContent = SERIETA[+ev.target.value]; });
$("form-scheda-casa").addEventListener("submit", async (ev) => {
  if (!ev.submitter || ev.submitter.value !== "salva") return;
  const d = await azione({ tipo: "agente", cosa: "salva_casa", nome: schedaCasaNome,
    description: $("sc-descr").value.trim(), model: $("sc-modello").value, tools: $("sc-strumenti").value.trim(),
    tono: $("sc-tono").value.trim(), umorismo: +$("sc-umor").value, serieta: +$("sc-seri").value }, ev.submitter);
  if (d) toast(d.messaggio || "salvato");
});
function aggiornaSelezione() {
  for (const d of document.querySelectorAll("#lav-mondo .nodo[data-id]")) d.classList.toggle("scelto", d.dataset.id === LAV.sel || LAV.multi.has(d.dataset.id));
  $("lav-togli").disabled = !(LAV.sel || LAV.multi.size || LAV.selFilo != null);
}
function schedaNodo(n) {
  let d;
  if (n.tipo === "nota") {
    const t = el("div", { class: "testo-nota" }, n.testo || "Nota");
    const colore = coloreNota(n);
    const gid = gruppoDiNota(n.testo);
    const casa = NOTE_DI_CASA.has(nomeNotaDiCasa(n.testo));
    d = el("div", { class: "nodo nota" + (colore ? " colorata" : "") + (n.id === "demo-jarvis" ? " grande" : ""), "data-id": n.id,
      title: gid ? "Doppio clic per scrivere · tasto destro: scheda dello spazio"
        : casa ? "Doppio clic per scrivere · tasto destro: verifica il collegamento vero" : "Doppio clic per scrivere",
      style: colore ? `--c:${colore}` : null }, t, ...bottoniLink(n));
    d.addEventListener("dblclick", (ev) => { ev.stopPropagation(); modificaNota(t, n); });
    if (gid) d.addEventListener("contextmenu", (ev) => { ev.preventDefault(); apriSchedaGruppo(gid); });
    else if (casa) d.addEventListener("contextmenu", (ev) => { ev.preventDefault(); apriNotaDiCasa(nomeNotaDiCasa(n.testo)); });
  } else {
    const a = AGENTI.get(n.agente) || { key: n.agente, nome: n.agente.split(":").pop(), progettoNome: "", modello: "", spazio: "" };
    d = el("div", { class: "nodo" + (a.attivo === false ? " spento" : ""), "data-id": n.id, "data-agente": n.agente, title: "Doppio clic: chatta · tasto destro: scheda",
      style: `--c:${aspettoDi(a).colore}` }, avatar(a),
      el("div", { class: "testo" }, el("b", {}, nomeDi(a)), el("small", {}, [progettoDi(a), a.modello].filter(Boolean).join(" · "))), ...bottoniLink(n));
    d.addEventListener("dblclick", (ev) => { ev.stopPropagation(); apriChat(n.agente); });
    d.addEventListener("contextmenu", (ev) => { ev.preventDefault(); if (!ev.ctrlKey) apriScheda(n.agente); });   // su Mac Ctrl+clic = tasto destro: qui serve a selezionare
  }
  d.append(el("span", { class: "porta", title: "Tira su un'altra scheda: «dipende da»" }));
  d.style.left = n.x + "px"; d.style.top = n.y + "px";
  d.classList.toggle("scelto", LAV.sel === n.id || LAV.multi.has(n.id));
  return d;
}
function modificaNota(t, n) {
  t.contentEditable = "true"; t.focus();
  document.getSelection().selectAllChildren(t);
  t.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Escape") t.blur(); });
  t.addEventListener("blur", () => { t.contentEditable = "false"; n.testo = t.innerText.trim().slice(0, 2000); salvaPannello(true); disegnaFili(); dopoInterazione(); }, { once: true });
}
function centroNodo(n, lato) {
  const d = document.querySelector(`.nodo[data-id="${CSS.escape(n.id)}"]`);
  const w = d ? d.offsetWidth : 192, h = d ? d.offsetHeight : 44;
  return lato === "uscita" ? { x: n.x + w, y: n.y + h / 2 } : { x: n.x, y: n.y + h / 2 };
}
function rettNodo(n) {
  const d = document.querySelector(`.nodo[data-id="${CSS.escape(n.id)}"]`);
  const w = d ? d.offsetWidth : 192, h = d ? d.offsetHeight : 44;
  return { x: n.x, y: n.y, w, h, cx: n.x + w / 2, cy: n.y + h / 2 };
}
// il lato del rettangolo r più naturale per andare verso (altroCx, altroCy):
// sopra o sotto se il salto verticale conta di più, altrimenti destra o sinistra.
// Così un filo verso una scheda più in basso esce dal basso, non sempre da destra.
function puntoVersoAltro(r, altroCx, altroCy) {
  const dx = altroCx - r.cx, dy = altroCy - r.cy;
  if (Math.abs(dy) > Math.abs(dx) * .6) return dy >= 0 ? { x: r.cx, y: r.y + r.h, lato: "s" } : { x: r.cx, y: r.y, lato: "n" };
  return dx >= 0 ? { x: r.x + r.w, y: r.cy, lato: "e" } : { x: r.x, y: r.cy, lato: "o" };
}
function curva(p, q) {
  if (!p.lato || !q.lato) {   // filo provvisorio mentre si trascina: sempre orizzontale, come prima
    const dx = Math.max(40, Math.abs(q.x - p.x) / 2);
    return `M${p.x},${p.y} C${p.x + dx},${p.y} ${q.x - dx},${q.y} ${q.x},${q.y}`;
  }
  const scarto = { n: [0, -1], s: [0, 1], e: [1, 0], o: [-1, 0] }, d = 40;
  const [ox1, oy1] = scarto[p.lato], [ox2, oy2] = scarto[q.lato];
  return `M${p.x},${p.y} C${p.x + ox1 * d},${p.y + oy1 * d} ${q.x + ox2 * d},${q.y + oy2 * d} ${q.x},${q.y}`;
}
function disegnaFili() {
  const svg = $("lav-fili");
  for (const p of [...svg.querySelectorAll("path.filo, path.filo-presa")]) p.remove();
  const visibile = (n) => n && !(n.tipo === "agente" && AGENTI.size && !AGENTI.has(n.agente));
  lav().fili.forEach((f, i) => {
    const a = nodoDi(f.da), b = nodoDi(f.a);
    if (!visibile(a) || !visibile(b)) return;
    const ra = rettNodo(a), rb = rettNodo(b);
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const forma = formaFilo(a, b);
    p.dataset.da = f.da; p.dataset.a = f.a;
    p.setAttribute("d", forma ? percorsoOrtogonale(forma, ra, rb)
      : curva(puntoVersoAltro(ra, rb.cx, rb.cy), puntoVersoAltro(rb, ra.cx, ra.cy)));
    p.setAttribute("class", "filo" + (LAV.selFilo === i ? " scelto" : ""));
    const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
    t.textContent = `${etichettaNodo(a)} dipende da ${etichettaNodo(b)} · clic: sceglilo e compare ✕ · doppio clic: toglilo`;
    // il filo visibile è sottile (1,6 px): una seconda traccia trasparente larga 16 px lo rende facile da prendere
    const presa = p.cloneNode(false);
    presa.setAttribute("class", "filo-presa");
    presa.removeAttribute("data-da"); presa.removeAttribute("data-a");
    presa.append(t);
    presa.addEventListener("pointerenter", () => p.classList.add("sopra"));
    presa.addEventListener("pointerleave", () => p.classList.remove("sopra"));
    presa.addEventListener("pointerdown", (ev) => { if (ev.button !== 0) return; ev.stopPropagation(); scegliFilo(i); });
    presa.addEventListener("dblclick", (ev) => { ev.stopPropagation(); LAV.selFilo = i; LAV.sel = null; togliScelto(); });
    presa.addEventListener("contextmenu", (ev) => { ev.preventDefault(); ev.stopPropagation(); scegliFilo(i); });
    svg.append(p, presa);
  });
  marcaFili();
  applicaSinapsi();
  posaXFilo();
}
function scegliFilo(i) {
  LAV.selFilo = i; LAV.sel = null;
  document.querySelectorAll(".nodo.scelto").forEach((x) => x.classList.remove("scelto"));
  document.querySelectorAll("#lav-fili path.filo.scelto").forEach((x) => x.classList.remove("scelto"));
  const f = lav().fili[i];
  const p = f && document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(f.da)}"][data-a="${CSS.escape(f.a)}"]`);
  if (p) p.classList.add("scelto");
  $("lav-togli").disabled = false;
  posaXFilo();
  $("lavagna").focus({ preventScroll: true });
}
// il ✕ sta a metà del filo scelto: un clic e il collegamento se ne va
function posaXFilo() {
  let x = $("lav-x-filo");
  if (!x) {
    x = el("button", { class: "lav-x-filo nascosto", id: "lav-x-filo", type: "button", title: "Togli questo collegamento" }, "✕");
    x.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    x.addEventListener("click", (ev) => { ev.stopPropagation(); togliScelto(); });
    $("lav-mondo").append(x);
  }
  const f = LAV.selFilo != null && lav().fili[LAV.selFilo];
  const p = f && document.querySelector(`#lav-fili path.filo[data-da="${CSS.escape(f.da)}"][data-a="${CSS.escape(f.a)}"]`);
  if (!p) { x.classList.add("nascosto"); return; }
  const m = p.getPointAtLength(p.getTotalLength() / 2);
  x.style.left = m.x + "px"; x.style.top = m.y + "px";
  x.classList.remove("nascosto");
}
// I fili della gerarchia disegnata da «Tutta la catena» (26/09/2026): niente raggiera.
// pannello.json tiene dei fili solo da/a (il server scarta il resto): la forma si ricava qui, solo
// nella lavagna generale e solo quando la scheda di arrivo sta più in basso.
function formaFilo(a, b) {
  if (lavagnaAttiva === DEMO.id) return a.id === "demo-report" ? "ritorno" : "";
  if (lavagnaAttiva !== "generale" || b.y <= a.y + 40) return "";
  const testaRamo = a.tipo === "nota" ? String(a.testo || "").startsWith("📁 ") && b.tipo === "agente" && !(AGENTI.get(b.agente) || {}).capogruppo
    : !!(AGENTI.get(a.agente) || {}).capogruppo ||
    (b.tipo === "agente" && (AGENTI.get(b.agente) || {}).riporta_a === (AGENTI.get(a.agente) || {}).nome);
  if (testaRamo && b.tipo === "agente" && b.x >= a.x - 4 && b.x <= a.x + CATENA.LARG + 4) return "ramo";
  return a.tipo === "nota" ? "giu" : "";
}
// il colore di un'etichetta della catena: quello dello spazio che nomina (anche questo non si salva)
function coloreNota(n) {
  if (eDemo(n.id)) return DEMO.colori[n.id.split("-")[1]] || "";
  const t = String(n.testo || "");
  const cart = progettoDiEtichetta(t);
  if (cart) return COLORE_SPAZIO[cart.s.id] || "";
  for (const s of spaziCat || []) {
    if (t === s.nome) return COLORE_SPAZIO[s.id] || "";
    if (s.progetti.some((p) => t === p.nome + " · senza capogruppo")) return COLORE_SPAZIO[s.id] || "";
  }
  return "";
}
// «giu»: scende dal centro, corre in orizzontale poco sopra la scheda di sotto, scende sul suo centro.
// «ramo»: esce dal basso a sinistra, corre su un tronco a sinistra della colonna, entra dal lato.
function percorsoOrtogonale(forma, ra, rb) {
  if (forma === "ritorno") {        // la risposta risale lungo il lato sinistro, fuori dalla piramide
    const xt = Math.min(ra.x, rb.x) - 70;
    return `M${ra.x},${ra.cy} H${xt} V${rb.cy} H${rb.x}`;
  }
  if (forma === "ramo") {
    const xt = rb.x - 12, y0 = ra.y + ra.h;
    return `M${ra.x + 20},${y0} V${y0 + 12} H${xt} V${rb.cy} H${rb.x}`;
  }
  const ym = rb.y - 26;
  return `M${ra.cx},${ra.y + ra.h} V${ym} H${rb.cx} V${rb.y}`;
}
function etichettaNodo(n) { return n.tipo === "nota" ? "«" + (n.testo || "nota").slice(0, 30) + "»" : nomeDi(AGENTI.get(n.agente) || { key: n.agente, nome: n.agente.split(":").pop() }); }

function mettiInLavagna(k, punto) {
  let n = lav().nodi.find((x) => x.agente === k);
  if (n) { LAV.sel = n.id; LAV.selFilo = null; disegnaLavagna(); toast("È già in lavagna: l'ho evidenziato"); return; }
  const r = $("lavagna").getBoundingClientRect();
  const p = punto || puntoMondo(r.left + 30 + (lav().nodi.length % 5) * 30, r.top + 30 + (lav().nodi.length % 8) * 56);
  n = { id: "n" + Date.now().toString(36), tipo: "agente", agente: k, x: Math.round(p.x), y: Math.round(p.y) };
  lav().nodi.push(n);
  LAV.sel = n.id;
  salvaPannello(); disegnaLavagna();
}
// Apre un gruppo della colonna di sinistra nella lavagna, con capogruppo e squadra
// già disposti in gerarchia (un progetto per colonna) e collegati. Chi è già in
// lavagna non si sposta: il pulsante riporta lì e completa solo quello che manca.
function posizionaNodoSeNuovo(k, x, y) {
  if (lav().nodi.some((n) => n.agente === k)) return false;
  lav().nodi.push({ id: "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), tipo: "agente", agente: k, x, y });
  return true;
}
function collegaSeManca(daKey, aKey) {
  const nDa = lav().nodi.find((n) => n.agente === daKey), nA = lav().nodi.find((n) => n.agente === aKey);
  if (!nDa || !nA || lav().fili.some((f) => f.da === nDa.id && f.a === nA.id)) return false;
  lav().fili.push({ da: nDa.id, a: nA.id });
  return true;
}
// Dispone gli agenti di un gruppo in piramidi (una per progetto, dall'alto in
// basso: capogruppo in cima, poi la squadra su righe centrate sotto di lui),
// affiancate una accanto all'altra a partire da xIniziale. Non sposta chi è già
// in lavagna: completa solo quello che manca. Ritorna quanto spazio ha occupato
// e la chiave di ogni capogruppo di primo livello, per collegarli a un nodo sopra.
function posizionaGruppoPiramide(agentiGruppo, xIniziale, yIniziale) {
  const PER_RIGA = 5, LARG = 200, ALT = 140;
  const progetti = new Map();
  for (const a of agentiGruppo) { if (!progetti.has(a.progetto)) progetti.set(a.progetto, []); progetti.get(a.progetto).push(a); }
  let colX = xIniziale, tocco = false, altezza = ALT;
  const capiPrimoLivello = [];
  for (const lista of progetti.values()) {
    const capo = lista.find((a) => a.capogruppo);
    const specialisti = lista.filter((a) => a !== capo);
    const righe = [];
    for (let i = 0; i < specialisti.length; i += PER_RIGA) righe.push(specialisti.slice(i, i + PER_RIGA));
    const larghMax = Math.max(1, ...righe.map((r) => r.length)) * LARG;
    if (capo) { if (posizionaNodoSeNuovo(capo.key, Math.round(colX + larghMax / 2 - 88), yIniziale)) tocco = true; capiPrimoLivello.push(capo.key); }
    let yr = capo ? yIniziale + ALT : yIniziale;
    for (const riga of righe) {
      const offset = (larghMax - riga.length * LARG) / 2;
      riga.forEach((a, i) => { if (posizionaNodoSeNuovo(a.key, Math.round(colX + offset + i * LARG), yr)) tocco = true; });
      yr += ALT;
    }
    if (capo) specialisti.forEach((a) => { if (collegaSeManca(capo.key, a.key)) tocco = true; });
    else specialisti.forEach((a) => capiPrimoLivello.push(a.key));   // nessun capogruppo: ognuno si collega direttamente a chi chiama
    colX += larghMax + 60;
    altezza = Math.max(altezza, yr - yIniziale);
  }
  return { tocco, largh: colX - xIniziale, altezza, capiPrimoLivello };
}
function apriGruppoInLavagna(gid) {
  fissaGruppi();
  const g = PAN.gruppi.find((x) => x.id === gid);
  const agentiGruppo = (g ? g.agenti : []).map((k) => AGENTI.get(k)).filter(Boolean);
  if (!agentiGruppo.length) { toast("Il gruppo non ha agenti da mettere in lavagna", true); return; }
  vaiALavagna(gid, g.nome);   // la sua lavagna dedicata, non quella generale: un gruppo alla volta, non tutto mescolato
  const r = posizionaGruppoPiramide(agentiGruppo, 40, 30);
  if (r.tocco) salvaPannello();
  location.hash = "#lavagna";
  chiudiCassetti();   // 2026-10-05: sul telefono il cassetto degli agenti restava aperto sopra la lavagna
  requestAnimationFrame(() => { disegnaLavagna(); centraLavagna(); });
}
// Trova o crea una nota ferma (non entra in modifica): serve per i nodi radice
// «L'utente» e «Jarvis» che stanno sopra a tutta la catena.
function trovaOCreaNota(testo, x, y) {
  let n = lav().nodi.find((z) => z.tipo === "nota" && z.testo === testo);
  if (n) return { n, nuovo: false };
  n = { id: "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), tipo: "nota", testo, x, y };
  lav().nodi.push(n);
  return { n, nuovo: true };
}
// Con chi è collegato questo agente, guardando in TUTTE le lavagne (non solo
// quella aperta ora: un agente può stare in più gruppi). Serve a scrivere
// davvero nel suo profilo con chi si deve coordinare, appena l'utente lo collega
// a qualcuno nella lavagna — non solo un disegno, un aggiornamento vero.
function chiaviCollegate(agenteKey) {
  const trovati = new Set();
  for (const lg of Object.values(PAN.lavagne || {})) {
    const miei = new Set(lg.nodi.filter((n) => n.agente === agenteKey).map((n) => n.id));
    if (!miei.size) continue;
    for (const f of lg.fili) {
      const altroId = miei.has(f.da) ? f.a : miei.has(f.a) ? f.da : null;
      if (altroId == null) continue;
      const altro = lg.nodi.find((n) => n.id === altroId);
      if (altro && altro.tipo === "agente" && altro.agente !== agenteKey) trovati.add(altro.agente);
    }
  }
  return [...trovati];
}
async function sincronizzaComunicazioni(agenteKey) {
  if (lavDemo) return;                     // dimostrazione: i profili veri non si toccano
  const a = AGENTI.get(agenteKey);
  if (!a || !a.file) return;
  // il nome VERO del profilo, non quello da mostrare: nel «Comunica con» serve il nome del file (27/09/2026)
  const nomi = chiaviCollegate(agenteKey).map((k) => (AGENTI.get(k) || {}).nome || k.split(":").pop());
  try { await api("/api/agente-comunica", { file: a.file, comunica: nomi }); }
  catch (e) { toast("Non ho aggiornato il profilo di " + nomeDi(a) + ": " + e.message, true); }
}
// Un collegamento fatto o tolto a mano nella lavagna arriva all'utente su
// Telegram, non solo nel registro eventi: Jarvis dice cosa è cambiato.
function notificaUtente(testo) { if (!lavDemo) api("/api/notifica-utente", { testo }).catch(() => {}); }   // in dimostrazione niente Telegram
// «Tutta la catena» (rifatta il 26/09/2026, richiesta dell'utente): una piramide dall'alto in basso.
//   livello 0 l'utente · livello 1 Jarvis, con i suoi agenti di casa accanto (esecutore, ricercatore-web)
//   livello 2 i capigruppo, raggruppati per spazio sotto un'etichetta del colore dello spazio
//   sotto ogni capogruppo la sua squadra IN COLONNA (due colonne affiancate oltre le 6 schede).
// Così la larghezza resta di una dozzina di colonne e cresce l'altezza: a vista adattata i nomi si
// leggono. Solo agenti che esistono come file di profilo (da /api/catalogo); un progetto senza
// capogruppo ha in testa un'etichetta col suo nome. I fili della gerarchia sono ortogonali (formaFilo:
// «giu» scende, corre in orizzontale, scende; «ramo» è un tronco a sinistra della colonna); gli
// altri, come i «comunica con» dei profili (/api/agente-profilo), restano curvi.
const CATENA = { LARG: 212, SCHEDA: 192, PASSO: 70, PER_COLONNA: 6, GRUPPO: 56, PROGETTO: 24,
  Y_UTENTE: 0, Y_JARVIS: 110, Y_SPAZIO: 220, Y_CAPI: 330, Y_SQUADRA: 430 };
// 30/09/2026 (l'utente): la piramide è Jarvis → cartella del progetto → capogruppo → agenti. Ogni progetto ha la sua
// scheda «📁 nome» e Jarvis parla con lei. Se lo spazio ha più progetti il nome dello spazio va davanti.
function etichettaCartella(s, p) { return "📁 " + ((s.progetti || []).length > 1 && s.nome !== p.nome ? `${s.nome} · ${p.nome}` : p.nome); }
function progettoDiEtichetta(testo) {
  for (const s of spaziCat || []) for (const p of s.progetti || []) if (etichettaCartella(s, p) === testo) return { s, p };
  return null;
}
// i link di ogni scheda: cartella, memoria del vault, profilo. Non si salvano nel pannello (il server tiene solo x, y, testo):
// si ricavano dal nome della scheda ogni volta.
let MEMORIA_RADICE = "~/Jarvis-Memoria";      // da /api/spazi (chiave «memoria» di ~/.jarvis/percorsi.json)
function collegamentiNodo(n) {
  if (n.tipo === "agente") {
    const a = AGENTI.get(n.agente);
    return a && a.file ? [{ icona: "📄", titolo: "Mostra il profilo nel Finder", percorsi: [a.file] }] : [];
  }
  const t = String(n.testo || "");
  if (eNotaOrchestratore(t)) return [
    { icona: "📁", titolo: "Apri la cartella di Jarvis", percorsi: ["~/Jarvis"] },
    { icona: "🧠", titolo: "Apri la memoria (porta d'ingresso)", percorsi: [MEMORIA_RADICE + "/Comune/Memoria.md"] }];
  if (eNotaUtente(t)) return [{ icona: "🧠", titolo: "Profilo dell'utente e regole", percorsi: [MEMORIA_RADICE + "/Comune"] }];
  const pr = progettoDiEtichetta(t);
  if (pr) {
    const memo = (pr.p.sezioni_memoria || []).map((x) => MEMORIA_RADICE + "/" + x + "/Stato.md");
    return [{ icona: "📁", titolo: "Apri la cartella del progetto", percorsi: [pr.p.cartella] },
      { icona: "🧠", titolo: "Apri la memoria del progetto", percorsi: memo.concat([pr.s.memoria]) }];
  }
  return [];
}
function bottoniLink(n) {
  return collegamentiNodo(n).map((c) => el("button", { type: "button", class: "link-nodo", "data-solo-mac": "apri_cartella", title: c.titolo,
    onpointerdown: (ev) => ev.stopPropagation(),
    ondblclick: (ev) => ev.stopPropagation(),
    onclick: async (ev) => { ev.stopPropagation(); await azione({ tipo: "apri_cartella", percorsi: c.percorsi }); } }, c.icona));
}
function progettiCatena() {
  const out = [], viste = new Set();
  for (const s of spaziCat || []) {
    for (const p of s.progetti || []) {
      const ag = (p.agenti || []).map((a) => AGENTI.get(`${p.id}:${a.nome}`)).filter(Boolean);
      if (!p.esiste) continue;
      // più progetti sulla stessa cartella (3 voci, una cartella) = una scheda sola
      const chiave = s.id + "|" + p.cartella;
      if (viste.has(chiave)) continue;
      viste.add(chiave);
      if (!ag.length && s.sistema) continue;
      const capo = ag.find((a) => a.capogruppo) || null;
      out.push({ spazio: s, progetto: p, capo, squadra: ag.filter((a) => a !== capo), testo: etichettaCartella(s, p) });
    }
  }
  return out;
}
function alberoCatena() {
  const spazi = [];
  for (const s of spaziCat || []) {
    const rami = [];
    for (const p of s.progetti || []) {
      const ag = (p.agenti || []).map((a) => AGENTI.get(`${p.id}:${a.nome}`)).filter(Boolean);
      if (!ag.length && (s.sistema || !p.esiste)) continue;      // 30/09/2026: una cartella senza agenti si vede lo stesso
      const capo = ag.find((a) => a.capogruppo) || null;
      rami.push({ progetto: p, capo, squadra: ag.filter((a) => a !== capo) });
    }
    if (rami.length) spazi.push({ spazio: s, rami });
  }
  return spazi;
}
function nodoAgente(k, x, y) {
  let n = lav().nodi.find((z) => z.agente === k);
  if (!n) { n = { id: "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), tipo: "agente", agente: k, x, y }; lav().nodi.push(n); }
  n.x = Math.round(x); n.y = Math.round(y);
  return n;
}
// una nota «di servizio» della catena (l'utente, Jarvis, etichette): la ritrova dal testo e la rimette a posto
function notaCatena(testo, x, y) {
  const { n } = trovaOCreaNota(testo, x, y);
  n.x = Math.round(x); n.y = Math.round(y);
  return n;
}
function filoSeManca(da, a) {
  if (!da || !a || da.id === a.id) return;
  if (!lav().fili.some((x) => (x.da === da.id && x.a === a.id) || (x.da === a.id && x.a === da.id))) lav().fili.push({ da: da.id, a: a.id });
}
// «comunica con A, B.» dentro il blocco che scrive la lavagna nel profilo
function nomiComunica(corpo) {
  const m = String(corpo || "").match(/<!-- comunica-con:inizio[\s\S]*?comunica con ([^\n]*?)\.?\s*\n<!-- comunica-con:fine -->/);
  return m ? m[1].split(",").map((x) => x.trim()).filter(Boolean) : [];
}
async function filiDaiProfili(agenti) {
  const trovati = [];
  const coda = agenti.filter((a) => a.file);
  const lavora = async () => {
    for (let a = coda.shift(); a; a = coda.shift()) {
      try {
        const p = await api("/api/agente-profilo?file=" + encodeURIComponent(a.file));
        for (const nome of nomiComunica(p.corpo)) {
          // il nome può essere quello del profilo o quello mostrato; prima nello stesso progetto
          const tutti = [...AGENTI.values()];
          const b = tutti.find((x) => x.progetto === a.progetto && (x.nome === nome || nomeDi(x) === nome)) ||
            tutti.find((x) => x.nome === nome || nomeDi(x) === nome);
          if (b && b.key !== a.key) trovati.push([a.key, b.key]);
        }
      } catch (e) { /* profilo illeggibile: restano i fili della gerarchia */ }
    }
  };
  await Promise.all(Array.from({ length: 6 }, lavora));
  return trovati;
}
// l'ordine della squadra in colonna: ogni agente seguito da chi riporta a lui, con il suo livello
function ordinaRamo(r) {
  const capo = r.capo ? r.capo.nome : "";
  const nomi = new Set(r.squadra.map((a) => a.nome));
  const padre = (a) => (a.riporta_a && a.riporta_a !== capo && nomi.has(a.riporta_a) && a.riporta_a !== a.nome ? a.riporta_a : "");
  const out = [], visti = new Set();
  const giu = (nome, livello) => {
    for (const a of r.squadra) if (padre(a) === nome && !visti.has(a.key)) { visti.add(a.key); out.push([a, livello]); giu(a.nome, livello + 1); }
  };
  giu("", 1);
  for (const a of r.squadra) if (!visti.has(a.key)) out.push([a, 1]);           // cicli o padri spariti: al primo livello
  return out;
}
async function popolaCatenaCompleta() {
  vaiALavagna("generale", "Tutta la catena");
  const C = CATENA, L = lav();
  const rami = progettiCatena();
  if (!rami.length) { toast(SPAZI_LETTI ? testoNessunProgetto() : "Nessun progetto da mettere in lavagna: il catalogo non è ancora arrivato", !SPAZI_LETTI); return; }
  {  // le schede di servizio della catena si rifanno ogni volta: via quelle vecchie (spazi, cartelle, etichette) e i loro fili.
     // Le note scritte dall'utente restano.
    const nomiSpazio = new Set((spaziCat || []).map((s) => s.nome));
    const vecchie = new Set(L.nodi.filter((n) => n.tipo === "nota" && (String(n.testo).startsWith("📁 ") || nomiSpazio.has(n.testo) ||
      String(n.testo).endsWith(" · senza capogruppo") || n.testo === "Memoria" || eNotaUtente(n.testo) || eNotaOrchestratore(n.testo))).map((n) => n.id));
    if (vecchie.size) { L.nodi = L.nodi.filter((n) => !vecchie.has(n.id)); L.fili = L.fili.filter((f) => !vecchie.has(f.da) && !vecchie.has(f.a)); }
  }
  // via i nodi di agenti che non esistono più, e i loro fili; e tutti i fili fra schede di servizio ricalcolati
  if (AGENTI.size) {
    const via = new Set(L.nodi.filter((n) => n.tipo === "agente" && !AGENTI.has(n.agente)).map((n) => n.id));
    L.nodi = L.nodi.filter((n) => !via.has(n.id));
    L.fili = L.fili.filter((f) => !via.has(f.da) && !via.has(f.a));
  }
  const colonne = (r) => (r.squadra.length > C.PER_COLONNA ? 2 : 1);
  const largRamo = (r) => colonne(r) * C.LARG;
  // 30/09/2026 (l'utente): Memoria e Agenti di casa non c'entrano con i progetti: stanno in alto, ai lati di Jarvis,
  // sulla sua fila. I progetti veri stanno sotto, in una fila sola.
  const principali = rami.filter((r) => !r.spazio.sistema), sistema = rami.filter((r) => r.spazio.sistema);
  const totale = principali.reduce((w, r) => w + largRamo(r), 0) + C.PROGETTO * Math.max(0, principali.length - 1);
  const xCentro = totale / 2 - C.SCHEDA / 2;
  const nUtente = notaCatena(nomeUtente(), xCentro, C.Y_UTENTE);
  const nJarvis = notaCatena(etichettaOrchestratore(), xCentro, C.Y_JARVIS);
  filoSeManca(nUtente, nJarvis);
  const disegnaRamo = (r, x, yCartella) => {
    const yCapi = yCartella + 110, ySquadra = yCartella + 210;
    const cartella = notaCatena(r.testo, x, yCartella);
    filoSeManca(nJarvis, cartella);                     // Jarvis parla con la cartella di ogni progetto
    let yFiglio = yCapi;
    if (r.capo) {
      const capo = nodoAgente(r.capo.key, x, yCapi);
      filoSeManca(cartella, capo);                      // la cartella ha sotto il capogruppo
      r.testaNodo = capo; yFiglio = ySquadra;
    } else r.testaNodo = cartella;                      // senza capogruppo gli agenti stanno subito sotto la cartella
    const perColonna = Math.ceil(r.squadra.length / colonne(r)) || 1;
    const nodiRamo = new Map();
    ordinaRamo(r).forEach(([a, livello], i) => {
      const col = Math.floor(i / perColonna), riga = i % perColonna;
      const n = nodoAgente(a.key, x + col * C.LARG + (livello - 1) * 16, yFiglio + riga * C.PASSO);
      nodiRamo.set(a.nome, n);
      filoSeManca(livello > 1 ? nodiRamo.get(a.riporta_a) || r.testaNodo : r.testaNodo, n);
    });
  };
  let x = 0;
  for (const r of principali) { disegnaRamo(r, x, C.Y_SPAZIO); x += largRamo(r) + C.PROGETTO; }
  // la Memoria a sinistra di tutto, gli agenti di casa (e ogni altro gruppo di sistema) a destra
  let xDestra = totale + 80;
  for (const r of sistema) {
    if (r.progetto.id === "memoria") disegnaRamo(r, -(C.LARG + 80), C.Y_JARVIS);
    else { disegnaRamo(r, xDestra, C.Y_JARVIS); xDestra += largRamo(r) + C.PROGETTO; }
  }
  // il filo dal gruppo di sistema Memoria: la memoria è una cartella del vault come le altre, già una scheda-cartella
  salvaPannello();
  location.hash = "#lavagna";
  requestAnimationFrame(() => { disegnaLavagna(); centraLavagna(); });
  // poi i fili scritti nei profili veri (chi comunica con chi), solo dentro lo stesso progetto: niente raggiera fra gruppi
  const tutti = rami.flatMap((r) => (r.capo ? [r.capo] : []).concat(r.squadra));
  const coppie = await filiDaiProfili(tutti);
  if (lavagnaAttiva !== "generale") return;          // l'utente nel frattempo ha aperto un'altra lavagna
  const prima = lav().fili.length;
  for (const [a, b] of coppie) filoSeManca(lav().nodi.find((n) => n.agente === a), lav().nodi.find((n) => n.agente === b));
  const nuovi = lav().fili.length - prima;
  if (nuovi) { salvaPannello(); disegnaLavagna(); }
  toast(`Catena disegnata: ${tutti.length} agenti in ${rami.length} progetti, ognuno con la sua cartella` +
    (coppie.length ? ` · ${nuovi} fili nuovi dai «comunica con» dei profili` : ""));
}
function nuovaNota(p) {
  if (!p) { const r = $("lavagna").getBoundingClientRect(); p = puntoMondo(r.left + r.width / 2 - 80, r.top + r.height / 2 - 20); }
  const n = { id: "n" + Date.now().toString(36), tipo: "nota", testo: "", x: Math.round(p.x), y: Math.round(p.y) };
  lav().nodi.push(n);
  LAV.sel = n.id;
  salvaPannello(); disegnaLavagna();
  const t = document.querySelector(`.nodo[data-id="${n.id}"] .testo-nota`);
  if (t) modificaNota(t, n);
}
// ---- togliere un agente o un gruppo dalla lavagna (l'utente, 30/09/2026): «Voglio cancellare o sospendere?»
// Prima Canc toglieva solo la scheda: l'agente restava vero e «Tutta la catena» lo rimetteva.
function gruppoDaNota(n) {
  const t = String(n.testo || "");
  const cart = progettoDiEtichetta(t);
  if (cart) return { nome: cart.p.nome, progetti: cart.s.progetti.filter((q) => q.cartella === cart.p.cartella), etichetta: t };
  for (const s of spaziCat || []) if (!s.sistema && t === s.nome) return { nome: s.nome, progetti: s.progetti };
  const m = t.match(/^📁 (.+?) · nessun agente ancora$/) || t.match(/^(.+) · senza capogruppo$/);
  if (m) for (const s of spaziCat || []) for (const p of s.progetti) if (p.nome === m[1]) return { nome: p.nome, progetti: [p] };
  return null;
}
function purgaNodiAgenti(chiavi, note) {
  const k = new Set(chiavi), t = new Set(note || []);
  for (const L of Object.values(PAN.lavagne || {})) {
    const via = new Set((L.nodi || []).filter((n) => (n.tipo === "agente" && k.has(n.agente)) || (n.tipo === "nota" && t.has(n.testo))).map((n) => n.id));
    if (!via.size) continue;
    L.nodi = L.nodi.filter((n) => !via.has(n.id));
    L.fili = (L.fili || []).filter((f) => !via.has(f.da) && !via.has(f.a));
  }
  LAV.sel = null; LAV.selFilo = null; LAV.multi.clear();
  salvaPannello(); disegnaLavagna();
}
function chiediTogliMolti() {
  const nodi = [...LAV.multi].map((id) => nodoDi(id)).filter(Boolean);
  const ag = nodi.filter((n) => n.tipo === "agente" && AGENTI.has(n.agente)).map((n) => AGENTI.get(n.agente));
  const gruppi = nodi.filter((n) => n.tipo === "nota").map((n) => gruppoDaNota(n)).filter(Boolean);
  if (!ag.length && gruppi.length) return chiediTogliGruppi(gruppi);
  if (!ag.length) return false;
  const dlg = $("togli-scelta"), altri = nodi.length - ag.length;
  $("ts-definitivo").checked = false; $("ts-definitivo-riga").hidden = false;
  $("ts-titolo").textContent = `${ag.length} agenti selezionati: cancello o sospendo?`;
  $("ts-sotto").textContent = ag.slice(0, 4).map((a) => nomeDi(a)).join(", ") + (ag.length > 4 ? "…" : "") + (altri ? ` · più ${altri} schede non agente` : "");
  $("ts-sospendi-nota").textContent = "Sospendi: restano sulla lavagna, in grigio, e le missioni non li lanciano.";
  $("ts-elimina-nota").textContent = "Elimina: i profili escono da lavagna, spazi e «comunica con» degli altri. Una copia resta in _archivio, salvo «definitivo».";
  const sosp = $("ts-sospendi"), elim = $("ts-elimina"), sch = $("ts-scheda"); elim.hidden = false;
  sch.hidden = false;
  sosp.textContent = "Sospendi tutti"; elim.textContent = "Elimina tutti";
  const lega = (b, f) => { b.onclick = async () => { b.disabled = true; try { await f(b); } finally { b.disabled = false; } }; };
  lega(sch, async () => { dlg.close(); togliScelto(true); });
  lega(sosp, async (b) => {
    for (const a of ag) if (a.attivo !== false) await azione({ tipo: "agente", cosa: "attivo", progetto: a.progetto, nome: a.nome, valore: false }, b);
    dlg.close(); LAV.multi.clear(); caricaSpazi(); disegnaLavagna();
  });
  lega(elim, async (b) => {
    const def = $("ts-definitivo").checked, fatti = [];
    for (const a of ag) { const d = await azione({ tipo: "agente", cosa: def ? "elimina" : "togli", progetto: a.progetto, nome: a.nome }, b); if (d) fatti.push(a.key); }
    dlg.close(); LAV.multi.clear(); purgaNodiAgenti(fatti); caricaSpazi();
  });
  dlg.showModal();
  return true;
}
// più schede cartella scelte insieme: si sospendono o si eliminano tutti i gruppi (l'utente, 30/09/2026)
// daMenu (02/10/2026, audit P5): chiamato dal menu a sinistra, dove «Solo la scheda» non vuol dire niente
function chiediTogliGruppi(gruppi, daMenu = false) {
  const dlg = $("togli-scelta"), progetti = gruppi.flatMap((g) => g.progetti);
  const ag = progetti.flatMap((p) => (p.agenti || []).map((a) => ({ p, a })));
  $("ts-definitivo").checked = false; $("ts-definitivo-riga").hidden = true;
  $("ts-titolo").textContent = gruppi.length === 1 ? `${gruppi[0].nome}: cancello o sospendo?` : `${gruppi.length} gruppi: cancello o sospendo?`;
  $("ts-sotto").textContent = gruppi.map((g) => g.nome).join(", ") + ` · ${ag.length} agenti`;
  $("ts-sospendi-nota").textContent = "Sospendi: gli agenti restano sulla lavagna, in grigio, e le missioni non li lanciano.";
  $("ts-elimina-nota").textContent = "Elimina: i gruppi escono da spazi e lavagna, gli agenti vanno in un archivio dentro la cartella. Le cartelle e i loro file non si toccano. Si recupera da «Gruppi archiviati».";
  const sosp = $("ts-sospendi"), elim = $("ts-elimina"), sch = $("ts-scheda"); elim.hidden = false;
  sch.hidden = daMenu;
  // 2026-10-05: i gruppi di sistema (gli agenti di casa di Jarvis) stanno dentro la cartella di Jarvis: il server non li
  // archivia (togli_gruppo → 400), quindi qui si possono solo sospendere
  if (progetti.some((p) => ["casa", "agenti-jarvis"].includes(p.id))) {
    elim.hidden = true;
    $("ts-elimina-nota").textContent = "Gruppo di sistema di Jarvis: si sospende, non si elimina.";
  }
  sosp.textContent = gruppi.length === 1 ? "Sospendi" : "Sospendi i gruppi"; elim.textContent = gruppi.length === 1 ? "Elimina (archivia)" : "Elimina i gruppi";
  const lega = (b, f) => { b.onclick = async () => { b.disabled = true; try { await f(b); } finally { b.disabled = false; } }; };
  lega(sch, async () => { dlg.close(); togliScelto(true); });
  lega(sosp, async (b) => {
    for (const { p, a } of ag) if (a.attivo !== false) await azione({ tipo: "agente", cosa: "attivo", progetto: p.id, nome: a.nome, valore: false }, b);
    dlg.close(); LAV.multi.clear(); caricaSpazi(); disegnaLavagna();
  });
  lega(elim, async (b) => {
    const fatti = [];
    for (const p of progetti) { const d = await azione({ tipo: "agente", cosa: "togli_gruppo", progetto: p.id }, b); if (d) fatti.push(p.id); }
    dlg.close(); LAV.multi.clear();
    purgaNodiAgenti(ag.filter(({ p }) => fatti.includes(p.id)).map(({ p, a }) => `${p.id}:${a.nome}`),
      gruppi.flatMap((g) => [g.nome, g.etichetta, `📁 ${g.nome} · nessun agente ancora`, `${g.nome} · senza capogruppo`]).filter(Boolean));
    caricaSpazi().then(() => popolaCatenaCompleta());
  });
  dlg.showModal();
  return true;
}
function chiediTogli(n) {
  const dlg = $("togli-scelta"), agente = n.tipo === "agente" ? AGENTI.get(n.agente) : null, gr = agente ? null : gruppoDaNota(n);
  if (!agente && !gr) return false;
  const sosp = $("ts-sospendi"), elim = $("ts-elimina"), sch = $("ts-scheda"); elim.hidden = false;
  sch.hidden = false;
  $("ts-definitivo").checked = false;
  $("ts-definitivo-riga").hidden = !agente;
  const chiudi = () => dlg.close();
  const lega = (b, f) => { b.onclick = async () => { b.disabled = true; try { await f(b); } finally { b.disabled = false; } }; };
  lega(sch, async () => { chiudi(); togliScelto(true); });
  if (agente) {
    const spento = agente.attivo === false, nome = nomeDi(agente);
    $("ts-titolo").textContent = `${nome}: cancello o sospendo?`;
    $("ts-sotto").textContent = `${agente.progettoNome}${agente.capogruppo ? " · capogruppo: la squadra resta senza guida" : ""}`;
    $("ts-sospendi-nota").textContent = spento ? "Sospeso adesso: «Riattiva» lo rimette a lavorare." : "Sospendi: resta sulla lavagna, in grigio, e le missioni non lo lanciano. Lo riattivi quando vuoi.";
    $("ts-elimina-nota").textContent = "Elimina: il profilo esce dalla lavagna, dagli spazi e dai «comunica con» degli altri. Una copia resta in _archivio (recuperabile), salvo che spunti «definitivo».";
    sosp.textContent = spento ? "Riattiva" : "Sospendi"; elim.textContent = "Elimina";
    lega(sosp, async (b) => {
      const d = await azione({ tipo: "agente", cosa: "attivo", progetto: agente.progetto, nome: agente.nome, valore: spento }, b);
      if (d) { agente.attivo = spento; chiudi(); caricaSpazi(); disegnaLavagna(); }
    });
    lega(elim, async (b) => {
      const def = $("ts-definitivo").checked;
      const d = await azione({ tipo: "agente", cosa: def ? "elimina" : "togli", progetto: agente.progetto, nome: agente.nome }, b);
      if (d) { chiudi(); purgaNodiAgenti([agente.key]); caricaSpazi(); }
    });
  } else {
    $("ts-titolo").textContent = `Gruppo ${gr.nome}: cancello o sospendo?`;
    const ag = gr.progetti.flatMap((p) => (p.agenti || []).map((a) => ({ p, a })));
    $("ts-sotto").textContent = `${gr.progetti.length} progetto/i · ${ag.length} agenti`;
    $("ts-sospendi-nota").textContent = "Sospendi: tutti gli agenti del gruppo restano sulla lavagna, in grigio, e le missioni non li lanciano.";
    $("ts-elimina-nota").textContent = "Elimina: il gruppo esce dagli spazi e dalla lavagna, gli agenti vanno in un archivio dentro la cartella. La cartella e i suoi file non si toccano. Si recupera da «Gruppi archiviati».";
    sosp.textContent = "Sospendi il gruppo"; elim.textContent = "Elimina il gruppo";
    lega(sosp, async (b) => {
      for (const { p, a } of ag) if (a.attivo !== false) await azione({ tipo: "agente", cosa: "attivo", progetto: p.id, nome: a.nome, valore: false }, b);
      chiudi(); caricaSpazi(); disegnaLavagna();
    });
    lega(elim, async (b) => {
      let fatto = false;
      for (const p of gr.progetti) { const d = await azione({ tipo: "agente", cosa: "togli_gruppo", progetto: p.id }, b); fatto = !!d || fatto; }
      if (fatto) { chiudi(); purgaNodiAgenti(ag.map(({ p, a }) => `${p.id}:${a.nome}`), [gr.nome, gr.etichetta, `📁 ${gr.nome} · nessun agente ancora`, `${gr.nome} · senza capogruppo`].filter(Boolean)); caricaSpazi(); }
    });
  }
  dlg.showModal();
  return true;
}
function togliScelto(soloScheda) {
  if (!soloScheda && LAV.selFilo == null && LAV.multi.size > 1 && chiediTogliMolti()) return;
  if (!soloScheda && LAV.selFilo == null && LAV.sel) {
    const n = nodoDi(LAV.sel);
    if (n && chiediTogli(n)) return;
  }
  if (LAV.selFilo == null && LAV.multi.size > 1) {          // «Solo la scheda» con più schede scelte: via tutte
    const ids = new Set(LAV.multi);
    lav().nodi = lav().nodi.filter((n) => !ids.has(n.id));
    lav().fili = lav().fili.filter((f) => !ids.has(f.da) && !ids.has(f.a));
    LAV.multi.clear(); LAV.sel = null;
    salvaPannello(); disegnaLavagna();
    return;
  }
  const agentiDaRisincronizzare = new Set();
  const segna = (nodoId) => { const n = nodoDi(nodoId); if (n && n.tipo === "agente") agentiDaRisincronizzare.add(n.agente); };
  if (LAV.selFilo != null) {
    const f = lav().fili[LAV.selFilo];
    if (!f) { LAV.selFilo = null; disegnaLavagna(); return; }   // filo sparito nel frattempo: non si toglie un altro
    segna(f.da); segna(f.a);
    lav().fili.splice(LAV.selFilo, 1); LAV.selFilo = null;
  } else if (LAV.sel) {
    for (const f of lav().fili) if (f.da === LAV.sel || f.a === LAV.sel) { segna(f.da); segna(f.a); }
    lav().nodi = lav().nodi.filter((n) => n.id !== LAV.sel);
    lav().fili = lav().fili.filter((f) => f.da !== LAV.sel && f.a !== LAV.sel);
    LAV.sel = null;
  } else return;
  salvaPannello(); disegnaLavagna();
  for (const k of agentiDaRisincronizzare) sincronizzaComunicazioni(k);
  if (agentiDaRisincronizzare.size === 2) {
    const nomi = [...agentiDaRisincronizzare].map((k) => nomeDi(AGENTI.get(k)));
    notificaUtente(`✂️ Tolto un collegamento nella lavagna: ${nomi[0]} ↔ ${nomi[1]}. Aggiornato il profilo di entrambi.`);
  }
}
// Calamita (l'utente, 27/09/2026: «rendi più semplice allineare gli agenti»): trascinando una scheda,
// se il suo bordo sinistro, il centro o il bordo destro (e in verticale alto, centro, basso) arriva a
// 10 px da quello di un'altra scheda, si aggancia e compare una guida tratteggiata. Alt la spegne.
function calamita(n) {
  const r = rettNodo(n), soglia = 10 / (vista().zoom || 1);
  let bx = null, by = null;
  for (const o of lav().nodi) {
    if (o.id === n.id) continue;
    const q = rettNodo(o);
    for (const [mio, suo] of [[r.x, q.x], [r.cx, q.cx], [r.x + r.w, q.x + q.w], [r.x, q.x + q.w + 20], [r.x + r.w, q.x - 20]]) {
      const d = suo - mio;
      if (Math.abs(d) <= soglia && (!bx || Math.abs(d) < Math.abs(bx.d))) bx = { d, linea: suo, q };
    }
    for (const [mio, suo] of [[r.y, q.y], [r.cy, q.cy], [r.y + r.h, q.y + q.h]]) {
      const d = suo - mio;
      if (Math.abs(d) <= soglia && (!by || Math.abs(d) < Math.abs(by.d))) by = { d, linea: suo, q };
    }
  }
  if (bx) n.x = Math.round(n.x + bx.d);
  if (by) n.y = Math.round(n.y + by.d);
  const g = [];
  if (bx) { const lo = Math.min(n.y, bx.q.y) - 20, hi = Math.max(n.y + r.h, bx.q.y + bx.q.h) + 20; g.push(`M${bx.linea},${lo} V${hi}`); }
  if (by) { const lo = Math.min(n.x, by.q.x) - 20, hi = Math.max(n.x + r.w, by.q.x + by.q.w) + 20; g.push(`M${lo},${by.linea} H${hi}`); }
  guide(g);
}
function guide(tratti) {
  const svg = $("lav-fili");
  for (const p of [...svg.querySelectorAll("path.guida")]) p.remove();
  for (const d of tratti) {
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("class", "guida"); p.setAttribute("d", d);
    svg.append(p);
  }
}
// «Ordina» (rifatto il 27/09/2026): nella lavagna generale ridisegna la catena intera; in quella di un
// gruppo mette una piramide per progetto (capogruppo in cima, squadra sotto), come «Apri il gruppo».
// Prima faceva una colonna per SPAZIO, e due progetti dello stesso spazio finivano mischiati.
// I fili restano quelli che ci sono: Ordina sposta le schede, non aggiunge né toglie collegamenti.
function ordinaLavagna() {
  if (eDemo(lavagnaAttiva)) return ordinaColonne();
  if (lavagnaAttiva === "generale") return popolaCatenaCompleta();
  const L = lav(), filiPrima = L.fili.slice();
  const agenti = L.nodi.filter((n) => n.tipo === "agente" && AGENTI.has(n.agente));
  if (!agenti.length) return ordinaColonne();
  const idDi = new Map(agenti.map((n) => [n.agente, n.id]));
  L.nodi = L.nodi.filter((n) => !idDi.has(n.agente));
  const r = posizionaGruppoPiramide(agenti.map((n) => AGENTI.get(n.agente)), 40, 30);
  for (const n of L.nodi) if (idDi.has(n.agente)) n.id = idDi.get(n.agente);   // stesso id: i fili restano attaccati
  L.fili = filiPrima;
  L.nodi.filter((n) => n.tipo === "nota").forEach((n, j) => { n.x = 40 + j * 212; n.y = 30 + r.altezza + 40; });
  salvaPannello(); disegnaLavagna();
  requestAnimationFrame(centraLavagna);
}
function ordinaColonne() {
  // una colonna per spazio, capogruppo in cima; le note in fondo a destra
  const colonne = new Map();
  for (const n of lav().nodi) {
    const a = AGENTI.get(n.agente);
    const c = n.tipo === "nota" ? "~note" : a ? a.spazio : "~altro";
    if (!colonne.has(c)) colonne.set(c, []);
    colonne.get(c).push(n);
  }
  [...colonne.keys()].sort().forEach((c, i) => {
    colonne.get(c).sort((p, q) => {
      const a = AGENTI.get(p.agente) || {}, b = AGENTI.get(q.agente) || {};
      return (b.capogruppo ? 1 : 0) - (a.capogruppo ? 1 : 0) || (a.progetto || "").localeCompare(b.progetto || "") || (a.nome || "").localeCompare(b.nome || "");
    }).forEach((n, j) => { n.x = 20 + i * 220; n.y = 20 + j * 64; });
  });
  lav().vista = { x: 0, y: 0, zoom: 1 };
  salvaPannello(); disegnaLavagna();
}
// «Centra» adatta la vista al contenuto (26/09/2026): il rettangolo di tutte le schede, con le
// misure vere, sta nella tela con 40 px di margine; zoom fra 0,3 e 1. Se a 0,3 non ci sta tutto
// si parte dall'alto, centrati in orizzontale: la testa della piramide resta in vista.
function centraLavagna(salva = true) {
  if (salva instanceof Event) salva = true;   // dal pulsante «Centra»
  VISTE_DA_ADATTARE.delete(lavagnaAttiva);    // centrata a mano o da un comando: la vista ora è di questo dispositivo
  const nodi = lav().nodi;
  const r = $("lavagna").getBoundingClientRect();
  if (!nodi.length || !r.width) { lav().vista = { x: 0, y: 0, zoom: 1 }; applicaVista(); return; }
  const rr = nodi.map(rettNodo), M = 40;
  const minX = Math.min(...rr.map((q) => q.x)), maxX = Math.max(...rr.map((q) => q.x + q.w));
  const minY = Math.min(...rr.map((q) => q.y)), maxY = Math.max(...rr.map((q) => q.y + q.h));
  const w = Math.max(1, maxX - minX), h = Math.max(1, maxY - minY);
  const zoom = Math.max(.3, Math.min(1, Math.min((r.width - 2 * M) / w, (r.height - 2 * M) / h)));
  const x = (r.width - w * zoom) / 2 - minX * zoom;
  const y = h * zoom <= r.height - 2 * M ? (r.height - h * zoom) / 2 - minY * zoom : M - minY * zoom;
  lav().vista = { zoom, x, y };
  applicaVista();
  if (salva) salvaPannello();
}

// mouse e dita sulla lavagna: sposta schede, tira fili, sposta il foglio
(function lavagnaInterazioni() {
  // 🔴 Fino al 26/09/2026 questa si chiamava «lav» e nascondeva la funzione lav() (la lavagna
  // attiva): lasciando un filo su una scheda partiva «lav is not a function» e il collegamento
  // non si salvava mai. Il foglio ora si chiama «tela».
  const tela = $("lavagna");
  let gesto = null;
  tela.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    const porta = ev.target.closest(".porta"), nodo = ev.target.closest(".nodo");
    if (nodo && nodo.querySelector("[contenteditable=true]")) return;
    if (nodo && !nodo.dataset.id) return;   // Sentinella e Memoria provvisorie: solo disegno, non si spostano né collegano
    // niente setPointerCapture: sposterebbe sulla lavagna anche il clic e il doppio
    // clic, e le schede non si aprirebbero più. Movimento e rilascio si seguono sulla finestra.
    if (porta && nodo) {
      const n = nodoDi(nodo.dataset.id);
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("class", "provvisorio");
      $("lav-fili").append(p);
      gesto = { tipo: "filo", n, p };
    } else if (nodo) {
      const n = nodoDi(nodo.dataset.id), m = puntoMondo(ev.clientX, ev.clientY);
      LAV.selFilo = null;
      // Ctrl, Cmd o Maiusc + clic: la scheda entra o esce dalla selezione (30/09/2026, l'utente: spostarne tante insieme)
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
        if (LAV.sel && !LAV.multi.size) LAV.multi.add(LAV.sel);
        if (LAV.multi.has(n.id)) LAV.multi.delete(n.id); else LAV.multi.add(n.id);
        LAV.sel = LAV.multi.has(n.id) ? n.id : ([...LAV.multi].pop() || null);
        aggiornaSelezione();
        if (!LAV.multi.has(n.id)) { gesto = null; return; }
      } else if (!(LAV.multi.size > 1 && LAV.multi.has(n.id))) {
        LAV.multi.clear(); LAV.sel = n.id; aggiornaSelezione();
      } else { LAV.sel = n.id; aggiornaSelezione(); }
      document.querySelectorAll("#lav-fili path.filo.scelto").forEach((x) => x.classList.remove("scelto"));
      posaXFilo();
      $("lav-togli").disabled = false;
      const gruppo = LAV.multi.size > 1 ? [...LAV.multi].map((id) => nodoDi(id)).filter(Boolean).map((z) => ({ n: z, x0: z.x, y0: z.y,
        d: document.querySelector(`.nodo[data-id="${CSS.escape(z.id)}"]`) })) : null;
      gesto = { tipo: "nodo", n, d: nodo, dx: m.x - n.x, dy: m.y - n.y, mosso: false, gruppo, x0: n.x, y0: n.y };
    } else if (ev.ctrlKey || ev.metaKey || ev.shiftKey) {
      // Ctrl/Cmd/Maiusc + trascina sullo sfondo: riquadro di selezione
      const box = el("div", { class: "riquadro-selezione" });
      document.body.append(box);
      gesto = { tipo: "riquadro", x0: ev.clientX, y0: ev.clientY, box };
    } else {
      const v = vista();
      gesto = { tipo: "foglio", sx: ev.clientX - v.x, sy: ev.clientY - v.y, mosso: false };
      tela.classList.add("muove");
    }
    LAV.gesto = gesto;
  });
  addEventListener("pointermove", (ev) => {
    if (!gesto) return;
    if (gesto.tipo === "nodo") {
      const m = puntoMondo(ev.clientX, ev.clientY);
      gesto.n.x = Math.round(m.x - gesto.dx); gesto.n.y = Math.round(m.y - gesto.dy);
      if (gesto.gruppo) guide([]); else if (!ev.altKey) calamita(gesto.n); else guide([]);
      gesto.d.style.left = gesto.n.x + "px"; gesto.d.style.top = gesto.n.y + "px";
      if (gesto.gruppo) for (const g of gesto.gruppo) {          // tutta la selezione si muove dello stesso passo
        if (g.n === gesto.n) continue;
        g.n.x = g.x0 + (gesto.n.x - gesto.x0); g.n.y = g.y0 + (gesto.n.y - gesto.y0);
        if (g.d) { g.d.style.left = g.n.x + "px"; g.d.style.top = g.n.y + "px"; }
      }
      if (!gesto.mosso) { gesto.mosso = true; gesto.d.classList.add("trascina"); }
      disegnaFili();
    } else if (gesto.tipo === "riquadro") {
      const x = Math.min(gesto.x0, ev.clientX), y = Math.min(gesto.y0, ev.clientY);
      Object.assign(gesto.box.style, { left: x + "px", top: y + "px", width: Math.abs(ev.clientX - gesto.x0) + "px", height: Math.abs(ev.clientY - gesto.y0) + "px" });
    } else if (gesto.tipo === "foglio") {
      const v = vista();
      v.x = ev.clientX - gesto.sx; v.y = ev.clientY - gesto.sy; gesto.mosso = true;
      applicaVista();
    } else if (gesto.tipo === "filo") {
      gesto.p.setAttribute("d", curva(centroNodo(gesto.n, "uscita"), puntoMondo(ev.clientX, ev.clientY)));
      document.querySelectorAll(".nodo.bersaglio").forEach((x) => x.classList.remove("bersaglio"));
      const sotto = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".nodo");
      if (sotto && sotto.dataset.id !== gesto.n.id) sotto.classList.add("bersaglio");
    }
  });
  const fine = (ev) => {
    if (!gesto) return;
    tela.classList.remove("muove");
    if (gesto.tipo === "riquadro") {
      const r = gesto.box.getBoundingClientRect(); gesto.box.remove();
      if (r.width > 4 || r.height > 4) {
        if (LAV.sel && !LAV.multi.size) LAV.multi.add(LAV.sel);
        for (const d of document.querySelectorAll("#lav-mondo .nodo[data-id]")) {
          const q = d.getBoundingClientRect();
          if (q.left < r.right && q.right > r.left && q.top < r.bottom && q.bottom > r.top) LAV.multi.add(d.dataset.id);
        }
        LAV.sel = [...LAV.multi].pop() || null; LAV.selFilo = null;
        aggiornaSelezione();
        toast(LAV.multi.size + " schede selezionate: trascinane una per spostarle tutte, Canc per sospenderle o eliminarle");
      }
    }
    else if (gesto.tipo === "nodo") { guide([]); gesto.d.classList.remove("trascina"); if (gesto.mosso) salvaPannello(true); }
    else if (gesto.tipo === "foglio") { if (gesto.mosso) salvaPannello(); else { LAV.sel = null; LAV.selFilo = null; LAV.multi.clear(); disegnaLavagna(); } }
    else if (gesto.tipo === "filo") {
      gesto.p.remove();
      document.querySelectorAll(".nodo.bersaglio").forEach((x) => x.classList.remove("bersaglio"));
      const sotto = ev.type === "pointerup" && document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".nodo[data-id]");
      if (sotto && sotto.dataset.id !== gesto.n.id && nodoDi(sotto.dataset.id)) {
        const a = gesto.n.id, b = sotto.dataset.id;
        if (lav().fili.some((f) => f.da === a && f.a === b)) toast("Collegamento già presente");
        else {
          lav().fili.push({ da: a, a: b }); salvaPannello(true);
          const nb = nodoDi(b);
          toast(`${etichettaNodo(gesto.n)} dipende da ${etichettaNodo(nb)} · ` + (lavDemo ? "dimostrazione: i profili non si toccano" : "aggiorno i profili…"));
          if (gesto.n.tipo === "agente") sincronizzaComunicazioni(gesto.n.agente);
          if (nb && nb.tipo === "agente") sincronizzaComunicazioni(nb.agente);
          if (gesto.n.tipo === "agente" && nb && nb.tipo === "agente") {
            notificaUtente(`🔗 Collegati nella lavagna: ${etichettaNodo(gesto.n)} ↔ ${etichettaNodo(nb)}. Aggiornato il profilo di entrambi: ora sanno con chi comunicare.`);
          }
        }
        disegnaFili();
      }
    }
    gesto = null; LAV.gesto = null;
    dopoInterazione();
  };
  addEventListener("pointerup", fine);
  addEventListener("pointercancel", fine);
  tela.addEventListener("dblclick", (ev) => { if (!ev.target.closest(".nodo")) nuovaNota(puntoMondo(ev.clientX, ev.clientY)); });
  tela.addEventListener("contextmenu", (ev) => { if (ev.ctrlKey) ev.preventDefault(); });
  tela.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const v = vista(), r = tela.getBoundingClientRect();
    const z = Math.max(.2, Math.min(2.5, v.zoom * (ev.deltaY < 0 ? 1.1 : 1 / 1.1)));
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    v.x = mx - (mx - v.x) * z / v.zoom; v.y = my - (my - v.y) * z / v.zoom; v.zoom = z;
    applicaVista(); salvaPannello();
  }, { passive: false });
  tela.addEventListener("keydown", (ev) => {
    if ((ev.key === "Delete" || ev.key === "Backspace") && !ev.target.isContentEditable) { ev.preventDefault(); togliScelto(); }
  });
  // agenti trascinati dalla colonna di sinistra
  tela.addEventListener("dragover", (ev) => { if (trascinoAgente) { ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; tela.classList.add("sopra"); } });
  tela.addEventListener("dragleave", (ev) => { if (!tela.contains(ev.relatedTarget)) tela.classList.remove("sopra"); });
  tela.addEventListener("drop", (ev) => {
    ev.preventDefault(); tela.classList.remove("sopra");
    const k = ev.dataTransfer.getData("text/x-agente");
    if (k) { const p = puntoMondo(ev.clientX, ev.clientY); mettiInLavagna(k, { x: p.x - 88, y: p.y - 20 }); }
  });
  $("lav-nota").addEventListener("click", () => nuovaNota());
  $("lav-tutta-catena").addEventListener("click", popolaCatenaCompleta);
  $("lav-ordina").addEventListener("click", ordinaLavagna);
  $("lav-centra").addEventListener("click", centraLavagna);
  $("lav-togli").addEventListener("click", () => togliScelto());
})();

// ------------------------------------------------ colonna di destra: lavagna e VPS
// Lavagna e VPS non sono più un cassetto apribile a fianco: hanno solo la
// loro pagina a piena larghezza (#lavagna, #vps), raggiunta dal menu in alto.
const PANNELLI = ["lavagna", "vps", "terminale", "pc"];
function scegliPannello(quale, soloSegna = false) {
  if (!PANNELLI.includes(quale)) quale = "lavagna";
  for (const p of document.querySelectorAll(".pannello-destra")) p.classList.toggle("attivo", p.dataset.pannello === quale);
  mem.scrivi("destra", quale);
  if (quale === "lavagna") requestAnimationFrame(() => { adattaVistaSeServe(); disegnaFili(); });   // prima volta a schermo: si adatta
  if (soloSegna) return quale;   // all'avvio: niente tunnel o terminale accesi se l'utente non è su quella pagina (27/09/2026)
  if (quale === "vps") vpsApri();
  if (quale === "terminale") termApri();
  if (quale === "pc") pcwApri();
  return quale;
}
// «#computer/terminale» → «terminale» (2026-10-05: Terminale e Desktop VPS sono schede di Computer)
const pannelloAttivo = () => { const h = location.hash.slice(1); return h.startsWith("computer/") ? h.slice(9) : h; };
function chiudiCassetti() { $("app").classList.remove("lato-aperto"); }

let ultimaVista = "chat";
function paginaIntera(si) {
  $("app").classList.toggle("destra-intera", si);
  $("app").classList.toggle("senza-destra", !si);   // fuori da Lavagna/VPS la colonna destra resta sempre chiusa
  // la Lavagna/VPS a pagina intera lascia comunque lo spazio della barra in alto:
  // è una pagina come le altre, si torna indietro cliccando un'altra voce del menu.
  $("destra").style.top = si ? document.querySelector(".barra").getBoundingClientRect().height + "px" : "";
  requestAnimationFrame(disegnaFili);
}
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || document.querySelector("dialog[open]") || ev.target.isContentEditable) return;
  chiudiCassetti();
});
$("apri-lato").addEventListener("click", () => $("app").classList.add("lato-aperto"));
document.querySelector("[data-chiudi-lato]").addEventListener("click", chiudiCassetti);
$("velo").addEventListener("click", chiudiCassetti);

// ------------------------------------------------ desktop della VPS (tunnel SSH + noVNC sul Mac)
let vpsInfo = null;
// 2026-10-05 (l'utente: terminale e desktop VPS sono la stessa cosa): dal sito il desktop è noVNC sulla VPS stessa
// (servizio jarvis-desktop), servito da Caddy su /vps-desktop/ dietro il login del sito, come /term/vps/.
const VPS_DESKTOP_SITO = "/vps-desktop/vnc.html?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=3000&show_dot=1&path=vps-desktop/websockify";
async function vpsLeggi() {
  if (!PONTE.fatto) { try { await PONTE.deciso; } catch (e) { /* si va avanti come sul Mac */ } }
  if (PONTE.dentro) {
    vpsInfo = { installato: true, acceso: !(vpsInfo && vpsInfo.spento), vps: "VPS", url: VPS_DESKTOP_SITO };
    vpsDisegna();
    return vpsInfo;
  }
  try { vpsInfo = await api("/api/vps-desktop"); } catch (e) { vpsInfo = null; }
  vpsDisegna();
  return vpsInfo;
}
function vpsDisegna() {
  const s = vpsInfo, f = $("vps-frame");
  const acceso = !!(s && s.acceso);
  $("vps-pallino").className = "pallino " + (!s ? "rosso" : acceso ? "verde" : s.tunnel || s.ponte ? "giallo" : "grigio");
  $("vps-testo").textContent = !s ? "il pannello non risponde"
    : !s.installato ? "mancano websockify o noVNC sul Mac"
    : acceso ? `collegato a ${s.vps} · desktop :10` : s.tunnel || s.ponte ? "collegamento a metà" : "scollegato";
  $("vps-collega").classList.toggle("nascosto", acceso);
  $("vps-scollega").classList.toggle("nascosto", !acceso);
  $("vps-ricarica").disabled = $("vps-fuori").disabled = !acceso;
  if (acceso && f.dataset.url !== s.url) { f.src = s.url; f.dataset.url = s.url; }
  if (!acceso && f.dataset.url) { f.src = "about:blank"; f.dataset.url = ""; }
  f.classList.toggle("nascosto", !acceso);
  $("vps-vuoto").classList.toggle("nascosto", acceso);
}
async function vpsCollega(bottone) {
  if (PONTE.dentro) { vpsInfo = { installato: true, acceso: true, vps: "VPS", url: VPS_DESKTOP_SITO }; vpsDisegna(); return; }
  $("vps-testo").textContent = "apro il tunnel verso la VPS…";
  const d = await azione({ tipo: "vps_desktop", acceso: true }, bottone);
  if (d) { vpsInfo = d; vpsDisegna(); }
}
// Aprire la scheda VPS collega da solo: il tunnel è solo di questo Mac e non costa niente.
let vpsProvato = false;
async function vpsApri() {
  const s = await vpsLeggi();
  if (s && s.installato && !s.acceso && !vpsProvato) { vpsProvato = true; vpsCollega($("vps-collega")); }
}
$("vps-collega").addEventListener("click", (ev) => vpsCollega(ev.currentTarget));
$("vps-scollega").addEventListener("click", async (ev) => {
  if (PONTE.dentro) { vpsInfo = { installato: true, acceso: false, spento: true, vps: "VPS", url: VPS_DESKTOP_SITO }; vpsProvato = true; vpsDisegna(); return; }
  const d = await azione({ tipo: "vps_desktop", acceso: false }, ev.currentTarget);
  if (d) { vpsInfo = d; vpsProvato = true; vpsDisegna(); }
});
$("vps-ricarica").addEventListener("click", () => { const f = $("vps-frame"); if (vpsInfo && vpsInfo.url) f.src = vpsInfo.url; });
// «Apri fuori»: mai l'indirizzo con la password (finirebbe nella cronologia di Chrome, che si
// sincronizza fuori dal Mac). Il server dà un indirizzo monouso che vale 60 secondi.
$("vps-fuori").addEventListener("click", async (ev) => {
  if (PONTE.dentro) { window.open(VPS_DESKTOP_SITO, "_blank", "noopener"); return; }
  const w = window.open("about:blank", "_blank");    // aperta subito, dentro il clic: niente blocco dei popup
  const d = await azione({ tipo: "vps_fuori" }, ev.currentTarget);
  if (d && d.url && w) { w.opener = null; w.location.replace(d.url); } else if (w) w.close();
});
setInterval(() => { if (pannelloAttivo() === "vps" && !document.hidden) vpsLeggi(); }, 10000);

// ------------------------------------------------ PC Windows dell'amministrazione (2026-10-05, l'utente)
// Solo dal sito: Caddy porta /pc-desktop/ (noVNC → TightVNC del PC, che ascolta solo su 127.0.0.1, attraverso il ponte 2223)
// e /term/pc/ (tmux «pc»: sopra il registro dei comandi di win.sh, sotto un PowerShell sul PC). Lo schermo parte sempre
// in «solo guardare» (view_only): chi lavora al PC non si ritrova un clic arrivato per sbaglio. Sul Mac la scheda rimanda al sito.
const PCW_SCHERMO = (comanda) => `/pc-desktop/vnc.html?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=3000&show_dot=1&path=pc-desktop/websockify&view_only=${comanda ? 0 : 1}`;
let pcwVista = mem.leggi("pcwVista", "schermo") === "comandi" ? "comandi" : "schermo";
let pcwComanda = false, pcwStato = null;
async function pcwLeggi() {
  if (!PONTE.fatto) { try { await PONTE.deciso; } catch (e) { /* come sul Mac */ } }
  if (!PONTE.dentro) { pcwStato = null; pcwDisegna(); return; }
  try { pcwStato = (await fetch("/pc-desktop/vnc.html", { method: "HEAD", cache: "no-store" })).ok; } catch (e) { pcwStato = false; }
  pcwDisegna();
}
function pcwUrl(v) { return v === "comandi" ? "/term/pc/" : PCW_SCHERMO(pcwComanda); }
function pcwDisegna() {
  const dentro = PONTE.dentro;
  $("pcw-pallino").className = "pallino " + (!dentro ? "grigio" : pcwStato ? "verde" : pcwStato === false ? "rosso" : "giallo");
  $("pcw-testo").textContent = !dentro ? "si vede dal sito" : pcwStato ? "PcContabilita · attraverso il ponte" : pcwStato === false ? "il PC non risponde (spento o ponte giù)" : "collego…";
  for (const b of document.querySelectorAll("[data-pcw]")) {
    const on = b.dataset.pcw === pcwVista;
    b.classList.toggle("attivo", on); b.setAttribute("aria-selected", String(on));
  }
  $("pcw-comanda").textContent = pcwComanda ? "🖱 Comandare" : "👁 Solo guardare";
  $("pcw-comanda").classList.toggle("pericolo", pcwComanda);
  $("pcw-comanda").classList.toggle("nascosto", !dentro || pcwVista !== "schermo");
  $("pcw-ricarica").disabled = $("pcw-fuori").disabled = !dentro;
  for (const v of ["schermo", "comandi"]) {
    const f = $("pcw-frame-" + v), mostra = dentro && v === pcwVista;
    if (mostra && f.dataset.url !== pcwUrl(v)) { f.src = pcwUrl(v); f.dataset.url = pcwUrl(v); }
    f.classList.toggle("nascosto", !mostra);
  }
  $("pcw-vuoto").classList.toggle("nascosto", dentro);
}
function pcwApri() { pcwLeggi(); }
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-pcw]");
  if (!b) return;
  pcwVista = b.dataset.pcw; mem.scrivi("pcwVista", pcwVista); pcwDisegna();
});
$("pcw-comanda").addEventListener("click", () => { pcwComanda = !pcwComanda; pcwDisegna(); });
$("pcw-ricarica").addEventListener("click", () => { const f = $("pcw-frame-" + pcwVista); f.src = pcwUrl(pcwVista); f.dataset.url = f.src; pcwLeggi(); });
$("pcw-fuori").addEventListener("click", () => window.open(pcwUrl(pcwVista), "_blank", "noopener"));
setInterval(() => { if (pannelloAttivo() === "pc" && !document.hidden) pcwLeggi(); }, 15000);

// ------------------------------------------------ terminale (ttyd sul Mac, dietro il pannello)
// Due terminali, Mac e VPS, ognuno col suo iframe: passando dall'uno all'altro nessuno
// dei due si chiude. Il Mac gira dentro tmux: ricaricando la pagina ritrovi la sessione.
let termInfo = null;
let termModo = mem.leggi("termModo", "mac") === "vps" ? "vps" : "mac";
let termAccanto = !!mem.leggi("termAccanto", false);
const termFrame = (m) => $("term-frame-" + m);
// Dal sito (dentro il ponte) il terminale è quello root della VPS: /term/vps/ passa da Caddy col login del sito
// (prima stava in cima alla pagina Schermo, computer.js). La shell del Mac da lì non si apre (il ponte non porta websocket).
const TERM_PONTE = { installato: true, vps: "vps", ponte: true, modi: { mac: { acceso: false }, vps: { acceso: true, url: "/term/vps/" } } };
async function termLeggi() {
  if (!PONTE.fatto) await PONTE.deciso;
  if (PONTE.dentro) { termModo = "vps"; termInfo = TERM_PONTE; termDisegna(); return termInfo; }
  try { termInfo = await api("/api/terminale"); } catch (e) { termInfo = null; }   // porta anche il cookie di /term/
  termDisegna();
  return termInfo;
}
function termDisegna() {
  const s = termInfo, modi = (s && s.modi) || {};
  for (const b of document.querySelectorAll("[data-term]")) {
    const m = b.dataset.term, acceso = !!(modi[m] && modi[m].acceso);
    b.setAttribute("aria-selected", String(m === termModo));
    b.classList.toggle("attivo", m === termModo);
    b.querySelector(".pallino").className = "pallino " + (acceso ? "verde" : "grigio");
  }
  const acceso = !!(modi[termModo] && modi[termModo].acceso);
  for (const m of ["mac", "vps"]) {
    const f = termFrame(m), on = !!(modi[m] && modi[m].acceso);
    if (on && f.dataset.url !== modi[m].url) { f.src = modi[m].url; f.dataset.url = modi[m].url; }
    if (!on && f.dataset.url) { f.src = "about:blank"; f.dataset.url = ""; }
    f.classList.toggle("nascosto", !(on && m === termModo));
  }
  $("term-testo").textContent = !s ? "il pannello non risponde"
    : !s.installato ? "manca ttyd sul Mac (brew install ttyd)"
    : acceso ? (termModo === "mac" ? "shell del Mac · tmux, la sessione resta" : s.ponte ? "root sulla VPS · dal sito" : `ssh ${s.vps} · dal Mac, in uscita`)
    : "spento";
  $("term-vuoto").classList.toggle("nascosto", acceso);
  $("term-vuoto-titolo").textContent = termModo === "mac" ? "Terminale del Mac" : "Terminale della VPS";
  $("term-vuoto-testo").replaceChildren(...(termModo === "mac"
    ? ["Una shell vera: ci lanci ", el("code", {}, "claude"), " con tutte le skill, ", el("code", {}, "git"), ", gli script di Jarvis."]
    : ["Una sessione ", el("code", {}, "ssh " + ((s && s.vps) || "vps")), " aperta dal Mac: sulla VPS non si installa e non si apre niente."]));
  $("term-accendi").classList.toggle("nascosto", acceso);
  $("term-spegni").classList.toggle("nascosto", !acceso);
  $("term-sessione").classList.toggle("nascosto", termModo !== "mac");
  $("term-ricarica").disabled = $("term-fuori").disabled = $("term-claude").disabled = !acceso;
}
let TERM_CONFERMATO = false;
async function termAccendi(bottone, modo = termModo) {
  if (!TERM_CONFERMATO && !confirm(modo === "mac"
    ? "Accendo una shell vera del Mac dentro il pannello (ttyd, solo su questo Mac, protetta dal token della pagina). Procedo?"
    : "Apro una sessione ssh verso la VPS dentro il pannello. Procedo?")) return;
  TERM_CONFERMATO = true;
  $("term-testo").textContent = modo === "mac" ? "accendo la shell del Mac…" : "apro ssh verso la VPS…";
  const d = await azione({ tipo: "terminale", cosa: "avvia", modo }, bottone);
  if (d) await termLeggi();
  if (d) setTimeout(() => termFocus(), 600);
}
function termFocus() { try { const f = termFrame(termModo); f.focus(); f.contentWindow && f.contentWindow.focus(); } catch (e) { /* niente */ } }
function termScegli(m) {
  termModo = m; mem.scrivi("termModo", m);
  termDisegna();
  const modi = (termInfo && termInfo.modi) || {};
  if (modi[m] && modi[m].acceso) termFocus();      // spento: resta spento finché non premi «Accendi» (con conferma)
}
// Aprire il pannello NON accende il terminale (prodotto pubblico, 2026-10-10): si accende solo da «Accendi».
async function termApri() {
  const s = await termLeggi();
  const modi = (s && s.modi) || {};
  // 2026-10-10 (prodotto pubblico): aprire la pagina non accende niente. Il terminale parte solo da «Accendi», con conferma.
  if (modi[termModo] && modi[termModo].acceso) termFocus();
}
// scrive un comando nel terminale come se lo battesse l'utente (stessa origine: si può)
function termScrivi(testo) {
  try {
    const w = termFrame(termModo).contentWindow;
    // input() come se fosse battuto (paste() lo manderebbe «incollato» e l'Invio non partirebbe)
    if (w && w.term && w.term.input) { w.term.input(testo, true); w.term.focus(); return true; }
  } catch (e) { /* niente */ }
  navigator.clipboard.writeText(testo).then(() => toast("Copiato: incollalo nel terminale"));
  return false;
}
function terminaleAccanto(si) {
  const largo = matchMedia("(min-width: 1100px)").matches;
  $("app").classList.toggle("con-terminale", si && largo);
  $("btn-term-accanto").setAttribute("aria-pressed", String(si));
  $("btn-term-accanto").classList.toggle("attivo", si);
  if (si && largo) { $("app").classList.remove("senza-destra"); scegliPannello("terminale"); }
  else $("app").classList.add("senza-destra");      // fuori dalle pagine intere la colonna destra resta chiusa
}
for (const b of document.querySelectorAll("[data-term]")) b.addEventListener("click", () => termScegli(b.dataset.term));
$("term-accendi").addEventListener("click", (ev) => termAccendi(ev.currentTarget));
$("term-accendi-grande").addEventListener("click", (ev) => termAccendi(ev.currentTarget));
$("term-spegni").addEventListener("click", async (ev) => {
  const d = await azione({ tipo: "terminale", cosa: "ferma", modo: termModo }, ev.currentTarget);
  if (d) { termInfo = d; termDisegna(); }
});
$("term-sessione").addEventListener("click", async (ev) => {
  if (!confirm("Chiudere la sessione del terminale del Mac?\n\nTutto quello che gira dentro (anche un claude aperto) si chiude.")) return;
  const d = await azione({ tipo: "terminale", cosa: "chiudi_sessione" }, ev.currentTarget);
  if (d) { termInfo = d; termDisegna(); }
});
$("term-ricarica").addEventListener("click", () => { const f = termFrame(termModo); if (f.dataset.url) f.src = f.dataset.url; });
$("term-fuori").addEventListener("click", () => { const f = termFrame(termModo); if (f.dataset.url) window.open(f.dataset.url, "_blank", "noopener"); });
$("term-claude").addEventListener("click", () => termScrivi("claude\r"));
$("btn-term-accanto").addEventListener("click", () => {
  if (!matchMedia("(min-width: 1100px)").matches) { location.hash = "#computer/terminale"; return; }
  termAccanto = !termAccanto; mem.scrivi("termAccanto", termAccanto);
  terminaleAccanto(termAccanto);
  requestAnimationFrame(disegnaFili);
});
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-term-vai]");
  if (!b) return;
  termModo = b.dataset.termVai; mem.scrivi("termModo", termModo);
  if (location.hash === "#computer/terminale") { termScegli(termModo); return; }   // già lì: l'hash non cambia, si cambia a mano
  location.hash = "#computer/terminale";
});
setInterval(() => { if ((pannelloAttivo() === "terminale" || $("app").classList.contains("con-terminale")) && !document.hidden) termLeggi(); }, 10000);

// ------------------------------------------------ sezioni (dall'indirizzo: #chat, #missioni, #lavagna…)
const TITOLI = { chat: "Chat", home: "Stato", agenti: "Squadra", missioni: "Missioni", scadenze: "Scadenze", telefono: "Telefono",
  memoria: "Memoria", lavagna: "Lavagna", computer: "Computer" };
// 2026-10-05 (l'utente): da 17 a 13 voci. I vecchi indirizzi portano alla pagina nuova, sulla scheda giusta.
const VECCHI_INDIRIZZI = { schermo: "computer/schermo", terminale: "computer/terminale", vps: "computer/vps",
  server: "computer/server", tecnico: "telefono/android" };
const SCHEDE_PC = ["schermo", "terminale", "vps", "pc", "server"];
const NOMI_SCHEDE_PC = { schermo: "Schermo del Mac", terminale: "Terminale", vps: "Desktop VPS", pc: "PC Windows", server: "Server" };
function pcSchedaVisibile(scheda) {
  const b = document.querySelector(`#pc-schede [data-scheda="${scheda}"]`);
  return !!b && getComputedStyle(b).display !== "none";
}
// la scheda scelta da sola per un «#computer» senza scheda: si può ancora cambiare quando computer.js porta lo Schermo
let pcSchedaAuto = null;
function pcRivedi() {
  if (!pcSchedaAuto || location.hash !== "#computer/" + pcSchedaAuto) return false;
  history.replaceState(null, "", "#computer");
  mostraVista();
  return true;
}
function pcSchedaPredefinita() {
  const m = mem.leggi("pcScheda", "");
  if (SCHEDE_PC.includes(m) && pcSchedaVisibile(m)) return m;
  return pcSchedaVisibile("schermo") ? "schermo" : "terminale";
}
// la barra delle schede è una sola: sta in cima alla vista Computer (Schermo, Server) o al pannello a pagina intera (Terminale, Desktop VPS)
function pcSchede(scheda) {
  const nav = $("pc-schede");
  if (!nav) return;
  nav.hidden = !scheda;
  for (const b of nav.querySelectorAll("[data-scheda]")) {
    const on = b.dataset.scheda === scheda;
    b.classList.toggle("attivo", on);
    b.setAttribute("aria-selected", String(on));
  }
  if (!scheda) return;
  const vista = document.querySelector('.vista[data-vista="computer"]');
  for (const x of vista.querySelectorAll(":scope > .pc-scheda")) x.classList.toggle("scheda-on", x.dataset.scheda === scheda);
  const casa = PANNELLI.includes(scheda) ? document.querySelector(`.pannello-destra[data-pannello="${scheda}"]`) : vista;
  if (casa && casa.firstElementChild !== nav) casa.prepend(nav);
}
document.getElementById("pc-schede")?.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-scheda]");
  if (b) location.hash = "#computer/" + b.dataset.scheda;
});
function mostraVista() {
  // #lavori era una scheda a sé fino al 26/09/2026: i vecchi segnalibri portano ai lavori dentro la Squadra
  if (location.hash === "#lavori") {
    history.replaceState(null, "", "#agenti");
    requestAnimationFrame(() => $("blocco-lavori").scrollIntoView({ block: "start" }));
  }
  // l'app «Jarvis Assistenza» sulla scrivania apre #assistenza-tecnico: è un riquadro della vista Stato
  if (location.hash === "#assistenza-tecnico") {
    history.replaceState(null, "", "#home");
    window.tecScorri = true;              // ci scorre tecDisegna, quando il riquadro è visibile
    if (!$("assistenza-tecnico").classList.contains("nascosto")) tecDisegnaScorri();
  }
  let [base, sotto] = (location.hash || "#chat").slice(1).split("/");
  if (VECCHI_INDIRIZZI[base] && !sotto) {
    [base, sotto] = VECCHI_INDIRIZZI[base].split("/");
    history.replaceState(null, "", "#" + base + "/" + sotto);
  }
  let scheda = null;
  if (base === "computer") {
    const esplicita = SCHEDE_PC.includes(sotto);
    scheda = esplicita ? sotto : pcSchedaPredefinita();
    // dal sito senza «tutto» il desktop della VPS non funziona (GET bloccati): si apre lo stato della VPS
    if (ponteRistretto() && PONTE_VISTE_MAC.includes(scheda)) scheda = "server";
    if (location.hash !== "#computer/" + scheda) history.replaceState(null, "", "#computer/" + scheda);
    if (esplicita) mem.scrivi("pcScheda", scheda); else pcSchedaAuto = scheda;
  }
  const nome = TITOLI[base] ? base : "chat";
  const intera = nome === "lavagna" || PANNELLI.includes(scheda);
  if (!intera) ultimaVista = nome;
  for (const s of document.querySelectorAll(".vista")) s.classList.toggle("attiva", s.dataset.vista === ultimaVista);
  for (const a of document.querySelectorAll(".menu a")) a.classList.toggle("attiva", a.dataset.vista === nome);
  pcSchede(scheda);
  $("vista-titolo").textContent = TITOLI[nome];
  document.title = `${scheda ? NOMI_SCHEDE_PC[scheda] : TITOLI[nome]} · Jarvis`;
  document.body.classList.remove("modo-tecnico");
  if (intera) { $("app").classList.remove("con-terminale"); scegliPannello(scheda || nome); paginaIntera(true); return; }
  paginaIntera(false);
  terminaleAccanto(nome === "chat" && termAccanto);
  // il banco di collaudo dell'app Android (ex «Tecnico») sta in fondo alla pagina Telefono
  if (nome === "telefono" && !ponteRistretto()) caricaTecnico();
  if (nome === "telefono" && sotto === "android") requestAnimationFrame(() => $("telefono-android").scrollIntoView({ block: "start" }));
  if (nome === "chat") { disegnaMessaggi(); aggiornaInvia(); }
}
// dopo che ponte.js ha deciso (e messo «dentro-ponte», «ponte-tutto»): le schede di Computer possibili cambiano
PONTE.deciso.then(() => { if (/^#(computer|vps|schermo)/.test(location.hash) && !pcRivedi()) mostraVista(); });
window.addEventListener("hashchange", () => { pcSchedaAuto = null; mostraVista(); $("app").querySelector("main").scrollTop = 0; });

// ------------------------------------------------ motore (26/09/2026)
// Quale motore risponde alla chat: Claude Code, Gemini, Cursor, Codex. Dal 26/09/2026 sera il
// server lancia davvero quello scelto (comando_motore in server.py) e la chiedi porta il campo
// «motore». Un motore installato ma senza login resta spento, col motivo nel title. Stato in
// comune con la bolla del widget desktop, via /api/motore — un solo file, non duplicarlo qui.
async function caricaMotore() {
  const stato = await api("/api/motore");
  MOTORE.attivo = stato.attivo;
  const elenco = $("motore-elenco");
  elenco.innerHTML = "";
  for (const m of stato.motori) {
    MOTORE.nomi[m.id] = m.nome;
    const nota = m.pronto ? "" : m.installato === false ? "da installare" : "login mancante";
    elenco.append(el("button", {
      class: "motore-voce" + (m.id === stato.attivo ? " attivo" : ""), "data-solo-mac": "/api/motore",
      disabled: !m.pronto,
      title: m.pronto ? "" : (m.motivo || nota),
      onclick: () => sceltaMotore(m.id),
    },
      el("span", { class: "pallino " + (m.id === stato.attivo ? "verde" : "grigio") }),
      el("span", {}, m.nome),
      el("small", {}, nota),
    ));
  }
  disegnaModoChat(modoChat);        // la nota del modo, la testa della chat e il benvenuto dicono il motore
}
async function sceltaMotore(id) {
  try {
    await api("/api/motore", { motore: id });
    await caricaMotore();
    toast("Risponde " + nomeMotore(id));
  } catch (e) { toast(e.message, true); }
}

// Alle 17:13 del 26/09/2026 è partita una chat con Jarvis il cui testo era la lista degli Eventi
// («sentinella · rientrata: …», l'ora su una riga a parte come nella lista): un pezzo di lista
// trascinato nel campo della chat e mandato. Le righe degli Eventi non si trascinano più; copiarle
// con Cmd-C resta possibile.
$("eventi").addEventListener("dragstart", (ev) => ev.preventDefault());

// ------------------------------------------------ avvio
scegliPannello(mem.leggi("destra", "lavagna"), true);   // la scheda lasciata aperta l'ultima volta, fra Lavagna e VPS
aggiornaTestaChat();
mostraVista();
orologio();
setInterval(orologio, 1000);
caricaSpazi();       // 2026-10-10: nomi dal profilo, stato vuoto, lavagna; il catalogo da solo non bastava
catalogo().then(() => { disegnaGruppi(); aggiornaTestaChat(); disegnaMessaggi(); caricaModifiche(); return caricaPannello(); })
  .catch((e) => toast(e.message, true));
caricaMotore().catch((e) => toast(e.message, true));
// I giri di lettura: veloci con la pagina davanti, quasi fermi con la scheda nascosta (prima
// giravano sempre, anche in background). Tornando visibile si rilegge subito.
// «visibile» può essere una funzione: il ritmo di aggiorna() cambia col flusso (qui sotto).
function ogni(fn, visibile, nascosta) {
  let timer = null;
  const giro = async () => {
    clearTimeout(timer);
    try { await fn(); } catch (e) { /* il giro dopo riprova */ }
    finally {
      clearTimeout(timer);
      timer = setTimeout(giro, document.hidden ? nascosta : typeof visibile === "function" ? visibile() : visibile);
    }
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) giro(); });
  giro();
}

// ------------------------------------------------ tempo reale (contratto, punto 1, 26/09/2026)
// Il server manda un evento a ogni cambio di stato su /api/flusso (Server-Sent Events): la pagina
// rilegge /api/stato subito, con 300 ms di attesa per raccogliere gli eventi vicini. Con il flusso
// vivo il sondaggio scende a uno ogni 15 s (rete di sicurezza); se il flusso cade resta a 15 s e
// si ricollega con attesa crescente, da 2 a 30 s. Il server vecchio non ha /api/flusso (404):
// allora resta il sondaggio di prima, ogni 4 s. EventSource non manda intestazioni: il token va
// nell'indirizzo, e il server lo accetta solo lì.
const FLUSSO = { stato: "sondaggio", es: null, versione: null, attesa: 2000, timer: null, rimbalzo: null, provato: false,
  sa: [], sospese: new Set() };
// Chiavi del flusso che non toccano /api/stato: da sole non fanno rileggere lo stato (2026-10-03). Una chiave
// che non sta qui (anche nuova o sconosciuta) lo fa rileggere come prima.
const CHIAVI_NON_STATO = new Set(["scadenze", "spazi", "modifiche", "pannello", "attivita", "frequenti", "approvazione", "fili", "chat_voce",
  "file_progetti", "diari"]);
// Le chiavi arrivate con la scheda nascosta (2026-10-03): niente letture finché nessuno guarda; tornando
// visibile si fanno una volta sola (aggiorna() riparte comunque dal giro di ogni()).
function trattaChiavi(chiavi, senzaStato = false) {
  if (document.hidden) { for (const k of chiavi) FLUSSO.sospese.add(k); if (!chiavi.length) FLUSSO.sospese.add("stato"); return; }
  if (chiavi.includes("scadenze")) caricaScadenze();
  if (chiavi.includes("spazi")) caricaSpazi();
  if (chiavi.includes("modifiche")) caricaModifiche();
  if (chiavi.includes("pannello")) { aggiornaAllineamento(); ricaricaSeCambiato(); }
  if (chiavi.includes("attivita")) {            // una riga nuova nel registro delle attività
    caricaSommarioAttivita();
    if ($("scheda-agente").open && schedaKey) caricaAttivita(schedaKey);
  }
  if (chiavi.includes("chat_voce")) aggiornaChatVoce();
  // 2026-10-10: file caricati e diari cambiati (anche fuori dalla pagina): le schede aperte si rileggono da sole
  if (chiavi.some((k) => k === "file_progetti" || k === "diari" || k === "spazi")) {
    if ($("scheda-progetto").open && SP_ID) caricaFileProgetto();
    if ($("scheda-agente").open && schedaKey) caricaDiario(schedaKey);
  }
  if (!senzaStato && (!chiavi.length || chiavi.some((k) => !CHIAVI_NON_STATO.has(k)))) chiediAggiorna();
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden || !FLUSSO.sospese.size) return;
  const chiavi = [...FLUSSO.sospese].filter((k) => k !== "stato");
  FLUSSO.sospese.clear();
  trattaChiavi(chiavi, true);   // lo stato no: lo rilegge già il giro di ogni() appena la scheda torna visibile
});
let ritmoAggiorna = 4000;
function flussoSegna(stato) {
  FLUSSO.stato = stato;
  const n = $("flusso"), vivo = stato === "live";
  n.textContent = vivo ? "● live" : "○ sondaggio";
  n.className = "flusso" + (vivo ? " vivo" : "");
  n.title = vivo ? "Aggiornamenti in tempo reale dal server"
    : stato === "assente" ? "Il server non ha il flusso in tempo reale: rileggo lo stato ogni 4 s"
    : "Flusso in tempo reale caduto: rileggo ogni 15 s e riprovo a collegarmi";
}
function chiediAggiorna() {
  clearTimeout(FLUSSO.rimbalzo);
  FLUSSO.rimbalzo = setTimeout(() => aggiorna(true), 300);
}
async function flussoApri() {
  if (FLUSSO.es || FLUSSO.stato === "assente") return;
  if (!("EventSource" in window)) { flussoSegna("assente"); return; }
  const url = "/api/flusso?token=" + encodeURIComponent(window.CC_TOKEN);
  // EventSource non dice il codice di risposta: una prova sola, all'avvio, per riconoscere il 404
  if (!FLUSSO.provato) {
    FLUSSO.provato = true;
    const ctl = new AbortController();
    const tetto = setTimeout(() => ctl.abort(), 5000);
    try {
      const r = await fetch(url, { headers: { "X-Token": window.CC_TOKEN }, signal: ctl.signal, cache: "no-store" });
      if (r.status === 404) { flussoSegna("assente"); return; }
    } catch (e) { /* rete giù o prova troppo lenta: ci pensa la riconnessione */ }
    finally { clearTimeout(tetto); ctl.abort(); }
  }
  const es = new EventSource(url);
  FLUSSO.es = es;
  es.onopen = () => { FLUSSO.attesa = 2000; ritmoAggiorna = 15000; flussoSegna("live"); SCAD.letto = 0; chiediAggiorna(); };
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (Array.isArray(d.sa)) FLUSSO.sa = d.sa;            // il primo messaggio dice cosa sa fare il server
    if (d.versione != null && d.versione === FLUSSO.versione) return;
    if (d.versione != null) FLUSSO.versione = d.versione;
    const chiavi = d.chiavi || [];
    if (!document.hidden && chiavi.length && d.stato && typeof d.stato === "object" && chiavi.every((k) => k in d.stato) && applicaSpinta(d)) return;
    trattaChiavi(chiavi);
  };
  es.onerror = () => {
    es.close();
    FLUSSO.es = null;
    ritmoAggiorna = 15000;
    flussoSegna("caduto");
    clearTimeout(FLUSSO.timer);
    FLUSSO.timer = setTimeout(flussoApri, FLUSSO.attesa);
    FLUSSO.attesa = Math.min(30000, FLUSSO.attesa * 2);
  };
}

ogni(aggiorna, () => ritmoAggiorna, 60000);
// rete di sicurezza se il flusso cade (audit 02/10/2026); col flusso vivo il cambio arriva con «pannello» (2026-10-03)
ogni(ricaricaSeCambiato, () => (FLUSSO.stato === "live" ? 60000 : 15000), 60000);
flussoApri();
caricaSommarioAttivita();
ogni(caricaSommarioAttivita, 60000, 5 * 60000);   // anche senza flusso: le «senza risposta» scadono col tempo
ogni(seguiRisposte, 1500, 15000);           // una risposta che arriva a scheda nascosta si prende lo stesso
// la chat a voce: col flusso vivo e un server che avvisa «chat_voce» (2026-10-03) si rilegge all'avviso, con un
// giro di sicurezza ogni 15 s; altrimenti ogni 2 s come prima
ogni(aggiornaChatVoce, () => (FLUSSO.stato === "live" && FLUSSO.sa.includes("chat_voce") ? 15000 : 2000), 5 * 60000);
addEventListener("resize", () => requestAnimationFrame(disegnaFili));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

// ✕ delle schede (27/09/2026): ora sono type="button", così Invio salva invece di chiudere e perdere tutto
document.addEventListener("click", (ev) => {
  const x = ev.target.closest("dialog .chiudi-dialog");
  if (x) x.closest("dialog").close("chiudi");
});
$("sa-comunica-nuovo").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); $("sa-comunica-aggiungi").click(); }
});
$("esito-chiudi").addEventListener("click", () => $("esito-box").classList.add("nascosto"));

// «Togli gruppo» archivia un progetto intero: da qui si riporta indietro (27/09/2026, prima non c'era modo)
function disegnaGruppiArchiviati(lista) {
  const box = $("gruppi-archiviati");
  if (!Array.isArray(lista) || !lista.length) { box.classList.add("nascosto"); return; }
  box.classList.remove("nascosto");
  box.querySelector("summary").textContent = `Gruppi archiviati (${lista.length})`;
  $("gruppi-archiviati-lista").replaceChildren(...lista.map((g) => el("li", {},
    el("span", { title: g.archivio_mancante ? "La cartella _archivio-… con gli agenti non c'è più: si può solo eliminare" : "" },
      (g.archivio_mancante ? "⚠ " : "") + (g.nome || g.progetto)), " ",
    el("span", { class: "azioni-archiviato" },
      el("button", { type: "button", class: "piccolo", "data-solo-mac": "agente:ripristina_gruppo", title: g.archivio_mancante ? "L'archivio degli agenti non c'è più: non si può ripristinare" : "Rimette progetto e agenti com'erano",
        disabled: g.archivio_mancante ? "" : null,
        onclick: async (ev) => {
          if (!confirm(`Ripristinare il gruppo ${g.nome || g.progetto}? Profili e voce negli spazi tornano com'erano.`)) return;
          const d = await azione({ tipo: "agente", cosa: "ripristina_gruppo", progetto: g.progetto }, ev.currentTarget);
          if (d) caricaSpazi();
        } }, "Ripristina"),
      // 02/10/2026 (l'utente, audit P6): cancellazione vera, con anteprima e il nome scritto a mano. L'archivio va nel Cestino del Mac.
      el("button", { type: "button", class: "piccolo pericolo", "data-solo-mac": "agente:anteprima_elimina_gruppo", title: "Cancella la voce e l'archivio degli agenti (nel Cestino del Mac): la cartella del progetto e la memoria restano",
        onclick: (ev) => eliminaGruppoArchiviato(g, ev.currentTarget) }, "Elimina definitivamente")))));
}
async function eliminaGruppoArchiviato(g, b) {
  const p = await azione({ tipo: "agente", cosa: "anteprima_elimina_gruppo", progetto: g.progetto }, b);
  if (!p) return;
  const elenco = p.file.length ? p.file.slice(0, 15).map((f) => "    · " + f).join("\n") + (p.file.length > 15 ? `\n    … e altri ${p.file.length - 15}` : "") : "    (nessun file)";
  const testo = `Eliminare DEFINITIVAMENTE il gruppo ${p.nome}?\n\nSparisce:\n  · la voce in «Gruppi archiviati» (non si ripristina più)\n` +
    (p.archivio ? `  · la cartella ${p.archivio.split("/").pop()} → Cestino del Mac:\n${elenco}\n` : p.archivio_mancante ? "  · (l'archivio degli agenti non c'era già più)\n" : "") +
    (p.tombe.length ? `  · le tombe di ${p.tombe.join(", ")} (il CEO potrà riproporli)\n` : "") +
    "  · le schede rimaste sulle lavagne\n" +
    `\nResta com'è:\n${p.restano.map((x) => "  · " + x).join("\n")}\n  · report e storico delle modifiche\n\nPer confermare scrivi il nome del gruppo:`;
  const scritto = prompt(testo, "");
  if (scritto == null) return;
  if (scritto.trim() !== p.nome) { toast(`Nome diverso da «${p.nome}»: non ho eliminato niente`, true); return; }
  const d = await azione({ tipo: "agente", cosa: "elimina_gruppo", progetto: g.progetto, conferma: scritto }, b);
  if (d) caricaSpazi();
}

// ------------------------------------------------ Assistenza a distanza a pagamento (2026-09-29)
// Spenta di default: se /api/assistenza/stato dice abilitata:false non si vede niente.
// Con una sessione attiva il banner resta in cima a tutte le pagine, con il tempo e il tasto Ferma.
const assist = { abilitata: false, d: null, scarto: 0 };

function assistEuro(n) {
  return Number(n || 0).toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}
function assistOre(sec) {
  sec = Math.max(0, Math.floor(sec));
  return [Math.floor(sec / 3600), Math.floor(sec / 60) % 60, sec % 60].map((x) => String(x).padStart(2, "0")).join(":");
}

function assistDisegna(d) {
  assist.d = d;
  assist.abilitata = d && d.abilitata === true;
  $("box-assistenza").classList.toggle("nascosto", !assist.abilitata);
  const a = assist.abilitata ? d.attiva : null;
  $("assist-banner").classList.toggle("nascosto", !a);
  if (!assist.abilitata) return;
  assist.scarto = Date.now() / 1000 - (d.ora_ts || Date.now() / 1000);
  const c = d.condizioni || {};
  $("assist-banner-chi").textContent = "Il tecnico può usare il terminale";
  // 2026-10-02 (l'utente): al cliente una sola riga di condizioni; la regola è a blocchi da 15 anticipati
  $("assist-condizioni").replaceChildren(
    el("li", {}, `Ogni sessione scala subito i primi ${c.primo_blocco_minuti} minuti.`));
  // 30/09/2026: dati del conto, email e telefono del tecnico non stanno nella pagina: arrivano solo dopo la scelta delle ore
  const sel = $("assist-ore"), massimo = d.ore_max || 8;
  if (sel.options.length !== massimo) {
    const prima = sel.value || "1";
    sel.replaceChildren(...Array.from({ length: massimo }, (_, i) => el("option", { value: String(i + 1) }, `${i + 1} ${i ? "ore" : "ora"}`)));
    sel.value = prima;
  }
  assistTotale();
  $("assist-ordina").disabled = !d.pagamento_pronto;
  $("assist-ordina").title = d.pagamento_pronto ? "" : "Il pagamento non è ancora configurato su questo computer";
  $("assist-saldo").textContent = `${d.credito_min} minuti`;
  $("assist-saldo-euro").textContent = `≈ ${assistEuro(d.credito_euro)}`;
  $("assist-avvio").classList.toggle("nascosto", !!a);
  $("assist-sessione").classList.toggle("nascosto", !a);
  $("assist-avvia").disabled = !$("assist-consenso").checked;
  const minimo = c.primo_blocco_minuti || 15;
  let avviso = "";
  // 2026-10-02: d.collegamento = «tunnel» (sulla VPS) o «tmate» (ripiego); d.tmate = c'è almeno un modo
  if (!d.tmate) avviso = "Manca il modo di collegarsi: il tunnel non è configurato e tmate non c'è (brew install tmate).";
  else if (!a && d.credito_min < minimo) avviso = `Per chiedere assistenza servono almeno ${minimo} minuti di credito.`;
  if (a && a.ultimo_blocco) avviso = "Credito finito: la sessione si chiude alla fine del blocco già pagato.";
  $("assist-avviso").textContent = avviso;
  if (a) {
    $("assist-ssh").textContent = a.ssh || "";
    const tunnel = a.modo === "tunnel";
    $("assist-collegamento").textContent = tunnel
      ? (a.collegato ? `Tunnel sicuro attivo sul server di Jarvis (porta ${a.porta}): il tecnico può entrare.`
        : "In attesa: il tunnel parte appena il tecnico apre la tua richiesta. Se in 15 minuti non succede, la sessione si chiude e i minuti tornano a credito.")
      : "Collegamento con tmate (terminale condiviso su tmate.io).";
    $("assist-guarda").textContent = a.guarda || "";
    $("assist-guarda-box").classList.toggle("nascosto", !(tunnel && a.guarda));
    $("assist-banner-chi").textContent = tunnel && !a.collegato ? "In attesa del tecnico" : "Il tecnico può usare il terminale";
    $("assist-tempo").textContent = `Iniziata alle ${String(a.ora_inizio || "").slice(11, 16)} · pagati ${a.minuti_pagati} minuti in ${a.blocchi} ${a.blocchi === 1 ? "blocco" : "blocchi"}`;
  }
  $("assist-log").replaceChildren(...(d.log || []).slice(0, 12).map((x) => el("li", {}, `${x.ora}  ${x.testo}`)));
  assistOrologio();
}

function assistOrologio() {
  const a = assist.abilitata && assist.d ? assist.d.attiva : null;
  if (!a) return;
  const ora = Date.now() / 1000 - assist.scarto;
  $("assist-banner-tempo").textContent = assistOre(ora - a.inizio);
}
setInterval(assistOrologio, 1000);

function assistTotale() {
  const c = (assist.d && assist.d.condizioni) || {}, ore = +$("assist-ore").value || 1;
  $("assist-totale").textContent = assistEuro(ore * (c.tariffa_ora_euro || 0));
}
$("assist-ore").addEventListener("change", assistTotale);
$("assist-form-ordine").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const ore = +$("assist-ore").value;
  try {
    const o = await api("/api/assistenza/ordine", { ore });
    $("assist-ordine-testo").textContent = `${o.ore} ${o.ore === 1 ? "ora" : "ore"} · ${o.importo_testo} · causale «${o.causale}»`;
    $("assist-l-mail").href = o.mailto;
    $("assist-l-stampa").href = o.stampa;
    const wa = $("assist-l-wa");
    wa.href = o.whatsapp || "#";
    wa.parentElement.classList.toggle("nascosto", !o.whatsapp);
    $("assist-ordine").classList.remove("nascosto");
  } catch (e) { toast(e.message, true); }
});

async function assistLeggi() {
  assistDisegna(await api("/api/assistenza/stato"));
}

$("assist-consenso").addEventListener("change", () => { $("assist-avvia").disabled = !$("assist-consenso").checked; });

$("assist-form-codice").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const codice = $("assist-codice").value.trim();
  if (!codice) return toast("Incolla il codice che hai ricevuto", true);
  try {
    const d = await api("/api/assistenza/codice", { codice });
    $("assist-codice").value = "";
    toast(`Ricarica fatta: saldo ${d.credito_min} minuti`);
    assistDisegna(d);
  } catch (e) { toast(e.message, true); }
});

$("assist-avvia").addEventListener("click", async (ev) => {
  if (!$("assist-consenso").checked) return toast("Spunta prima la casella del consenso", true);
  const b = ev.currentTarget;
  b.disabled = true;
  b.textContent = "Collegamento in corso…";
  try {
    const d = await api("/api/assistenza/avvia", { consenso: true }, 60000);   // tmate aspetta tmate.io; il tunnel crea le chiavi
    toast("Assistenza avviata: manda al tecnico la riga qui sotto");
    assistDisegna(d);
  } catch (e) { toast(e.message, true); }
  finally {
    b.textContent = "Chiedi assistenza";
    $("assist-consenso").checked = false;          // il consenso vale per una sessione sola
    b.disabled = true;
  }
});

$("assist-copia-guarda").addEventListener("click", () => {
  const t = $("assist-guarda").textContent;
  if (t) navigator.clipboard.writeText(t).then(() => toast("Comando copiato: incollalo nel Terminale"));
});

$("assist-copia").addEventListener("click", () => {
  const t = $("assist-ssh").textContent;
  if (t) navigator.clipboard.writeText(t).then(() => toast("Riga copiata: mandala al tecnico"));
});

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-assist-stop]");
  if (!b) return;
  try {
    const d = await api("/api/assistenza/stop", {}, 20000);
    toast("Assistenza fermata");
    assistDisegna(d);
  } catch (e) { toast(e.message, true); }
});

ogni(assistLeggi, () => (assist.abilitata ? 5000 : 60000), 30000);

// ------------------------------------------------ Assistenza, lato tecnico (2026-09-29)
// Solo dove c'è la chiave privata dei codici (il Mac dell'utente): altrove /api/assistenza/tecnico/stato
// risponde 404 e il riquadro resta nascosto. Genera i codici per i clienti e apre il Terminale sulla
// riga ssh di tmate che il cliente manda. La chiave non passa mai di qui: il server firma e basta.
// 2026-10-02: la stessa casella accetta la richiesta del tunnel (jarvis-tunnel:1:…): il server apre la
// chiave sulla VPS (tunnel-apri) e il Terminale; «Sessioni sulla VPS» legge tunnel-stato e CHIUDI usa tunnel-chiudi.
const tec = { disponibile: false, tunnel: false };

function tecDisegna(d) {
  tec.disponibile = !!(d && d.disponibile);
  $("assistenza-tecnico").classList.toggle("nascosto", !tec.disponibile);
  if (!tec.disponibile) return;
  if ("tunnel" in d) tec.tunnel = !!d.tunnel;
  $("tec-tunnel-manca").classList.toggle("nascosto", tec.tunnel);
  const voci = d.emessi || [];
  $("tec-emessi").replaceChildren(...(voci.length ? voci.map((v) => el("li", { class: v.scaduto ? "scaduto" : null,
    title: v.codice || "" },
    `${v.creato_il}  ${v.cliente || "—"} · ${v.minuti} min · ${v.scaduto ? "scaduto il" : "scade il"} ${v.scade_il} · …${String(v.id || "").slice(-6)}  `,
    el("button", { class: "piccolo", onclick: () => tecCopia(v.codice) }, "Copia")))
    : [el("li", {}, "Nessun codice emesso da qui.")]));
  tecDisegnaScorri();
}

function tecDisegnaScorri() {
  if (!window.tecScorri) return;
  window.tecScorri = false;
  requestAnimationFrame(() => $("assistenza-tecnico").scrollIntoView({ block: "start" }));
}

function tecCopia(t) {
  if (t) navigator.clipboard.writeText(t).then(() => toast("Codice copiato: mandalo al cliente"),
    () => toast("Copia non riuscita: selezionalo a mano", true));
}

async function tecLeggi() {
  try { tecDisegna(await api("/api/assistenza/tecnico/stato")); } catch (e) { tecDisegna(null); }
}

$("tec-form-codice").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cliente = $("tec-cliente").value.trim();
  const minuti = Number($("tec-minuti").value);
  const scade_ore = Number($("tec-scade").value || 48);
  if (!cliente) return toast("Scrivi il nome del cliente", true);
  if (!Number.isInteger(minuti) || minuti < 15 || minuti % 15) return toast("I minuti devono essere un multiplo di 15", true);
  const b = $("tec-genera");
  b.disabled = true;
  try {
    const d = await api("/api/assistenza/tecnico/codice", { cliente, minuti, scade_ore }, 30000);
    const v = d.emesso;
    $("tec-codice").textContent = v.codice;
    $("tec-risultato-info").textContent = `${v.cliente} · ${v.minuti} minuti (circa ${assistEuro(v.euro)}) · scade il ${v.scade_il} · vale una volta sola`;
    $("tec-risultato").classList.remove("nascosto");
    toast("Codice generato");
    tecDisegna({ disponibile: true, emessi: d.emessi });
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; }
});

$("tec-copia").addEventListener("click", () => tecCopia($("tec-codice").textContent));

function tecSessioni(lista) {
  const ora = (ts) => new Date(ts * 1000).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  $("tec-tunnel-sessioni").replaceChildren(...(lista && lista.length ? lista.map((v) => el("li", {},
    el("span", {}, `porta ${v.porta}${v.porta_schermo ? ` + schermo ${v.porta_schermo}` : ""} · ${v.cliente || "—"} · aperta alle ${ora(v.aperta)} · `
      + `${v.collegata ? "collegata" : "in attesa del cliente"} · chiude al più tardi alle ${ora(v.tetto)}`),
    el("button", { class: "pericolo piccolo", onclick: () => tecChiudi(v.porta) }, "CHIUDI")))
    : [el("li", {}, "Nessuna sessione aperta sulla VPS.")]));
}

async function tecTunnelStato() {
  const b = $("tec-tunnel-aggiorna");
  b.disabled = true;
  try { tecSessioni((await api("/api/assistenza/tecnico/tunnel-stato", {}, 40000)).sessioni); }
  catch (e) { toast(e.message, true); }
  finally { b.disabled = false; }
}

async function tecChiudi(porta) {
  if (!confirm(`Chiudere la sessione sulla porta ${porta}? Il tunnel cade e il cliente viene scollegato.`)) return;
  try {
    const d = await api("/api/assistenza/tecnico/tunnel-chiudi", { porta }, 40000);
    toast(`Sessione della porta ${porta} chiusa`);
    tecSessioni(d.sessioni);
  } catch (e) { toast(e.message, true); }
}

async function tecCollegati(soloSchermo) {
  const riga = $("tec-ssh").value.trim();
  if (!riga) return toast("Incolla la richiesta (o la riga ssh) del cliente", true);
  if (soloSchermo === true && !/^jarvis-tunnel:2:/.test(riga.replace(/\s+/g, "")))
    return toast("Questa richiesta non porta lo schermo: il PC del cliente ha solo il terminale", true);
  const b = $(soloSchermo === true ? "tec-solo-schermo" : "tec-collegati");
  b.disabled = true;
  try {
    if (/^jarvis-tunnel:/.test(riga)) {
      // 2026-10-02 sera: richiesta v2 = Terminale e Schermo condiviso insieme; v1 = solo Terminale, senza errori
      const d = await api("/api/assistenza/tecnico/tunnel-apri", { richiesta: riga, solo_schermo: soloSchermo === true }, 60000);
      const cosa = [d.terminale ? "Terminale" : "", d.schermo ? "Schermo condiviso" : ""].filter(Boolean).join(" e ");
      toast(`Tunnel aperto sulla porta ${d.porta}: ${cosa || "niente"} verso il cliente`
        + (d.avviso_schermo ? ` · schermo: ${d.avviso_schermo}` : ""), !!d.avviso_schermo);
      tecSessioni(d.sessioni);
    } else {
      await api("/api/assistenza/tecnico/collegati", { ssh: riga }, 30000);
      toast("Terminale aperto: sei collegato al cliente");
    }
  } catch (e) { toast(e.message, true); }
  finally { b.disabled = false; }
}
$("tec-tunnel-aggiorna").addEventListener("click", tecTunnelStato);
$("tec-collegati").addEventListener("click", () => tecCollegati(false));
$("tec-solo-schermo").addEventListener("click", () => tecCollegati(true));
$("tec-form-ssh").addEventListener("submit", (ev) => { ev.preventDefault(); tecCollegati(); });

ogni(tecLeggi, () => (tec.disponibile ? 60000 : 300000), 300000);

// =====================================================================
// Repository GitHub e box spostabili (01/10/2026, richiesta dell'utente)
// =====================================================================

// ------------------------------------------------ Repository GitHub
const REPO_GRUPPI = [
  ["jarvis", "Jarvis", "il repository di Jarvis e le sue copie"],
  ["prodotti", "Prodotti", "si pubblicano solo con il sì dell'utente"],
  ["condiviso", "Condivisi", "repository usati anche da altri computer"],
  ["altri", "Altri repository", "personali, fuori dalla linea unica"],
];
function quandoFa(iso) {
  if (!iso) return "—";
  const g = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (g < 1) return "oggi"; if (g === 1) return "ieri"; if (g < 60) return g + " giorni fa";
  return iso.slice(0, 10);
}
function repoStato(r) {
  const l = r.locale;
  if (!l) return el("span", { class: "repo-stato tenue" }, "nessun clone");
  const parti = [];
  if (l.modifiche) parti.push(l.modifiche + " modifiche");
  if (l.avanti) parti.push(l.avanti + " da inviare");
  if (l.indietro) parti.push(l.indietro + " da scaricare");
  return el("span", { class: "repo-stato " + (parti.length ? "attenzione" : "ok") }, parti.length ? "● " + parti.join(" · ") : "✓ allineato");
}
let repoInCorso = false;
async function caricaRepo(forza = false) {
  const lista = $("repo-lista");
  if (!lista || repoInCorso) return;
  repoInCorso = true;
  try {
    const d = await api("/api/github" + (forza ? "?forza=1" : ""), null, 40000);
    lista.replaceChildren();
    for (const [g, titolo, nota] of REPO_GRUPPI) {
      const righe = d.repo.filter((r) => r.gruppo === g);
      if (!righe.length) continue;
      lista.append(el("h3", { class: "repo-gruppo" }, titolo, el("small", {}, nota)));
      for (const r of righe) {
        lista.append(el("div", { class: "repo-riga" },
          r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener", class: "repo-nome" }, r.nome) : el("b", { class: "repo-nome" }, r.nome),
          el("span", { class: "repo-badge " + r.visibilita }, r.visibilita === "public" ? "pubblico" : "privato"),
          el("span", { class: "repo-tipo", title: r.nota || "" }, r.tipo),
          el("span", { class: "repo-push", title: r.push }, "push " + quandoFa(r.push)),
          repoStato(r)));
      }
    }
    $("repo-conta").textContent = `${d.repo.length} · letti alle ${d.aggiornato.slice(11)}`;
    if (d.errori && d.errori.length) lista.append(el("p", { class: "nota" }, "GitHub non ha risposto per: " + d.errori.join(" · ")));
  } catch (e) {
    lista.replaceChildren(el("p", { class: "vuoto" }, "Non leggo i repository: " + e.message));
  } finally { repoInCorso = false; }
}
$("btn-repo-aggiorna")?.addEventListener("click", () => caricaRepo(true));

// ------------------------------------------------ box spostabili
// Ogni .pannello ha una maniglia ⠿ nel titolo: la si trascina e gli altri box si riallineano da soli,
// perché l'impaginazione resta quella della griglia CSS (cambia solo l'ordine nel DOM). L'ordine si salva
// per pagina nel browser (localStorage «cc.box.<pagina>»). Con i puntatori, quindi vale anche col dito.
// Restano fuori la chat, la lavagna e i box dentro .blocco-lavori (lista e dettaglio dipendono l'uno dall'altro).
const BOX = { drag: null, vista: null, sfondo: null };
const boxChiave = (p, i) => p.id || ("n" + i + "-" + (p.querySelector("h2")?.firstChild?.textContent || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 30));
function boxVista(v) {
  return [...v.querySelectorAll(".pannello")].filter((p) => !p.closest(".blocco-lavori") && p.parentElement);
}
function boxApplica(v, ordine) {
  const pos = new Map(ordine.map((k, i) => [k, i]));
  const gruppi = new Map();
  for (const p of boxVista(v)) { if (!gruppi.has(p.parentElement)) gruppi.set(p.parentElement, []); gruppi.get(p.parentElement).push(p); }
  for (const [padre, lista] of gruppi) {
    const dopo = lista[lista.length - 1].nextSibling;
    const ord = lista.map((p, i) => [p, pos.has(p.dataset.box) ? pos.get(p.dataset.box) : 1e6 + i]).sort((a, b) => a[1] - b[1]);
    for (const [p] of ord) padre.insertBefore(p, dopo);
  }
}
function boxSalva(v) {
  const ordine = boxVista(v).map((p) => p.dataset.box);
  const fabbrica = boxVista(v).slice().sort((a, b) => a.dataset.fabbrica - b.dataset.fabbrica).map((p) => p.dataset.box);
  const uguale = JSON.stringify(ordine) === JSON.stringify(fabbrica);
  mem.scrivi("box." + v.dataset.vista, uguale ? null : ordine);
  boxBottone();
}
function boxBottone() {
  const b = $("btn-ripristina-box"), v = document.querySelector(".vista.attiva");
  if (b) b.classList.toggle("nascosto", !(v && mem.leggi("box." + v.dataset.vista, null)));
}
function boxPosizioneDelPuntatore(ev) {
  const d = BOX.drag;
  for (const p of boxVista(d.closest(".vista"))) {
    if (p === d || p.parentElement !== d.parentElement || p.offsetParent === null) continue;
    const r = p.getBoundingClientRect(), m = d.getBoundingClientRect();
    if (ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom) continue;
    const stessaRiga = Math.abs(r.top - m.top) < 24 && r.width < d.parentElement.clientWidth * 0.9;
    const prima = stessaRiga ? ev.clientX < r.left + r.width / 2 : ev.clientY < r.top + r.height / 2;
    d.parentElement.insertBefore(d, prima ? p : p.nextSibling);
    return;
  }
}
function boxInizia(ev, p) {
  if (ev.button !== undefined && ev.button !== 0) return;
  if (BOX.drag) return;
  ev.preventDefault();
  const maniglia = ev.currentTarget;
  try { maniglia.setPointerCapture(ev.pointerId); } catch (e) { /* puntatore già rilasciato: il trascinamento parte lo stesso */ }
  BOX.drag = p; p.classList.add("box-sollevato"); document.body.classList.add("box-in-corso");
  const scorri = document.querySelector("main") || document.documentElement;
  let timer = null, y = 0, finito = false;
  // movimento e rilascio si ascoltano sulla finestra, non sulla maniglia: se il rilascio avviene fuori
  // (o la cattura del puntatore salta) il trascinamento si chiude lo stesso e l'ordine si salva
  const muovi = (e) => {
    if (e.buttons === 0 && e.pointerType === "mouse") return fine();   // il tasto è già stato rilasciato
    y = e.clientY; boxPosizioneDelPuntatore(e);
    clearInterval(timer);
    if (y < 70 || y > window.innerHeight - 70) timer = setInterval(() => { scorri.scrollTop += y < 70 ? -14 : 14; }, 30);
  };
  const fine = () => {
    if (finito) return; finito = true;
    clearInterval(timer);
    for (const t of ["pointermove", "pointerup", "pointercancel", "blur"]) window.removeEventListener(t, t === "pointermove" ? muovi : fine, true);
    try { maniglia.releasePointerCapture(ev.pointerId); } catch (e) { /* già rilasciato */ }
    p.classList.remove("box-sollevato"); document.body.classList.remove("box-in-corso");
    BOX.drag = null; boxSalva(p.closest(".vista"));
  };
  window.addEventListener("pointermove", muovi, true);
  for (const t of ["pointerup", "pointercancel", "blur"]) window.addEventListener(t, fine, true);
}
function boxInit() {
  for (const v of document.querySelectorAll(".vista")) {
    if (["chat", "lavagna"].includes(v.dataset.vista)) continue;
    boxVista(v).forEach((p, i) => {
      p.dataset.box = boxChiave(p, i); p.dataset.fabbrica = i;
      const titolo = p.querySelector(":scope > h2, :scope > .testa-pannello > h2, :scope h2");
      if (!titolo) return;
      const m = el("button", { type: "button", class: "maniglia-box", title: "Trascina per spostare il box", "aria-label": "Sposta il box " + (titolo.textContent || "").trim(),
        onpointerdown: (ev) => boxInizia(ev, p) }, "⠿");
      titolo.prepend(m);
    });
    const salvato = mem.leggi("box." + v.dataset.vista, null);
    if (Array.isArray(salvato)) boxApplica(v, salvato);
  }
  $("btn-ripristina-box")?.addEventListener("click", () => {
    const v = document.querySelector(".vista.attiva"); if (!v) return;
    boxApplica(v, boxVista(v).slice().sort((a, b) => a.dataset.fabbrica - b.dataset.fabbrica).map((p) => p.dataset.box));
    mem.scrivi("box." + v.dataset.vista, null); boxBottone(); toast("Box rimessi nell'ordine di fabbrica");
  });
  boxBottone();
}
boxInit();
window.addEventListener("hashchange", () => { boxBottone(); if (location.hash === "#home") caricaRepo(); });
if (location.hash === "#home") caricaRepo();

// ------------------------------------------------ aggiornamento del software (01/10/2026, rifatto il 05/10/2026)
// /api/aggiornamento dice se il pannello gira su una versione più vecchia di quella su disco o su GitHub.
// «Aggiorna ora»: il server scarica (solo avanti veloce), risponde e si riavvia; la pagina aspetta che torni
// con la versione nuova e si ricarica da sola. Con chat o missioni in corso chiede prima nel riquadro.
const AGG = { riavvio: false };
async function controllaAggiornamento(forza = false) {
  const box = $("avviso-aggiorna");
  if (!box || AGG.riavvio) return;
  try {
    const d = await api("/api/aggiornamento" + (forza ? "?forza=1" : ""), null, 45000);
    box.classList.toggle("nascosto", !d.disponibile);
    if (!d.disponibile) return;
    const n = d.indietro || d.novita.length;
    const cosa = d.da_scaricare ? "" : " · da riavviare";
    $("aggiorna-testo").textContent = `${n} ${n === 1 ? "modifica nuova" : "modifiche nuove"} · ${d.locale} → ${d.remoto}${cosa}`
      + (d.nota ? ` · ${d.nota}` : "");
    $("aggiorna-novita").replaceChildren(...d.novita.map((x) => el("li", {}, x)));
  } catch (e) { /* senza rete o senza git il pannello va avanti: l'avviso non compare */ }
}
function aggiornaStato(testo, errore = false) {
  const t = $("aggiorna-testo");
  t.textContent = testo;
  t.classList.toggle("errore", errore);
}
// Aspetta il pannello nuovo: durante il riavvio le richieste falliscono; quando risponde con un token diverso
// (403 token_scaduto) o con un'altra versione di avvio, la pagina si ricarica.
async function aspettaRiavvio(versionePrima) {
  const inizio = Date.now();
  await new Promise((ok) => setTimeout(ok, 2500));
  while (Date.now() - inizio < 120000) {
    try {
      const r = await fetch("/api/aggiornamento", { headers: HDR, cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if ((r.status === 403 && d.token_scaduto) || (r.ok && d.avvio && d.avvio !== versionePrima)) {
        aggiornaStato("pannello ripartito: ricarico la pagina…");
        sessionStorage.setItem("cc.ricarica", String(Date.now()));
        location.reload();
        return;
      }
    } catch (e) { /* il pannello sta ripartendo */ }
    aggiornaStato(`riavvio in corso… (${Math.round((Date.now() - inizio) / 1000)} s)`);
    await new Promise((ok) => setTimeout(ok, 2000));
  }
  AGG.riavvio = false;
  $("btn-aggiorna-ora").disabled = false;
  aggiornaStato("il pannello non è tornato entro 2 minuti: guarda command-center/lavori/aggiornamento.log", true);
}
async function aggiornaOra(forza = false) {
  const b = $("btn-aggiorna-ora");
  b.disabled = true;
  $("aggiorna-conferma")?.remove();
  aggiornaStato("sto aggiornando…");
  let prima = "";
  try { prima = (await api("/api/aggiornamento", null, 45000)).avvio || ""; } catch (e) { /* si va avanti */ }
  try {
    const d = await api("/api/aggiorna", forza ? { forza: true } : {}, 90000);
    if (d.chiede_conferma) {
      aggiornaStato("c'è del lavoro in corso, il riavvio lo interrompe: " + (d.occupato || []).join(" · "), true);
      const si = el("button", { type: "button", class: "pericolo" }, "Riavvia lo stesso");
      si.onclick = () => aggiornaOra(true);
      const no = el("button", { type: "button" }, "Aspetto");
      no.onclick = () => { $("aggiorna-conferma").remove(); b.disabled = false; controllaAggiornamento(true); };
      b.after(el("span", { id: "aggiorna-conferma", class: "azioni-riga" }, si, no));
      return;
    }
    if (!d.avviato) {
      aggiornaStato(d.motivo || "niente da aggiornare", true);
      toast(d.motivo || "Niente da aggiornare", true);
      b.disabled = false;
      setTimeout(() => controllaAggiornamento(true), 4000);
      return;
    }
    AGG.riavvio = true;
    aggiornaStato((d.scaricato ? "codice scaricato · " : "") + "riavvio del pannello…");
    aspettaRiavvio(prima || d.da || "");
  } catch (e) {
    aggiornaStato(e.message, true);
    toast(e.message, true);
    b.disabled = false;
  }
}
$("btn-aggiorna-ora")?.addEventListener("click", () => aggiornaOra(false));
controllaAggiornamento();
setInterval(controllaAggiornamento, 10 * 60 * 1000);

// ---- 2026-10-10: diario dell'agente e pagina del progetto (file caricati, nome, descrizione, archivio)
// Una sola fonte: il diario è <cartella>/.claude/memoria/agenti/<nome>.md, i file stanno in <cartella>/File/.
let DIARIO_LETTO = { k: "", testo: "" };
async function caricaDiario(k) {
  const [pid, nome] = String(k || "").split(":");
  const box = $("sa-diario-sintesi");
  if (!pid || !nome || pid === "casa" || !box) { if (box) box.replaceChildren(el("small", { class: "nota" }, "Gli agenti di casa non hanno un diario di progetto.")); return; }
  try {
    const d = await api(`/api/diario?progetto=${encodeURIComponent(pid)}&agente=${encodeURIComponent(nome)}`);
    if (schedaKey !== k) return;
    $("sa-diario-file").textContent = d.file.replace(/^.*\/\.claude\//, ".claude/");
    const riga = (titolo, voci) => el("div", { class: "sa-diario-sez" }, el("b", {}, titolo),
      voci.length ? el("ul", {}, ...voci.slice(-5).map(([q, x]) => el("li", {}, el("small", {}, q + " · "), x))) : el("small", { class: "nota" }, " niente ancora"));
    const parti = [riga("FATTO", d.fatto), riga("DA FARE", d.da_fare), riga("ERRORI COMMESSI DA NON RIPETERE", d.errori)];
    if ((d.errori_ripetuti || []).length) parti.push(el("p", { class: "avviso" }, "⚠ Errore ripetuto in due giorni diversi: " + d.errori_ripetuti.join("; ")));
    box.replaceChildren(...parti);
    const ta = $("sa-diario");
    if (DIARIO_LETTO.k !== k || ta.value === DIARIO_LETTO.testo) ta.value = d.testo;   // non si perde quello che stai scrivendo
    DIARIO_LETTO = { k, testo: d.testo };
  } catch (e) { box.replaceChildren(el("small", { class: "nota" }, "Diario non letto: " + e.message)); }
}
$("sa-diario-salva")?.addEventListener("click", async () => {
  const [pid, nome] = String(schedaKey || "").split(":");
  try {
    const r = await api("/api/diario", { progetto: pid, agente: nome, testo: $("sa-diario").value });
    $("sa-diario-nota").textContent = r.messaggio; DIARIO_LETTO.testo = $("sa-diario").value; caricaDiario(schedaKey);
  } catch (e) { toast("Diario non salvato: " + e.message, true); }
});
let SP_ID = "";
function progettoCat(pid) {
  for (const s of spaziCat || []) for (const p of s.progetti || []) if (p.id === pid) return { s, p };
  return null;
}
async function apriSchedaProgetto(pid) {
  const c = progettoCat(pid);
  if (!c) { toast("Progetto non trovato", true); return; }
  SP_ID = pid;
  $("sp-titolo").textContent = c.p.nome; $("sp-cartella").textContent = c.p.cartella;
  $("sp-nome").value = c.p.nome; $("sp-descr").value = c.p.descrizione || "";
  $("sp-carica-nota").textContent = "";
  $("scheda-progetto").showModal();
  caricaFileProgetto();
}
async function caricaFileProgetto() {
  if (!SP_ID) return;
  try {
    const d = await api("/api/progetto/file?progetto=" + encodeURIComponent(SP_ID));
    $("sp-file-conta").textContent = d.file.length ? `${d.file.length} file` : "nessuno";
    $("sp-file").replaceChildren(...(d.file.length ? d.file.map((x) => el("li", {}, el("b", {}, x.nome), el("small", {}, ` · ${x.data} · ${x.byte} byte`)))
      : [el("li", { class: "nota" }, "Nessun file ancora. Caricali qui sopra o copiali in File/.")]));
    $("sp-indice").textContent = d.indice || "";
  } catch (e) { $("sp-file").replaceChildren(el("li", { class: "nota" }, "File non letti: " + e.message)); }
}
function base64Di(file) {
  return new Promise((ok, ko) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",")[1] || "");
    r.onerror = () => ko(r.error || new Error("lettura del file non riuscita"));
    r.readAsDataURL(file);
  });
}
$("sp-carica")?.addEventListener("change", async (ev) => {
  const files = [...(ev.target.files || [])];
  for (const f of files) {
    if (f.size > 25 * 1024 * 1024) { toast(`${f.name}: più di 25 MB, copialo a mano in File/`, true); continue; }
    $("sp-carica-nota").textContent = `carico ${f.name}…`;
    try {
      const r = await api("/api/progetto/carica", { progetto: SP_ID, nome: f.name, base64: await base64Di(f) }, 120000);
      $("sp-carica-nota").textContent = r.messaggio;
    } catch (e) { toast(`${f.name} non caricato: ${e.message}`, true); }
  }
  ev.target.value = "";
  caricaFileProgetto();
});
$("sp-salva")?.addEventListener("click", async () => {
  const c = progettoCat(SP_ID);
  if (!c) return;
  try {
    if ($("sp-nome").value.trim() && $("sp-nome").value.trim() !== c.p.nome) await api("/api/progetto/modifica", { cosa: "rinomina", progetto: SP_ID, valore: $("sp-nome").value.trim() });
    if ($("sp-descr").value.trim() !== (c.p.descrizione || "")) await api("/api/progetto/modifica", { cosa: "descrizione", progetto: SP_ID, valore: $("sp-descr").value.trim() });
    toast("Progetto salvato (spazi.json, copia .bak accanto)"); caricaSpazi();
  } catch (e) { toast("Non salvato: " + e.message, true); }
});
$("sp-archivia")?.addEventListener("click", async () => {
  const c = progettoCat(SP_ID);
  if (!c || !confirm(`Archivio «${c.p.nome}»? Esce dai progetti attivi; cartella, agenti e memoria restano. Si ripristina con crea_progetto.py --ripristina ${SP_ID}.`)) return;
  try { await api("/api/progetto/modifica", { cosa: "archivia", progetto: SP_ID }); $("scheda-progetto").close(); toast("Progetto archiviato"); caricaSpazi(); }
  catch (e) { toast("Non archiviato: " + e.message, true); }
});

// 2026-10-10: primo caricamento sicuro. Se dopo 3 s la pagina non ha ancora letto gli spazi (o una lettura è andata
// persa), li richiede; poi ogni 15 s finché non arrivano.
(function primoCaricamentoSpazi() {
  setTimeout(function giro() { if (!SPAZI_API_OK) { caricaSpazi(); setTimeout(giro, 15000); } }, 3000);
})();

// 2026-10-10: il nome dell'assistente e del proprietario dal profilo anche nei testi fissi della pagina
// («Nuova chat con Jarvis», titolo, pulsanti). Si cambia solo il testo visibile, mai codice, campi o percorsi.
let NOMI_APPLICATI = "";
// «Jarvis» come nome, non dentro un percorso o un nome di file (~/Jarvis, Jarvis-Memoria, jarvis_status.py)
const PAROLA_JARVIS = /(?<![\/~\w.-])Jarvis(?![\/\w.-])/, PAROLA_JARVIS_G = /(?<![\/~\w.-])Jarvis(?![\/\w.-])/g;
function applicaNomi() {
  const cambiaNome = !/\bJarvis\b/.test(ASSISTENTE);      // «Jarvis 2» resta com'è: niente giri infiniti
  if (!cambiaNome && !UTENTE) return;
  if (!/\bJARVIS\b|Jarvis|L'utente/.test(document.body.textContent + document.title)) return;   // niente da cambiare
  const firma = ASSISTENTE + "|" + UTENTE;
  const salta = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "INPUT", "KBD"]);
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement && !salta.has(n.parentElement.tagName) && !n.parentElement.closest("code,pre,textarea,.msg-testo,.messaggi")
      && ((cambiaNome && PAROLA_JARVIS.test(n.nodeValue)) || (UTENTE && /L'utente/.test(n.nodeValue))) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) });
  const nodi = [];
  while (w.nextNode()) nodi.push(w.currentNode);
  for (const n of nodi) n.nodeValue = (cambiaNome ? n.nodeValue.replace(PAROLA_JARVIS_G, ASSISTENTE) : n.nodeValue).replace(/L'utente/g, UTENTE || "L'utente");
  if (cambiaNome) for (const e of document.querySelectorAll("[title*='Jarvis'],[placeholder*='Jarvis'],[aria-label*='Jarvis']"))
    for (const a of ["title", "placeholder", "aria-label"]) if (e.getAttribute(a)) e.setAttribute(a, e.getAttribute(a).replace(PAROLA_JARVIS_G, ASSISTENTE));
  const cuore = document.querySelector("#sfera .cuore b");          // la sfera della voce: il nome in maiuscolo
  if (cambiaNome && cuore && cuore.textContent !== ASSISTENTE.toUpperCase()) cuore.textContent = ASSISTENTE.toUpperCase();
  if (cambiaNome && PAROLA_JARVIS.test(document.title)) document.title = document.title.replace(PAROLA_JARVIS_G, ASSISTENTE);
  NOMI_APPLICATI = firma;
}
// i testi disegnati dopo (chat, menu, schede) passano di qui una volta per fotogramma
const OSSERVA_NOMI = new MutationObserver(() => { if (!applicaNomi.attesa) { applicaNomi.attesa = true; requestAnimationFrame(() => { applicaNomi.attesa = false; applicaNomi(); }); } });
OSSERVA_NOMI.observe(document.body, { childList: true, subtree: true, characterData: true });
if (document.querySelector("title")) OSSERVA_NOMI.observe(document.querySelector("title"), { childList: true, characterData: true, subtree: true });

window.addEventListener("hashchange", () => { if (location.hash.startsWith("#lavagna")) requestAnimationFrame(() => requestAnimationFrame(centraSeFuoriVista)); });
