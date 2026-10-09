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


def test_playlist_docx_ranges_and_name(one):
    make_episode(one, VID2, "3", clips=("k01",))
    (one.post.image_dir / "b.png").write_bytes(png(200))
    add_posts(one, VID2, [("k01", ["Tập ba."], "b.png", False)])
    make_episode(one, VID3, "5", clips=("k01",))  # no posts: skipped
    make_playlist(one, [(VID, "29"), (VID3, "5"), (VID2, "3")], series=SERIES)
    with client(one) as c:
        login(c)
        assert c.get(f"/files/playlists/{PL}/posts.docx").status_code == 422  # no whole-bộ file
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=30")
        assert r.status_code == 422  # more than 10 episodes
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=21&to=30")
        assert [h.split(" — ")[0] for h in headings(read(r), 1)] == [f"{SERIES} tập 29"]
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=10")
        d = read(r)
        assert [p.text for p in d.paragraphs if p.style.name == "Title"] == [SERIES]
        assert [h.split(" — ")[0] for h in headings(d, 1)] == [f"{SERIES} tập 3"]  # tập 5 has no post: skipped
        assert len(media(r)) == 1 and len(d.inline_shapes) == 1
        assert "BaiDang.docx" in r.headers["content-disposition"] and "T%E1%BA%ADp1-10_BaiDang" in r.headers["content-disposition"]
        assert "Th%E1%BA%ADp%20Thi%E1%BB%87n" in r.headers["content-disposition"]  # series in the UTF-8 file name
        assert c.get(f"/files/playlists/{PL}/posts.docx?from=4&to=4").status_code == 404  # empty range
        assert c.get(f"/files/playlists/{PL}/posts.docx?from=x&to=4").status_code == 422
        assert c.get(f"/files/playlists/{PL}/posts.docx?from=5&to=2").status_code == 422
        assert c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=10&images=2").status_code == 422
        assert c.get("/files/playlists/PLunknown000000/posts.docx?from=1&to=10").status_code == 404
        assert c.get("/files/playlists/..%2Fx/posts.docx").status_code == 404


def test_playlist_docx_404_without_posts_and_fallback_name(tcfg):
    make_episode(tcfg, VID2, "3", clips=("k01",), series=None)
    make_playlist(tcfg, [(VID2, "3")])
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=10").status_code == 404
        add_posts(tcfg, VID2, [("k01", ["x"], None, False)])
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=10")
        assert f"{PL}_T%E1%BA%ADp1-10_BaiDang.docx" in r.headers["content-disposition"]


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
        assert "posts_docx_url" not in d  # A1: no whole-bộ download
        assert d["posts_ranges"] == [
            {"from": 1, "to": 10, "label": "Tập 1–10", "episodes": 1, "posts": 1,
             "url": f"/files/playlists/{PL}/posts.docx?from=1&to=10"},
            {"from": 21, "to": 30, "label": "Tập 21–30", "episodes": 1, "posts": 3,
             "url": f"/files/playlists/{PL}/posts.docx?from=21&to=30"}]
    make_playlist(one, [(VID2, "3")])
    with client(one) as c:
        login(c)
        assert c.get(f"/api/playlists/{PL}").json()["posts_ranges"] == []


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
        pl = c.get(f"/playlists/{PL}").text
        assert 'id="pl-posts-box"' in pl and 'id="pl-docx-images"' in pl and "Có hình" in pl
        assert 'id="posts-docx-images"' in c.get(f"/episodes/{VID}/posts").text
        assert "autoShort.docxImages" in js and "progressBadge" in js and ".badge.prog.full" in css
        assert 'id="posts-docx"' in c.get(f"/episodes/{VID}/posts").text
        assert "posts_docx_url" in js and 'icon("zip")' in js and 'icon("doc")' in js
        # D6: the enhance block moved from the storage tab to the monitor tab
        storage, monitor = c.get("/storage").text, c.get("/monitor").text
        assert "enhance-card" not in storage and "enhance-pause" not in storage and "enhance-summary" not in storage
        assert 'id="enhance-summary"' in monitor and 'id="enhance-pause"' in monitor and 'id="mon-gpu"' in monitor
        assert "enhance-workers" not in monitor and "enhance-workers" not in js
        assert c.get("/api/enhance/status").status_code == 200


