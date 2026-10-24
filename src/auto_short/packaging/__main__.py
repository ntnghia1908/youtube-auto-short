"""Local asset management: python -m auto_short.packaging assets --help."""
import argparse
import json
import sys
from pathlib import Path

from ..config import ConfigError, load
from ..render.stage import RenderError
from . import PackageError, assets


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
    library.add_parser("approve").add_argument("id")
    library.add_parser("list")
    library.add_parser("import-post-images").add_argument("--license", required=True)
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
        if args.action == "add":
            result = assets.add(cfg.packaging.asset_dir, args.file, kind=args.kind, source=args.source,
                                license=args.license, tags=args.tag)
        elif args.action == "approve":
            result = assets.approve(cfg.packaging.asset_dir, args.id)
        elif args.action == "import-post-images":
            result = assets.import_post_images(cfg, license=args.license)
        else:
            result = assets.list_assets(cfg.packaging.asset_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ConfigError, PackageError, RenderError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
