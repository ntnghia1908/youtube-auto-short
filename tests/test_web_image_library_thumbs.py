"""Library thumbnails: cached previews, original downloads and shared grid URLs."""

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from auto_short.config import PostConfig
from auto_short.post import dhash, images, imggen, imgsearch
from image_fixtures import make_jpeg, make_png


@pytest.fixture
def library_cfg(cfg, tmp_path):
    config = replace(cfg, post=PostConfig(image_dir=tmp_path / "images"))
    config.post.image_dir.mkdir()
    (config.post.image_dir / "photo.png").write_bytes(make_png(1200, 900))
    return config


@pytest.fixture(scope="module", params=["png", "jpg"])
def large_image(request):
    # Real scan data: image_fixtures.make_jpeg only supplies a sniffable header.
    codec = "png" if request.param == "png" else "mjpeg"
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1600x1200",
         "-frames:v", "1", "-c:v", codec, "-q:v", "1", "-f", "image2pipe", "pipe:1"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )
    return f"large.{request.param}", result.stdout


@pytest.fixture
def client(library_cfg, monkeypatch):
    pytest.importorskip("fastapi")
    from auto_short.packaging import cover_suggest
    from web_helpers import web_client

    monkeypatch.setattr(cover_suggest, "available", lambda config: None)
    with web_client(library_cfg, login=True, post_preflight=lambda config: None,
                    post_compose=lambda *args, **kwargs: None) as c:
        yield c


def test_helper_thumbnail_is_small_jpeg(library_cfg, large_image):
    name, data = large_image
    folder = library_cfg.post.image_dir
    (folder / name).write_bytes(data)
    thumb = images.thumbnail_file(folder, name)
    assert thumb is not None
    ext, width, height = images.sniff(thumb.read_bytes())
    assert ext == ".jpg" and 0 < width <= 400 and height > 0
    assert len(thumb.read_bytes()) < len(data) / 4


def test_helper_cache_key_tracks_name_mtime_size_and_replacement(library_cfg, monkeypatch):
    folder = library_cfg.post.image_dir
    source = folder / "photo.png"
    render = Mock(return_value=make_jpeg(400, 300))
    monkeypatch.setattr(dhash, "thumbnail", render)
    first = images.thumbnail_file(folder, source.name)
    assert first is not None
    assert images.thumbnail_file(folder, source.name) == first
    render.assert_called_once_with(source.read_bytes(), width=400)

    st = source.stat()
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    second = images.thumbnail_file(folder, source.name)
    assert second != first
    st = source.stat()
    source.write_bytes(source.read_bytes() + b"extra")
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    third = images.thumbnail_file(folder, source.name)
    assert third != second
    renamed = folder / "other.png"
    source.rename(renamed)
    fourth = images.thumbnail_file(folder, renamed.name)
    assert fourth != third
    renamed.unlink()
    renamed.write_bytes(make_png(900, 1200))
    os.utime(renamed, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000))
    assert images.thumbnail_file(folder, renamed.name) != fourth
    assert render.call_count == 5


def test_helper_cache_is_outside_library_and_ignored_by_runs(library_cfg):
    folder = library_cfg.post.image_dir
    before = images.list_images(folder)
    thumb = images.thumbnail_file(folder, "photo.png")
    assert thumb is not None and folder not in thumb.parents
    assert thumb.parent == imgsearch.cache_dir(folder) / "library-thumbs"
    assert not imgsearch.SEARCH_ID_RE.match(thumb.parent.name)
    assert images.list_images(folder) == before
    assert imgsearch.next_name(folder) == "01"
    run = imggen.create(library_cfg, "hoa sen")
    assert [r["search_id"] for r in imggen._runs(library_cfg)] == [run["search_id"]]
    assert imgsearch.purge_old(imgsearch.cache_dir(folder), 0, now=10**12) == 0
    assert thumb.is_file()  # Running generations and library cache both survive purge.


@pytest.mark.parametrize("failure", ["decode", "write", "missing", "unsafe"])
def test_helper_failure_returns_none(library_cfg, monkeypatch, failure):
    render = Mock(return_value=None if failure == "decode" else make_jpeg(400, 300))
    monkeypatch.setattr(dhash, "thumbnail", render)
    if failure == "write":
        monkeypatch.setattr(images, "atomic_write_bytes", Mock(side_effect=OSError("read-only cache")))
    name = {"missing": "missing.png", "unsafe": "../photo.png"}.get(failure, "photo.png")
    assert images.thumbnail_file(library_cfg.post.image_dir, name) is None
    assert render.call_count == (0 if failure in ("missing", "unsafe") else 1)


def test_http_thumbnail_and_cache_isolation(client, library_cfg, large_image):
    name, data = large_image
    (library_cfg.post.image_dir / name).write_bytes(data)
    before = client.get("/api/post-images").json()
    response = client.get(f"/files/post-images/{name}?thumb=1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert images.sniff(response.content)[1] <= 400
    assert len(response.content) < len(data) / 4
    assert "content-disposition" not in response.headers
    assert response.headers["cache-control"] == "private, no-cache"
    assert client.get("/api/post-images").json() == before


@pytest.mark.parametrize("name", ["missing.png", "photo.png;bad", "..%2Fphoto.png"])
def test_http_unknown_or_unsafe_name_is_404(client, monkeypatch, name):
    render = Mock()
    monkeypatch.setattr(dhash, "thumbnail", render)
    assert client.get(f"/files/post-images/{name}?thumb=1").status_code == 404
    render.assert_not_called()


def test_http_decode_failure_falls_back_to_original(client, library_cfg, monkeypatch):
    render = Mock(return_value=None)
    monkeypatch.setattr(dhash, "thumbnail", render)
    response = client.get("/files/post-images/photo.png?thumb=1")
    assert response.status_code == 200
    assert response.content == (library_cfg.post.image_dir / "photo.png").read_bytes()
    assert response.headers["content-type"] == "image/png"
    assert render.call_count == 1


@pytest.mark.parametrize("query,download", [("", False), ("?download=1", True),
                                            ("?download=1&thumb=1", True)])
def test_http_original_and_download_stay_unchanged(client, library_cfg, monkeypatch, query, download):
    render = Mock()
    monkeypatch.setattr(dhash, "thumbnail", render)
    response = client.get(f"/files/post-images/photo.png{query}")
    assert response.status_code == 200
    assert response.content == (library_cfg.post.image_dir / "photo.png").read_bytes()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-cache"
    assert ("content-disposition" in response.headers) == download
    if download:
        assert "photo.png" in response.headers["content-disposition"]
    render.assert_not_called()


def test_grid_uses_thumbnails_and_posts_use_originals():
    js = (Path(__file__).parents[1] / "src/auto_short/web/static/app.js").read_text(encoding="utf-8")
    assert 'src: `/files/post-images/${encodeURIComponent(img.name)}?thumb=1`' in js
    for owner in ("p", "cur"):
        assert f'src: `/files/post-images/${{encodeURIComponent({owner}.image)}}`' in js
        assert f'href: `/files/post-images/${{encodeURIComponent({owner}.image)}}?download=1`' in js
