"""SR1.3: ``POST /api/sutras/import`` for ``.pdf`` (limits, child process, temp file, timeout kill)."""

import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pypdf")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_short.sutra import importer, markup
from auto_short.sutra import web as sutra_web
from auto_short.sutra.store import SutraStore

from sutra_pdf_helpers import make_pdf, sample_pdf

STATIC = Path(importer.__file__).resolve().parents[1] / "web" / "static"


@pytest.fixture
def env(tmp_path):
    store = SutraStore(tmp_path / "work" / "_sutras")
    app = FastAPI()
    app.include_router(sutra_web.router(store, STATIC))
    return TestClient(app), store


def tmp_files(store):
    d = store.root / ".tmp"
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def post(client, name, body):
    return client.post("/api/sutras/import", params={"name": name}, content=body)


def test_pdf_import_returns_s2_text_and_leaves_no_temp_file(env):
    client, store = env
    r = post(client, "Kinh_Thu_Nghiem.PDF", sample_pdf())
    assert r.status_code == 200
    doc = r.json()
    assert doc["text"].startswith("= Kinh Thu Nghiem\n")
    assert "# CHAPTER ONE" in doc["text"] and "RUNNING HEADER" not in doc["text"]
    assert "cần soát lại" in doc["warnings"][0]
    assert any("tên bộ kinh" in w for w in doc["warnings"])
    markup.parse(doc["text"])
    assert tmp_files(store) == []
    assert store.list() == []  # `.tmp` is not a sutra, and nothing was saved


def test_store_list_ignores_tmp_directory(env):
    _, store = env
    (store.root / ".tmp").mkdir(parents=True)
    (store.root / ".tmp" / "x.pdf").write_bytes(b"x")
    assert store.list() == []


def test_unsupported_extension_is_415_and_too_big_is_413(env):
    client, _ = env
    assert post(client, "a.exe", b"x").status_code == 415
    assert post(client, "a.PDF.exe", sample_pdf()).status_code == 415
    big = post(client, "a.pdf", b"%PDF-" + b"0" * (importer.MAX_PDF_BYTES + 1))
    assert big.status_code == 413 and "30 MB" in big.json()["detail"]
    assert post(client, "a.txt", b"a" * (importer.MAX_BYTES + 1)).status_code == 413
    ok = post(client, "a.pdf", b"%PDF-" + b"0" * (importer.MAX_BYTES + 1))  # above the 5 MB txt limit is fine for pdf
    assert ok.status_code == 422


def test_txt_and_docx_routes_still_work(env):
    client, _ = env
    r = post(client, "a.txt", "Kinh Thử\n\nPHẨM MỘT\nDòng\n".encode("utf-8"))
    assert r.status_code == 200 and r.json()["text"].startswith("= Kinh Thử")


@pytest.mark.parametrize("name,body,needle", [
    ("a.pdf", b"this is not a pdf at all", "không phải PDF"),
    ("a.pdf", b"%PDF-1.4\nbroken broken broken\n", "hỏng"),
    ("scan.pdf", None, "lớp chữ"),
])
def test_bad_pdf_is_422_and_temp_file_removed(env, name, body, needle):
    client, store = env
    r = post(client, name, make_pdf([[], []]) if body is None else body)
    assert r.status_code == 422 and needle in r.json()["detail"]
    assert tmp_files(store) == []


def test_timeout_is_504_child_is_killed_and_temp_file_removed(env, monkeypatch):
    client, store = env
    code = "import os, time; open('child.pid', 'w').write(str(os.getpid())); time.sleep(60)"
    monkeypatch.setattr(importer, "_child_cmd", lambda path: [sys.executable, "-c", code])
    monkeypatch.setattr(importer, "PDF_TIMEOUT_S", 1)
    t0 = time.time()
    r = post(client, "slow.pdf", sample_pdf())
    assert r.status_code == 504 and time.time() - t0 < 20
    pid_file = store.root / ".tmp" / "child.pid"
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # reaped: run() killed it and waited
    pid_file.unlink()
    assert tmp_files(store) == []


def test_child_crash_or_garbage_output_is_422(env, monkeypatch):
    client, store = env
    for code in ("import sys; sys.exit(3)", "print('not json')", "print('[1, 2]')",
                 "import json; print(json.dumps({'text': 5, 'warnings': []}))"):
        monkeypatch.setattr(importer, "_child_cmd", lambda path, code=code: [sys.executable, "-c", code])
        r = post(client, "x.pdf", sample_pdf())
        assert r.status_code == 422, code
    assert tmp_files(store) == []


def test_child_error_json_status_is_passed_on(env, monkeypatch):
    client, _ = env
    code = "import json; print(json.dumps({'error': 'PDF quá 1000 trang', 'status': 422}))"
    monkeypatch.setattr(importer, "_child_cmd", lambda path: [sys.executable, "-c", code])
    r = post(client, "x.pdf", sample_pdf())
    assert r.status_code == 422 and r.json()["detail"] == "PDF quá 1000 trang"


def test_child_gets_the_pdf_path_and_stale_temp_files_are_swept(env, monkeypatch, tmp_path):
    client, store = env
    tmp = store.root / ".tmp"
    tmp.mkdir(parents=True)
    old = tmp / "old.pdf"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    seen = []
    real = importer._child_cmd

    def spy(path):
        seen.append(Path(path))
        assert Path(path).read_bytes().startswith(b"%PDF-") and Path(path).parent == tmp
        return real(path)

    monkeypatch.setattr(importer, "_child_cmd", spy)
    assert post(client, "a.pdf", sample_pdf()).status_code == 200
    assert seen and not old.exists() and tmp_files(store) == []


def test_child_runs_isolated_and_imports_this_package():
    cmd = importer._child_cmd(Path("/nonexistent.pdf"))
    assert cmd[:3] == [sys.executable, "-I", "-c"] and cmd[4] == str(importer._SRC_DIR)
    assert (importer._SRC_DIR / "auto_short" / "sutra" / "pdf.py").is_file()
