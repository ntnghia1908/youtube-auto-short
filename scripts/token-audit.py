#!/usr/bin/env python3
"""Token audit: Claude Code cost (main session vs subagents), context waste and cost per merged PR, from local transcripts.

Usage: python3 scripts/token-audit.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--project SUBSTR] [--repo PATH]
Reads ~/.claude/projects/*/*.jsonl (main) and */*/subagents/*.jsonl, ~/.codex/sessions; prints aggregates only.
Cost = API list price equivalent (not the subscription bill). Baseline + re-measure plan: docs/tasks/FW-token-audit.md.
"""
import argparse
import datetime
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# $/MTok: input, cache read, output (Opus 5.5, Sonnet 5.5, Haiku 5.5). Cache write = input × 2 (1h TTL) or × 1.25 (5m TTL).
PRICES = {"opus": (4.0, 0.2, 20.0), "sonnet": (2.0, 0.2, 10.0), "haiku": (0.1, 0.01, 0.5)}
BIG_REWRITE = 50_000  # a cache write this large with fewer cache reads = context rewritten after the cache expired
THRESHOLDS = (150_000, 250_000)


def family(model):
    return next((f for f in PRICES if f in (model or "")), None)


def turns(path: Path):
    """One record per API message (streamed chunks share a message id; output_tokens grows, keep the max)."""
    msgs = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if event.get("type") == "assistant" else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if not usage or not family(message.get("model")):
            continue
        rec = msgs.setdefault(message.get("id"), {"model": family(message["model"]), "usage": usage, "out": 0,
                                                   "ts": event.get("timestamp", "")})
        rec["out"] = max(rec["out"], usage.get("output_tokens", 0))
    return sorted(msgs.values(), key=lambda r: r["ts"])


def cost(rec):
    price_in, price_read, price_out = PRICES[rec["model"]]
    u = rec["usage"]
    split = u.get("cache_creation") or {}
    write_1h = split.get("ephemeral_1h_input_tokens", 0) if split else u.get("cache_creation_input_tokens", 0)
    write_5m = split.get("ephemeral_5m_input_tokens", 0)
    return (u.get("input_tokens", 0) * price_in + write_1h * price_in * 2 + write_5m * price_in * 1.25
            + u.get("cache_read_input_tokens", 0) * price_read + rec["out"] * price_out) / 1e6


def context(rec):
    u = rec["usage"]
    return u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)


def agent_type(path: Path):
    if path.parent.name != "subagents":
        return "MAIN"
    meta = path.with_suffix(".meta.json")
    try:
        return json.loads(meta.read_text()).get("agentType", "?")
    except (OSError, ValueError):
        return "?"


def merged_prs(repo: Path, since, until):
    out = subprocess.run(["git", "-C", str(repo), "log", "--merges", "--first-parent", "main", "--format=%ad",
                          "--date=short"], capture_output=True, text=True).stdout.split()
    return sum(since <= day <= until for day in out)


def codex_tokens(since, until):
    total, cached = 0, 0
    for log in (Path.home() / ".codex" / "sessions").glob("*/*/*/*.jsonl"):
        last, day = None, None
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            day = day or event.get("timestamp", "")[:10]
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if payload.get("type") == "token_count" and payload.get("info"):
                last = payload["info"].get("total_token_usage")
        if last and day and since <= day <= until:
            total += last.get("input_tokens", 0)
            cached += last.get("cached_input_tokens", 0)
    return total, cached


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="2000-01-01")
    parser.add_argument("--until", default="2999-12-31")
    parser.add_argument("--project", default="youtube", help="substring of the ~/.claude/projects dir name")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    root = Path.home() / ".claude" / "projects"
    paths = [p for p in list(root.glob("*/*.jsonl")) + list(root.glob("*/*/subagents/*.jsonl"))
             if args.project in p.relative_to(root).parts[0]]
    by_agent = defaultdict(lambda: [0, 0.0])  # (agent, model) -> turns, $
    main_input, above = 0, {t: 0 for t in THRESHOLDS}
    rewrites = {"MAIN": [0, 0], "subagent": [0, 0]}  # count, tokens
    peaks = []
    for path in paths:
        agent, prev, peak = agent_type(path), None, 0
        for rec in turns(path):
            day = rec["ts"][:10]
            if not args.since <= day <= args.until:
                continue
            by_agent[(agent, rec["model"])][0] += 1
            by_agent[(agent, rec["model"])][1] += cost(rec)
            ctx, u = context(rec), rec["usage"]
            written = u.get("cache_creation_input_tokens", 0)
            if prev and written > BIG_REWRITE and u.get("cache_read_input_tokens", 0) < written:
                kind = "MAIN" if agent == "MAIN" else "subagent"
                rewrites[kind][0] += 1
                rewrites[kind][1] += written
            if agent == "MAIN":
                main_input += ctx
                for t in THRESHOLDS:
                    above[t] += max(0, ctx - t)
                peak = max(peak, ctx)
            prev = rec
        if agent == "MAIN" and peak:
            peaks.append(peak)

    total = sum(v[1] for v in by_agent.values())
    print(f"period {args.since} .. {args.until}, projects matching '{args.project}': ${total:.0f} (API list-price equivalent)")
    for (agent, model), (n, usd) in sorted(by_agent.items(), key=lambda kv: -kv[1][1]):
        print(f"  {agent:18} {model:7} turns {n:6}  ${usd:7.0f}  {100 * usd / max(total, 1e-9):5.1f}%")
    sub = sum(v[1] for k, v in by_agent.items() if k[0] != "MAIN")
    print(f"subagent share: {100 * sub / max(total, 1e-9):.0f}%")
    for t in THRESHOLDS:
        print(f"main input above {t // 1000}k context: {100 * above[t] / max(main_input, 1):.0f}%")
    if peaks:
        peaks.sort()
        print(f"main session peak context: median {peaks[len(peaks) // 2] // 1000}k, p90 {peaks[int(.9 * len(peaks))] // 1000}k"
              f" ({len(peaks)} sessions)")
    for kind, (n, tok) in rewrites.items():
        print(f"{kind} cache-expired rewrites: {n} ({tok / 1e6:.1f}M tokens)")
    prs = merged_prs(Path(args.repo), args.since, args.until)
    print(f"merged PRs on main: {prs}  -> ${total / prs:.1f}/PR" if prs else "merged PRs on main: 0")
    codex_in, codex_cached = codex_tokens(args.since, args.until)
    print(f"codex input tokens: {codex_in / 1e6:.1f}M ({100 * codex_cached / max(codex_in, 1):.0f}% cached; separate subscription)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
