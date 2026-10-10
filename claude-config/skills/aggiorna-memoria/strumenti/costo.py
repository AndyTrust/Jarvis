#!/usr/bin/env python3
"""costo.py — chi ti sta mangiando il contesto, in ordine. Zero token.

`/context` dice quanto è pieno; questo dice **chi** l'ha riempito e quanto
costa ciascuno, distinguendo la spesa che paghi UNA VOLTA all'avvio da quella
che paghi a OGNI messaggio — che è la sola che si moltiplica.

    ./costo.py                  tutto
    ./costo.py <progetto>       includendo i CLAUDE.md di quel progetto
    ./costo.py --messaggi 20    quanto costano 20 scambi
"""
import argparse, json, os, re
from pathlib import Path

H = Path.home()
# 4 caratteri per token e' la regola INGLESE. L'italiano tokenizza peggio:
# misurato su ~/.claude/CLAUDE.md contro /context, 2.7 caratteri per token
# (2.146 caratteri = 809 token). Con /4 si sottostima del 50%.
CAR_PER_TOKEN_IT = 2.7
CAR_PER_TOKEN_EN = 4.0

def tok(x):
    if not isinstance(x, str):
        return int(x / CAR_PER_TOKEN_EN)
    # se e' pieno di accenti e parole italiane, usa il divisore italiano
    it = sum(x.count(c) for c in "àèéìòùÀÈÉÌÒÙ") + sum(
        x.lower().count(w) for w in (" che ", " non ", " sono ", " della ", " per "))
    return int(len(x) / (CAR_PER_TOKEN_IT if it > 3 else CAR_PER_TOKEN_EN))
def leggi(p):
    try: return p.read_text(encoding="utf-8", errors="ignore")
    except OSError: return ""

def frontmatter(p):
    t = leggi(p)
    m = re.match(r"^---\n(.*?)\n---", t, re.S)
    if not m: return None
    d = {}
    for k in ("name", "description"):
        mm = re.search(rf"^{k}:\s*(.+?)(?=\n\w+:|\Z)", m.group(1), re.S | re.M)
        if mm: d[k] = " ".join(mm.group(1).split())
    return d

def attivi():
    """quali plugin sono davvero accesi (globali meno gli spenti per progetto)"""
    acc = {}
    for f, seg in ((H/".claude/settings.json", None), (Path.cwd()/".claude/settings.json", None)):
        try: acc.update(json.loads(leggi(f)).get("enabledPlugins", {}))
        except Exception: pass
    # "nome@marketplace" -> marketplace acceso?
    mk = set()
    for k, v in acc.items():
        if v and "@" in k: mk.add(k.split("@", 1)[1])
    return acc, mk

def skills():
    """ogni skill costa nome+descrizione all'avvio, il corpo solo se invocata"""
    out = []
    radici = [(H/".claude/skills", "utente")]
    _, mk_attivi = attivi()
    pc = H/".claude/plugins/cache"
    if pc.is_dir():
        for m in pc.iterdir():
            if m.is_dir() and m.name in mk_attivi:
                radici.append((m, f"plugin:{m.name}"))
    visti = set()
    for radice, orig in radici:
        for s in radice.rglob("SKILL.md"):
            fm = frontmatter(s)
            if not fm or not fm.get("name"): continue
            k = (fm["name"], orig)
            if k in visti: continue
            visti.add(k)
            out.append({"nome": fm["name"], "origine": orig,
                        "avvio": tok(fm["name"] + fm.get("description", "")),
                        "corpo": tok(leggi(s))})
    return out

