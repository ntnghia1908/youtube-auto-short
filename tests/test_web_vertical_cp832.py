"""CP8.32: vertical full-episode version / landscape download from the original video >= 720p (V1), archived episodes
(V2: the original is downloaded again for the job and removed afterwards), "Tạo bản dọc cả bộ" (V3) and the lane order."""

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, EnhanceConfig, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.ingest.youtube import Download, YoutubeBlocked  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.render import full  # noqa: E402
from auto_short.render.stage import RenderError  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web import jobs as jobs_mod  # noqa: E402
from auto_short.web.jobs import KIND_RENDER, KIND_VERTICAL, JobRunner, Step  # noqa: E402

from web_helpers import PW, fake_pipeline, login, web_client as client, write_episode  # noqa: E402

VID = "aaaaaaaaaa1"
KT = VID + ".kt"
SERIES = "Thập Thiện Nghiệp Đạo"
ORIG = bytes(range(256)) * 50


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2),
                  enhance=EnhanceConfig(enabled=True, min_height=720))


def ffmpeg_clip(path: Path, seconds=2, w=1280, h=720, fps=25):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
                    str(path)], check=True)


def make_ep(cfg, eid=VID, *, height=1080, data=ORIG, archived=False, name="source.mp4", episode="1",
            render_status="done", duration=3600.0, with_titles=True):
    """A finished episode (Shorts rendered) with a downloaded original ``name`` of ``height`` p; ``archived`` removes
    the file like CP8.6 (``archive.json``; the manifest keeps its sha256 / size)."""
    write_episode(cfg, eid, clips=("k01",), render_status=render_status)
    d = Path(cfg.workspace.dir) / eid
    if with_titles:
        fields = {"speaker": "HT. Tịnh Không", "series": SERIES, "episode": episode}
        (d / "titles.json").write_text(json.dumps({"header": {"fields": fields, "lines": [
            "HT. Tịnh Không", f"Thập Thiện (tập {episode})"]}}, ensure_ascii=False), encoding="utf-8")
    src = d / name
    src.write_bytes(data)
    m = json.loads((d / "manifest.json").read_text())
    m["source"] = {"kind": "youtube", "uri": f"https://youtu.be/{eid}", "path": name,
                   "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mtime_ns": 1}
    (d / "manifest.json").write_text(json.dumps(m))
    (d / "metadata.json").write_text(json.dumps({"title": "T", "duration": duration, "width": height * 16 // 9,
                                                 "height": height}), encoding="utf-8")
    if archived:
        src.unlink()
        (d / "archive.json").write_text(json.dumps({"schema_version": 1, "episode_id": eid, "archived_at": "x",
                                                    "removed": [{"path": name, "size": len(data)}]}))
    return d


def write_hd(cfg, eid, data=b"HD" * 500):
    d = Path(cfg.workspace.dir) / eid
    (d / "source_hd.mp4").write_bytes(data)
    stt = (d / "source_hd.mp4").stat()
    doc = st.new_doc(eid)
    doc.update(wanted=True, state=st.DONE, source_hd_sha256=hashlib.sha256(data).hexdigest(),
               source_hd_size=stt.st_size, source_hd_mtime_ns=stt.st_mtime_ns)
    st.write(d, doc)


def fake_vertical(calls):
    def run(eid, cfg):
        calls.append(eid)
        src = st.effective_source(cfg, eid)
        d = full.vertical_dir(cfg, eid)
        d.mkdir(parents=True, exist_ok=True)
        (d / full.VIDEO_NAME).write_bytes(b"v" * 77)
        (d / full.META_NAME).write_text(json.dumps({"hd_sha256": src.sha256, "size": 77, "key": "k",
                                                    "source": src.kind}), encoding="utf-8")
        return full.FullResult(eid, d / full.VIDEO_NAME, True, 0.1, 77)
    return run


# --- V1: effective source -----------------------------------------------------------------------------------------