def test_playlist_name_falls_back_to_episode_series_and_heading_no_duplicate(tcfg):
    make_episode(tcfg, VID2, "3", clips=("k01",))
    add_posts(tcfg, VID2, [("k01", ["x"], None, False)])
    meta = Path(tcfg.workspace.dir) / VID2 / "metadata.json"
    meta.write_text(json.dumps({"title": f"{SERIES} tập 3 / 102 - Lão Pháp Sư"}, ensure_ascii=False), encoding="utf-8")
    make_playlist(tcfg, [(VID2, "3")])  # no stored series
    with client(tcfg) as c:
        login(c)
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=1&to=10")
        assert "BaiDang.docx" in r.headers["content-disposition"] and PL not in r.headers["content-disposition"]
        assert headings(read(r), 1) == [f"{SERIES} tập 3"]  # video title already holds the series: no repeat


def test_static_and_pages_revalidate(tcfg):
    with client(tcfg) as c:
        assert c.get("/login").headers["cache-control"] == "no-cache"
        login(c)
        assert c.get("/static/style.css").headers["cache-control"] == "no-cache"
        assert c.get("/static/app.js").headers["cache-control"] == "no-cache"
        assert c.get("/monitor").headers["cache-control"] == "no-cache"
        assert c.get("/api/storage/status").headers["cache-control"] == "no-store"  # own value kept


# --- A1: images=0, unnumbered episodes, names ------------------------------------------------------------------

def test_images_flag_video_and_range(one):
    make_playlist(one, [(VID, "29")], series=SERIES)
    with client(one) as c:
        login(c)
        with_img, without = c.get(f"/files/{VID}/posts.docx"), c.get(f"/files/{VID}/posts.docx?images=0")
        assert len(media(with_img)) == 1 and media(without) == []
        assert len(read(without).inline_shapes) == 0 and "Chỉ một đoạn." in [p.text for p in read(without).paragraphs]
        assert "BaiDang_KhongHinh.docx" in without.headers["content-disposition"]
        assert "KhongHinh" not in with_img.headers["content-disposition"]
        r = c.get(f"/files/playlists/{PL}/posts.docx?from=21&to=30&images=0")
        assert media(r) == [] and "T%E1%BA%ADp21-30_BaiDang_KhongHinh.docx" in r.headers["content-disposition"]
        assert c.get(f"/files/{VID}/posts.docx?images=x").status_code == 422


def test_other_unnumbered_episodes(tcfg):
    make_episode(tcfg, VID2, "3", clips=("k01",))
    make_episode(tcfg, VID3, "0", clips=("k01",))
    add_posts(tcfg, VID2, [("k01", ["x"], None, False)])
    add_posts(tcfg, VID3, [("k01", ["y"], None, False)])
    make_playlist(tcfg, [(VID2, "3"), (VID3, None)], series=SERIES)
    with client(tcfg) as c:
        login(c)
        rng = c.get(f"/api/playlists/{PL}").json()["posts_ranges"]
        assert [(r["label"], r["posts"]) for r in rng] == [("Tập 1–10", 1), ("Tập chưa rõ số", 1)]
        r = c.get(rng[1]["url"])
        assert "T%E1%BA%ADp%20ch%C6%B0a%20r%C3%B5_BaiDang.docx" in r.headers["content-disposition"]
        assert [p.text for p in read(r).paragraphs if p.text == "y"] == ["y"]
        assert c.get(f"/files/playlists/{PL}/posts.docx?other=1&from=1&to=2").status_code == 422


def test_docx_names_range_and_no_images():
    assert posts_docx_name(None, series=SERIES, span="1-10") == f"{SERIES}_Tập1-10_BaiDang.docx"
    assert posts_docx_name(None, series=None, fallback="PL1", span="1-10", images=False) == "PL1_Tập1-10_BaiDang_KhongHinh.docx"
    assert posts_docx_name("29", series=SERIES, images=False) == f"{SERIES}_Tập29_BaiDang_KhongHinh.docx"


