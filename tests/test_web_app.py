import io
import json
import threading
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.pipeline import PreflightError  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.auth import COOKIE_NAME, SECRET_FILE  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "đúng-mật-khẩu"
VID = "tHtxw6ykUmM"


@pytest.fixture
def wcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"), web=WebConfig(session_days=30))


@pytest.fixture(autouse=True)
def _fast_login_delay(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.05)


def make_client(cfg, *, password=PW, preflight=lambda c: None, pipeline=None, calls=None):
    app = app_mod.create_app(cfg, password, preflight=preflight,
                             pipeline=pipeline or fake_pipeline(calls if calls is not None else []))
    return TestClient(app, follow_redirects=False)


def login(client, password=PW):
    return client.post("/login", data={"password": password, "next": "/"})


# --- W2 auth -----------------------------------------------------------------------------------------

def test_unauthenticated_requests(wcfg):
    with make_client(wcfg) as c:
        r = c.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login?next=%2F"
        r = c.get(f"/episodes/{VID}")
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=%2Fepisodes%2F")
        for path in ("/api/episodes", f"/api/episodes/{VID}", f"/files/{VID}/k01.mp4", f"/files/{VID}/shorts.zip",
                     f"/files/{VID}/k01.mp4?download=1"):
            assert c.get(path).status_code == 401, path
        assert c.get("/static/app.js").status_code == 303
        assert c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}"}).status_code == 401
        assert c.get("/login").status_code == 200
        assert c.get("/static/style.css").status_code == 200


def test_login_wrong_then_right(wcfg):
    with make_client(wcfg) as c:
        t0 = time.monotonic()
        r = login(c, "sai")
        assert r.status_code == 401 and time.monotonic() - t0 >= 0.05
        assert "set-cookie" not in r.headers and "Sai mật khẩu" in r.text
        assert c.get("/api/episodes").status_code == 401

        r = c.post("/login", data={"password": PW, "next": f"/episodes/{VID}"})
        assert r.status_code == 303 and r.headers["location"] == f"/episodes/{VID}"
        cookie = r.headers["set-cookie"]
        assert f"{COOKIE_NAME}=" in cookie and "Max-Age=2592000" in cookie
        assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Path=/" in cookie
        assert c.get("/api/episodes").status_code == 200
        assert c.get("/").status_code == 200
        assert c.get("/login").status_code == 303  # already logged in

        r = c.post("/logout")
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert f'{COOKIE_NAME}=""' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
        assert c.get("/api/episodes").status_code == 401


def test_login_json_and_open_redirect(wcfg):
    with make_client(wcfg) as c:
        assert c.post("/login", json={"password": "x"}).status_code == 401
        for nxt in ("//evil.example/", "https://evil.example/", "/\\evil", "javascript:x"):
            r = c.post("/login", data={"password": PW, "next": nxt})
            assert r.status_code == 303 and r.headers["location"] == "/", nxt
        assert c.post("/login", json={"password": PW}).json() == {"ok": True}


def test_cookie_survives_restart_and_forgery_rejected(wcfg):
    with make_client(wcfg) as c:
        login(c)
        token = c.cookies[COOKIE_NAME]
    assert (Path(wcfg.workspace.dir) / SECRET_FILE).is_file()
    with make_client(wcfg) as c2:  # server restart: same secret file
        c2.cookies.set(COOKIE_NAME, token)
        assert c2.get("/api/episodes").status_code == 200
        v, exp, sig = token.split(".")
        for forged in (f"{v}.{int(exp) + 86400}.{sig}", f"{v}.{exp}.{'0' * 64}", "garbage"):
            c2.cookies.set(COOKIE_NAME, forged)
            assert c2.get("/api/episodes").status_code == 401
    with make_client(wcfg, password="mật khẩu mới") as c3:  # password changed -> old cookie invalid
        c3.cookies.set(COOKIE_NAME, token)
        assert c3.get("/api/episodes").status_code == 401


