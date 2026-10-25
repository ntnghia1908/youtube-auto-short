"""SRC4: process-wide source index; cache misses and store failures for five minutes too."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from ..config import Config, StoreConfig
from .client import StoreClient

TTL_SECONDS = 300.0
_CHANGED = threading.Condition()
_CACHE: dict[StoreConfig, tuple[float, dict[str, dict]]] = {}
_REFRESHING: object | None = None
_GENERATION = 0
_LISTENERS: set[Callable[[], None]] = set()
log = logging.getLogger("auto_short")


def add_listener(callback: Callable[[], None]) -> None:
    """Register once; the owner must remove the callback when it stops."""
    with _CHANGED:
        _LISTENERS.add(callback)


def remove_listener(callback: Callable[[], None]) -> None:
    """Unregister a callback; an already dispatched callback may still finish."""
    with _CHANGED:
        _LISTENERS.discard(callback)


def invalidate() -> None:
    """Forget all snapshots (for tests or after uploading a new source)."""
    global _GENERATION
    with _CHANGED:
        _CACHE.clear()
        _GENERATION += 1  # an in-flight refresh must not republish an invalidated snapshot


def _refresh(config: StoreConfig, generation: int) -> None:
    """Fetch outside the cache lock; publish an empty snapshot on failure."""
    global _REFRESHING
    try:
        rows = StoreClient.from_config(config).index()
        sources = {row["video_id"]: dict(row) for row in rows
                   if isinstance(row, dict) and row.get("kind") == "source"
                   and isinstance(row.get("video_id"), str)}
    except Exception:
        sources = {}
    with _CHANGED:
        listeners = ()
        if generation == _GENERATION:
            _CACHE[config] = (time.monotonic() + TTL_SECONDS, sources)
            listeners = tuple(_LISTENERS)
        _REFRESHING = None
        _CHANGED.notify_all()
    # A listener can acquire the scheduler lock; never call it while holding the cache lock.
    for callback in listeners:
        try:
            callback()
        except Exception:
            log.debug("store index listener failed", exc_info=True)


def source_entry(config: Config, video_id: str, *, blocking: bool = True) -> dict | None:
    """Read a source row; optionally wait for a fresh index (ingest, outside scheduler locks).

    Nonblocking readers return the existing snapshot, even when stale, or None on a cold cache.
    An expired snapshot starts one background refresh at a time across store configurations.
    Neither mode holds the cache lock during network IO; failures are cached for five minutes.
    """
    global _REFRESHING
    if not config.store.enabled:
        return None
    with _CHANGED:
        while True:
            cached = _CACHE.get(config.store)
            if cached is not None and time.monotonic() < cached[0]:
                break
            if _REFRESHING is None:
                worker = threading.Thread(target=_refresh, args=(config.store, _GENERATION),
                                          name="store-index-refresh", daemon=True)
                _REFRESHING = worker
                try:
                    worker.start()
                except RuntimeError:
                    _REFRESHING = None
                    _CACHE[config.store] = (time.monotonic() + TTL_SECONDS, {})
                    _CHANGED.notify_all()
                    return None
            if not blocking:
                break
            _CHANGED.wait()
        entry = cached[1].get(video_id) if cached else None
        return dict(entry) if entry is not None else None


def has_source(config: Config, video_id: str, *, blocking: bool = True) -> bool:
    """Whether the store snapshot contains this source; store errors never escape."""
    return source_entry(config, video_id, blocking=blocking) is not None
