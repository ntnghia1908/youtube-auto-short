"""Khai thị episodes (CP8.9): the ``work/<id>/khaithi.json`` parameter file and the effective analysis / selection
parameters derived from it. Pure functions + one atomic write; shared by analysis, selection, ingest, transcript,
the pipeline, the CLI and the web.

Canonical contract: docs/decisions/CP8.9-khai-thi-contract.md (K1-K4, K9).

The kind of an episode is decided ONLY by the presence of ``khaithi.json`` (never by the ``.kt`` suffix of its id).
Without the file every function here leaves the config untouched, so a Short keeps its config hashes byte for byte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config
from .workspace import WorkspaceError, atomic_write_json, validate_episode_id

KHAITHI_NAME = "khaithi.json"
SCHEMA_VERSION = 1
KIND = "khaithi"
SUFFIX = ".kt"


class KhaithiError(Exception):
    """Invalid khai thị parameters or ``khaithi.json`` (user-facing). ``vi`` is the Vietnamese message (web 422)."""

    def __init__(self, message: str, vi: str | None = None):
        super().__init__(message)
        self.vi = vi or message


@dataclass(frozen=True)
class KhaiThi:
    base_episode_id: str
    min_minutes: int
    max_minutes: int

    def to_json(self) -> dict:
        """The file content, key order fixed, no timestamp (K1)."""
        return {"schema_version": SCHEMA_VERSION, "kind": KIND, "base_episode_id": self.base_episode_id,
                "min_minutes": self.min_minutes, "max_minutes": self.max_minutes}

    @property
    def label(self) -> str:
        return f"{self.min_minutes}–{self.max_minutes}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_minutes(min_minutes: object, max_minutes: object, limit: int) -> tuple[int, int]:
    """K2: whole numbers, ``1 <= min < max <= limit``. Returns (min, max) or raises :class:`KhaithiError`."""
    if not _is_int(min_minutes) or not _is_int(max_minutes):
        raise KhaithiError("min_minutes and max_minutes must be whole numbers of minutes",
                           "Số phút tối thiểu / tối đa phải là số nguyên")
    if min_minutes < 1:
        raise KhaithiError("min_minutes must be >= 1", "Số phút tối thiểu phải từ 1 trở lên")
    if max_minutes > limit:
        raise KhaithiError(f"max_minutes must be <= {limit} ([khaithi] max_minutes_limit)",
                           f"Số phút tối đa không được quá {limit}")
    if not min_minutes < max_minutes:
        raise KhaithiError("min_minutes must be < max_minutes", "Số phút tối thiểu phải nhỏ hơn số phút tối đa")
    return min_minutes, max_minutes


def episode_id_for(base_episode_id: str) -> str:
    """``<base_id>.kt`` (K1); both ids must be valid CP2 D3 episode ids."""
    try:
        validate_episode_id(base_episode_id)
        return validate_episode_id(base_episode_id + SUFFIX)
    except WorkspaceError as exc:
        raise KhaithiError(str(exc), f"id tập không hợp lệ: {base_episode_id!r}") from exc


def path_of(ws_dir: Path) -> Path:
    return Path(ws_dir) / KHAITHI_NAME


def read(ws_dir: Path, limit: int) -> KhaiThi | None:
    """``khaithi.json`` of a workspace dir: None when absent (a Short); a broken file raises :class:`KhaithiError`."""
    path = path_of(ws_dir)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KhaithiError(f"cannot read {path}: {exc}", f"không đọc được {KHAITHI_NAME}: {exc}") from exc
    bad = KhaithiError(f"{path}: invalid khai thi file (expected schema_version 1, kind \"khaithi\", "
                       "base_episode_id, min_minutes, max_minutes)", f"{KHAITHI_NAME} không hợp lệ")
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or doc.get("kind") != KIND:
        raise bad
    base = doc.get("base_episode_id")
    if not isinstance(base, str):
        raise bad
    try:
        validate_episode_id(base)
    except WorkspaceError as exc:
        raise KhaithiError(f"{path}: {exc}", f"{KHAITHI_NAME}: base_episode_id không hợp lệ") from exc
    try:
        lo, hi = check_minutes(doc.get("min_minutes"), doc.get("max_minutes"), limit)
    except KhaithiError as exc:
        raise KhaithiError(f"{path}: {exc}", f"{KHAITHI_NAME}: {exc.vi}") from exc
    return KhaiThi(base, lo, hi)


def read_quiet(ws_dir: Path, limit: int) -> KhaiThi | None:
    """Like :func:`read` but a broken file reads as None (read-only views)."""
    try:
        return read(ws_dir, limit)
    except KhaithiError:
        return None


def write(ws_dir: Path, kt: KhaiThi) -> bool:
    """Write ``khaithi.json`` atomically when its content changes; returns True when it was (re)written."""
    path = path_of(ws_dir)
    text = json.dumps(kt.to_json(), indent=2, ensure_ascii=False) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    atomic_write_json(path, kt.to_json())
    return True


# --- K2-K4 effective parameters ---------------------------------------------------------------------------


def effective_config(config: Config, kt: KhaiThi | None) -> Config:
    """The config analysis / selection use for an episode: unchanged for a Short (``kt`` None); for a khai thị
    episode ``[analysis]`` durations = the minutes (K2), ``[khaithi] prompt_version`` with the minutes (K3) and the
    larger window (K4). Every other key keeps its ``[analysis]`` / ``[selection]`` value."""
    if kt is None:
        return config
    lo, hi = 60.0 * kt.min_minutes, 60.0 * kt.max_minutes
    analysis = replace(config.analysis, min_duration=lo, max_duration=hi, target_min=lo, target_max=hi)
    sel = config.selection
    selection = replace(sel, prompt_version=config.khaithi.prompt_version,
                        max_window_words=max(sel.max_window_words,
                                             config.khaithi.window_words_per_minute * kt.max_minutes),
                        duration_minutes=(kt.min_minutes, kt.max_minutes))
    return replace(config, analysis=analysis, selection=selection)


def load_effective(config: Config, ws_dir: Path) -> tuple[Config, KhaiThi | None]:
    """(effective config, khai thị parameters or None) of a workspace dir; raises :class:`KhaithiError`."""
    kt = read(ws_dir, config.khaithi.max_minutes_limit)
    return effective_config(config, kt), kt


def prepare(config: Config, base_episode_id: str, min_minutes: object, max_minutes: object) -> tuple[str, bool]:
    """``run`` (CLI / web) before any stage: validate, refuse an archived episode, write / update
    ``work/<base_id>.kt/khaithi.json``. Returns (episode id, file changed). Nothing is written on error."""
    lo, hi = check_minutes(min_minutes, max_minutes, config.khaithi.max_minutes_limit)
    episode_id = episode_id_for(base_episode_id)
    ws_dir = Path(config.workspace.dir) / episode_id
    from .review.archive import is_archived  # review imports the web-free core only

    if is_archived(ws_dir):
        raise KhaithiError(f"episode {episode_id!r} is archived (source video cleaned up); delete the episode to "
                           "run it again", f"tập {episode_id}: đã dọn video nguồn; muốn chạy lại thì xóa tập")
    return episode_id, write(ws_dir, KhaiThi(base_episode_id, lo, hi))