# --- A2: progress badges (API numbers + static) ---------------------------------------------------------------------

def test_post_progress_numbers(one):
    make_episode(one, VID2, "3", clips=("k01", "k02"))
    add_posts(one, VID2, [("k01", ["a"], None, True), ("k02", ["b"], None, True)])  # all posted
    make_episode(one, VID3, "5", clips=("k01",))  # rendered, no post yet
    make_playlist(one, [(VID, "29"), (VID2, "3"), (VID3, "5")], series=SERIES)
    with client(one) as c:
        login(c)
        by = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
        # VID: Short k01 + k02 (k02 posted) + khai thị k01 -> 3 rendered, 3 posts, 1 posted
        assert (by[VID]["posts_total"], by[VID]["posts_posted"]) == (3, 1)
        assert (by[VID2]["posts_total"], by[VID2]["posts_posted"]) == (2, 2)
        assert (by[VID3]["posts_total"], by[VID3]["posts_posted"]) == (1, 0)
        assert by[VID]["shorts"] == 2 and by[VID]["khaithi_videos"] == 1


def test_badge_static_has_text_and_colour_classes(tcfg):
    with client(tcfg) as c:
        login(c)
        js, css = c.get("/static/app.js").text, c.get("/static/style.css").text
        assert "if (!total) return null" in js  # y = 0 hides the badge
        assert 'done >= total ? "full" : done > 0 ? "part" : "none"' in js
        assert '`${label} ${done}/${total}`' in js  # text, not colour only
        for k in ("full", "part", "none"):
            assert f".badge.prog.{k}" in css
        assert "đã đăng ${e.published}/${e.shorts}" not in js  # the counts moved out of the status line


def test_mobile_row_actions_aligned_with_name(tcfg):
    with client(tcfg) as c:
        login(c)
        css = c.get("/static/style.css").text
        mobile = css[css.index("@media (max-width: 640px)"):]
        assert "margin-left: calc(2.2rem + .5rem)" in mobile and "flex-basis: calc(100% - 2.7rem)" in mobile
        assert ".pl-entry .rec-actions .btn { width: auto; min-height: 2.75rem;" in mobile
        assert ".pl-index { min-width: 2.2rem;" in css  # the index column the margin matches


def test_home_playlist_badges_static(tcfg):
    with client(tcfg) as c:
        login(c)
        js, css = c.get("/static/app.js").text, c.get("/static/style.css").text
        body = js[js.index("function playlistBadges(p)"):js.index("// Episode list filter")]
        assert "`Đã xử lý ${p.processed}/${p.count}`" in body and "`Xong ${p.complete}`" in body
        assert '"full" : p.processed > 0 ? "part" : "none"' in body  # grey 0 / amber partial / green all
        assert body.count(".filter(([, n]) => n)") == 1  # zero badges hidden (only "Đã xử lý" is always shown)
        assert '"busy"' in body and '"err"' in body and '"part"' in body
        for k in ("full", "part", "none", "busy", "err"):
            assert f".badge.prog.{k}" in css
        assert " · đã xử lý" not in js  # no joined text line any more


def test_zip_click_refreshes_repeatedly_and_on_return(tcfg):
    with client(tcfg) as c:
        login(c)
        js = c.get("/static/app.js").text
        assert "const ZIP_REFRESH_MS = [2000, 5000, 10000, 20000];" in js  # last ones > 5 s status cache
        assert "zipRefresh.timers.forEach(clearTimeout)" in js  # no stacked timers
        assert 'document.addEventListener("visibilitychange", zipRefreshNow)' in js
        assert 'window.addEventListener("focus", zipRefreshNow)' in js
        assert "Date.now() - zipRefresh.at < ZIP_RETURN_MS" in js
        assert "zip.onclick = () => zipAfterClick(refreshEpisode);" in js
        assert "zipAll.onclick = () => zipAfterClick(refreshEpisode);" in js
        assert "zipAfterClick(loadPlaylist)" in js and "setTimeout(loadPlaylist, 2500)" not in js