# --- W3/W4/W7 submit ---------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://www.youtube.com/playlist?list=PL1", "https://vimeo.com/1", "not a url",
                                 "/etc/passwd", f"https://evil.example/watch?v={VID}"])
def test_submit_invalid_url_422_no_job(wcfg, url):
    calls = []
    with make_client(wcfg, calls=calls) as c:
        login(c)
        r = c.post("/api/episodes", json={"url": url})
        assert r.status_code == 422 and r.json()["detail"]
        assert c.app.state.runner.jobs() == [] and calls == []
        assert c.post("/api/episodes", json={}).status_code == 422


def test_submit_preflight_error_still_queues_job(wcfg):
    # FIX-ollama-wait O4 (was: 503 + no job): the link is accepted; the ai lane reports / waits for the GPU
    def bad(cfg):
        raise PreflightError("model 'x' ([selection] model) is not available")

    with make_client(wcfg, preflight=bad) as c:
        login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}"})
        assert r.status_code == 202 and r.json()["job"]["kind"] == "pipeline"
        runner = c.app.state.runner
        assert runner.wait_idle(10)
        job = runner.latest(VID)
        assert job.status == "failed" and job.error.startswith("ollama preflight: model 'x'")


def test_submit_runs_pipeline_and_episode_view(wcfg):
    calls = []
    with make_client(wcfg, calls=calls) as c:
        login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}?si=R1TwdI4gh0sPcVHB",
                                          "series": " Kinh A ", "episode": "", "kinds": ["short"]})
        assert r.status_code == 202
        body = r.json()
        assert body["created"] is True and body["episode_id"] == VID and body["job"]["kind"] == "pipeline"
        assert c.app.state.runner.wait_idle(10)
        assert calls[0][:2] == ("ingest", f"https://youtu.be/{VID}")  # si dropped
        titling = next(kw for stage, _, kw in calls if stage == "titling")
        assert titling["series"] == "Kinh A" and titling["episode"] is None

        d = c.get(f"/api/episodes/{VID}").json()
        assert [s["status"] for s in d["stages"]] == ["done"] * 6
        assert [s["stage"] for s in d["stages"]] == ["ingest", "transcript", "analysis", "selection", "titling",
                                                     "render"]
        assert d["job"]["status"] == "done" and d["job"]["summary"] == "2/2 Shorts (2 encoded, 0 reused)"
        assert [s["stage"] for s in d["job"]["stages"]] == [s["stage"] for s in d["stages"]]
        assert any("start pipeline job" in line for line in d["job"]["logs"])
        assert d["title"] == "Kinh Vô Lượng Thọ tập 3" and d["source_url"] == f"https://youtu.be/{VID}"
        assert [s["clip_id"] for s in d["shorts"]] == ["k01", "k02"] and d["rendered"] == 2
        s1 = d["shorts"][0]
        assert s1["title"] == {"text": "Tiêu đề k01", "origin": "ai", "display_lines": ["Tiêu đề k01"]}
        assert s1["editable"] is False and s1["rendering"] is False  # fake episode: no titles.json
        assert s1["video_url"] == f"/files/{VID}/k01.mp4?v={'0' * 12}"
        assert s1["download_url"] == f"/files/{VID}/k01.mp4?download=1"
        assert d["zip_url"] == f"/files/{VID}/shorts.zip"

        lst = c.get("/api/episodes").json()["episodes"]
        assert lst[0]["id"] == VID and lst[0]["shorts"] == 2 and lst[0]["stages_done"] == 6
        assert lst[0]["job"]["status"] == "done" and "logs" not in lst[0]["job"]

        # AC6: resubmit a finished episode -> a new job (the real pipeline skips every stage).
        r = c.post("/api/episodes", json={"url": f"https://www.youtube.com/watch?v={VID}", "kinds": ["short"]})
        assert r.status_code == 202 and r.json()["created"] is True
        assert c.app.state.runner.wait_idle(10)


