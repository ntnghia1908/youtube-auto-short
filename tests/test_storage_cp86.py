"""CP8.6 storage tab: sizes (S1), recommendations (S2), source clean-up / archived episodes (S3), low-disk warning
and URL block (S4). Fake render / pipeline; disk usage and clock injected."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, TranscriptConfig, WhisperConfig, WorkspaceConfig  # noqa: E402
from auto_short.ingest import IngestError, run_ingest  # noqa: E402
from auto_short.render import RenderError, run_render  # noqa: E402
from auto_short.review import (ArchivedError, ReviewError, archive_source, reject_archived_clip,  # noqa: E402
                               reset_title, restore_clip, set_alternative, set_title)
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.storage import (GB, StorageCache, episode_sizes, recommend, tree_size,  # noqa: E402
                                    warning)

from render_helpers import EID, TITLES, make_render_episode, write_docs  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
BASE = f"/api/episodes/{EID}/shorts"
NOW = 1_790_000_000.0  # fixed "now" (2026-09-21)
DAY = 86400
SOURCE_BYTES = 4096


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"),
                  transcript=TranscriptConfig(whisper=WhisperConfig(models_dir=tmp_path / "models")))


@pytest.fixture
def episode(tcfg, tmp_path):
    """YouTube episode, every stage done, render of k01 + k02 (fake mp4), 4 kB source.mp4 in the workspace."""
    tmpl = tmp_path / "fake.mp4"
    tmpl.write_bytes(b"s" * SOURCE_BYTES)
    ws = make_render_episode(tcfg.workspace.dir, tmpl)
    write_docs(ws)
    write_episode(tcfg, EID, titles=TITLES)  # manifest: youtube source, all stages done
    return ws


def free_disk(free: int, total: int = 100 * GB):
    return lambda path: (total, total - free, free)


def client(cfg, *, disk=None, pipeline=None, preflight=None, clock=lambda: NOW):
    calls = [] if preflight is None else None
    pf = preflight or (lambda c: calls.append(c))
    app = app_mod.create_app(cfg, PW, preflight=pf, render=lambda eid, c: SimpleNamespace(
        ran=True, rendered=2, clips=2, encoded=0, reused=2), pipeline=pipeline or fake_pipeline([]),
        disk_usage=disk or free_disk(50 * GB), clock=clock)
    app.state.preflight_calls = calls
    return TestClient(app, follow_redirects=False)


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


# --- S1 sizes ------------------------------------------------------------------------------------------------

def test_tree_size_matches_du(tmp_path):
    root = tmp_path / "t"
    (root / "a" / "b").mkdir(parents=True)
    (root / "x.bin").write_bytes(b"1" * 1000)
    (root / "a" / "y.bin").write_bytes(b"2" * 12345)
    (root / "a" / "b" / "z.bin").write_bytes(b"")
    os.symlink(root / "x.bin", root / "link")  # not followed
    assert tree_size(root) == 13345
    assert tree_size(tmp_path / "missing") == 0
    du = int(subprocess.run(["du", "-sb", str(root)], capture_output=True, text=True).stdout.split()[0])
    # du -sb also counts directories (4 kB each) and the symlink itself
    assert 13345 <= du <= 13345 + 3 * 4096 + 200


def test_episode_sizes_states(tcfg, episode):
    (episode.dir / "transcript").mkdir()
    (episode.dir / "transcript" / "t.vtt").write_bytes(b"v" * 500)
    write_episode(tcfg, "failedEp01")
    m = json.loads((Path(tcfg.workspace.dir) / "failedEp01" / "manifest.json").read_text())
    m["stages"]["selection"]["status"] = "failed"
    (Path(tcfg.workspace.dir) / "failedEp01" / "manifest.json").write_text(json.dumps(m))
    orphan = Path(tcfg.render.output_dir) / "orphanEp01"
    orphan.mkdir(parents=True)
    (orphan / "k01.mp4").write_bytes(b"o" * 70000)
    rows = {r["id"]: r for r in episode_sizes(tcfg, active={"failedEp01"})}
    r = rows[EID]
    assert r["state"] == "done" and r["source"] == SOURCE_BYTES and r["source_kind"] == "youtube"
    out = Path(tcfg.render.output_dir) / EID
    assert r["shorts_bytes"] == tree_size(out) and r["shorts_bytes"] > 2000
    assert r["other"] == tree_size(episode.dir) - SOURCE_BYTES and r["other"] >= 500
    assert r["total"] == r["source"] + r["other"] + r["shorts_bytes"]
    assert (r["shorts"], r["published"]) == (2, 0)
    assert rows["failedEp01"]["state"] == "processing"  # a job is active
    assert rows["orphanEp01"]["state"] == "orphan" and rows["orphanEp01"]["total"] == 70000
    assert list(rows)[0] == "orphanEp01"  # largest first
    rows = {r["id"]: r for r in episode_sizes(tcfg)}
    assert rows["failedEp01"]["state"] == "failed"


# --- S2 recommendations --------------------------------------------------------------------------------------

def _row(eid, **kw):
    base = {"id": eid, "title": None, "state": "done", "source_kind": "youtube", "source": 650 * 10**6,
            "shorts_bytes": 250 * 10**6, "other": 3 * 10**6, "total": 903 * 10**6, "shorts": 20, "published": 0,
            "render_finished_at": NOW - DAY, "last_activity": NOW - DAY, "archived_at": None,
            "complete": False}
    return {**base, **kw}


def test_recommendations_rules_and_priority():
    rows = [
        _row("allPub", published=20, complete=True, render_finished_at=NOW - 30 * DAY),  # rule 1 wins over 2
        _row("allPubArchived", published=20, complete=True, state="archived", source=0, total=253 * 10**6),
        # CP8.7: every Short ticked but one is "đã đăng bản cũ" -> not Xong -> no rule 1 (render is recent)
        _row("staleTick", published=20, complete=False),
        _row("old8", render_finished_at=NOW - 8 * DAY),
        _row("new6", render_finished_at=NOW - 6 * DAY),
        _row("oldLocal", source_kind="local", source=0, render_finished_at=NOW - 30 * DAY),
        _row("oldArchived", state="archived", source=0, render_finished_at=NOW - 30 * DAY),
        _row("failed8", state="failed", shorts=0, render_finished_at=None, last_activity=NOW - 8 * DAY),
        _row("incomplete9", state="incomplete", shorts=0, render_finished_at=None, last_activity=NOW - 9 * DAY),
        _row("failed2", state="failed", shorts=0, render_finished_at=None, last_activity=NOW - 2 * DAY),
        _row("busy", state="processing", published=20, complete=True, last_activity=NOW - 30 * DAY),
        _row("orph", state="orphan", source_kind=None, source=0, shorts=0, last_activity=NOW - 30 * DAY),
    ]
    recs = {r["episode_id"]: r for r in recommend(rows, NOW)}
    assert set(recs) == {"allPub", "allPubArchived", "old8", "failed8", "incomplete9"}
    assert recs["allPub"]["rule"] == "all_published"
    assert recs["allPub"]["actions"] == [{"action": "archive", "frees": 650 * 10**6},
                                         {"action": "delete", "frees": 903 * 10**6}]
    assert recs["allPubArchived"]["actions"] == [{"action": "delete", "frees": 253 * 10**6}]
    assert recs["old8"]["rule"] == "old_source" and recs["old8"]["age_days"] == 8
    assert recs["old8"]["actions"] == [{"action": "archive", "frees": 650 * 10**6}]
    assert recs["failed8"]["rule"] == "stale_unfinished"
    assert recs["failed8"]["actions"] == [{"action": "delete", "frees": 903 * 10**6}]
    assert [r["episode_id"] for r in recommend(rows, NOW)][:2] == ["allPub", "allPubArchived"]  # input order


# --- S4 warning ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("free, total, warn, block", [
    (50 * GB, 100 * GB, False, False),
    (10 * GB, 100 * GB, False, False),
    (int(9.9 * GB), 100 * GB, True, False),
    (15 * GB, 200 * GB, True, False),  # 7.5 % free
    (int(2.9 * GB), 100 * GB, True, True),
])
def test_warning_thresholds(free, total, warn, block):
    w = warning([{"total": total, "used": total - free, "free": free}])
    assert (w["warn"], w["block"], w["free"]) == (warn, block, free)


def test_storage_cache_30s(tcfg, episode):
    mono = [0.0]
    cache = StorageCache(tcfg, disk_usage=free_disk(50 * GB), clock=lambda: NOW, monotonic=lambda: mono[0])
    first = cache.report()
    (episode.dir / "big.bin").write_bytes(b"x" * 10000)
    mono[0] = 29.0
    assert cache.report() is first
    mono[0] = 31.0
    assert cache.report()["episodes"][0]["other"] == first["episodes"][0]["other"] + 10000
    cache.invalidate()
    assert cache.report() is not first


# --- S3 source clean-up --------------------------------------------------------------------------------------

def test_archive_source_and_guards(tcfg, episode, tmp_path):
    manifest_before = episode.manifest_path.read_bytes()
    r = archive_source(EID, tcfg, now="2026-09-27T12:00:00Z")
    assert (r.changed, r.freed, r.removed) == (True, SOURCE_BYTES, ["source.mp4"])
    assert not (episode.dir / "source.mp4").exists()
    assert json.loads((episode.dir / "archive.json").read_text()) == {
        "schema_version": 1, "episode_id": EID, "archived_at": "2026-09-27T12:00:00Z",
        "removed": [{"path": "source.mp4", "size": SOURCE_BYTES}]}
    assert archive_source(EID, tcfg).changed is False
    assert episode.manifest_path.read_bytes() == manifest_before
    for fn in (lambda: set_title(EID, tcfg, "k01", "Tiêu đề mới"), lambda: set_alternative(EID, tcfg, "k01", 1),
               lambda: reset_title(EID, tcfg, "k01"), lambda: restore_clip(EID, tcfg, "k01")):
        with pytest.raises(ArchivedError, match="đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại"):
            fn()
    with pytest.raises(RenderError, match="archived"):
        run_render(EID, tcfg)
    with pytest.raises(IngestError, match="archived"):
        run_ingest(f"https://youtu.be/{EID}", tcfg, downloader=lambda *a: pytest.fail("no download"))
    assert episode.manifest_path.read_bytes() == manifest_before  # nothing recorded as failed
    assert not (episode.dir / "review.json").exists()


def test_archive_refuses_local_and_unfinished(tcfg, tmp_path):
    local = tmp_path / "input" / "lecture.mp4"
    local.parent.mkdir()
    local.write_bytes(b"L" * 100)
    ws = make_render_episode(tcfg.workspace.dir, local)  # kind "local"
    m = json.loads(ws.manifest_path.read_text())
    m["stages"]["render"] = {"status": "done"}
    ws.manifest_path.write_text(json.dumps(m))
    with pytest.raises(ReviewError, match="file local"):
        archive_source(EID, tcfg)
    assert local.read_bytes() == b"L" * 100 and (ws.dir / "source.mp4").exists()
    m["source"]["kind"] = "youtube"
    m["stages"]["render"] = {"status": "stale"}
    ws.manifest_path.write_text(json.dumps(m))
    with pytest.raises(ReviewError, match="chưa dựng Short xong"):
        archive_source(EID, tcfg)
    assert not (ws.dir / "archive.json").exists()
    with pytest.raises(ReviewError):
        archive_source("nope", tcfg)


def test_reject_archived_clip_without_render(tcfg, episode):
    out = Path(tcfg.render.output_dir) / EID
    m = json.loads(episode.manifest_path.read_text())
    m["stages"]["render"]["artifacts"] = [str(out.resolve() / "render_manifest.json"),
                                          str(out.resolve() / "shorts/k01.mp4"), str(out.resolve() / "shorts/k02.mp4")]
    episode.manifest_path.write_text(json.dumps(m))
    with pytest.raises(ReviewError, match="chưa dọn"):
        reject_archived_clip(EID, tcfg, "k01")
    archive_source(EID, tcfg)
    assert reject_archived_clip(EID, tcfg, "k01") is True
    rm = json.loads((out / "render_manifest.json").read_text())
    k01 = rm["shorts"][0]
    assert (k01["status"], k01["skip_reason"], k01["file"], k01["sha256"], k01["render_key"]) == \
        ("skipped", "rejected", None, None, None)
    assert k01["title"] == TITLES["k01"]
    assert (rm["stats"]["rendered"], rm["stats"]["skipped"]) == (1, 1)
    assert not (out / "shorts/k01.mp4").exists() and (out / "shorts/k02.mp4").exists()
    arts = json.loads(episode.manifest_path.read_text())["stages"]["render"]["artifacts"]
    assert str(out.resolve() / "shorts/k01.mp4") not in arts and len(arts) == 2
    assert json.loads((episode.dir / "review.json").read_text())["rejected"] == [
        {"clip_id": "k01", "candidate_id": "c00001"}]
    assert reject_archived_clip(EID, tcfg, "k01") is False


# --- web -------------------------------------------------------------------------------------------------------

def test_storage_api_and_page(tcfg, episode):
    (Path(tcfg.transcript.whisper.models_dir) / "m").mkdir(parents=True)
    (Path(tcfg.transcript.whisper.models_dir) / "m" / "model.bin").write_bytes(b"m" * 1234)
    with client(tcfg) as c:
        assert c.get("/api/storage").status_code == 401
        assert c.get("/storage").status_code == 303
        _login(c)
        assert "Bộ nhớ" in c.get("/storage").text and 'id="disk-banner"' in c.get("/").text
        d = c.get("/api/storage").json()
        assert d["disks"][0]["free"] == 50 * GB and d["warn"] is False and d["block"] is False
        assert d["episodes"][0]["id"] == EID and d["episodes"][0]["source"] == SOURCE_BYTES
        assert d["caches"] == [{"name": "Model Whisper", "path": str(tcfg.transcript.whisper.models_dir),
                                "bytes": 1234, "exists": True}]
        assert d["recommendations"] == []  # rendered "now", nothing published
        for clip in ("k01", "k02"):
            c.post(f"{BASE}/{clip}/published", json={"value": True})
        c.app.state.storage.invalidate()
        recs = c.get("/api/storage").json()["recommendations"]
        assert [(r["episode_id"], r["rule"], [a["action"] for a in r["actions"]]) for r in recs] == \
            [(EID, "all_published", ["archive", "delete"])]


def test_old_render_recommended_with_injected_clock(tcfg, episode):
    from auto_short.web.storage import parse_time
    finished = parse_time("2026-09-27T00:01:00Z")  # web_helpers.write_episode render finished_at
    with client(tcfg, clock=lambda: finished + 8 * DAY + 3600) as c:
        _login(c)
        recs = c.get("/api/storage").json()["recommendations"]
        assert [(r["rule"], r["age_days"]) for r in recs] == [("old_source", 8)]


@pytest.mark.parametrize("free, total, warn, block", [(50 * GB, 100 * GB, False, False),
                                                      (8 * GB, 100 * GB, True, False),
                                                      (2 * GB, 100 * GB, True, True)])
def test_disk_status_and_submit_block(tcfg, free, total, warn, block):
    calls = []
    with client(tcfg, disk=free_disk(free, total), pipeline=fake_pipeline(calls)) as c:
        _login(c)
        st = c.get("/api/storage/status").json()
        assert (st["warn"], st["block"], st["free"]) == (warn, block, free)
        r = c.post("/api/episodes", json={"url": "https://youtu.be/abcdefghijk"})
        if block:
            assert r.status_code == 507 and "dưới 3 GB" in r.json()["detail"]
            assert c.app.state.runner.jobs() == [] and c.app.state.preflight_calls == []
            assert not (Path(tcfg.workspace.dir) / "abcdefghijk").exists()
        else:
            assert r.status_code == 202
            assert c.app.state.runner.wait_idle(5)


def test_archive_route_and_archived_episode_rules(tcfg, episode):
    with client(tcfg) as c:
        _login(c)
        assert c.post("/api/episodes/nope/archive").status_code == 404
        assert c.post("/api/episodes/..%2Fx/archive").status_code == 404
        before = c.get(f"/api/storage").json()["episodes"][0]
        r = c.post(f"/api/episodes/{EID}/archive")
        assert r.status_code == 200 and r.json() == {"archived": EID, "changed": True, "freed": SOURCE_BYTES,
                                                     "removed": ["source.mp4"]}
        after = c.get("/api/storage").json()["episodes"][0]  # cache invalidated
        assert after["state"] == "archived" and after["source"] == 0
        assert after["total"] == before["total"] - SOURCE_BYTES + (episode.dir / "archive.json").stat().st_size
        d = c.get(f"/api/episodes/{EID}").json()
        assert d["archived"]["freed"] == SOURCE_BYTES and d["archived"]["at"]
        assert c.get("/api/episodes").json()["episodes"][0]["archived"] is True
        # still: play / download / tick
        k02 = d["shorts"][1]
        assert c.get(k02["download_url"]).status_code == 200
        assert c.post(f"{BASE}/k02/published", json={"value": True}).json()["published"] is True
        # refused with the contract message: title edit, restore, resubmit
        msg = "đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại"
        for resp in (c.post(f"{BASE}/k01/title", json={"set": "Tiêu đề mới"}),
                     c.post(f"{BASE}/k01/title", json={"reset": True}),
                     c.post(f"{BASE}/k01/restore"),
                     c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["short"]})):
            assert resp.status_code == 409 and msg in resp.json()["detail"]
        assert c.app.state.runner.jobs() == []
        # delete a Short: applied directly, no render job
        r = c.post(f"{BASE}/k01/delete")
        assert r.status_code == 200 and r.json() == {"changed": True, "job": None}
        k01 = c.get(f"/api/episodes/{EID}").json()["shorts"][0]
        assert (k01["deleted"], k01["status"]) == (True, "skipped")
        assert c.get(f"/files/{EID}/k01.mp4").status_code == 404
        assert c.app.state.runner.jobs() == []
        # then the whole episode can go
        assert c.delete(f"/api/episodes/{EID}").status_code == 200
        assert c.get("/api/storage").json()["episodes"] == []


def test_archive_refused_while_job_active(tcfg, episode):
    import threading
    gate = threading.Event()
    with client(tcfg, pipeline=fake_pipeline([], gate=gate)) as c:
        _login(c)
        assert c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"}).status_code == 202
        r = c.post(f"/api/episodes/{EID}/archive")
        assert r.status_code == 409 and (episode.dir / "source.mp4").exists()
        gate.set()
        assert c.app.state.runner.wait_idle(5)
