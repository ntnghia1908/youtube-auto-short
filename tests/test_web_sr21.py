"""SR2.1: Khai thị reading library (K2 API, K3 page route / static), shares its data with the CP8.31 ``.docx`` export."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
docx = pytest.importorskip("docx")

from auto_short.web import reading  # noqa: E402
from test_web_cp831 import (KT, PL, SERIES, VID, VID2, VID3, add_posts, client, login, make_episode,  # noqa: E402
                            make_playlist, tcfg)  # noqa: F401

STATIC = Path(__file__).resolve().parent.parent / "src" / "auto_short" / "web" / "static"


def setup_book(cfg):
    make_episode(cfg, VID, "29", kt=True)
    make_episode(cfg, VID2, "3", clips=("k01",))
    make_episode(cfg, VID3, "5", clips=("k01",))  # no post
    add_posts(cfg, VID, [("k01", ["Đoạn một.", "Đoạn hai."], None, False), ("k02", ["Chỉ một."], None, True)])
    add_posts(cfg, KT, [("k01", ["Khai thị đoạn."], None, False)])
    add_posts(cfg, VID2, [("k01", ["Tập ba."], None, False)])
    make_playlist(cfg, [(VID, "29"), (VID3, "5"), (VID2, "3")], series=SERIES)


def sections(book):
    return [(g["title"], s) for g in book["groups"] for s in g["sections"]]


def test_pure_helpers():
    assert reading.range_label(1, 10) == "Tập 1–10"
    ranges, other = reading.ranges_of([(3, 2), (29, 1), (None, 4), (5, 0)], 10)
    assert ranges == [{"from": 1, "to": 10, "label": "Tập 1–10", "posts": 2},
                      {"from": 21, "to": 30, "label": "Tập 21–30", "posts": 1}] and other == {"posts": 4}
    assert reading.ranges_of([(None, 0)], 10) == ([], None)
    assert [r["posts"] for r in reading.single_ranges(12, 10, [1] * 12)] == [10, 2]
    assert reading.sort_key("Đại") < reading.sort_key("Em")


def test_requires_login(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        assert c.get("/api/reading/khaithi").status_code == 401
        assert c.get(f"/api/reading/khaithi/{PL}?from=1&to=10").status_code == 401
        r = c.get(f"/sutras/khaithi/{PL}")
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")


def test_list_ranges_counts_and_single(tcfg):
    setup_book(tcfg)
    make_episode(tcfg, "lone0000001", "1", clips=("k01",), series=None)
    add_posts(tcfg, "lone0000001", [("k01", ["Lẻ."], None, False)])
    with client(tcfg) as c:
        login(c)
        r = c.get("/api/reading/khaithi")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        books = r.json()
        assert [b["playlist_id"] for b in books] == [PL, "_single"]
        assert books[0]["title"] == SERIES and books[0]["other"] is None
        assert [(x["from"], x["to"], x["label"], x["posts"]) for x in books[0]["ranges"]] == \
            [(1, 10, "Tập 1–10", 1), (21, 30, "Tập 21–30", 3)]
        assert books[1]["title"] == "Video lẻ"
        assert books[1]["ranges"] == [{"from": 1, "to": 10, "label": "Tập 1–10", "posts": 1}]


def test_empty_library(tcfg):
    with client(tcfg) as c:
        login(c)
        assert c.get("/api/reading/khaithi").json() == []


def test_book_shape_and_docx_order(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        r = c.get(f"/api/reading/khaithi/{PL}?from=1&to=30")
        assert r.status_code == 422  # more than 10 episodes
        r = c.get(f"/api/reading/khaithi/{PL}?from=1&to=30".replace("to=30", "to=10"))
        b = r.json()
        assert b["schema_version"] == 1 and b["title"] == f"{SERIES} · Tập 1–10" and b["intro"] == []
        assert [g["title"].split(" — ")[0] for g in b["groups"]] == [f"{SERIES} tập 3"]
        r = c.get(f"/api/reading/khaithi/{PL}?from=21&to=30")
        b = r.json()
        secs = sections(b)
        assert [s["id"] for _, s in secs] == ["s1", "s2", "s3"]
        assert [s["title"] for _, s in secs] == ["T29_S01 · TỰA AA K01", "T29_S02 · TỰA AA K02", "T29_KT01 · KHAI AA"]
        s1 = secs[0][1]
        assert s1["paragraphs"] == [[{"text": "Đoạn một.", "kind": "text"}], [{"text": "Đoạn hai.", "kind": "text"}]]
        assert s1["notes"] == {} and s1["episode_id"] == VID and s1["clip_id"] == "k01" and s1["posted"] is False
        assert secs[1][1]["posted"] is True and secs[2][1]["episode_id"] == KT
        assert s1["copy_text"].startswith("Đoạn một.\n\nĐoạn hai.") and "Xem video" in s1["copy_text"]
        assert isinstance(s1["stale"], bool)
        # same episodes / posts / order as the .docx of the same range
        d = docx.Document(io.BytesIO(c.get(f"/files/playlists/{PL}/posts.docx?from=21&to=30").content))
        h3 = [p.text for p in d.paragraphs if p.style.name == "Heading 3"]
        assert h3 == ["TỰA AA K01", "TỰA AA K02", "KHAI AA"] == [s["title"].split(" · ")[1] for _, s in secs]
        h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
        assert h1 == [g["title"] for g in b["groups"]]


def test_copy_text_equals_posts_tab(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        tab = {p["clip_id"]: p["text"] for p in c.get(f"/api/episodes/{VID}/posts").json()["posts"]}
        secs = sections(c.get(f"/api/reading/khaithi/{PL}?from=21&to=30").json())
        assert {s["clip_id"]: s["copy_text"] for _, s in secs if s["episode_id"] == VID} == tab


def test_errors_404_422(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        g = lambda q, pid=PL: c.get(f"/api/reading/khaithi/{pid}{q}").status_code  # noqa: E731
        assert g("?from=4&to=4") == 404 and g("?other=1") == 404
        assert g("") == 422 and g("?from=5&to=2") == 422 and g("?from=x&to=4") == 422
        assert g("?other=1&from=1&to=2") == 422 and g("?other=2") == 422
        assert g("?from=1&to=10", "PLunknown000000") == 404 and g("?from=1&to=10", "..%2Fx") == 404
        assert g("?from=1&to=10", "_single") == 404  # no single episode
        assert g("?other=1", "_single") == 404 and g("", "_single") == 422


def test_other_unnumbered(tcfg):
    make_episode(tcfg, VID3, "0", clips=("k01",))
    add_posts(tcfg, VID3, [("k01", ["y"], None, False)])
    make_playlist(tcfg, [(VID3, None)], series=SERIES)
    with client(tcfg) as c:
        login(c)
        assert c.get("/api/reading/khaithi").json()[0]["other"] == {"posts": 1}
        b = c.get(f"/api/reading/khaithi/{PL}?other=1").json()
        assert b["title"] == f"{SERIES} · Tập chưa rõ số" and sections(b)[0][1]["paragraphs"][0][0]["text"] == "y"


def test_single_groups_newest_first(tcfg):
    ids = [f"single{n:05d}" for n in range(12)]
    for n, eid in enumerate(ids):
        make_episode(tcfg, eid, str(n + 1), clips=("k01",), series=None)
        add_posts(tcfg, eid, [("k01", [f"bài {n}"], None, False)])
        mf = Path(tcfg.workspace.dir) / eid / "manifest.json"
        doc = json.loads(mf.read_text(encoding="utf-8"))
        for st in doc["stages"].values():
            st["started_at"] = f"2026-09-{n + 1:02d}T00:00:00Z"
        mf.write_text(json.dumps(doc), encoding="utf-8")
    with client(tcfg) as c:
        login(c)
        rng = c.get("/api/reading/khaithi").json()[0]["ranges"]
        assert [(r["from"], r["to"], r["posts"]) for r in rng] == [(1, 10, 10), (11, 20, 2)]
        b = c.get("/api/reading/khaithi/_single?from=1&to=10").json()
        assert b["title"] == "Video lẻ · Tập 1–10"
        assert [s["paragraphs"][0][0]["text"] for _, s in sections(b)][:3] == ["bài 11", "bài 10", "bài 9"]
        b2 = c.get("/api/reading/khaithi/_single?from=11&to=20").json()
        assert [s["paragraphs"][0][0]["text"] for _, s in sections(b2)] == ["bài 1", "bài 0"]


def test_posted_tick_via_existing_route(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        s = sections(c.get(f"/api/reading/khaithi/{PL}?from=21&to=30").json())[0][1]
        assert s["posted"] is False
        r = c.post(f"/api/episodes/{s['episode_id']}/posts/{s['clip_id']}/posted", json={"value": True})
        assert r.status_code == 200 and r.json()["posted"] is True
        assert sections(c.get(f"/api/reading/khaithi/{PL}?from=21&to=30").json())[0][1]["posted"] is True
        tab = {p["clip_id"]: p["posted"] for p in c.get(f"/api/episodes/{VID}/posts").json()["posts"]}
        assert tab["k01"] is True


def test_edit_shows_in_library(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        add_posts(tcfg, VID2, [("k01", ["Đã sửa."], None, False)])
        b = c.get(f"/api/reading/khaithi/{PL}?from=1&to=10").json()
        assert sections(b)[0][1]["paragraphs"][0][0]["text"] == "Đã sửa."


def test_page_route(tcfg):
    setup_book(tcfg)
    with client(tcfg) as c:
        login(c)
        r = c.get(f"/sutras/khaithi/{PL}?from=1&to=10")
        assert r.status_code == 200 and 'data-page="reader"' in r.text
        assert c.get("/sutras/khaithi/_single").status_code == 200
        assert c.get("/sutras/khaithi/PLunknown000000").status_code == 404
        assert c.get("/sutras/khaithi/edit").status_code == 404  # not the sutra editor of a slug "khaithi"


def test_static_ui():
    js = (STATIC / "sutra.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js
    for token in ("/api/reading/khaithi", "sutra:pos:kt:", "Đã đăng ✓", "Short đã đổi", "execCommand", "/posted", "sutra:tab"):
        assert token in js
    lib = (STATIC / "sutras.html").read_text(encoding="utf-8")
    assert 'id="tab-sutras"' in lib and 'id="tab-kt"' in lib and "Khai thị" in lib and 'id="kt-list"' in lib
