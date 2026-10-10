#!/usr/bin/env python3
"""Prove automatiche della riunione degli agenti (strumenti/riunione.py e backtest_check.py).

Creato il 2026-09-30. Tutto in una cartella temporanea: configurazione di prova, schede di
prova, report di prova. Non tocca il vault, Report né le riunioni vere. Solo unittest.

Uso:  python3 strumenti/prova_riunione.py      (esce 1 se una prova fallisce)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

QUI = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="prova-riunione-"))
os.environ["RIUNIONE_RADICE"] = str(TMP / "riunioni")
os.environ["RIUNIONE_REPORT_DIR"] = str(TMP / "report")
os.environ["RIUNIONE_STRATEGIE_DIR"] = str(TMP / "Strategie")
os.environ["RIUNIONE_CONFIG"] = str(TMP / "gruppi.json")
os.environ["RIUNIONE_OGGI"] = "2026-09-30"

sys.path.insert(0, str(QUI))
import backtest_check as B  # noqa: E402
import riunione as R  # noqa: E402

GIORNO = date(2026, 9, 30)


def zitto(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        esito = fn(*a)
    return esito, buf.getvalue()


def prepara_ambiente():
    (TMP / "Strategie").mkdir(exist_ok=True)
    (TMP / "profili").mkdir(exist_ok=True)
    (TMP / "profili" / "capo.md").write_text("---\nname: capo\nmodel: sonnet\n---\nIl capo di prova.\n", encoding="utf-8")
    (TMP / "profili" / "spec.md").write_text("---\nname: spec\nmodel: haiku\n---\nLo specialista di prova.\n", encoding="utf-8")
    (TMP / "a.md").write_text("Il conto vero è 1.550 EUR.\n", encoding="utf-8")
    (TMP / "b.md").write_text("conto ~1500 €\n", encoding="utf-8")
    (TMP / "scadenze.md").write_text("- [ ] 2026-09-20 · rata vecchia\n- [ ] 2026-10-03 · rata vicina\n"
                                     "- [x] 2026-09-01 → chiusa · fatta\n- [ ] 2027-01-01 · lontana\n", encoding="utf-8")
    cfg = {"grazia_giorni": 30, "gruppi": {"prova": {
        "nome": "Gruppo di prova", "spazio": "Prova", "modo": "interno",
        "capogruppo": {"agente": "capo", "profilo": str(TMP / "profili" / "capo.md")},
        "revisore": {"agente": "rev", "profilo": str(TMP / "profili" / "manca.md")},
        "membri": [{"agente": "spec", "profilo": str(TMP / "profili" / "spec.md"), "temi": ["tema uno"]}],
        "fonti": [{"nome": "file a", "percorso": str(TMP / "a.md"), "max_giorni": 5},
                  {"nome": "assente", "percorso": str(TMP / "non-c-e.md")},
                  {"nome": "database", "solo_agenti": True, "nota": "sola lettura"}],
        "scadenze": [str(TMP / "scadenze.md")],
        "metriche": [{"nome": "capitale", "tolleranza": 0.02, "fonti": [
            {"file": str(TMP / "a.md"), "cerca": "è ([\\d.,]+) EUR"},
            {"file": str(TMP / "b.md"), "cerca": "~([\\d.,]+) €"}]}],
        "strategie": str(TMP / "Strategie"), "report": str(TMP / "report")}}}
    (TMP / "gruppi.json").write_text(json.dumps(cfg), encoding="utf-8")
    scheda = {
        "id": "prova-uno", "gruppo": "prova", "titolo": "Strategia di prova", "versione": "V1", "stato": "prova",
        "ipotesi": "i numeri tornano", "regola": "compra: basso, vende: alto",
        "taratura": {"da": "2011-01", "a": "2018-12"}, "prova": {"da": "2019-01", "a": "2026-08"},
        "previsioni": [
            {"data": "2025-01-10", "orizzonte": "12 mesi", "metrica": "EUR/anno", "atteso": 40, "intervallo": [20, 60],
             "fonte": "finta", "realizzato": None, "data_esito": None, "errore": None, "dentro_intervallo": None, "esito": "aperta"},
            {"data": "2026-09-01", "orizzonte": "3 mesi", "metrica": "operazioni", "atteso": 10, "intervallo": [8, 12],
             "fonte": "finta", "realizzato": None, "data_esito": None, "errore": None, "dentro_intervallo": None, "esito": "aperta"},
            {"data": "senza data", "orizzonte": "corsa nel tester", "metrica": "PF", "atteso": 1.4, "intervallo": None,
             "fonte": "finta", "realizzato": None, "data_esito": None, "errore": None, "dentro_intervallo": None, "esito": "senza data"},
            {"data": "2026-06-01", "orizzonte": "2 mesi", "metrica": "DD %", "atteso": 20, "intervallo": [15, 25],
             "fonte": "finta", "realizzato": None, "data_esito": None, "errore": None, "dentro_intervallo": None, "esito": "aperta"},
        ],
        "decisione": None, "versioni": [{"versione": "V1", "data": "2026-09-01", "cosa": "nasce"}],
    }
    (TMP / "Strategie" / "prova-uno.md").write_text(R.testo_scheda(scheda, "\n# Strategia di prova\n\nTesto: con i due punti.\n"),
                                                   encoding="utf-8")
    cattiva = dict(scheda, id="prova-futuro", previsioni=[], taratura={"da": "2011-01", "a": "2020-12"},
                   prova={"da": "2019-01", "a": "2026-08"})
    (TMP / "Strategie" / "prova-futuro.md").write_text(R.testo_scheda(cattiva, "\n# Guarda il futuro\n"), encoding="utf-8")


class ProvaBacktest(unittest.TestCase):
    def righe(self):
        # 2018: realizzato 10 ogni mese (la base banale vale 10); 2019: previsto 12, realizzato 12 o 20
        out = [{"periodo": f"2018-{m:02d}", "realizzato": 10} for m in range(1, 13)]
        for m in range(1, 13):
            out.append({"periodo": f"2019-{m:02d}", "realizzato": 12 if m <= 6 else 20,
                        "previsto": 12, "basso": 9, "alto": 15})
        return out

    def test_sguardo_al_futuro(self):
        self.assertEqual(B.periodi_ok(B.intervallo("2011-01:2018-12"), B.intervallo("2019-01:2026-08")), [])
        err = B.periodi_ok(B.intervallo("2011-01:2019-06"), B.intervallo("2019-01:2026-08"))
        self.assertTrue(any("sguardo al futuro" in e for e in err))
        self.assertEqual(B.fine_periodo("2016"), B.mese("2016-12"))

    def test_riga_taratura_dentro_la_prova(self):
        f = TMP / "fase.json"
        f.write_text(json.dumps([{"periodo": "2019-03", "realizzato": 1, "fase": "taratura"}]), encoding="utf-8")
        esito = B.controlla(B.carica(f), B.intervallo("2011-01:2018-12"), B.intervallo("2019-01:2019-12"))
        self.assertTrue(esito["sguardo_al_futuro"])

    def test_errore_copertura_base(self):
        f = TMP / "risultati.csv"
        rr = self.righe()
        f.write_text("periodo,realizzato,previsto,basso,alto\n" + "\n".join(
            f"{r['periodo']},{r['realizzato']},{r.get('previsto', '')},{r.get('basso', '')},{r.get('alto', '')}" for r in rr),
            encoding="utf-8")
        e = B.controlla(B.carica(f), B.intervallo("2011-01:2018-12"), B.intervallo("2019-01:2019-12"))
        self.assertFalse(e["sguardo_al_futuro"])
        self.assertEqual(e["base_banale"], 10)
        o1, o3, o12 = e["orizzonti"]["1"], e["orizzonti"]["3"], e["orizzonti"]["12"]
        self.assertEqual((o1["errore_medio"], o1["copertura"], o1["errore_base"], o1["batte_la_base"]), (0, 1, 2, True))
        self.assertEqual((o3["errore_medio"], o3["copertura"]), (0, 1))
        # 12 mesi: 6 mesi errore 0, 6 mesi errore 8 -> 4; copertura 6/12; base: 6x2 + 6x10 -> 6
        self.assertEqual((o12["errore_medio"], o12["copertura"], o12["errore_base"]), (4, 0.5, 6))
        self.assertTrue(o12["batte_la_base"])

    def test_dati_insufficienti(self):
        f = TMP / "corto.json"
        f.write_text(json.dumps({"righe": [{"periodo": "2019-01", "realizzato": "3,5", "previsto": 3}]}), encoding="utf-8")
        e = B.controlla(B.carica(f), B.intervallo("2018-01:2018-12"), B.intervallo("2019-01:2019-02"))
        self.assertEqual(e["orizzonti"]["1"]["errore_medio"], 0.5)
        self.assertIsNone(e["orizzonti"]["1"]["errore_base"])
        self.assertEqual(e["orizzonti"]["3"]["esito"], "dati insufficienti")
        self.assertEqual(e["orizzonti"]["12"]["esito"], "dati insufficienti")

    def test_riga_di_comando(self):
        f = TMP / "cli.json"
        f.write_text(json.dumps(self.righe()), encoding="utf-8")
        esito, out = zitto(B.main, [str(f), "--taratura", "2011-01:2019-02", "--prova", "2019-01:2019-12"])
        self.assertEqual(esito, 1)
        self.assertIn("sguardo al futuro", out)


class ProvaRiunione(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepara_ambiente()
        cls.gid, cls.g = R.gruppo("Gruppo di prova")

    def test_01_scheda_si_rilegge_uguale(self):
        meta, corpo = R.leggi_scheda(TMP / "Strategie" / "prova-uno.md")
        self.assertEqual(meta["id"], "prova-uno")
        self.assertEqual(meta["taratura"], {"da": "2011-01", "a": "2018-12"})
        self.assertEqual(len(meta["previsioni"]), 4)
        self.assertIsNone(meta["previsioni"][0]["realizzato"])
        self.assertIn("con i due punti", corpo)

    def test_02_scadenze_delle_previsioni(self):
        self.assertEqual(R.scadenza({"data": "2025-01-10", "orizzonte": "12 mesi"}), date(2026, 1, 10))
        self.assertEqual(R.scadenza({"data": "2026-01-31", "orizzonte": "1 mese"}), date(2026, 2, 28))
        self.assertIsNone(R.scadenza({"data": "senza data", "orizzonte": "12 mesi"}))
        sc = R.previsioni_scadute(self.g, GIORNO)
        self.assertEqual(sorted((s["id"], s["n"]) for s in sc), [("prova-uno", 1), ("prova-uno", 4)])

    def test_03_prepara(self):
        esito, out = zitto(R.cmd_prepara, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 0, out)
        cart = R.cartella_giorno(self.gid, GIORNO)
        for nome in ("dati.md", "controlli.md", "controlli.json", "LEGGIMI.md",
                     "compiti/spec.md", "compiti/revisore.md", "compiti/capogruppo.md"):
            self.assertTrue((cart / nome).exists(), nome)
        c = json.loads((cart / "controlli.json").read_text(encoding="utf-8"))
        self.assertEqual(c["metriche"][0]["esito"], "discordante")
        self.assertEqual([v["valore"] for v in c["metriche"][0]["valori"]], [1550, 1500])
        self.assertEqual([s["tipo"] for s in c["scadenze"]], ["scaduta", "entro 7 giorni"])
        self.assertEqual({f["stato"] for f in c["fonti"]}, {"ok", "manca", "solo agenti"})
        tipi = {(s["id"], s["tipo"]) for s in c["strategie"]}
        self.assertIn(("prova-futuro", "periodi"), tipi)
        self.assertIn(("prova-uno", "senza data"), tipi)
        self.assertIn(("prova-uno", "scaduta senza esito"), tipi)
        self.assertEqual([p["agente"] for p in c["profili_mancanti"]], ["rev"])
        compito = (cart / "compiti" / "spec.md").read_text(encoding="utf-8")
        self.assertTrue(compito.startswith("Modello: haiku"))
        self.assertIn("## Cambiato da ieri", compito)
        self.assertIn("Nessun ordine reale", compito)
        self.assertIn("general-purpose", (cart / "LEGGIMI.md").read_text(encoding="utf-8"))

    def test_04_chiudi_rifiuta_json_sbagliato(self):
        cart = R.cartella_giorno(self.gid, GIORNO)
        (cart / "riunione.json").write_text(json.dumps({
            "gruppo": "prova", "data": "2026-09-30", "temi": [{"tema": "x", "verdetto": "forse", "perche": "y"}],
            "strategie": [{"id": "non-esiste", "verdetto": "continuare", "perche": "z"}],
            "importanti": [{"cosa": str(i), "cambia": "rischio", "fonte": "f"} for i in range(6)],
            "approfondire": [{"cosa": "a"}], "decisioni": [{"domanda": "d"}], "non_verificato": [],
            "revisore": {"esito": "boh"}}), encoding="utf-8")
        esito, out = zitto(R.cmd_chiudi, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 2)
        for pezzo in ("tema 1", "non-esiste", "massimo è 5", "costo", "incarico", "revisore.esito"):
            self.assertIn(pezzo, out)
        self.assertFalse(R.file_report(self.gid, self.g, GIORNO).exists())
        (cart / "riunione.json").unlink()

    def test_05_prepara_poi_chiudi_idempotente(self):
        cart = R.cartella_giorno(self.gid, GIORNO)
        (cart / "posizioni" / "spec.md").write_text(
            "# Posizione\n\n## Fatti\n- a\n\n## Cambiato da ieri\n- b\n\n## Dubbi\n\n## Proposta\n\n## Non verificato\n",
            encoding="utf-8")
        self.assertEqual(R.valida_posizione(cart / "posizioni" / "spec.md"), [])
        (cart / "riunione.json").write_text(json.dumps({
            "gruppo": "prova", "data": "2026-09-30",
            "temi": [{"tema": "capitale", "verdetto": "da approfondire", "perche": "due fonti discordano"}],
            "strategie": [{"id": "prova-uno", "verdetto": "correggere", "perche": "previsione scaduta",
                           "incarico": "misurare di nuovo nel tester"}],
            "importanti": [{"cosa": "il capitale scritto è diverso in due file", "cambia": "rischio", "fonte": "a.md, b.md"}],
            "approfondire": [{"cosa": "capitale vero", "costo": "5 minuti sul terminale", "chi": "analista"}],
            "decisioni": [], "non_verificato": ["il saldo di oggi"], "revisore": {"esito": "ok", "note": []}}),
            encoding="utf-8")
        esito, out = zitto(R.cmd_chiudi, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 0, out)
        rep = R.file_report(self.gid, self.g, GIORNO)
        testo = rep.read_text(encoding="utf-8")
        self.assertIn("## Cosa cambia", testo)
        self.assertIn("costo del controllo: 5 minuti", testo)
        self.assertIn("prova-uno: il capogruppo propone di correggere", testo)
        self.assertIn("Incarico se dici sì: misurare di nuovo nel tester", testo)
        self.assertLessEqual(len(testo.splitlines()), 60, "il report deve stare in una pagina")
        meta, _ = R.leggi_scheda(TMP / "Strategie" / "prova-uno.md")
        self.assertEqual(meta["decisione"]["esito"], "correggere")
        # la previsione 4 è scaduta il 2026-08-01, oltre i 30 giorni di grazia; la 1 il 2026-01-10
        esiti = [p["esito"] for p in meta["previsioni"]]
        self.assertEqual(esiti, ["scaduta senza dati", "aperta", "senza data", "scaduta senza dati"])
        self.assertTrue((TMP / "Strategie" / "Strategie.md").exists())
        # seconda volta: non riscrive
        prima = rep.stat().st_mtime_ns
        esito, out = zitto(R.cmd_chiudi, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 0)
        self.assertIn("già chiusa", out)
        self.assertEqual(rep.stat().st_mtime_ns, prima)
        # e prepara non rifà la riunione
        esito, out = zitto(R.cmd_prepara, self.gid, self.g, GIORNO)
        self.assertIn("già fatta", out)

    def test_06_niente_di_nuovo(self):
        giorno = date(2026, 10, 1)
        cart = R.cartella_giorno(self.gid, giorno)
        zitto(R.cmd_prepara, self.gid, self.g, giorno)
        self.assertIn("2026-09-30", (cart / "compiti" / "spec.md").read_text(encoding="utf-8"),
                      "il compito deve indicare la riunione di ieri")
        (cart / "riunione.json").write_text(json.dumps({
            "gruppo": "prova", "data": "2026-10-01", "temi": [], "strategie": [], "importanti": [],
            "approfondire": [], "decisioni": [], "non_verificato": [], "revisore": {"esito": "ok"}}), encoding="utf-8")
        esito, out = zitto(R.cmd_chiudi, self.gid, self.g, giorno)
        self.assertEqual(esito, 0, out)
        self.assertIn("Niente di nuovo.", R.file_report(self.gid, self.g, giorno).read_text(encoding="utf-8"))

    def test_07_chiudi_previsione(self):
        p = R.chiudi_previsione(self.g, "prova-uno", 2, 13.0, "tester", GIORNO)
        self.assertEqual((p["errore"], p["dentro_intervallo"], p["esito"]), (3.0, False, "fallita"))
        with self.assertRaises(SystemExit):
            R.chiudi_previsione(self.g, "prova-uno", 2, 10.0, None, GIORNO)
        p = R.chiudi_previsione(self.g, "prova-uno", 3, 1.5, None, GIORNO)
        self.assertEqual(p["esito"], "chiusa senza intervallo")
        self.assertIn("non conta come prova", p["nota_esito"])

    def test_08_non_si_cancellano_previsioni(self):
        f = TMP / "Strategie" / "prova-uno.md"
        meta, corpo = R.leggi_scheda(f)
        meta["previsioni"] = meta["previsioni"][:1]
        with self.assertRaises(RuntimeError):
            R.scrivi_scheda(f, meta, corpo)
        meta, corpo = R.leggi_scheda(f)
        meta["previsioni"][1]["realizzato"] = 99
        with self.assertRaises(RuntimeError):
            R.scrivi_scheda(f, meta, corpo)

    def test_09_stato_e_strategie(self):
        esito, out = zitto(R.cmd_stato, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 0)
        self.assertIn("posizione spec: ok", out)
        self.assertIn("riunione.json: sì", out)
        esito, out = zitto(R.cmd_strategie, self.gid, self.g, GIORNO)
        self.assertEqual(esito, 0)
        self.assertIn("senza data: non conta", out)
        indice = (TMP / "Strategie" / "Strategie.md").read_text(encoding="utf-8")
        self.assertIn("[[prova-uno]]", indice)
        self.assertIn("0 su 1 previsioni chiuse con intervallo", indice)

    def test_10_numeri_italiani(self):
        self.assertEqual(R.numero_it("1.550"), 1550)
        self.assertEqual(R.numero_it("3,5"), 3.5)
        self.assertEqual(R.numero_it("-12.5"), -12.5)
        self.assertEqual(R.numero_it("1.234,5"), 1234.5)


if __name__ == "__main__":
    prog = unittest.main(exit=False, verbosity=2)
    print(f"cartella di prova: {TMP}")
    sys.exit(0 if prog.result.wasSuccessful() else 1)
