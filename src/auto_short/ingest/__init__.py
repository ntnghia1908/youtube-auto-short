"""Ingest stage (CP2): YouTube URL or local video -> work/<episode_id>/metadata.json."""

from .stage import IngestError, IngestResult, run_ingest

__all__ = ["IngestError", "IngestResult", "run_ingest"]
