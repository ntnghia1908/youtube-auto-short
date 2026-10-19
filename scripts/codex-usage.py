#!/usr/bin/env python3
"""Codex CLI quota: the latest `rate_limits` recorded in ~/.codex/sessions (codex exec does not print it).

Usage: python3 scripts/codex-usage.py   — prints the 5-hour and weekly windows (used %, reset time, local).
Policy (when to fall back to the Sonnet implementer): .claude/rules/execution.md.
"""
import datetime
import json
import sys
from pathlib import Path


def find(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("rate_limits"), dict):
            return obj["rate_limits"]
        for value in obj.values():
            found = find(value)
            if found:
                return found
    return None


def latest_limits(root: Path, recent: int = 50):
    """The quota snapshot with the newest event timestamp across the most recent session logs (a log's mtime is not
    the freshness of its quota events: concurrent / resumed sessions write in any order)."""
    best = (None, None, None)
    logs = sorted(root.glob("*/*/*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:recent]
    for log in logs:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            limits, stamp = find(event), event.get("timestamp") if isinstance(event, dict) else None
            if limits and isinstance(stamp, str) and (best[0] is None or stamp > best[0]):
                best = (stamp, log, limits)
    return best[1], best[2]


def main() -> int:
    log, limits = latest_limits(Path.home() / ".codex" / "sessions")
    if not limits:
        print("no rate_limits in ~/.codex/sessions")
        return 1
    for key in ("primary", "secondary"):
        w = limits.get(key) or {}
        reset = datetime.datetime.fromtimestamp(w.get("resets_at", 0)).strftime("%Y-%m-%d %H:%M")
        print(f"{key}: {w.get('used_percent')}% of {w.get('window_minutes')} min window, resets {reset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
