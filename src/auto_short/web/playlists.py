"""Bộ kinh = YouTube playlist on the web (CP8.7 L1–L5).

A playlist is listed with ``yt-dlp`` ``extract_flat`` (no video is downloaded) and stored as
``<workspace.dir>/_playlists/<playlist_id>.json`` (the leading ``_`` can never be an episode id, CP2 D3). The
processing state of each entry is never stored there: it is read from ``work/<video_id>/manifest.json`` and the
job runner (single source of truth); "Xong" is derived (L4). Processing an entry = submitting
``https://youtu.be/<video_id>`` like a single video (L3).

Canonical contract: docs/decisions/CP8.3-web-contract.md W10.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .. import khaithi
from ..config import Config
from ..post import doc as post_doc
from ..review import ReviewError, episode_complete, publish_status, read_archive, read_publish, read_tombstone
from ..review.names import MAX_COPY_CHARS, copy_text, hashtag, hashtags
from ..review.publish import PUBLISH_NAME
from ..titling.logic import match_title
from ..titling.playlist import PLAYLISTS_DIR, normalize_series, stored_series
from ..enhance import state as enh_state
from ..workspace import DONE, Workspace, WorkspaceError, atomic_write_json
from . import episodes as ep
from . import prepared
from .urls import PLAYLIST_ID_RE, playlist_url, valid_playlist_id

log = logging.getLogger("auto_short")

SCHEMA_VERSION = 1
LIST_TIMEOUT = 60.0  # L5: seconds for listing a playlist inside the request
STATUS_CACHE_SECONDS = 5.0  # L5
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]", "[Unavailable video]"}

# entry states (L4 + UI filter groups)
NEW, QUEUED, PROCESSING, FAILED, RENDERED, INCOMPLETE, COMPLETE, UNAVAILABLE, DELETED = (
    "new", "queued", "processing", "failed", "rendered", "incomplete", "complete", "unavailable", "deleted")
# CP13.2 H1: "Chuẩn bị + HD" finished (prepare lane done, AI not run): waits for "Chạy tiếp"; its own filter group,
# never "Lỗi / dở dang".
PREPARED = "prepared"
# CP8.13 G1: Chưa xử lý / Đang xử lý / Lỗi / dở dang / Đang làm (render done, not every Short ticked) / Xong; an
# unavailable entry is only under "Tất cả". One table for the entry ``group``, ``counts`` and the summary (G3).
GROUPS = {NEW: "todo", QUEUED: "running", PROCESSING: "running", FAILED: "failed", INCOMPLETE: "failed",
          RENDERED: "doing", COMPLETE: "done", UNAVAILABLE: None}
GROUP_NAMES = ("todo", "running", "failed", "doing", "done")
# button per state: process (Xử lý), resume (Chạy tiếp), reprocess (Xử lý lại, asks first: new download, the AI may
# choose other clips / titles)
ACTIONS = {NEW: "process", FAILED: "resume", INCOMPLETE: "resume", DELETED: "reprocess", PREPARED: "resume"}


def group_of(state: str, complete: bool) -> str | None:
    if state == PREPARED:  # CP13.2: not in GROUPS (the CP8.13 table is unchanged); own tab "Chờ cắt"
        return "prepared"
    if state == DELETED:  # tombstone: Xong when it was Xong at deletion, else back to "Chưa xử lý"
        return "done" if complete else "todo"
    return GROUPS[state]

Lister = Callable[[str, Config], dict]  # (playlist url, config) -> yt-dlp flat info {"id", "title", "entries"}


MAX_HASHTAGS = 15
USER_FIELDS = ("hashtags", "series", "doc_url")
SAMPLE_TITLE = "Tiêu đề mẫu dài sáu mươi ký tự để xem trước hashtag trên YouTube"[:60]


class PlaylistError(Exception):
    """Listing failed or the stored document is invalid (user-facing message)."""


def normalize_hashtags(values: object) -> list[str]:
    """Per-playlist hashtag list (bổ sung HUMAN LEAD 2026-09-27): each value -> the ``hashtag()`` form, stored
    without ``#``; empty, duplicate (case-insensitive) or more than 15 tags -> PlaylistError (422)."""
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise PlaylistError("hashtags phải là danh sách chuỗi")
    out, seen = [], set()
    for raw in values:
        tag = hashtag(raw)
        if tag is None:
            raise PlaylistError(f"hashtag rỗng sau khi bỏ khoảng trắng / dấu câu: {raw!r}")
        if tag.casefold() in seen:
            raise PlaylistError(f"hashtag trùng: {tag}")
        seen.add(tag.casefold())
        out.append(tag[1:])
    if len(out) > MAX_HASHTAGS:
        raise PlaylistError(f"tối đa {MAX_HASHTAGS} hashtag")
    return out


