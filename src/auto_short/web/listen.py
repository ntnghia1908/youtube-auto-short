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
from . import episodes as ep


def playlist_listen(config: Config, doc: dict, favorites: Iterable[Item]) -> dict:
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
                items.append({"kind": kind, "episode_id": eid, "base_episode_id": base,
                              "ep_index": entry.get("index"), "ep_title": entry.get("title"),
                              "clip_id": clip, "title": view["title"]["text"],
                              "duration": view["duration"], "video_url": view["video_url"],
                              "audio_url": f"/api/watch/audio/{eid}/{clip}",
                              "fav": {"playlist_id": pid, "episode_id": eid, "clip": clip,
                                      "favorite": (eid, clip) in hearted}})
    return {"playlist_id": pid, "title": doc.get("title") or pid, "items": items}