def main():
    ap = argparse.ArgumentParser(description="chi ti mangia il contesto")
    ap.add_argument("progetto", nargs="?")
    ap.add_argument("--messaggi", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ogni, avvio = [], []

    # --- a OGNI messaggio: i CLAUDE.md ---
    g = H/".claude/CLAUDE.md"
    if g.is_file(): ogni.append(("~/.claude/CLAUDE.md", tok(leggi(g))))
    if a.progetto:
        base = Path(a.progetto).expanduser().resolve()
        cm = base/"CLAUDE.md"
        if cm.is_file(): ogni.append((f"{base.name}/CLAUDE.md", tok(leggi(cm))))
        for sub in sorted(base.rglob("CLAUDE.md")):
            if sub != cm and ".claude" not in str(sub):
                ogni.append((f"  ↳ {sub.relative_to(base)} (solo entrando lì)", -tok(leggi(sub))))

    # --- a OGNI messaggio: gli hook UserPromptSubmit dei plugin ---
    inj = 0
    acc, mk_attivi = attivi()
    for hj in (H/".claude/plugins/cache").rglob("hooks/hooks.json") if (H/".claude/plugins/cache").is_dir() else []:
        parti = hj.parts
        try: mk = parti[parti.index("cache")+1]
        except ValueError: continue
        if mk not in mk_attivi: continue
        plug = parti[parti.index("cache")+2] if len(parti) > parti.index("cache")+2 else mk
        if not acc.get(f"{plug}@{mk}", False): continue
        try: hd = json.loads(leggi(hj))
        except Exception: continue
        if "UserPromptSubmit" in hd.get("hooks", {}):
            ogni.append((f"hook UserPromptSubmit · {plug}@{mk}", 300)); inj += 1

    # --- UNA VOLTA all'avvio: le skill ---
    sk = skills()
    tot_sk = sum(s["avvio"] for s in sk)
    avvio.append((f"descrizioni di {len(sk)} skill", tot_sk))

    # doppioni: stesso nome da origini diverse
    da_nome = {}
    for s in sk: da_nome.setdefault(s["nome"], []).append(s)
    doppie = {k: v for k, v in da_nome.items() if len(v) > 1}

    if a.json:
        print(json.dumps({"ogni_messaggio": ogni, "avvio": avvio,
                          "skill_doppie": {k: [x["origine"] for x in v] for k, v in doppie.items()}},
                         ensure_ascii=False, indent=2)); return

    print("\n╔═ A OGNI MESSAGGIO — questo si moltiplica")
    ogni_tot = 0
    for n, t in sorted(ogni, key=lambda x: -abs(x[1])):
        if t < 0: print(f"║  {n:<52} {abs(t):>6}  (non a ogni messaggio)")
        else: print(f"║  {n:<52} {t:>6}"); ogni_tot += t
    print(f"╠═ totale                                               {ogni_tot:>6} token/messaggio")
    print(f"╚═ su {a.messaggi} scambi:                                        "
          f"{ogni_tot*a.messaggi:>6} token")

    print("\n╔═ UNA VOLTA ALL'AVVIO — si paga e basta")
    av_tot = 0
    for n, t in sorted(avvio, key=lambda x: -x[1]):
        print(f"║  {n:<52} {t:>6}"); av_tot += t
    print(f"╚═ totale                                               {av_tot:>6} token")

    print(f"\nPer {a.messaggi} messaggi: {av_tot:,} una volta + {ogni_tot*a.messaggi:,} ricorrenti "
          f"= {av_tot + ogni_tot*a.messaggi:,}".replace(",", "."))

    if doppie:
        print(f"\n🔴 {len(doppie)} SKILL DOPPIE — caricate due volte, "
              f"~{sum(v[0]['avvio'] for v in doppie.values())} token sprecati all'avvio")
        for k, v in sorted(doppie.items(), key=lambda x: -x[1][0]["avvio"])[:8]:
            print(f"   {k:<34} {' + '.join(x['origine'] for x in v)}")
        if len(doppie) > 8: print(f"   … e altre {len(doppie)-8}")

    grosse = sorted(sk, key=lambda s: -s["avvio"])[:5]
    print("\nLe descrizioni più lunghe (si accorciano senza perdere l'aggancio):")
    for s in grosse:
        print(f"   {s['nome']:<34} {s['avvio']:>5} token  [{s['origine']}]")

    if inj:
        print(f"\n⚠️  {inj} plugin con hook UserPromptSubmit: iniettano testo a OGNI "
              f"messaggio.\n   Si spengono per progetto in <progetto>/.claude/settings.json")

if __name__ == "__main__":
    main()
