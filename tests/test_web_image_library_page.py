"""IMG3: standalone image library page, shared markup and navigation."""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.web.app import STATIC_DIR
from web_helpers import login, web_client


STATIC = Path(STATIC_DIR)


@pytest.mark.parametrize("name", [
    "index", "episode", "playlist", "posts", "monitor", "storage", "sutras", "sutra-edit", "favorites",
])
def test_topnav_links_to_image_library(name):
    html = (STATIC / f"{name}.html").read_text(encoding="utf-8")
    nav = html.split('<nav class="topnav">', 1)[1].split('</nav>', 1)[0]
    assert '<a href="/sutras">Đọc Kinh</a> <a href="/images">Thư viện ảnh</a>' in nav


def test_image_library_markup_has_one_shared_builder():
    posts = (STATIC / "posts.html").read_text(encoding="utf-8")
    page = (STATIC / "images.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="image-dialog"' in posts and 'id="image-close"' in posts
    for element in ("image-grid", "image-find-btn", "image-upload-input", "image-cand-grid"):
        assert f'id="{element}"' not in posts
        assert f'id="{element}"' not in page
        assert js.count(f'id="{element}"') == 1
    assert js.count("function buildImageLibrary(container)") == 1
    assert 'buildImageLibrary($("#image-dialog .modal-box"))' in js
    assert 'buildImageLibrary($("#image-library"))' in js
    assert 'id="image-dialog"' not in page and 'id="image-close"' not in page
    assert "AutoShort.initImages();" in page


def test_images_page_requires_login_and_initializes_library(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                 render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"))
    client = web_client(cfg)
    anon = client.get("/images")
    assert anon.status_code == 303
    assert anon.headers["location"] == "/login?next=%2Fimages"
    login(client)
    page = client.get("/images")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-cache"
    assert "AutoShort.initImages();" in page.text
