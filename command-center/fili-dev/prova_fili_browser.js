#!/usr/bin/env node
// Prova dei fili con Chrome vero e headless (2026-10-03, cc-fili-opus). La lancia prova_fili.py (parte c),
// che prepara una COPIA del server con la patch (porta 7799, claude finto) e una copia di cc_ponte.py davanti.
//
//   A = «Mac»: desktop 1440, pagina della copia su 127.0.0.1:7799, localStorage con una chat vecchia
//       (messaggi che il server non ha, fra cui una domanda mai partita);
//   B = «telefono»: iPhone 14, la stessa pagina ATTRAVERSO IL PONTE (cookie di sessione dato da prova_fili.py),
//       localStorage vuoto.
// I due contesti hanno localStorage separati. Le domande le manda questo programma al server con un POST
// diretto (come farebbe un terzo dispositivo); dalle pagine NESSUN POST esce: l'intercettazione li abortisce
// tutti e alla fine si elencano. Schermate in FILI_SCHERMATE.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const crypto = require("crypto");
const puppeteer = require(path.join(os.homedir(), "Jarvis", "node_modules", "puppeteer-core"));

const MAC = process.env.FILI_BASE_MAC;
const PONTE = process.env.FILI_BASE_PONTE;
const COOKIE = process.env.FILI_COOKIE || "";
const SCHERMATE = process.env.FILI_SCHERMATE || path.join(os.homedir(), ".locale-onedrive", "cc-ponte", "schermate-fili");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const attesa = (ms) => new Promise((r) => setTimeout(r, ms));
const RIS = [];
function esito(nome, ok, dettaglio = "") {
  RIS.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${nome}${!ok && dettaglio ? "  — " + String(dettaglio).slice(0, 300) : ""}`);
}

function richiesta(metodo, url, corpo, intest = {}) {
  return new Promise((ok, ko) => {
    const u = new URL(url);
    const dati = corpo ? Buffer.from(JSON.stringify(corpo)) : null;
    const r = http.request({ host: u.hostname, port: u.port, path: u.pathname + u.search, method: metodo,
      headers: { ...(dati ? { "Content-Type": "application/json", "Content-Length": dati.length } : {}), ...intest } }, (res) => {
      let b = "";
      res.on("data", (c) => (b += c));
      res.on("end", () => ok({ stato: res.statusCode, corpo: b }));
    });
    r.on("error", ko);
    if (dati) r.write(dati);
    r.end();
  });
}

let TOKEN = "";
async function chiedi(sessione, testo) {
  const r = await richiesta("POST", MAC + "/api/azione", { tipo: "chiedi", testo, sessione, motore: "claude", agente: "", progetto: "" },
    { "X-Token": TOKEN, Origin: MAC });
  return JSON.parse(r.corpo);
}

async function apri(browser, { base, disp, seme = null, cookie = null }) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const D = disp === "iphone14"
    ? { width: 390, height: 844, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
      ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1" }
    : { width: 1440, height: 900, deviceScaleFactor: 1, isMobile: false, hasTouch: false, ua: null };
  await page.setViewport({ width: D.width, height: D.height, deviceScaleFactor: D.deviceScaleFactor, isMobile: D.isMobile, hasTouch: D.hasTouch });
  if (D.ua) await page.setUserAgent(D.ua);
  await page.setBypassServiceWorker(true);
  const reg = { post: [], errori: [], console: [] };
  page.on("pageerror", (e) => reg.errori.push(String(e.message || e).slice(0, 240)));
  page.on("console", (m) => { if (m.type() === "error") reg.console.push(m.text().slice(0, 160)); });
  page.on("dialog", (d) => d.accept().catch(() => {}));
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const m = req.method();
    if (m !== "GET" && m !== "HEAD") {
      reg.post.push(new URL(req.url()).pathname + " " + (req.postData() || "").slice(0, 60));
      return req.abort().catch(() => {});
    }
    if (new URL(req.url()).pathname === "/sw.js") return req.respond({ status: 200, contentType: "application/javascript", body: "" });
    return req.continue().catch(() => {});
  });
  if (cookie) {
    const [nome, valore] = cookie.split("=");
    await page.setCookie({ name: nome, value: valore, url: base });
  }
  if (seme) {
    await page.evaluateOnNewDocument((s) => {
      if (sessionStorage.getItem("seme-fatto")) return;
      sessionStorage.setItem("seme-fatto", "1");
      for (const [k, v] of Object.entries(s)) localStorage.setItem(k, JSON.stringify(v));
    }, seme);
  }
  const r = await page.goto(base + "/#chat", { waitUntil: "domcontentloaded", timeout: 30000 });
  return { ctx, page, reg, stato: r ? r.status() : 0 };
}

const filoDi = (page) => page.evaluate(() => {
  if (typeof THREADS === "undefined") return { pronta: false, messaggi: [], dom: [], fili: null };
  const t = THREADS[chatCon] || {};
  return { chatCon, sessione: t.sessione, attesa: t.attesa || null,
    messaggi: (t.messaggi || []).map((m) => ({ chi: m.chi, testo: m.testo, fid: m.fid || "", errore: !!m.errore })),
    dom: [...document.querySelectorAll("#messaggi .msg .testo")].map((x) => x.textContent),
    lavora: !!document.querySelector("#durata-attesa"), fili: window.CCFili ? window.CCFili.stato() : null,
    ponte: typeof PONTE !== "undefined" ? !!PONTE.dentro : null };
});
async function finche(page, fn, ms = 10000, passo = 150) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const f = await filoDi(page);
    if (fn(f)) return { f, ms: Date.now() - t0 };
    await attesa(passo);
  }
  return { f: await filoDi(page), ms: null };
}
const conta = (f, testo) => f.messaggi.filter((m) => m.testo === testo).length;
const contaDom = (f, testo) => f.dom.filter((t) => t === testo).length;

(async () => {
  fs.mkdirSync(SCHERMATE, { recursive: true });
  const pag = await richiesta("GET", MAC + "/");
  TOKEN = (pag.corpo.match(/window\.CC_TOKEN = "([^"]+)"/) || [])[1] || "";
  esito("token della copia letto (mai stampato)", !!TOKEN);
  const S3 = crypto.randomUUID();
  const vecchi = [
    { chi: "io", testo: "Vecchia domanda solo locale", ora: "10:00" },
    { chi: "lui", testo: "Vecchia risposta solo locale", ora: "10:01" },
    { chi: "io", testo: "Domanda mai partita", ora: "10:05" },
    { chi: "lui", testo: "Command Center non raggiungibile", errore: true, ora: "10:05" },
  ];
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true,
    userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), "fili-chrome-")), args: ["--no-first-run", "--no-default-browser-check"] });
  let A, B;
  try {
    A = await apri(browser, { base: MAC, disp: "desktop", seme: { "cc.fili": { jarvis: { sessione: S3, avviata: true, messaggi: vecchi } }, "cc.chatCon": "jarvis" } });
    B = await apri(browser, { base: PONTE, disp: "iphone14", cookie: COOKIE });
    esito("A (Mac, desktop 1440) e B (iPhone 14 dal ponte) caricano la pagina", A.stato === 200 && B.stato === 200, `${A.stato} ${B.stato}`);
    await attesa(1500);
    if (A.reg.errori.length || B.reg.errori.length) console.log("(errori JS all'avvio: " + JSON.stringify([A.reg.errori, B.reg.errori, A.reg.console, B.reg.console]).slice(0, 800) + ")");
    let a = (await finche(A.page, (f) => f.fili && f.fili.attivo === true && f.fili.letture >= 1, 15000)).f;
    let b = (await finche(B.page, (f) => f.fili && f.fili.attivo === true && f.fili.letture >= 1, 15000)).f;
    esito("fili.js attivo su A e su B (GET /api/fili risponde, anche attraverso il ponte)", a.fili && a.fili.attivo && b.fili && b.fili.attivo,
      JSON.stringify([a.fili, b.fili]).slice(0, 200));
    esito("B è davvero dentro il ponte (PONTE.dentro)", b.ponte === true && a.ponte === false, `${a.ponte} ${b.ponte}`);
    esito("A: la chat vecchia del localStorage resta com'era (il server ha solo fili più vecchi di lei)",
      a.sessione === S3 && a.messaggi.length === 4 && a.messaggi.every((m, i) => m.testo === vecchi[i].testo), JSON.stringify(a.messaggi).slice(0, 200));

    // 1. una domanda nel filo di A, mandata da «un altro dispositivo» (questo programma)
    const q1 = "Domanda arrivata dal server numero uno";
    const t0 = Date.now();
    const r1 = await chiedi(S3, q1);
    const lid1 = r1.lavoro && r1.lavoro.id;
    let rb = await finche(B.page, (f) => f.sessione === S3 && conta(f, q1) === 1 && contaDom(f, q1) === 1, 8000);
    esito(`B: la domanda compare (passa al filo nuovo) entro 5 s · ${rb.ms} ms`, rb.ms !== null && Date.now() - t0 < 5000 + 500 && rb.ms < 5000,
      JSON.stringify(rb.f.messaggi.slice(-3)));
    rb = await finche(B.page, (f) => f.lavora && f.attesa && f.attesa.id === lid1, 3000);
    esito("B: mostra «sta lavorando» mentre il Mac lavora (attesa presa dal server)", rb.ms !== null, JSON.stringify(rb.f.attesa));
    let ra = await finche(A.page, (f) => conta(f, q1) === 1 && contaDom(f, q1) === 1, 8000);
    esito(`A: la domanda compare nella chat aperta entro 5 s · ${ra.ms} ms`, ra.ms !== null && ra.ms < 5000, JSON.stringify(ra.f.messaggi.slice(-3)));
    const risp1 = "Risposta finta a: " + q1;
    rb = await finche(B.page, (f) => contaDom(f, risp1) === 1 && !f.attesa, 15000);
    ra = await finche(A.page, (f) => contaDom(f, risp1) === 1 && !f.attesa, 15000);
    esito("B: arriva la risposta, l'attesa finisce", rb.ms !== null, JSON.stringify(rb.f.messaggi.slice(-2)));
    esito("A: arriva la risposta, l'attesa finisce", ra.ms !== null, JSON.stringify(ra.f.messaggi.slice(-2)));
    await attesa(2500);                                       // un paio di giri in più: niente doppioni che arrivano tardi
    a = await filoDi(A.page); b = await filoDi(B.page);
    esito("A: nessun doppione (domanda e risposta una volta sola, nei dati e nella pagina)",
      conta(a, q1) === 1 && conta(a, risp1) === 1 && contaDom(a, q1) === 1 && contaDom(a, risp1) === 1, JSON.stringify(a.messaggi));
    esito("B: nessun doppione", conta(b, q1) === 1 && conta(b, risp1) === 1 && contaDom(b, risp1) === 1, JSON.stringify(b.messaggi));
    esito("A: i messaggi solo locali (anche la domanda mai partita) restano, prima dei nuovi",
      vecchi.every((v) => conta(a, v.testo) === 1) && a.messaggi.findIndex((m) => m.testo === "Domanda mai partita") < a.messaggi.findIndex((m) => m.testo === q1),
      JSON.stringify(a.messaggi.map((m) => m.testo)));
    esito("A e B: id del server sui messaggi (q-/a- con l'id del lavoro)",
      a.messaggi.some((m) => m.fid === "q-" + lid1) && a.messaggi.some((m) => m.fid === "a-" + lid1) && b.messaggi.some((m) => m.fid === "a-" + lid1));
    esito("B: ha solo i messaggi del server (nessuno dei vecchi locali di A)", b.messaggi.length === 2, JSON.stringify(b.messaggi.map((m) => m.testo)));

    // 2. seconda domanda: tutte e due si aggiornano ancora
    const q2 = "Seconda domanda dal server";
    const risp2 = "Risposta finta a: " + q2;
    const r2 = await chiedi(S3, q2);
    rb = await finche(B.page, (f) => contaDom(f, risp2) === 1, 15000);
    ra = await finche(A.page, (f) => contaDom(f, risp2) === 1, 15000);
    esito("seconda domanda: risposta su A e su B", ra.ms !== null && rb.ms !== null);
    await A.page.screenshot({ path: path.join(SCHERMATE, "fili-A-mac-desktop-1440.png") });
    await B.page.screenshot({ path: path.join(SCHERMATE, "fili-B-iphone14-ponte.png") });

    // 3. «togli dalla chat» su A: quel messaggio non torna dal server, su B resta
    const tolto = await A.page.evaluate((testo) => {
      const nodi = [...document.querySelectorAll("#messaggi .msg")];
      const n = nodi.find((x) => (x.querySelector(".testo") || {}).textContent === testo);
      const b = n && [...n.querySelectorAll("button")].find((x) => x.title === "Togli dalla chat");
      if (b) b.click();
      return !!b;
    }, risp2);
    await A.page.evaluate(() => window.CCFili.sincronizza());
    const q3 = "Terza domanda dopo il togli";
    await chiedi(S3, q3);
    ra = await finche(A.page, (f) => contaDom(f, "Risposta finta a: " + q3) === 1, 15000);
    a = ra.f;
    b = (await finche(B.page, (f) => contaDom(f, "Risposta finta a: " + q3) === 1, 15000)).f;
    esito("A: il messaggio tolto a mano non torna dal server (e gli altri arrivano)", tolto && conta(a, risp2) === 0 && ra.ms !== null,
      JSON.stringify(a.messaggi.map((m) => m.testo)));
    esito("B: lo stesso messaggio resta (togliere è di quel dispositivo)", conta(b, risp2) === 1);

    // 4. ricarica di A: tutto resta, nessun doppione
    await A.page.reload({ waitUntil: "domcontentloaded" });
    ra = await finche(A.page, (f) => f.fili && f.fili.letture >= 1, 10000);
    await attesa(1500);
    a = await filoDi(A.page);
    esito("A ricaricata: stessa chat, nessun doppione, vecchi locali ancora lì", a.sessione === S3 && conta(a, q1) === 1 && conta(a, risp1) === 1
      && conta(a, q3) === 1 && conta(a, "Domanda mai partita") === 1 && conta(a, risp2) === 0, JSON.stringify(a.messaggi.map((m) => m.testo)));

    // 5. «svuota» su B: B riparte vuota e non riprende né quel filo né quelli più vecchi
    await B.page.evaluate(() => document.getElementById("btn-svuota-chat").click());
    await attesa(300);
    b = await filoDi(B.page);
    const sB = b.sessione;
    esito("B: svuota = chat nuova vuota", sB !== S3 && b.messaggi.length === 0, JSON.stringify(b).slice(0, 200));
    const q4 = "Quarta domanda dopo lo svuota di B";
    await chiedi(S3, q4);
    ra = await finche(A.page, (f) => contaDom(f, "Risposta finta a: " + q4) === 1, 15000);
    await B.page.evaluate(() => window.CCFili.sincronizza());
    await attesa(2000);
    b = await filoDi(B.page);
    esito("B svuotata: non riprende il filo lasciato né i fili più vecchi; A continua", b.sessione === sB && b.messaggi.length === 0 && ra.ms !== null,
      JSON.stringify(b).slice(0, 200));
    // e un filo nuovo nato dopo lo svuota (un altro dispositivo che riparte) sì
    const S4 = crypto.randomUUID();
    const q5 = "Filo nuovo nato dopo";
    await chiedi(S4, q5);
    rb = await finche(B.page, (f) => f.sessione === S4 && conta(f, q5) === 1, 8000);
    esito("B: un filo più nuovo dello svuota invece arriva", rb.ms !== null, JSON.stringify(rb.f).slice(0, 200));
    ra = await finche(A.page, (f) => f.sessione === S4 && conta(f, q5) === 1, 8000);
    esito("A: passa anche lei al filo più nuovo; la sua chat con messaggi solo locali è messa da parte",
      ra.ms !== null && await A.page.evaluate((s) => (JSON.parse(localStorage.getItem("cc.fili-da-parte") || "[]")).some((x) => x.sessione === s), S3),
      JSON.stringify(ra.f).slice(0, 200));
    await attesa(5000);                    // la risposta del filo nuovo
    await A.page.screenshot({ path: path.join(SCHERMATE, "fili-A-mac-dopo-filo-nuovo.png") });
    await B.page.screenshot({ path: path.join(SCHERMATE, "fili-B-iphone14-dopo-filo-nuovo.png") });

    // 6. pulizia: nessun errore JS, nessun POST uscito dalle pagine
    esito("nessun errore JavaScript nelle pagine", !A.reg.errori.length && !B.reg.errori.length, JSON.stringify([A.reg.errori, B.reg.errori]));
    console.log(`(POST delle pagine, tutti abortiti: A ${A.reg.post.length} [${[...new Set(A.reg.post.map((x) => x.split(" ")[0]))].join(", ")}], ` +
      `B ${B.reg.post.length} [${[...new Set(B.reg.post.map((x) => x.split(" ")[0]))].join(", ")}])`);
    esito("nessun POST di chat o di fili uscito dalle pagine (tutti abortiti, nessun «chiedi»)",
      ![...A.reg.post, ...B.reg.post].some((x) => /"tipo":"chiedi"|\/api\/fili/.test(x)));
    console.log(`(schermate in ${SCHERMATE})`);
  } catch (e) {
    esito("la prova del browser finisce senza eccezioni", false, e.stack || e);
  } finally {
    await browser.close().catch(() => {});
  }
  const ok = RIS.filter(Boolean).length;
  console.log(`Totale browser: ${ok}/${RIS.length} PASS`);
  process.exit(ok === RIS.length ? 0 : 1);
})();
