"""Versioned package records and canonical input keys (PKG R3/R4; schema 2 = PKG3 styles A/B/C)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path

from .. import theme_plan
from ..compilation import store
from ..hashing import config_hash
from ..render.text import nfc
from ..titling.playlist import stored_series
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PackageError

PLAN_ID = re.compile(r"[a-z0-9]{8,32}")
REVISION = re.compile(r"([a-z0-9]{8,32})-r([1-9][0-9]{0,9})")
SHA = re.compile(r"[a-f0-9]{64}")
# Group 1 = shape, group 2 = cache key (same group layout as packaging.episode.FILE_NAME, so thumbnail.reusable works).
FILE_NAME = re.compile(r"(?:A|B|C)-(landscape|vertical)-([a-f0-9]{64})\.jpg")
SCHEMA_VERSION = 2
STYLES = ("A", "B", "C")
SHAPES = ("landscape", "vertical")
PALETTES = ("nau-vang", "xanh-ngoc", "do-son", "xanh-dem")  # ids only; drawing data: thumbnail.PALETTES
BACKGROUNDS = ("plain", "blur")
KIND_TITLE = "Tuyển tập khai thị"
DEFAULT_SPEAKER = "Hòa Thượng Tịnh Không"
MAX_LINE, MAX_SERIES, MAX_SPEAKER = 40, 100, 60
SETTING_FIELDS = ("title_lines", "series", "speaker", "minutes", "focus_x", "palette", "background")


def directory(output_dir, pid, plan_id, revision):
    if not PLAN_ID.fullmatch(plan_id) or type(revision) is not int or not 1 <= revision <= 9999999999:
        raise PackageError("invalid package plan/revision")
    # Playlist identities are checked at the web boundary; also guard direct callers.
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", pid):
        raise PackageError("invalid playlist id")
    folder = store.directory(output_dir, pid) / "theme" / "pkg" / f"{plan_id}-r{revision}"
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise PackageError("package directory must not contain symlinks")
    return folder


def fingerprint(plan):
    return theme_plan.plan_fingerprint({k: v for k, v in plan.items() if k != "check"})


def title_options(config, plan):
    speaker = theme_plan.speaker_for_clips(config, plan["clips"])
    traditional = theme_plan._compose_title(plan["theme"]["label"], "B", speaker)
    return [*plan.get("title_options", []), traditional]


def _header_series(config, plan):
    """Series of the first source video with a valid titling header (same fallback as episode thumbnails)."""
    from ..titling.logic import TitlingError
    from . import episode  # lazy: episode imports thumbnail, which imports this module
    for clip in (plan or {}).get("clips") or []:
        try:
            return episode.header(config, clip["episode_id"])["series"]
        except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _series(config, pid, plan=None):
    """The playlist's "Tên bộ kinh" (else its title); "" when the playlist file is unavailable."""
    if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", pid):
        return ""
    doc = read_json_dict(Path(config.workspace.dir) / "_playlists" / f"{pid}.json")
    if not isinstance(doc, dict):
        return ""
    value = stored_series(doc) or _header_series(config, plan) or doc.get("title")
    return " ".join(nfc(value).split())[:MAX_SERIES] if isinstance(value, str) else ""


def default_settings(config, plan, tc3, pid=None):
    speaker = theme_plan.speaker_for_clips(config, plan["clips"])
    speaker = theme_plan._HT.sub("Hòa Thượng ", speaker).strip() if speaker else ""
    duration = tc3.get("duration") if isinstance(tc3, dict) else None
    ok = type(duration) in (int, float) and math.isfinite(duration) and duration > 0
    label = " ".join(nfc(plan["theme"]["label"]).split())
    if len(label) > MAX_LINE:  # a default must be valid: cut at a word boundary, never mid-word
        label = label[:MAX_LINE].rsplit(" ", 1)[0] if " " in label[:MAX_LINE] else label[:MAX_LINE]
    return dict(title_lines=[KIND_TITLE, label],
                series=_series(config, pid, plan), speaker=speaker or DEFAULT_SPEAKER,
                minutes=max(1, round(duration / 60)) if ok else 1,
                focus_x=0.5, palette="nau-vang", background="plain")


def default_asset_ids(config, plan_id):
    """One deterministic usable image per plan (index = sha256(plan_id) mod count); none when the library is empty."""
    from . import episode  # lazy: episode imports thumbnail, which imports this module
    try:
        ids = [a["id"] for a in episode.images(config)]
    except (PackageError, OSError, ValueError, KeyError):
        return []
    if not ids:
        return []
    return [ids[int(hashlib.sha256(plan_id.encode("utf-8")).hexdigest(), 16) % len(ids)]]


def new(config, plan, tc3, pid=None):
    options = title_options(config, plan)
    default_assets = default_asset_ids(config, plan["plan_id"])
    return dict(schema_version=SCHEMA_VERSION, plan_id=plan["plan_id"], revision=plan["revision"],
                plan_fingerprint=fingerprint(plan), tc3_sha256=tc3["sha256"], title_options=options,
                title=plan["title"], settings=default_settings(config, plan, tc3, pid),
                thumbnails=[dict(style=s, layout_version=1, asset_ids=list(default_assets), files={shape: None for shape in SHAPES})
                            for s in STYLES], selected="A", state="draft", approved_at=None,
                updated_at=utc_now())