def stored_doc_url(doc: dict) -> str | None:
    """The playlist's lecture-document link (CP8.19 D1), or None when absent or not a valid link."""
    try:
        return post_doc.normalize_url(doc.get("doc_url"))
    except post_doc.DocError:
        return None


def custom_hashtags(doc: dict) -> list[str] | None:
    """The playlist's stored hashtag list (H1), or None (default) when absent or not a list of strings."""
    tags = doc.get("hashtags")
    if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
        return list(tags)
    return None


def ytdlp_list(url: str, config: Config) -> dict:
    """``yt-dlp`` flat extraction of a playlist: entries with id / title / duration, nothing downloaded."""
    import yt_dlp

    opts = {"extract_flat": "in_playlist", "skip_download": True, "quiet": True, "no_warnings": True,
            "socket_timeout": 30, "js_runtimes": {name: {} for name in config.ingest.js_runtimes}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=False))
    except yt_dlp.utils.DownloadError as exc:
        raise PlaylistError(f"không lấy được playlist từ YouTube: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def episode_number(title: str | None, config: Config) -> str | None:
    """Episode number from the entry title with the first matching CP6 ``[titling.header] title_patterns`` entry
    (group ``episode``, CP8.11 D4), e.g. "Thập Thiện Nghiệp Đạo Kinh tập 1/149 - …" -> "1",
    'Tập 11/128: Giảng "Thái Thượng Cảm Ứng Thiên" | …' -> "11"."""
    m = match_title(config.titling.header.title_patterns, title)
    if m is None or "episode" not in m.re.groupindex or m.group("episode") is None:
        return None
    return m.group("episode")


def title_series(title: str | None, config: Config) -> str | None:
    """Series name of an entry title from the first matching ``title_patterns`` entry (group ``series``)."""
    m = match_title(config.titling.header.title_patterns, title)
    if m is None or "series" not in m.re.groupindex or m.group("series") is None:
        return None
    return " ".join(unicodedata.normalize("NFC", m.group("series")).split()) or None


def _with_user_fields(doc: dict, source: dict) -> dict:
    """``doc`` with the user's fields of ``source`` (``hashtags``, ``series``, ``doc_url``, after ``entries``; H5, D5,
    CP8.19 D1)."""
    for key in USER_FIELDS:
        doc.pop(key, None)
    for key in USER_FIELDS:
        if key in source:
            doc[key] = source[key]
    return doc


def build_document(info: dict, playlist_id: str, config: Config, *, now: str | None = None) -> dict:
    """L1 document from a flat yt-dlp info dict (entries in playlist order, 1-based ``index``)."""
    entries = []
    for n, e in enumerate(info.get("entries") or [], 1):
        if not isinstance(e, dict):
            continue
        vid, title = e.get("id"), e.get("title")
        available = isinstance(vid, str) and bool(_VIDEO_ID_RE.match(vid)) and title not in UNAVAILABLE_TITLES \
            and e.get("availability") not in ("private", "needs_auth", "subscriber_only", "premium_only")
        duration = e.get("duration")
        entries.append({"index": int(e.get("playlist_index") or n),
                        "video_id": vid if isinstance(vid, str) and _VIDEO_ID_RE.match(vid) else None,
                        "title": title if isinstance(title, str) else None,
                        "duration": float(duration) if isinstance(duration, (int, float)) else None,
                        "episode": episode_number(title, config) if available else None,
                        "available": available})
    return {"schema_version": SCHEMA_VERSION, "playlist_id": playlist_id,
            "title": info.get("title") if isinstance(info.get("title"), str) else playlist_id,
            "url": playlist_url(playlist_id), "fetched_at": now or _now(), "entries": entries}


class PlaylistStore:
    """Stored playlists + listing with a timeout (L5) + per-video status cache (≤ 5 s, L5)."""

    def __init__(self, config: Config, *, lister: Lister = ytdlp_list, timeout: float = LIST_TIMEOUT,
                 monotonic: Callable[[], float] = time.monotonic):
        self._config, self._lister, self._timeout, self._mono = config, lister, timeout, monotonic
        self._lock = threading.Lock()  # read-modify-write of one playlist file
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def root(self) -> Path:
        return Path(self._config.workspace.dir) / PLAYLISTS_DIR

    def path(self, playlist_id: str) -> Path:
        if not valid_playlist_id(playlist_id):
            raise PlaylistError("playlist id không hợp lệ")
        return self.root / f"{playlist_id}.json"

    # --- documents -------------------------------------------------------------------------------------

    def load(self, playlist_id: str) -> dict | None:
        path = self.path(playlist_id)
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PlaylistError(f"không đọc được {path.name}: {exc}") from exc
        if not isinstance(doc, dict) or doc.get("playlist_id") != playlist_id \
                or not isinstance(doc.get("entries"), list):
            raise PlaylistError(f"{path.name} không hợp lệ")
        return doc

    def all(self) -> list[dict]:
        out = []
        if self.root.is_dir():
            for p in sorted(self.root.glob("*.json")):
                if not PLAYLIST_ID_RE.match(p.stem):
                    continue
                try:
                    doc = self.load(p.stem)
                except PlaylistError:
                    continue
                if doc is not None:
                    out.append(doc)
        return out

    def video_ids(self) -> set[str]:
        return {e["video_id"] for d in self.all() for e in d["entries"] if e.get("video_id")}

    def fetch(self, playlist_id: str) -> dict:
        """List the playlist now (in a helper thread, at most ``timeout`` seconds)."""
        result: dict = {}

        def run() -> None:
            try:
                result["info"] = self._lister(playlist_url(playlist_id), self._config)
            except Exception as exc:  # reported to the user
                result["error"] = exc

        t0 = time.monotonic()
        worker = threading.Thread(target=run, name="auto-short-playlist", daemon=True)
        worker.start()
        worker.join(self._timeout)
        if worker.is_alive():
            raise PlaylistError(f"YouTube không trả lời trong {self._timeout:.0f} giây khi liệt kê playlist; "
                                "thử lại sau")
        if "error" in result:
            exc = result["error"]
            raise exc if isinstance(exc, PlaylistError) else PlaylistError(f"không lấy được playlist: {exc}")
        doc = build_document(result.get("info") or {}, playlist_id, self._config)
        log.info("web: listed playlist %s (%d entries) in %.1f s", playlist_id, len(doc["entries"]),
                 time.monotonic() - t0)
        return doc

    def add(self, playlist_id: str) -> tuple[dict, bool]:
        """Import a playlist (L1); an already stored one is returned as is (``created`` False; use refresh)."""
        existing = self.load(playlist_id)
        if existing is not None:
            return existing, False
        doc = self.fetch(playlist_id)
        if not doc["entries"]:
            raise PlaylistError("playlist trống hoặc không truy cập được")
        with self._lock:
            atomic_write_json(self.path(playlist_id), doc)
        return doc, True

    def refresh(self, playlist_id: str) -> tuple[dict, list[str]]:
        """"Cập nhật danh sách": replace ``entries`` (playlist order from YouTube); returns the new video ids."""
        old = self.load(playlist_id)
        if old is None:
            raise FileNotFoundError(playlist_id)
        doc = self.fetch(playlist_id)
        before = {e.get("video_id") for e in old["entries"]}
        added = [e["video_id"] for e in doc["entries"] if e.get("video_id") and e["video_id"] not in before]
        with self._lock:
            # the user's hashtags (H5) and series name (CP8.11 D5) survive "Cập nhật danh sách"; re-read under the
            # lock: saved during the fetch
            current = self.load(playlist_id)
            if current is not None:
                _with_user_fields(doc, current)
            atomic_write_json(self.path(playlist_id), doc)
        return doc, added

    # --- hashtags (bổ sung HUMAN LEAD 2026-09-27) -----------------------------------------------------

    def set_hashtags(self, playlist_id: str, values: list[str] | None) -> dict:
        """Store the playlist's full ordered hashtag list (``None`` = back to the default: field removed)."""
        tags = normalize_hashtags(values) if values is not None else None
        with self._lock:
            doc = self.load(playlist_id)
            if doc is None:
                raise FileNotFoundError(playlist_id)
            fields = {k: doc[k] for k in USER_FIELDS if k in doc and k != "hashtags"}
            if tags is not None:
                fields["hashtags"] = tags
            _with_user_fields(doc, fields)
            atomic_write_json(self.path(playlist_id), doc)
        return doc

    # --- "Tên bộ kinh" (CP8.11 D5) ----------------------------------------------------------------------

    def set_series(self, playlist_id: str, value: object) -> dict:
        """Store the playlist's series name (``None`` = not set: field removed); invalid -> PlaylistError (422)."""
        try:
            series = normalize_series(value) if value is not None else None
        except ValueError as exc:
            raise PlaylistError(str(exc)) from exc
        with self._lock:
            doc = self.load(playlist_id)
            if doc is None:
                raise FileNotFoundError(playlist_id)
            fields = {k: doc[k] for k in USER_FIELDS if k in doc and k != "series"}
            if series is not None:
                fields["series"] = series
            _with_user_fields(doc, fields)
            atomic_write_json(self.path(playlist_id), doc)
        return doc

    # --- "Văn bản gốc" (CP8.19 D1) ------------------------------------------------------------------------------

    def set_doc_url(self, playlist_id: str, value: object) -> dict:
        """Store the playlist's lecture-document link (``None`` = removed); a link of another form -> PlaylistError
        (422)."""
        try:
            url = post_doc.normalize_url(value) if value is not None else None
        except post_doc.DocError as exc:
            raise PlaylistError(str(exc)) from exc
        with self._lock:
            doc = self.load(playlist_id)
            if doc is None:
                raise FileNotFoundError(playlist_id)
            fields = {k: doc[k] for k in USER_FIELDS if k in doc and k != "doc_url"}
            if url is not None:
                fields["doc_url"] = url
            _with_user_fields(doc, fields)
            atomic_write_json(self.path(playlist_id), doc)
        return doc

    def hashtags_for(self, video_id: str) -> list[str] | None:
        """Custom hashtags of the first stored playlist (by playlist id) listing ``video_id`` that has a custom
        list (H4); None -> default (#<series> + ``[web] hashtags``)."""
        for doc in self.all():
            tags = custom_hashtags(doc)
            if tags is not None and any(e.get("video_id") == video_id for e in doc["entries"]):
                return tags
        return None

    def effective_hashtags(self, doc: dict) -> tuple[list[str], bool]:
        """(tags with ``#``, custom?) of a playlist: custom list, else ``#<series>`` of its first processed episode
        + ``[web] hashtags``."""
        tags = custom_hashtags(doc)
        if tags is not None:
            return [f"#{t}" for t in tags], True
        series = None
        for e in doc["entries"]:
            if e.get("video_id"):
                series = ep._series(self._config, e["video_id"])
                if series:
                    break
        return hashtags(series, tuple(self._config.web.hashtags)), False

    def sample_title(self, doc: dict) -> tuple[str, bool]:
        """Longest title in the files of the playlist's processed episodes, else a 60-char sample."""
        best = ""
        for e in doc["entries"]:
            rm = ep._render_manifest(self._config, e["video_id"]) if e.get("video_id") else None
            for s in (rm or {}).get("shorts", []):
                t = s.get("title") if isinstance(s, dict) and s.get("status") == "rendered" else None
                if isinstance(t, str) and len(t) > len(best):
                    best = t
        return (best, True) if best else (SAMPLE_TITLE, False)

    def preview(self, doc: dict, values: list[str] | None) -> dict:
        tags = [f"#{t}" for t in normalize_hashtags(values)] if values is not None \
            else self.effective_hashtags(doc)[0]
        title, real = self.sample_title(doc)
        text, kept = copy_text(title, None, [t[1:] for t in tags])
        return {"hashtags": tags, "title": title, "title_is_real": real, "copy_text": text, "chars": len(text),
                "max_chars": MAX_COPY_CHARS, "dropped": tags[len(kept):]}

    def remove(self, playlist_id: str) -> bool:
        """"Xóa bộ kinh": only the stored list; processed episodes stay."""
        path = self.path(playlist_id)
        with self._lock:
            if not path.is_file():
                return False
            path.unlink()
        return True

    # --- status (L4) ------------------------------------------------------------------------------------

    def _disk_status(self, video_id: str) -> dict:
        """Status of one entry from its workspace (cached ≤ 5 s)."""
        hit = self._cache.get(video_id)
        if hit is not None and self._mono() - hit[0] < STATUS_CACHE_SECONDS:
            return hit[1]
        st = disk_status(self._config, video_id)
        self._cache[video_id] = (self._mono(), st)
        return st

    def invalidate(self, video_id: str | None = None) -> None:
        if video_id is None:
            self._cache.clear()
        else:
            self._cache.pop(video_id, None)
            self._cache.pop(video_id + khaithi.SUFFIX, None)  # CP8.9: the entry also shows its khai thi episode

    def _kind_status(self, episode_id: str, job: dict | None) -> dict:
        """Disk status of one episode (Short or khai thi) with its live job on top (L4)."""
        st = dict(self._disk_status(episode_id))
        if job is not None and job["status"] in ("queued", "running"):
            st["state"] = QUEUED if job["status"] == "queued" else PROCESSING
            st["stage"] = job.get("stage")
        elif job is not None and job["status"] in ("failed", "interrupted") and st["state"] != COMPLETE:
            st["state"], st["error"] = FAILED, job.get("error") or job["status"]
        return st

    def _khaithi_id(self, video_id: str | None) -> str | None:
        """``<video_id>.kt`` when ``work/<video_id>.kt/`` exists (CP8.9 K8), else None."""
        if not video_id:
            return None
        try:
            kid = khaithi.episode_id_for(video_id)
        except khaithi.KhaithiError:
            return None
        return kid if (Path(self._config.workspace.dir) / kid).is_dir() else None

    def view(self, doc: dict, jobs: dict[str, dict]) -> dict:
        """Playlist page: entries (playlist order) with status (disk + live job), counts per filter group. CP8.9
        A1.4: with a khai thi episode ``<video_id>.kt`` the entry state combines both episodes."""
        # ``counts["prepared"]`` (CP13.2) exists only when some entry is prepared
        entries, counts = [], {"all": 0, **{g: 0 for g in GROUP_NAMES}}
        for e in doc["entries"]:
            vid = e.get("video_id")
            usable = bool(e.get("available") and vid)
            job = jobs.get(vid) if vid else None
            kid = self._khaithi_id(vid) if usable else None
            if not usable:
                st = {"state": UNAVAILABLE}
            else:
                kst = self._kind_status(kid, jobs.get(kid)) if kid is not None else None
                st = combine_status(self._kind_status(vid, job), kst)
            st["group"] = group_of(st["state"], bool(st.get("complete")))
            st["action"] = ACTIONS.get(st["state"]) if usable else None
            st["resume_kinds"] = resume_kinds(st) if usable else None  # A1.2 "Chạy tiếp"
            st["job"] = job
            st["khaithi_job"] = jobs.get(kid) if kid is not None else None
            st["khaithi_episode_id"] = kid
            counts["all"] += 1
            if st["group"]:
                counts[st["group"]] = counts.get(st["group"], 0) + 1
            st["hd"] = hd_progress(self._config, vid) if usable else None  # CP13.2 H1
            entries.append({**e, **st})
        tags, custom = self.effective_hashtags(doc)
        return {"id": doc["playlist_id"], "title": doc.get("title"), "url": doc.get("url"),
                "fetched_at": doc.get("fetched_at"), "count": len(doc["entries"]), "entries": entries,
                "counts": counts, "hashtags": tags, "hashtags_custom": custom, "doc_url": stored_doc_url(doc),
                **self.series_view(doc)}

    def series_view(self, doc: dict) -> dict:
        """CP8.11 D7: ``series`` (the user's name or null), ``series_suggested`` (series of the first entry title a
        pattern recognizes, or null), ``unrecognized`` (available entries whose title no pattern matches)."""
        patterns = self._config.titling.header.title_patterns
        suggested, unrecognized = None, 0
        for e in doc["entries"]:
            if not e.get("available"):
                continue
            title = e.get("title")
            if match_title(patterns, title) is None:
                unrecognized += 1
            elif suggested is None:
                suggested = title_series(title, self._config)
        return {"series": stored_series(doc), "series_suggested": suggested, "unrecognized": unrecognized}

    def summary(self, doc: dict, jobs: dict[str, dict]) -> dict:
        v = self.view(doc, jobs)
        processed = sum(1 for e in v["entries"] if e["state"] not in (NEW, UNAVAILABLE))
        deleted = sum(1 for e in v["entries"] if e["state"] == DELETED)
        return {"id": v["id"], "title": v["title"], "count": v["count"], "fetched_at": v["fetched_at"],
                "processed": processed, "complete": v["counts"]["done"], "running": v["counts"]["running"],
                "failed": v["counts"]["failed"], "doing": v["counts"]["doing"], "deleted": deleted}


_RANK = {NEW: 0, DELETED: 0, INCOMPLETE: 1, PREPARED: 1, RENDERED: 2, COMPLETE: 3}
_DONE_STATES = (RENDERED, COMPLETE)


def combine_status(short: dict, kt: dict | None) -> dict:
    """CP8.9 A1.4: entry status of a video from its Short status and, when ``work/<video_id>.kt/`` exists, its khai
    thi status. Without a khai thi episode the Short status is returned unchanged (plus empty khai thi fields).
    A job queued / running on either -> ``queued`` / ``processing``; either failed -> ``failed`` (error names which);
    otherwise the less advanced of the two (new / deleted < incomplete < rendered < complete): "Xong" needs both."""
    out = dict(short, short_state=short["state"], khaithi_state=None, khaithi_videos=None, khaithi_published=None)
    if kt is None:
        return out
    out.update(khaithi_state=kt["state"], khaithi_videos=kt["shorts"], khaithi_published=kt["published"])
    pair = (("Short", short), ("khai thị", kt))
    for state in (PROCESSING, QUEUED):
        hit = next(((name, st) for name, st in pair if st["state"] == state), None)
        if hit is not None:
            out.update(state=state, stage=hit[1].get("stage"), error=None, complete=False)
            return out
    failed = [(name, st) for name, st in pair if st["state"] == FAILED]
    if failed:
        out.update(state=FAILED, stage=failed[0][1].get("stage"), complete=False,
                   error="; ".join(f"{name}: {st.get('error') or 'lỗi'}" for name, st in failed))
        return out
    name, low = min(pair, key=lambda x: _RANK.get(x[1]["state"], 0))
    out["state"] = low["state"]
    if low["state"] == DELETED:  # tombstone of the Short: Xong only if it was and the khai thi is Xong too
        out["complete"] = bool(short.get("complete")) and kt["state"] == COMPLETE
    else:
        out["complete"] = low["state"] == COMPLETE
    if name != "Short":
        out["stage"], out["error"] = kt.get("stage"), kt.get("error")
    return out


def resume_kinds(st: dict) -> list[str]:
    """CP8.9 A1.2 "Chạy tiếp": the Short unless its pipeline finished, plus the khai thi only when
    ``work/<video_id>.kt/`` exists and its pipeline has not finished (never creates a khai thi for an old
    episode)."""
    kinds = [] if st.get("short_state") in _DONE_STATES else ["short"]
    if st.get("khaithi_state") is not None and st["khaithi_state"] not in _DONE_STATES:
        kinds.append("khaithi")
    elif st.get("short_state") == PREPARED and st.get("khaithi_state") is None:
        kinds.append("khaithi")  # CP13.2 H2: "Chạy tiếp" a prepared episode cuts the Short and the khai thị
    return kinds or ["short"]


def hd_progress(config: Config, video_id: str) -> dict | None:
    """CP13.2 H1: the HD (enhance) progress of a video for its entry, from ``enhance.json``; None when the video has
    none or does not want HD. ``state``: ``queued`` | ``running`` | ``assembling`` | ``done`` | ``failed``."""
    doc = enh_state.read(Path(config.workspace.dir) / video_id)
    if doc is None or not doc.get("wanted"):
        return None
    lease = doc.get("lease") or {}
    exp = enh_state.parse_iso(lease.get("expires_at"))
    if doc.get("state") == enh_state.DONE:
        state = "done"
    elif doc.get("state") == enh_state.FAILED:
        state = "failed"
    elif doc.get("state") == enh_state.ASSEMBLING:
        state = "assembling"
    elif exp is not None and exp > time.time():
        state = "running"
    else:
        state = "queued"
    return {"state": state, "segments_done": len(doc.get("segments") or {}),
            "segments_total": enh_state.total_segments(doc), "worker": lease.get("worker") if state == "running" else None}


def disk_status(config: Config, video_id: str) -> dict:
    """State of an entry from ``work/<video_id>`` (L4): ``new`` (no workspace), ``processing`` (a stage
    running), ``failed``, ``incomplete``, ``rendered`` (render done, not every Short ticked), ``complete`` (Xong),
    plus Short counts and the archived flag."""
    out = {"state": NEW, "stage": None, "error": None, "shorts": 0, "published": 0, "archived": False,
           "complete": False, "deleted_at": None}
    try:
        ws = Workspace(Path(config.workspace.dir), video_id)
        manifest = ws.load_manifest()
    except WorkspaceError:
        return out
    if manifest is None:
        tomb = read_tombstone(config, video_id)  # deleted to save disk: stats kept (bổ sung HUMAN LEAD 2026-09-27)
        if tomb is not None:
            out.update(state=DELETED, complete=bool(tomb.get("complete")), deleted_at=tomb.get("deleted_at"),
                       shorts=tomb.get("shorts") or 0, published=tomb.get("published") or 0)
        return out
    stages = manifest.get("stages") or {}
    statuses = {s: (stages.get(s) or {}).get("status") for s in ep.PIPELINE_STAGES}
    doc = ep._render_manifest(config, video_id)
    rendered = [s for s in (doc or {}).get("shorts", []) if isinstance(s, dict) and s.get("status") == "rendered"]
    try:
        pub = read_publish(ws.dir / PUBLISH_NAME, video_id)
    except ReviewError:
        pub = {"published": []}
    status = publish_status(pub, rendered)
    out.update(shorts=len(rendered), archived=read_archive(ws.dir) is not None,
               published=sum(1 for s in rendered if status.get(s.get("clip_id"), {}).get("published")))
    running = next((s for s, st in statuses.items() if st == "running"), None)
    failed = next((s for s, st in statuses.items() if st == "failed"), None)
    if running:
        out.update(state=PROCESSING, stage=running)
    elif failed:
        out.update(state=FAILED, stage=failed, error=(stages.get(failed) or {}).get("error"))
    elif statuses.get("render") == DONE and doc is not None:
        complete = episode_complete(DONE, doc.get("shorts") or [], pub)
        out["state"] = COMPLETE if complete else RENDERED
        out["complete"] = complete
    elif prepared.is_prepared(ws.dir) and statuses.get("selection") != DONE \
            and all(statuses.get(s) == DONE for s in ("ingest", "transcript", "analysis")):
        out["state"] = PREPARED  # CP13.2 H1: "Đã chuẩn bị — chờ cắt"
    else:
        out["state"] = INCOMPLETE
    return out
