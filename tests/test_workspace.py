import json
import os

from auto_short import hashing
from auto_short.config import ConfigError, load
from auto_short.workspace import STAGES, Workspace, atomic_write_json, mark_downstream_stale

import pytest


def test_stage_order_follows_cp1():
    assert STAGES == ("ingest", "transcript", "analysis", "selection", "titling", "review", "render")


def test_config_hash_is_canonical():
    assert hashing.config_hash({"b": 1, "a": "x"}) == hashing.config_hash({"a": "x", "b": 1})
    assert hashing.config_hash({"a": "x"}) != hashing.config_hash({"a": "y"})


def test_atomic_write_leaves_no_tmp(tmp_path):
    target = tmp_path / "d" / "x.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_json(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in target.parent.iterdir()] == ["x.json"]
    umask = os.umask(0)
    os.umask(umask)
    assert target.stat().st_mode & 0o777 == 0o666 & ~umask  # not mkstemp's 0600


def test_mark_downstream_stale_only_after_stage():
    m = {"stages": {s: {"status": "done"} for s in ("ingest", "transcript", "render")}}
    assert mark_downstream_stale(m, "transcript") == ["render"]
    assert m["stages"]["ingest"]["status"] == "done"
    assert m["stages"]["render"]["status"] == "stale"


def test_unknown_schema_version_rejected(tmp_path):
    ws = Workspace(tmp_path, "ep")
    ws.dir.mkdir()
    ws.manifest_path.write_text('{"schema_version": 99}')
    from auto_short.workspace import WorkspaceError
    with pytest.raises(WorkspaceError, match="schema_version"):
        ws.load_manifest()


def test_config_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert str(load().workspace.dir) == "work"  # defaults without config.toml
    p = tmp_path / "c.toml"
    p.write_text('[workspace]\ndir = "w2"\n[ingest]\nyoutube_format = "b"\n')
    cfg = load(p)
    assert str(cfg.workspace.dir) == "w2" and cfg.ingest.youtube_format == "b"
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "missing.toml")
    p.write_text('[ingest]\nyoutube_format = 3\n')
    with pytest.raises(ConfigError, match="youtube_format"):
        load(p)


def test_example_config_matches_defaults():
    from pathlib import Path
    from auto_short.config import Config
    root = Path(__file__).resolve().parents[1]
    assert load(root / "config.example.toml") == Config()
