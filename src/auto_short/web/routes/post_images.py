"""Post images routes extracted from the app factory."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ...post import images as post_images, imgsearch as post_imgsearch, redistribute as post_redistribute
from ...review import content_disposition
from ..context import WebContext
from ..jobs import (
    KIND_IMAGE_SEARCH,
    KIND_POST,
    KIND_POST_SEARCH,
    POST_IMAGES_KEY,
    image_search_target,
    keyword_search_target,
)

log = logging.getLogger("auto_short")


class PostImageSearchIn(BaseModel):
    url: str = Field(max_length=2000)


class PostImageFindIn(BaseModel):
    keyword: str = Field(max_length=200)


class PostImageAddIn(BaseModel):
    search_id: str = Field(max_length=40)
    ids: list[str] = Field(max_length=200)


class PostImageRedistributeIn(BaseModel):
    confirm: bool = False


def build(ctx: WebContext) -> APIRouter:
    router = APIRouter()

    def _post_image_sources() -> dict[str, str]:
        try:
            lines = (ctx.config.post.image_dir / "sources.tsv").read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        out = {}
        for line in lines:
            name, _, url = line.partition("\t")
            if name and url:
                out[name] = url
        return out

    @router.get("/api/post-images")
    def api_post_images():
        infos = post_images.list_images(ctx.config.post.image_dir)
        used = post_images.usage_counts(Path(ctx.config.workspace.dir))
        sources = _post_image_sources()
        return {"images": [{"name": i.name, "width": i.width, "height": i.height, "bytes": i.bytes,
                            "used": used.get(i.name, 0), "source": sources.get(i.name)} for i in infos],
                "image_sources": list(ctx.config.post.image_sources),
                "search": post_imgsearch.search_status(ctx.config)}

    @router.post("/api/post-images")
    async def api_post_images_upload(request: Request, name: str = ""):
        """P5a: raw body (``Content-Type: image/jpeg`` | ``image/png``), original name in ``?name=``."""
        if not name.strip():
            return JSONResponse({"detail": "cần tên ảnh gốc (?name=...)"}, status_code=422)
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > post_images.MAX_BYTES:
            return JSONResponse({"detail": f"ảnh lớn hơn {post_images.MAX_BYTES // (1024 * 1024)} MB"},
                                status_code=422)
        body = await request.body()
        if len(body) > post_images.MAX_BYTES:
            return JSONResponse({"detail": f"ảnh lớn hơn {post_images.MAX_BYTES // (1024 * 1024)} MB"},
                                status_code=422)
        try:
            img_name, duplicate = post_images.save_image(ctx.config.post.image_dir, body, original_name=name)
        except post_images.ImageError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        log.info("web: post-images: %s \"%s\" (%d bytes)%s", "upload" if not duplicate else "upload (trùng)",
                 img_name, len(body), "" if not duplicate else ", ảnh có sẵn")
        return JSONResponse({"image": img_name, "duplicate": duplicate}, status_code=200)

    @router.delete("/api/post-images/{name}")
    def api_post_images_delete(name: str):
        path = post_images.resolve(ctx.config.post.image_dir, name)
        if path is None:
            return JSONResponse({"detail": "không có ảnh này"}, status_code=404)
        used = post_images.usage_counts(Path(ctx.config.workspace.dir)).get(name, 0)
        post_images.delete_image(ctx.config.post.image_dir, name)
        log.info("web: post-images: xóa %s (đang dùng ở %d bài)", name, used)
        return {"used": used}

    @router.post("/api/post-images/search")
    def api_post_images_search(body: PostImageSearchIn):
        """P5b: tìm ảnh từ một link -> job nền (lane prepare, không cần Ollama); 409 khi đang tìm."""
        with ctx.submit_lock:
            current = ctx.runner.latest(POST_IMAGES_KEY)
            if current is not None and current.active:
                return JSONResponse({"detail": "đang tìm ảnh; đợi xong rồi tìm tiếp",
                                     "job": ctx.job_view(current)}, status_code=409)
            job, _created = ctx.runner.submit(POST_IMAGES_KEY, KIND_POST_SEARCH,
                                          image_search_target(ctx.config, body.url, search=ctx.post_search))
        log.info("web: post-images: tìm ảnh %s -> job %s", body.url, job.id)
        return JSONResponse({"job": ctx.job_view(job)}, status_code=202)

    @router.get("/api/post-images/search/{job_id}")
    def api_post_images_search_status(job_id: str):
        job = ctx.runner.job(job_id)
        if job is None or job.episode_id != POST_IMAGES_KEY:
            return JSONResponse({"detail": "không có job này"}, status_code=404)
        result = getattr(job.target, "result", None)
        found = len(result.added) + len(result.duplicate) if result is not None else 0
        return {"status": job.status, "found": found, "added": list(result.added) if result else [],
                "duplicate": list(result.duplicate) if result else [],
                "skipped": dict(result.skipped) if result else {}}

    @router.post("/api/post-images/find")
    def api_post_images_find(body: PostImageFindIn):
        """CP8.30 P5c: tìm ảnh theo từ khóa -> job nền (lane prepare); kết quả là ứng viên, chưa vào thư viện."""
        if not post_imgsearch.tokens(body.keyword):
            return JSONResponse({"detail": "nhập từ khóa"}, status_code=422)
        with ctx.submit_lock:
            current = ctx.runner.latest(POST_IMAGES_KEY)
            if current is not None and current.active:
                return JSONResponse({"detail": "đang tìm ảnh; đợi xong rồi tìm tiếp", "job": ctx.job_view(current)},
                                    status_code=409)
            job, _created = ctx.runner.submit(POST_IMAGES_KEY, KIND_IMAGE_SEARCH,
                                          keyword_search_target(ctx.config, body.keyword.strip(), search=ctx.keyword_search))
        log.info("web: post-images: tìm theo từ khóa \"%s\" -> job %s", body.keyword.strip(), job.id)
        return JSONResponse({"job": ctx.job_view(job)}, status_code=202)

    @router.get("/api/post-images/find/{job_id}")
    def api_post_images_find_status(job_id: str):
        job = ctx.runner.job(job_id)
        if job is None or job.episode_id != POST_IMAGES_KEY or job.kind != KIND_IMAGE_SEARCH:
            return JSONResponse({"detail": "không có job này"}, status_code=404)
        result = getattr(job.target, "result", None)
        out = {"status": job.status, "progress": job.stage, "error": job.error if job.status == "failed" else None}
        if result is not None:
            out.update({"search_id": result.search_id, "keyword": result.keyword, "skipped": dict(result.skipped),
                        "notes": list(result.notes), "sources": dict(result.sources),
                        "candidates": [{k: c.get(k) for k in ("id", "width", "height", "bytes", "origin", "page", "url",
                                                              "flag", "thumb")} for c in result.candidates]})
        return out

    @router.get("/files/post-image-candidates/{search_id}/{cand_id}")
    def post_image_candidate_file(search_id: str, cand_id: str, thumb: str | None = None):
        path = post_imgsearch.candidate_file(ctx.config.post.image_dir, search_id, cand_id, thumb=thumb is not None)
        if path is None:
            return JSONResponse({"detail": "không có ảnh này"}, status_code=404)
        ctype = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return FileResponse(path, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})

    @router.post("/api/post-images/candidates/add")
    def api_post_images_candidates_add(body: PostImageAddIn):
        """CP8.30 P5c: thêm các ứng viên đã chọn vào thư viện (tên tiếp số, ghi sources.tsv); bấm lại không thêm trùng."""
        if not post_imgsearch.SEARCH_ID_RE.match(body.search_id):
            return JSONResponse({"detail": "không có lượt tìm này"}, status_code=404)
        ids = [i for i in dict.fromkeys(body.ids) if post_imgsearch.CAND_ID_RE.match(i)]
        if not ids:
            return JSONResponse({"detail": "chưa chọn ảnh nào"}, status_code=422)
        try:
            res = post_imgsearch.add_candidates(ctx.config.post.image_dir, body.search_id, ids)
        except post_images.ImageError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        log.info("web: post-images: thêm %d ứng viên (%d đã có, %d không còn)", len(res["added"]),
                 len(res["duplicate"]), len(res["missing"]))
        return res

    def _redistribute_view(plan: "post_redistribute.Plan") -> dict:
        return {"changes": plan.changed, "episodes": len(plan.changes), "unposted": plan.unposted,
                "posted": plan.posted, "spread": plan.spread(), "skipped_broken": list(plan.skipped_broken)}

    @router.post("/api/post-images/redistribute")
    def api_post_images_redistribute(body: PostImageRedistributeIn):
        """CP8.30 P5d: chia lại ảnh cho bài chưa đăng. ``confirm=false`` chỉ xem trước (số bài sẽ đổi);
        ``confirm=true`` ghi (sao lưu posts.json trước). 409 khi đang có job soạn bài."""
        library = [i.name for i in post_images.list_images(ctx.config.post.image_dir)]
        if not library:
            return JSONResponse({"detail": "thư viện chưa có ảnh"}, status_code=422)
        work = Path(ctx.config.workspace.dir)
        if body.confirm and any(j.kind == KIND_POST and j.active for j in ctx.runner.jobs()):
            return JSONResponse({"detail": "đang soạn bài; đợi xong rồi chia lại ảnh"}, status_code=409)
        with ctx.post_lock:
            plan = post_redistribute.plan(work, library)
            if not body.confirm:
                return {**_redistribute_view(plan), "applied": False}
            backup = post_redistribute.apply(work, plan, now=datetime.now())
        log.info("web: post-images: chia lại ảnh: %d bài / %d tập đổi ảnh (sao lưu %s)", plan.changed,
                 len(plan.changes), backup.name if backup else "-")
        return {**_redistribute_view(plan), "applied": True, "backup": backup.name if backup else None}

    @router.get("/files/post-images/{name}")
    def post_image_file(name: str, download: str | None = None):
        path = post_images.resolve(ctx.config.post.image_dir, name)
        if path is None:
            return JSONResponse({"detail": "không có ảnh này"}, status_code=404)
        headers = {"Cache-Control": "private, no-cache"}
        if download is not None:
            headers["Content-Disposition"] = content_disposition(name)
        return FileResponse(path, media_type=post_images.CONTENT_TYPES[Path(name).suffix.lower()], headers=headers)

    return router
