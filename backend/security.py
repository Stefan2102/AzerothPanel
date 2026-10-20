"""Single-admin authentication: scrypt password hash + HMAC-signed session cookie."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request, WebSocket

from .paths import AUTH_FILE, CONTROL_TOKEN_FILE, SECRET_FILE, ensure_dirs

SESSION_COOKIE = "acp_session"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSWORD_LENGTH = 8


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _write_private(path, data: bytes) -> None:
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


_secret_key: bytes | None = None     # data/secret.key, kept in memory: it is read on every request


def _secret() -> bytes:
    global _secret_key
    if _secret_key is None:
        if not SECRET_FILE.is_file():
            _write_private(SECRET_FILE, secrets.token_bytes(32))
        _secret_key = SECRET_FILE.read_bytes()
    return _secret_key


def _new_secret() -> None:
    """Replace the signing key: every existing session becomes invalid."""
    global _secret_key
    key = secrets.token_bytes(32)
    _write_private(SECRET_FILE, key)
    _secret_key = key


# ---- account ---------------------------------------------------------------
# One admin account, stored in data/auth.json as username + scrypt hash.
# A fresh install ships with admin / admin (created on first start).

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"


def _write_account(username: str, password: str) -> None:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    record = {"username": username, "salt": _b64(salt), "hash": _b64(digest), **_SCRYPT}
    _write_private(AUTH_FILE, json.dumps(record).encode())


def _read_account() -> dict:
    record = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    # Installs from before usernames existed only stored the password: they log in as "admin".
    record.setdefault("username", DEFAULT_USERNAME)
    return record


def ensure_default_account() -> None:
    if not AUTH_FILE.is_file():
        _write_account(DEFAULT_USERNAME, DEFAULT_PASSWORD)


def username() -> str:
    return _read_account()["username"]


def verify_credentials(name: str, password: str) -> bool:
    record = _read_account()
    digest = hashlib.scrypt(
        password.encode(), salt=_unb64(record["salt"]),
        n=record["n"], r=record["r"], p=record["p"], dklen=record["dklen"],
    )
    name_ok = hmac.compare_digest(name.strip().lower().encode(), record["username"].lower().encode())
    return hmac.compare_digest(digest, _unb64(record["hash"])) and name_ok


def is_default_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), DEFAULT_PASSWORD.encode())


def change_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if is_default_password(password):
        raise ValueError("Choose a password other than the default.")
    _write_account(username(), password)
    # New signing key: every other session (other browsers, other devices) is signed out.
    _new_secret()


def default_password_in_use() -> bool:
    return verify_credentials(username(), DEFAULT_PASSWORD)


# ---- login lockout ----------------------------------------------------------------

class LoginLimiter:
    """Per-IP lockout: MAX_FAILURES wrong logins within WINDOW seconds lock that IP for LOCK seconds."""

    MAX_FAILURES, WINDOW, LOCK = 5, 15 * 60, 15 * 60

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def locked_for(self, ip: str) -> int:
        """Seconds this IP is still locked (0 = may try)."""
        return max(0, int(self._locked_until.get(ip, 0) - time.time()))

    def failed(self, ip: str) -> bool:
        """Record a failure; True when this failure locked the IP."""
        now = time.time()
        recent = [t for t in self._failures.get(ip, []) if now - t < self.WINDOW] + [now]
        self._failures[ip] = recent
        if len(recent) >= self.MAX_FAILURES:
            self._locked_until[ip] = now + self.LOCK
            self._failures.pop(ip, None)
            return True
        return False

    def succeeded(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)


login_limiter = LoginLimiter()


# ---- session tokens -------------------------------------------------------
# Payload: {"exp": unix time, "mc": true while the default password is still in use}.

def issue_session(hours: int, must_change: bool = False) -> tuple[str, int]:
    expires = int(time.time()) + hours * 3600
    payload = _b64(json.dumps({"exp": expires, "mc": must_change}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}", expires


def session_payload(token: str | None) -> dict | None:
    """The token's payload if it is genuine and not expired, else None."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
        return data if data["exp"] > time.time() else None
    except (ValueError, KeyError):
        return None


def session_valid(token: str | None) -> bool:
    return session_payload(token) is not None


def _same_origin(origin: str | None, host: str | None) -> bool:
    # Browsers send Origin on cross-site requests; reject anything not from this panel.
    if not origin:
        return True
    return origin.split("://", 1)[-1] == host


def require_same_origin(request: Request) -> None:
    """For unauthenticated state-changing routes (setup, login)."""
    if not _same_origin(request.headers.get("origin"), request.headers.get("host")):
        raise HTTPException(status_code=403, detail="Cross-origin request blocked.")


def require_session(request: Request) -> None:
    """FastAPI dependency for every protected HTTP route."""
    payload = session_payload(request.cookies.get(SESSION_COOKIE))
    if payload is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if payload.get("mc"):
        raise HTTPException(status_code=403, detail="Change the default password first.")
    if request.method not in ("GET", "HEAD") and not _same_origin(request.headers.get("origin"), request.headers.get("host")):
        raise HTTPException(status_code=403, detail="Cross-origin request blocked.")


def websocket_allowed(ws: WebSocket) -> bool:
    payload = session_payload(ws.cookies.get(SESSION_COOKIE))
    return payload is not None and not payload.get("mc") and _same_origin(ws.headers.get("origin"), ws.headers.get("host"))


# ---- local control token (used by `python -m backend stop`) ---------------

def new_control_token() -> str:
    token = secrets.token_urlsafe(32)
    _write_private(CONTROL_TOKEN_FILE, token.encode())
    return token


def read_control_token() -> str | None:
    return CONTROL_TOKEN_FILE.read_text().strip() if CONTROL_TOKEN_FILE.is_file() else None