def test_effective_source_rules(tcfg):
    make_ep(tcfg, height=1080)
    src = st.effective_source(tcfg, VID)
    assert src.kind == st.SRC_ORIGINAL and src.path.name == "source.mp4"
    assert src.sha256 == hashlib.sha256(ORIG).hexdigest()
    write_hd(tcfg, VID)  # (a) a valid source_hd.mp4 wins
    assert st.effective_source(tcfg, VID).kind == st.SRC_HD
    make_ep(tcfg, "bbbbbbbbbb2", height=480)  # (c) below the threshold, not enhanced
    assert st.effective_source(tcfg, "bbbbbbbbbb2") is None
    make_ep(tcfg, "cccccccccc3", height=720)  # exactly the threshold counts
    assert st.effective_source(tcfg, "cccccccccc3").kind == st.SRC_ORIGINAL
    tcfg2 = replace(tcfg, enhance=EnhanceConfig(enabled=True, min_height=1080))  # the same config key
    assert st.effective_source(tcfg2, "cccccccccc3") is None


def test_ac1_original_buttons_routes_and_names(tcfg):
    make_ep(tcfg, height=1080)
    calls = []
    c = client(tcfg, vertical=fake_vertical(calls))
    c.__enter__()
    login(c)
    view = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert view["source"] == "original" and view["url"] and view["size"] == len(ORIG)
    r = c.get(f"/api/episodes/{VID}/source-hd")
    assert r.status_code == 200 and r.content == ORIG  # the file as it is, no re-encode
    assert "_HD.mp4" in r.headers["content-disposition"] or "HD.mp4" in r.headers["content-disposition"]
    assert c.get(f"/api/episodes/{VID}/source-hd", headers={"Range": "bytes=5-9"}).status_code == 206
    assert c.get(f"/api/episodes/{VID}/vertical").status_code == 404
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 202
    for _ in range(100):
        v = c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]
        if v["ready"]:
            break
        time.sleep(0.1)
    assert v["ready"] and calls == [VID]
    assert c.get(f"/api/episodes/{VID}/vertical").content == b"v" * 77
    c.__exit__(None, None, None)


def test_original_keeps_its_extension_in_the_name(tcfg):
    make_ep(tcfg, height=1080, name="source.mkv")
    c = client(tcfg)
    login(c)
    r = c.get(f"/api/episodes/{VID}/source-hd")
    assert r.status_code == 200
    assert "HD.mkv" in r.headers["content-disposition"] or "HD.mkv" in c.get(f"/api/episodes/{VID}").json()["hd_video"]["name"]
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"]["name"].endswith("_HD.mkv")


def test_run_vertical_from_original_real_encode_and_reuse(tcfg):
    d = make_ep(tcfg, height=720, data=b"x", duration=2.0)
    ffmpeg_clip(d / "source.mp4", seconds=2)
    data = (d / "source.mp4").read_bytes()
    m = json.loads((d / "manifest.json").read_text())
    m["source"].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    (d / "manifest.json").write_text(json.dumps(m))
    r1 = full.run_vertical(VID, tcfg)
    assert r1.ran
    meta = full.read_meta(tcfg, VID)
    assert meta["source"] == "original" and meta["hd_sha256"] == hashlib.sha256(data).hexdigest()
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(r1.path)],
                                      capture_output=True, text=True, check=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["nb_frames"]) == (1080, 1920, "50")
    assert full.current(tcfg, VID)
    assert not full.run_vertical(VID, tcfg).ran  # second press: no encode
    assert (d / "source.mp4").exists()  # not archived: the original stays
    assert full.run_vertical(KT, tcfg).path == r1.path  # a khai thị id means its video


def test_ac2_low_resolution_unchanged(tcfg):
    make_ep(tcfg, height=480)
    c = client(tcfg)
    login(c)
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"] is None
    assert c.get(f"/api/episodes/{VID}/source-hd").status_code == 404
    assert c.get(f"/api/episodes/{VID}/vertical").status_code == 404
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 404
    write_hd(tcfg, VID)  # enhanced: source_hd.mp4 as in CP8.27
    view = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert view["source"] == "hd" and c.get(f"/api/episodes/{VID}/source-hd").content == b"HD" * 500


def test_ac6_khaithi_uses_the_original(tcfg):
    make_ep(tcfg)
    write_episode(tcfg, KT, clips=("k01",))
    khaithi.write(Path(tcfg.workspace.dir) / KT, KhaiThi(VID, 4, 7))
    c = client(tcfg)
    login(c)
    assert c.get(f"/api/episodes/{KT}/source-hd").content == ORIG
    assert c.get(f"/api/episodes/{KT}").json()["hd_video"]["source"] == "original"


# --- V2: archived episodes ----------------------------------------------------------------------------------------