def test_resubmit_while_running_is_not_duplicated(wcfg):
    gate, calls = threading.Event(), []
    with make_client(wcfg, pipeline=fake_pipeline(calls, gate=gate)) as c:
        login(c)
        first = c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}", "kinds": ["short"]})
        assert first.status_code == 202
        for url in (f"https://youtu.be/{VID}?si=x", f"https://m.youtube.com/watch?v={VID}"):
            again = c.post("/api/episodes", json={"url": url, "kinds": ["short"]})
            assert again.status_code == 200 and again.json()["created"] is False
            assert again.json()["job"]["id"] == first.json()["job"]["id"]
        d = c.get(f"/api/episodes/{VID}").json()
        assert d["job"]["status"] in ("queued", "running")
        gate.set()
        assert c.app.state.runner.wait_idle(10)
        assert len(c.app.state.runner.jobs()) == 1
        assert sum(1 for stage, *_ in calls if stage == "ingest") == 1


def test_failed_pipeline_reported(wcfg):
    with make_client(wcfg, pipeline=fake_pipeline([], fail_stage="transcript")) as c:
        login(c)
        c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}"})
        assert c.app.state.runner.wait_idle(10)
        job = c.get(f"/api/episodes/{VID}").json()["job"]
        assert job["status"] == "failed" and job["error"] == "transcript: transcript boom"


def test_unknown_episode_404(wcfg):
    with make_client(wcfg) as c:
        login(c)
        for eid in ("nope", "..", ".hidden", "a" * 200, "x%2F..%2Fy"):
            assert c.get(f"/api/episodes/{eid}").status_code == 404, eid
        assert c.get("/episodes/..%2F..").status_code == 404


# --- files: Range, download, zip, traversal -----------------------------------------------------------

def test_files_range_download_and_zip(wcfg):
    # CP8.5 X1: names from titles.json header.fields.episode + the title in the file (? and " dropped)
    files = write_episode(wcfg, VID, titles={"k01": "Đánh mắng trẻ là có tội không?", "k02": 'Chữ "hiếu" là gì'})
    (wcfg.workspace.dir / VID / "titles.json").write_text(
        json.dumps({"header": {"fields": {"episode": "29"}}}), encoding="utf-8")
    k01, k02 = "T29_S01_Đánh mắng trẻ là có tội không.mp4", "T29_S02_Chữ hiếu là gì.mp4"
    with make_client(wcfg) as c:
        login(c)
        r = c.get(f"/files/{VID}/k01.mp4")
        assert r.status_code == 200 and r.content == files["k01"] and r.headers["content-type"] == "video/mp4"
        assert r.headers["accept-ranges"] == "bytes"
        assert "attachment" not in r.headers.get("content-disposition", "")

        r = c.get(f"/files/{VID}/k01.mp4", headers={"Range": "bytes=10-19"})
        assert r.status_code == 206 and r.content == files["k01"][10:20]
        assert r.headers["content-range"] == f"bytes 10-19/{len(files['k01'])}"

        r = c.get(f"/files/{VID}/k02.mp4?download=1")
        assert r.status_code == 200 and r.content == files["k02"]
        assert r.headers["content-disposition"] == \
            "attachment; filename=\"T29_S02_Chu hieu la gi.mp4\"; filename*=UTF-8''" \
            "T29_S02_Ch%E1%BB%AF%20hi%E1%BA%BFu%20l%C3%A0%20g%C3%AC.mp4"
        assert c.get(f"/api/episodes/{VID}").json()["shorts"][1]["download_name"] == k02

        r = c.get(f"/files/{VID}/shorts.zip")
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        assert r.headers["content-disposition"] == \
            "attachment; filename=\"Tap29_Shorts.zip\"; filename*=UTF-8''T%E1%BA%ADp29_Shorts.zip"
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert zf.testzip() is None
            assert zf.namelist() == [k01, k02]
            assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
            assert all(i.flag_bits & 0x800 for i in zf.infolist())  # UTF-8 names
            assert zf.read(k02) == files["k02"]


