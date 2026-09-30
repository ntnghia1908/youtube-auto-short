"""Ollama chat client over stdlib ``urllib`` (CP1 §10) behind a small Protocol for tests."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_TIMEOUT = 600.0


class ChatError(Exception):
    """The chat request failed (HTTP error, timeout, unreachable host, invalid envelope)."""


class ChatUnavailable(ChatError):
    """FIX-ollama-wait O1: Ollama is unreachable (connection error, HTTP 502/503/504, or a timeout whose
    ``/api/tags`` re-check also fails). Callers must not retry; the web waits for the GPU."""


UNAVAILABLE_HTTP = (502, 503, 504)
TAGS_TIMEOUT = 10.0


@dataclass(frozen=True)
class ChatResult:
    content: str
    thinking: str | None = None
    eval_count: int | None = None
    prompt_eval_count: int | None = None
    total_duration: int | None = None  # nanoseconds, as reported by Ollama
    extra: dict = field(default_factory=dict)


class ChatClient(Protocol):
    def chat(self, *, model: str, messages: list[dict], format: dict | None, options: dict,
            think: bool) -> ChatResult:
        ...


def resolve_host(config_host: str) -> str:
    """Env ``OLLAMA_HOST`` > config; a bare ``host:port`` gets ``http://``."""
    host = (os.environ.get("OLLAMA_HOST") or config_host).strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    return host


def request_body(*, model: str, messages: list[dict], format: dict | None, options: dict, think: bool) -> dict:
    body = {"model": model, "messages": messages}
    if format:  # CP8.15 P3: free-form text response (post/prompt.py v2) omits the format key entirely
        body["format"] = format
    body["options"], body["think"], body["stream"] = options, think, False
    return body


class OllamaClient:
    """``POST <host>/api/chat`` with ``stream: false``; ``format`` is a JSON schema for structured output, or
    ``None``/``{}`` for free-form text (CP8.15 P3)."""

    def __init__(self, host: str, timeout: float = DEFAULT_TIMEOUT):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _timeout_error(self, exc: BaseException) -> ChatError:
        """O3: after a chat timeout, ``GET /api/tags`` (10 s) decides unavailable vs. a genuinely slow model."""
        msg = f"timeout after {self.timeout:g} s calling {self.host}/api/chat"
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=TAGS_TIMEOUT) as resp:
                resp.read()
        except Exception as tags_exc:  # noqa: BLE001 - any failure of the probe means unreachable
            return ChatUnavailable(f"{msg}; Ollama not responding ({tags_exc})")
        return ChatError(msg)

    def chat(self, *, model: str, messages: list[dict], format: dict | None, options: dict,
             think: bool) -> ChatResult:
        body = json.dumps(request_body(model=model, messages=messages, format=format, options=options,
                                       think=think), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            msg = f"HTTP {exc.code} from {self.host}/api/chat: {detail}"
            raise (ChatUnavailable if exc.code in UNAVAILABLE_HTTP else ChatError)(msg) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise self._timeout_error(exc) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise self._timeout_error(exc) from exc
            raise ChatUnavailable(f"cannot reach Ollama at {self.host}: {exc.reason}") from exc
        except OSError as exc:  # ConnectionError, RemoteDisconnected, other socket errors
            raise ChatUnavailable(f"error calling {self.host}/api/chat: {exc}") from exc
        try:
            data = json.loads(raw)
            message = data["message"]
            content = message["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ChatError(f"invalid Ollama response envelope: {raw[:300]!r}") from exc
        if not isinstance(content, str):
            raise ChatError("invalid Ollama response: message.content is not a string")
        return ChatResult(content=content, thinking=message.get("thinking") or None,
                          eval_count=data.get("eval_count"), prompt_eval_count=data.get("prompt_eval_count"),
                          total_duration=data.get("total_duration"),
                          extra={k: data[k] for k in ("done_reason",) if k in data})
