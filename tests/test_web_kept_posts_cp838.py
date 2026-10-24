"""CP8.38 API integration. ORCHESTRATOR runs these where TestClient sockets are available."""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.post import kept, store  # noqa: E402
from auto_short.review import set_title  # noqa: E402
from auto_short.workspace import atomic_write_json  # noqa: E402
from image_fixtures import make_png  # noqa: E402
from kept_post_helpers import make_episode as make_post_episode, write_posts  # noqa: E402
from post_helpers import EID  # noqa: E402
from web_helpers import login, make_app  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images"))


def client(cfg):
    return TestClient(make_app(cfg, render=lambda *a, **kw: SimpleNamespace(ran=False),
                               post_compose=lambda *a, **kw: None, post_preflight=lambda c: None),
                      follow_redirects=False)


@pytest.mark.parametrize("episode_id", [EID, EID + ".kt"])
def test_kept_posts_delete_copy_tick_and_remove(cfg, episode_id):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=episode_id)
    write_posts(ws, posted=("k02",))
    set_title(episode_id, cfg, "k01", "Lời dạy đã sửa")
    # A stored playlist's custom hashtags must be captured even for the .kt variant.
    playlist_id = "PLkeptPosts838"
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{playlist_id}.json",
                      {"playlist_id": playlist_id, "entries": [{"video_id": EID}], "hashtags": ["TinhDo"]})
    cfg.post.image_dir.mkdir(parents=True)
    (cfg.post.image_dir / "shared.png").write_bytes(make_png(2, 2))
    with client(cfg) as c:
        assert c.get("/api/kept-posts").status_code == 401
        assert c.post(f"/api/kept-posts/{episode_id}/k01/posted", json={"value": True}).status_code == 401
        assert c.delete(f"/api/kept-posts/{episode_id}").status_code == 401
        login(c)
        assert c.get("/api/kept-posts").json() == {"episodes": []}
        assert c.get(f"/api/episodes/{episode_id}").json()["post_unticked"] == 1
        row = next(r for r in c.get("/api/storage").json()["episodes"] if r["id"] == episode_id)
        assert row["post_unticked"] == 1  # excludes k03, which is no longer rendered
        before = {p["clip_id"]: p["text"] for p in c.get(f"/api/episodes/{episode_id}/posts").json()["posts"]}
        assert before["k01"].startswith("LỜI DẠY ĐÃ SỬA\n\n") and before["k01"].endswith("#TinhDo")
        assert c.delete(f"/api/episodes/{episode_id}").status_code == 200
        assert c.get(f"/api/episodes/{episode_id}").status_code == 404
        data = c.get("/api/kept-posts").json()["episodes"]
        assert len(data) == 1
        assert [p["clip_id"] for p in data[0]["posts"]] == ["k01", "k03"]
        for p in data[0]["posts"]:
            assert p["copy_text"] == before[p["clip_id"]] and p["image_missing"] is False
        assert c.get("/files/post-images/shared.png").status_code == 200
        for value in (True, False):
            response = c.post(f"/api/kept-posts/{episode_id}/k01/posted", json={"value": value})
            assert response.status_code == 200 and response.json()["posted"] is value
            saved = c.get("/api/kept-posts").json()["episodes"][0]["posts"][0]
            assert (saved["posted_at"] is not None) is value
        # The list survives a recreated episode and removal of its tombstone.
        make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=episode_id)
        assert c.delete(f"/api/deleted/{episode_id}").status_code == 200
        assert len(c.get("/api/kept-posts").json()["episodes"]) == 1
        (cfg.post.image_dir / "shared.png").unlink()
        missing = c.get("/api/kept-posts").json()["episodes"][0]["posts"][0]
        assert missing["image_missing"] is True and missing["copy_text"] == before["k01"]
        assert c.delete(f"/api/kept-posts/{episode_id}").status_code == 200
        assert c.delete(f"/api/kept-posts/{episode_id}").status_code == 404
        assert c.get("/api/kept-posts").json() == {"episodes": []}
        assert ws.dir.is_dir()  # removing snapshots does not delete the new workspace


