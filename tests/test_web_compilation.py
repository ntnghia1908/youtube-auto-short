"""CP8.33: favourites (G9), compilation routes + job (G2-G7, G10) with tiny lavfi clips; auth, restart, delete."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

pytest.importorskip("fastapi")

from auto_short import compilation as comp  # noqa: E402
from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.routes import episodes as episodes_routes, episode_edit as episode_edit_routes  # noqa: E402
from auto_short.web.jobs import RENDER, compilation_key  # noqa: E402

from compilation_helpers import PL, duration_of, frame_color, make_series  # noqa: E402
from web_helpers import login, web_client as client  # noqa: E402

V1, V2, V3 = "aaaaaaaaaa1", "bbbbbbbbbb2", "cccccccccc3"
K1, K2, K3 = V1 + ".kt", V2 + ".kt", V3 + ".kt"
BASE = f"/api/playlists/{PL}"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    (tmp_path / "images").mkdir()
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images"))


@pytest.fixture
def series(tcfg, tmp_path):
    # playlist order is reversed on purpose: G1 order is by episode number (3 < 5 < 9)
    make_series(tcfg, tmp_path, [(V3, "9", [("blue", 2)]), (V1, "3", [("red", 2), ("white", 1)]),
                                 (V2, "5", [("green", 3)])])
    return tcfg


def heart(c, eid, clip, on=True):
    return c.post(f"{BASE}/favorites", json={"episode_id": eid, "clip": clip, "favorite": on})


def wait_done(c, timeout=30):
    assert c.app.state.runner.wait_idle(timeout)


def item(eid, clip):
    return {"episode_id": eid, "clip": clip}


def listing(c):
    return c.get(f"{BASE}/compilations").json()


# --- AC5 / AC9: auth and validation ---------------------------------------------------------------------------

def test_routes_need_login(series):
    with client(series) as c:
        assert c.get(f"/playlists/{PL}/favorites").status_code == 303
        assert c.get(f"/playlists/{PL}/favorites").headers["location"].startswith("/login")
        assert c.get(f"{BASE}/compilations").status_code == 401
        assert c.post(f"{BASE}/compilations", json={}).status_code == 401
        assert c.post(f"{BASE}/favorites", json={}).status_code == 401
        assert c.delete(f"{BASE}/compilations/0123456789ab").status_code == 401
        assert c.get(f"/files/playlists/{PL}/compilations/0123456789ab.mp4").status_code == 401
        login(c)
        assert c.get(f"/playlists/{PL}/favorites").status_code == 200
        assert c.get("/playlists/bad!/favorites").status_code == 404
        assert c.get("/api/playlists/PLunknown000000/compilations").status_code == 404
        assert c.delete(f"{BASE}/compilations/zz").status_code == 404
        assert c.delete(f"{BASE}/compilations/0123456789ab").status_code == 404
        assert c.get(f"/files/playlists/{PL}/compilations/0123456789ab.mp4").status_code == 404


# --- AC9: favourites ----------------------------------------------------------------------------------------------

def test_favorites_toggle_idempotent_ordered(series):
    path = Path(series.render.output_dir) / "_compilations" / PL / "favorites.json"
    with client(series) as c:
        login(c)
        assert heart(c, K3, "k01").json()["count"] == 1
        assert heart(c, K1, "k02").json()["count"] == 2
        assert heart(c, K1, "k02").json()["count"] == 2  # idempotent
        assert heart(c, K2, "k01").status_code == 200
        items = json.loads(path.read_text())["items"]
        assert [(i["episode_id"], i["clip"]) for i in items] == [(K1, "k02"), (K2, "k01"), (K3, "k01")]  # G1 order
        assert heart(c, K2, "k01", False).json()["count"] == 2
        assert heart(c, K2, "k01", False).json()["count"] == 2  # idempotent off
        assert c.get(f"{BASE}").json()["favorites_count"] == 2
        # outside the bộ kinh / not a khai thị / not rendered / malformed
        assert heart(c, "dddddddddd4.kt", "k01").status_code == 400
        assert heart(c, V1, "k01").status_code == 400
        assert heart(c, K1, "k99").status_code == 400
        assert heart(c, "../x", "k01").status_code == 400
        assert c.post(f"{BASE}/favorites", json={"episode_id": K1, "clip": "k01", "favorite": "yes"}).status_code == 422
        assert c.post("/api/playlists/PLunknown000000/favorites",
                      json={"episode_id": K1, "clip": "k01", "favorite": True}).status_code == 404
        # the episode page knows the heart
        ep = c.get(f"/api/episodes/{K1}").json()
        assert ep["favorites"]["playlist_id"] == PL
        assert {s["clip_id"]: s["favorite"] for s in ep["shorts"]} == {"k01": False, "k02": True}


def test_stale_favorite_is_dimmed_and_not_used_by_auto(series):
    with client(series) as c:
        login(c)
        heart(c, K1, "k01")
        heart(c, K2, "k01")
        (Path(series.render.output_dir) / K2 / "shorts" / "k01.mp4").unlink()  # file gone
        fav = {(f["episode_id"], f["clip"]): f for f in listing(c)["favorites"]}
        assert fav[(K1, "k01")]["usable"] and not fav[(K2, "k01")]["usable"]
        assert fav[(K2, "k01")]["favorite"]  # still shown, can be un-hearted
        r = c.post(f"{BASE}/compilations", json={"mode": "auto", "minutes": 1})
        assert r.status_code == 202
        assert {(i["episode_id"], i["clip"]) for i in
                comp.store.read_doc(Path(series.render.output_dir) / "_compilations" / PL, r.json()["cid"])["items"]} == {(K1, "k01")}
        wait_done(c)
        assert heart(c, K2, "k01", False).json()["count"] == 1


# --- AC1 / AC4 / AC6 / AC7 / AC8: concat ------------------------------------------------------------------------------

def test_concat_end_to_end_reuse_download_delete(series):
    out_root = Path(series.render.output_dir)
    with client(series) as c:
        login(c)
        body = {"mode": "concat", "items": [item(K3, "k01"), item(K1, "k01"), item(K2, "k01")]}  # unsorted
        r = c.post(f"{BASE}/compilations", json=body)
        assert r.status_code == 202 and r.json()["created"]
        cid = r.json()["cid"]
        job = c.app.state.runner.latest(compilation_key(PL, cid))
        assert job.kind == "compilation" and job.steps[0].lane == RENDER
        wait_done(c)
        view = next(v for v in listing(c)["compilations"] if v["cid"] == cid)
        assert view["state"] == "done" and view["mode"] == "concat" and view["segments"] == 3
        mp4 = out_root / "_compilations" / PL / f"{cid}.mp4"
        srcs = [out_root / k / "shorts" / "k01.mp4" for k in (K1, K2, K3)]  # G1: tập 3, 5, 9
        total = sum(duration_of(p) for p in srcs)
        assert abs(duration_of(mp4) - total) <= 0.1
        starts = [0.0, duration_of(srcs[0]), duration_of(srcs[0]) + duration_of(srcs[1])]
        assert [frame_color(mp4, t + 0.5) for t in starts] == ["r", "g", "b"]
        # G7: name, description with chapters
        assert view["download_name"] == "Bộ thử - Khai thị T3-T9 (3 đoạn).mp4"
        lines = view["description"].split("\n\n")[0].split("\n")
        assert lines[0] == "00:00 Khai thị 3.1" and lines[1].startswith("00:02 Khai thị 5.1")
        assert lines[2].startswith("00:05 Khai thị 9.1")
        assert view["description"].rstrip().endswith("#TịnhKhông #LờiPhậtDạy #TịnhĐộ #NiệmPhật")
        dl = c.get(view["download_url"])
        assert dl.status_code == 200 and dl.headers["content-type"] == "video/mp4"
        assert unquote(dl.headers["content-disposition"].split("filename*=UTF-8''")[1]) == view["download_name"]
        # AC4: same request -> same cid, no new job; another selection -> another cid
        jobs_before = len(c.app.state.runner.jobs())
        again = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": body["items"][::-1]})
        assert again.status_code == 200 and again.json() == {**again.json(), "cid": cid, "created": False}
        assert len(c.app.state.runner.jobs()) == jobs_before
        other = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
        assert other.json()["cid"] != cid
        wait_done(c)
        # AC8: deleting an episode does not touch the namespace; deleting the compilation removes mp4 + json
        assert c.delete(f"/api/episodes/{K3}").status_code == 200
        assert mp4.is_file()
        assert c.delete(f"{BASE}/compilations/{cid}").status_code == 200
        assert not mp4.exists() and not mp4.with_suffix(".json").exists()
        assert c.delete(f"{BASE}/compilations/{cid}").status_code == 404
        assert c.get(f"/files/playlists/{PL}/compilations/{cid}.mp4").status_code == 404


def test_concat_validation_queues_nothing(series):
    with client(series) as c:
        login(c)
        runner = c.app.state.runner
        bad = [
            {"mode": "concat", "items": [item(K1, "k01")]},  # fewer than two
            {"mode": "concat", "items": [item(K1, "k01"), item(K1, "k01")]},  # duplicate
            {"mode": "concat", "items": [item(K1, "k01"), item("dddddddddd4.kt", "k01")]},  # outside the bộ kinh
            {"mode": "concat", "items": [item(V1, "k01"), item(K1, "k01")]},  # a Short episode
            {"mode": "concat", "items": [item(K1, "k01"), item(K1, "k77")]},  # not rendered
            {"mode": "concat", "items": "x"},
            {"mode": "loop", "item": item(K1, "k01"), "minutes": 0},
            {"mode": "loop", "item": item(K1, "k01"), "minutes": 721},
            {"mode": "loop", "item": item(K1, "k01"), "minutes": 1.5},
            {"mode": "loop", "item": item("dddddddddd4.kt", "k01"), "minutes": 5},
            {"mode": "auto", "minutes": 5},  # no favourite
            {"mode": "nope"},
        ]
        for body in bad:
            r = c.post(f"{BASE}/compilations", json=body)
            assert r.status_code == 400, body
        assert runner.jobs() == []
        assert c.post("/api/playlists/PLunknown000000/compilations", json=bad[0]).status_code == 404


# --- AC2 / AC10: loop and auto -----------------------------------------------------------------------------------------

def test_loop_repeats_and_limit(series):
    series = Config(workspace=series.workspace, render=series.render, post=series.post,
                    compilation=comp_cfg(1))
    with client(series) as c:
        login(c)
        src = Path(series.render.output_dir) / K2 / "shorts" / "k01.mp4"
        d = duration_of(src)
        r = c.post(f"{BASE}/compilations", json={"mode": "loop", "item": item(K2, "k01"), "minutes": 1})
        assert r.status_code == 202
        n = -(-60 // d) if False else int(-(-60 // d))
        view = r.json()["compilation"]
        assert view["segments"] == n and view["repeat"] == n and r.json()["compilation"]["preview"]["repeat"] == n
        wait_done(c)
        v = next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])
        assert abs(duration_of(Path(series.render.output_dir) / "_compilations" / PL / f"{v['cid']}.mp4") - n * d) <= 0.1
        assert v["download_name"] == f"Bộ thử - T5_KT01 lặp {n} lần.mp4"
        assert v["description"].split("\n\n")[0] == "Khai thị 5.1" and v["chapters"] == []
        # max_minutes = 1: asking 2 minutes is refused before any job is queued
        jobs = len(c.app.state.runner.jobs())
        assert c.post(f"{BASE}/compilations", json={"mode": "loop", "item": item(K2, "k01"), "minutes": 2}).status_code == 400
        assert len(c.app.state.runner.jobs()) == jobs


def comp_cfg(minutes):
    from auto_short.config import CompilationConfig
    return CompilationConfig(max_minutes=minutes)


def test_auto_round_robin(series):
    with client(series) as c:
        login(c)
        for eid, clip in ((K1, "k01"), (K2, "k01"), (K3, "k01")):  # 2 s, 3 s, 2 s (+ ~tiny container rounding)
            heart(c, eid, clip)
        # a favourite list that is shorter than T wraps; the last clip is never cut
        r = c.post(f"{BASE}/compilations", json={"mode": "auto", "minutes": 1})
        assert r.status_code == 202
        doc = comp.store.read_doc(Path(series.render.output_dir) / "_compilations" / PL, r.json()["cid"])
        items = [(i["episode_id"], i["clip"]) for i in doc["items"]]
        assert doc["mode"] == "auto" and items[:3] == [(K1, "k01"), (K2, "k01"), (K3, "k01")]
        cycle = [(K1, "k01"), (K2, "k01"), (K3, "k01")]
        assert items == [cycle[n % 3] for n in range(len(items))]  # round robin in G1 order
        srcs = {k: duration_of(Path(series.render.output_dir) / k / "shorts" / "k01.mp4") for k in (K1, K2, K3)}
        total = sum(srcs[e] for e, _ in items)
        assert total >= 60 > total - srcs[items[-1][0]]  # stops at the first clip that reaches T, never cut
        assert r.json()["compilation"]["preview"]["rounds"] == -(-len(items) // 3)
        wait_done(c)
        v = next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])
        assert v["state"] == "done" and v["download_name"].startswith("Bộ thử - Khai thị T3-T9 (")
        assert v["description"].startswith("00:00 Khai thị 3.1\n00:02 Khai thị 5.1")
        # identical to the concat of the same expanded list (G10: same cid)
        again = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
        assert again.json()["cid"] != r.json()["cid"]


# --- AC3 / AC6: failure and restart ------------------------------------------------------------------------------------

def test_failed_job_marks_failed_and_leaves_no_temp(series):
    with client(series) as c:
        login(c)

        def boom(cmd):
            if cmd[0] == "ffmpeg":
                return subprocess.CompletedProcess(cmd, 1, "", "kaboom")
            return comp.run_command(cmd)

        c.app.state.compilations._probe_runner = boom
        r = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
        wait_done(c)
        v = next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])
        assert v["state"] == "failed" and "kaboom" in v["error"]
        folder = Path(series.render.output_dir) / "_compilations" / PL
        assert sorted(p.name for p in folder.iterdir()) == [f"{r.json()['cid']}.json"]  # no mp4, no temp dir
        assert c.get(v["download_url"] or f"/files/playlists/{PL}/compilations/{v['cid']}.mp4").status_code == 404
        # a failed one can be asked again (retry, new job)
        c.app.state.compilations._probe_runner = comp.run_command
        again = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
        assert again.status_code == 202 and again.json()["cid"] == r.json()["cid"]
        wait_done(c)
        assert next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])["state"] == "done"


def test_job_survives_restart(series):
    queue = Path(series.workspace.dir) / app_mod.QUEUE_FILE
    c1 = client(series)  # no lifespan: the lanes never start, the job stays queued
    login(c1)
    r = c1.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
    cid = r.json()["cid"]
    assert r.status_code == 202
    saved = json.loads(queue.read_text())
    entries = [e for lane in saved["lanes"].values() for e in lane]
    assert [(e["kind"], e["episode_id"]) for e in entries] == [("compilation", compilation_key(PL, cid))]
    assert listing(c1)["compilations"][0]["state"] == "queued"
    with client(series) as c2:  # "restart": the queue file is restored, the lane runs the job
        login(c2)
        wait_done(c2)
        assert next(x for x in listing(c2)["compilations"] if x["cid"] == cid)["state"] == "done"
        assert (Path(series.render.output_dir) / "_compilations" / PL / f"{cid}.mp4").is_file()
    # a saved job whose compilation file is gone cannot be recreated
    assert c2.app.state.compilations.rebuild(compilation_key(PL, "0" * 12), {"playlist_id": PL, "cid": "0" * 12,
                                              "mode": "concat", "items": [item(K1, "k01")], "repeat": 1}) is None


def test_queued_compilation_job_does_not_break_episode_and_monitor_views(series):
    c = client(series)
    login(c)
    c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(K2, "k01")]})
    assert all(not e["id"].startswith("compilation") for e in c.get("/api/episodes").json()["episodes"])
    assert c.get("/api/monitor/queue").status_code == 200
    assert c.get("/api/queue").status_code == 200
    assert c.delete(f"{BASE}/compilations/{listing(c)['compilations'][0]['cid']}").status_code == 409  # still queued


# --- G11 / AC12: favourites survive deleting the khai thị episode -----------------------------------------------------

def folder_of(cfg) -> Path:
    return Path(cfg.render.output_dir) / "_compilations" / PL


def test_delete_episode_keeps_hearted_clips(series):
    out = Path(series.render.output_dir)
    with client(series) as c:
        login(c)
        heart(c, K1, "k01")
        heart(c, K1, "k02")
        heart(c, K2, "k01")
        src = out / K1 / "shorts" / "k01.mp4"
        want = duration_of(src)
        assert c.delete(f"/api/episodes/{K1}").status_code == 200
        assert not (Path(series.workspace.dir) / K1).exists() and not (out / K1).exists()
        kept = folder_of(series) / "kept" / K1
        assert sorted(p.name for p in kept.iterdir()) == ["k01.mp4", "k02.mp4"]
        favs = json.loads((folder_of(series) / "favorites.json").read_text())["items"]
        snap = next(f for f in favs if f["episode_id"] == K1 and f["clip"] == "k01")["kept"]
        assert snap["path"] == f"kept/{K1}/k01.mp4" and snap["title"] == "Khai thị 3.1" and snap["episode_number"] == "3"
        assert (snap["clip_number"], snap["clip_total"]) == (1, 2) and abs(snap["duration"] - want) <= 0.1
        assert "kept" not in next(f for f in favs if f["episode_id"] == K2)
        view = listing(c)
        by = {(f["episode_id"], f["clip"]): f for f in view["favorites"]}
        assert by[(K1, "k01")]["kept"] and by[(K1, "k01")]["usable"] and by[(K1, "k01")]["code"] == "T3_KT01"
        assert not by[(K2, "k01")]["kept"]
        # concat / loop / auto work with the kept files, in G1 order, next to a live clip
        r = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K2, "k01"), item(K1, "k02"), item(K1, "k01")]})
        assert r.status_code == 202
        r2 = c.post(f"{BASE}/compilations", json={"mode": "loop", "item": item(K1, "k02"), "minutes": 1})
        r3 = c.post(f"{BASE}/compilations", json={"mode": "auto", "minutes": 1})
        assert r2.status_code == 202 and r3.status_code == 202
        wait_done(c)
        states = {v["cid"]: v for v in listing(c)["compilations"]}
        assert all(states[x.json()["cid"]]["state"] == "done" for x in (r, r2, r3))
        v = states[r.json()["cid"]]
        assert v["download_name"] == "Bộ thử - Khai thị T3-T5 (3 đoạn).mp4"
        assert v["description"].startswith("00:00 Khai thị 3.1\n00:02 Khai thị 3.2")
        # un-hearting a kept item deletes the kept file; a live one has none
        assert heart(c, K1, "k01", False).status_code == 200
        assert not (kept / "k01.mp4").exists() and (kept / "k02.mp4").exists()
        assert heart(c, K1, "k02", False).status_code == 200
        assert not (folder_of(series) / "kept").exists()
        # re-hearting a deleted episode's clip is refused (not rendered any more)
        assert heart(c, K1, "k01").status_code == 400


def test_delete_without_favorites_is_unchanged_and_failure_keeps_everything(series, monkeypatch):
    out = Path(series.render.output_dir)
    with client(series) as c:
        login(c)
        assert c.delete(f"/api/episodes/{K3}").status_code == 200  # no heart: nothing kept
        assert not (folder_of(series) / "kept").exists() and not (out / K3).exists()
        heart(c, K1, "k01")
        before = (folder_of(series) / "favorites.json").read_text()
        src = out / K1 / "shorts" / "k01.mp4"

        def boom(*a, **k):
            raise app_mod.ReviewError("disk")

        monkeypatch.setattr(episodes_routes, "delete_episode", boom)
        assert c.delete(f"/api/episodes/{K1}").status_code == 500
        assert src.is_file() and (folder_of(series) / "favorites.json").read_text() == before
        assert not (folder_of(series) / "kept" / K1 / "k01.mp4").exists()
        # a failure while keeping: nothing is deleted either
        monkeypatch.undo()
        monkeypatch.setattr("auto_short.web.compilations._move", boom)
        r = c.delete(f"/api/episodes/{K1}")
        assert r.status_code == 500 and (Path(series.workspace.dir) / K1).is_dir() and src.is_file()


def test_rejecting_a_favorite_clip_drops_its_heart(series, monkeypatch):
    with client(series) as c:  # lanes not started: the render job just stays queued
        login(c)
        heart(c, K1, "k01")
        heart(c, K1, "k02")
        monkeypatch.setattr(episode_edit_routes, "reject_clip", lambda eid, cfg, clip: True)
        r = c.post(f"/api/episodes/{K1}/shorts/k01/delete")
        assert r.status_code == 202, r.text
        left = json.loads((folder_of(series) / "favorites.json").read_text())["items"]
        assert [(i["episode_id"], i["clip"]) for i in left] == [(K1, "k02")]


# --- Amendment 2 / AC13: Shorts behave like khai thị ---------------------------------------------------------------

@pytest.fixture
def mixed(tcfg, tmp_path):
    make_series(tcfg, tmp_path, [(V1, "3", [("red", 2)], [("white", 1), ("blue", 2)]),
                                 (V2, "5", [("green", 3)], [("white", 1)])])
    return tcfg


def comp_doc(cfg, cid):
    return comp.store.read_doc(folder_of(cfg), cid)


def test_short_heart_toggle_and_listing(mixed):
    with client(mixed) as c:
        login(c)
        assert heart(c, V1, "s02").json()["count"] == 1
        assert heart(c, V1, "s02").json()["count"] == 1  # idempotent
        assert heart(c, K1, "k01").json()["count"] == 2
        assert heart(c, V1, "s99").status_code == 400  # not rendered
        assert heart(c, "dddddddddd4", "s01").status_code == 400  # outside the bộ kinh
        ep = c.get(f"/api/episodes/{V1}").json()
        assert ep["favorites"]["playlist_id"] == PL
        assert {s["clip_id"]: s["favorite"] for s in ep["shorts"]} == {"s01": False, "s02": True}
        assert c.get(BASE).json()["favorites_count"] == 2
        favs = listing(c)["favorites"]
        assert [(f["kind"], f["code"]) for f in favs] == [("short", "T3_S02"), ("khaithi", "T3_KT01")]  # Shorts first
        assert heart(c, V1, "s02", False).json()["count"] == 1


def test_mixed_concat_order_name_and_description(mixed):
    out = Path(mixed.render.output_dir)
    with client(mixed) as c:
        login(c)
        items = [item(K2, "k01"), item(V2, "s01"), item(K1, "k01"), item(V1, "s02")]
        r = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": items})
        assert r.status_code == 202
        wait_done(c)
        v = next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])
        assert v["state"] == "done" and v["download_name"] == "Bộ thử - Short + Khai thị T3-T5 (4 đoạn).mp4"
        lines = v["description"].split("\n\n")[0].split("\n")
        assert [ln.split(" ", 1)[1] for ln in lines] == ["Short 3.2", "Khai thị 3.1", "Short 5.1", "Khai thị 5.1"]
        mp4 = out / "_compilations" / PL / f"{r.json()['cid']}.mp4"
        assert [frame_color(mp4, t) for t in (0.5, 2.5, 4.5, 5.5)] == ["b", "r", "w", "g"]  # S02, KT01, S01(5), KT01(5)
        only = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(V1, "s01"), item(V1, "s02")]})
        wait_done(c)
        assert next(x for x in listing(c)["compilations"] if x["cid"] == only.json()["cid"])["download_name"] \
            == "Bộ thử - Short T3 (2 đoạn).mp4"


def test_loop_of_a_short_name(mixed):
    with client(mixed) as c:
        login(c)
        r = c.post(f"{BASE}/compilations", json={"mode": "loop", "item": item(V1, "s02"), "minutes": 1})
        assert r.status_code == 202
        wait_done(c)
        v = next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])
        n = v["repeat"]
        assert v["state"] == "done" and v["download_name"] == f"Bộ thử - T3_S02 lặp {n} lần.mp4"
        assert v["description"].split("\n\n")[0] == "Short 3.2"


def test_auto_with_kinds_filter(mixed):
    with client(mixed) as c:
        login(c)
        for eid, clip in ((V1, "s01"), (K1, "k01"), (V2, "s01")):
            heart(c, eid, clip)

        def run(kinds):
            body = {"mode": "auto", "minutes": 1} if kinds is None else {"mode": "auto", "minutes": 1, "kinds": kinds}
            r = c.post(f"{BASE}/compilations", json=body)
            assert r.status_code in (200, 202), r.text  # 200: the same spec again (G4)
            return [(i["episode_id"], i["clip"]) for i in comp_doc(mixed, r.json()["cid"])["items"]]

        both = run(None)
        assert both[:3] == [(V1, "s01"), (K1, "k01"), (V2, "s01")]
        assert run(["short", "khaithi"]) == both
        assert {i for i, _ in run(["short"])} == {V1, V2}
        assert run(["short"])[:2] == [(V1, "s01"), (V2, "s01")]
        assert {i for i, _ in run(["khaithi"])} == {K1} and set(run(["khaithi"])) == {(K1, "k01")}
        wait_done(c)
        for bad in ([], ["x"], "short"):
            assert c.post(f"{BASE}/compilations", json={"mode": "auto", "minutes": 1, "kinds": bad}).status_code == 400
        heart(c, V1, "s01", False)
        heart(c, V2, "s01", False)
        r = c.post(f"{BASE}/compilations", json={"mode": "auto", "minutes": 1, "kinds": ["short"]})
        assert r.status_code == 400  # no usable Short favourite left


def test_delete_short_episode_keeps_favorite_shorts(mixed):
    out = Path(mixed.render.output_dir)
    with client(mixed) as c:
        login(c)
        heart(c, V1, "s01")
        heart(c, V1, "s02")
        heart(c, K1, "k01")
        assert c.delete(f"/api/episodes/{V1}").status_code == 200
        assert not (out / V1).exists() and (out / K1).exists()
        kept = folder_of(mixed) / "kept" / V1
        assert sorted(p.name for p in kept.iterdir()) == ["s01.mp4", "s02.mp4"]
        by = {(f["episode_id"], f["clip"]): f for f in listing(c)["favorites"]}
        assert by[(V1, "s02")]["kept"] and by[(V1, "s02")]["code"] == "T3_S02" and by[(V1, "s02")]["kind"] == "short"
        assert not by[(K1, "k01")]["kept"]
        # kept Short + live khai thị still join; the khai thị episode delete keeps its own favourite
        r = c.post(f"{BASE}/compilations", json={"mode": "concat", "items": [item(K1, "k01"), item(V1, "s02")]})
        assert r.status_code == 202
        wait_done(c)
        assert next(x for x in listing(c)["compilations"] if x["cid"] == r.json()["cid"])["state"] == "done"
        assert c.delete(f"/api/episodes/{K1}").status_code == 200
        assert (folder_of(mixed) / "kept" / K1 / "k01.mp4").is_file()
        assert heart(c, V1, "s02", False).status_code == 200 and not (kept / "s02.mp4").exists()


def test_rejecting_a_favorite_short_drops_its_heart(mixed, monkeypatch):
    with client(mixed) as c:
        login(c)
        heart(c, V1, "s01")
        heart(c, V1, "s02")
        monkeypatch.setattr(episode_edit_routes, "reject_clip", lambda eid, cfg, clip: True)
        assert c.post(f"/api/episodes/{V1}/shorts/s01/delete").status_code == 202
        left = json.loads((folder_of(mixed) / "favorites.json").read_text())["items"]
        assert [(i["episode_id"], i["clip"]) for i in left] == [(V1, "s02")]
