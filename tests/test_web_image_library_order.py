"""Image library ordering; TestClient verification runs outside the Codex sandbox."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.packaging import cover_suggest
from auto_short.post import images, imggen, imgsearch
from image_fixtures import make_jpeg, make_png
from test_imggen_img1 import fake_codex, gen_cfg
from web_helpers import login, make_app


@pytest.fixture
def client(gen_cfg, monkeypatch):
    monkeypatch.setattr(cover_suggest, "available", lambda config: None)
    app = make_app(gen_cfg, codex_runner=fake_codex)
    with TestClient(app, follow_redirects=False) as c:
        login(c)
        yield c


def test_newest_mtime_first_and_response_fields(gen_cfg, client):
    folder = gen_cfg.post.image_dir
    folder.mkdir()
    png = make_png(600, 800)
    for name, mtime, data in (("99.jpg", 100, make_jpeg(800, 600)),
                              ("312.png", 300, png), ("01.png", 200, png)):
        path = folder / name
        path.write_bytes(data)
        os.utime(path, (mtime, mtime))
    (folder / "sources.tsv").write_text("312.png\tcodex-ai:sen\n", encoding="utf-8")

    response = client.get("/api/post-images")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"images", "image_sources", "search", "generate"}
    assert [i["name"] for i in body["images"]] == ["312.png", "01.png", "99.jpg"]
    assert body["images"] == [
        {"name": "312.png", "width": 600, "height": 800, "bytes": len(png),
         "used": 0, "source": "codex-ai:sen"},
        {"name": "01.png", "width": 600, "height": 800, "bytes": len(png), "used": 0, "source": None},
        {"name": "99.jpg", "width": 800, "height": 600, "bytes": len(make_jpeg(800, 600)),
         "used": 0, "source": None},
    ]
    assert body["image_sources"] == list(gen_cfg.post.image_sources)
    assert body["search"] == imgsearch.search_status(gen_cfg)
    assert body["generate"] == {
        "unavailable": None, "styles": [{"id": s["id"], "label": s["label"]} for s in imggen.STYLES]}
    assert [i.name for i in images.list_images(folder)] == ["01.png", "312.png", "99.jpg"]


def test_same_mtime_numeric_descending_then_name(gen_cfg, client):
    folder = gen_cfg.post.image_dir
    folder.mkdir()
    for name in ("abc.jpg", "99.jpg", "100.jpg", "099.jpg", "zzz.png"):
        path = folder / name
        path.write_bytes(make_png(600, 600) if path.suffix == ".png" else make_jpeg(600, 600))
        os.utime(path, (100, 100))

    response = client.get("/api/post-images")
    assert response.status_code == 200
    assert [i["name"] for i in response.json()["images"]] == [
        "100.jpg", "099.jpg", "99.jpg", "abc.jpg", "zzz.png"]


def test_empty_library(gen_cfg, client):
    gen_cfg.post.image_dir.mkdir()
    response = client.get("/api/post-images")
    assert response.status_code == 200
    assert response.json()["images"] == []
    assert set(response.json()) == {"images", "image_sources", "search", "generate"}


def test_disappearing_file_uses_zero_mtime(gen_cfg, client, monkeypatch):
    folder = gen_cfg.post.image_dir
    folder.mkdir()
    for name in ("100.png", "01.png"):
        path = folder / name
        path.write_bytes(make_png(600, 600))
        os.utime(path, (100, 100))
    original = images.list_images

    def list_then_remove(image_dir):
        infos = original(image_dir)
        (image_dir / "100.png").unlink()
        return infos

    monkeypatch.setattr(images, "list_images", list_then_remove)
    response = client.get("/api/post-images")
    assert response.status_code == 200
    assert [i["name"] for i in response.json()["images"]] == ["01.png", "100.png"]
