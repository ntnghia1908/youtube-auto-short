"""HD2a G4: lend the HD source of a released video back to a job for the duration of the job.

``borrow_hd`` downloads the HD from the store to ``<dest_dir>/source_hd.mp4`` (the place HD1 deleted it from), checks the
sha256 recorded when the video was released, and removes the file again when the block ends; ``enhance.json``
``released`` is never changed, so every render key (it uses the same sha256) stays what it was."""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from ..config import Config
from ..enhance import state as enh
from ..render.stage import RenderError, StoreWait
from .client import StoreClient, StoreError

log = logging.getLogger("auto_short")

WAIT_PREFIX = "đợi 3090"
_LOCK = threading.Lock()
_FETCH = threading.Lock()
_BORROWED: Counter = Counter()  # path -> number of jobs using the file we fetched


def released_hd_sha(config: Config, episode_id: str, dest_dir: Path) -> str | None:
    """The sha256 of the HD recorded at release (``backup.json`` ``released.hd``; else ``enhance.json``)."""
    owner_dir = Path(config.workspace.dir) / enh.owner_for(config, episode_id)
    try:
        doc = json.loads((owner_dir / "backup.json").read_text(encoding="utf-8"))
        sha = (((doc.get("released") or {}).get("hd")) or {}).get("sha256")
    except (OSError, ValueError, AttributeError):
        sha = None
    if isinstance(sha, str) and sha:
        return sha
    for d in (Path(dest_dir), owner_dir):
        sha = (enh.read(d) or {}).get("source_hd_sha256")
        if isinstance(sha, str) and sha:
            return sha
    return None


def refusal(owner: str) -> RenderError:
    """The HD1 G3 refusal (store off)."""
    return RenderError(f"{owner!r}: {enh.RELEASED_MESSAGE}; không dựng lại từ bản gốc")


@contextmanager
def borrow_hd(config: Config, episode_id: str, dest_dir: Path | None = None, *, client: StoreClient | None = None):
    """Yield with ``source_hd.mp4`` present in ``dest_dir`` (default: the owner workspace). Store off -> the HD1
    refusal (:class:`RenderError`); store down / file missing / sha256 differs -> :class:`StoreWait` ("đợi 3090: …",
    never a silent fall-back to the original). Only the file this call fetched is deleted afterwards."""
    owner = enh.owner_for(config, episode_id)
    dest_dir = Path(dest_dir) if dest_dir is not None else Path(config.workspace.dir) / owner
    if not config.store.enabled:
        raise refusal(owner)
    dest = enh.hd_path(dest_dir)
    real = False
    with _FETCH:  # one fetch at a time; a second job of the same file joins the first one's copy
        if _BORROWED[dest] == 0 and dest.is_file():
            real = True  # a real file (not released after all): nothing to lend, nothing to delete
        elif _BORROWED[dest] == 0:
            sha = released_hd_sha(config, episode_id, dest_dir)
            if sha is None:
                raise StoreWait(f"{WAIT_PREFIX}: không biết sha256 của bản HD đã giải phóng ({owner})")
            client = client or StoreClient.from_config(config.store)
            try:
                client.fetch(enh.owner_id(episode_id), "hd", dest, sha)
            except StoreError as exc:
                raise StoreWait(f"{WAIT_PREFIX}: {exc}") from exc
            log.info("store: mượn HD %s từ kho (%d bytes)", owner, dest.stat().st_size)
        if not real:
            with _LOCK:
                _BORROWED[dest] += 1
    if real:
        yield dest
        return
    try:
        yield dest
    finally:
        with _LOCK:
            _BORROWED[dest] -= 1
            last = _BORROWED[dest] <= 0
            if last:
                del _BORROWED[dest]
        if last:
            dest.unlink(missing_ok=True)
            dest.with_name(dest.name + ".part").unlink(missing_ok=True)
            log.info("store: đã xóa HD mượn %s", owner)