def fake_downloader(d_orig: Path, calls: list, *, blocked_first=0):
    def download(url, dest_dir, cfg):
        calls.append(url)
        if len(calls) <= blocked_first:
            raise YoutubeBlocked("Sign in to confirm you're not a bot")
        out = dest_dir / "source.mp4"
        out.write_bytes(d_orig.read_bytes())
        return Download(out, {})
    return download


@pytest.fixture
def orig_clip(tmp_path):
    p = tmp_path / "orig.mp4"
    ffmpeg_clip(p, seconds=1, w=1280, h=720)
    return p


def make_archived(cfg, orig_clip, eid=VID):
    data = orig_clip.read_bytes()
    d = make_ep(cfg, eid, height=720, data=data, archived=True, duration=1.0)
    return d, data


def tree_state(d: Path):
    return {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}


def test_ac3_archived_vertical_refetch_then_cleanup(tcfg, orig_clip):
    d, data = make_archived(tcfg, orig_clip)
    before = tree_state(d)
    calls = []
    c = client(tcfg, vertical_downloader=fake_downloader(orig_clip, calls))
    c.__enter__()
    login(c)
    view = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert view["source"] == "archived" and view["url"] is None  # vertical button yes, landscape no
    assert c.get(f"/api/episodes/{VID}/source-hd").status_code == 404
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 202
    for _ in range(300):
        v = c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]
        if v["ready"] or (v["job"] and v["job"]["status"] == "failed"):
            break
        time.sleep(0.1)
    assert v["ready"], v
    assert calls == [f"https://youtu.be/{VID}"]
    assert not list(d.glob("source.*")) and not (d / ".vertical-fetch-tmp").exists()  # removed again
    after = tree_state(d)
    assert after == before  # archive.json, manifest, metadata, titles, ... unchanged (the sha256 matched: no warning)
    assert full.read_meta(tcfg, VID)["source"] == "original"
    assert c.get(f"/api/episodes/{VID}/vertical").status_code == 200
    # pressing again: reuse, no second download
    assert not full.run_vertical(VID, tcfg).ran and len(calls) == 1
    c.__exit__(None, None, None)


def test_ac3_youtube_block_waits_not_fails(tcfg, orig_clip):
    make_archived(tcfg, orig_clip)
    calls = []
    runner = JobRunner(youtube_retry_seconds=0.3, youtube_retry_max_seconds=0.3)
    c = client(tcfg, runner=runner, vertical_downloader=fake_downloader(orig_clip, calls, blocked_first=1))
    c.__enter__()
    login(c)
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 202
    for _ in range(100):
        if calls:
            break
        time.sleep(0.05)
    time.sleep(0.2)
    job = runner.latest_vertical(VID)
    assert job.status in ("queued", "running") and job.error is None  # waiting for YouTube like the prepare lane
    assert runner.youtube_status()["blocked"] is True
    for _ in range(300):
        if job.status in ("done", "failed"):
            break
        time.sleep(0.1)
    assert job.status == "done", job.error
    assert len(calls) == 2 and not list((Path(tcfg.workspace.dir) / VID).glob("source.*"))
    c.__exit__(None, None, None)


def test_refetch_wrong_video_is_refused_and_cleaned(tcfg, orig_clip):
    d, _ = make_archived(tcfg, orig_clip)
    meta = json.loads((d / "metadata.json").read_text())
    meta["duration"] = 600.0  # the downloaded file is 1 s: not the same video
    (d / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(RenderError, match="không dùng"):
        full.run_vertical(VID, tcfg, downloader=fake_downloader(orig_clip, []))
    assert not list(d.glob("source.*")) and not (d / ".vertical-fetch-tmp").exists()
    assert (d / "archive.json").exists()


def test_refetch_different_bytes_warns_but_is_used(tcfg, orig_clip, caplog):
    d, _ = make_archived(tcfg, orig_clip)
    m = json.loads((d / "manifest.json").read_text())
    m["source"]["size"] = 12345  # the manifest remembers another file
    (d / "manifest.json").write_text(json.dumps(m))
    r = full.run_vertical(VID, tcfg, downloader=fake_downloader(orig_clip, []))
    assert r.ran and "khác bản ingest" in full.read_meta(tcfg, VID)["source_warning"]
    assert not list(d.glob("source.*"))


def test_archived_below_threshold_is_not_offered(tcfg):
    make_ep(tcfg, height=480, archived=True)
    c = client(tcfg)
    login(c)
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"] is None
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 404


def test_auto_archive_waits_for_a_vertical_job(tcfg):
    make_ep(tcfg, height=1080)
    app = app_mod.create_app(tcfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9), vertical=fake_vertical([]))
    runner = app.state.runner
    runner.submit(VID, KIND_VERTICAL, jobs_mod.vertical_target(tcfg, episode_id=VID))  # not started: stays queued
    assert VID not in app.state.auto_archive_pass()


