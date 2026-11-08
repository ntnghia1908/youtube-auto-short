"""PCX1 AC6: CLI selects the backlog safely; every rewrite uses fake media/Whisper/Codex."""
import pytest

from auto_short import cli
from auto_short.post import codex_text as ct, store
from post_helpers import EID, make_post_episode
from test_post_codex_helpers import Codex, Media, Whisper, seed


@pytest.mark.parametrize("flags,expected", [([], ["k02"]), (["--clips", "k01"], []),
                                           (["--clips", "k01,k02", "--include-posted"], ["k01", "k02"]),
                                           (["--all-ai"], ["k02"])])
def test_cli_codex_clip_selection(tmp_path, monkeypatch, flags, expected):
    cfg, path = seed(tmp_path)
    doc = store.read_posts(path, EID)
    doc["posts"][0]["posted_at"] = "2026-11-08T00:00:00Z"
    store.write(path, doc)
    # An empty episode is harmless when walking all posts.json files.
    make_post_episode(cfg.workspace.dir, cfg.render.output_dir, episode_id="anotherTest")
    other_path = cfg.workspace.dir / "anotherTest" / "posts.json"
    store.write(other_path, store.empty_posts("anotherTest"))
    monkeypatch.setattr(cli.config_mod, "load", lambda _: cfg)
    original = ct.rewrite_posts
    seen = []
    def fake(eid, config, clips=None, **kwargs):
        result = original(eid, config, clips, runner=Codex(), media_runner=Media(), whisper=Whisper(), **kwargs)
        seen.extend(result.rewritten)
        return result
    monkeypatch.setattr(ct, "rewrite_posts", fake)
    args = ["post", "codex"] + ([] if "--all-ai" in flags else [EID]) + flags
    assert cli.main(args) == 0
    assert seen == expected
    assert store.find(store.read_posts(path, EID), "k01")["posted_at"] is not None


@pytest.mark.parametrize("args", [[], ["--all-ai", "--include-posted"], [EID, "--all-ai"],
                                 [EID, "--clips", ""], [EID, "--clips", "k99"], ["../escape"]])
def test_cli_rejects_invalid_scope_without_running_codex(tmp_path, monkeypatch, args):
    cfg, _ = seed(tmp_path)
    monkeypatch.setattr(cli.config_mod, "load", lambda _: cfg)
    # No runner is injected: invalid input must be rejected before a real process can start.
    assert cli.main(["post", "codex", *args]) == 1


def test_cli_failure_returns_nonzero_keeps_post(tmp_path, monkeypatch):
    cfg, path = seed(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(cli.config_mod, "load", lambda _: cfg)
    original = ct.rewrite_posts
    monkeypatch.setattr(ct, "rewrite_posts", lambda eid, config, clips, **kw: original(
        eid, config, clips, runner=Codex(code=1, log="quota"), media_runner=Media(), whisper=Whisper(), **kw))
    assert cli.main(["post", "codex", EID, "--clips", "k01"]) == 1
    assert path.read_bytes() == before
