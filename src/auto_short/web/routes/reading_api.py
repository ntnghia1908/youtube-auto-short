"""Reading api routes extracted from the app factory."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi import Query
from fastapi.responses import JSONResponse

from ... import khaithi
from ...titling.playlist import stored_series as playlist_series
from ...workspace import iter_manifests
from .. import reading
from ..context import WebContext, RANGE_SIZE


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _post_count(video_id: str) -> int:
        """Posts (still rendered) of a Short episode and of its khai thị episode."""
        return ctx.post_stats(video_id)[0] + ctx.post_stats(video_id + khaithi.SUFFIX)[0]

    def _single_episodes() -> list[str]:
        """Short episodes of no bộ kinh that hold at least one post, by creation date (first stage start), newest first."""
        in_playlists = ctx.playlists.video_ids()
        found: list[tuple[str, str]] = []
        for ws, manifest in iter_manifests(Path(ctx.config.workspace.dir)):
            eid = ws.episode_id
            if eid in in_playlists or eid.endswith(khaithi.SUFFIX) or _post_count(eid) <= 0:
                continue
            starts = [st.get("started_at") for st in (manifest.get("stages") or {}).values()
                      if isinstance(st, dict) and isinstance(st.get("started_at"), str)]
            try:
                stamp = min(starts) if starts else datetime.fromtimestamp(ws.manifest_path.stat().st_mtime,
                                                                          timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                stamp = ""
            found.append((stamp, eid))
        found.sort(reverse=True)
        return [eid for _, eid in found]

    @router.get("/api/reading/khaithi")
    def api_reading_khaithi():
        """K2: bộ kinh with at least one post -> ranges of 10 episodes + posts; then "Video lẻ" (``_single``)."""
        out = []
        for doc in ctx.playlists.all():
            entries = [e for e in doc["entries"] if e.get("video_id") and e.get("available")]
            counts = [(int(e["episode"]) if ctx.is_numbered(e) else None, _post_count(e["video_id"])) for e in entries]
            ranges, other = reading.ranges_of(counts, RANGE_SIZE)
            if ranges or other:
                out.append({"playlist_id": doc["playlist_id"],
                            "title": playlist_series(doc) or doc.get("title") or doc["playlist_id"],
                            "ranges": ranges, "other": other})
        out.sort(key=lambda b: reading.sort_key(b["title"]))
        singles = _single_episodes()
        if singles:
            out.append({"playlist_id": reading.SINGLE_ID, "title": reading.SINGLE_TITLE,
                        "ranges": reading.single_ranges(len(singles), RANGE_SIZE, [_post_count(e) for e in singles]),
                        "other": None})
        return out

    @router.get("/api/reading/khaithi/{playlist_id}")
    def api_reading_khaithi_book(playlist_id: str, range_from: int | None = Query(None, alias="from", ge=0),
                                 range_to: int | None = Query(None, alias="to", ge=0), other: str | None = None):
        """K2: one "book" (S3 + ``episode_id, clip_id, copy_text, posted, stale`` per section); episodes and posts in
        the order of the ``.docx`` export; 404 unknown bộ / no post; 422 bad range (at most ``RANGE_SIZE`` episodes)."""
        single = playlist_id == reading.SINGLE_ID
        doc = None if single else ctx.playlist_or_404(playlist_id)
        if doc is None and not single:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        if single:
            if other is not None:
                if other != "1" or range_from is not None or range_to is not None:
                    return JSONResponse({"detail": "dùng other=1 một mình hoặc from + to"}, status_code=422)
                return JSONResponse({"detail": "Video lẻ không có nhóm chưa rõ số"}, status_code=404)
            if range_from is None or range_to is None or range_to < range_from or range_to - range_from >= RANGE_SIZE:
                return JSONResponse({"detail": f"cần from, to (to ≥ from, tối đa {RANGE_SIZE} tập)"}, status_code=422)
            singles = _single_episodes()
            chosen_ids = [e for pos, e in enumerate(singles, 1) if range_from <= pos <= range_to]
            title, span = reading.SINGLE_TITLE, reading.range_label(range_from, range_to)
        else:
            picked = ctx.pick_range(doc, range_from, range_to, other, error_response=JSONResponse)
            if isinstance(picked, JSONResponse):
                return picked
            chosen, _ = picked
            chosen_ids = [e["video_id"] for e in chosen]
            title = playlist_series(doc) or doc.get("title") or playlist_id
            span = reading.range_label(range_from, range_to) if other is None else "Tập chưa rõ số"
        episodes = [(d[0], [i for _, items in d[1] for i in items]) for vid in chosen_ids
                    if (d := ctx.export_data(vid, views=True)) is not None]
        if not episodes:
            return JSONResponse({"detail": "chưa có bài đăng nào"}, status_code=404)
        return reading.book(f"{title} · {span}", episodes)

    return router
