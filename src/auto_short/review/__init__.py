"""Review (CP8.2, partial: manual titles only): ``review.json`` title overrides shared by the CLI and the web.

Canonical contract: docs/decisions/CP8.2-title-override-contract.md.
"""

from .logic import AI, ALTERNATIVE, MANUAL, REVIEW_NAME, ReviewError
from .titles import (TitlePreview, list_titles, load_overrides, preview_title, reset_title, set_alternative,
                     set_title)

__all__ = ["AI", "ALTERNATIVE", "MANUAL", "REVIEW_NAME", "ReviewError", "TitlePreview", "list_titles",
           "load_overrides", "preview_title", "reset_title", "set_alternative", "set_title"]
