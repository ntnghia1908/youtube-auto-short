"""SR1.1: Đọc Kinh routes (S6 read / count part), auth, topnav link, static assets."""

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.sutra.store import SutraStore  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
TEXT = "= Kinh Thử\n@ Chính kinh\n# Phẩm một\nDòng a[^1]\n[^1]: chú\n"
STATIC = Path(app_mod.STATIC_DIR)


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))


@pytest.fixture
def c(tcfg):
    app = app_mod.create_app(tcfg, PW, preflight=lambda cfg: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def lc(c):
    assert c.post("/login", data={"password": PW}).status_code == 303
    return c


@pytest.fixture
def store(tcfg):
    return SutraStore(Path(tcfg.workspace.dir) / "_sutras")


def test_requires_login(c, store):
    slug = store.create(TEXT)
    for url in ("/api/sutras", f"/api/sutras/{slug}", f"/api/sutras/{slug}/text"):
        assert c.get(url).status_code == 401
    assert c.post(f"/api/sutras/{slug}/recitations").status_code == 401
    assert c.delete(f"/api/sutras/{slug}/recitations/last").status_code == 401
    for url in ("/sutras", f"/sutras/{slug}"):
        r = c.get(url)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    assert store.get(slug)["recitations"]["total"] == 0


def test_library_and_pages(lc, store):
    assert lc.get("/api/sutras").json() == []
    slug = store.create(TEXT)
    rows = lc.get("/api/sutras").json()
    assert rows[0]["slug"] == slug and rows[0]["sections"] == 1 and rows[0]["recitations"]["total"] == 0
    assert lc.get("/api/sutras").headers["cache-control"] == "no-store"
    r = lc.get("/sutras")
    assert r.status_code == 200 and "sutra.js" in r.text and r.headers["cache-control"] == "no-cache"
    r = lc.get(f"/sutras/{slug}")
    assert r.status_code == 200 and 'data-page="reader"' in r.text
    assert lc.get("/sutras/khong-co").status_code == 404
    assert lc.get("/sutras/..%2Fx").status_code == 404
    assert lc.get("/sutras/Bad_Slug").status_code == 404


def test_detail_and_text(lc, store):
    slug = store.create(TEXT)
    d = lc.get(f"/api/sutras/{slug}").json()
    assert d["title"] == "Kinh Thử" and d["slug"] == slug and d["groups"][0]["sections"][0]["notes"] == {"1": "chú"}
    t = lc.get(f"/api/sutras/{slug}/text").json()
    assert t["text"] == TEXT and t["sha256"] == d["sha256"]
    for url in ("/api/sutras/nope", "/api/sutras/nope/text"):
        r = lc.get(url)
        assert r.status_code == 404 and "detail" in r.json()


def test_corrupt_text_is_422(lc, store):
    slug = store.create(TEXT)
    (store.root / slug / "sutra.txt").write_text("hỏng", encoding="utf-8")
    r = lc.get(f"/api/sutras/{slug}")
    assert r.status_code == 422 and r.json()["detail"]


def test_recitations_flow(lc, store):
    slug = store.create(TEXT)
    r = lc.delete(f"/api/sutras/{slug}/recitations/last")
    assert r.status_code == 409 and r.json()["detail"]
    r = lc.post(f"/api/sutras/{slug}/recitations")
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["entry"]["at"].endswith("Z")
    assert lc.post(f"/api/sutras/{slug}/recitations").json()["total"] == 2
    assert lc.get(f"/api/sutras/{slug}").json()["recitations"]["total"] == 2
    assert lc.delete(f"/api/sutras/{slug}/recitations/last").json() == {"total": 1}
    assert lc.post("/api/sutras/nope/recitations").status_code == 404
    assert lc.delete("/api/sutras/nope/recitations/last").status_code == 404


def test_sr12_routes_not_present(lc):
    assert lc.post("/api/sutras", json={"text": TEXT}).status_code in (404, 405)
    assert lc.put("/api/sutras/x", json={}).status_code in (404, 405)


@pytest.mark.parametrize("page", ["index", "episode", "playlist", "posts", "monitor", "storage"])
def test_topnav_has_doc_kinh_link(page):
    html = (STATIC / f"{page}.html").read_text(encoding="utf-8")
    nav = re.search(r'<nav class="topnav">.*?</nav>', html, re.S).group(0)
    assert '<a href="/sutras">Đọc Kinh</a>' in nav and "/monitor" in nav and "/storage" in nav


def test_kind_bar_untouched():
    html = (STATIC / "episode.html").read_text(encoding="utf-8")
    assert "Khai thị" in html and "Bài đăng" in html


def test_static_assets_exist_and_served(lc):
    for name in ("sutras.html", "sutra.html", "sutra.js", "sutra.css", "sutra-awake.mp4"):
        assert (STATIC / name).is_file()
        assert lc.get(f"/static/{name}").status_code == 200
    js = (STATIC / "sutra.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "ffmpeg" in js and "wakeLock" in js
