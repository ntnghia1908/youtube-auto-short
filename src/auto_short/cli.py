"""Command line interface: ``auto-short`` / ``python -m auto_short``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config as config_mod
from . import khaithi
from .analysis import AnalysisError, run_analysis
from .ingest import IngestError, derived_episode_id, run_ingest
from .learning.cli import cmd_learn
from .pipeline import (PIPELINE_STAGES, PipelineError, PipelineInterrupted, PipelineResult, PreflightError,
                       ollama_preflight, run_pipeline)
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

    u = sub.add_parser("run", help="run every stage (ingest .. render) on a YouTube URL or local video; "
                                   "re-run to resume")
    u.add_argument("source", help="YouTube video URL or path to a local video file")
    u.add_argument("--episode-id", help="override the derived episode id (ingest)")
    u.add_argument("--subtitle", type=Path, help="local subtitle file (transcript)")
    u.add_argument("--speaker", help="header speaker (titling)")
    u.add_argument("--series", help="header series (titling)")
    u.add_argument("--episode", help="header episode number (titling)")
    u.add_argument("--force-from", choices=PIPELINE_STAGES, metavar="STAGE",
                   help=f"re-run STAGE even if up to date (later stages follow as stale); "
                        f"one of: {', '.join(PIPELINE_STAGES)}")
    u.add_argument("--no-preflight", action="store_true", help="skip the Ollama host/model check")
    u.add_argument("--khai-thi", action="store_true",
                   help="make khai thi videos (longer, one complete teaching each) in episode <id>.kt instead of "
                        "Shorts; with --episode-id X the episode is X.kt")
    u.add_argument("--min-minutes", type=int, metavar="N",
                   help="khai thi: minimum length in minutes after silence trimming (default: [khaithi] "
                        "default_min_minutes, 4)")
    u.add_argument("--max-minutes", type=int, metavar="M",
                   help="khai thi: maximum length in minutes (default: [khaithi] default_max_minutes, 7)")
    u.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    w = sub.add_parser("web", help="web UI on the LAN (password from env AUTO_SHORT_WEB_PASSWORD; needs the "
                                   "[web] extra)")
    w.add_argument("--host", help="listen address (default: [web] host, 0.0.0.0)")
    w.add_argument("--port", type=int, help="listen port (default: [web] port, 8080)")
    w.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    et = sub.add_parser("enhance-token", help="make a random worker token for the enhance GPU workers "
                                              "(printed once; CP13.1 E8) and show where to put it")
    et.add_argument("--name", default="worker", help="worker name = token name, e.g. rtx3090 (default: worker)")

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

    lr = sub.add_parser("learn", help="Chinese Learning: Chinese subtitle + first 5 minutes of a YouTube video "
                                      "-> <workspace>/_learning/<video id>/")
    lr.add_argument("url", help="YouTube video URL")
    lr.add_argument("--force", action="store_true", help="re-run every stage even if up to date")
    lr.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")

    s = sub.add_parser("status", help="show stage status of an episode")
    s.add_argument("episode_id")
    s.add_argument("--config", type=Path, help="config TOML (default: ./config.toml if present)")
    return parser


# E6: "<episode_id>\t<state>\t<path>" per stage; the state when the stage ran.
_STATES = {
    "ingest": lambda r: "ingested",
    "transcript": lambda r: f"transcribed ({r.source}/{r.method})",
    "analysis": lambda r: f"analyzed ({r.candidates} candidates)",
    "selection": lambda r: f"selected ({r.clips} clips)",
    "titling": lambda r: f"titled ({r.titled}/{r.clips} clips)",
    "render": lambda r: f"rendered ({r.rendered}/{r.clips} clips)",
}


def stage_line(stage: str, result) -> str:
    """The stdout line of a stage command (shared by the single-stage commands and ``run``, E6)."""
    state = _STATES[stage](result) if result.ran else "skipped (up to date)"
    path = result.workspace if stage == "ingest" else result.path
    return f"{result.episode_id}\t{state}\t{path}"


def _cmd_ingest(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    print(stage_line("ingest", run_ingest(args.source, cfg, episode_id=args.episode_id, force=args.force)))
    return 0


def _cmd_transcript(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    print(stage_line("transcript", run_transcript(args.episode_id, cfg, subtitle=args.subtitle, force=args.force)))
    return 0


def _cmd_analysis(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    print(stage_line("analysis", run_analysis(args.episode_id, cfg, force=args.force)))
    return 0


def _cmd_selection(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    print(stage_line("selection", run_selection(args.episode_id, cfg, force=args.force)))
    return 0


def _cmd_titling(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    result = run_titling(args.episode_id, cfg, force=args.force, speaker=args.speaker, series=args.series,
                         episode=args.episode)
    print(stage_line("titling", result))
    return 0


def _cmd_render(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    print(stage_line("render", run_render(args.episode_id, cfg, force=args.force)))
    return 0


def _print_summary(result: PipelineResult, stopped: str | None = None) -> None:
    """E6: per-stage timing table on stderr; ``stopped`` = state of the stage that did not finish."""
    log.info("run: summary [%s]", result.episode_id or "-")
    for run in result.stages:
        log.info("  %-11s %-5s %9.1f s", run.stage, "ran" if run.ran else "skip", run.seconds)
    if stopped is not None:
        log.info("  %-11s %s", result.failed_stage or stopped, "error" if result.failed_stage else "interrupted")
    log.info("  %-11s %-5s %9.1f s", "total", "", sum(r.seconds for r in result.stages))


def _khaithi_episode(args: argparse.Namespace, cfg: config_mod.Config) -> str | None:
    """CP8.9 K6: validate the minutes and write / update ``<base_id>.kt/khaithi.json``; returns the episode id
    (None without ``--khai-thi``). Raises KhaithiError / IngestError before any stage."""
    if not args.khai_thi:
        if args.min_minutes is not None or args.max_minutes is not None:
            raise khaithi.KhaithiError("--min-minutes / --max-minutes need --khai-thi")
        return None
    lo = args.min_minutes if args.min_minutes is not None else cfg.khaithi.default_min_minutes
    hi = args.max_minutes if args.max_minutes is not None else cfg.khaithi.default_max_minutes
    khaithi.check_minutes(lo, hi, cfg.khaithi.max_minutes_limit)
    base_id = args.episode_id or derived_episode_id(args.source, cfg)
    episode_id, changed = khaithi.prepare(cfg, base_id, lo, hi)
    log.info("run: khai thi %d-%d minutes -> episode %s (%s)", lo, hi, episode_id,
             f"{khaithi.KHAITHI_NAME} written" if changed else "parameters unchanged")
    return episode_id


def _cmd_run(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    try:
        kt_episode = _khaithi_episode(args, cfg)
    except khaithi.KhaithiError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    try:
        result = run_pipeline(args.source, cfg, episode_id=kt_episode or args.episode_id, subtitle=args.subtitle,
                              speaker=args.speaker, series=args.series, episode=args.episode,
                              force_from=args.force_from,
                              preflight=None if args.no_preflight else ollama_preflight,
                              on_stage=lambda run: print(stage_line(run.stage, run.result), flush=True))
    except PreflightError as exc:
        print(f"auto-short: error: ollama preflight: {exc}", file=sys.stderr)
        return 1
    except PipelineError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    except PipelineInterrupted as exc:
        _print_summary(exc.result, exc.stage)
        print(f"auto-short: interrupted during {exc.stage}; re-run the same command to resume", file=sys.stderr)
        return 130
    _print_summary(result, result.failed_stage)
    if not result.ok:
        print(f"auto-short: error: {result.error}", file=sys.stderr)
        print("auto-short: re-run the same command to resume from the failed stage", file=sys.stderr)
        return 1
    print(f"{result.episode_id}\tdone ({result.rendered}/{result.clips} Shorts)\t{result.output_dir}")
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
    kt = khaithi.read(ws.dir, cfg.khaithi.max_minutes_limit)  # CP8.9 K6; a broken file is an error
    print(f"kind:      khai thi {kt.label} minutes (base episode {kt.base_episode_id})" if kt else "kind:      short")
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


def _cmd_web(args: argparse.Namespace, cfg: config_mod.Config) -> int:
    from .web.auth import AuthError, password_from_env  # stdlib only

    try:
        password_from_env()
    except AuthError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    try:
        from .web.server import serve
    except ImportError as exc:
        print(f"auto-short: error: the web server needs the [web] extra (pip install -e \".[web]\"): {exc}",
              file=sys.stderr)
        return 1
    port = args.port if args.port is not None else cfg.web.port
    if not 1 <= port <= 65535:
        print(f"auto-short: error: invalid port {port}", file=sys.stderr)
        return 1
    try:
        serve(cfg, host=args.host or cfg.web.host, port=port)
    except AuthError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_enhance_token(args: argparse.Namespace) -> int:
    """CP13.1 E8: print a fresh token (stdout, once) and the instructions (stderr). Nothing is stored anywhere."""
    from .enhance.tokens import TOKENS_ENV, TokenError, new_token, parse_tokens

    token = new_token()
    try:
        parse_tokens(f"{args.name}={token}")
    except TokenError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    print(token)
    print(f"Token cho worker '{args.name}' (hiện một lần, không lưu ở đâu cả).\n"
          f"1. VM: thêm vào biến môi trường của tiến trình web (pane tmux chạy `auto-short web`), nối với token đã có "
          f"bằng dấu phẩy, rồi khởi động lại web:\n"
          f"     export {TOKENS_ENV}='{args.name}=<token ở dòng trên>'      # nhiều worker: 'a=<token>,b=<token>'\n"
          f"2. Máy Windows: điền cùng token vào `config.json` của worker (khóa \"token\"), worker_name = \"{args.name}\".\n"
          f"Không ghi token vào repo / config.toml / chat.", file=sys.stderr)
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
    if args.command == "enhance-token":  # needs no config
        return _cmd_enhance_token(args)
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
        if args.command == "run":
            return _cmd_run(args, cfg)
        if args.command == "web":
            return _cmd_web(args, cfg)
        if args.command == "title":
            return _cmd_title(args, cfg)
        if args.command == "learn":
            return cmd_learn(args, cfg)
        return _cmd_status(args, cfg)
    except (config_mod.ConfigError, IngestError, TranscriptError, AnalysisError, SelectionError,
            TitlingError, RenderError, ReviewError, WorkspaceError, khaithi.KhaithiError) as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
