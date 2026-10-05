"""CP8.30 P5c / P5d: keyword image search (known sites + Google), candidate filtering (sha256, dHash), add to the
library, re-deal of images. No network: a fake opener serves canned pages / images; ffmpeg decodes the tiny synthetic
PNGs for the perceptual hash."""

from __future__ import annotations

import io
import json
import shutil
import socket
import urllib.error
import zlib
import struct
from pathlib import Path

import pytest

from auto_short.post import dhash, fetch, images, imgsearch, redistribute, store

HOST = "example.test"
KEY, CX = "SECRET-KEY-123", "cx-456"


def _public(_host, port, **_kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def png_pattern(w: int, h: int, seed: int, pad: int = 0) -> bytes:
    """RGB PNG of a deterministic, size-independent pattern (8x8 blocks chosen by ``seed``); ``pad`` px of flat border."""
    import hashlib
    cells = list(hashlib.sha512(str(seed).encode()).digest())  # 64 values

    def row_bytes(cy: int | None) -> bytes:  # None = a padding row
        out = bytearray()
        for x in range(w):
            inside = cy is not None and pad <= x < w - pad
            v = cells[cy * 8 + (x - pad) * 8 // (w - 2 * pad)] if inside else 255
            out += bytes((v, v, v))
        return b"\x00" + bytes(out)

    cache: dict = {}
    rows = []
    for y in range(h):
        cy = None if (y < pad or y >= h - pad) else (y - pad) * 8 // (h - 2 * pad)
        if cy not in cache:
            cache[cy] = row_bytes(cy)
        rows.append(cache[cy])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"".join(rows), 1)) + chunk(b"IEND", b"")


class _Resp:
    def __init__(self, body: bytes, ctype: str):
        self._b, self.headers = io.BytesIO(body), {"Content-Type": ctype}

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWeb:
    """``opener`` seam of :mod:`auto_short.post.fetch`: URL -> (content type, body); unknown -> HTTP 404."""

    def __init__(self, routes: dict[str, tuple[str, bytes]]):
        self.routes, self.requests = routes, []

    def __call__(self):
        return self

    def open(self, req, timeout=None):
        self.requests.append(req.full_url)
        url = req.full_url.split("?")[0] if "googleapis" not in req.full_url else req.full_url
        hit = self.routes.get(url)
        if hit is None:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
        return _Resp(hit[1], hit[0])


def html(*imgs: str, links: tuple[str, ...] = ()) -> tuple[str, bytes]:
    body = "".join(f'<a href="{l}">x</a>' for l in links) + "".join(f'<img src="{i}">' for i in imgs)
    return "text/html", body.encode()


