"""Pages routes extracted from the app factory."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from .. import episodes as ep
from .. import reading
from ..context import WebContext
from ..urls import valid_playlist_id


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def index():
        return FileResponse(ctx.static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @router.get("/episodes/{episode_id}")
    async def episode_page(episode_id: str):
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return FileResponse(ctx.static_dir / "episode.html", headers={"Cache-Control": "no-cache"})

    @router.get("/episodes/{episode_id}/posts")
    async def episode_posts_page(episode_id: str):
        """CP8.16 R1: tab "Bài đăng" of a video (same HTML for the Short episode and its khai thị episode)."""
        if not ep.valid_episode_id(episode_id):
            return JSONResponse({"detail": "không có episode này"}, status_code=404)
        return FileResponse(ctx.static_dir / "posts.html", headers={"Cache-Control": "no-cache"})

    @router.get("/playlists/{playlist_id}")
    async def playlist_page(playlist_id: str):
        if not valid_playlist_id(playlist_id):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return FileResponse(ctx.static_dir / "playlist.html", headers={"Cache-Control": "no-cache"})

    @router.get("/sutras/khaithi/{playlist_id}")
    async def khaithi_reader_page(playlist_id: str):
        if playlist_id != reading.SINGLE_ID and (not valid_playlist_id(playlist_id) or ctx.playlist_or_404(playlist_id) is None):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return FileResponse(ctx.static_dir / "sutra.html", headers={"Cache-Control": "no-cache"})

    @router.get("/storage")
    async def storage_page():
        return FileResponse(ctx.static_dir / "storage.html", headers={"Cache-Control": "no-cache"})

    @router.get("/monitor")
    async def monitor_page():
        return FileResponse(ctx.static_dir / "monitor.html", headers={"Cache-Control": "no-cache"})

    @router.get("/playlists/{playlist_id}/favorites")
    async def favorites_page(playlist_id: str):
        if not valid_playlist_id(playlist_id):
            return JSONResponse({"detail": "không có bộ kinh này"}, status_code=404)
        return FileResponse(ctx.static_dir / "favorites.html", headers={"Cache-Control": "no-cache"})

    return router
