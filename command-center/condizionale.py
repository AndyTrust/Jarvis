"""Letture condizionali del Command Center (2026-10-03, lavoro «prestazioni da internet»).

Dal telefono, attraverso il ponte, la pagina rileggeva a ogni avviso del flusso /api/stato (65 KB) e
/api/scadenze (fino a 170 KB) anche quando non era cambiato niente: 3 MB ogni 30 s. Qui due aiuti, usati
da server.py, che valgono SOLO se il client li chiede (una pagina vecchia riceve le risposte di sempre):

1. ETag e 304 (etag_di, coincide). Per gli indirizzi di ETAG_PERCORSI il server calcola un'impronta del
   JSON; se la pagina manda If-None-Match con la stessa impronta risponde 304 senza corpo e la pagina
   riusa la copia che tiene in memoria (JavaScript, non la cache del browser: Cache-Control resta no-store,
   i dati dell'utente non si scrivono sul disco del telefono).
   Alcuni indirizzi hanno un campo che cambia a ogni lettura e che la pagina non usa (es. «letto_ts» delle
   scadenze, l'ora del calcolo): non entra nell'impronta, e l'ETag è debole (W/) come vuole l'HTTP per
   «stesso contenuto per chi lo usa». Un indirizzo con un campo d'ora che la pagina USA non sta qui.

2. /api/stato a pezzi (stato_a_pezzi). /api/stato?parti=<nome.impronta,…>: per ogni sezione di primo
   livello abbastanza grande il server calcola un'impronta e la manda in «parti»; le sezioni la cui
   impronta coincide con quella che la pagina ha già NON vengono rimandate (es. «catena», 44 KB, cambia
   ogni due minuti). La pagina rimette insieme lo stato con le sue copie. ?parti= vuoto = stato intero
   più le impronte (prima lettura). Senza ?parti la risposta è quella di sempre.

Solo libreria standard. Nessun dato nuovo esce: l'impronta è un sha1 troncato di dati che lo stesso
client riceve comunque, dopo gli stessi controlli (Host, token).
"""
import hashlib
import json
import re

# indirizzo -> campi di primo livello fuori dall'impronta (cambiano a ogni lettura, la pagina non li usa)
ETAG_PERCORSI = {
    "/api/scadenze": ("letto_ts",),     # time.time() del calcolo: app.js non lo legge (verificato 2026-10-03)
    "/api/pannello": (),
    "/api/catalogo": (),
    "/api/spazi": (),
    "/api/chat/storia": (),
    "/api/approvazioni": (),            # «ora» resta dentro: approvazioni.js e chiamata.js la usano per l'orologio
    "/api/fili": ("ora",),              # fili.js non legge l'«ora» dell'elenco (solo quella dei messaggi)
    "/api/registro": ("ora",),          # registro.js non la legge
    "/api/registro/regole": (),
}

# sezioni di /api/stato sempre intere: cambiano a ogni lettura o sono piccole
STATO_SEMPRE = frozenset(("ora", "ora_ts", "versione", "modo_chat"))
STATO_MIN_BYTE = 256          # sotto, l'impronta nella query costa più della sezione
_NOME = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
_IMPRONTA = re.compile(r"^[0-9a-f]{16}$")


def _impronta(obj):
    testo = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(testo.encode("utf-8")).hexdigest()[:16], len(testo)


def etag_di(percorso, corpo):
    """L'ETag per questo indirizzo e questo corpo (dict/list già pronto per json.dumps), o None se
    l'indirizzo non ne ha. Forte se conta tutto il corpo, debole (W/) se qualche campo resta fuori."""
    if percorso not in ETAG_PERCORSI or isinstance(corpo, (bytes, str)):
        return None
    fuori = ETAG_PERCORSI[percorso]
    if fuori and isinstance(corpo, dict):
        h, _ = _impronta({k: v for k, v in corpo.items() if k not in fuori})
        return f'W/"{h}"'
    h, _ = _impronta(corpo)
    return f'"{h}"'


def _nuda(tag):
    """L'impronta senza W/, virgolette e il suffisso che un proxy che comprime può aggiungere
    (Caddy: "abc-gzip", "abc-zstd")."""
    t = tag.strip()
    if t.startswith("W/"):
        t = t[2:]
    t = t.strip('"')
    for suff in ("-gzip", "-zstd", "-br", "-deflate"):
        if t.endswith(suff):
            t = t[: -len(suff)]
    return t


def coincide(if_none_match, tag):
    """If-None-Match (anche con più valori separati da virgola) contiene questo ETag? Confronto debole,
    come vuole l'RFC 9110 per If-None-Match. «*» non vale: qui serve sempre un'impronta precisa."""
    if not if_none_match or not tag or len(if_none_match) > 2000:
        return False
    mio = _nuda(tag)
    return any(_nuda(x) == mio for x in if_none_match.split(",") if x.strip() and x.strip() != "*")


def leggi_parti(valore):
    """«catena.0123456789abcdef,memoria.…» -> {nome: impronta}. Voci malformate: ignorate."""
    note = {}
    for pezzo in (valore or "").split(",")[:64]:
        nome, _, h = pezzo.strip().partition(".")
        if _NOME.match(nome) and _IMPRONTA.match(h):
            note[nome] = h
    return note


def stato_a_pezzi(stato, valore_parti):
    """Lo stato con le sole sezioni cambiate rispetto alle impronte che la pagina ha già, più «parti»
    = {sezione: impronta} di TUTTE le sezioni con impronta. La pagina rimette insieme: una sezione in
    «parti» e assente dalla risposta è invariata. Le sezioni piccole o in STATO_SEMPRE arrivano sempre."""
    note = leggi_parti(valore_parti)
    fuori, parti = {}, {}
    for k, v in stato.items():
        if k in STATO_SEMPRE:
            fuori[k] = v
            continue
        h, n = _impronta(v)
        if n < STATO_MIN_BYTE:
            fuori[k] = v
            continue
        parti[k] = h
        if note.get(k) != h:
            fuori[k] = v
    fuori["parti"] = parti
    return fuori