@pytest.fixture
def lib(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    (d / "01.png").write_bytes(png_pattern(700, 700, seed=3))
    (d / "sources.tsv").write_text("01.png\thttps://x/1.png\n", encoding="utf-8")
    return d


SOURCES = [imgsearch.SourceEntry("index", [], f"https://{HOST}/idx", ["/bo-suu-tap/", "/hinh/"])]


def site_routes():
    a1, a2 = png_pattern(700, 700, 11), png_pattern(1000, 1000, 11)  # same picture, two sizes
    padded = png_pattern(900, 700, 11, pad=100)  # same picture on a padded background
    b = png_pattern(800, 800, 22)
    small = png_pattern(300, 300, 33)
    lib_other_size = png_pattern(1200, 1200, 3)  # same picture as the library's 01.png
    pages = {
        f"https://{HOST}/idx": html(links=("/bo-suu-tap/tay-phuong-tam-thanh", "/bo-suu-tap/dai-the-chi")),
        f"https://{HOST}/bo-suu-tap/tay-phuong-tam-thanh": html(
            "https://cdn.test/a1.png", "https://cdn.test/a1-p-500.png", "https://cdn.test/logo.svg",
            "https://cdn.test/small.png", "https://cdn.test/b.png", "https://cdn.test/a1-copy.png",
            "https://cdn.test/page-banner.png", links=("/hinh/tay-phuong-tam-thanh-01", "/hinh/other-01")),
        f"https://{HOST}/hinh/tay-phuong-tam-thanh-01": html("https://cdn.test/a2.png", "https://cdn.test/pad.png",
                                                             "https://cdn.test/lib2.png", "https://cdn.test/n--thumb.png"),
        f"https://{HOST}/bo-suu-tap/dai-the-chi": html("https://cdn.test/never.png"),
        "https://cdn.test/a1.png": ("image/png", a1), "https://cdn.test/a1-copy.png": ("image/png", a1),
        "https://cdn.test/a2.png": ("image/png", a2), "https://cdn.test/pad.png": ("image/png", padded),
        "https://cdn.test/b.png": ("image/png", b), "https://cdn.test/small.png": ("image/png", small),
        "https://cdn.test/lib2.png": ("image/png", lib_other_size),
        "https://cdn.test/page-banner.png": ("image/png", png_pattern(2400, 700, 55)),
    }
    return pages


def search(lib, web, keyword="Tây Phương Tam Thánh", **kw):
    return imgsearch.run_search(keyword, lib, opener=web, resolver=_public, sources=SOURCES, **kw)


# --- helpers ---------------------------------------------------------------------------------------------------

def test_tokens_strip_diacritics():
    assert imgsearch.tokens("Tây Phương Tam Thánh") == ["tay", "phuong", "tam", "thanh"]
    assert imgsearch.tokens("A Di Đà Phật") == ["a", "di", "da", "phat"]
    assert imgsearch.matches(["tam", "thanh"], imgsearch.tokens("tay-phuong-tam-thanh-01"))
    assert not imgsearch.matches(["tinh"], ["tam"]) and not imgsearch.matches([], ["x"])


def test_usable_image_url_maps_webflow_variant_and_rejects_other_types():
    assert imgsearch.usable_image_url("https://c/x/abc-p-800.jpeg") == "https://c/x/abc.jpeg"
    assert imgsearch.usable_image_url("https://c/x/abc.png") == "https://c/x/abc.png"
    assert imgsearch.usable_image_url("https://c/x/logo.svg") is None
    assert imgsearch.usable_image_url("https://c/x/a.webp") is None


def test_dhash_same_picture_other_size_and_padding_is_near_different_picture_is_not():
    a1, a2, pad = (png_pattern(700, 700, 11), png_pattern(1000, 1000, 11), png_pattern(900, 700, 11, pad=100))
    h1, h2, hp, hb = (dhash.dhash(x) for x in (a1, a2, pad, png_pattern(800, 800, 22)))
    assert None not in (h1, h2, hp, hb)
    assert dhash.distance(h1, h2) <= dhash.NEAR_DUPLICATE_BITS
    assert dhash.distance(h1, hp) <= dhash.NEAR_DUPLICATE_BITS
    assert dhash.distance(h1, hb) > dhash.NEAR_DUPLICATE_BITS


def test_dhash_undecodable_is_none():
    assert dhash.dhash(b"not an image") is None


# --- AC1: site search + filtering ------------------------------------------------------------------------------

def test_site_search_filters_and_counts_reasons(lib):
    web = FakeWeb(site_routes())
    out = search(lib, web)
    # matched collection page + its sub-page only; the "dai-the-chi" collection and "other-01" are not followed
    assert f"https://{HOST}/bo-suu-tap/dai-the-chi" not in web.requests
    assert f"https://{HOST}/hinh/other-01" not in web.requests
    assert "https://cdn.test/never.png" not in web.requests
    assert "https://cdn.test/a1-p-500.png" not in web.requests  # responsive variant mapped back, not fetched
    ids = {c["url"] for c in out.candidates}
    assert ids == {"https://cdn.test/a2.png", "https://cdn.test/b.png", "https://cdn.test/page-banner.png"}  # a2 is larger than a1
    assert out.skipped["nhỏ hơn 600 px"] == 1
    assert out.skipped["trùng trong lô"] == 1  # a1-copy
    assert out.skipped["gần giống ảnh khác trong lô"] == 2  # a1 replaced by larger a2, padded copy dropped
    assert out.skipped["gần giống ảnh trong thư viện"] == 1  # lib2 = library picture at another size
    assert "không tải được" not in out.skipped  # logo.svg is never a candidate (not JPEG/PNG by URL)
    banner = next(c for c in out.candidates if c["url"].endswith("page-banner.png"))
    assert banner["flag"]
    assert all(imgsearch.candidate_file(lib, out.search_id, c["id"], thumb=False) for c in out.candidates)
    assert not (lib / "page-banner.png").exists() and len(images.list_images(lib)) == 1  # library untouched
    assert any("Google" in n for n in out.notes)  # no key -> only the sites, said so
    assert out.skipped["ảnh xem trước / bìa của trang khác"] == 1 and "https://cdn.test/n--thumb.png" not in web.requests


def test_image_on_most_pages_is_site_chrome_and_dropped(lib):
    routes = site_routes()
    nav = "https://cdn.test/nav-ad.png"
    for url in list(routes):
        if url.startswith(f"https://{HOST}/") and url.endswith(("tam-thanh", "tam-thanh-01")):
            ctype, body = routes[url]
            routes[url] = (ctype, body + f'<img src="{nav}">'.encode())
    routes[f"https://{HOST}/idx"] = (routes[f"https://{HOST}/idx"][0], routes[f"https://{HOST}/idx"][1] + f'<img src="{nav}">'.encode())
    routes[nav] = ("image/png", png_pattern(900, 900, 99))
    web = FakeWeb(routes)
    out = search(lib, web)
    assert nav not in {c["url"] for c in out.candidates} and nav not in web.requests
    assert out.skipped["ảnh chung của trang (banner / logo)"] == 1


def test_exact_library_duplicate_is_skipped(lib):
    routes = site_routes()
    routes["https://cdn.test/lib2.png"] = ("image/png", (lib / "01.png").read_bytes())
    out = search(lib, FakeWeb(routes))
    assert out.skipped["trùng ảnh có trong thư viện"] == 1


def test_no_match_gives_note_not_error(lib):
    out = search(lib, FakeWeb(site_routes()), keyword="Địa Tạng")
    assert out.candidates == [] and any("không có bộ sưu tập khớp" in n for n in out.notes)


def test_empty_keyword_raises(lib):
    with pytest.raises(imgsearch.SearchError):
        search(lib, FakeWeb({}), keyword="  ")


# --- AC5: P13 on candidate downloads ---------------------------------------------------------------------------

def test_candidate_on_private_host_is_blocked(lib):
    routes = {f"https://{HOST}/idx": html(links=("/bo-suu-tap/tay-phuong-tam-thanh",)),
              f"https://{HOST}/bo-suu-tap/tay-phuong-tam-thanh": html("http://10.0.0.5/x.png"),
              "http://10.0.0.5/x.png": ("image/png", png_pattern(800, 800, 5))}

    def resolver(host, port, **kw):
        ip = "10.0.0.5" if host == "10.0.0.5" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    web = FakeWeb(routes)
    out = imgsearch.run_search("tay phuong tam thanh", lib, opener=web, resolver=resolver, sources=SOURCES)
    assert out.candidates == [] and out.skipped == {"không tải được": 1}
    assert "http://10.0.0.5/x.png" not in web.requests


# --- AC2: Google ------------------------------------------------------------------------------------------------

def google_items(*urls, w=1000, h=800):
    return json.dumps({"items": [{"link": u, "image": {"width": w, "height": h, "contextLink": "https://ctx/"}}
                                 for u in urls]}).encode()


def google_web(extra=None):
    q = "https://www.googleapis.com/customsearch/v1"
    routes = {"https://g.test/1.png": ("image/png", png_pattern(800, 800, 71)),
              "https://g.test/2.png": ("image/png", png_pattern(800, 800, 72))}
    routes.update(extra or {})
    web = FakeWeb(routes)
    inner = web.open

    def open_(req, timeout=None):
        if req.full_url.startswith(q):
            web.requests.append(req.full_url)
            return _Resp(google_items("https://g.test/1.png", "https://g.test/2.png", "https://g.test/3.png"),
                         "application/json")
        return inner(req, timeout)

    web.open = open_
    return web


def test_google_from_env_requires_both_vars(tmp_path):
    assert imgsearch.GoogleImageSource.from_env({}, state_path=tmp_path / "g.json") is None
    assert imgsearch.GoogleImageSource.from_env({imgsearch.ENV_KEY: KEY}, state_path=tmp_path / "g.json") is None
    assert imgsearch.GoogleImageSource.from_env({imgsearch.ENV_KEY: KEY, imgsearch.ENV_CX: CX},
                                                state_path=tmp_path / "g.json") is not None


def test_google_merged_with_sites_uses_image_search_parameters(lib, tmp_path):
    web = google_web(extra=site_routes())
    g = imgsearch.GoogleImageSource(KEY, CX, state_path=tmp_path / "g.json", opener=web, resolver=_public)
    out = imgsearch.run_search("Tây Phương Tam Thánh", lib, opener=web, resolver=_public, sources=SOURCES, google=g)
    gurl = next(u for u in web.requests if u.startswith("https://www.googleapis.com/customsearch/v1"))
    for part in ("searchType=image", f"cx={CX}", "q=T%C3%A2y+Ph%C6%B0%C6%A1ng+Tam+Th%C3%A1nh", "num=10"):
        assert part in gurl
    assert {"https://g.test/1.png", "https://g.test/2.png"} <= {c["url"] for c in out.candidates}
    assert out.skipped["không tải được"] >= 1  # g.test/3.png is a 404
    assert out.sources["google"] == 3
    assert g.used_today() == 1
    assert KEY not in json.dumps(out.to_dict())


def test_google_daily_limit_is_reported_and_sites_still_work(lib, tmp_path):
    web = google_web(extra=site_routes())
    g = imgsearch.GoogleImageSource(KEY, CX, state_path=tmp_path / "g.json", daily_limit=1, opener=web,
                                    resolver=_public, today=lambda: "2026-10-04")
    out1 = imgsearch.run_search("tay phuong tam thanh", lib, opener=web, resolver=_public, sources=SOURCES, google=g)
    out2 = imgsearch.run_search("tay phuong tam thanh", lib, opener=web, resolver=_public, sources=SOURCES, google=g)
    assert not any("Google" in n for n in out1.notes)
    assert any("hết 1 lượt" in n for n in out2.notes) and out2.candidates  # B still produced candidates
    g._today = lambda: "2026-10-05"  # next day: counter resets
    assert g.used_today() == 0


def test_google_error_never_leaks_key(lib, tmp_path):
    class Boom:
        def __call__(self):
            return self

        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(
                b'{"error": {"message": "API key not valid."}}'))

    g = imgsearch.GoogleImageSource(KEY, CX, state_path=tmp_path / "g.json", opener=Boom(), resolver=_public)
    with pytest.raises(imgsearch.GoogleError) as exc:
        g.find("x", 10)
    assert KEY not in str(exc.value) and "403" in str(exc.value)
    out = imgsearch.run_search("tay phuong tam thanh", lib, opener=FakeWeb(site_routes()), resolver=_public,
                               sources=SOURCES, google=g)
    assert KEY not in json.dumps(out.to_dict()) and any("Google" in n for n in out.notes)


