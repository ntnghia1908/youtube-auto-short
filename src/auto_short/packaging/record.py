"""Versioned package records and canonical input keys (PKG R3/R4)."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from .. import theme_plan
from ..compilation import store
from ..hashing import config_hash
from ..render.text import nfc
from ..workspace import atomic_write_json, utc_now
from . import PackageError

PLAN_ID = re.compile(r"[a-z0-9]{8,32}")
REVISION = re.compile(r"([a-z0-9]{8,32})-r([1-9][0-9]{0,9})")
SHA = re.compile(r"[a-f0-9]{64}")
FILE_NAME = re.compile(r"(classic|minimal|scenic)-([a-f0-9]{64})\.jpg")
TEMPLATES = ("classic", "minimal", "scenic")


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


def new(config, plan, tc3):
    options = title_options(config, plan)
    return dict(schema_version=1, plan_id=plan["plan_id"], revision=plan["revision"],
                plan_fingerprint=fingerprint(plan), tc3_sha256=tc3["sha256"], title_options=options,
                title=plan["title"], headline=nfc(plan["theme"]["label"]),
                thumbnails=[dict(template=t, template_version=1, asset_ids=[], file=None, sha256=None, key=None)
                            for t in TEMPLATES], selected="classic", state="draft", approved_at=None,
                updated_at=utc_now())


def cache_key(doc, template, version, asset_ids, font_sha):
    return config_hash(dict(tc3_sha256=doc["tc3_sha256"], template=template, template_version=version,
                            headline=nfc(doc["headline"]), asset_ids=asset_ids, font_sha256=font_sha))


def validate(doc):
    try:
        if not isinstance(doc, dict) or doc.get("schema_version") != 1 \
                or not PLAN_ID.fullmatch(doc["plan_id"]) or type(doc["revision"]) is not int \
                or not 1 <= doc["revision"] <= 9999999999 \
                or not all(SHA.fullmatch(doc[k]) for k in ("plan_fingerprint", "tc3_sha256")) \
                or doc["state"] not in ("draft", "approved", "stale") or doc["selected"] not in TEMPLATES \
                or not all(isinstance(doc[k], str) and doc[k].strip() for k in ("title", "headline", "updated_at")) \
                or not isinstance(doc["title_options"], list) \
                or not all(isinstance(t, str) for t in doc["title_options"]) \
                or (doc["approved_at"] is not None and not isinstance(doc["approved_at"], str)) \
                or (doc["state"] == "approved" and not doc["approved_at"]) \
                or not isinstance(doc["thumbnails"], list) or len(doc["thumbnails"]) != 3:
            raise PackageError("invalid package record")
        seen = set()
        for t in doc["thumbnails"]:
            if t["template"] not in TEMPLATES or t["template"] in seen \
                    or type(t["template_version"]) is not int or t["template_version"] < 1 \
                    or not isinstance(t["asset_ids"], list) or len(t["asset_ids"]) > 1 \
                    or not all(SHA.fullmatch(a) for a in t["asset_ids"]):
                raise PackageError("invalid thumbnail entry")
            seen.add(t["template"])
            if t["file"] is None:
                if t["sha256"] is not None or t["key"] is not None:
                    raise PackageError("invalid empty thumbnail")
            else:
                match = FILE_NAME.fullmatch(t["file"])
                if match is None or match[1] != t["template"] or match[2] != t["key"] \
                        or not SHA.fullmatch(t["sha256"]):
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
        doc = validate(json.loads(path.read_text(encoding="utf-8")))
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
