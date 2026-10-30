"""Per-clip khai thị thumbnails using approved covers and the video's resolved titles."""
from __future__ import annotations

import functools
import itertools
import os
import re
import tempfile
from pathlib import Path

from .. import khaithi
from ..hashing import config_hash, sha256_file
from ..render.stage import RenderError, _run, probe_media
from ..render.text import Font, TextError, _limit_units, check_glyphs, nfc, wrap_balanced
from ..review.logic import ReviewError, added_entries, read_review, resolve_titles
from ..titling.logic import TitlingError
from ..titling.playlist import stored_series
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PackageError, cover, episode, thumbnail

LAYOUT_VERSION = 6
PORTRAIT_NAME = re.compile(r"[0-9]{2}-[0-9a-f]{12}\.png")
CLIP_ID = re.compile(r"[km][0-9]{2,}")
FILE_NAME = re.compile(r"([km][0-9]{2,}-(?:vertical|landscape))-([a-f0-9]{64})\.jpg")


def directory(config, ident):
    if not isinstance(ident, str) or not ident.endswith(".kt"):
        raise PackageError("cần id tập khai thị")
    return episode.directory(config, ident)


def titles(config, ident, *, include_hidden=False):
    directory(config, ident)
    folder = episode._no_symlinks(Path(config.workspace.dir) / ident)
    episode._no_symlinks(folder / "khaithi.json")
    try:
        kind = khaithi.read(folder, config.khaithi.max_minutes_limit)
    except khaithi.KhaithiError as exc:
        raise PackageError(exc.vi) from exc
    if kind is None:
        return []
    if kind.base_episode_id != ident[:-3]:
        raise PackageError("tập gốc khai thị không khớp id")
    doc = read_json_dict(episode._no_symlinks(folder / "titles.json"))
    if doc is None:
        return []
    try:
        review = read_review(episode._no_symlinks(folder / "review.json"), ident)
    except ReviewError as exc:
        raise PackageError(str(exc)) from exc
    resolved, _ = resolve_titles(doc.get("titles", []) + added_entries(review), review)
    return [t for t in resolved if CLIP_ID.fullmatch(t.clip_id) and (include_hidden or t.title and not t.rejected)]


