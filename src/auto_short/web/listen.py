"""Read-only listening queue: manifest order within each numbered playlist entry.

Only local JSON is read. In particular a released Short keeps the same /files URL
as the episode page; resolving or fetching its bytes belongs to that existing route.
"""

from collections.abc import Iterable
from pathlib import Path

from ..compilation import Item
from ..config import Config
from ..khaithi import KhaithiError, episode_id_for
from ..review import REVIEW_NAME, ReviewError
from ..review.logic import read_review
from ..review.names import short_code
from . import episodes as ep


def clip_metadata(config: Config, episode_id: str, manifest: dict | None = None) -> dict[str, dict]:
    """Same label, manifest positions and total as ep._names/copy_prefixes, including skipped clips."""
    manifest = manifest if manifest is not None else ep.render_manifest(config, episode_id)
    if manifest is None:
        return {}
    fields = ep.kind_fields(config, episode_id)
    label, shorts = ep.label(config, episode_id, fields), manifest["shorts"]
    return {short["clip_id"]: {
        "code": short_code(label, n, len(shorts), khaithi=fields["kind"] == "khaithi"),
        "ep_label": label, "number": n, "total": len(shorts), "kind": fields["kind"],
        "episode_id": episode_id, "base_episode_id": fields["base_episode_id"] or episode_id,
        "title": short.get("title"), "duration": short.get("duration"),
    } for n, short in enumerate(shorts, 1) if isinstance(short, dict)
        and isinstance(short.get("clip_id"), str) and ep.valid_clip_id(short["clip_id"])
        and short.get("status") == "rendered"}


def playlist_listen(config: Config, doc: dict, favorites: Iterable[Item], favorites_only: bool = False) -> dict:
    """Build a queue without loading titles, publication, jobs or remote storage."""
    pid = doc["playlist_id"]
    hearted = {(item.episode_id, item.clip) for item in favorites}
    items = []
    for entry in sorted(doc["entries"], key=lambda e: e.get("index", 0)):
        base = entry.get("video_id")
        if not entry.get("available") or not isinstance(base, str) or not ep.valid_episode_id(base):
            continue
        # Same association as PlaylistStore._khaithi_id, without its full status view.
        episodes = [("short", base)]
        try:
            episodes.append(("khaithi", episode_id_for(base)))
        except KhaithiError:
            pass
        for kind, eid in episodes:
            workspace = Path(config.workspace.dir) / eid
            if not workspace.is_dir():
                continue
            manifest = ep.render_manifest(config, eid)
            if manifest is None:
                continue
            metadata = clip_metadata(config, eid, manifest)
            try:
                review = read_review(workspace / REVIEW_NAME, eid)
            except ReviewError:
                review = {}
            rejected = {(r["clip_id"], r["candidate_id"]) for r in review.get("rejected", [])}
            for short in manifest["shorts"]:
                if not isinstance(short, dict) or short.get("status") != "rendered" \
                        or (short.get("clip_id"), short.get("candidate_id")) in rejected:
                    continue
                view = ep._short_view(eid, short, None)
                if view is None:
                    continue
                clip = view["clip_id"]
                if favorites_only and (eid, clip) not in hearted:
                    continue
                items.append({**metadata[clip], "kind": kind, "episode_id": eid, "base_episode_id": base,
                              "ep_index": entry.get("index"), "ep_title": entry.get("title"),
                              "clip_id": clip, "title": view["title"]["text"],
                              "duration": view["duration"], "video_url": view["video_url"],
                              "fav": {"playlist_id": pid, "episode_id": eid, "clip": clip,
                                      "favorite": (eid, clip) in hearted}})
    return {"playlist_id": pid, "title": doc.get("title") or pid, "items": items}
