"""Local packaging assets and series covers: python -m auto_short.packaging --help."""
import argparse
import json
import sys
from pathlib import Path

from ..config import ConfigError, load
from ..render.stage import RenderError
from . import PackageError, assets, cover, thumbnail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    library = commands.add_parser("assets").add_subparsers(dest="action", required=True)
    add = library.add_parser("add")
    add.add_argument("file", type=Path)
    add.add_argument("--kind", choices=assets.KINDS, required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--license", default="")
    add.add_argument("--tag", action="append", default=[])
    for field in ("title", "artist", "attribution"):
        add.add_argument("--" + field)
    add.add_argument("--loop-end", type=float)
    library.add_parser("approve").add_argument("id")
    library.add_parser("unapprove").add_argument("id")
    music = library.add_parser("import-music")
    music.add_argument("manifest", type=Path)
    music.add_argument("--dir", dest="directory", type=Path, required=True)
    library.add_parser("list")
    library.add_parser("import-post-images").add_argument("--license", required=True)
    covers = commands.add_parser("cover").add_subparsers(dest="action", required=True)
    for action in ("install", "remove", "show"):
        command = covers.add_parser(action)
        command.add_argument("--playlist", required=True)
        if action != "show":
            command.add_argument("--shape", choices=cover.SIZES, required=True)
        if action == "install":
            command.add_argument("--image", type=Path, required=True)
            command.add_argument("--box", required=True, help="x,y,w,h in source-image pixels")
            command.add_argument("--prompt-file", type=Path)
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        if args.command == "cover":
            if args.action == "install":
                try:
                    box = [int(v) for v in args.box.split(",")]
                except ValueError as exc:
                    raise PackageError("box cần bốn số nguyên x,y,w,h") from exc
                prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else None
                result = cover.install(cfg, args.playlist, args.shape, args.image, box, prompt=prompt)
            elif args.action == "remove":
                result = cover.remove(cfg, args.playlist, args.shape)
            else:
                result = cover.read(cfg, args.playlist)
        elif args.action == "add":
            result = assets.add(cfg.packaging.asset_dir, args.file, kind=args.kind, source=args.source,
                                license=args.license, tags=args.tag, title=args.title, artist=args.artist,
                                attribution=args.attribution, loop_end=args.loop_end)
        elif args.action == "approve":
            result = assets.approve(cfg.packaging.asset_dir, args.id)
        elif args.action == "unapprove":
            result = assets.unapprove(cfg.packaging.asset_dir, args.id)
        elif args.action == "import-music":
            result = assets.import_music(cfg.packaging.asset_dir, args.manifest, args.directory)
        elif args.action == "import-post-images":
            result = assets.import_post_images(cfg, license=args.license)
        else:
            result = assets.list_assets(cfg.packaging.asset_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ConfigError, PackageError, RenderError, UnicodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
