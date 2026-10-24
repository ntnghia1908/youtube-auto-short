"""Canonical visual/music specifications and independently approved TC3 variants."""
from __future__ import annotations

import json
import math
import re

from ..hashing import config_hash, fingerprint, sha256_file
from ..workspace import atomic_write_json
from . import PackageError, assets, record

VISUAL_VERSION = 1
VISUAL_FPS, VISUAL_CRF, VISUAL_GOP = 30, 23, 60
PRESETS = {"warm": ("0xdaa451", "0x493024"), "dawn": ("0xe5abb8", "0x8cb9cf"),
           "soft": ("0x646881", "0x242e40")}
KEY12 = re.compile(r"[a-f0-9]{12}")
MEDIA_NAME = re.compile(r"(variant|preview|loop)-([a-f0-9]{12})\.mp4")
MUSIC_PREVIEW = re.compile(r"preview-([a-f0-9]{12})-([123])\.m4a")


def normalize(spec):
    if isinstance(spec, dict) and spec.get("music") is not None:
        if set(spec) != {"visual", "music"}:
            raise PackageError("cấu hình variant không hợp lệ")
        v = normalize({"visual": spec["visual"]})["visual"] if spec["visual"] is not None else None
        return dict(visual=v, music=normalize_music(spec["music"]))
    if isinstance(spec, dict) and "music" in spec:
        if set(spec) != {"visual", "music"}:
            raise PackageError("cấu hình variant không hợp lệ")
        spec = {"visual": spec["visual"]}
    try:
        if not isinstance(spec, dict) or set(spec) != {"visual"} or not isinstance(spec["visual"], dict):
            raise ValueError
        v = dict(mode="ambient", asset_id="generated:warm", motion="none", fit="cover",
                 loop_seconds=40, crossfade=2.0)
        if set(spec["visual"]) - set(v):
            raise ValueError
        v.update(spec["visual"])
        if v["mode"] != "ambient" or v["motion"] not in ("none", "kenburns") \
                or v["fit"] not in ("cover", "blur") or not isinstance(v["asset_id"], str) \
                or not (record.SHA.fullmatch(v["asset_id"]) or v["asset_id"] in {"generated:" + p for p in PRESETS}) \
                or type(v["loop_seconds"]) is not int or not 2 <= v["loop_seconds"] <= 120 \
                or v["loop_seconds"] % 2 or type(v["crossfade"]) not in (int, float) \
                or not math.isfinite(v["crossfade"]) or not .5 <= v["crossfade"] <= 5 \
                or (v["asset_id"].startswith("generated:") and v["motion"] != "none"):
            raise ValueError
        v["crossfade"] = round(float(v["crossfade"]), 1)
        return {"visual": v}
    except (ValueError, TypeError):
        raise PackageError("cấu hình hình ambient không hợp lệ") from None


def normalize_music(value):
    defaults = dict(asset_id=None, level_lu=-20, fade_in=3, fade_out=5, loop_crossfade=3)
    try:
        if not isinstance(value, dict) or set(value) - set(defaults):
            raise ValueError
        m = defaults | value
        if not isinstance(m["asset_id"], str) or not record.SHA.fullmatch(m["asset_id"]):
            raise ValueError
        for name, low, high in (("level_lu", -30, -12), ("fade_in", 0, 10),
                                ("fade_out", 0, 15), ("loop_crossfade", .5, 8)):
            x = m[name]
            if type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high:
                raise ValueError
            if name == "level_lu" and x * 2 != round(x * 2):
                raise ValueError
            m[name] = round(float(x), 1)
        return m
    except (ValueError, TypeError):
        raise PackageError("cấu hình nhạc không hợp lệ") from None


def source(spec, asset_dir):
    spec = normalize(spec)
    if "music" in spec:
        entry, path = assets.usable(asset_dir, spec["music"]["asset_id"], kind="music")
        needed = 2 * spec["music"]["loop_crossfade"] + 1
        if entry["duration"] < needed:
            raise PackageError(f"Nhạc cần dài ít nhất {needed:g} giây")
        if spec["visual"] is None:
            return "music", path
    v = spec["visual"]
    if v["asset_id"].startswith("generated:"):
        return "generated", None
    entry, _ = assets.usable(asset_dir, v["asset_id"])
    if entry["kind"] not in ("image", "loop") or (entry["kind"] == "loop" and v["motion"] != "none"):
        raise PackageError("Ken Burns chỉ dùng cho ảnh; nguồn phải là ảnh hoặc loop")
    _, path = assets.usable(asset_dir, v["asset_id"], kind=entry["kind"])
    needed = v["loop_seconds"] + v["crossfade"]
    if entry["kind"] == "loop" and entry["duration"] < needed:
        raise PackageError(f"Loop dài {entry['duration']:g} giây, cần ít nhất {needed:g} giây; "
                           "hãy chọn vòng ngắn hơn")
    return entry["kind"], path