def test_search_status_hides_secrets(tmp_path):
    from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "w"), render=RenderConfig(output_dir=tmp_path / "o"),
                 post=PostConfig(image_dir=tmp_path / "images"))
    assert imgsearch.search_status(cfg, environ={}) == {"google": {"enabled": False}}
    st = imgsearch.search_status(cfg, environ={imgsearch.ENV_KEY: KEY, imgsearch.ENV_CX: CX})
    assert st["google"]["enabled"] and KEY not in json.dumps(st) and CX not in json.dumps(st)


# --- AC3: add to library ----------------------------------------------------------------------------------------

def test_add_candidates_numbered_names_sources_and_idempotent(lib):
    out = search(lib, FakeWeb(site_routes()))
    assert len(out.candidates) == 3
    pick = [c["id"] for c in out.candidates[:2]]
    res = imgsearch.add_candidates(lib, out.search_id, pick)
    assert res["added"] == ["02.png", "03.png"] and res["duplicate"] == [] and res["missing"] == []
    lines = (lib / "sources.tsv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and all(len(l.split("\t")) == 2 for l in lines)
    assert lines[1].startswith("02.png\t") and lines[1].split("\t")[1] == out.candidates[0]["url"]
    assert not (lib / "04.png").exists()  # the third (not picked) stays out
    again = imgsearch.add_candidates(lib, out.search_id, pick)
    assert again["added"] == [] and sorted(again["duplicate"]) == ["02.png", "03.png"]
    assert len(images.list_images(lib)) == 3
    assert imgsearch.add_candidates(lib, out.search_id, ["0" * 16])["missing"] == ["0" * 16]
    assert imgsearch.add_candidates(lib, "bad/../id", pick)["missing"] == pick


def test_next_name_keeps_padding(tmp_path):
    d = tmp_path / "i"
    d.mkdir()
    assert imgsearch.next_name(d) == "01"
    for n in ("08.jpg", "99.jpg", "129.jpg"):
        (d / n).write_bytes(png_pattern(600, 600, 1))
    assert imgsearch.next_name(d) == "130"


def test_candidate_file_refuses_traversal(lib):
    out = search(lib, FakeWeb(site_routes()))
    cid = out.candidates[0]["id"]
    assert imgsearch.candidate_file(lib, out.search_id, cid, thumb=False).is_file()
    assert imgsearch.candidate_file(lib, "../" + out.search_id, cid, thumb=False) is None
    assert imgsearch.candidate_file(lib, out.search_id, "../../etc/passwd", thumb=False) is None


def test_purge_old_removes_only_expired_search_dirs(lib):
    out = search(lib, FakeWeb(site_routes()))
    cdir = imgsearch.cache_dir(lib)
    assert imgsearch.purge_old(cdir, 6, now=out_time() + 3600) == 0
    assert imgsearch.purge_old(cdir, 6, now=out_time() + 7 * 3600) == 1
    assert not (cdir / out.search_id).exists() and (cdir / "library-hashes.json").exists()


def out_time():
    import time
    return time.time()


# --- AC4: re-deal -----------------------------------------------------------------------------------------------

NOW = "2026-10-04T00:00:00Z"
SHA = "a" * 64


def write_posts(work: Path, eid: str, entries: list[tuple[str, str | None, bool]]):
    posts = [{"clip_id": cid, "candidate_id": "c1", "source_sha256": SHA, "paragraphs": ["x."], "origin": "ai",
              "image": img, "link": None, "posted_at": NOW if posted else None, "updated_at": NOW}
             for cid, img, posted in entries]
    (work / eid).mkdir(parents=True, exist_ok=True)
    store.write(work / eid / store.POSTS_NAME, {"schema_version": 1, "episode_id": eid, "posts": posts})


def read(work: Path, eid: str):
    return {e["clip_id"]: e for e in store.read_posts(work / eid / store.POSTS_NAME, eid)["posts"]}


def test_redistribute_keeps_posted_spreads_evenly_and_no_repeat_in_video(tmp_path):
    work = tmp_path / "work"
    library = [f"{n:02d}.jpg" for n in range(1, 7)]
    write_posts(work, "vidA", [("k01", "01.jpg", True), ("k02", "01.jpg", False), ("k03", None, False),
                               ("k04", "02.jpg", False)])
    write_posts(work, "vidA.kt", [("t01", "01.jpg", False), ("t02", "01.jpg", False)])
    write_posts(work, "vidB", [(f"k{n:02d}", "01.jpg", False) for n in range(1, 5)])
    before_a = read(work, "vidA")
    p = redistribute.plan(work, library)
    assert p.posted == 1 and p.unposted == 9 and p.skipped_broken == []
    bdir = redistribute.apply(work, p, now=__import__("datetime").datetime(2026, 10, 4, 12, 0, 0))
    after_a, after_kt, after_b = read(work, "vidA"), read(work, "vidA.kt"), read(work, "vidB")
    assert after_a["k01"] == before_a["k01"]  # posted: untouched
    for e in list(after_a.values()) + list(after_kt.values()) + list(after_b.values()):
        assert e["updated_at"] == NOW and e["source_sha256"] == SHA and e["paragraphs"] == ["x."]  # nothing else changed
    video_a = [e["image"] for e in list(after_a.values()) + list(after_kt.values())]
    assert len(video_a) == len(set(video_a)) == 6  # Short + khai thị of one video never repeat an image
    counts = {}
    for e in list(after_a.values()) + list(after_kt.values()) + list(after_b.values()):
        counts[e["image"]] = counts.get(e["image"], 0) + 1
    assert max(counts.values()) - min(counts.values()) <= 1 and p.spread() <= 1
    assert (bdir / "vidA.json").is_file() and json.loads((bdir / "vidA.json").read_text())["posts"][1]["image"] == "01.jpg"
    # idempotent: a second plan on the result changes nothing
    assert redistribute.plan(work, library).changed == 0


def test_redistribute_is_deterministic_and_prunes_backups(tmp_path):
    from datetime import datetime
    work = tmp_path / "work"
    write_posts(work, "v1", [(f"k{n}", None, False) for n in range(5)])
    lib = ["a.jpg", "b.jpg", "c.jpg"]
    p1, p2 = redistribute.plan(work, lib), redistribute.plan(work, lib)
    assert p1.changes == p2.changes
    for n in range(7):
        write_posts(work, "v1", [(f"k{m}", "z.jpg", False) for m in range(5)])
        redistribute.apply(work, redistribute.plan(work, lib), now=datetime(2026, 10, 4, 12, 0, n))
    assert len(list((work / "_post-backups").iterdir())) == redistribute.KEEP_BACKUPS


def test_redistribute_broken_file_skipped_and_empty_library_noop(tmp_path):
    work = tmp_path / "work"
    write_posts(work, "good", [("k1", None, False)])
    (work / "bad").mkdir()
    (work / "bad" / "posts.json").write_text("{nope", encoding="utf-8")
    p = redistribute.plan(work, ["a.jpg"])
    assert p.skipped_broken == ["bad"] and p.changes == {"good": {"k1": "a.jpg"}}
    assert redistribute.plan(work, []).changed == 0