# --- V3: whole bộ kinh --------------------------------------------------------------------------------------------

PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"
EPS = {"ep1xxxxxxx1": 1, "ep2xxxxxxx2": 2, "ep3xxxxxxx3": 3, "ep4xxxxxxx4": 4, "ep5xxxxxxx5": 5}


def seed_playlist(cfg):
    entries = [{"index": i, "video_id": v, "title": f"Thập Thiện tập {n}", "duration": 3000.0, "episode": str(n),
                "available": True} for i, (v, n) in enumerate(reversed(list(EPS.items())), 1)]
    path = Path(cfg.workspace.dir) / "_playlists" / f"{PL}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "playlist_id": PL, "title": "Thập Thiện", "url": "u",
                                "fetched_at": "2026-10-04T00:00:00Z", "entries": entries}), encoding="utf-8")


def seed_five(cfg):
    ids = list(EPS)
    make_ep(cfg, ids[0], height=1080, episode="1")  # 1: done + original -> queued
    make_ep(cfg, ids[1], height=1080, episode="2", archived=True)  # 2: done + archived 1080p -> queued (re-download)
    make_ep(cfg, ids[2], height=1080, episode="3")  # 3: already has a current vertical -> skipped
    sha = hashlib.sha256(ORIG).hexdigest()
    vd = full.vertical_dir(cfg, ids[2])
    vd.mkdir(parents=True, exist_ok=True)
    (vd / full.VIDEO_NAME).write_bytes(b"v" * 9)
    (vd / full.META_NAME).write_text(json.dumps({"hd_sha256": sha, "size": 9, "key": "k", "source": "original"}))
    make_ep(cfg, ids[3], height=480, episode="4")  # 4: < 720p, not enhanced -> skipped
    make_ep(cfg, ids[4], height=1080, episode="5", render_status="pending")  # 5: Short not done -> skipped
    seed_playlist(cfg)
    return ids


def test_ac4_playlist_button_queues_only_eligible_and_not_twice(tcfg):
    ids = seed_five(tcfg)
    c = client(tcfg)  # lifespan not started: the jobs stay queued
    login(c)
    entries = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
    assert [i for i in ids if entries[i]["vertical"]["status"] == "todo"] == ids[:2]
    assert entries[ids[1]]["vertical"]["fetch"] and entries[ids[2]]["vertical"]["ready"]
    assert entries[ids[2]]["vertical"]["url"] == f"/api/episodes/{ids[2]}/vertical"
    r = c.post(f"/api/playlists/{PL}/vertical")
    assert r.status_code == 202
    body = r.json()
    assert body["queued"] == 2 and body["queued_ids"] == ids[:2]  # episode order
    reasons = {s["episode_id"]: s["reason"] for s in body["skipped"]}
    assert set(reasons) == set(ids[2:]) and "đã có bản dọc" in reasons[ids[2]]
    assert "480" not in reasons[ids[3]] and "720" in reasons[ids[3]] and "Short" in reasons[ids[4]]
    again = c.post(f"/api/playlists/{PL}/vertical").json()  # second press: nothing is queued twice
    assert again["queued"] == 0 and len(again["skipped"]) == 5
    assert c.post("/api/playlists/PLnotthere/vertical").status_code == 404


def test_playlist_button_needs_login(tcfg):
    seed_five(tcfg)
    c = client(tcfg)
    assert c.post(f"/api/playlists/{PL}/vertical").status_code in (303, 401)


def test_playlist_entry_download_icons(tcfg):
    ids = seed_five(tcfg)
    c = client(tcfg)
    login(c)
    entries = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
    assert entries[ids[0]]["hd_url"] == f"/api/episodes/{ids[0]}/source-hd"  # (b): the original of 1080p
    assert "hd_url" not in entries[ids[1]] or not entries[ids[1]].get("hd_url")  # archived: no landscape
    assert not entries[ids[3]].get("hd_url")


