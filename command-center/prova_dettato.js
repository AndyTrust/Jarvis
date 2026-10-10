// Prova di static/dettato.js: node command-center/prova_dettato.js
const { unisci } = require("./static/dettato.js");
let ko = 0;
const R = (t, fin = false) => Object.assign([{ transcript: t }], { isFinal: fin });
const chk = (nome, cond, v) => { if (!cond) { ko++; console.log("KO ", nome, JSON.stringify(v)); } else console.log("ok ", nome); };
// 1. Android: le ipotesi crescono (il caso incollato dall'utente)
let r = [R("Ascolta"), R("Ascolta ti"), R("Ascolta ti voglio"), R("Ascolta ti voglio chiedere"), R("Ascolta ti voglio chiedere"), R("Ascolta ti voglio chiedere una cortesia")];
chk("android: ipotesi crescenti = una sola frase", unisci(r).testo === "Ascolta ti voglio chiedere una cortesia", unisci(r));
// 2. Android: l'ultima diventa finale
r = [R("Ascolta"), R("Ascolta ti"), R("Ascolta ti voglio chiedere", true)];
chk("android: l'ultima finale chiude la frase", unisci(r).fissa === "Ascolta ti voglio chiedere" && unisci(r).provv === "", unisci(r));
// 3. desktop: segmenti finali separati + una provvisoria
r = [R("ciao Jarvis", true), R("come stai", true), R("oggi vorrei")];
chk("desktop: frasi finali separate e provvisoria", unisci(r).testo === "ciao Jarvis come stai oggi vorrei" && unisci(r).fissa === "ciao Jarvis come stai", unisci(r));
// 4. una parola ripetuta davvero in due frasi finali resta
r = [R("ciao", true), R("ciao", true)];
chk("due frasi finali uguali restano due", unisci(r).testo === "ciao ciao", unisci(r));
// 5. nuova frase dopo una finale con inizio uguale
r = [R("sì", true), R("sì certo")];
chk("dopo una finale la frase nuova non si fonde", unisci(r).testo === "sì sì certo", unisci(r));
// 6. maiuscole diverse nel prefisso
r = [R("ascolta ti"), R("Ascolta ti voglio")];
chk("maiuscole diverse: sostituisce", unisci(r).testo === "Ascolta ti voglio", unisci(r));
// 7. vuoti e null
chk("vuoto", unisci([]).testo === "" && unisci(null).testo === "" && unisci([R("  ")]).testo === "", unisci([]));
// 8. frase lunga con ripetizioni cumulative come nel testo dell'utente
const parole = "Ascolta ti voglio chiedere una cortesia Se mi senti bene Non voglio che mi ripete tutte le cose degli script che stai facendo".split(" ");
r = []; for (let i = 1; i <= parole.length; i++) { r.push(R(parole.slice(0, i).join(" "))); if (i % 3 === 0) r.push(R(parole.slice(0, i).join(" "))); }
chk("frase lunga cumulativa con doppioni", unisci(r).testo === parole.join(" "), unisci(r).testo.slice(0, 80));
console.log(ko ? ko + " KO" : "tutto ok"); process.exit(ko ? 1 : 0);