def cache_key(doc, entry, shape, layout, font_sha):
    """Only the settings a style actually draws take part: palette / background belong to style A alone."""
    s, style = doc["settings"], entry["style"]
    used = {k: s[k] for k in ("title_lines", "series", "speaker", "minutes", "focus_x")}
    if style == "A":
        used.update(palette=s["palette"], background=s["background"])
    return config_hash(dict(tc3_sha256=doc["tc3_sha256"], style=style, shape=shape, layout=layout,
                            settings=used, asset_ids=entry["asset_ids"], font_sha256=font_sha))


def validate_settings(s):
    """Shape and bounds only; fit / glyphs / blur-needs-image are checked by thumbnail.check."""
    if not isinstance(s, dict) or set(s) != set(SETTING_FIELDS):
        raise PackageError("invalid package settings")
    lines = s["title_lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3 \
            or any(not isinstance(v, str) or not v.strip() or len(nfc(v)) > MAX_LINE or len(v.splitlines()) != 1
                   for v in lines):
        raise PackageError("tiêu đề ảnh cần 1–3 dòng không rỗng, tối đa 40 ký tự mỗi dòng")
    for name, limit in (("series", MAX_SERIES), ("speaker", MAX_SPEAKER)):
        if not isinstance(s[name], str) or len(nfc(s[name])) > limit or len(s[name].splitlines()) > 1:
            raise PackageError(f"{name} tối đa {limit} ký tự trên một dòng")
    if type(s["minutes"]) is not int or not 1 <= s["minutes"] <= 9999:
        raise PackageError("thời lượng phải từ 1 đến 9999 phút")
    if type(s["focus_x"]) not in (int, float) or isinstance(s["focus_x"], bool) \
            or not 0 <= s["focus_x"] <= 1:
        raise PackageError("vị trí ảnh phải từ 0 đến 1")
    if s["palette"] not in PALETTES:
        raise PackageError("bảng màu không hợp lệ")
    if s["background"] not in BACKGROUNDS:
        raise PackageError("nền không hợp lệ")
    return s


def normalize_settings(s):
    """NFC + collapsed whitespace, then validate; empty title lines are dropped (the rest move up)."""
    if not isinstance(s, dict) or not isinstance(s.get("title_lines"), list):
        raise PackageError("invalid package settings")
    s = dict(s)
    lines = [" ".join(nfc(v).split()) if isinstance(v, str) else v for v in s["title_lines"]]
    s["title_lines"] = [v for v in lines if v != ""]
    for name in ("series", "speaker"):
        if isinstance(s.get(name), str):
            s[name] = " ".join(nfc(s[name]).split())
    return validate_settings(s)


def validate(doc):
    try:
        if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION \
                or not PLAN_ID.fullmatch(doc["plan_id"]) or type(doc["revision"]) is not int \
                or not 1 <= doc["revision"] <= 9999999999 \
                or not all(SHA.fullmatch(doc[k]) for k in ("plan_fingerprint", "tc3_sha256")) \
                or doc["state"] not in ("draft", "approved", "stale") or doc["selected"] not in STYLES \
                or not all(isinstance(doc[k], str) and doc[k].strip() for k in ("title", "updated_at")) \
                or not isinstance(doc["title_options"], list) \
                or not all(isinstance(t, str) for t in doc["title_options"]) \
                or (doc["approved_at"] is not None and not isinstance(doc["approved_at"], str)) \
                or (doc["state"] == "approved" and not doc["approved_at"]) \
                or not isinstance(doc["thumbnails"], list) or len(doc["thumbnails"]) != len(STYLES):
            raise PackageError("invalid package record")
        validate_settings(doc["settings"])
        seen = []
        for t in doc["thumbnails"]:
            if t["style"] not in STYLES or t["style"] in seen \
                    or type(t["layout_version"]) is not int or t["layout_version"] < 1 \
                    or not isinstance(t["asset_ids"], list) or len(t["asset_ids"]) > 1 \
                    or not all(isinstance(a, str) and SHA.fullmatch(a) for a in t["asset_ids"]) \
                    or not isinstance(t["files"], dict) or set(t["files"]) != set(SHAPES):
                raise PackageError("invalid thumbnail entry")
            seen.append(t["style"])
            for shape, f in t["files"].items():
                if f is None:
                    continue
                match = FILE_NAME.fullmatch(f["file"])
                if match is None or not f["file"].startswith(f"{t['style']}-{shape}-") \
                        or match[2] != f["key"] or not SHA.fullmatch(f["sha256"]):
                    raise PackageError("invalid thumbnail file")
    except (KeyError, TypeError, AttributeError) as exc:
        raise PackageError("invalid package record") from exc
    return doc


def read(folder):
    path = folder / "package.json"
    if not path.exists():
        return None
    if path.is_symlink():
        raise PackageError("invalid package record path")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("schema_version") == 1:
            return None  # PKG1 record: treated as not built yet; the next build writes schema 2
        doc = validate(doc)
        if folder.name != f"{doc['plan_id']}-r{doc['revision']}":
            raise PackageError("package identity mismatch")
        return doc
    except (OSError, ValueError) as exc:
        raise PackageError("cannot read package record") from exc


def status(doc, plan, tc3):
    doc = deepcopy(doc)
    if doc["revision"] != plan["revision"] or doc["plan_fingerprint"] != fingerprint(plan) \
            or tc3 is None or doc["tc3_sha256"] != tc3["sha256"]:
        doc.update(state="stale", approved_at=None)
    return doc


def write(folder, doc):
    validate(doc)
    atomic_write_json(folder / "package.json", doc)
