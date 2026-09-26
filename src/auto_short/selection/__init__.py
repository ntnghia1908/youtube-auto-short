"""Selection stage (CP5): AI picks non-overlapping clips among CP4 candidates."""

from .logic import SelectionError
from .stage import SelectionResult, run_selection

__all__ = ["SelectionError", "SelectionResult", "run_selection"]
