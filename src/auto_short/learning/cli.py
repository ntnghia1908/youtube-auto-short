"""Handler of ``auto-short learn <youtube-url> [--force] [--config PATH]`` (CL1 C12)."""

from __future__ import annotations

import argparse
import sys

from ..config import Config
from .run import LearningError, run_learning


def _print_stage(episode_id: str, stage: str, ran: bool) -> None:
    print(f"{episode_id}\t{stage}\t{'ran' if ran else 'skipped (up to date)'}", flush=True)


def cmd_learn(args: argparse.Namespace, cfg: Config) -> int:
    """stdout: ``<id>\\t<stage>\\t<ran|skipped (up to date)>`` per stage, then ``<id>\\tdone\\t<dir>``.

    Stages: ``subtitle``, ``media``, ``lesson`` (CL1.2). Log on stderr; exit 0 on success, 1 on error
    (``auto-short: error: …``, CP2 D8; also an Ollama preflight error before ``lesson``), 130 on Ctrl-C.
    """
    try:
        result = run_learning(args.url, cfg, force=args.force, on_stage=_print_stage)
    except LearningError as exc:
        print(f"auto-short: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("auto-short: interrupted; re-run the same command to resume", file=sys.stderr)
        return 130
    print(f"{result.episode_id}\tdone\t{result.workspace}")
    return 0
