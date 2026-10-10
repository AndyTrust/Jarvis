#!/usr/bin/env python3
"""Estrae da una sessione Claude Code (.jsonl) solo il succo: i messaggi utente
per intero, e per ogni turno assistente solo il testo (non i tool-call/risultati),
troncato. Serve per leggere tante sessioni storiche senza il rumore delle
tool-call, per la fase 5 di aggiorna-memoria.

Uso: python3 estrai_sessione.py <file.jsonl> [--max-assistente 800]
"""
import json
import sys
from pathlib import Path


def testo_di(blocco):
    if isinstance(blocco, str):
        return blocco
    if isinstance(blocco, list):
        parti = []
        for b in blocco:
            if isinstance(b, dict) and b.get("type") == "text":
                parti.append(b.get("text", ""))
        return "\n".join(parti)
    return ""


def main():
    if len(sys.argv) < 2:
        print("uso: estrai_sessione.py <file.jsonl> [--max-assistente N]", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    max_ass = 800
    if "--max-assistente" in sys.argv:
        i = sys.argv.index("--max-assistente")
        max_ass = int(sys.argv[i + 1])

    righe = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    righe.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        print(f"errore lettura {path}: {e}", file=sys.stderr)
        sys.exit(1)

    out = [f"# {path.name}", ""]
    if righe:
        primo_ts = righe[0].get("timestamp", "")
        ultimo_ts = righe[-1].get("timestamp", "")
        out.append(f"periodo: {primo_ts} → {ultimo_ts}")
        cwd = None
        for r in righe:
            if r.get("cwd"):
                cwd = r["cwd"]
                break
        if cwd:
            out.append(f"cwd: {cwd}")
        out.append("")

    for r in righe:
        tipo = r.get("type")
        msg = r.get("message", {})
        if tipo == "user" and isinstance(msg, dict):
            contenuto = msg.get("content", "")
            t = testo_di(contenuto)
            if t and not t.strip().startswith("<"):
                out.append(f"## Utente\n{t.strip()}\n")
        elif tipo == "assistant" and isinstance(msg, dict):
            contenuto = msg.get("content", "")
            t = testo_di(contenuto).strip()
            if t:
                if len(t) > max_ass:
                    t = t[:max_ass] + " […troncato]"
                out.append(f"### Assistente\n{t}\n")

    print("\n".join(out))


if __name__ == "__main__":
    main()
