"""FIX-storage-suggest: clean-up recommendations per video (Short + khai thị, D1 D2), pending-post warning (D3) and
the automatic clean-up of a finished video's source (D4). Fake render / pipeline; clock injected; tmp_path only."""

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import (Config, RenderConfig, StorageConfig, TranscriptConfig, WhisperConfig,  # noqa: E402
                               WorkspaceConfig)
from auto_short.config import load as load_config  # noqa: E402
from auto_short.post.store import POSTS_NAME  # noqa: E402
from auto_short.review import read_archive, set_published  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.storage import (GB, auto_archive_plan, episode_sizes, recommend, video_id)  # noqa: E402

from render_helpers import EID, TITLES, make_render_episode, write_docs  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
KT = EID + ".kt"
DAY = 86400
GRACE = 30 * 60
MB = 10**6


def _row(eid, **kw):
    base = {"id": eid, "title": None, "state": "done", "source_kind": "youtube", "source": 600 * MB,
            "shorts_bytes": 200 * MB, "other": 3 * MB, "total": 803 * MB, "shorts": 5, "published": 5,
            "render_finished_at": 1000.0, "last_activity": 1000.0, "archived_at": None, "complete": True,
            "post_unticked": 0, "complete_since": 1000.0}
    return {**base, **kw}


NOW = 10_000_000.0


# --- D1 / D2 / D3: recommend (pure) ----------------------------------------------------------------------------

def test_video_id():
    assert video_id("abc.kt") == "abc" and video_id("abc") == "abc" and video_id(".kt") == ".kt"


def test_short_done_khaithi_not_done_no_recommendation():  # AC1, both directions
    for done, other in (("v1", "v1.kt"), ("v1.kt", "v1")):
        rows = [_row(done), _row(other, complete=False, published=2)]
        assert [r for r in recommend(rows, NOW) if r["rule"] == "all_published"] == []


def test_both_done_one_merged_recommendation():  # AC2
    rows = [_row("v1", title="T"), _row("v1.kt", source=600 * MB, total=700 * MB)]
    (rec,) = recommend(rows, NOW)
    assert rec["rule"] == "all_published" and rec["episodes"] == ["v1", "v1.kt"] and rec["title"] == "T"
    arch, delete = rec["actions"]
    assert arch == {"action": "archive", "frees": 1200 * MB, "episodes": ["v1", "v1.kt"]}
    assert delete == {"action": "delete", "frees": 803 * MB + 700 * MB, "episodes": ["v1", "v1.kt"]}


def test_both_done_one_already_archived():
    rows = [_row("v1", state="archived", source=0, total=203 * MB), _row("v1.kt")]
    (rec,) = recommend(rows, NOW)
    assert rec["actions"][0] == {"action": "archive", "frees": 600 * MB, "episodes": ["v1.kt"]}
    assert rec["actions"][1]["episodes"] == ["v1", "v1.kt"]


def test_single_part_as_before():  # AC3
    for eid in ("v1", "v1.kt"):
        (rec,) = recommend([_row(eid)], NOW)
        assert rec["episodes"] == [eid] and rec["rule"] == "all_published"
        assert [a["action"] for a in rec["actions"]] == ["archive", "delete"]


def test_post_unticked_warning_count():  # AC4
    rows = [_row("v1", post_unticked=3), _row("v1.kt", post_unticked=2), _row("v2")]
    recs = {r["video_id"]: r for r in recommend(rows, NOW)}
    assert recs["v1"]["post_unticked"] == 5 and recs["v2"]["post_unticked"] == 0
    assert recs["v1"]["rule"] == "all_published"  # posts never block


def test_part_processing_skips_video():  # AC5
    rows = [_row("v1"), _row("v1.kt", state="processing", complete=False)]
    assert recommend(rows, NOW) == []


def test_old_source_and_stale_per_video():
    old = NOW - 8 * DAY
    rows = [_row("a", complete=False, render_finished_at=old), _row("a.kt", complete=False, render_finished_at=old),
            _row("b", complete=False, render_finished_at=old),
            _row("b.kt", complete=False, render_finished_at=NOW - DAY),  # recent part -> no old_source
            _row("c", state="failed", complete=False, render_finished_at=None, last_activity=old),
            _row("c.kt", state="incomplete", complete=False, render_finished_at=None, last_activity=old),
            _row("d", state="failed", complete=False, render_finished_at=None, last_activity=old),
            _row("d.kt", state="failed", complete=False, render_finished_at=None, last_activity=NOW - DAY)]
    recs = {r["video_id"]: r for r in recommend(rows, NOW)}
    assert set(recs) == {"a", "c"}
    assert recs["a"]["rule"] == "old_source" and recs["a"]["actions"][0]["episodes"] == ["a", "a.kt"]
    assert recs["c"]["rule"] == "stale_unfinished" and recs["c"]["actions"][0]["frees"] == 2 * 803 * MB


