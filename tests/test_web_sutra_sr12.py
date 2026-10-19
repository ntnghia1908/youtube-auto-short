"""SR1.2: Đọc Kinh add / edit / delete / import routes (S6) + editor assets."""

import hashlib
import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
docx = pytest.importorskip("docx")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.sutra.store import SutraStore  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
TEXT = "= Kinh Thử\n@ Chính kinh\n# Phẩm một\nDòng a[^1]\n[^1]: chú\n"
STATIC = Path(app_mod.STATIC_DIR)


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


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_requires_login(c, store):
    slug = store.create(TEXT)
    assert c.post("/api/sutras", json={"text": TEXT}).status_code == 401
    assert c.post("/api/sutras/import?name=a.txt", content=b"x").status_code == 401
    assert c.put(f"/api/sutras/{slug}", json={"text": TEXT, "sha256": "x"}).status_code == 401
    assert c.delete(f"/api/sutras/{slug}").status_code == 401
    for url in ("/sutras/new", f"/sutras/{slug}/edit"):
        assert c.get(url).status_code == 303
    assert store.exists(slug)


def test_create_and_dedupe(lc, store):
    r = lc.post("/api/sutras", json={"text": TEXT})
    assert r.status_code == 201 and r.json() == {"slug": "kinh-thu"}
    assert lc.post("/api/sutras", json={"text": TEXT}).json() == {"slug": "kinh-thu-2"}
    assert store.text("kinh-thu")["text"] == TEXT


def test_dry_run_writes_nothing(lc, store):
    r = lc.post("/api/sutras?dry_run=1", json={"text": TEXT})
    assert r.status_code == 200 and r.json()["title"] == "Kinh Thử" and r.json()["groups"][0]["sections"][0]["id"] == "s1"
    assert not store.root.exists() or not any(store.root.iterdir())
    r = lc.post("/api/sutras?dry_run=1", json={"text": "chữ lạc\n"})
    assert r.status_code == 400 and r.json()["errors"]
    assert not store.root.exists() or not any(store.root.iterdir())


def test_parse_errors_are_400_with_lines(lc, store):
    r = lc.post("/api/sutras", json={"text": "= T\nlạc\n# M\n"})
    body = r.json()
    assert r.status_code == 400 and body["detail"]
    assert {"line": 2, "message": body["errors"][0]["message"]} in body["errors"]
    assert any(e["line"] == 3 for e in body["errors"])  # empty section
    assert not store.root.exists() or not any(store.root.iterdir())


def test_bad_json_bodies(lc):
    assert lc.post("/api/sutras", content=b"{nope").status_code == 422
    assert lc.post("/api/sutras", json=[1]).status_code == 422
    assert lc.post("/api/sutras", json={"text": 5}).status_code == 422
    assert lc.put("/api/sutras/x", json={"text": TEXT}).status_code == 422


def test_json_body_over_3mb_is_413(lc):
    big = b'{"text": "' + b"a" * (3 * 1024 * 1024 + 10) + b'"}'
    assert lc.post("/api/sutras", content=big).status_code == 413
    assert lc.post("/api/sutras?dry_run=1", content=big).status_code == 413


def test_put_ok_conflict_and_errors(lc, store):
    slug = store.create(TEXT)
    new = "= Kinh Mới\n# Phẩm\nDòng\n"
    r = lc.put(f"/api/sutras/{slug}", json={"text": new, "sha256": "0" * 64})
    assert r.status_code == 409 and r.json()["detail"]
    assert store.text(slug)["text"] == TEXT
    r = lc.put(f"/api/sutras/{slug}", json={"text": new, "sha256": sha(TEXT)})
    assert r.status_code == 200 and r.json() == {"slug": slug, "sha256": sha(new)}
    assert lc.get(f"/api/sutras/{slug}/text").json() == {"text": new, "sha256": sha(new)}
    assert lc.get("/api/sutras").json()[0]["title"] == "Kinh Mới" and slug == lc.get("/api/sutras").json()[0]["slug"]
    r = lc.put(f"/api/sutras/{slug}", json={"text": "x\n", "sha256": sha(new)})
    assert r.status_code == 400 and r.json()["errors"]
    assert lc.put("/api/sutras/nope", json={"text": new, "sha256": "a"}).status_code == 404