def encoding():
    return dict(version=VISUAL_VERSION, fps=VISUAL_FPS, crf=VISUAL_CRF, gop=VISUAL_GOP)


def key(spec, tc3_sha256=None, *, settings=None):
    spec = normalize(spec)
    if "music" in spec:
        from .music import encoding as music_encoding
        values = dict(spec=spec, asset=spec["music"]["asset_id"], **(settings or music_encoding()))
        if spec["visual"] is not None:
            values["visual_key"] = key({"visual": spec["visual"]}, tc3_sha256)
    else:
        values = dict(spec=spec, asset=spec["visual"]["asset_id"], **(settings or encoding()))
    if tc3_sha256 is not None:
        if not isinstance(tc3_sha256, str) or not record.SHA.fullmatch(tc3_sha256):
            raise PackageError("invalid TC3 sha256")
        values["tc3_sha256"] = tc3_sha256
    return config_hash(values)


def reference(path, meta):
    return {"file": path.name, **{k: meta[k] for k in ("sha256", "plan_id", "revision", "plan_fingerprint")}}


def validate(doc):
    try:
        spec, tc3, settings = normalize(doc["spec"]), doc["tc3"], doc["encoding"]
        has_music = "music" in spec
        if has_music:
            _validate_music(doc, spec, tc3, settings)
        elif not isinstance(settings, dict) or set(settings) != {"version", "fps", "crf", "gop"} \
                or not all(type(v) is int for v in settings.values()) or settings["version"] < 1 \
                or (settings["fps"], settings["gop"]) != (30, 60) or not 0 <= settings["crf"] <= 51:
            raise ValueError
        if doc["schema_version"] != 1 or doc["spec"] != spec \
                or doc["key"] != key(spec, tc3["sha256"], settings=settings) \
                or (not has_music and doc["loop_key"] != key(spec, settings=settings)) \
                or not record.PLAN_ID.fullmatch(tc3["plan_id"]) \
                or type(tc3["revision"]) is not int or not 1 <= tc3["revision"] <= 9999999999 \
                or tc3["file"] != f"{tc3['plan_id']}-r{tc3['revision']}.mp4" \
                or not record.SHA.fullmatch(tc3["plan_fingerprint"]) or not record.SHA.fullmatch(doc["sha256"]) \
                or type(doc["size"]) is not int or doc["size"] <= 0 \
                or any(type(doc[k]) not in (int, float) or not math.isfinite(doc[k]) or doc[k] < 0
                       for k in ("duration", "build_seconds")) or doc["duration"] <= 0 \
                or not isinstance(doc["chapters"], list) or not isinstance(doc["description"], str) \
                or not isinstance(doc["built_at"], str) or not doc["built_at"] \
                or (doc["approved_at"] is not None and (not isinstance(doc["approved_at"], str) or not doc["approved_at"])):
            raise ValueError
        if has_music:
            return doc
        c = doc["checks"]
        if (c["width"], c["height"], c["sar"]) != (1920, 1080, "1:1") \
                or c["method"] not in ("copy", "reencode") or c["black"] is not False \
                or type(c["seam_ssim"]) not in (int, float) or not .97 <= c["seam_ssim"] <= 1 \
                or not record.SHA.fullmatch(c["audio_streamhash"]):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PackageError("invalid variant record") from None
    return doc


def _validate_music(doc, spec, tc3, settings):
    from ..theme_render import audio
    try:
        m, v, c = doc["music"], doc["video_source"], doc["checks"]
        if set(settings) != {"music_version", "audio_bitrate"} or type(settings["music_version"]) is not int \
                or settings["music_version"] < 1 or not re.fullmatch(r"[1-9][0-9]*k", settings["audio_bitrate"]) \
                or "loop_key" in doc:
            raise ValueError
        if m["asset_id"] != spec["music"]["asset_id"] or any(type(m[k]) not in (int, float) or not math.isfinite(m[k])
                for k in ("voice_lufs", "music_lufs", "gain_db", "true_peak", "true_peak_tc3", "true_peak_limit", "corr", "lag")) \
                or m["music_lufs"] < -60 or m["true_peak_limit"] != max(-1., m["true_peak_tc3"] + .5) \
                or m["true_peak"] > m["true_peak_limit"] or not audio.MIN_CORRELATION <= m["corr"] <= 1 \
                or abs(m["lag"]) > audio.MAX_LAG + 1e-9 \
                or abs(m["gain_db"] - (m["voice_lufs"] + spec["music"]["level_lu"] - m["music_lufs"])) > 1e-6 \
                or (c["codec"], c["channels"], c["sample_rate"], c["method"]) != ("aac", 2, 48000, "copy") \
                or not 0 <= c["duration_diff"] <= 1024 / 48000 + 1e-9 \
                or not record.SHA.fullmatch(c["video_streamhash"]) or not record.SHA.fullmatch(v["sha256"]):
            raise ValueError
        expected = "tc3" if spec["visual"] is None else key({"visual": spec["visual"]}, tc3["sha256"])
        if v["key"] != expected or (expected == "tc3" and v["sha256"] != tc3["sha256"]):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PackageError("invalid music variant record") from None
    return doc