# --- D4: auto_archive_plan (pure) ------------------------------------------------------------------------------

def test_plan_grace_and_all_parts():  # AC6
    rows = [_row("v1", complete_since=NOW - GRACE), _row("v1.kt", complete_since=NOW - 2 * GRACE)]
    (item,) = auto_archive_plan(rows, NOW, GRACE)
    assert item["video_id"] == "v1" and item["episodes"] == ["v1", "v1.kt"] and item["freed"] == 1200 * MB
    assert auto_archive_plan(rows, NOW - 1, GRACE) == []  # the latest part has not held for the grace period
    rows[1]["complete"] = False
    assert auto_archive_plan(rows, NOW, GRACE) == []
    rows[1].update(complete=True, state="processing")
    assert auto_archive_plan(rows, NOW, GRACE) == []


def test_plan_ignores_local_archived_and_unfinished_render():
    rows = [_row("loc", source_kind="local", source=0), _row("arch", state="archived", source=0),
            _row("youtube1", state="failed", complete=False), _row("grace", complete_since=NOW - 60)]
    assert auto_archive_plan(rows, NOW, GRACE) == []


# --- integration on real files ---------------------------------------------------------------------------------

@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"),
                  transcript=TranscriptConfig(whisper=WhisperConfig(models_dir=tmp_path / "models")))


def _clone(cfg, src, dst):
    for root in (Path(cfg.workspace.dir), Path(cfg.render.output_dir)):
        shutil.copytree(root / src, root / dst)
        for f in (root / dst).rglob("*.json"):
            f.write_text(f.read_text(encoding="utf-8").replace(f'"{src}"', f'"{dst}"'), encoding="utf-8")


@pytest.fixture
def video(tcfg, tmp_path):
    """Short episode EID + khai thị EID.kt, each with k01 + k02 rendered and a 4 kB source."""
    tmpl = tmp_path / "fake.mp4"
    tmpl.write_bytes(b"s" * 4096)
    ws = make_render_episode(tcfg.workspace.dir, tmpl)
    write_docs(ws)
    write_episode(tcfg, EID, titles=TITLES)
    _clone(tcfg, EID, KT)
    return tcfg


def _tick_all(cfg, eids=(EID, KT)):
    for eid in eids:
        for clip in ("k01", "k02"):
            set_published(eid, cfg, clip, True)


def _app(cfg, clock, **kw):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda eid, c: SimpleNamespace(
        ran=True, rendered=2, clips=2, encoded=0, reused=2), pipeline=fake_pipeline([]),
        disk_usage=lambda p: (100 * GB, 50 * GB, 50 * GB), clock=clock, auto_archive_interval=0, **kw)
    return app


def test_episode_sizes_fields_posts_and_since(video):
    rows = {r["id"]: r for r in episode_sizes(video)}
    assert rows[EID]["complete"] is False and rows[EID]["complete_since"] is None
    _tick_all(video)
    ws = Path(video.workspace.dir) / EID
    entry = {"clip_id": "k01", "candidate_id": "c1", "source_sha256": "a" * 64, "paragraphs": ["x"], "origin": "raw",
             "image": None, "link": None, "posted_at": None, "updated_at": "2026-09-27T00:00:00Z"}
    (ws / POSTS_NAME).write_text(json.dumps({"schema_version": 1, "episode_id": EID, "posts": [
        entry, {**entry, "clip_id": "k02", "posted_at": "2026-09-27T01:00:00Z"},
        {**entry, "clip_id": "gone"}]}), encoding="utf-8")  # a post of a Short that is not rendered: not counted
    rows = {r["id"]: r for r in episode_sizes(video)}
    assert rows[EID]["complete"] and rows[EID]["post_unticked"] == 1 and rows[KT]["post_unticked"] == 0
    assert rows[EID]["complete_since"] >= time.time() - 60


