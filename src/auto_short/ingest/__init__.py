"""Ingest stage (CP2): YouTube URL or local video -> work/<episode_id>/metadata.json."""

from .stage import IngestError, IngestResult, derived_episode_id, run_ingest

__all__ = ["IngestError", "IngestResult", "derived_episode_id", "run_ingest"]