def read(folder, key12):
    if not isinstance(key12, str) or not KEY12.fullmatch(key12):
        raise PackageError("invalid variant key")
    path = folder / f"variant-{key12}.json"
    if not path.exists():
        return None
    try:
        if path.is_symlink():
            raise PackageError("variant record must not be a symlink")
        doc = validate(json.loads(path.read_text(encoding="utf-8")))
        if doc["key"][:12] != key12:
            raise PackageError("variant filename/key mismatch")
        return doc
    except (OSError, ValueError) as exc:
        raise PackageError("cannot read variant record") from exc


def write(folder, doc):
    validate(doc)
    atomic_write_json(folder / f"variant-{doc['key'][:12]}.json", doc)


def reusable(folder, doc, *, cache=None):
    path = folder / f"variant-{doc['key'][:12]}.mp4"
    if not path.is_file() or path.is_symlink():
        return False
    if cache is None:
        return path.stat().st_size == doc["size"] and sha256_file(path) == doc["sha256"]
    previous = cache.get(path.resolve())
    current = fingerprint(path, (previous,) if previous is not None else ())
    cache[current.path] = current
    return current.size == doc["size"] and current.sha256 == doc["sha256"]


def status(folder, doc, plan, meta, *, cache=None, asset_dir=None):
    stale = meta is None or any(doc["tc3"][k] != meta[k] for k in ("sha256", "revision", "plan_fingerprint")) \
        or doc["tc3"]["plan_id"] != plan["plan_id"] or doc["tc3"]["revision"] != plan["revision"] \
        or doc["tc3"]["plan_fingerprint"] != record.fingerprint(plan) or not reusable(folder, doc, cache=cache)
    if not stale and "music" in doc["spec"]:
        try:
            if asset_dir is not None:
                source(doc["spec"], asset_dir)
            video = doc["video_source"]
            if video["key"] != "tc3":
                origin = read(folder, video["key"][:12])
                stale = origin is None or origin["sha256"] != video["sha256"] or origin["tc3"] != doc["tc3"] \
                    or not reusable(folder, origin, cache=cache)
        except PackageError:
            stale = True
    return "stale" if stale else "approved" if doc["approved_at"] else "draft"


def listing(folder, plan, meta, *, cache=None, asset_dir=None):
    result = []
    if folder.parent.is_dir():
        for candidate in sorted(folder.parent.glob(plan["plan_id"] + "-r*")):
            match = record.REVISION.fullmatch(candidate.name)
            if not match or candidate.is_symlink():
                continue
            for path in sorted(candidate.glob("variant-*.json")):
                ident = path.stem.removeprefix("variant-")
                if not KEY12.fullmatch(ident):
                    continue
                try:
                    doc = read(candidate, ident)
                    state = status(candidate, doc, plan, meta, cache=cache, asset_dir=asset_dir) if candidate == folder else "stale"
                    result.append((candidate, doc, state))
                except PackageError:
                    continue
    return result


def delete(folder, doc):
    ident = doc["key"][:12]
    for suffix in ("mp4", "json"):
        (folder / f"variant-{ident}.{suffix}").unlink(missing_ok=True)
    (folder / f"preview-{ident}.mp4").unlink(missing_ok=True)
    for index in (1, 2, 3):
        (folder / f"preview-{ident}-{index}.m4a").unlink(missing_ok=True)
    if "music" in doc["spec"]:
        return
    for path in folder.glob("variant-*.json"):
        try:
            other = read(folder, path.stem.removeprefix("variant-"))
            if other.get("loop_key") == doc["loop_key"]:
                return
        except PackageError:
            continue
    (folder / f"loop-{doc['loop_key'][:12]}.mp4").unlink(missing_ok=True)
