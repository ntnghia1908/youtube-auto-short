"""FIX-youtube-id-dash: YouTube video ids may start with '-' or '_' (CP2 D3 amended)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.post.images import usage_counts  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.workspace import WorkspaceError, iter_manifests, validate_episode_id  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
DASH, UNDER = "-RjgLgw_iVk", "_xIElIoe2Ls"


@pytest.fixture
def wcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"), web=WebConfig(session_days=30))


@pytest.fixture(autouse=True)
def _fast_login_delay(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.05)


def make_client(cfg, calls=None):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline(calls if calls is not None else []))
    c = TestClient(app, follow_redirects=False)
    return c


def login(c):
    assert c.post("/login", data={"password": PW, "next": "/"}).status_code == 303


# --- AC1 ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("eid", [DASH, UNDER, DASH + ".kt", UNDER + ".kt", "tHtxw6ykUmM", "tHtxw6ykUmM.kt",
                                 "a", "vid00000001", "Kinh-A_1.kt", "a" * 128, "-" * 11, "_" * 11 + ".kt"])
def test_valid_ids(eid):
    assert validate_episode_id(eid) == eid


@pytest.mark.parametrize("eid", [".x", "..", "a/b", "-abc", "_abc", "_playlists", "_sutras", "_deleted", "_learning",
                                 "_post-backups", "", "a" * 129, "-RjgLgw_iV", "-RjgLgw_iVkk", "-RjgLgw_iVk.kt.kt",
                                 "-RjgLgw_iVk/", "-Rjg/gw_iVk", ".web_state1", "-RjgLgw_iV.kt"])
def test_invalid_ids(eid):
    with pytest.raises(WorkspaceError):
        validate_episode_id(eid)


# --- AC3 ---------------------------------------------------------------------------------------------------

def test_iter_manifests_and_image_usage_list_dash_and_underscore_episodes(wcfg):
    work = Path(wcfg.workspace.dir)
    for eid in (DASH, UNDER, DASH + ".kt", "tHtxw6ykUmM"):
        write_episode(wcfg, eid)
    for sysdir in ("_playlists", "_sutras", "_deleted", "_learning", "_post-backups"):
        (work / sysdir).mkdir()
        (work / sysdir / "manifest.json").write_text("{}", encoding="utf-8")
        (work / sysdir / "posts.json").write_text("{}", encoding="utf-8")
    assert sorted(ws.episode_id for ws, _ in iter_manifests(work)) == sorted([DASH, UNDER, DASH + ".kt", "tHtxw6ykUmM"])
    from auto_short.post import store

    def doc(eid, image):
        return {"schema_version": store.SCHEMA_VERSION, "episode_id": eid, "posts": [
            {"clip_id": "k01", "candidate_id": "c1", "source_sha256": "a" * 64, "paragraphs": ["x"], "origin": store.ORIGINS[0],
             "image": image, "link": None, "posted_at": None, "created_at": "2026-10-15T00:00:00Z",
             "updated_at": "2026-10-15T00:00:00Z"}]}
    # build the entry through the real schema check; keys order = ENTRY_KEYS
    def entry_doc(eid, image):
        d = doc(eid, image)
        d["posts"] = [{k: d["posts"][0].get(k) for k in store.ENTRY_KEYS}]
        return d
    (work / UNDER / "posts.json").write_text(json.dumps(entry_doc(UNDER, "a.jpg")), encoding="utf-8")
    assert usage_counts(work) == {"a.jpg": 1}
    (work / "_sutras" / "posts.json").write_text(json.dumps(entry_doc("_sutras", "b.jpg")), encoding="utf-8")
    assert usage_counts(work) == {"a.jpg": 1}  # system dirs are skipped


def test_episode_pages_for_dash_ids(wcfg):
    write_episode(wcfg, DASH)
    write_episode(wcfg, UNDER)
    with make_client(wcfg) as c:
        login(c)
        ids = {e["id"] for e in c.get("/api/episodes").json()["episodes"]}
        assert {DASH, UNDER} <= ids
        for eid in (DASH, UNDER):
            d = c.get(f"/api/episodes/{eid}")
            assert d.status_code == 200 and len(d.json()["shorts"]) == 2
            assert c.get(f"/files/{eid}/k01.mp4").status_code == 200
            assert c.get(f"/files/{eid}/shorts.zip").status_code == 200


# --- AC2 / AC5 ---------------------------------------------------------------------------------------------

def test_submit_short_and_khaithi_for_a_dash_id(wcfg):
    calls = []
    with make_client(wcfg, calls) as c:
        login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{DASH}", "kinds": ["short", "khaithi"]})
        assert r.status_code == 202, r.text
        assert [e["episode_id"] for e in r.json()["episodes"]] == [DASH, DASH + ".kt"]
        assert all("error" not in e for e in r.json()["episodes"])
        assert c.app.state.runner.wait_idle(10)
        for eid in (DASH, DASH + ".kt"):
            assert c.app.state.runner.latest(eid).status == "done"
            assert (Path(wcfg.workspace.dir) / eid).is_dir()
        assert (Path(wcfg.workspace.dir) / (DASH + ".kt") / "khaithi.json").is_file()


def test_invalid_id_is_422_not_500(wcfg, monkeypatch):
    monkeypatch.setattr(app_mod, "classify_url",
                        lambda url: SimpleNamespace(kind="video", video_id="bad/id", playlist_id=None))
    with make_client(wcfg) as c:
        login(c)
        for kinds in (["short"], ["khaithi"], ["short", "khaithi"]):
            r = c.post("/api/episodes", json={"url": "https://youtu.be/whatever", "kinds": kinds})
            assert r.status_code == 422 and r.json()["detail"], kinds
        assert c.app.state.runner.jobs() == []


# --- AC6: no bare '-' id as argv ---------------------------------------------------------------------------

def test_cli_accepts_dash_episode_id_after_double_dash_or_equals():
    from auto_short.cli import _build_parser

    p = _build_parser()
    assert p.parse_args(["transcript", "--", DASH]).episode_id == DASH
    assert p.parse_args(["run", "x.mp4", f"--episode-id={DASH}"]).episode_id == DASH


def test_workspace_paths_never_start_with_dash(wcfg):
    from auto_short.workspace import Workspace

    ws = Workspace(Path(wcfg.workspace.dir), DASH)
    # every subprocess argument derived from an episode is ``<workspace dir>/<id>/...`` (never the bare id)
    assert not str(ws.dir / "source.mp4").startswith("-")