def test_kept_post_route_validation_sorting_and_version_ticks(cfg):
    for eid, now in ((EID, "2026-10-24T10:00:00Z"), (EID + ".kt", "2026-10-24T11:00:00Z")):
        ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=eid)
        write_posts(ws)
        kept.write_kept(eid, cfg, now=now)
    doc = store.read_posts(ws.dir / store.POSTS_NAME, ws.episode_id)
    doc = store.with_fields(doc, ["k01", "k02", "k03"], "k01", {"paragraphs": ["Một phiên bản mới."]},
                            now="2026-10-24T12:00:00Z")
    store.write(ws.dir / store.POSTS_NAME, doc)
    kept.write_kept(ws.episode_id, cfg, now="2026-10-24T12:00:00Z")
    with client(cfg) as c:
        login(c)
        assert [d["episode_id"] for d in c.get("/api/kept-posts").json()["episodes"]] == [EID + ".kt", EID]
        base = f"/api/kept-posts/{EID}.kt/k01/posted"
        for value in (1, 0, "true", None, []):
            assert c.post(base, json={"value": value}).status_code == 422
        assert c.post(base, json={}).status_code == 422
        assert c.post(base + "?index=3", json={"value": True}).status_code == 200
        posts = c.get("/api/kept-posts").json()["episodes"][0]["posts"]
        assert posts[0]["posted_at"] is None and posts[3]["posted_at"] is not None
        assert c.post(base + "?index=1", json={"value": True}).status_code == 404
        assert c.post(f"/api/kept-posts/{EID}/missing/posted", json={"value": True}).status_code == 404
        assert c.post("/api/kept-posts/noSuchEpisode/k01/posted", json={"value": True}).status_code == 404
        assert c.post("/api/kept-posts/_invalid/k01/posted", json={"value": True}).status_code == 404
        assert c.delete("/api/kept-posts/_invalid").status_code == 404


def test_delete_route_write_failure_keeps_files_and_undoes_favorites(cfg, monkeypatch):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    with client(cfg) as c:
        login(c)
        undone = []
        monkeypatch.setattr(c.app.state.compilations, "keep_favorites", lambda eid: lambda: undone.append(eid))

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(kept, "atomic_write_json", fail)
        response = c.delete(f"/api/episodes/{EID}")
        assert response.status_code == 500 and "disk full" in response.json()["detail"]
        assert ws.dir.is_dir() and (cfg.render.output_dir / EID).is_dir()
        assert undone == [EID] and not kept.kept_path(cfg, EID).exists()


@pytest.mark.parametrize("kind", ["missing", "posted", "broken"])
def test_episode_post_unticked_zero_and_delete_without_kept_file(cfg, kind):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    if kind == "posted":
        write_posts(ws, posted=("k01", "k02", "k03"))
    elif kind == "broken":
        (ws.dir / store.POSTS_NAME).write_text("broken json")
    with client(cfg) as c:
        login(c)
        assert c.get(f"/api/episodes/{EID}").json()["post_unticked"] == 0
        assert c.delete(f"/api/episodes/{EID}").status_code == 200
        assert c.get("/api/kept-posts").json() == {"episodes": []}


def test_delete_blocked_by_queued_job_keeps_posts_in_workspace(cfg):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    with client(cfg) as c:
        login(c)
        c.post("/api/queue/pause", json={"mode": "now"})
        job, _ = c.app.state.runner.submit(EID, "post", SimpleNamespace(run=lambda job: None))
        assert job.status == "queued"
        assert c.delete(f"/api/episodes/{EID}").status_code == 409
        assert (ws.dir / store.POSTS_NAME).is_file() and not kept.kept_path(cfg, EID).exists()
