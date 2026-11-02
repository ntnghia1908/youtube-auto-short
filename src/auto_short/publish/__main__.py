"""Gắn thumbnail tập / khai thị: python -m auto_short.publish auth / thumbs / kt-thumbs."""
import argparse
import json
import sys
from pathlib import Path

from ..config import ConfigError, load
from ..packaging import PackageError, episode
from . import PublishError, kt, thumbs, youtube


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
            if args.command == "kt-thumbs":
                rows = kt.plan(cfg, videos, pid=args.playlist, shape=args.shape)
                print("Video YouTube\tMã\tClip\tẢnh thumbnail\tTrạng thái / lý do\tCảnh báo")
                for row in rows:
                    print(f"{row['youtube_id']}\t{row['code']}\t{row.get('clip_id', '')}\t{row.get('file', '')}\t"
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