def test_put_keeps_recitations(lc, store):
    slug = store.create(TEXT)
    store.add_recitation(slug)
    lc.put(f"/api/sutras/{slug}", json={"text": "= K\n# M\nx\n", "sha256": sha(TEXT)})
    assert store.get(slug)["recitations"]["total"] == 1


def test_delete(lc, store):
    slug = store.create(TEXT)
    store.add_recitation(slug)
    assert lc.delete(f"/api/sutras/{slug}").status_code == 200
    assert not (store.root / slug).exists()
    assert lc.delete(f"/api/sutras/{slug}").status_code == 404
    assert lc.delete("/api/sutras/..%2Fx").status_code == 404
    assert lc.delete("/api/sutras/Bad_Slug").status_code == 404


def test_pages_and_route_order(lc, store):
    r = lc.get("/sutras/new")
    assert r.status_code == 200 and 'data-page="edit"' in r.text and r.headers["cache-control"] == "no-cache"
    slug = store.create(TEXT)
    r = lc.get(f"/sutras/{slug}/edit")
    assert r.status_code == 200 and 'data-page="edit"' in r.text
    assert lc.get("/sutras/nope/edit").status_code == 404
    assert lc.get(f"/sutras/{slug}").text.count('data-page="reader"') == 1
    # a sutra titled "New" must not shadow /sutras/new
    assert lc.post("/api/sutras", json={"text": "= New\n# a\nx\n"}).json() == {"slug": "new-2"}


def test_import_txt_and_docx(lc):
    r = lc.post("/api/sutras/import?name=a.txt", content="Kinh Đại\nPHẨM 1\nx\n".encode("utf-8"))
    assert r.status_code == 200 and r.json() == {"text": "= Kinh Đại\n\n# PHẨM 1\nx\n", "warnings": []}
    d = docx.Document()
    d.add_paragraph("Kinh Word")
    d.add_heading("Mục", level=1)
    d.add_paragraph("Dòng")
    buf = io.BytesIO()
    d.save(buf)
    r = lc.post("/api/sutras/import?name=%E2%80%A6k.docx", content=buf.getvalue())
    assert r.status_code == 200 and r.json()["text"] == "= Kinh Word\n\n# Mục\nDòng\n"


def test_import_errors(lc):
    assert lc.post("/api/sutras/import", content=b"x").status_code == 422
    assert lc.post("/api/sutras/import?name=a.pdf", content=b"x").status_code == 422  # .pdf is SR1.3: not a PDF
    assert lc.post("/api/sutras/import?name=a.doc", content=b"x").status_code == 415
    assert lc.post("/api/sutras/import?name=a.docx", content=b"junk").status_code == 422
    assert lc.post("/api/sutras/import?name=a.txt", content=b"\xff\xfe\x00").status_code == 422
    assert lc.post("/api/sutras/import?name=a.txt", content=b"a" * (5 * 1024 * 1024 + 1)).status_code == 413


def test_editor_assets():
    html = (STATIC / "sutra-edit.html").read_text(encoding="utf-8")
    assert 'accept=".txt,.docx,.pdf"' in html and "sutra.js" in html and "ed-text" in html
    assert "Thêm bộ kinh" in (STATIC / "sutras.html").read_text(encoding="utf-8")
    reader = (STATIC / "sutra.html").read_text(encoding="utf-8")
    assert "menu-edit" in reader and "menu-delete" in reader
    js = (STATIC / "sutra.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "dry_run=1" in js and "lịch sử tụng" in js.lower()
