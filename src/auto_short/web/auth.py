"""W2: single-password login with an HMAC-SHA256 signed session cookie (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path

PASSWORD_ENV = "AUTO_SHORT_WEB_PASSWORD"
SECRET_FILE = ".web_secret"
COOKIE_NAME = "auto_short_session"
_TOKEN_VERSION = "v1"


class AuthError(Exception):
    """Server cannot start: missing password or unusable secret file."""


def password_from_env(environ: dict | None = None) -> str:
    value = (os.environ if environ is None else environ).get(PASSWORD_ENV, "")
    if not value:
        raise AuthError(f"{PASSWORD_ENV} is not set; set it to the web password before starting the server "
                        f"(it is never read from config)")
    return value


def load_or_create_secret(workspace_dir: Path) -> bytes:
    """Random 32-byte key in ``<workspace_dir>/.web_secret`` (mode 600), created on first start so a restart
    keeps existing sessions valid."""
    path = Path(workspace_dir) / SECRET_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            data = path.read_text(encoding="ascii").strip()
            key = bytes.fromhex(data)
            if len(key) < 32:
                raise AuthError(f"{path}: secret too short; delete the file to generate a new one")
            if path.stat().st_mode & 0o077:
                os.chmod(path, 0o600)
            return key
        key = secrets.token_bytes(32)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(key.hex() + "\n")
        return key
    except (OSError, ValueError) as exc:
        raise AuthError(f"cannot use web secret file {path}: {exc}") from exc


class SessionSigner:
    """Signs ``v1.<expires unix>`` with a key derived from the secret file and the password hash, so changing
    the password invalidates every existing cookie."""

    def __init__(self, secret: bytes, password: str, session_days: int, *, clock=time.time):
        self._password = password.encode("utf-8")
        pw_hash = hashlib.sha256(self._password).digest()
        self._key = hmac.new(secret, b"auto-short-web-session\0" + pw_hash, hashlib.sha256).digest()
        self.max_age = int(session_days) * 86400
        self._clock = clock

    def check_password(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode("utf-8"), self._password)

    def _sig(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        payload = f"{_TOKEN_VERSION}.{int(self._clock()) + self.max_age}"
        return f"{payload}.{self._sig(payload)}"

    def verify(self, token: str | None) -> bool:
        if not token or len(token) > 200:
            return False
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_VERSION or not re.fullmatch(r"[0-9]{1,12}", parts[1]):
            return False
        payload = f"{parts[0]}.{parts[1]}"
        try:
            ok = hmac.compare_digest(parts[2], self._sig(payload))
        except TypeError:  # non-ASCII signature
            return False
        return ok and int(parts[1]) > self._clock()
