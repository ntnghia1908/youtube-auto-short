"""Analysis stage (CP4): shots, silences and deterministic clip candidates."""

from .detect import AnalysisError
from .stage import AnalysisResult, run_analysis

__all__ = ["AnalysisError", "AnalysisResult", "run_analysis"]