def test_files_rejects_unknown_and_traversal(wcfg, tmp_path):
    secret = tmp_path / "output" / "secret.mp4"
    extra = [{"clip_id": "k09", "status": "rendered", "file": "../secret.mp4", "sha256": "0" * 64},
             {"clip_id": "k10", "status": "rendered", "file": "/etc/passwd", "sha256": "0" * 64},
             {"clip_id": "k11", "status": "skipped", "file": None, "skip_reason": "untitled"}]
    write_episode(wcfg, VID, extra_shorts=extra)
    secret.write_bytes(b"secret")
    with make_client(wcfg) as c:
        login(c)
        for path in (f"/files/{VID}/k99.mp4", f"/files/{VID}/k09.mp4", f"/files/{VID}/k10.mp4",
                     f"/files/{VID}/k11.mp4", f"/files/{VID}/render_manifest.json", f"/files/{VID}/..%2Fsecret.mp4",
                     f"/files/{VID}/%2E%2E.mp4", "/files/..%2Foutput/secret.mp4", f"/files/nope/k01.mp4",
                     f"/files/{VID}/k01.mp4%00"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert b"secret" not in r.content
        with zipfile.ZipFile(io.BytesIO(c.get(f"/files/{VID}/shorts.zip").content)) as zf:
            # no titles.json: <episode> = episode id; numbers = position among the 5 manifest entries
            assert zf.namelist() == [f"T{VID}_S01_Tiêu đề k01.mp4", f"T{VID}_S02_Tiêu đề k02.mp4"]
        d = c.get(f"/api/episodes/{VID}").json()
        skipped = next(s for s in d["shorts"] if s["clip_id"] == "k11")
        assert skipped["video_url"] is None and skipped["skip_reason"] == "untitled"


@pytest.mark.parametrize("status", ["running", "failed", "stale"])
def test_previous_render_listed_while_render_not_done(wcfg, status):
    """A render run replaces files only at its commit and a failed run keeps the previous render (CP8.2 T5): the
    last render_manifest.json stays listed and served whatever the render stage status is."""
    files = write_episode(wcfg, VID, render_status=status)
    with make_client(wcfg) as c:
        login(c)
        d = c.get(f"/api/episodes/{VID}").json()
        assert d["render_status"] == status and [s["clip_id"] for s in d["shorts"]] == ["k01", "k02"]
        assert d["zip_url"] == f"/files/{VID}/shorts.zip"
        assert c.get(f"/files/{VID}/k01.mp4").content == files["k01"]


def test_no_render_manifest_no_shorts(wcfg):
    write_episode(wcfg, VID)
    (Path(wcfg.render.output_dir) / VID / "render_manifest.json").unlink()
    with make_client(wcfg) as c:
        login(c)
        d = c.get(f"/api/episodes/{VID}").json()
        assert d["shorts"] == [] and d["zip_url"] is None
        assert c.get(f"/files/{VID}/k01.mp4").status_code == 404
        assert c.get(f"/files/{VID}/shorts.zip").status_code == 404


def test_pages_served(wcfg):
    write_episode(wcfg, VID)
    with make_client(wcfg) as c:
        login(c)
        r = c.get("/")
        assert r.status_code == 200 and "Tạo Short" in r.text
        r = c.get(f"/episodes/{VID}")
        assert r.status_code == 200 and 'id="shorts"' in r.text
        assert c.get("/static/app.js").status_code == 200
        assert r.headers["x-frame-options"] == "DENY"
        assert c.get("/api/episodes").headers["cache-control"] == "no-store"


def test_session_days_config(wcfg):
    with make_client(replace(wcfg, web=WebConfig(session_days=2))) as c:
        assert "Max-Age=172800" in login(c).headers["set-cookie"]
