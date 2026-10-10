#!/usr/bin/env python3
"""Google FINTO per le prove del Vault: un emittente OIDC locale che firma token ID RS256 con una chiave
di prova. Nessun dato reale, nessuna chiamata a Google.

    python3 command-center/prova_vault_google.py --porta 7814

Endpoint (stessi nomi che vault_cc.oidc_conf usa con JARVIS_VAULT_OIDC_EMITTENTE=http://127.0.0.1:<porta>):
  /auth   pagina di scelta dell'account (o redirect subito con ?account=…&scenario=…, per le prove automatiche)
  /token  scambia il codice: controlla client_id, client_secret, redirect_uri e la PKCE S256
  /jwks   la chiave pubblica di prova
Scenari del token: ok, scaduto, aud, nonverificata, firma (chiave sbagliata), iss, nonce.
Client finto: id «prova-client-id.apps.esempio», segreto «prova-segreto-FINTO» (da mettere nel .env.jarvis FINTO
della casa di prova come VAULT__GOOGLE_CLIENT_ID / VAULT__GOOGLE_CLIENT_SECRET).
"""
import base64
import hashlib
import html
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

CLIENT_ID = "prova-client-id.apps.esempio"
CLIENT_SECRET = "prova-segreto-FINTO"
ACCOUNT = {"proprietario@esempio.invalid": "1001", "altro@esempio.invalid": "1002"}
SCENARI = ("ok", "scaduto", "aud", "nonverificata", "firma", "iss", "nonce")


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Emittente:
    def __init__(self, porta):
        self.base = f"http://127.0.0.1:{porta}"
        self.chiave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.chiave_sbagliata = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codici = {}
        self.scambi = 0

    def jwks(self):
        n = self.chiave.public_key().public_numbers()
        enc = lambda x: _b64url(x.to_bytes((x.bit_length() + 7) // 8, "big"))  # noqa: E731
        return {"keys": [{"kty": "RSA", "kid": "prova-1", "alg": "RS256", "use": "sig", "n": enc(n.n), "e": enc(n.e)}]}

    def token_id(self, c):
        ora = int(time.time())
        email = c["account"]
        corpo = {"iss": self.base, "aud": CLIENT_ID, "sub": ACCOUNT.get(email, "9999"), "email": email,
                 "email_verified": True, "iat": ora, "exp": ora + 3600, "nonce": c["nonce"]}
        s = c["scenario"]
        if s == "scaduto":
            corpo.update(iat=ora - 7200, exp=ora - 3600)
        elif s == "aud":
            corpo["aud"] = "altro-client.apps.esempio"
        elif s == "nonverificata":
            corpo["email_verified"] = False
        elif s == "iss":
            corpo["iss"] = "https://emittente-sbagliato.invalid"
        elif s == "nonce":
            corpo["nonce"] = "nonce-sbagliato"
        testa = _b64url(json.dumps({"alg": "RS256", "kid": "prova-1", "typ": "JWT"}).encode())
        dati = _b64url(json.dumps(corpo).encode())
        k = self.chiave_sbagliata if s == "firma" else self.chiave
        firma = k.sign(f"{testa}.{dati}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{testa}.{dati}.{_b64url(firma)}"


def gestore(em):
    class G(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _invia(self, codice, corpo, tipo="application/json", extra=()):
            dati = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
            self.send_response(codice)
            self.send_header("Content-Type", tipo)
            for k, v in extra:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(dati)))
            self.end_headers()
            self.wfile.write(dati)

        def do_GET(self):
            u = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/jwks":
                return self._invia(200, em.jwks())
            if u.path == "/auth":
                if q.get("client_id") != CLIENT_ID or q.get("code_challenge_method") != "S256" or \
                        "openid" not in q.get("scope", "") or not q.get("code_challenge"):
                    return self._invia(400, {"error": "invalid_request"})
                if q.get("account"):
                    codice = secrets.token_urlsafe(16)
                    em.codici[codice] = {"redirect": q["redirect_uri"], "nonce": q.get("nonce", ""),
                                         "sfida": q["code_challenge"], "account": q["account"],
                                         "scenario": q.get("scenario", "ok")}
                    dest = q["redirect_uri"] + "?" + urlencode({"code": codice, "state": q.get("state", "")})
                    return self._invia(302, b"", "text/plain", [("Location", dest)])
                righe = []
                for a in ACCOUNT:
                    for s in SCENARI:
                        if s != "ok" and a != "proprietario@esempio.invalid":
                            continue
                        link = self.path + "&" + urlencode({"account": a, "scenario": s})
                        righe.append(f"<li><a href='{html.escape(link)}'>{html.escape(a)} · {s}</a></li>")
                pagina = ("<!doctype html><meta charset='utf-8'><title>Google finto</title><body style='font:16px system-ui;"
                          "padding:16px'><h1>Google finto (prova)</h1><p>Scegli l'account di prova e lo scenario:</p><ul>"
                          + "".join(righe) + "</ul>")
                return self._invia(200, pagina.encode(), "text/html; charset=utf-8")
            return self._invia(404, {"error": "not_found"})

        def do_POST(self):
            if urlsplit(self.path).path != "/token":
                return self._invia(404, {"error": "not_found"})
            n = int(self.headers.get("Content-Length") or 0)
            q = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
            c = em.codici.pop(q.get("code", ""), None)
            if not c or q.get("client_id") != CLIENT_ID or q.get("client_secret") != CLIENT_SECRET or \
                    q.get("redirect_uri") != c["redirect"] or q.get("grant_type") != "authorization_code":
                return self._invia(400, {"error": "invalid_grant"})
            if _b64url(hashlib.sha256(q.get("code_verifier", "").encode()).digest()) != c["sfida"]:
                return self._invia(400, {"error": "invalid_grant", "error_description": "pkce"})
            em.scambi += 1
            return self._invia(200, {"access_token": "finto", "token_type": "Bearer", "expires_in": 3600,
                                     "id_token": em.token_id(c)})
    return G


def avvia(porta):
    em = Emittente(porta)
    srv = ThreadingHTTPServer(("127.0.0.1", porta), gestore(em))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return em, srv


if __name__ == "__main__":
    porta = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else 7814
    if porta == 7777:
        sys.exit("porta vietata")
    em = Emittente(porta)
    print(f"Google finto su http://127.0.0.1:{porta}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", porta), gestore(em)).serve_forever()
