"""Review (CP8.2 manual titles; CP8.5 deleted Shorts, "đã đăng", download names, episode delete), shared by the
CLI and the web.

Canonical contracts: docs/decisions/CP8.2-title-override-contract.md (``review.json``),
docs/decisions/CP8.3-web-contract.md (download names, ``publish.json``, episode delete).
"""

from .delete import EpisodeNotFound, delete_episode
from .logic import AI, ALTERNATIVE, MANUAL, REVIEW_NAME, ReviewError
from .names import content_disposition, download_name, episode_label, zip_name
from .publish import PUBLISH_NAME, load_published, publish_status, set_published
from .titles import (TitlePreview, list_titles, load_overrides, preview_title, reject_clip, reset_title,
                     restore_clip, set_alternative, set_title)

__all__ = ["AI", "ALTERNATIVE", "MANUAL", "PUBLISH_NAME", "REVIEW_NAME", "EpisodeNotFound", "ReviewError",
           "TitlePreview", "content_disposition", "delete_episode", "download_name", "episode_label",
           "list_titles", "load_overrides", "load_published", "preview_title", "publish_status", "reject_clip",
           "reset_title", "restore_clip", "set_alternative", "set_published", "set_title", "zip_name"]
