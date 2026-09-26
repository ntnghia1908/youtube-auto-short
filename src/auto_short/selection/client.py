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


@dataclass(frozen=True)
class ChatResult:
    content: str
    thinking: str | None = None
    eval_count: int | None = None
    prompt_eval_count: int | None = None
    total_duration: int | None = None  # nanoseconds, as reported by Ollama
    extra: dict = field(default_factory=dict)


class ChatClient(Protocol):
    def chat(self, *, model: str, messages: list[dict], format: dict, options: dict, think: bool) -> ChatResult:
        ...


def resolve_host(config_host: str) -> str:
    """Env ``OLLAMA_HOST`` > config; a bare ``host:port`` gets ``http://``."""
    host = (os.environ.get("OLLAMA_HOST") or config_host).strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    return host


def request_body(*, model: str, messages: list[dict], format: dict, options: dict, think: bool) -> dict:
    return {"model": model, "messages": messages, "format": format, "options": options,
            "think": think, "stream": False}


class OllamaClient:
    """``POST <host>/api/chat`` with ``stream: false`` and a JSON schema ``format``."""

    def __init__(self, host: str, timeout: float = DEFAULT_TIMEOUT):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def chat(self, *, model: str, messages: list[dict], format: dict, options: dict, think: bool) -> ChatResult:
        body = json.dumps(request_body(model=model, messages=messages, format=format, options=options,
                                       think=think), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ChatError(f"HTTP {exc.code} from {self.host}/api/chat: {detail}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ChatError(f"timeout after {self.timeout:g} s calling {self.host}/api/chat") from exc
        except urllib.error.URLError as exc:
            raise ChatError(f"cannot reach Ollama at {self.host}: {exc.reason}") from exc
        except OSError as exc:
            raise ChatError(f"error calling {self.host}/api/chat: {exc}") from exc
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
