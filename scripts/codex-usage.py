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


def latest_limits(root: Path):
    for log in sorted(root.glob("*/*/*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        last = None
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"rate_limits"' in line:
                try:
                    last = find(json.loads(line)) or last
                except ValueError:
                    continue
        if last:
            return log, last
    return None, None


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