# --- AC5: lane order ---------------------------------------------------------------------------------------------

class Dummy:
    def __init__(self, lane_steps):
        self._steps = lane_steps

    def __call__(self, job):
        pass

    def lane_steps(self):
        return self._steps


def test_ac5_short_jobs_start_before_queued_verticals():
    runner = JobRunner()  # not started: only the queue order is observed
    verts = [runner.submit(f"v{i}", KIND_VERTICAL, lambda job: None)[0] for i in range(3)]
    short, _ = runner.submit("s1", KIND_RENDER, lambda job: None)
    runner.priority.mark(["v0"])  # even a marked video's vertical job does not pass a Short job
    assert runner.queue_position(short) == 1
    assert [runner.queue_position(j) for j in verts] == [2, 3, 4]
    assert runner._pick(runner._queues[jobs_mod.RENDER]) is short


def test_ac5_running_lane_takes_the_short_first():
    order, gate = [], threading.Event()
    runner = JobRunner()

    def blocker(job):
        assert gate.wait(10)

    def mk(name):
        def run(job):
            order.append(name)
        return run

    runner.submit("blk", KIND_RENDER, blocker)
    runner.start()
    for _ in range(100):
        if runner.running().get(jobs_mod.RENDER):
            break
        time.sleep(0.02)
    runner.submit("v1", KIND_VERTICAL, mk("v1"))
    runner.submit("v2", KIND_VERTICAL, mk("v2"))
    runner.submit("s1", KIND_RENDER, mk("s1"))  # arrives after the verticals
    gate.set()
    assert runner.wait_idle(10)
    runner.stop(2)
    assert order == ["s1", "v1", "v2"]


def test_vertical_fetch_prefetch_is_bounded():
    gate, fetched, rendered = threading.Event(), [], []
    runner = JobRunner(prepare_workers=2)

    def target(i):
        def fetch(job):
            fetched.append(i)

        def render(job):
            assert gate.wait(10)
            rendered.append(i)
        return Dummy([Step(jobs_mod.PREPARE, fetch), Step(jobs_mod.RENDER, render)])

    runner.start()
    for i in range(5):
        runner.submit(f"v{i}", KIND_VERTICAL, target(i))
    for _ in range(500):
        if len(fetched) >= jobs_mod.VERTICAL_PREFETCH:
            break
        time.sleep(0.02)
    time.sleep(0.5)
    assert len(fetched) == jobs_mod.VERTICAL_PREFETCH  # no more originals on disk until the render lane frees one
    gate.set()
    assert runner.wait_idle(10)
    runner.stop(2)
    assert sorted(fetched) == list(range(5)) and sorted(rendered) == list(range(5))


# --- review round 1: F1 identity after a re-download, F2 leaks --------------------------------------------------

def test_f1_redownload_with_other_bytes_stays_current_and_bulk_skips(tcfg, orig_clip, tmp_path):
    other = tmp_path / "other.mp4"  # same video, other encoder settings -> other size / sha256
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(orig_clip), "-c:v", "libx264", "-crf", "35",
                    "-c:a", "aac", "-b:a", "32k", str(other)], check=True)
    assert other.stat().st_size != orig_clip.stat().st_size
    d, _ = make_archived(tcfg, orig_clip)
    seed_playlist_for(tcfg, VID)
    calls = []
    r = full.run_vertical(VID, tcfg, downloader=fake_downloader(other, calls))
    assert r.ran and "khác bản ingest" in full.read_meta(tcfg, VID)["source_warning"]
    assert not list(d.glob("source.*"))
    assert full.current(tcfg, VID)  # identity = the manifest sha256, also after the clean-up
    c = client(tcfg, vertical_downloader=fake_downloader(other, calls))
    login(c)
    body = c.post(f"/api/playlists/{PL}/vertical").json()
    assert body["queued"] == 0 and "đã có bản dọc" in body["skipped"][0]["reason"]
    assert len(calls) == 1  # no second download


def seed_playlist_for(cfg, vid):
    path = Path(cfg.workspace.dir) / "_playlists" / f"{PL}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "playlist_id": PL, "title": "T", "url": "u",
                                "fetched_at": "2026-10-04T00:00:00Z", "entries": [
                                    {"index": 1, "video_id": vid, "title": "Thập Thiện tập 1", "duration": 3.0,
                                     "episode": "1", "available": True}]}), encoding="utf-8")


