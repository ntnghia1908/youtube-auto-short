"""CP8.38 snapshots and deletion safety; no server, socket or real AI."""

import json
from types import SimpleNamespace

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig
from auto_short.post import kept, logic, store
from auto_short.review import delete_episode, list_titles, set_title
from auto_short.review.names import hashtags
from auto_short.review.tombstone import list_tombstones, remove_tombstone
from auto_short.web.context import WebContext
from auto_short.workspace import WorkspaceError, atomic_write_json
from kept_post_helpers import NOW, make_episode as make_post_episode, write_posts
from post_helpers import EID

LATER = "2026-10-24T11:00:00Z"


@pytest.fixture
def cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(hashtags=("PhatPhap",)))


@pytest.mark.parametrize("episode_id", [EID, EID + ".kt"])
def test_delete_keeps_only_unticked_complete_snapshot(cfg, episode_id):
    """AC1/8: includes a no-longer-rendered clip; copy uses current title, not the burnt-in title."""
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=episode_id)
    source = write_posts(ws, posted=("k02",))
    set_title(episode_id, cfg, "k01", "Lời dạy đã sửa")
    ctx = WebContext.__new__(WebContext)
    ctx.config = cfg
    ctx.playlists = SimpleNamespace(hashtags_for=lambda eid: ["BoKinhRieng", "TinhDo"])
    titles = {c["clip_id"]: c["title"] for c in list_titles(episode_id, cfg)["clips"]}
    series, tags = ctx.post_series_and_tags(episode_id)

    def tab_text(entry):
        return ctx.post_entry_view(entry, ep_src=None, title=titles.get(entry["clip_id"]),
                                   header_fields=ctx.post_header_fields(episode_id),
                                   hashtags_list=hashtags(series, tags))["text"]

    expected = {e["clip_id"]: tab_text(e) for e in source["posts"]}
    cfg.post.image_dir.mkdir(parents=True)
    (cfg.post.image_dir / "shared.png").write_bytes(b"shared image outside episode")
    removed = delete_episode(episode_id, cfg, copy_text=tab_text)
    assert len(removed) == 2 and all(not p.exists() for p in removed)
    doc = kept.read(cfg, episode_id)
    assert set(doc) == {"schema_version", "episode_id", "title", "deleted_at", "posts"}
    assert doc["schema_version"] == 1 and doc["episode_id"] == episode_id
    assert doc["title"] == "Kinh Test tập 9"
    assert [e["clip_id"] for e in doc["posts"]] == ["k01", "k03"]
    for entry in doc["posts"]:
        original = store.find(source, entry["clip_id"])
        assert set(entry) == kept.ENTRY_KEYS
        assert entry["copy_text"] == expected[entry["clip_id"]]
        assert entry["copy_text"].endswith("#BoKinhRieng #TinhDo")
        assert all(entry[k] == original[k] for k in ("paragraphs", "image", "link", "posted_at"))
    assert doc["posts"][0]["short_title"] == "Tiêu đề k01"
    assert doc["posts"][0]["copy_text"].startswith("LỜI DẠY ĐÃ SỬA\n\n")
    assert doc["posts"][1]["short_title"] is None
    assert (cfg.post.image_dir / "shared.png").is_file()


def test_default_copy_reuses_p4_composer(cfg):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    doc = write_posts(ws)
    fields = json.loads((ws.dir / "titles.json").read_text())["header"]["fields"]
    result = kept.build(EID, cfg, now=NOW)
    assert result["deleted_at"] == NOW
    assert result["posts"][0]["copy_text"] == logic.compose_copy_text(
        title="Tiêu đề k01", paragraphs=doc["posts"][0]["paragraphs"], header_fields=fields,
        link=doc["posts"][0]["link"], hashtags=hashtags("Kinh Test", cfg.web.hashtags))


@pytest.mark.parametrize("kind", ["missing", "posted", "json", "schema"])
def test_delete_without_usable_unticked_posts(cfg, kind, caplog):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    path = ws.dir / store.POSTS_NAME
    if kind == "posted":
        write_posts(ws, posted=("k01", "k02", "k03"))
    elif kind == "json":
        path.write_text("{broken", encoding="utf-8")
    elif kind == "schema":
        atomic_write_json(path, {"posts": [{"paragraphs": []}]})
    delete_episode(EID, cfg)
    assert not ws.dir.exists()
    assert not kept.kept_path(cfg, EID).exists()
    if kind in ("json", "schema"):
        assert "skipping broken posts.json" in caplog.text


