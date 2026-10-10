#!/usr/bin/env python3
"""Toglie da ~/.claude quello che è vecchio e non serve più, così Claude Code e Jarvis non si inquinano (l'utente, 29/09/2026).
  - projects/*: le chat (file .jsonl e le cartelle di sotto-agenti e risultati con lo stesso nome) più vecchie di --giorni-chat (7).
    MAI: le cartelle memory/ (l'auto-memoria), le chat toccate nelle ultime 24 ore, le sessioni ancora aperte. Il riassunto di
    ogni sessione sta già nel vault (Jarvis Brain/Sessioni), quindi una chat nuova riparte da lì, non dalla cronologia.
  - cache/pdf-testo: testo estratto dai PDF, si rifà da solo: più vecchio di --giorni-pdf (14).
  - paste-cache: testi incollati: più vecchi di --giorni-incolla (3).
  - agents/: NON cancella; dice quali agenti di casa non sono in claude-config/agents (repo) e quali differiscono.
  - shell-snapshots (3 giorni), session-env (3), debug (7), file-history (14), todos (14), backups/.claude.json.backup.* (tiene gli ultimi 3).
  - hook: NON toglie; segnala gli hook registrati due volte in settings.json e quelli diversi da claude-config/hooks (repo).
Dal 2026-10-04 (l'utente: «quando lanciamo aggiorna memoria deve cancellare tutto lo storico passato e obsoleto», anche sulla VPS) la chat
vecchia è > 2 giorni, e con --archivia DIR ogni chat tolta finisce prima in DIR/AAAAMMGG-<casa>.tar.gz (si tiene 30 giorni).
Senza --applica mostra soltanto cosa toglierebbe. Scrive ~/.claude/pulizia-jarvis.log.
  python3 strumenti/pulisci_claude.py                 (prova)
  python3 strumenti/pulisci_claude.py --applica [--giorni-chat 2] [--archivia DIR] [--home /home/jarvis] [--quiet]
Variabile CLAUDE_HOME (o --home) per provarlo su una casa finta."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path


def opzione(nome, predefinito):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


HOME = Path(opzione("--home", os.environ.get("CLAUDE_HOME") or str(Path.home()))).expanduser()
CLAUDE = HOME / ".claude"
QUI = Path(__file__).resolve().parents[1]
APPLICA = "--applica" in sys.argv
QUIET = "--quiet" in sys.argv
G_CHAT, G_PDF, G_INCOLLA = (float(opzione("--giorni-chat", 2)), float(opzione("--giorni-pdf", 14)), float(opzione("--giorni-incolla", 3)))
ARCHIVIA = opzione("--archivia", None)
ADESSO = time.time()
DA_TOGLIERE = []          # (percorso, archiviare?) — si esegue alla fine, dopo l'archivio
tot = {"file": 0, "byte": 0}
righe = []


def peso(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def togli(p: Path, motivo: str):
    if any(q == p or q in p.parents for q in DA_TOGLIERE):
        return
    n = 1 if p.is_file() else sum(1 for f in p.rglob("*") if f.is_file())
    b = peso(p)
    tot["file"] += n
    tot["byte"] += b
    righe.append(f"{motivo}: {p.relative_to(CLAUDE)} ({n} file, {b // 1024} KB)")
    DA_TOGLIERE.append(p)


def esegui():
    """Archivia (se richiesto) le chat da togliere, poi toglie tutto. Un errore dell'archivio ferma la cancellazione delle chat."""
    if not APPLICA or not DA_TOGLIERE:
        return
    chat_da = [p for p in DA_TOGLIERE if (CLAUDE / "projects") in p.parents]
    if ARCHIVIA and chat_da:
        dest = Path(ARCHIVIA).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        os.chmod(dest, 0o700)
        nome = dest / f"{time.strftime('%Y%m%d-%H%M')}-{HOME.name or 'root'}.tar.gz"
        with tarfile.open(nome, "w:gz") as tf:
            for p in chat_da:
                tf.add(p, arcname=str(p.relative_to(CLAUDE)))
        righe.append(f"archivio: {len(chat_da)} elementi in {nome}")
        for vecchio in dest.glob("*.tar.gz*"):
            if ADESSO - vecchio.stat().st_mtime > 30 * 86400:
                vecchio.unlink()
    for p in DA_TOGLIERE:
        if p.exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def ultimo_tocco(p: Path) -> float:
    try:
        m = p.lstat().st_mtime            # lstat: un collegamento rotto (es. debug/latest) non fa errore
    except OSError:
        return ADESSO                      # non si sa: si considera «appena toccato», quindi non si toglie
    if p.is_dir():
        for f in p.rglob("*"):
            try:
                m = max(m, f.stat().st_mtime)
            except OSError:
                pass
    return m