def test_f2_failed_vertical_job_removes_the_refetched_original(tcfg, orig_clip):
    d, _ = make_archived(tcfg, orig_clip)
    calls = []

    def broken(eid, cfg):
        raise RenderError("boom after the fetch")

    c = client(tcfg, vertical=broken, vertical_downloader=fake_downloader(orig_clip, calls))
    c.__enter__()
    login(c)
    c.post(f"/api/episodes/{VID}/vertical")
    for _ in range(300):
        job = c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]["job"]
        if job and job["status"] == "failed":
            break
        time.sleep(0.1)
    assert job["status"] == "failed" and len(calls) == 1  # the fetch happened
    time.sleep(0.2)
    assert not list(d.glob("source.*")) and (d / "archive.json").exists()
    c.__exit__(None, None, None)


def test_f2_startup_sweep_cleans_orphans_but_not_active_jobs(tcfg, orig_clip):
    d, _ = make_archived(tcfg, orig_clip)
    (d / "source.mp4").write_bytes(b"x" * 100)  # left by a vanished job
    (d / ".vertical-fetch-tmp").mkdir()
    (d / ".vertical-fetch-tmp" / "part").write_bytes(b"y")
    keep = make_ep(tcfg, "bbbbbbbbbb2", height=1080, archived=True)  # a restored active job owns this one
    (keep / "source.mp4").write_bytes(b"z" * 50)
    live = make_ep(tcfg, "cccccccccc3", height=1080)  # not archived: its original is the normal one
    under = make_ep(tcfg, "_xxxxxxxxxx", height=1080, archived=True)  # PR #84: ids may start with "_"
    (under / "source.mp4").write_bytes(b"u" * 7)
    (Path(tcfg.workspace.dir) / "_playlists").mkdir(exist_ok=True)
    assert full.sweep_refetched_sources(tcfg, {"bbbbbbbbbb2"}) == 107
    assert not (under / "source.mp4").exists()
    assert not list(d.glob("source.*")) and not (d / ".vertical-fetch-tmp").exists()
    assert (keep / "source.mp4").exists() and (live / "source.mp4").exists()
    # through the app start-up (lifespan)
    (d / "source.mp4").write_bytes(b"x" * 10)
    c = client(tcfg)
    c.__enter__()
    assert not (d / "source.mp4").exists()
    c.__exit__(None, None, None)


# --- Amendment 1 (V4): cancel vertical jobs ---------------------------------------------------------------------

def wait_until(pred, timeout=15.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "condition not reached"
        time.sleep(0.05)


def seed_playlist_many(cfg, vids):
    path = Path(cfg.workspace.dir) / "_playlists" / f"{PL}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"index": i, "video_id": v, "title": f"Thập Thiện tập {i}", "duration": 3.0, "episode": str(i),
                "available": True} for i, v in enumerate(vids, 1)]
    path.write_text(json.dumps({"schema_version": 1, "playlist_id": PL, "title": "T", "url": "u",
                                "fetched_at": "2026-10-04T00:00:00Z", "entries": entries}), encoding="utf-8")


