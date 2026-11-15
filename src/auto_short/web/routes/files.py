"""Files routes extracted from the app factory."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter
from fastapi import Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from ...compilation import CID_RE as CID_RE
from ...compilation import Item
from ...compilation import store as comp_store
from ...compilation.meta import timecode
from ...post import export as post_export
from ...review import content_disposition
from ...review.names import download_name, favorites_zip_name, posts_docx_name
from ...titling.playlist import stored_series as playlist_series
from .. import episodes as ep
from ..context import WebContext
from ..compilations import MAX_BODY_ITEMS
from ..urls import valid_playlist_id

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _export_episode(video_id: str) -> post_export.ExportEpisode | None:
        """Heading + groups "Shorts" then "Khai thị" of ``video_id`` (a Short episode); None when it has no post."""
        data = ctx.export_data(video_id)
        if data is None:
            return None
        heading, groups = data
        return post_export.ExportEpisode(heading=heading, groups=[
            post_export.ExportGroup(name=n, posts=[post_export.ExportPost(title=i["head"], paragraphs=i["paras"],
                                                                         source=i["source"], image=i["image"])
                                                   for i in items]) for n, items in groups])

    def _images_flag(images: str) -> bool | None:
        return {"1": True, "0": False}.get(images)

    def _docx_response(title: str, episodes: list[post_export.ExportEpisode], name: str,
                       images: bool = True) -> FileResponse:
        fd, tmp = tempfile.mkstemp(prefix="posts-", suffix=".docx")
        os.close(fd)
        try:
            post_export.build_docx(Path(tmp), title, episodes, ctx.config.post.image_dir, images=images)
        except BaseException:
            os.unlink(tmp)
            raise
        return FileResponse(tmp, media_type=DOCX_TYPE, background=BackgroundTask(os.unlink, tmp),
                            headers={"Content-Disposition": content_disposition(name), "Cache-Control": "no-store"})

    @router.get("/files/{episode_id}/posts.docx")
    def posts_docx(episode_id: str, images: str = "1"):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        if (with_images := _images_flag(images)) is None:
            return JSONResponse({"detail": "images phải là 0 hoặc 1"}, status_code=422)
        video_id = ep.hd_owner(episode_id)
        episode = _export_episode(video_id)
        if episode is None:
            return JSONResponse({"detail": "chưa có bài đăng nào"}, status_code=404)
        return _docx_response(episode.heading, [episode], ctx.docx_name_of(video_id, with_images), with_images)

    @router.get("/files/playlists/{playlist_id}/posts.docx")
    def playlist_posts_docx(playlist_id: str, range_from: int | None = Query(None, alias="from", ge=0),
                            range_to: int | None = Query(None, alias="to", ge=0), other: str | None = None,
                            images: str = "1"):
        """CP8.31 A1: posts of at most ``RANGE_SIZE`` episodes by episode number (``from``..``to``), or the
        unnumbered ones (``other=1``); no whole-bộ file."""
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        if (with_images := _images_flag(images)) is None:
            return JSONResponse({"detail": "images phải là 0 hoặc 1"}, status_code=422)
        picked = ctx.pick_range(doc, range_from, range_to, other, error_response=JSONResponse)
        if isinstance(picked, JSONResponse):
            return picked
        chosen, span = picked
        episodes = [x for e in chosen if (x := _export_episode(e["video_id"])) is not None]
        if not episodes:
            return JSONResponse({"detail": "chưa có bài đăng nào"}, status_code=404)
        return _docx_response(playlist_series(doc) or doc.get("title") or playlist_id, episodes,
                              posts_docx_name(None, series=ctx.playlist_docx_series(doc), fallback=playlist_id,
                                              span=span, images=with_images), with_images)

    @router.get("/files/playlists/{playlist_id}/favorites.zip")
    def favorites_zip(playlist_id: str, items: str = "", filter: str = "", part: str = ""):
        doc = ctx.playlist_or_404(playlist_id)
        if doc is None:
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        if filter not in {"both", "short", "khaithi"} or not re.fullmatch(r"[1-9][0-9]*", part):
            return JSONResponse({"detail": "filter hoặc part không hợp lệ"}, status_code=400)
        try:
            part_number = int(part)
        except ValueError:
            return JSONResponse({"detail": "part không hợp lệ"}, status_code=400)
        raw = items.split(",")
        if not items or len(raw) > MAX_BODY_ITEMS:
            return JSONResponse({"detail": "items rỗng hoặc quá nhiều mục"}, status_code=400)
        by_item = ctx.compilations._lookup(doc)
        favorites = set(ctx.compilations.favorites(playlist_id))
        picked, seen = [], set()
        for value in raw:
            pair = value.split("/")
            if len(pair) != 2 or not ep.valid_episode_id(pair[0]) or not ep.valid_clip_id(pair[1]):
                return JSONResponse({"detail": "item không hợp lệ"}, status_code=400)
            item = Item(*pair)
            clip = by_item.get(item)
            if item in seen or item not in favorites or clip is None or (filter != "both" and clip.kind != filter):
                return JSONResponse({"detail": "item bị trùng, không còn yêu thích hoặc không dùng được"}, status_code=400)
            seen.add(item)
            picked.append(clip)
        series = ctx.compilations.series_of(doc)
        duration = timecode(sum(c.manifest_duration for c in picked)) \
            if all(c.manifest_duration is not None for c in picked) else "không rõ"
        kind = {"both": "Short + Khai thị", "short": "Short", "khaithi": "Khai thị"}[filter]
        heading = " ".join((series or doc.get("title") or playlist_id).split())
        lines = [f"{heading} — Phần {part_number} — {kind} — Tổng thời lượng: {duration}"]
        entries = []
        for n, clip in enumerate(picked, 1):
            name = download_name(clip.label, clip.number, clip.total, clip.title, khaithi=clip.kind == "khaithi")
            entries.append((clip.item.clip, clip.path, f"{n:02d}_{name}"))
            title = " ".join((clip.title or "").split())
            lines.append(f"{n:02d}. {clip.code} — {title}")
        entries.append(("list", ("\n".join(lines) + "\n").encode("utf-8"), "danh-sach.txt"))
        from .files_catchall import zip_body

        body = zip_body(ctx, entries)
        if isinstance(body, Response):
            return body
        return StreamingResponse(body, media_type="application/zip", headers={
            "Content-Disposition": content_disposition(favorites_zip_name(part_number, filter=filter, series=series)),
            "Cache-Control": "no-store"})

    @router.get("/files/playlists/{playlist_id}/compilations/{name}")
    def compilation_file(playlist_id: str, name: str):
        cid = name[:-4] if name.endswith(".mp4") else ""
        if not valid_playlist_id(playlist_id) or not CID_RE.match(cid):
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        path = ctx.compilations.video_file(playlist_id, cid)
        stored = comp_store.read_doc(ctx.compilations.folder(playlist_id), cid)
        if path is None or stored is None:
            return JSONResponse({"detail": "không có file này"}, status_code=404)
        return FileResponse(path, media_type="video/mp4", headers={
            "Content-Disposition": content_disposition(stored.get("download_name") or f"{cid}.mp4"),
            "Cache-Control": "private, no-cache"})

    return router
