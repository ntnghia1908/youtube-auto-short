"""IMG1 HTTP integration; run outside the Codex sandbox (TestClient needs loopback)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.packaging import cover_suggest
from auto_short.post import imggen
from auto_short.web.episode_thumbs import EpisodeThumbs
from test_imggen_img1 import fake_codex, gen_cfg  # shared fixture + PNG runner
from web_helpers import login, make_app


@pytest.fixture(autouse=True)
def codex_available(monkeypatch):
    monkeypatch.setattr(cover_suggest, "available", lambda config: None)


def test_generate_serve_pick_and_latest_without_queue(gen_cfg):
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        for method, path in (("get", "/api/post-images/generate/latest"),
                             ("post", "/api/post-images/generate"),
                             ("get", "/api/post-images/generate/bad"),
                             ("post", "/api/post-images/generate/bad/cancel"),
                             ("post", "/api/post-images/generate/bad/dismiss")):
            assert getattr(c, method)(path).status_code in (302, 303, 401)
        login(c)
        assert c.get("/api/post-images").json()["generate"] == {
            "unavailable": None, "styles": [{"id": s["id"], "label": s["label"]} for s in imggen.STYLES]}
        assert c.get("/api/post-images/generate/latest").json() == {"run": None}
        r = c.post("/api/post-images/generate", json={"keyword": "hoa sen Tịnh Không"})
        assert r.status_code == 202, r.text
        ident = r.json()["run"]["search_id"]
        app.state.post_image_gen.thread.join(15)
        run = c.get(f"/api/post-images/generate/{ident}").json()["run"]
        assert set(run) == {"search_id", "keyword", "status", "error", "tokens", "candidates", "skipped", "notes", "sources", "style", "styles", "extra"}
        assert run["status"] == "done" and len(run["candidates"]) == 10
        assert run["style"] == "random" and run["extra"] == ""
        assert len(set(run["styles"])) == 10
        assert not app.state.runner.jobs()  # separate thread, no prepare job
        assert c.get("/api/post-images").json()["images"] == []
        for n, cand in enumerate(run["candidates"]):
            assert set(cand) == {"id", "width", "height", "bytes", "origin", "page", "url", "flag", "thumb", "style", "style_label"}
            assert cand["origin"] == "codex"
            assert cand["style"] == run["styles"][n]
            assert cand["style_label"] == imggen.STYLE_BY_ID[cand["style"]]["label"]
            path = f"/files/post-image-candidates/{ident}/{cand['id']}"
            assert c.get(path).headers["content-type"] == "image/png"
            assert c.get(path + "?thumb=1").headers["content-type"] == "image/jpeg"
        for name in ("prompt.md", "codex.log", "state.json", "meta.json"):
            assert c.get(f"/files/post-image-candidates/{ident}/{name}").status_code == 404
        ids = [cand["id"] for cand in run["candidates"]]
        picked = c.post("/api/post-images/candidates/add", json={"search_id": ident, "ids": ids[:2]})
        assert picked.status_code == 200 and picked.json()["added"] == ["01.png", "02.png"]
        library = c.get("/api/post-images").json()["images"]
        assert len(library) == 2 and library[0]["source"] == "codex-ai:hoa%20sen%20T%E1%BB%8Bnh%20Kh%C3%B4ng"
        assert len(c.get("/api/post-images/generate/latest").json()["run"]["candidates"]) == 8
        c.post("/api/post-images/candidates/add", json={"search_id": ident, "ids": ids[2:]})
        assert c.get("/api/post-images/generate/latest").json() == {"run": None}


def test_empty_unavailable_and_shared_cover_lock(gen_cfg, monkeypatch):
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        for keyword in ("", " \n ", "!", "x" * 201):
            assert c.post("/api/post-images/generate", json={"keyword": keyword}).status_code == 422
        monkeypatch.setattr(cover_suggest, "available", lambda config: "gợi ý Codex đang tắt trong cấu hình")
        r = c.post("/api/post-images/generate", json={"keyword": "sen"})
        assert r.status_code == 503 and "đang tắt" in r.json()["detail"]
        assert c.get("/api/post-images").json()["generate"]["unavailable"] == r.json()["detail"]
        monkeypatch.setattr(cover_suggest, "available", lambda config: None)
        with EpisodeThumbs.codex_lock:
            assert c.post("/api/post-images/generate", json={"keyword": "sen"}).status_code == 409
        assert not app.state.runner.jobs()


def test_cancel_running_latest_and_lock_release(gen_cfg):
    entered = threading.Event()

    def blocking(cmd, **kw):
        entered.set()
        assert kw["cancel"].wait(10)
        raise cover_suggest.Cancelled("đã hủy")

    app = make_app(gen_cfg, codex_runner=blocking)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        run = c.post("/api/post-images/generate", json={"keyword": "chùa"}).json()["run"]
        ident = run["search_id"]
        try:
            assert entered.wait(5)
            assert c.get("/api/post-images/generate/latest").json()["run"]["status"] == "running"
            rejected = c.post(f"/api/post-images/generate/{ident}/dismiss")
            assert rejected.status_code == 409 and rejected.json()["detail"] == "lượt đang chạy"
            assert not imggen.state(gen_cfg, ident).get("dismissed")
            assert c.post("/api/post-images/generate", json={"keyword": "sen"}).status_code == 409
            assert c.post(f"/api/post-images/generate/{ident}/cancel").status_code == 200
        finally:
            app.state.post_image_gen.cancel_event.set()
            app.state.post_image_gen.thread.join(10)
        assert c.get(f"/api/post-images/generate/{ident}").json()["run"]["status"] == "cancelled"
        assert EpisodeThumbs.codex_lock.acquire(blocking=False)
        EpisodeThumbs.codex_lock.release()


def test_restart_and_unsafe_ids(gen_cfg):
    doc = imggen.create(gen_cfg, "sen")
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        run = c.get("/api/post-images/generate/latest").json()["run"]
        assert run["search_id"] == doc["search_id"]
        assert run["status"] == "failed" and run["error"] == "máy chủ khởi động lại"
        for ident in ("bad", "..%2Fx", "20260101000000-abcdef", "20260101000000-abcdef%0A"):
            assert c.get(f"/api/post-images/generate/{ident}").status_code == 404
            assert c.post(f"/api/post-images/generate/{ident}/cancel").status_code == 404
            assert c.post(f"/api/post-images/generate/{ident}/dismiss").status_code == 404


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_dismiss_http_hides_latest_preserves_files_and_does_not_fall_back(gen_cfg, status):
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        older = imggen.create(gen_cfg, "sen")
        older["status"] = "failed"
        imggen.save(imggen.directory(gen_cfg, older["search_id"]), older)
        r = c.post("/api/post-images/generate", json={"keyword": "chùa"})
        assert r.status_code == 202, r.text
        ident = r.json()["run"]["search_id"]
        app.state.post_image_gen.thread.join(15)
        doc = imggen.state(gen_cfg, ident)
        assert doc["status"] == "done", doc["error"]
        candidate = doc["candidates"][0]["id"]
        doc["status"] = status
        imggen.save(imggen.directory(gen_cfg, ident), doc)
        assert c.get("/api/post-images/generate/latest").json()["run"]["search_id"] == ident
        dismissed = c.post(f"/api/post-images/generate/{ident}/dismiss")
        assert dismissed.status_code == 200 and dismissed.json()["run"]["status"] == status
        assert imggen.state(gen_cfg, ident)["dismissed"] is True
        assert c.get("/api/post-images/generate/latest").json() == {"run": None}
        assert c.get(f"/files/post-image-candidates/{ident}/{candidate}").status_code == 200
        assert c.get("/api/post-images").json()["images"] == []
        assert c.post(f"/api/post-images/generate/{ident}/dismiss").status_code == 200


@pytest.mark.parametrize("style,extra,error", [
    ("thuy-mac", "sắc mực nhẹ", None), ("tinh-do", "", None),
    ("unknown", "", "phong cách"), ("random", "x" * 201, "200 ký tự"),
    ("random", "màu\nnhạt", "ký tự điều khiển"),
])
def test_generate_style_extra_validation_and_view(gen_cfg, style, extra, error):
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        r = c.post("/api/post-images/generate", json={"keyword": "hoa sen", "style": style, "extra": extra})
        if error:
            assert r.status_code == 422 and error in r.json()["detail"]
            assert imggen.latest(gen_cfg) is None
            return
        assert r.status_code == 202, r.text
        app.state.post_image_gen.thread.join(15)
        run = c.get(f"/api/post-images/generate/{r.json()['run']['search_id']}").json()["run"]
        assert run["status"] == "done", run["error"]
        assert run["style"] == style and run["extra"] == extra
        assert run["styles"] == [style] * 10
        assert all(cand["style_label"] == imggen.STYLE_BY_ID[style]["label"] for cand in run["candidates"])


def test_shared_image_ui_style_controls_submission_and_labels():
    # Both the library page and the post picker use this markup and request handler.
    static = Path(__file__).parents[1] / "src/auto_short/web/static"
    js = (static / "app.js").read_text()
    assert '<label for="image-generate-style">Phong cách</label>' in js
    assert '<option value="random">Trộn ngẫu nhiên</option>' in js
    assert '<label for="image-generate-extra">Mô tả thêm</label>' in js
    assert 'id="image-generate-extra" type="text" maxlength="200"' in js
    assert '...(d.generate?.styles || []).map' in js
    assert 'keyword, style: $("#image-generate-style").value, extra: $("#image-generate-extra").value' in js
    assert 'text: c.style_label' in js


@pytest.mark.parametrize("payload,error", [
    ({"keyword": "sen"}, None),
    ({"keyword": "sen", "style": "thuy-mac", "extra": "mực nhạt"}, None),
    ({"keyword": "sen", "style": "unknown"}, "phong cách"),
    ({"keyword": "sen", "extra": "x" * 201}, "200 ký tự"),
    ({"keyword": "sen", "extra": "mực\t nhạt"}, "ký tự điều khiển"),
])
def test_generate_route_parameters_without_http_transport(gen_cfg, payload, error):
    # Exercise the real endpoints/service without TestClient's blocked sandbox transport.
    from auto_short.web.post_image_gen import PostImageGen
    from auto_short.web.routes.post_images import build, PostImageGenerateIn

    service = PostImageGen(gen_cfg, codex_runner=fake_codex)
    routes = build(SimpleNamespace(config=gen_cfg, post_image_gen=service)).routes
    generate = next(r.endpoint for r in routes if r.path == "/api/post-images/generate" and "POST" in r.methods)
    listing = next(r.endpoint for r in routes if r.path == "/api/post-images" and "GET" in r.methods)
    assert listing()["generate"] == {
        "unavailable": None, "styles": [{"id": s["id"], "label": s["label"]} for s in imggen.STYLES]}
    response = generate(PostImageGenerateIn(**payload))
    data = json.loads(response.body)
    if error:
        assert response.status_code == 422 and error in data["detail"]
        assert service.latest() is None
        assert EpisodeThumbs.codex_lock.acquire(blocking=False)
        EpisodeThumbs.codex_lock.release()
        return
    assert response.status_code == 202
    service.thread.join(15)
    assert not service.thread.is_alive()
    run = service.get(data["run"]["search_id"])
    assert run["status"] == "done", run["error"]
    assert run["style"] == payload.get("style", "random") and run["extra"] == payload.get("extra", "")
    assert len(run["styles"]) == len(run["candidates"]) == 10
    for n, candidate in enumerate(run["candidates"]):
        assert candidate["style"] == run["styles"][n]
        assert candidate["style_label"] == imggen.STYLE_BY_ID[candidate["style"]]["label"]
