"""Gắn thumbnail và lên lịch video: python -m auto_short.publish."""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from ..config import ConfigError, load
from ..packaging import PackageError, episode
from . import PublishError, check, kt, overview, playlists, schedule, shorts, thumbs, youtube


def _episode_range(value):
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", value)
    if not match or not 1 <= int(match[1]) <= int(match[2]):
        raise argparse.ArgumentTypeError("cần khoảng tập A-B với 1 ≤ A ≤ B")
    return int(match[1]), int(match[2])


def _since(value):
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("cần ngày hợp lệ YYYY-MM-DD") from None
    return value


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
    kt_attach.add_argument("--shape", choices=("vertical", "landscape"), default="vertical")
    kt_attach.add_argument("--apply", action="store_true")
    kt_attach.add_argument("--force", action="store_true")
    short_attach = commands.add_parser("short-thumbs")
    short_attach.add_argument("--playlist", required=True)
    short_attach.add_argument("--yt-playlist")
    short_attach.add_argument("--apply", action="store_true")
    short_attach.add_argument("--force", action="store_true")
    scheduler = commands.add_parser("schedule")
    scheduler.add_argument("--apply", action="store_true")
    scheduler.add_argument("--only", help="id video YouTube, phân cách bằng dấu phẩy")
    scheduler.add_argument("--limit", type=int)
    scheduler.add_argument("--playlist")
    checker = commands.add_parser("check")
    checker.add_argument("--playlist", required=True)
    checker.add_argument("--add-playlists", action="store_true")
    for command in (scheduler, checker):
        command.add_argument("--refresh", action="store_true")
    for command in (kt_attach, short_attach):
        command.add_argument("--since", type=_since)
        command.add_argument("--episodes", type=_episode_range)
        command.add_argument("--only", help="id video YouTube, phân cách bằng dấu phẩy")
    # Accept common options before or after the command, like other module CLIs.
    for command in commands.choices.values():
        for name in ("config", "client", "token"):
            command.add_argument("--" + name, type=Path, default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "schedule" and args.limit is not None and args.limit < 1:
        parser.error("--limit phải là số nguyên dương")
    cfg = None
    stem = error_stem = None
    try:
        cfg = load(args.config)
        if args.command == "check":
            # Only registered/default token paths have a web authorization target.
            stem = youtube.token_stem(args.token)
            error_stem = stem or Path(args.token or youtube.default_token()).stem
        if args.command == "auth":
            result = youtube.auth(args.client, args.token, transport=transport, sleep=sleep, now=now)
        elif args.command in ("schedule", "check"):
            stock = check.inventory(cfg, args.playlist) if args.playlist else None
            client = youtube.YouTube(args.client, args.token, transport=transport, now=now,
                                     read_only=args.command == "check" and not args.add_playlists)
            videos = client.all_videos(cache=Path(cfg.workspace.dir) / "_publish" / "videos", refresh=args.refresh)
            # A response without an owner id cannot be used to assign channel playlists.
            catalog = client.owned_playlists() if client._uploads_channel else []
            memberships = playlists.Memberships(client)
            if stock is not None:
                checked = check.compare(videos, stock)
                checked["rows"].extend(check.missing_playlists(videos, catalog, memberships))
                check.report(checked)
            print(f"Tổng YouTube: {len(videos)} video; search: {client.search_calls} lượt")
            if args.command == "check":
                if args.add_playlists:
                    for row in checked["rows"]:
                        if row["group"] == "playlist_missing":
                            row["playlist_added"] = memberships.add(row)
                if client._uploads_channel:
                    moment = datetime.fromtimestamp(now(), timezone.utc) if now else datetime.now(timezone.utc)
                    # Fresh video/playlist snippets already contain the owner's name.
                    title = next((item.get("snippet", {}).get("channelTitle") for item in [*videos, *catalog]
                                  if item.get("snippet", {}).get("channelTitle")), client._uploads_channel)
                    overview.write(cfg, dict(schema_version=1, channel_id=client._uploads_channel,
                                             channel_title=title, playlist_id=args.playlist,
                                             **({"token": stem} if stem else {}),
                                             updated_at=overview._iso(moment), kinds=overview.summarize(videos, moment),
                                             **overview.issues(checked, videos)))
                moment = datetime.fromtimestamp(now(), timezone.utc) if now else datetime.now(timezone.utc)
                overview.check_error(cfg, error_stem, moment)
                print(json.dumps(checked, ensure_ascii=False, indent=2))
                return 0
            moment = datetime.fromtimestamp(now(), timezone.utc) if now else datetime.now(timezone.utc)
            rows = schedule.plan(videos, moment)
            if args.only is not None:
                selected = {ident.strip() for ident in args.only.split(",") if ident.strip()}
                rows = [row for row in rows if row["youtube_id"] in selected]
            if args.limit is not None:
                selected = [row["youtube_id"] for row in rows if row["status"] == "sẵn sàng"][:args.limit]
                ready = set(selected)
                rows = [row for row in rows if row["status"] != "sẵn sàng" or row["youtube_id"] in ready]
            rows = playlists.assign(rows, catalog)
            print("Video YouTube\tLoại\tKhóa\tGiờ VN dự kiến\tTrạng thái / lý do\tDanh sách phát")
            for row in rows:
                local = ""
                if row["publish_at"]:
                    stamp = datetime.fromisoformat(row["publish_at"].replace("Z", "+00:00"))
                    local = stamp.astimezone(schedule.VN).strftime("%Y-%m-%d %H:%M")
                print(f"{row['youtube_id']}\t{schedule.KINDS.get(row['kind'], '')}\t{row['key']}\t{local}\t"
                      f"{row['status']} {row['reason']}\t{row['playlist_title'] or row['playlist_warning']}")
            for kind, label in schedule.KINDS.items():
                group = [row for row in rows if row["kind"] == kind]
                ready = sum(row["status"] == "sẵn sàng" for row in group)
                print(f"Tổng {label}: {ready} sẵn sàng, {len(group) - ready} bỏ qua")
            result = dict(mode="apply" if args.apply else "chạy thử",
                          rows=schedule.apply(cfg, rows, client, memberships=memberships) if args.apply else rows)
        else:
            # Validate local identity before reading the channel.
            episode.playlist(cfg, args.playlist)
            client = youtube.YouTube(args.client, args.token, transport=transport, now=now)
            journal = thumbs._journal(cfg)[1] if args.command == "thumbs" and args.yt_playlist else None
            videos = client.playlist_videos(args.yt_playlist) if args.yt_playlist else client.videos()
            if args.command in ("kt-thumbs", "short-thumbs"):
                is_short = args.command == "short-thumbs"
                rows = (shorts.plan(cfg, videos, pid=args.playlist, episodes=args.episodes, since=args.since) if is_short else
                        kt.plan(cfg, videos, pid=args.playlist, shape=args.shape, since=args.since))
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
        if args.command == "check" and cfg is not None:
            moment = datetime.fromtimestamp(now(), timezone.utc) if now else datetime.now(timezone.utc)
            try:
                overview.check_error(cfg, error_stem, moment, str(exc))
            except (OSError, PublishError):
                pass  # Preserve the original CLI failure even when local error storage is unavailable.
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        if args.command == "check" and cfg is not None:
            moment = datetime.fromtimestamp(now(), timezone.utc) if now else datetime.now(timezone.utc)
            try:
                overview.check_error(cfg, error_stem, moment, "file error")
            except (OSError, PublishError):
                pass
        journal = "lịch đăng" if args.command == "schedule" else "thumbnail"
        print(f"không đọc / ghi được file cấu hình, OAuth hoặc nhật ký {journal}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
