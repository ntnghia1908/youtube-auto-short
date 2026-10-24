"""Build kdt-backup.ps1 (Windows backup of Kinh Địa Tạng HD + vertical) with the server's sha256 table embedded.

    python3 -I ~/.local/share/auto-short/backup/make-kdt-backup.py

HD sha256 comes from work/<id>/enhance.json; vertical sha256 is hashed here (nice 19) and cached by size + mtime.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path

ROOT = Path("/home/ntnghia/projects/youtube-auto-short")
HERE = Path(__file__).resolve().parent
PLAYLIST = ROOT / "work/_playlists/PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4.json"
CACHE = HERE / "vertical-sha.cache.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    os.nice(19)
    ids = [e["video_id"] for e in json.loads(PLAYLIST.read_text())["entries"]]
    cache = json.loads(CACHE.read_text()) if CACHE.is_file() else {}
    table = {}
    for vid in ids:
        doc = ROOT / "work" / vid / "enhance.json"
        hd = ROOT / "work" / vid / "source_hd.mp4"
        if doc.is_file() and hd.is_file():
            d = json.loads(doc.read_text())
            if d.get("source_hd_sha256") and d.get("source_hd_size") == hd.stat().st_size:
                table[f"{vid}|HD"] = d["source_hd_sha256"]
        mp4 = ROOT / "output" / vid / "full" / "vertical.mp4"
        if mp4.is_file():
            st = mp4.stat()
            stamp = f"{st.st_size}:{st.st_mtime_ns}"
            if cache.get(vid, {}).get("stamp") != stamp:
                cache[vid] = {"stamp": stamp, "sha256": sha256(mp4)}
                CACHE.write_text(json.dumps(cache, indent=1))
            table[f"{vid}|Doc"] = cache[vid]["sha256"]
    lines = "\n".join(f'    "{k}" = "{v}"' for k, v in sorted(table.items()))
    text = (HERE / "kdt-backup.template.ps1").read_text()
    text = text.replace("@@SHA@@", lines).replace("@@GENERATED@@", datetime.date.today().isoformat())
    out = HERE / "kdt-backup.ps1"
    out.write_bytes(b"\xef\xbb\xbf" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    rename = (HERE / "kdt-rename.template.ps1").read_text()
    (HERE / "kdt-rename.ps1").write_bytes(b"\xef\xbb\xbf" + rename.replace("\n", "\r\n").encode("utf-8"))
    hd = sum(k.endswith("|HD") for k in table)
    print(f"{out}: {hd} HD + {len(table) - hd} Doc sha256")


main()
