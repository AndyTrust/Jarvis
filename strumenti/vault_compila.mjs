#!/usr/bin/env node
// Scrive un valore del Vault nel campo di una pagina di Chrome, senza che il valore passi da chi lo chiede
// (funziona su macOS e Linux; su Windows il Vault non lo usa). Lo lancia SOLO command-center/vault_cc.py (UsoAgenti),
// mai un agente a mano.
//
//   node vault_compila.mjs '{"porta":9222,"domini":["esempio.it"],"campo":"password","selettore":"#ap_password","invio":false}'  < valore
//
// - il valore arriva per stdin (mai nella riga di comando, mai nei log); non viene mai stampato;
// - la scheda si sceglie per DOMINIO: la prima scheda aperta su uno dei domini della voce (o un suo sottodominio),
//   non la prima della lista (le routine che aprono schede nello stesso browser non confondono niente);
//   la scheda scelta viene portata in primo piano prima di scrivere;
// - pagine dei fornitori di identità (vault-provider.json: accounts.google.com, appleid.apple.com, ...): solo se la
//   voce ha ESATTAMENTE quel dominio; una voce di un altro sito lì si rifiuta;
// - campo «password»: solo un <input type="password"> (mai un campo di testo visibile);
//   campo «codice»: input di testo/numero/telefono/password; «utente», «mail»: input o textarea non password;
// - con «selettore» mette il fuoco su quel campo e lo seleziona; senza, usa il campo che ha già il fuoco
//   (per «codice» prima prova input[autocomplete=one-time-code]);
// - scrive con Input.insertText (DevTools, 127.0.0.1), poi controlla SOLO la lunghezza del campo;
// - «invio»: preme Invio; dopo guarda se la pagina chiede verifica in due passaggi, passkey o captcha e lo dice
//   («verifica»): l'agente si ferma e avvisa il proprietario.
// Uscita: una riga JSON {ok, host, verificato, motivo, verifica}. Nessun valore.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const esci = (o, codice = 0) => { process.stdout.write(JSON.stringify(o) + "\n"); process.exit(codice); };
let conf;
try { conf = JSON.parse(process.argv[2] || "{}"); } catch { esci({ ok: false, motivo: "argomenti non validi" }, 2); }
const porta = Number(conf.porta);
const domini = Array.isArray(conf.domini) ? conf.domini.map((d) => String(d).toLowerCase()) : [];
const campo = String(conf.campo || "password");
if (!Number.isInteger(porta) || porta < 1024 || porta > 65535) esci({ ok: false, motivo: "porta non valida" }, 2);
if (!domini.length) esci({ ok: false, motivo: "nessun dominio ammesso" }, 2);
if (!["password", "utente", "mail", "codice"].includes(campo)) esci({ ok: false, motivo: "campo non ammesso" }, 2);
if (typeof WebSocket === "undefined") esci({ ok: false, motivo: "node senza WebSocket (serve --experimental-websocket)" }, 2);

let PROVIDER = {};
try { PROVIDER = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "vault-provider.json"), "utf8")).provider || {}; }
catch { esci({ ok: false, motivo: "manca o non si legge strumenti/vault-provider.json" }, 2); }

const leggiStdin = () => new Promise((ok) => { const p = []; process.stdin.on("data", (c) => p.push(c)); process.stdin.on("end", () => ok(Buffer.concat(p).toString("utf8"))); });
const hostDi = (u) => { try { return new URL(u).hostname.toLowerCase(); } catch { return ""; } };
const ammesso = (h) => domini.some((d) => h === d || h.endsWith("." + d));

function collega(url) {
  return new Promise((ok, ko) => {
    const s = new WebSocket(url);
    const attese = new Map();
    let n = 0;
    const t = setTimeout(() => { try { s.close(); } catch { /* */ } ko(new Error("tempo scaduto")); }, 30000);
    s.onopen = () => ok({
      manda: (method, params = {}) => new Promise((r, k) => { const id = ++n; attese.set(id, { r, k }); s.send(JSON.stringify({ id, method, params })); }),
      chiudi: () => { clearTimeout(t); try { s.close(); } catch { /* */ } },
    });
    s.onmessage = (e) => { const m = JSON.parse(e.data); const a = attese.get(m.id); if (a) { attese.delete(m.id); m.error ? a.k(new Error("DevTools: " + (m.error.message || "errore"))) : a.r(m.result); } };
    s.onerror = () => { clearTimeout(t); ko(new Error("collegamento al browser non riuscito")); };
  });
}

