"""Command line interface: ``auto-short`` / ``python -m auto_short``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config as config_mod
from .ingest import IngestError, run_ingest
from .transcript import TranscriptError, run_transcript
from .workspace import PENDING, STAGES, Workspace, WorkspaceError, validate_episode_id

log = logging.getLogger("auto_short")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-short", description="Vietnamese lecture video -> YouTube Shorts.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="register a YouTube URL or local video in the workspace")
    p.add_argument("source", help="YouTube video URL or path to a local video file")
    p.add_argument("--episode-id", help="override the derived episode id")
    p.add_argument("--force", action="store_true", help="re-run even if up to date")
    p.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    t = sub.add_parser("transcript", help="produce transcript.json (YouTube caption -> subtitle -> Whisper)")
    t.add_argument("episode_id")
    t.add_argument("--subtitle", type=Path, help="local subtitle file (.srt/.vtt/.json3); overrides a sidecar")
    t.add_argument("--force", action="store_true", help="re-run even if up to date")
    t.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    s = sub.add_parser("status", help="show stage status of an episode")
    s.add_argument("episode_id")
    s.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")
    return parser


def _cmd_ingest(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_ingest(args.source, cfg, episode_id=args.episode_id, force=args.force)
    print(f"{result.episode_id}\t{'ingested' if result.ran else 'skipped (up to date)'}\t{result.workspace}")
    return 0


def _cmd_transcript(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_transcript(args.episode_id, cfg, subtitle=args.subtitle, force=args.force)
    state = f"transcribed ({result.source}/{result.method})" if result.ran else "skipped (up to date)"
    print(f"{result.episode_id}\t{state}\t{result.path}")
    return 0


def _cmd_status(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    ws = Workspace(cfg.workspace.dir, validate_episode_id(args.episode_id))
    manifest = ws.load_manifest()
    if manifest is None:
        raise WorkspaceError(f"no manifest for episode {args.episode_id!r} in {ws.dir}")
    src = manifest.get("source") or {}
    print(f"episode:   {manifest['episode_id']}")
    print(f"workspace: {ws.dir.resolve()}")
    print(f"source:    {src.get('kind')} {src.get('uri')}")
    if src.get("sha256"):
        print(f"           sha256 {src['sha256']}  size {src.get('size')}")
    print("stages:")
    for name in STAGES:
        entry = manifest["stages"].get(name) or {}
        status = entry.get("status", PENDING)
        line = f"  {name:<11} {status:<8}"
        if entry.get("finished_at"):
            line += f" finished {entry['finished_at']}"
        if entry.get("artifacts"):
            line += f"  artifacts: {', '.join(entry['artifacts'])}"
        if entry.get("error"):
            line += f"  error: {entry['error']}"
        print(line.rstrip())
    return 0


def _setup_logging() -> None:
    """Log to the current stderr; idempotent across repeated main() calls."""
    for h in list(log.handlers):
        log.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("auto-short: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging()
    try:
        cfg = config_mod.load(args.config)
        if args.command == "ingest":
            return _cmd_ingest(args, cfg)
        if args.command == "transcript":
            return _cmd_transcript(args, cfg)
        return _cmd_status(args, cfg)
    except (config_mod.ConfigError, IngestError, TranscriptError, WorkspaceError) as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
