"""Đọc Kinh: the third application of the host repository.

Canonical contract: docs/decisions/SR1-sutra-reader-contract.md (S2 text format, S3 reading structure,
S4 storage ``<workspace dir>/_sutras/<slug>/``, S6 routes). SR1.1 implements ``markup``, ``store`` and ``web``.
"""

from .markup import MarkupError, Sutra, parse
from .store import SutraConflict, SutraError, SutraNotFound, SutraStore

__all__ = ["MarkupError", "Sutra", "SutraConflict", "SutraError", "SutraNotFound", "SutraStore", "parse"]
