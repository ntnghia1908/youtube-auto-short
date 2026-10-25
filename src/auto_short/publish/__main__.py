"""Gắn thumbnail tập: python -m auto_short.publish auth / thumbs."""
import argparse
import json
import sys
from pathlib import Path

from ..config import ConfigError, load
from ..packaging import PackageError, episode
from . import PublishError, thumbs, youtube


def main(argv=None, *, transport=None, sleep=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--token", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth")
    attach = commands.add_parser("thumbs")
    attach.add_argument("--playlist", required=True)
    attach.add_argument("--series")
    attach.add_argument("--apply", action="store_true")
    attach.add_argument("--force", action="store_true")
    # Accept common options before or after the command, like other module CLIs.
    for command in commands.choices.values():
        for name in ("config", "client", "token"):
            command.add_argument("--" + name, type=Path, default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        if args.command == "auth":
            result = youtube.auth(args.client, args.token, transport=transport, sleep=sleep, now=now)
        else:
            # Validate local identity before reading the channel.
            episode.playlist(cfg, args.playlist)
            client = youtube.YouTube(args.client, args.token, transport=transport, now=now)
            rows = thumbs.plan(cfg, client.videos(), pid=args.playlist, series=args.series, output=print)
            print("Video YouTube\tTập / khuôn\tẢnh thumbnail\tTrạng thái / lý do")
            for row in rows:
                detail = f"{row.get('episode', '')} {row.get('shape', '')}".strip()
                print(f"{row['youtube_id']}\t{detail}\t{row.get('file', '')}\t"
                      f"{row['status']} {row['reason']} {row['warning']}".rstrip())
            result = dict(mode="apply" if args.apply else "chạy thử", rows=
                          thumbs.apply(cfg, rows, client, force=args.force) if args.apply else rows)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ConfigError, PackageError, PublishError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("không đọc / ghi được file cấu hình, OAuth hoặc nhật ký thumbnail", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
