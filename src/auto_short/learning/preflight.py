"""Ollama preflight of the Chinese Learning application (CL1 C7).

Own implementation over stdlib ``urllib`` (no import from ``pipeline.py``): ``GET <host>/api/tags``
and check that ``[learning] model`` is listed (``name`` or ``model``; a bare name matches ``:latest``).
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ..config import Config
from ..selection.client import resolve_host

log = logging.getLogger("auto_short")

PREFLIGHT_TIMEOUT = 10.0

Opener = Callable[..., Any]


class LearningPreflightError(Exception):
    """Ollama is unreachable or the model is missing; the message is user-facing."""


def _model_names(host: str, opener: Opener, timeout: float) -> list[str]:
    url = f"{host}/api/tags"
    try:
        with opener(urllib.request.Request(url, method="GET"), timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise LearningPreflightError(f"Ollama preflight: HTTP {exc.code} from {url}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise LearningPreflightError(f"Ollama preflight: timeout after {timeout:g} s calling {url}") from exc
    except urllib.error.URLError as exc:
        raise LearningPreflightError(f"cannot reach Ollama at {host}: {exc.reason}") from exc
    except OSError as exc:
        raise LearningPreflightError(f"Ollama preflight: error calling {url}: {exc}") from exc
    try:
        names = []
        for m in json.loads(raw)["models"]:
            names += [n for n in (m.get("name"), m.get("model")) if isinstance(n, str)]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LearningPreflightError(f"Ollama preflight: invalid response from {url}: {raw[:200]!r}") from exc
    return names


def has_model(model: str, names: list[str]) -> bool:
    return model in names or (":" not in model and f"{model}:latest" in names)


def learning_preflight(config: Config, *, opener: Opener | None = None,
                       timeout: float = PREFLIGHT_TIMEOUT) -> None:
    """Raise :class:`LearningPreflightError` unless Ollama answers and lists ``[learning] model``."""
    host = resolve_host(config.learning.ollama_host)
    model = config.learning.model
    names = _model_names(host, opener or urllib.request.urlopen, timeout)
    if not has_model(model, names):
        raise LearningPreflightError(f"model {model!r} ([learning] model) is not available at {host} "
                                     f"(ollama pull {model})")
    log.info("preflight: ollama %s ok (%s)", host, model)
