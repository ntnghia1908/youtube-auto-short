"""Ingest stage (CP2): YouTube URL or local video -> work/<episode_id>/metadata.json."""

from .stage import IngestBlocked, IngestError, IngestResult, derived_episode_id, needs_download, run_ingest

__all__ = ["IngestBlocked", "IngestError", "IngestResult", "derived_episode_id", "needs_download", "run_ingest"]
