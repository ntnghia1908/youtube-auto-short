"""Fake episodes and pipelines for the web tests (no real stage runs)."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from auto_short.pipeline import PIPELINE_STAGES, StageDeps, run_pipeline
from auto_short.workspace import STAGES, Workspace


def write_episode(cfg, episode_id: str, *, clips=("k01", "k02"), title="Kinh Vô Lượng Thọ tập 3",
                  render_status="done", extra_shorts=(), titles: dict | None = None,
                  origins: dict | None = None) -> dict[str, bytes]:
    """Workspace manifest (every pipeline stage ``done``), metadata and a render manifest + fake mp4 files.
    Returns clip_id -> file bytes."""
    ws = Workspace(Path(cfg.workspace.dir), episode_id)
    ws.dir.mkdir(parents=True, exist_ok=True)
    stages = {s: {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x",
                  "started_at": "2026-09-27T00:00:00Z", "finished_at": "2026-09-27T00:01:00Z", "error": None}
              for s in STAGES if s != "review"}
    stages["render"]["status"] = render_status
    manifest = ws.new_manifest({"kind": "youtube", "uri": f"https://youtu.be/{episode_id}?si=zz", "path": None,
                                "sha256": None, "size": None, "mtime_ns": None})
    manifest["stages"] = stages
    ws.save_manifest(manifest)
    (ws.dir / "metadata.json").write_text(json.dumps({"title": title, "channel": "Kênh", "duration": 3600.0}),
                                          encoding="utf-8")
    out = Path(cfg.render.output_dir) / episode_id
    (out / "shorts").mkdir(parents=True, exist_ok=True)
    files, shorts = {}, []
    for i, clip in enumerate(clips):
        data = bytes([i + 1]) * (1000 + i) + clip.encode()
        (out / "shorts" / f"{clip}.mp4").write_bytes(data)
        files[clip] = data
        shorts.append({"clip_id": clip, "candidate_id": f"c{i + 1:05d}", "status": "rendered", "skip_reason": None,
                       "file": f"shorts/{clip}.mp4",
                       "sha256": f"{i:064x}", "title": (titles or {}).get(clip, f"Tiêu đề {clip}"),
                       "title_origin": (origins or {}).get(clip, "ai"),
                       "title_display_lines": [(titles or {}).get(clip, f"Tiêu đề {clip}")],
                       "duration": 60.0 + i, "source_start": 10.0, "source_end": 80.0})
    shorts += list(extra_shorts)
    doc = {"schema_version": 1, "episode_id": episode_id, "header": {"lines": ["HT.Tịnh Không", "X (tập 3)"]},
           "stats": {"clips": len(shorts), "rendered": len(clips), "skipped": len(shorts) - len(clips)},
           "shorts": shorts}
    (out / "render_manifest.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return files


def fake_pipeline(calls: list, *, fail_stage: str | None = None, gate=None):
    """``run_pipeline`` with every stage replaced: ingest takes the id from the URL, render writes a finished
    episode. ``gate`` (threading.Event) blocks the transcript stage until set."""

    def runner(stage):
        def run(target_or_id, config, **kw):
            calls.append((stage, target_or_id, kw))
            if stage == fail_stage:
                from auto_short.transcript import TranscriptError
                raise TranscriptError(f"{stage} boom")
            if stage == "transcript" and gate is not None:
                assert gate.wait(10)
            if stage == "ingest":
                eid = target_or_id.rsplit("/", 1)[-1]
                return SimpleNamespace(episode_id=eid, ran=True, workspace=Path(config.workspace.dir) / eid)
            if stage == "render":
                write_episode(config, target_or_id)
                path = Path(config.render.output_dir) / target_or_id / "render_manifest.json"
                return SimpleNamespace(episode_id=target_or_id, ran=True, path=path, rendered=2, clips=2,
                                       encoded=2, reused=0)
            return SimpleNamespace(episode_id=target_or_id, ran=stage != "analysis", path=None)
        return run

    return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))
