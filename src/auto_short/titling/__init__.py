"""Titling stage (CP6): deterministic header + AI title/hook per selected clip."""

from .logic import TitlingError
from .stage import TitlingResult, run_titling

__all__ = ["TitlingError", "TitlingResult", "run_titling"]
