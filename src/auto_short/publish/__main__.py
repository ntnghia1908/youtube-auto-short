"""Gắn thumbnail tập / khai thị / Short: python -m auto_short.publish."""
import argparse
import json
import re
import sys
from pathlib import Path

from ..config import ConfigError, load
from ..packaging import PackageError, episode
from . import PublishError, kt, shorts, thumbs, youtube


def _episode_range(value):
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", value)
    if not match or not 1 <= int(match[1]) <= int(match[2]):
        raise argparse.ArgumentTypeError("cần khoảng tập A-B với 1 ≤ A ≤ B")
    return int(match[1]), int(match[2])


def main(argv=None, *, transport=None, sleep=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--token", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth")
    attach = commands.add_parser("thumbs")
    attach.add_argument("--playlist", required=True)
    attach.add_argument("--yt-playlist")
    attach.add_argument("--series")
    attach.add_argument("--apply", action="store_true")
    attach.add_argument("--force", action="store_true")
    kt_attach = commands.add_parser("kt-thumbs")
    kt_attach.add_argument("--playlist", required=True)
    kt_attach.add_argument("--yt-playlist", required=True)
    kt_attach.add_argument("--shape", choices=("vertical", "landscape"), default="landscape")
    kt_attach.add_argument("--apply", action="store_true")
    kt_attach.add_argument("--force", action="store_true")
    short_attach = commands.add_parser("short-thumbs")
    short_attach.add_argument("--playlist", required=True)
    short_attach.add_argument("--yt-playlist")
    short_attach.add_argument("--apply", action="store_true")
    short_attach.add_argument("--force", action="store_true")
    for command in (kt_attach, short_attach):
        command.add_argument("--episodes", type=_episode_range)
        command.add_argument("--only", help="id video YouTube, phân cách bằng dấu phẩy")
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
            journal = thumbs._journal(cfg)[1] if args.command == "thumbs" and args.yt_playlist else None
            videos = client.playlist_videos(args.yt_playlist) if args.yt_playlist else client.videos()
            if args.command in ("kt-thumbs", "short-thumbs"):
                is_short = args.command == "short-thumbs"
                rows = (shorts.plan(cfg, videos, pid=args.playlist, episodes=args.episodes) if is_short else
                        kt.plan(cfg, videos, pid=args.playlist, shape=args.shape))
                if args.episodes:
                    rows = [r for r in rows if args.episodes[0] <= r.get("episode", 0) <= args.episodes[1]]
                if args.only is not None:
                    selected = {ident.strip() for ident in args.only.split(",") if ident.strip()}
                    rows = [r for r in rows if r["youtube_id"] in selected]
                column = "Nguồn" if is_short else "Clip"
                print(f"Video YouTube\tMã\t{column}\tẢnh thumbnail\tTrạng thái / lý do\tCảnh báo")
                for row in rows:
                    detail = row.get("source" if is_short else "clip_id", "")
                    print(f"{row['youtube_id']}\t{row['code']}\t{detail}\t{row.get('file', '')}\t"
                          f"{row['status']} {row['reason']}\t{row['warning']}")
            else:
                rows = thumbs.plan(cfg, videos, pid=args.playlist, series=args.series, output=print, journal=journal)
                print("Video YouTube\tTập / khuôn\tẢnh thumbnail\tTrạng thái / lý do" +
                      ("\tghép theo" if args.yt_playlist else ""))
                for row in rows:
                    detail = f"{row.get('episode', '')} {row.get('shape', '')}".strip()
                    line = (f"{row['youtube_id']}\t{detail}\t{row.get('file', '')}\t"
                            f"{row['status']} {row['reason']} {row['warning']}".rstrip())
                    print(line + (f"\t{row['matched_by']}" if args.yt_playlist else ""))
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
