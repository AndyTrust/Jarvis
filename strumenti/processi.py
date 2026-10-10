#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I processi, senza `ps`, `lsof` e senza `os.kill(pid, 0)`.

Perché esiste (29/09/2026): su Windows `os.kill(pid, 0)` NON controlla se il processo c'è,
lo TERMINA (TerminateProcess con codice 0). Il portiere, `lavori.py` e il cruscotto lo
usavano per «il processo è vivo?»: su questo PC avrebbero ucciso la sessione che stavano
controllando. Qui il controllo si fa con le API di Windows, in sola lettura.

Su Mac e Linux le stesse domande le risolve `ps` come prima: questo modulo lo si usa solo
quando serve (`processi.WIN`).

    vivo(pid)              True/False, senza toccare il processo
    elenco()               [{pid, ppid, nome, cmd}] di tutti i processi (una chiamata a PowerShell, ~1 s)
    cpu_secondi(pid)       tempo di processore consumato, None se il processo non c'è
    acceso_da(pid)         «hh:mm:ss» dall'avvio, come l'`etime` di ps
    sessioni_claude()      i pid delle sessioni di Claude Code (non i processi dell'app Claude)
    antenato(pid, nome)    il primo antenato con quel nome di programma, o None
    porta_aperta(porta)    qualcuno ascolta su 127.0.0.1:porta?
"""
import json
import os
import socket
import subprocess
import sys
import time

WIN = sys.platform == "win32"

# Su Windows ogni programma a riga di comando lanciato da un processo senza console (pythonw, attività
# pianificate) apre per un istante una finestra di terminale, che disturba: tutto parte in background.
# Stessa regola di command-center/senza_finestre.py, ripetuta qui perché lavori, portiere, agenti e
# sentinella si possono lanciare anche da soli. Vale per tutti i subprocess del processo (idempotente).
if WIN and not getattr(subprocess, "_senza_finestre", False):
    _orig_init = subprocess.Popen.__init__

    def _senza_finestra(self, *a, **k):
        k["creationflags"] = k.get("creationflags", 0) | 0x08000000     # CREATE_NO_WINDOW
        _orig_init(self, *a, **k)

    subprocess.Popen.__init__ = _senza_finestra
    subprocess._senza_finestre = True

_STILL_ACTIVE = 259
_QUERY_LIMITED = 0x1000
_ERRORE_ACCESSO = 5


def _k32():
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
    return ctypes, k


def vivo(pid):
    """Il processo esiste ed è in esecuzione? Non lo tocca mai."""
    try:
        pid = int(pid)
    except (ValueError, TypeError, OverflowError):
        return False
    if pid <= 0:
        return False
    if not WIN:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (ProcessLookupError, OSError):
            return False
    ct, k = _k32()
    h = k.OpenProcess(_QUERY_LIMITED, 0, pid)
    if not h:
        return ct.get_last_error() == _ERRORE_ACCESSO      # esiste ma non è nostro
    try:
        codice = ct.c_uint32()
        if not k.GetExitCodeProcess(h, ct.byref(codice)):
            return True
        return codice.value == _STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def _tempi(pid):
    """(creazione, kernel, utente) in unità da 100 ns, o None."""
    ct, k = _k32()
    h = k.OpenProcess(_QUERY_LIMITED, 0, int(pid))
    if not h:
        return None
    try:
        t = [ct.c_uint64() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ct.byref(x) for x in t]):
            return None
        return t[0].value, t[2].value, t[3].value
    finally:
        k.CloseHandle(h)


def cpu_secondi(pid):
    if not vivo(pid):
        return None
    t = _tempi(pid) if WIN else None
    return (t[1] + t[2]) / 1e7 if t else None


def acceso_da(pid):
    t = _tempi(pid) if WIN else None
    if not t:
        return ""
    # la creazione è in 100 ns dal 1601-01-01: si toglie l'epoca Unix
    secondi = max(0, int(time.time() - (t[0] / 1e7 - 11644473600)))
    g, resto = divmod(secondi, 86400)
    h, resto = divmod(resto, 3600)
    m, s = divmod(resto, 60)
    return (f"{g}-" if g else "") + f"{h:02d}:{m:02d}:{s:02d}"


_PS = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
       "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine"
       " | ConvertTo-Json -Compress")


def elenco(timeout=20):
    """Tutti i processi. Vuoto se non si riesce a leggerli: chi chiama non deve morire per questo."""
    try:
        if WIN:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, stdin=subprocess.DEVNULL)
            dati = json.loads(r.stdout or "[]")
            if isinstance(dati, dict):
                dati = [dati]
            return [{"pid": int(d["ProcessId"]), "ppid": int(d["ParentProcessId"] or 0),
                     "nome": d.get("Name") or "", "cmd": d.get("CommandLine") or ""} for d in dati]
        r = subprocess.run(["ps", "-eo", "pid=,ppid=,comm=,args="], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        fuori = []
        for riga in r.stdout.splitlines():
            p = riga.split(None, 3)
            if len(p) >= 3 and p[0].isdigit() and p[1].isdigit():
                fuori.append({"pid": int(p[0]), "ppid": int(p[1]), "nome": os.path.basename(p[2]),
                              "cmd": p[3] if len(p) > 3 else ""})
        return fuori
    except Exception:
        return []


def _e_sessione_claude(p):
    """Una sessione di Claude Code, non uno dei processi dell'app Claude (Electron: --type=..., WindowsApps)."""
    if p["nome"].lower() not in ("claude.exe", "claude"):
        return False
    c = p["cmd"]
    return "--type=" not in c and "WindowsApps" not in c and "chrome-native-host" not in c


def sessioni_claude():
    return [p["pid"] for p in elenco() if _e_sessione_claude(p)]


def antenato(pid, nome, tabella=None, massimo=12):
    """Il primo antenato (pid incluso) il cui programma si chiama `nome` (senza .exe), o None."""
    per_pid = {p["pid"]: p for p in (tabella if tabella is not None else elenco())}
    voluto = nome.lower().removesuffix(".exe")
    for _ in range(massimo):
        p = per_pid.get(pid)
        if not p:
            return None
        if p["nome"].lower().removesuffix(".exe") == voluto and _e_sessione_claude(p):
            return pid
        pid = p["ppid"]
        if pid <= 1:
            return None
    return None


def porta_aperta(porta, timeout=0.5):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", int(porta))) == 0


if __name__ == "__main__":
    print("sessioni di Claude Code:", sessioni_claude())
    print("questo processo vivo:", vivo(os.getpid()), "· pid 999999 vivo:", vivo(999999))
    print("acceso da:", acceso_da(os.getpid()), "· cpu:", cpu_secondi(os.getpid()))
