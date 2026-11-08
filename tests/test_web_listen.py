"""LISTEN1: file-only queue assembly and authenticated read endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_short.compilation import Item, store
from auto_short.review.logic import empty_review
from auto_short.web.listen import playlist_listen
from web_helpers import login, make_app, write_episode

PID = "PLlisten0001"
FIRST, SECOND, THIRD = "youtube0001", "youtube0002", "youtube0003"


def document():
    return {"playlist_id": PID, "title": "Kinh thử", "entries": [
        {"index": 2, "video_id": SECOND, "title": "Tập hai", "available": True},
        {"index": 1, "video_id": FIRST, "title": "Tập một", "available": True},
        {"index": 3, "video_id": THIRD, "title": "Chưa render", "available": True},
        {"index": 4, "video_id": "unavailable", "title": "Ẩn", "available": False},
    ]}


@pytest.fixture
def library(cfg):
    # Clip ids deliberately oppose manifest order; never sort them lexically.
    write_episode(cfg, FIRST, clips=("k09", "k01"), titles={"k09": "Chữ trong file"}, extra_shorts=[
        {"clip_id": "k10", "status": "skipped", "skip_reason": "rejected"},
        {"clip_id": "k11", "status": "skipped", "skip_reason": "untitled"},
    ])
    write_episode(cfg, FIRST + ".kt", clips=("k03", "k02"))
    write_episode(cfg, SECOND, clips=("k05",))
    write_episode(cfg, "unavailable", clips=("k01",))
    folder = Path(cfg.workspace.dir) / "_playlists"
    folder.mkdir(parents=True)
    (folder / (PID + ".json")).write_text(json.dumps(document()), encoding="utf-8")
    return cfg


def test_queue_order_fields_favorites_and_no_khaithi(library):  # AC1,2
    result = playlist_listen(library, document(), [Item(FIRST, "k09"), Item(FIRST + ".kt", "k02")])
    assert result["playlist_id"] == PID and result["title"] == "Kinh thử"
    items = result["items"]
    assert [(i["episode_id"], i["clip_id"]) for i in items] == [
        (FIRST, "k09"), (FIRST, "k01"), (FIRST + ".kt", "k03"), (FIRST + ".kt", "k02"), (SECOND, "k05")]
    assert [i["kind"] for i in items] == ["short", "short", "khaithi", "khaithi", "short"]
    assert [i["ep_index"] for i in items] == [1, 1, 1, 1, 2]
    assert items[2]["base_episode_id"] == FIRST and items[2]["ep_title"] == "Tập một"
    assert items[0]["title"] == "Chữ trong file" and items[0]["duration"] == 60.0
    assert items[0]["video_url"] == f"/files/{FIRST}/k09.mp4?v={'0' * 12}"
    assert all("audio_url" not in item for item in items)
    assert items[0]["fav"] == dict(playlist_id=PID, episode_id=FIRST, clip="k09", favorite=True)
    assert [i["fav"]["favorite"] for i in items] == [True, False, False, True, False]


def test_review_rejected_current_candidate_only(library):  # AC1: deletion before render commits
    review = empty_review(FIRST)
    review["rejected"] = [{"clip_id": "k09", "candidate_id": "c00001"},
                          {"clip_id": "k01", "candidate_id": "stale-candidate"}]
    (Path(library.workspace.dir) / FIRST / "review.json").write_text(json.dumps(review))
    items = playlist_listen(library, document(), [])["items"]
    assert [(i["episode_id"], i["clip_id"]) for i in items][:1] == [(FIRST, "k01")]
    assert not any(i["episode_id"] == FIRST and i["clip_id"] == "k09" for i in items)
    review = empty_review(FIRST + ".kt")
    review["rejected"] = [{"clip_id": "k03", "candidate_id": "c00001"},
                          {"clip_id": "k02", "candidate_id": "c00002"}]
    (Path(library.workspace.dir) / (FIRST + ".kt") / "review.json").write_text(json.dumps(review))
    assert all(i["kind"] == "short" for i in playlist_listen(library, document(), [])["items"])


def test_released_short_uses_episode_url_without_resolving_storage(library, monkeypatch):
    from auto_short.web import episodes
    (Path(library.render.output_dir) / FIRST / "shorts/k09.mp4").unlink()
    # The view is manifest-based, just like episode_view: no file probing or store calls.
    monkeypatch.setattr(episodes, "short_locations", lambda *a: pytest.fail("unnecessary locations read"))
    monkeypatch.setattr(episodes, "episode_view", lambda *a: pytest.fail("full episode view is too expensive"))
    assert playlist_listen(library, document(), [])["items"][0]["video_url"].endswith("?v=" + "0" * 12)


def test_unrendered_episode_and_khaithi_are_omitted(library):  # AC1,2
    write_episode(library, SECOND + ".kt")
    (Path(library.render.output_dir) / (SECOND + ".kt") / "render_manifest.json").unlink()
    (Path(library.workspace.dir) / THIRD).mkdir()
    items = playlist_listen(library, document(), [])["items"]
    assert items[-1]["episode_id"] == SECOND
    assert all(i["episode_id"] not in (THIRD, SECOND + ".kt") for i in items)
    assert playlist_listen(library, {**document(), "entries": []}, [])["items"] == []


def test_codes_use_download_labels_positions_and_width_including_skipped(library):  # AC24
    from auto_short.khaithi import KhaiThi
    from auto_short.web import episodes as ep
    for eid in (FIRST, FIRST + ".kt"):
        (Path(library.workspace.dir) / eid / "titles.json").write_text(json.dumps({"header": {"fields": {"episode": "20"}}}))
    (Path(library.workspace.dir) / (FIRST + ".kt") / "khaithi.json").write_text(json.dumps(KhaiThi(FIRST, 4, 7).to_json()))
    path = Path(library.render.output_dir) / FIRST / "render_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["shorts"].insert(0, {"clip_id": "gone", "status": "skipped", "skip_reason": "rejected"})
    manifest["shorts"] += [{"clip_id": f"skip{n}", "status": "skipped"} for n in range(95)]
    path.write_text(json.dumps(manifest))
    items = playlist_listen(library, document(), [])["items"]
    assert [i["code"] for i in items[:4]] == ["T20_S002", "T20_S003", "T20_KT01", "T20_KT02"]
    assert items[0]["number"] == 2 and items[0]["total"] == 100 and items[0]["ep_label"] == "20"
    for item in items:
        eid = item["episode_id"]
        name = ep._names(library, eid, ep.render_manifest(library, eid))[item["clip_id"]]
        assert name.startswith(item["code"] + "_")


def endpoint(app):
    # Same nested router traversal as test_web_watch_party / test_store_download.
    routes = list(app.routes)
    while routes:
        route = routes.pop(0)
        if hasattr(route, "original_router"):
            routes[0:0] = route.original_router.routes
        elif getattr(route, "path", None) == "/api/playlists/{playlist_id}/listen":
            return route.endpoint
    raise AssertionError("missing listen route")


def test_route_fresh_favorites_and_404(library):
    app = make_app(library)
    get = endpoint(app)
    assert get("invalid!").status_code == 404
    assert get("PLmissing001").status_code == 404
    assert get(PID)["items"][0]["fav"]["favorite"] is False
    store.write_favorites(app.state.compilations.folder(PID), [Item(FIRST, "k09")])
    assert get(PID)["items"][0]["fav"]["favorite"] is True


def test_http_listen_auth_404_and_queue(library):  # AC1,2: full middleware path
    from fastapi.testclient import TestClient
    with TestClient(make_app(library), follow_redirects=False) as client:
        path = f"/api/playlists/{PID}/listen"
        assert client.get(path).status_code == 401
        login(client)
        assert client.get("/api/playlists/PLmissing001/listen").status_code == 404
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == playlist_listen(library, document(), [])
