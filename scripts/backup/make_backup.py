"""Build backup.ps1 (+ rename.ps1): Windows script backing up the HD (landscape) + vertical files of a bộ kinh from the
web server, with the server's sha256 table embedded (HD1 G6).

    python scripts/backup/make_backup.py --playlist PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4 \\
        --series "Kinh Địa Tạng Bồ Tát Bổn Nguyện" [--out DIR] [--dest-name KinhDiaTang_HD] [--config config.toml]

HD sha256 comes from work/<id>/enhance.json (size must match the file); vertical sha256 is hashed here (nice 19) and
cached by size + mtime_ns in ``<out>/vertical-sha.cache.json``. Paths come from the config (``[workspace] dir``,
``[render] output_dir``), relative paths are relative to the repository root. Read-only on the server data.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAYLIST_RE = re.compile(r"[A-Za-z0-9_-]{2,64}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def ps_quote(text: str) -> str:
    """Body of a PowerShell single-quoted string."""
    return text.replace("'", "''")


def sha_table(workspace: Path, output: Path, ids: list[str], cache_path: Path) -> dict[str, str]:
    """``{"<id>|HD": sha, "<id>|Doc": sha}`` of the files the server holds now."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    table: dict[str, str] = {}
    for vid in ids:
        # FIX-hd-owner-kt: a video whose Shorts were deleted keeps its HD / vertical under <id>.kt
        own = vid if (workspace / vid).is_dir() or not (workspace / (vid + ".kt")).is_dir() else vid + ".kt"
        doc, hd = workspace / own / "enhance.json", workspace / own / "source_hd.mp4"
        if doc.is_file() and hd.is_file():
            d = json.loads(doc.read_text(encoding="utf-8"))
            if d.get("source_hd_sha256") and d.get("source_hd_size") == hd.stat().st_size:
                table[f"{vid}|HD"] = d["source_hd_sha256"]
        mp4 = output / own / "full" / "vertical.mp4"
        if mp4.is_file():
            st = mp4.stat()
            stamp = f"{st.st_size}:{st.st_mtime_ns}"
            if cache.get(vid, {}).get("stamp") != stamp:
                cache[vid] = {"stamp": stamp, "sha256": sha256(mp4)}
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            table[f"{vid}|Doc"] = cache[vid]["sha256"]
    return table


def render(template: str, *, table: dict[str, str], playlist: str, series: str, dest_name: str,
           today: str) -> str:
    lines = "\n".join(f'    "{k}" = "{v}"' for k, v in sorted(table.items()))
    return (template.replace("@@SHA@@", lines).replace("@@GENERATED@@", today)
            .replace("@@PLAYLIST@@", ps_quote(playlist)).replace("@@SERIES@@", ps_quote(series))
            .replace("@@DESTNAME@@", ps_quote(dest_name)))


def to_crlf_bom(text: str) -> bytes:
    return b"\xef\xbb\xbf" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--playlist", required=True, help="playlist id of the bộ kinh (work/_playlists/<id>.json)")
    ap.add_argument("--series", required=True, help='bộ kinh name used in file names, e.g. "Kinh Địa Tạng Bồ Tát Bổn Nguyện"')
    ap.add_argument("--dest-name", default="KinhHD", help="default folder name on the backup drive (D:\\<name>)")
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "_backup", help="where the .ps1 files + sha cache go")
    ap.add_argument("--config", type=Path, default=None, help="config.toml (default: ./config.toml of the repository)")
    args = ap.parse_args(argv)
    if not PLAYLIST_RE.fullmatch(args.playlist):
        ap.error("playlist id không hợp lệ")
    if not args.series.strip() or any(c in args.series for c in '\\/:*?"<>|\r\n'):
        ap.error("--series rỗng hoặc có ký tự không dùng được trong tên file")
    sys.path.insert(0, str(ROOT / "src"))
    from auto_short import config as cfg_mod  # noqa: E402

    cfg_path = args.config or (ROOT / "config.toml")
    cfg = cfg_mod.load(cfg_path if cfg_path.is_file() else None)
    workspace = Path(cfg.workspace.dir)
    output = Path(cfg.render.output_dir)
    workspace = workspace if workspace.is_absolute() else ROOT / workspace
    output = output if output.is_absolute() else ROOT / output
    os.nice(19)
    doc = json.loads((workspace / "_playlists" / f"{args.playlist}.json").read_text(encoding="utf-8"))
    ids = [e["video_id"] for e in doc["entries"] if e.get("video_id")]
    args.out.mkdir(parents=True, exist_ok=True)
    table = sha_table(workspace, output, ids, args.out / "vertical-sha.cache.json")
    text = render((HERE / "backup.template.ps1").read_text(encoding="utf-8"), table=table, playlist=args.playlist,
                  series=args.series.strip(), dest_name=args.dest_name, today=datetime.date.today().isoformat())
    out = args.out / "backup.ps1"
    out.write_bytes(to_crlf_bom(text))
    rename = render((HERE / "rename.template.ps1").read_text(encoding="utf-8"), table={}, playlist=args.playlist,
                    series=args.series.strip(), dest_name=args.dest_name, today="")
    (args.out / "rename.ps1").write_bytes(to_crlf_bom(rename))
    hd = sum(k.endswith("|HD") for k in table)
    print(f"{out}: {hd} HD + {len(table) - hd} Doc sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
