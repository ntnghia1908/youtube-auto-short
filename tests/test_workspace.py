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


# --- CL1 C9 / CP2 D6 amendment: explicit ``downstream`` (CL1.1 AC1) ---------------------------

def test_mark_downstream_stale_explicit_downstream():
    m = {"stages": {"subtitle": {"status": "done"}, "media": {"status": "done"}, "lesson": {"status": "done"}}}
    assert mark_downstream_stale(m, "subtitle", ("lesson",)) == ["lesson"]
    assert m["stages"]["media"]["status"] == "done" and m["stages"]["lesson"]["status"] == "stale"
    assert mark_downstream_stale(m, "media", ()) == []
    assert mark_downstream_stale({"stages": {}}, "subtitle", ("lesson",)) == []  # no entry -> nothing
    with pytest.raises(ValueError):  # without downstream a stage outside STAGES is still an error
        mark_downstream_stale(m, "subtitle")


def test_run_stage_default_downstream_unchanged(tmp_path):
    from auto_short.workspace import run_stage
    ws = Workspace(tmp_path, "ep")
    m = ws.new_manifest({"kind": "local"})
    for name in ("ingest", "analysis", "render"):
        m["stages"][name] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "h"}
    assert run_stage(ws, m, "transcript", inputs=[], cfg_hash="h", force=False, action=lambda: [])
    assert [m["stages"][s]["status"] for s in ("ingest", "transcript", "analysis", "render")] == [
        "done", "done", "stale", "stale"]


def test_run_stage_with_downstream_outside_stages(tmp_path):
    from auto_short.workspace import run_stage
    ws = Workspace(tmp_path, "ep")
    m = ws.new_manifest({"kind": "youtube"})
    m["stages"]["lesson"] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "h"}
    m["stages"]["render"] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "h"}
    assert run_stage(ws, m, "subtitle", inputs=[], cfg_hash="h", force=False, action=lambda: [],
                     downstream=("lesson",))
    assert m["stages"]["subtitle"]["status"] == "done"
    assert m["stages"]["lesson"]["status"] == "stale" and m["stages"]["render"]["status"] == "done"
    m["stages"]["lesson"]["status"] = "done"
    assert run_stage(ws, m, "media", inputs=[], cfg_hash="h", force=False, action=lambda: [], downstream=())
    assert m["stages"]["lesson"]["status"] == "done" and m["stages"]["render"]["status"] == "done"
    assert not run_stage(ws, m, "media", inputs=[], cfg_hash="h", force=False, action=lambda: [], downstream=())
