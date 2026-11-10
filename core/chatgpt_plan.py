"""Official Sign in with ChatGPT for a local open-source desktop client."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import uuid
import webbrowser

from .config import CONFIG_DIR

AUTH = "https://auth.openai.com"
API = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url, *, data=None, headers=None):
    try:
        return build_opener(_NoRedirect()).open(Request(url, data=data, headers=headers or {}), timeout=25)
    except HTTPError as exc:
        message = {401: "Połącz ponownie konto ChatGPT.",
                   403: "Konto lub plan ChatGPT nie ma dostępu do tej funkcji.",
                   429: "Osiągnięto limit planu ChatGPT."}.get(exc.code, "Usługa ChatGPT zwróciła błąd.")
        exc.close()
        raise RuntimeError(message) from None
    except (URLError, TimeoutError):
        raise RuntimeError("Nie można połączyć się z ChatGPT.") from None


def _token(form):
    with _request(AUTH + "/api/accounts/oauth/token", data=urlencode({**form, "resource": API}).encode(),
                  headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
        return json.loads(response.read(64_000))


def _identity(encoded, client, nonce):
    import jwt
    try:
        key = jwt.PyJWKClient(AUTH + "/.well-known/jwks.json", timeout=12).get_signing_key_from_jwt(encoded)
        claims = jwt.decode(encoded, key.key, algorithms=["RS256"], audience=client, issuer=AUTH,
                            options={"require": ["sub", "iss", "aud", "exp", "nonce"]})
        if not secrets.compare_digest(claims["nonce"], nonce):
            raise ValueError
        return hashlib.sha256(claims["sub"].encode()).hexdigest()
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise RuntimeError("Nie można zweryfikować logowania ChatGPT.") from None


class _Loopback(HTTPServer):
    timeout = .3

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address


class ChatGPTPlan:
    def __init__(self):
        self.registration = Path(CONFIG_DIR) / "chatgpt-registration.json"
        self.tokens = None
        self.expiry = 0

    def connect(self, cancelled):
        try:
            saved = json.loads(self.registration.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        host = saved.get("host") or "urn:uuid:" + str(uuid.uuid4())
        client = saved.get("client") or "dynamic_agent_client"
        new = client == "dynamic_agent_client"
        state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        callback = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlsplit(self.path)
                params = parse_qs(url.query)
                valid = (url.path == "/auth/callback" and params.get("state") == [state]
                         and not callback and not cancelled())
                if valid:
                    callback.update(params)
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"Return to Frap Grab." if valid else b"Invalid sign-in callback.")

        with _Loopback(("127.0.0.1", 0), Handler) as listener:
            redirect = f"http://127.0.0.1:{listener.server_port}/auth/callback"
            form = {"client_id": client, "ext_agent_host_id": host, "redirect_uri": redirect, "scope": SCOPES,
                    "response_type": "code", "state": state, "nonce": nonce, "resource": API,
                    "code_challenge_method": "S256", "code_challenge": challenge}
            if new:
                form["agent_name_hint"] = "Frap Grab"
            if not webbrowser.open(AUTH + "/api/accounts/authorize?" + urlencode(form)):
                raise RuntimeError("Nie udało się otworzyć przeglądarki.")
            deadline = time.monotonic() + 180
            while not callback and not cancelled() and time.monotonic() < deadline:
                listener.handle_request()
        if cancelled():
            raise RuntimeError("Anulowano logowanie.")
        code = callback.get("code", [])
        issued = callback.get("client_id", [] if new else [client])
        if "error" in callback or len(code) != 1 or len(issued) != 1 or not issued[0].startswith("oaiapp_"):
            raise RuntimeError("Logowanie ChatGPT nie zostało ukończone.")
        if not new and issued != [client]:
            raise RuntimeError("ChatGPT zwrócił inną rejestrację konta.")
        tokens = _token({"grant_type": "authorization_code", "client_id": issued[0], "code": code[0],
                         "redirect_uri": redirect, "code_verifier": verifier})
        identity = _identity(tokens.get("id_token"), issued[0], nonce)
        if not new and identity != saved.get("identity"):
            raise RuntimeError("ChatGPT zwrócił inne konto.")
        if cancelled():
            raise RuntimeError("Anulowano logowanie.")
        self._set_tokens(tokens, issued[0])
        temp = self.registration.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps({"host": host, "client": issued[0], "identity": identity}), encoding="utf-8")
            temp.replace(self.registration)
        finally:
            temp.unlink(missing_ok=True)

    def _set_tokens(self, tokens, client):
        if PLAN_SCOPE not in tokens.get("scope", "").split() or not tokens.get("access_token"):
            raise RuntimeError("Włącz zgodę na użycie planu ChatGPT.")
        self.expiry = time.monotonic() + float(tokens["expires_in"])
        self.tokens = {**tokens, "client": client}

    def disconnect(self):
        tokens = self.tokens
        try:
            if tokens and tokens.get("refresh_token"):
                with _request(AUTH + "/.well-known/openid-configuration") as response:
                    endpoint = json.loads(response.read(64_000)).get("revocation_endpoint", "")
                parsed = urlsplit(endpoint)
                if (parsed.scheme, parsed.netloc) != ("https", "auth.openai.com"):
                    raise RuntimeError("Nie udało się odwołać sesji ChatGPT.")
                data = urlencode({"token": tokens["refresh_token"], "token_type_hint": "refresh_token",
                                  "client_id": tokens["client"]}).encode()
                with _request(endpoint, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}):
                    pass
        finally:
            self.tokens = None
            self.registration.unlink(missing_ok=True)

    def propose(self, prompt, cancelled):
        if not self.tokens:
            raise RuntimeError("Najpierw połącz konto ChatGPT.")
        if self.expiry < time.monotonic() + 30:
            current = self.tokens
            if not current.get("refresh_token"):
                raise RuntimeError("Połącz ponownie konto ChatGPT.")
            fresh = _token({"grant_type": "refresh_token", "client_id": current["client"],
                            "refresh_token": current["refresh_token"]})
            self._set_tokens({**current, **fresh}, current["client"])
        headers = {"Authorization": "Bearer " + self.tokens["access_token"], "Content-Type": "application/json"}
        with _request(API + "/models", headers=headers) as response:
            models = json.loads(response.read(512_000)).get("models", [])
        choices = [model["slug"] for model in models if model.get("visibility") == "list" and model.get("slug")]
        if not choices:
            raise RuntimeError("Plan ChatGPT nie udostępnia modelu.")
        model = next((slug for slug in choices if slug == "gpt-6.1-sol"), choices[0])
        body = json.dumps({"model": model, "input": [{"role": "user", "content": prompt}],
                           "store": False, "stream": True}).encode()
        return _read_reply(_request(API + "/responses", headers=headers, data=body), cancelled)


def _read_reply(response, cancelled):
    parts, length = [], 0
    with response:
        while not cancelled():
            line = response.readline(128_001)
            if not line or len(line) > 128_000:
                break
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            event = json.loads(data)
            kind = event.get("type")
            if kind == "response.output_text.delta":
                delta = event["delta"]
                length += len(delta)
                if length > 64_000:
                    raise RuntimeError("Odpowiedź ChatGPT jest za długa.")
                parts.append(delta)
            elif kind == "response.completed":
                return "".join(parts)
            elif kind in {"response.failed", "response.incomplete", "error"}:
                break
    raise RuntimeError("ChatGPT nie ukończył planu montażu.")