def title_lines(title, number, box):
    """Word-wrap into at most three lines; fit all ink plus the smaller number inside the box."""
    title = " ".join(nfc(title).split())
    font = Font(thumbnail.EPISODE_FONTS[cover.FONT_NAME])
    check_glyphs(font, [title, f"TẬP {number}"])
    if not title:
        raise PackageError("tiêu đề khai thị rỗng")
    x, y, w, h = box
    width, height = int(w * cover.FIT_WIDTH), int(h * cover.FIT_HEIGHT)
    for size in range(min(180, height // 2), 12, -1):
        wrapped = wrap_balanced(font, title, size, width, max_lines=3)
        if not wrapped:
            continue
        number_size = max(12, round(size * .65))
        texts = [(t, size) for t in wrapped] + [(f"TẬP {number}", number_size)]
        bounds = [font.ink_bounds(t, s) for t, s in texts]
        gap = max(6, round(size * .22))
        total = sum(bottom - top + 6 for top, bottom in bounds) + gap * (len(texts) - 1)
        if total > height:
            continue
        top = round(y + (h - total) / 2)
        result = []
        try:
            for (text, nominal), (ink_top, ink_bottom) in zip(texts, bounds):
                bottom = top + ink_bottom - ink_top + 6
                fitted, baseline = thumbnail._fit_line(text, cover.FONT_NAME, nominal, width,
                    reference=text, nominal_top=top + 2, top=top, bottom=bottom, shadow=2)
                result.append(thumbnail.EpisodeLine(text, cover.FONT_NAME, fitted, x, baseline, w, centered=True))
                top = bottom + gap
            return result
        except TextError:
            continue
    raise TextError("tiêu đề khai thị không vừa tối đa 3 dòng trong khung")


_PORTRAITS = {}  # folder -> (stat signature, (verified portraits, episode filename, episode playlists))


def _signature(folder):
    try:
        return tuple((p.name, st.st_mtime_ns, st.st_size, st.st_ino) for p in sorted(folder.iterdir())
                     if (st := p.lstat()))
    except OSError:
        return None


def portraits(config):
    """Read verified local RGBA PNGs as (path, sha256, facing), retaining manifest order."""
    return list(_portrait_catalog(config)[0])


def episode_portrait(config, pid):
    """Select the fixed episode cutout from the same cached, verified portrait catalog."""
    items, name, playlists = _portrait_catalog(config)
    if pid not in playlists:
        return None, None
    return next((item[:2] for item in items if item[0].name == name), (None, None))


def _portrait_catalog(config):
    folder = Path(config.packaging.asset_dir) / "portraits"
    signature = _signature(folder)
    cached = _PORTRAITS.get(folder)
    if signature is not None and cached and cached[0] == signature:
        return cached[1]
    result = _read_portraits(folder)
    if signature is not None:
        _PORTRAITS[folder] = (signature, result)
    return result


def _read_portraits(folder):
    try:
        folder = episode._no_symlinks(folder)
        doc = read_json_dict(episode._no_symlinks(folder / "portraits.json"))
        if not doc or type(doc.get("schema_version")) is not int or doc["schema_version"] != 1 \
                or not isinstance(doc.get("portraits"), list):
            return (), None, ()
    except (PackageError, OSError, ValueError):
        return (), None, ()
    result = []
    for entry in doc["portraits"]:
        try:
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str) \
                    or not PORTRAIT_NAME.fullmatch(entry["file"]) \
                    or not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
                continue
            path = episode._no_symlinks(folder / entry["file"])
            if not path.is_file() or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n" or sha256_file(path) != entry["sha256"]:
                continue
            stream = probe_media(path, _run)["video"]
            if not stream or stream.get("codec_name") != "png" or stream.get("pix_fmt") != "rgba":
                continue
            proc = _run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-frames:v", "1", "-f", "null", "-"])
            if proc.returncode == 0:
                facing = entry.get("facing")
                result.append((path, entry["sha256"], facing if facing in ("left", "right", "front") else "front"))
        except (PackageError, RenderError, OSError, ValueError, KeyError, TypeError):
            continue
    name = doc.get("episode")
    playlists = doc.get("episode_playlists")
    if not isinstance(playlists, list) or any(not isinstance(pid, str) or not pid.strip() for pid in playlists):
        playlists = []
    return tuple(result), name if isinstance(name, str) else None, tuple(playlists)


EPISODES_PER_PORTRAIT = 20  # HUMAN LEAD 2026-10-29: every clip of episodes 1-20 shares portrait 1, 21-40 portrait 2, ...


def start_episode(config, pid):
    """First episode that gets KT thumbnails (`khaithi_from.json`); earlier ones were already published."""
    try:
        doc = read_json_dict(episode._no_symlinks(Path(config.packaging.asset_dir) / "khaithi_from.json"))
    except (PackageError, OSError, ValueError):
        return None
    start = (doc or {}).get("playlists", {}).get(pid) if (doc or {}).get("schema_version") == 1 else None
    return start if type(start) is int and start > 1 else None


def before_start(config, pid, number):
    start = start_episode(config, pid)
    try:
        return start is not None and int(number) < start
    except (TypeError, ValueError):
        return False


def choose_portrait(items, number):
    return items[(int(number) - 1) // EPISODES_PER_PORTRAIT % len(items)] if items else (None, None, "front")


def display_fields(config, pid, fields):
    """The playlist's "Tên bộ kinh" wins over the per-video metadata header (e.g. "[HD] Kinh …"), as in PKG2."""
    try:
        series = stored_series(episode.playlist(config, pid))
    except PackageError:
        series = None
    return dict(fields, series=series or fields["series"])


# HUMAN LEAD 2026-10-29 (option B): the largest title wins (fewer lines only on a tie), filling 92 % of the
# frame width; the small lines grow with it so a thumbnail stays readable at feed size.
FIT_WIDTH = .92
LABEL_SCALE, SERIES_SCALE, SPEAKER_INK = .44, .42, .62
_CONNECTORS = frozenset("mà thì là nhưng để và nên vì khi cho của với hay hoặc".split())
# D-THUMB1-11: never split a two-syllable compound ("kỷ / niệm") unless keeping it costs > 15 % of the title size.
COMPOUNDS = Path(__file__).with_name("compounds_vi.txt")
COMPOUND_MIN_SIZE = .85


@functools.lru_cache(maxsize=1)
def _compounds():
    pairs = set()
    for line in COMPOUNDS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            first, second = line.split()
            pairs.add((nfc(first), nfc(second)))
    return frozenset(pairs)


def _compound_cuts(words):
    """Cut positions that would split a compound or a capitalised name ("Phật Đản"); punctuation ends either."""
    marks = "\"'“”‘’()[]«»"
    bare = [nfc(word).casefold() for word in words]
    pairs = _compounds()
    names = " ".join(words) != " ".join(words).upper()  # an all-caps title says nothing about names
    return {i for i in range(1, len(words))
            if (bare[i - 1].lstrip(marks), bare[i].strip(marks + ".,;:!?…")) in pairs
            or names and words[i - 1][-1:].isalpha() and words[i - 1].lstrip(marks)[:1].isupper() and words[i][:1].isupper()}


def _wrap_title(font, title, size, width, line_count, *, strict=False):
    """Fit exactly this many lines; prefer breaks before connectors, then whole compounds, then balanced widths.

    ``strict`` forbids any break inside a compound instead of only preferring fewer of them.
    """
    words = nfc(title).split()
    compound_cuts = _compound_cuts(words)
    limit = _limit_units(font, size, width)
    space = font.width_units(" ")
    advances = [0]
    for word in words:
        advances.append(advances[-1] + font.width_units(word) + space)
    connector_cuts = {i for i in range(1, len(words)) if words[i].casefold() in _CONNECTORS
                      and words[i - 1].casefold() not in _CONNECTORS}
    preferred = min(line_count - 1, len(connector_cuts))
    best = None
    for cuts in itertools.combinations(range(1, len(words)), line_count - 1):
        if any(words[cut - 1].casefold() in _CONNECTORS for cut in cuts):
            continue
        if sum(cut in connector_cuts for cut in cuts) < preferred:
            continue
        split = sum(cut in compound_cuts for cut in cuts)
        if strict and split:
            continue
        bounds = (0, *cuts, len(words))
        widths = [advances[b] - advances[a] - space for a, b in zip(bounds, bounds[1:])]
        longest = max(widths)
        if longest > limit:
            continue
        key = (split, longest, sum((limit - w) ** 2 for w in widths))
        if best is None or key < best[0]:
            best = key, bounds
    if best is not None:
        return [" ".join(words[a:b]) for a, b in zip(best[1], best[1][1:])]
    return None


DEFAULT_LABEL = "TRÍCH ĐOẠN KHAI THỊ"


def layout(title, fields, box, *, label=DEFAULT_LABEL, series_line=None):
    """Fit four text groups as one scaled block, including Vietnamese ink and shadow."""
    title = " ".join(nfc(title).split())
    if not title:
        raise TextError("tiêu đề khai thị rỗng")
    speaker = " ".join(nfc(fields["speaker"]).upper().split())
    if not speaker:
        raise TextError("tên chủ giảng khai thị rỗng")
    series = nfc(f"{fields['series']} · Tập {fields['episode']}" if series_line is None else series_line)
    fonts = {name: Font(thumbnail.EPISODE_FONTS[name]) for name in ("old", "sans")}
    check_glyphs(fonts["old"], [title])
    check_glyphs(fonts["sans"], [label, speaker, series])
    _, _, w, h = box
    width, height = int(w * FIT_WIDTH), int(h * cover.FIT_HEIGHT)
    strict = _fit(title, label, speaker, series, fonts, box, width, height, strict=True)
    free = _fit(title, label, speaker, series, fonts, box, width, height, strict=False)
    if strict and (not free or strict[0] >= free[0] * COMPOUND_MIN_SIZE):
        return strict[1:]
    if free:
        return free[1:]
    raise TextError("chữ khai thị không vừa tối đa 3 dòng tiêu đề trong khung")


def _fit(title, label, speaker, series, fonts, box, width, height, *, strict):
    """Largest (size, lines, styles) over 1–3 title lines, or None."""
    x, y, w, h = box
    candidates = []
    for line_count in range(1, min(3, len(title.split())) + 1):
        for size in range(min(180, height // 2), 12, -1):
            wrapped = _wrap_title(fonts["old"], title, size, width, line_count, strict=strict)
            if not wrapped:
                continue
            # Set speaker size from actual ink, not nominal font size (fonts have different metrics).
            title_ink = max(b - a for a, b in (fonts["old"].ink_bounds(t, size) for t in wrapped))
            speaker_size = max(12, round(size * .65))
            while speaker_size < size:
                speaker_top, speaker_bottom = fonts["sans"].ink_bounds(speaker, speaker_size)
                if speaker_bottom - speaker_top >= title_ink * SPEAKER_INK:
                    break
                speaker_size += 1
            if speaker_size >= size:
                continue
            texts = [(label, "sans", max(12, round(size * LABEL_SCALE)), "0xf2c66d", False)]
            texts += [(t, "old", size, "0xe8bf62", True) for t in wrapped]
            texts += [(speaker, "sans", speaker_size, "0xfff3d6", True),
                      (series, "sans", max(12, round(size * SERIES_SCALE)), "0xe9d9b0", False)]
            bounds = [fonts[f].ink_bounds(t, s) for t, f, s, _, _ in texts]
            gap = max(6, round(size * .2))
            total = sum(b - a + (8 if shadow else 6) for (_, _, _, _, shadow), (a, b) in zip(texts, bounds)) + gap * (len(texts) - 1)
            if total > height or any(fonts[f].width(t, s) > width * .98 for t, f, s, _, _ in texts):
                continue
            top = round(y + (h - total) / 2)
            lines, styles = [], []
            try:
                for (text, font, nominal, color, shadow), (a, b) in zip(texts, bounds):
                    bottom = top + b - a + (8 if shadow else 6)
                    fitted, baseline = thumbnail._fit_line(text, font, nominal, width, reference=text,
                        nominal_top=top + 2, top=top, bottom=bottom, shadow=2 if shadow else 0, floor=nominal)
                    lines.append(thumbnail.EpisodeLine(text, font, fitted, x, baseline, w, centered=True))
                    styles.append(dict(color=color, shadow=shadow))
                    top = bottom + gap
                candidates.append((size, lines, styles))
                break
            except TextError:
                continue
    return max(candidates, key=lambda c: c[0]) if candidates else None  # first (fewest lines) of the largest size


def draw(work, title, fields, entry, shape, image, filename, *, portrait=None, facing="front", run=None,
         label=DEFAULT_LABEL, series_line=None):
    lines, styles = layout(title, fields, entry["box"], label=label, series_line=series_line)
    return cover.draw_lines(work, lines, image, filename, styles=styles, portrait=portrait,
                            shape=shape, box=entry["box"], hflip=shape == "landscape" and facing == "left", run=run)


def cache_key(title, number, entry, shape, *, portrait_sha256=None, speaker="", series="", portrait_library=(), hflip=False,
              label=DEFAULT_LABEL, series_line=None):
    extra = {}
    if nfc(label) != DEFAULT_LABEL:
        extra["label"] = nfc(label)
    if series_line is not None and nfc(series_line) != nfc(f"{series} · Tập {number}"):
        extra["series_line"] = nfc(series_line)
    return config_hash(dict(title=nfc(title), episode=number, cover_sha256=entry["sha256"], box=entry["box"],
                            layout_version=LAYOUT_VERSION, font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]),
                            sans_sha256=sha256_file(thumbnail.EPISODE_FONTS["sans"]), speaker=nfc(speaker), series=nfc(series),
                            portrait_sha256=portrait_sha256, portrait_library=portrait_library,
                            compounds_sha256=sha256_file(COMPOUNDS),
                            shape=shape, hflip=hflip, **extra))


def read(config, ident):
    path = episode._no_symlinks(directory(config, ident) / "thumbs.json")
    doc = read_json_dict(path)
    if doc is None:
        return None
    if doc.get("schema_version") != 1 or doc.get("video_id") != ident or not isinstance(doc.get("clips"), dict):
        raise PackageError("hồ sơ thumbnail khai thị không hợp lệ")
    numbers = doc.get("clip_numbers")
    if not isinstance(numbers, dict) or len(set(numbers.values())) != len(numbers) \
            or any(not CLIP_ID.fullmatch(cid) or type(n) is not int or n < 1 for cid, n in numbers.items()):
        raise PackageError("số thứ tự clip khai thị không hợp lệ")
    for cid, files in doc["clips"].items():
        if not CLIP_ID.fullmatch(cid) or cid not in numbers or not isinstance(files, dict):
            raise PackageError("clip thumbnail khai thị không hợp lệ")
        for shape, entry in files.items():
            if shape not in thumbnail.EPISODE_SIZES or not isinstance(entry, dict) \
                    or entry.get("file") != f"{cid}-{shape}-{entry.get('key')}.jpg" \
                    or not FILE_NAME.fullmatch(entry["file"]):
                raise PackageError("file thumbnail khai thị không hợp lệ")
    return doc


def valid_files(config, ident, *, pid=None):
    try:
        doc = read(config, ident)
        if not doc or doc.get("skipped_reason"):
            return {}
        pid = pid or doc["playlist_id"]
        covers = cover.current(config, pid)
        fields = display_fields(config, pid, episode.header(config, ident[:-3]))
        if before_start(config, pid, fields["episode"]):
            return {}
        items = portraits(config)
        result = {}
        current_titles = titles(config, ident, include_hidden=True)
        if doc["clip_numbers"] != {t.clip_id: n for n, t in enumerate(current_titles, 1)}:
            return {}
        for title in current_titles:
            if not title.title or title.rejected:
                continue
            files = {}
            _, portrait_sha, facing = choose_portrait(items, fields["episode"])
            for shape, entry in doc["clips"].get(title.clip_id, {}).items():
                c = covers.get("kt_" + shape)
                if c and thumbnail.reusable(directory(config, ident), entry,
                        cache_key(title.title, fields["episode"], c, shape, portrait_sha256=portrait_sha,
                                  speaker=fields["speaker"], series=fields["series"],
                                  portrait_library=[sha for _, sha, _ in items],
                                  hflip=shape == "landscape" and facing == "left"), file_pattern=FILE_NAME):
                    files[shape] = entry
            if files:
                result[title.clip_id] = files
        return result
    except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
        return {}


def build_episode(config, ident, *, pid, run=None):
    folder = directory(config, ident)
    covers = cover.current(config, pid)
    covers = {s: covers["kt_" + s] for s in thumbnail.EPISODE_SIZES if "kt_" + s in covers}
    if not covers:
        return dict(built=0, reused=0, skipped_reason="bộ kinh chưa có ảnh bìa khai thị")
    all_titles = titles(config, ident, include_hidden=True)
    selected = [t for t in all_titles if t.title and not t.rejected]
    if not selected:
        return dict(built=0, reused=0, skipped_reason="chưa có tiêu đề clip khai thị")
    fields = display_fields(config, pid, episode.header(config, ident[:-3]))
    if before_start(config, pid, fields["episode"]):
        return dict(built=0, reused=0, skipped_reason=f"trước tập {start_episode(config, pid)} (khai thị đã đăng)")
    items = portraits(config)
    old = read(config, ident) or {}
    doc = dict(schema_version=1, video_id=ident, playlist_id=pid, header=fields, clips={},
               clip_numbers={t.clip_id: n for n, t in enumerate(all_titles, 1)}, updated_at=utc_now())
    doc["portrait_reason"] = None if items else "chưa có chân dung"
    folder.mkdir(parents=True, exist_ok=True)
    counts = dict(built=0, reused=0, skipped_reason=None)
    staged = []
    with tempfile.TemporaryDirectory(prefix=".kt-thumbs-", dir=folder) as tmp:
        for title in selected:
            files = doc["clips"][title.clip_id] = {}
            portrait, portrait_sha, facing = choose_portrait(items, fields["episode"])
            for shape, entry in covers.items():
                key = cache_key(title.title, fields["episode"], entry, shape, portrait_sha256=portrait_sha,
                                speaker=fields["speaker"], series=fields["series"], portrait_library=[sha for _, sha, _ in items],
                                hflip=shape == "landscape" and facing == "left")
                previous = old.get("clips", {}).get(title.clip_id, {}).get(shape)
                if thumbnail.reusable(folder, previous, key, file_pattern=FILE_NAME):
                    files[shape] = previous
                    counts["reused"] += 1
                    continue
                work = Path(tmp) / f"{title.clip_id}-{shape}"
                work.mkdir()
                name = f"{title.clip_id}-{shape}-{key}.jpg"
                image = draw(work, title.title, fields, entry, shape,
                             cover.directory(config, pid) / entry["file"], name, portrait=portrait, facing=facing, run=run)
                files[shape] = dict(file=name, key=key, sha256=sha256_file(image))
                staged.append((image, episode._no_symlinks(folder / name)))
                counts["built"] += 1
        for source, destination in staged:
            os.replace(source, destination)
        if staged or doc["clips"] != old.get("clips") or fields != old.get("header") \
                or doc["clip_numbers"] != old.get("clip_numbers") or doc["portrait_reason"] != old.get("portrait_reason"):
            atomic_write_json(folder / "thumbs.json", doc)
    keep = {f["file"] for files in doc["clips"].values() for f in files.values()}
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name) and path.name not in keep:
            episode._no_symlinks(path).unlink()
    return counts