def test_storage_api_merged_video(video):  # AC2, AC4 through the route
    _tick_all(video)
    with TestClient(_app(video, time.time), follow_redirects=False) as c:
        assert c.post("/login", data={"password": PW}).status_code == 303
        recs = c.get("/api/storage").json()["recommendations"]
        assert len(recs) == 1 and recs[0]["episodes"] == [EID, KT] and recs[0]["post_unticked"] == 0
        # the source link of the khai thị part is a copy here: archive via the API for each part
        for eid in recs[0]["actions"][0]["episodes"]:
            assert c.post(f"/api/episodes/{eid}/archive").status_code == 200
        assert read_archive(Path(video.workspace.dir) / EID) is not None
        assert read_archive(Path(video.workspace.dir) / KT) is not None
        assert "auto" not in read_archive(Path(video.workspace.dir) / EID)  # manual button: not auto


def test_auto_archive_after_grace(video):  # AC6
    _tick_all(video)
    clock = [time.time()]
    app = _app(video, lambda: clock[0])
    assert app.state.auto_archive_pass() == []  # just ticked: inside the grace period
    clock[0] += GRACE + 5
    done = app.state.auto_archive_pass()
    assert sorted(done) == sorted([EID, KT])
    for eid in (EID, KT):
        ar = read_archive(Path(video.workspace.dir) / eid)
        assert ar["auto"] is True and ar["removed"]
        assert not list((Path(video.workspace.dir) / eid).glob("source.*"))
    assert app.state.auto_archive_pass() == []  # already archived: nothing to do
    with TestClient(app, follow_redirects=False) as c:
        c.post("/login", data={"password": PW})
        assert c.get(f"/api/episodes/{EID}").json()["archived"]["auto"] is True


def test_auto_archive_unticking_in_grace_and_one_part_open(video):
    _tick_all(video, (EID,))  # khai thị part not ticked
    clock = [time.time() + 10 * GRACE]
    app = _app(video, lambda: clock[0])
    assert app.state.auto_archive_pass() == []
    _tick_all(video, (KT,))
    set_published(EID, video, "k01", False)  # un-tick inside the grace period
    assert app.state.auto_archive_pass() == []
    set_published(EID, video, "k01", True)  # re-ticked "now" (real time) -> grace restarts
    clock[0] = time.time() + 1
    assert app.state.auto_archive_pass() == []
    clock[0] = time.time() + GRACE + 60
    assert sorted(app.state.auto_archive_pass()) == sorted([EID, KT])


def test_auto_archive_disabled_and_job_waits(video):
    _tick_all(video)
    off = Config(workspace=video.workspace, render=video.render, transcript=video.transcript,
                 storage=StorageConfig(auto_archive=False))
    far = lambda: time.time() + 10 * GRACE  # noqa: E731
    assert _app(off, far).state.auto_archive_pass() == []
    assert read_archive(Path(video.workspace.dir) / EID) is None
    app = _app(video, far)
    runner = app.state.runner
    busy = SimpleNamespace(episode_id=KT, active=True)
    runner.latest = lambda eid: busy if eid == KT else None
    runner.jobs = lambda: [busy]
    assert app.state.auto_archive_pass() == []  # a part has a job: the whole video waits
    runner.latest = lambda eid: None
    runner.jobs = lambda: []
    assert len(app.state.auto_archive_pass()) == 2


def test_auto_archive_never_touches_local_source(video):
    ws = Path(video.workspace.dir) / EID
    m = json.loads((ws / "manifest.json").read_text())
    m["source"]["kind"] = "local"
    (ws / "manifest.json").write_text(json.dumps(m))
    _tick_all(video, (EID,))
    rows = {r["id"]: r for r in episode_sizes(video)}
    assert rows[EID]["complete"]
    _tick_all(video, (KT,))
    app = _app(video, lambda: time.time() + 10 * GRACE)
    assert app.state.auto_archive_pass() == [KT]  # the local part is left alone
    assert read_archive(ws) is None and (ws / "source.mp4").exists()


def test_config_storage_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[storage]\nauto_archive = false\nauto_archive_grace_minutes = 5\n")
    cfg = load_config(p)
    assert (cfg.storage.auto_archive, cfg.storage.auto_archive_grace_minutes) == (False, 5)
    assert Config().storage == StorageConfig(True, 30)