def sessioni_aperte() -> set:
    """Gli id delle sessioni di Claude Code che hanno un processo vivo adesso (dal registro delle sessioni)."""
    try:
        import json
        reg = json.loads((HOME / ".locale-onedrive" / "sessioni.json").read_text(encoding="utf-8"))
    except Exception:
        return set()
    vive = set()
    for sid, s in reg.items():
        pid = s.get("pid")
        if s.get("stato") == "aperta" and pid:
            try:
                os.kill(int(pid), 0)
                vive.add(sid)
            except (OSError, ValueError):
                pass
    return vive


def chat_dei_processi_vivi() -> set:
    """Dove non c'è sessioni.json (la VPS): per ogni processo `claude` in esecuzione si protegge l'ultima chat della sua cartella di
    lavoro (anche se ferma da giorni: il processo la riapre e la riscrive). Solo Linux (/proc); altrove insieme vuoto."""
    protette = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return protette
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            argv = (d / "cmdline").read_bytes().split(b"\0")
            nome = os.path.basename(argv[0].decode("utf-8", "ignore"))
            if not (nome in ("claude", "claude.exe") or (nome in ("node", "bun") and any(b"claude" in a for a in argv[1:3]))):
                continue
            cwd = os.readlink(d / "cwd")
        except (OSError, IndexError):
            continue
        cartella = CLAUDE / "projects" / "".join("-" if c in "/._" else c for c in cwd)
        recenti = sorted(cartella.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if cartella.is_dir() else []
        protette.update(recenti[:3])           # le ultime tre: un processo può averne riaperta una precedente
    return protette


def chat():
    progetti = CLAUDE / "projects"
    if not progetti.is_dir():
        return
    aperte = sessioni_aperte()
    vive = chat_dei_processi_vivi()
    for cartella in sorted(p for p in progetti.iterdir() if p.is_dir()):
        for f in sorted(cartella.glob("*.jsonl")):
            if f in vive:
                righe.append(f"  protetta (processo vivo): {f.relative_to(CLAUDE)}")
                continue
            if f.stem in aperte or ADESSO - ultimo_tocco(f) < 86400 or ADESSO - ultimo_tocco(f) < G_CHAT * 86400:
                continue
            togli(f, f"chat vecchia (> {G_CHAT:g} giorni)")
            extra = cartella / f.stem                 # sotto-agenti, risultati degli strumenti
            if extra.is_dir():
                togli(extra, "  con i suoi sotto-agenti e risultati")
        for extra in sorted(p for p in cartella.iterdir() if p.is_dir() and p.name not in ("memory",)):
            if len(extra.name) == 36 and not (cartella / f"{extra.name}.jsonl").exists() and ADESSO - ultimo_tocco(extra) > G_CHAT * 86400:
                togli(extra, "  cartella orfana di una chat già tolta")
        if APPLICA and not any(cartella.iterdir()):
            cartella.rmdir()


def cartella_di_lavoro_esiste(slug: str) -> bool:
    """Lo slug di projects/ è la cartella di lavoro con «/», «.» e «_» sostituiti da «-». Si risolve sul disco provando i separatori."""
    parti = slug.strip("-").split("-")
    cur, i = Path("/"), 0
    while i < len(parti):
        trovato = False
        for j in range(len(parti), i, -1):
            for sep in ("-", ".", "_"):
                cand = cur / sep.join(parti[i:j])
                if cand.exists():
                    cur, i, trovato = cand, j, True
                    break
            if trovato:
                break
        if not trovato:
            return False
    return True


NOMI_OBSOLETI = ("my-agent",)         # ~/my-agent è solo un collegamento: il progetto è ~/Jarvis (obsoleti.json)


def progetti():
    """Cartelle di progetto intere in ~/.claude/projects che confondono Claude (l'utente, 2026-10-04: «chat vecchie con progetti obsoleti;
    Claude deve ripartire solo dalla memoria di Jarvis»): senza nessuna chat e senza note di memoria; oppure di una cartella di lavoro
    che non esiste più; oppure col nome di un progetto obsoleto. Mai se c'è una chat toccata nelle ultime 24 ore o di un processo vivo."""
    base = CLAUDE / "projects"
    if not base.is_dir():
        return
    vive = chat_dei_processi_vivi()
    aperte = sessioni_aperte()
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        chat_ = list(d.glob("*.jsonl"))
        if any(f in vive or f.stem in aperte or ADESSO - ultimo_tocco(f) < 86400 for f in chat_):
            continue
        note = [f for f in (d / "memory").glob("*.md") if f.name != "MEMORY.md"] if (d / "memory").is_dir() else []
        if ADESSO - ultimo_tocco(d) < 3600:
            continue
        if not chat_ and not note:
            togli(d, "progetto senza chat né note")
        elif not cartella_di_lavoro_esiste(d.name):
            togli(d, "progetto di una cartella che non esiste più")
        elif any(n in d.name for n in NOMI_OBSOLETI):
            togli(d, "progetto con un nome obsoleto")


def cache(nome: str, giorni: float, etichetta: str):
    d = CLAUDE / nome
    if not d.is_dir():
        return
    for f in sorted(d.iterdir()):
        if f.is_file() and ADESSO - f.stat().st_mtime > giorni * 86400:
            togli(f, f"{etichetta} (> {giorni:g} giorni)")


def cartelle_vecchie(nome: str, giorni: float, etichetta: str):
    """Elementi (file o cartelle) direttamente dentro ~/.claude/<nome> non toccati da più di `giorni`."""
    d = CLAUDE / nome
    if not d.is_dir():
        return
    aperte = sessioni_aperte()
    for x in sorted(d.iterdir()):
        if x.name in aperte or x.is_symlink():
            continue
        if ADESSO - ultimo_tocco(x) > giorni * 86400:
            togli(x, f"{etichetta} (> {giorni:g} giorni)")


def backup_config(tieni: int = 3):
    d = CLAUDE / "backups"
    if not d.is_dir():
        return
    f = sorted(d.glob(".claude.json.backup.*"), key=lambda x: x.stat().st_mtime, reverse=True)
    for x in f[tieni:]:
        if ADESSO - x.stat().st_mtime > 86400:
            togli(x, f"copia vecchia di .claude.json (tengo le ultime {tieni})")


def hook():
    """Segnala, senza toccare: hook registrati due volte in settings.json e hook diversi da claude-config/hooks."""
    try:
        d = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    visti, doppi = set(), []
    for ev, gruppi in (d.get("hooks") or {}).items():
        for g in gruppi:
            for h in g.get("hooks", []):
                cmd = (h.get("command") or "").replace("$HOME", str(HOME)).replace("~", str(HOME)).replace('"', "")
                k = (ev, g.get("matcher", ""), cmd)
                if k in visti:
                    doppi.append(f"{ev} {g.get('matcher', '-')}: {cmd[-60:]}")
                visti.add(k)
    if doppi:
        righe.append(f"hook registrati DUE volte in settings.json ({len(doppi)}): " + " | ".join(doppi[:6]))
    live, repo = CLAUDE / "hooks", QUI / "claude-config" / "hooks"
    if live.is_dir() and repo.is_dir():
        diversi = [f.name for f in sorted(live.glob("*.py")) if (repo / f.name).exists() and (repo / f.name).read_bytes() != f.read_bytes()]
        if diversi:
            righe.append("hook diversi da claude-config/hooks (repo): " + ", ".join(diversi))


def agenti():
    live, repo = CLAUDE / "agents", QUI / "claude-config" / "agents"
    if not live.is_dir() or not repo.is_dir():
        return
    fuori, diversi = [], []
    for f in sorted(live.glob("*.md")):
        r = repo / f.name
        if not r.exists():
            fuori.append(f.name)
        elif r.read_bytes() != f.read_bytes():
            diversi.append(f.name)
    if fuori:
        righe.append("agenti in ~/.claude/agents che il repository non conosce (non li tolgo): " + ", ".join(fuori))
    if diversi:
        righe.append("agenti diversi dal repository (rilancia sincro_claude.py): " + ", ".join(diversi))


def main():
    chat()
    cache("cache/pdf-testo", G_PDF, "testo PDF vecchio")
    cache("paste-cache", G_INCOLLA, "testo incollato vecchio")
    cartelle_vecchie("shell-snapshots", 3, "snapshot della shell vecchio")
    cartelle_vecchie("session-env", 3, "ambiente di sessione vecchio")
    cartelle_vecchie("debug", 7, "log di debug vecchio")
    cartelle_vecchie("file-history", 14, "cronologia file vecchia")
    cartelle_vecchie("todos", 14, "todo vecchio")
    backup_config()
    progetti()
    esegui()
    hook()
    agenti()
    esito = f"{'Tolti' if APPLICA else 'Da togliere'}: {tot['file']} file, {tot['byte'] / 1048576:.1f} MB"
    if not QUIET:
        for r in righe:
            print(r)
    print(esito)
    if APPLICA:
        try:
            with open(CLAUDE / "pulizia-jarvis.log", "a", encoding="utf-8") as lg:
                lg.write(f"{time.strftime('%F %T')} {esito}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
