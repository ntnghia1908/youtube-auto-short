"""Command line interface: ``auto-short`` / ``python -m auto_short``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config as config_mod
from .analysis import AnalysisError, run_analysis
from .ingest import IngestError, run_ingest
from .render import RenderError, run_render
from .review import ReviewError, TitlePreview, list_titles, reset_title, set_alternative, set_title
from .selection import SelectionError, run_selection
from .titling import TitlingError, run_titling
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

    a = sub.add_parser("analysis", help="produce shots.json, silences.json and candidates.json")
    a.add_argument("episode_id")
    a.add_argument("--force", action="store_true", help="re-run even if up to date")
    a.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    c = sub.add_parser("selection", help="AI clip selection among candidates -> clips.json")
    c.add_argument("episode_id")
    c.add_argument("--force", action="store_true", help="re-run even if up to date")
    c.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    ti = sub.add_parser("titling", help="header + AI title per selected clip -> titles.json")
    ti.add_argument("episode_id")
    ti.add_argument("--speaker", help="header speaker (overrides [titling.header] speaker)")
    ti.add_argument("--series", help="header series (overrides config and the metadata title)")
    ti.add_argument("--episode", help="header episode number (overrides config and the metadata title)")
    ti.add_argument("--force", action="store_true", help="re-run even if up to date")
    ti.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    r = sub.add_parser("render", help="compose each titled clip into a 1080x1920 Short -> output/<id>/shorts/")
    r.add_argument("episode_id")
    r.add_argument("--force", action="store_true", help="re-run even if up to date")
    r.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    tt = sub.add_parser("title", help="set, choose or reset the title of one Short (review.json), or --list")
    tt.add_argument("episode_id")
    tt.add_argument("clip_id", nargs="?", help="clip id (e.g. k03); not with --list")
    act = tt.add_mutually_exclusive_group(required=True)
    act.add_argument("--set", metavar="TEXT", dest="set_text", help="manual title")
    act.add_argument("--alternative", metavar="N", type=int, help="use AI alternative number N (see --list)")
    act.add_argument("--reset", action="store_true", help="remove the override (back to the AI title)")
    act.add_argument("--list", action="store_true", help="list every clip: AI title, alternatives, override")
    tt.add_argument("--render", action="store_true", help="run 'render' after writing review.json")
    tt.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

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


def _cmd_analysis(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_analysis(args.episode_id, cfg, force=args.force)
    state = f"analyzed ({result.candidates} candidates)" if result.ran else "skipped (up to date)"
    print(f"{result.episode_id}\t{state}\t{result.path}")
    return 0


def _cmd_selection(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_selection(args.episode_id, cfg, force=args.force)
    state = f"selected ({result.clips} clips)" if result.ran else "skipped (up to date)"
    print(f"{result.episode_id}\t{state}\t{result.path}")
    return 0


def _cmd_titling(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_titling(args.episode_id, cfg, force=args.force, speaker=args.speaker, series=args.series,
                         episode=args.episode)
    state = f"titled ({result.titled}/{result.clips} clips)" if result.ran else "skipped (up to date)"
    print(f"{result.episode_id}\t{state}\t{result.path}")
    return 0


def _cmd_render(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_render(args.episode_id, cfg, force=args.force)
    state = f"rendered ({result.rendered}/{result.clips} clips)" if result.ran else "skipped (up to date)"
    print(f"{result.episode_id}\t{state}\t{result.path}")
    return 0


def _print_preview(episode_id: str, clip_id: str, p: TitlePreview | None) -> None:
    if p is None:
        print(f"{episode_id}\t{clip_id}\tuntitled\t-")
        print("  not rendered: untitled clip without an override")
        return
    print(f"{episode_id}\t{clip_id}\t{p.origin}\t{p.title}")
    print(f"  display ({p.font_size} px, panel {p.panel_height} px): {' / '.join(p.display_lines)}")


def _cmd_title(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    if args.list:
        if args.clip_id is not None or args.render:
            raise ReviewError("--list takes no clip id and no --render")
        doc = list_titles(args.episode_id, cfg)
        for c in doc["clips"]:
            print(f"{c['clip_id']}\t{c['candidate_id']}\t{c['origin'] or 'untitled'}\t{c['title'] or '-'}")
            print(f"  AI: {c['ai_title'] or '- (untitled)'}")
            for a in c["alternatives"]:
                print(f"  {a['n']}: {a['title']}")
            if c["override"]:
                print(f"  override ({c['override']['origin']}): {c['override']['title']}")
        for w in doc["ignored"]:
            log.warning("title: WARNING: %s", w)
        return 0
    if args.clip_id is None:
        raise ReviewError("clip id required (or use --list)")
    if args.set_text is not None:
        preview = set_title(args.episode_id, cfg, args.clip_id, args.set_text)
    elif args.alternative is not None:
        preview = set_alternative(args.episode_id, cfg, args.clip_id, args.alternative)
    else:
        preview = reset_title(args.episode_id, cfg, args.clip_id)
    _print_preview(args.episode_id, args.clip_id, preview)
    if args.render:
        return _cmd_render(argparse.Namespace(episode_id=args.episode_id, force=False), cfg)
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
        if args.command == "analysis":
            return _cmd_analysis(args, cfg)
        if args.command == "selection":
            return _cmd_selection(args, cfg)
        if args.command == "titling":
            return _cmd_titling(args, cfg)
        if args.command == "render":
            return _cmd_render(args, cfg)
        if args.command == "title":
            return _cmd_title(args, cfg)
        return _cmd_status(args, cfg)
    except (config_mod.ConfigError, IngestError, TranscriptError, AnalysisError, SelectionError,
            TitlingError, RenderError, ReviewError, WorkspaceError) as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