def test_failed_atomic_write_preserves_workspace_and_output(cfg, monkeypatch):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    before = {p: p.read_bytes() for root in (ws.dir, cfg.render.output_dir / EID)
              for p in root.rglob("*") if p.is_file()}

    def fail(*args):
        assert (cfg.workspace.dir / "_deleted" / f"{EID}.json").is_file()  # after tombstone
        raise OSError("disk full")

    monkeypatch.setattr(kept, "atomic_write_json", fail)
    with pytest.raises(OSError, match="disk full"):
        delete_episode(EID, cfg)
    assert all(p.is_file() and p.read_bytes() == content for p, content in before.items())
    assert not kept.kept_path(cfg, EID).exists()


def test_second_delete_merges_versions_preserves_ticks_and_deduplicates(cfg):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    delete_episode(EID, cfg)
    kept.set_posted(cfg, EID, "k01", True, now=NOW)
    old = kept.read(cfg, EID)["posts"]
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    doc = write_posts(ws)
    changed = store.with_fields(doc, ["k01", "k02", "k03"], "k02", {"paragraphs": ["Bài mới khác chữ."]}, now=LATER)
    store.write(ws.dir / store.POSTS_NAME, changed)
    delete_episode(EID, cfg)
    merged = kept.read(cfg, EID)["posts"]
    assert merged[:3] == old and len(merged) == 4
    assert merged[-1]["clip_id"] == "k02" and merged[-1]["paragraphs"] == ["Bài mới khác chữ."]
    kept.set_posted(cfg, EID, "k02", True, index=3, now=LATER)
    versions = kept.read(cfg, EID)["posts"]
    assert versions[1]["posted_at"] is None and versions[3]["posted_at"] == LATER
    kept.set_posted(cfg, EID, "k02", False, index=3)
    assert kept.read(cfg, EID)["posts"][3]["posted_at"] is None
    assert kept.set_posted(cfg, EID, "missing", True) is None
    assert kept.set_posted(cfg, EID, "k02", True, index=0) is None


def test_independent_of_tombstone_and_recreated_workspace(cfg):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    delete_episode(EID, cfg)
    make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    assert not list_tombstones(cfg)
    assert [d["episode_id"] for d in kept.list_kept(cfg)] == [EID]
    assert remove_tombstone(cfg, EID)
    assert len(kept.list_kept(cfg)) == 1
    for entry in kept.read(cfg, EID)["posts"]:
        kept.set_posted(cfg, EID, entry["clip_id"], True)
    assert len(kept.list_kept(cfg)) == 1  # all posted does not auto-remove
    assert kept.remove(cfg, EID) and not kept.remove(cfg, EID)
    assert kept.set_posted(cfg, EID, "k01", True) is None


def test_list_newest_first_and_ignores_broken_snapshots(cfg, caplog):
    for eid, now in ((EID, NOW), (EID + ".kt", LATER)):
        ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id=eid)
        write_posts(ws)
        kept.write_kept(eid, cfg, now=now)
    assert [d["episode_id"] for d in kept.list_kept(cfg)] == [EID + ".kt", EID]
    kept.kept_path(cfg, EID).write_text("{}")
    assert [d["episode_id"] for d in kept.list_kept(cfg)] == [EID + ".kt"]
    assert "skipping kept posts" in caplog.text


def test_broken_existing_snapshot_blocks_delete_instead_of_overwriting(cfg):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    path = kept.kept_path(cfg, EID)
    path.parent.mkdir(parents=True)
    path.write_text("broken snapshot")
    with pytest.raises(kept.KeptPostsError):
        delete_episode(EID, cfg)
    assert ws.dir.is_dir() and (cfg.render.output_dir / EID).is_dir()
    assert path.read_text() == "broken snapshot"


@pytest.mark.parametrize("episode_id", ["../escape", "_private", "a/b"])
def test_rejects_invalid_snapshot_path(cfg, episode_id):
    with pytest.raises(WorkspaceError):
        kept.kept_path(cfg, episode_id)


@pytest.mark.parametrize("field,value", [("posted_at", "not a timestamp"), ("paragraphs", []),
                                        ("copy_text", 42), ("image", {}), ("clip_id", "")])
def test_validate_snapshot_entries(cfg, field, value):
    ws = make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    write_posts(ws)
    doc = kept.build(EID, cfg)
    doc["posts"][0][field] = value
    with pytest.raises(kept.KeptPostsError):
        kept.check(doc, EID)
