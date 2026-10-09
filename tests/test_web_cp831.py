"""CP8.31: posts ``.docx`` export (D2, P16), download fields of the bộ kinh page (D3), static UI (D3-D6)."""

from __future__ import annotations

import io
import json
import struct
import zlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
docx = pytest.importorskip("docx")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.post import export as post_export  # noqa: E402
from auto_short.post import logic as post_logic  # noqa: E402
from auto_short.post import store as post_store  # noqa: E402
from auto_short.review.names import posts_docx_name  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
VID = "aaaaaaaaaa1"
KT = VID + ".kt"
VID2 = "bbbbbbbbbb2"
VID3 = "cccccccccc3"
PL = "PLtestplaylist01"
SERIES = "Thập Thiện Nghiệp Đạo Kinh"


def png(color: int) -> bytes:
    """A tiny valid PNG (distinct per colour so the SHA-1 differs)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    raw = b"\x00" + bytes([color, 0, 0]) * 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw * 2)) + chunk(b"IEND", b""))


@pytest.fixture
def tcfg(tmp_path) -> Config:
    (tmp_path / "images").mkdir()
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images"))


def client(cfg, **kw):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9), **kw)
    return TestClient(app, follow_redirects=False)


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def set_header(cfg, episode_id, series, episode):
    fields = {"speaker": "HT.Tịnh Không"}
    if series:
        fields["series"] = series
    fields["episode"] = episode
    (Path(cfg.workspace.dir) / episode_id / "titles.json").write_text(
        json.dumps({"header": {"fields": fields}}, ensure_ascii=False), encoding="utf-8")


def add_posts(cfg, episode_id, entries):
    """``entries``: (clip_id, paragraphs, image | None, posted)."""
    doc = post_store.empty_posts(episode_id)
    for cid, paras, image, posted in entries:
        doc["posts"].append({"clip_id": cid, "candidate_id": "c00001", "source_sha256": "a" * 64,
                             "paragraphs": paras, "origin": "manual", "image": image, "link": "https://youtube.com/shorts/xxxxxxxxxxx",
                             "posted_at": "2026-10-01T00:00:00Z" if posted else None, "updated_at": "2026-10-01T00:00:00Z"})
    post_store.write(Path(cfg.workspace.dir) / episode_id / "posts.json", doc)


def make_episode(cfg, eid, number, *, clips=("k01", "k02"), kt=False, series=SERIES):
    write_episode(cfg, eid, clips=clips, titles={c: f"Tựa {eid[:2]} {c}" for c in clips})
    set_header(cfg, eid, series, number)
    if kt:
        write_episode(cfg, eid + ".kt", clips=("k01",), titles={"k01": f"Khai {eid[:2]}"})
        khaithi.write(Path(cfg.workspace.dir) / (eid + ".kt"), KhaiThi(eid, 4, 7))
        set_header(cfg, eid + ".kt", series, number)


def read(resp):
    assert resp.status_code == 200, resp.text
    return docx.Document(io.BytesIO(resp.content))


def headings(d, level):
    return [p.text for p in d.paragraphs if p.style.name == f"Heading {level}"]


def media(resp):
    import zipfile
    return [n for n in zipfile.ZipFile(io.BytesIO(resp.content)).namelist() if n.startswith("word/media/")]


@pytest.fixture
def one(tcfg):
    """VID tập 29 with Short posts (k01 image a.png, k02 image missing.png) + khai thị post sharing a.png."""
    make_episode(tcfg, VID, "29", kt=True)
    (tcfg.post.image_dir / "a.png").write_bytes(png(10))
    add_posts(tcfg, VID, [("k01", ["Đoạn một.", "Đoạn hai."], "a.png", False), ("k02", ["Chỉ một đoạn."], "gone.png", True)])
    add_posts(tcfg, KT, [("k01", ["Khai thị đoạn."], "a.png", False)])
    return tcfg


# --- pure ----------------------------------------------------------------------------------------------------

def test_text_parts_matches_copy_text():
    fields = {"speaker": "HT.Tịnh Không", "series": "Kinh X", "episode": "3"}
    head, paras, src = post_logic.text_parts(title="Tựa", paragraphs=[" a ", "", "b"], header_fields=fields)
    assert (head, paras, src) == ("TỰA", ["a", "b"], "— HT. Tịnh Không, Kinh X tập 3")
    full = post_logic.compose_copy_text(title="Tựa", paragraphs=[" a ", "", "b"], header_fields=fields, link=None, hashtags=[])
    assert full == "\n\n".join([head, *paras, src])


def test_docx_names():
    assert posts_docx_name("29", series=SERIES) == f"{SERIES}_Tập29_BaiDang.docx"
    assert posts_docx_name("29") == "Tập29_BaiDang.docx"
    assert posts_docx_name(None, series=SERIES, fallback="PL1") == f"{SERIES}_BaiDang.docx"
    assert posts_docx_name(None, series=" ", fallback="PL1") == "PL1_BaiDang.docx"
    assert posts_docx_name("29", series='a/b:c*"d') == "abcd_Tập29_BaiDang.docx"


def test_build_docx_missing_image_keeps_text(tmp_path):
    out = tmp_path / "x.docx"
    post_export.build_docx(out, "Bộ", [post_export.ExportEpisode("Tập 1", [post_export.ExportGroup("Shorts", [
        post_export.ExportPost("TỰA", ["một"], "— src", "nope.png")])])], tmp_path)
    d = docx.Document(str(out))
    assert [p.text for p in d.paragraphs if p.style.name == "Heading 3"] == ["TỰA"]
    assert len(d.inline_shapes) == 0 and "một" in [p.text for p in d.paragraphs]


# --- D2: one video --------------------------------------------------------------------------------------------

def test_video_docx_content_and_order(one):
    before = (Path(one.workspace.dir) / VID / "posts.json").read_bytes()
    with client(one) as c:
        login(c)
        r = c.get(f"/files/{VID}/posts.docx")
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert "Tap29_BaiDang.docx" in r.headers["content-disposition"] or "BaiDang.docx" in r.headers["content-disposition"]
        d = read(r)
        assert [p.text for p in d.paragraphs if p.style.name == "Title"] == [f"{SERIES} tập 29 — Kinh Vô Lượng Thọ tập 3"]
        assert headings(d, 1) == [f"{SERIES} tập 29 — Kinh Vô Lượng Thọ tập 3"]
        assert headings(d, 2) == ["Shorts", "Khai thị"]
        assert headings(d, 3) == ["TỰA AA K01", "TỰA AA K02", "KHAI AA"]
        texts = [p.text for p in d.paragraphs]
        assert texts.index("Đoạn một.") < texts.index("Đoạn hai.") < texts.index("Chỉ một đoạn.") < texts.index("Khai thị đoạn.")
        assert texts.count("— HT. Tịnh Không, " + SERIES + " tập 29") == 3
        assert not any("youtube" in t or "#" in t or "▶" in t for t in texts)  # no link, no hashtags
        assert len(d.inline_shapes) == 2  # k01 + khai thị (k02's image is missing: text only)
        assert len(media(r)) == 1  # the shared image is embedded once
        # the khai thị id gives the same file
        d2 = read(c.get(f"/files/{KT}/posts.docx"))
        assert [p.text for p in d2.paragraphs] == [p.text for p in d.paragraphs]
    assert (Path(one.workspace.dir) / VID / "posts.json").read_bytes() == before  # no tick, no rewrite


def test_video_docx_skips_deleted_short_and_404s(one):
    rm_path = Path(one.render.output_dir) / VID / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][1].update(status="skipped", skip_reason="rejected")
    rm_path.write_text(json.dumps(rm), encoding="utf-8")
    with client(one) as c:
        login(c)
        assert headings(read(c.get(f"/files/{VID}/posts.docx")), 3) == ["TỰA AA K01", "KHAI AA"]
        assert c.get("/files/..%2Fx/posts.docx").status_code == 404
        assert c.get("/files/nonexistent1/posts.docx").status_code == 404
    make_episode(one, VID2, "30")  # episode without posts.json
    with client(one) as c:
        login(c)
        assert c.get(f"/files/{VID2}/posts.docx").status_code == 404


def test_docx_requires_login_and_removes_temp_file(one, monkeypatch, tmp_path):
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(tmpdir))
    with client(one) as c:
        assert c.get(f"/files/{VID}/posts.docx").status_code in (401, 303)
        assert c.get(f"/files/playlists/{PL}/posts.docx").status_code in (401, 303)
        login(c)
        assert c.get(f"/files/{VID}/posts.docx").status_code == 200
    assert list(tmpdir.iterdir()) == []


# --- D2/D3: bộ kinh -------------------------------------------------------------------------------------------

def make_playlist(cfg, entries, series=None):
    root = Path(cfg.workspace.dir) / "_playlists"
    root.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "playlist_id": PL, "title": "Danh sách thử", "url": f"https://www.youtube.com/playlist?list={PL}",
           "fetched_at": "2026-10-01T00:00:00Z",
           "entries": [{"index": i, "video_id": v, "title": f"Tập {n}", "duration": 3000.0, "episode": n, "available": True}
                       for i, (v, n) in enumerate(entries, 1)]}
    if series:
        doc["series"] = series
    (root / f"{PL}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_playlist_docx_order_and_name(one):
    make_episode(one, VID2, "3", clips=("k01",))
    (one.post.image_dir / "b.png").write_bytes(png(200))
    add_posts(one, VID2, [("k01", ["Tập ba."], "b.png", False)])
    make_episode(one, VID3, "5", clips=("k01",))  # no posts: skipped
    make_playlist(one, [(VID, "29"), (VID3, "5"), (VID2, "3")], series=SERIES)
    with client(one) as c:
        login(c)
        r = c.get(f"/files/playlists/{PL}/posts.docx")
        d = read(r)
        assert [p.text for p in d.paragraphs if p.style.name == "Title"] == [SERIES]
        assert [h.split(" — ")[0] for h in headings(d, 1)] == [f"{SERIES} tập 3", f"{SERIES} tập 29"]  # tập order
        assert len(media(r)) == 2  # a.png (2 uses) + b.png: one copy each
        assert len(d.inline_shapes) == 3
        assert "BaiDang.docx" in r.headers["content-disposition"]
        assert "Th%E1%BA%ADp%20Thi%E1%BB%87n" in r.headers["content-disposition"]  # series in the UTF-8 file name
        assert c.get("/files/playlists/PLunknown000000/posts.docx").status_code == 404
        assert c.get("/files/playlists/..%2Fx/posts.docx").status_code == 404


def test_playlist_docx_404_without_posts_and_fallback_name(tcfg):
    make_episode(tcfg, VID2, "3", clips=("k01",))
    make_playlist(tcfg, [(VID2, "3")])
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/files/playlists/{PL}/posts.docx").status_code == 404
        add_posts(tcfg, VID2, [("k01", ["x"], None, False)])
        r = c.get(f"/files/playlists/{PL}/posts.docx")
        assert f"{PL}_BaiDang.docx" in r.headers["content-disposition"]


def test_playlist_api_download_fields(one):
    make_episode(one, VID2, "3", clips=("k01",))  # Short only, no posts
    make_episode(one, VID3, "5", clips=("k01",), kt=False)
    add_posts(one, VID3, [("k01", ["x"], None, False)])
    make_playlist(one, [(VID, "29"), (VID2, "3"), (VID3, "5")], series=SERIES)
    with client(one) as c:
        login(c)
        d = c.get(f"/api/playlists/{PL}").json()
        by = {e["video_id"]: e for e in d["entries"]}
        assert by[VID]["zip_url"] == f"/files/{VID}/all.zip" and by[VID]["zip_name"].endswith("Shorts+KhaiThị.zip")
        assert by[VID]["posts_docx_url"] == f"/files/{VID}/posts.docx"
        assert by[VID]["posts_docx_name"] == f"{SERIES}_Tập29_BaiDang.docx"
        assert by[VID2]["zip_url"] == f"/files/{VID2}/shorts.zip" and by[VID2]["posts_docx_url"] is None
        assert by[VID3]["posts_docx_url"] == f"/files/{VID3}/posts.docx"
        assert d["posts_docx_url"] == f"/files/playlists/{PL}/posts.docx"
        assert d["posts_docx_name"] == f"{SERIES}_BaiDang.docx"
    make_playlist(one, [(VID2, "3")])
    with client(one) as c:
        login(c)
        assert c.get(f"/api/playlists/{PL}").json()["posts_docx_url"] is None


def test_playlist_zip_url_ticks(one):
    make_playlist(one, [(VID, "29")])
    with client(one) as c:
        login(c)
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert e["published"] == 0
        assert c.get(e["zip_url"]).status_code == 200
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert e["published"] == 2 and e["khaithi_published"] == 1


# --- static UI (D3-D6) -----------------------------------------------------------------------------------------

def test_static_ui(tcfg):
    with client(tcfg) as c:
        login(c)
        css, js = c.get("/static/style.css").text, c.get("/static/app.js").text
        assert "[hidden] { display: none !important; }" in css  # D4
        assert ".actions .btn { flex: 1 1 100%; }" not in css  # D5
        assert "calc(50% - .5rem)" in css
        assert 'id="pl-posts-docx"' in c.get(f"/playlists/{PL}").text
        assert 'id="posts-docx"' in c.get(f"/episodes/{VID}/posts").text
        assert "posts_docx_url" in js and 'icon("zip")' in js and 'icon("doc")' in js
        # D6: the enhance block moved from the storage tab to the monitor tab
        storage, monitor = c.get("/storage").text, c.get("/monitor").text
        assert "enhance-card" not in storage and "enhance-pause" not in storage and "enhance-summary" not in storage
        assert 'id="enhance-summary"' in monitor and 'id="enhance-pause"' in monitor and 'id="mon-gpu"' in monitor
        assert "enhance-workers" not in monitor and "enhance-workers" not in js
        assert c.get("/api/enhance/status").status_code == 200
