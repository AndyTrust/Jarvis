// Il tasto «■ Ferma» della chat (l'utente, 2026-10-04: «nella chat manca il tasto stop»). Mentre Jarvis sta rispondendo il tasto
// invio (↑) si nasconde e al suo posto compare ■: ferma il lavoro della chat con la stessa azione «ferma» del tasto «■ ferma» dei lavori
// (app.js). Vale anche dal telefono (la rotta «ferma» passa dal ponte). Si ferma anche con il tasto Esc. Non tocca app.js: legge
// THREADS, chatCon e azione(), che app.js definisce a livello globale.
(function stopChat() {
  "use strict";
  const invia = document.getElementById("btn-invia");
  if (!invia || document.getElementById("btn-ferma")) return;
  const stop = document.createElement("button");
  stop.type = "button";
  stop.id = "btn-ferma";
  stop.className = "invia ferma";
  stop.hidden = true;
  stop.textContent = "■";
  stop.title = "Ferma Jarvis (Esc)";
  stop.setAttribute("aria-label", "Ferma Jarvis");
  invia.after(stop);

  function lavoroInAttesa() {
    try {
      const t = typeof THREADS !== "undefined" && typeof chatCon !== "undefined" ? THREADS[chatCon] : null;
      return t && t.attesa && t.attesa.id ? t.attesa : null;
    } catch (e) { return null; }
  }
  function aggiorna() {
    const a = lavoroInAttesa();
    stop.hidden = !a;
    invia.hidden = !!a;
    if (!a) stop.disabled = false;
  }
  async function ferma() {
    const a = lavoroInAttesa();
    if (!a || stop.disabled) return;
    stop.disabled = true;
    a.fermato = true;           // seguiRisposteGiro di app.js scrive «(fermato da te)» invece di «(nessuna risposta)»
    try {
      if (typeof azione === "function") await azione({ tipo: "ferma", id: a.id }, stop);
    } catch (e) { /* il messaggio d'errore lo mostra azione() */ }
    setTimeout(() => { stop.disabled = false; aggiorna(); }, 600);
  }
  stop.addEventListener("click", ferma);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && lavoroInAttesa() && !ev.defaultPrevented && !document.querySelector("dialog[open]")) ferma();
  });
  new MutationObserver(aggiorna).observe(invia, { attributes: true, attributeFilter: ["disabled"] });
  setInterval(aggiorna, 500);
  aggiorna();
})();
