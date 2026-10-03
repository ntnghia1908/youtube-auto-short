"""Worker tokens (CP13.1 E8): ``AUTO_SHORT_ENHANCE_TOKENS="name=token,name2=token2"`` in the env of the web process.

Never read from config or the repository; compared in constant time; a token opens only ``/api/enhance/*``."""

from __future__ import annotations

import hmac
import os
import re
import secrets
from collections.abc import Mapping

from ..web.auth import AuthError

TOKENS_ENV = "AUTO_SHORT_ENHANCE_TOKENS"
MIN_TOKEN_CHARS = 32  # E8: >= 32 bytes of randomness (``secrets.token_hex(32)`` = 64 hex chars)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TokenError(AuthError):
    """The token setting is unusable (the web server refuses to start with it)."""


def parse_tokens(text: str | None) -> dict[str, str]:
    """``name -> token`` from ``name=token,name2=token2`` (empty / unset = no worker may connect)."""
    out: dict[str, str] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, token = part.partition("=")
        name, token = name.strip(), token.strip()
        if not sep or not _NAME_RE.match(name):
            raise TokenError(f"{TOKENS_ENV}: expected name=token entries, name = letters / digits / . _ - (got {name!r})")
        if len(token) < MIN_TOKEN_CHARS:
            raise TokenError(f"{TOKENS_ENV}: the token of {name!r} is shorter than {MIN_TOKEN_CHARS} characters "
                             "(make one with `auto-short enhance-token`)")
        if name in out:
            raise TokenError(f"{TOKENS_ENV}: duplicate name {name!r}")
        out[name] = token
    return out


def tokens_from_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    return parse_tokens((os.environ if environ is None else environ).get(TOKENS_ENV))


def authenticate(tokens: Mapping[str, str], header: str | None) -> str | None:
    """The token name for an ``Authorization: Bearer <token>`` header, or None. Every configured token is compared
    (no early exit), each in constant time."""
    if not header or not header.startswith("Bearer ") or len(header) > 512:
        return None
    given = header[7:].strip().encode("utf-8")
    found = None
    for name, token in tokens.items():
        if hmac.compare_digest(given, token.encode("utf-8")) and found is None:
            found = name
    return found


def new_token() -> str:
    return secrets.token_hex(32)