// Cosa chiede la pagina dopo l'invio (solo la categoria, mai il testo della pagina).
const VERIFICA_JS = `(() => {
  const t = ((document.body && document.body.innerText) || "").slice(0, 20000).toLowerCase();
  const q = (s) => !!document.querySelector(s);
  if (q('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"],iframe[src*="challenges.cloudflare"],.g-recaptcha,.h-captcha,.cf-turnstile')
      || /non sono un robot|i'm not a robot|captcha|verifica di essere umano|verify you are human/.test(t)) return "captcha";
  if (/passkey|chiave di accesso|security key|chiave di sicurezza/.test(t)) return "passkey";
  if (q('input[autocomplete="one-time-code"]') || /verifica in due passaggi|2-step|two-step|two-factor|autenticazione a due|codice di verifica|verification code|authenticator|conferma che sei tu|verify it's you/.test(t)) return "due passaggi";
  return "";
})()`;

try {
  let valore = await leggiStdin();
  if (!valore) esci({ ok: false, motivo: "valore vuoto" }, 2);
  const pagine = (await (await fetch(`http://127.0.0.1:${porta}/json/list`)).json()).filter((p) => p.type === "page");
  if (!pagine.length) esci({ ok: false, motivo: "nessuna scheda aperta nel browser" }, 3);
  const p = pagine.find((x) => ammesso(hostDi(x.url)));
  if (!p) {
    const davanti = hostDi(pagine[0].url);
    const prov = PROVIDER[davanti];
    esci({ ok: false, host: davanti, motivo: prov
      ? `usa il metodo ${prov}, non una password: la voce non è di ${davanti}`
      : `nessuna scheda aperta su ${domini.join(", ")} (in primo piano: «${davanti || "nessuna pagina"}»)` }, 4);
  }
  const host = hostDi(p.url);
  if (PROVIDER[host] && !domini.includes(host)) {
    esci({ ok: false, host, motivo: `usa il metodo ${PROVIDER[host]}, non una password: la voce non è di ${host} (serve il dominio esatto)` }, 4);
  }
  const c = await collega(p.webSocketDebuggerUrl);
  try { await c.manda("Page.bringToFront"); } catch { /* */ }
  const valuta = async (expr) => (await c.manda("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;
  const sel = String(conf.selettore || "");
  const pronto = await valuta(`(() => { const s = ${JSON.stringify(sel)}, campo = ${JSON.stringify(campo)};
    let e = s ? document.querySelector(s) : null;
    if (!s && campo === "codice") e = document.querySelector('input[autocomplete="one-time-code"]');
    if (!s && !e) e = document.activeElement;
    if (!e || e === document.body) return s ? "manca" : "nessun campo";
    const tag = (e.tagName || "").toLowerCase(), tipo = (e.getAttribute("type") || "text").toLowerCase();
    if (campo === "password") { if (tag !== "input" || tipo !== "password") return "non password"; }
    else if (campo === "codice") { if (tag !== "input" || !["text", "tel", "number", "password", ""].includes(tipo)) return "non campo"; }
    else { if (!(tag === "textarea" || (tag === "input" && ["text", "email", "tel", ""].includes(tipo)))) return "non campo"; }
    if (e.disabled || e.readOnly) return "bloccato";
    e.focus(); if (typeof e.select === "function") e.select(); return "ok"; })()`);
  const MOTIVI = { manca: "il selettore non trova il campo", "nessun campo": "nessun campo ha il fuoco: passa --selettore",
    "non password": "il campo scelto non è un campo password (input type=password): la password non si scrive in un campo visibile",
    "non campo": `l'elemento non è un campo adatto a «${campo}»`, bloccato: "il campo è disattivato o in sola lettura" };
  if (pronto !== "ok") { c.chiudi(); esci({ ok: false, host, motivo: MOTIVI[pronto] || "campo non adatto" }, 5); }
  // la pagina deve essere ancora sullo stesso host al momento di scrivere
  const ora = String(await valuta("location.hostname")).toLowerCase();
  if (ora !== host) { c.chiudi(); esci({ ok: false, host: ora, motivo: "la pagina è cambiata prima della scrittura" }, 4); }
  const lunghezza = valore.length;
  await c.manda("Input.insertText", { text: valore });
  valore = null;
  const scritti = await valuta("(() => { const e = document.activeElement; if (!e) return -1; return e.isContentEditable ? (e.textContent || '').length : (e.value || '').length; })()");
  let verifica = "";
  if (conf.invio === true) {
    for (const type of ["keyDown", "keyUp"]) {
      await c.manda("Input.dispatchKeyEvent", { type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, ...(type === "keyDown" ? { text: "\r" } : {}) });
    }
    await new Promise((r) => setTimeout(r, 2500));
    try { verifica = await valuta(VERIFICA_JS); } catch { verifica = ""; }
  }
  c.chiudi();
  esci({ ok: true, host, verificato: scritti === lunghezza, ...(verifica ? { verifica } : {}) });
} catch (e) {
  esci({ ok: false, motivo: String(e && e.message || "errore").slice(0, 160) }, 1);
}
