"""Windows: ogni programma a riga di comando lanciato da un processo senza console
(pythonw) apre per un istante una finestra di terminale. Importando questo modulo,
tutti i subprocess di questo processo partono con CREATE_NO_WINDOW."""
import subprocess
import sys

if sys.platform == "win32" and not getattr(subprocess, "_senza_finestre", False):
    _orig = subprocess.Popen.__init__

    def _init(self, *a, **k):
        k["creationflags"] = k.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
        _orig(self, *a, **k)

    subprocess.Popen.__init__ = _init
    subprocess._senza_finestre = True