def test_ac8_cancel_whole_bo_waiting_fetching_encoding(tcfg):
    a, b, c_id, short = "aaaaaaaaaa1", "cccccccccc3", "bbbbbbbbbb2", "dddddddddd4"
    make_ep(tcfg, a, height=1080)
    make_ep(tcfg, b, height=1080)
    cd = make_ep(tcfg, c_id, height=1080, archived=True)
    seed_playlist_many(tcfg, [a, b, c_id])
    started = {"enc": False, "fetch": False}
    short_done = []

    def vertical(eid, cfg):
        assert eid == a, "only the first job may start encoding"
        started["enc"] = True
        subprocess.run(["sleep", "60"])  # the "ffmpeg" child of the lane thread
        raise RenderError("ffmpeg failed: killed")

    def downloader(url, dest, cfg):
        started["fetch"] = True
        (dest / "source.mp4.part").write_bytes(b"half")
        while True:
            time.sleep(0.05)

    c = client(tcfg, vertical=vertical, vertical_downloader=downloader)
    c.__enter__()
    login(c)
    runner = c.app.state.runner
    assert c.post(f"/api/episodes/{a}/vertical").status_code == 202
    wait_until(lambda: started["enc"])
    assert c.post(f"/api/episodes/{b}/vertical").status_code == 202  # waits in the render queue
    assert c.post(f"/api/episodes/{c_id}/vertical").status_code == 202  # fetches in the prepare lane
    wait_until(lambda: started["fetch"])
    runner.submit(short, KIND_RENDER, lambda job: short_done.append(1))
    view = c.get(f"/api/playlists/{PL}").json()
    assert view["vertical_active"] == 3
    r = c.post(f"/api/playlists/{PL}/vertical/cancel")
    assert r.status_code == 200 and r.json()["cancelled"] == 3
    jobs = [runner.latest_vertical(x) for x in (a, b, c_id)]
    wait_until(lambda: all(j.status == "cancelled" for j in jobs))
    assert all(j.error is None for j in jobs)
    wait_until(lambda: short_done)  # the Short job was not touched and runs once the lane is free
    assert runner.wait_idle(10)
    assert not list(cd.glob("source.*")) and not (cd / ".vertical-fetch-tmp").exists() and (cd / "archive.json").exists()
    assert not list(full.vertical_dir(tcfg, a).glob("*.part")) if full.vertical_dir(tcfg, a).exists() else True
    q = json.loads((Path(tcfg.workspace.dir) / ".web_queue.json").read_text())
    assert not any(e["kind"] == "vertical" for lane in q["lanes"].values() for e in lane)
    assert c.get(f"/api/playlists/{PL}").json()["vertical_active"] == 0
    assert c.post(f"/api/playlists/{PL}/vertical/cancel").status_code == 409  # nothing left
    c.__exit__(None, None, None)
    c2 = client(tcfg)  # restart: nothing is restored
    c2.__enter__()
    assert not [j for j in c2.app.state.runner.jobs() if j.kind == "vertical"]
    c2.__exit__(None, None, None)


def test_ac9_cancel_one_job_by_episode_route(tcfg):
    make_ep(tcfg, height=1080)
    c = client(tcfg, vertical=fake_vertical([]))  # lifespan not started: the job stays queued
    assert c.post(f"/api/episodes/{VID}/vertical/cancel").status_code in (303, 401)  # needs login
    login(c)
    runner = c.app.state.runner
    assert c.post(f"/api/episodes/{VID}/vertical/cancel").status_code == 409  # no job
    assert c.post("/api/episodes/%2e%2e%2fwork/vertical/cancel").status_code in (404, 422)
    assert c.post("/api/episodes/-x/vertical/cancel").status_code in (404, 422)
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 202
    r = c.post(f"/api/episodes/{VID}/vertical/cancel")
    assert r.status_code == 200 and r.json()["cancelled"] == 1
    assert runner.latest_vertical(VID).status == "cancelled"
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]["job"]["status"] == "cancelled"
    assert c.post(f"/api/episodes/{VID}/vertical/cancel").status_code == 409
    again = c.post(f"/api/episodes/{VID}/vertical")  # can be queued again
    assert again.status_code == 202 and again.json()["job"]["status"] == "queued"


def test_ac9_cancel_leaves_other_job_kinds_alone(tcfg):
    make_ep(tcfg, height=1080)
    c = client(tcfg)
    login(c)
    runner = c.app.state.runner
    job, _ = runner.submit(VID, KIND_RENDER, lambda j: None)  # a Short render of the same video
    assert c.post(f"/api/episodes/{VID}/vertical/cancel").status_code == 409
    assert job.status == "queued"


def test_f3_signal_never_reaches_another_job_than_the_cancelled_one():
    """The interrupt / SIGINT are sent only while the cancelled job is still the slot's job (under the runner lock)."""
    gate = threading.Event()
    runner = JobRunner()

    def short(job):
        assert gate.wait(10)

    vjob_runner = JobRunner()  # a finished vertical job from its own runner stands for "the job that already left"
    stale, _ = vjob_runner.submit("v1", KIND_VERTICAL, lambda job: None)
    runner.start()
    s, _ = runner.submit("s1", KIND_RENDER, short)
    wait_until(lambda: runner.running().get(jobs_mod.RENDER) is s)
    with runner._lock:
        assert runner._signal_running_locked(jobs_mod.RENDER, stale) is False  # slot runs the Short now: no signal
    gate.set()
    assert runner.wait_idle(10)
    runner.stop(2)
    assert s.status == "done" and s.error is None
