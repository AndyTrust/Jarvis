// Service worker del Command Center: serve a renderlo installabile come app.
// Rete prima di tutto. In cache vanno SOLO i file statici senza segreti (/static/…).
// 🔴 2026-10-03 (REVISIONE-2, F2): fino alla v12 qui finiva in cache ogni GET che non fosse /api/ o /term/,
// quindi anche «/» (con window.CC_TOKEN) e /vps-fuori/<gettone> (con la password del desktop VPS), che poi
// tornavano senza rete ignorando no-store. Ora: le navigazioni non si salvano mai, e senza rete al loro posto
// c'è una paginetta che dice solo che il Mac non risponde. La v13 cancella all'attivazione le cache vecchie.
const CACHE = "jarvis-cc-v14";
const GUSCIO = ["/static/app.css", "/static/app.js", "/static/icona-192.png", "/static/logo.svg"];
// mai in cache, nemmeno se un giorno arrivassero da /static/
const MAI = [/^\/api\//, /^\/term\//, /^\/vps/, /^\/pc-desktop/, /^\/assistenza/, /^\/tecnico/, /^\/_ponte\//];

const SENZA_RETE = `<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis non raggiungibile</title><body style="font:16px system-ui;background:#141414;color:#f0f0f0;padding:24px">
<h1 style="font-size:20px">Jarvis non risponde</h1><p>Il Command Center sul Mac non è raggiungibile. Riprova quando è acceso.</p></body></html>`;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(GUSCIO)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((k) => Promise.all(k.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || MAI.some((r) => r.test(url.pathname))) return;
  // le pagine (con il token, le password, i gettoni): solo rete; senza rete la paginetta, mai una copia
  if (req.mode === "navigate" || req.destination === "document" || !url.pathname.startsWith("/static/")) {
    if (req.mode === "navigate") {
      e.respondWith(fetch(req).catch(() => new Response(SENZA_RETE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } })));
    }
    return;
  }
  // /static/: rete prima, copia solo delle risposte buone e salvabili
  e.respondWith(fetch(req).then((r) => {
    const cc = r.headers.get("Cache-Control") || "";
    if (r.ok && r.type === "basic" && !/no-store|private/i.test(cc)) {
      const copia = r.clone();
      caches.open(CACHE).then((c) => c.put(req, copia));
    }
    return r;
  }).catch(() => caches.match(req, { ignoreSearch: true })));
});
