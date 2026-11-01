"""LNK1 web orchestration: owned-channel reads, scoped matching, locked post writes."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..post import links, store
from ..publish import youtube
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import episodes as ep
from .urls import ASK, PLAYLIST, UrlError, classify_url

log = logging.getLogger("auto_short")


def playlist_id_from_url(raw: str) -> str:
    """Reuse the web URL policy; watch+list selects the playlist without a prompt."""
    parsed = classify_url(raw)
    if parsed.kind not in (PLAYLIST, ASK) or not parsed.playlist_id:
        raise UrlError("cần link playlist YouTube; không nhận Mix / Xem sau / Đã thích")
    return parsed.playlist_id


def _safe_error(exc: Exception) -> str:
    # Never return exception text: OAuth / transport errors may contain credentials.
    if "quotaExceeded" in str(exc):
        return "YouTube hết quota; thử lại ngày mai, nếu vẫn lỗi hãy chạy lại auth"
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "YouTube quá thời gian / mất kết nối; sẽ thử lại, kiểm tra và chạy lại auth nếu cần"
    return "Không đọc được YouTube / token hỏng hoặc hết hạn; kiểm tra quyền và chạy lại auth --token cho kênh"


class PostLinks:
    def __init__(self, ctx, *, api_factory=None):
        self.ctx = ctx
        self.api_factory = api_factory or youtube.YouTube
        self._lock = threading.RLock()  # serialize add / sync / sync_all and journal writes only
        self.path = Path(ctx.config.workspace.dir) / "_publish/post_links.json"

    def view(self, playlist_id: str) -> dict:
        # Both documents are replaced atomically; page reads must not wait for network I/O.
        doc = self.ctx.playlists.load(playlist_id)
        if doc is None:
            raise FileNotFoundError(playlist_id)
        journal = read_json_dict(self.path) or {}
        return {"playlist_id": playlist_id, "link_playlists": doc.get("link_playlists") or [],
                "last_scan": journal.get(playlist_id), "link_sync_hours": self.ctx.config.post.link_sync_hours}

    def add(self, playlist_id: str, raw: str) -> dict:
        ident = playlist_id_from_url(raw)
        with self._lock:
            self.ctx.playlists.set_link_playlist(playlist_id, ident)
            return self.sync(playlist_id)

    def remove(self, playlist_id: str, ident: str) -> dict:
        self.ctx.playlists.set_link_playlist(playlist_id, ident, remove=True)
        return self.view(playlist_id)

    def _clients(self) -> tuple[list, list[str]]:
        clients, failures = [], []
        paths = [youtube.default_token(), *sorted(youtube.default_token_dir().glob("*.json"))]
        for path in dict.fromkeys(paths):
            try:
                api = self.api_factory(token_path=path, read_only=True)
                clients.append((api.channel_id(), api))
            except Exception as exc:
                # A bad token cannot stop another channel. No exception or path is logged.
                failures.append(_safe_error(exc))
        return clients, failures

    def _videos(self, ident: str, clients: list) -> list:
        owner, failure = None, None
        for _, api in clients:
            try:
                owner = api.playlist_channel(ident)
            except Exception as exc:
                failure = exc
                continue  # private playlist may be visible only to a later token
            for channel_id, candidate in clients:
                if channel_id == owner["id"]:
                    return candidate.playlist_videos(ident)
        if owner:
            # Channel display names are public metadata, never token or transport exception text.
            raise MissingChannel(owner["title"])
        if failure:
            raise failure
        raise MissingChannel(None)

    def _targets(self, doc: dict) -> tuple[list[dict], dict[str, list[str]]]:
        targets, orders = [], {}
        for entry in doc["entries"]:
            vid = entry.get("video_id")
            if not isinstance(vid, str) or not ep.valid_episode_id(vid):
                continue
            for eid in (vid, vid + ".kt"):
                if eid in orders:
                    continue
                manifest = ep.render_manifest(self.ctx.config, eid) or {}
                prefixes = ep.copy_prefixes(self.ctx.config, eid, manifest)
                orders[eid] = [s["clip_id"] for s in manifest.get("shorts", []) if isinstance(s, dict)
                               and isinstance(s.get("clip_id"), str)]
                kt = ep.kind_fields(self.ctx.config, eid)["kind"] == "khaithi"
                for short in manifest.get("shorts", []):
                    if not isinstance(short, dict) or short.get("status") != "rendered":
                        continue
                    cid = short.get("clip_id")
                    code = prefixes.get(cid, "").rstrip("_")
                    if code and links.parse_code(code) == code:
                        targets.append(dict(code=code, episode_id=eid, clip_id=cid, khaithi=kt))
        return targets, orders

    def sync(self, playlist_id: str) -> dict:
        with self._lock:
            doc = self.ctx.playlists.load(playlist_id)
            if doc is None:
                raise FileNotFoundError(playlist_id)
            entries, errors = [], []
            ids = doc.get("link_playlists") or []
            clients, failures = self._clients() if ids else ([], [])
            for ident in ids:
                try:
                    entries.extend(self._videos(ident, clients))
                except MissingChannel as exc:
                    name = f' cho kênh “{exc.channel}”' if exc.channel else " cho kênh chủ playlist (playlist có thể riêng tư)"
                    message = "Cần chạy lại auth --token" + name
                    if not clients and failures:
                        message += ". " + " / ".join(dict.fromkeys(failures))
                    errors.append({"playlist_id": ident, "error": message})
                except Exception as exc:
                    errors.append({"playlist_id": ident, "error": _safe_error(exc)})
            try:
                targets, orders = self._targets(doc)
                # Read again after network I/O, and keep the lock through planning and every write.
                with self.ctx.post_lock:
                    posts = {eid: store.read_posts(self.ctx.posts_path(eid), eid) for eid in orders}
                    current = {(eid, p["clip_id"]): p["link"] for eid, d in posts.items() for p in d["posts"]}
                    result = links.plan(entries, targets, current)
                    changed = set()
                    for update in result["updates"]:
                        eid, cid = update["episode_id"], update["clip_id"]
                        posts[eid] = store.with_fields(posts[eid], orders[eid], cid, {"link": update["link"]}, now=utc_now())
                        changed.add(eid)
                    for eid in sorted(changed):
                        store.write(self.ctx.posts_path(eid), posts[eid])
            except Exception:
                result = links.plan([], [], {})
                errors.append({"error": "Không đọc / ghi được bài đăng; kiểm tra dữ liệu rồi cập nhật lại"})
            rows = [row for row in result["rows"]
                    if row["reason"] in {"no_code", "unmatched", "duplicate", "different", "waiting"}]
            scan = {"scanned_at": utc_now(), "counts": result["counts"], "rows": rows, "errors": errors}
            journal = read_json_dict(self.path) or {}
            journal[playlist_id] = scan
            atomic_write_json(self.path, journal)
            return self.view(playlist_id)

    def sync_all(self) -> None:
        with self._lock:
            for doc in self.ctx.playlists.all():
                if doc.get("link_playlists"):
                    try:
                        self.sync(doc["playlist_id"])
                    except Exception:
                        log.warning("web: không lưu được kết quả quét link bài đăng; sẽ thử lại")


class MissingChannel(Exception):
    def __init__(self, channel):
        self.channel = channel
