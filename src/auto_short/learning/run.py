"""Chinese Learning orchestrator (CL1 C9, option C): ``subtitle`` -> ``media`` -> ``lesson``.

Own stage order, independent of ``pipeline.py``; each stage goes through the shared
``run_stage`` (CP2 D6) with an explicit ``downstream``. Stops at the first failing stage. The
Ollama preflight runs right before ``lesson``, and only when that stage will actually run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import hashing
from ..config import Config
from ..ingest.source import youtube_video_id
from ..selection.client import ChatClient, OllamaClient, resolve_host
from ..workspace import DONE, StageError, Workspace, WorkspaceError, atomic_write_json, check_up_to_date, \
    run_stage, validate_episode_id
from . import lesson, media, subtitle
from .media import ClipDownloader, ytdlp_clip
from .preflight import LearningPreflightError, learning_preflight
from .prompt import prompt_texts
from .tracks import TrackLister, YtDlpChineseFetcher

log = logging.getLogger("auto_short")

LEARNING_DIR = "_learning"  # namespace of the application in the workspace root (C4)
STAGES = (subtitle.STAGE, media.STAGE, lesson.STAGE)


class LearningError(Exception):
    """``learn`` could not complete; the message is user-facing."""


@dataclass
class LearningResult:
    episode_id: str
    workspace: Path
    stages: list[tuple[str, bool]] = field(default_factory=list)  # (stage, ran)


def learning_root(config: Config) -> Path:
    return config.workspace.dir / LEARNING_DIR


def canonical_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def source_entry(video_id: str) -> dict:
    return {"kind": "youtube", "uri": canonical_url(video_id), "path": None, "sha256": None, "size": None,
            "mtime_ns": None}


def run_learning(
    url: str,
    config: Config,
    *,
    force: bool = False,
    lister: TrackLister | None = None,
    downloader: ClipDownloader | None = None,
    on_stage: Callable[[str, str, bool], None] | None = None,  # (episode_id, stage, ran)
    client: ChatClient | None = None,
    preflight: Callable[[Config], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> LearningResult:
    video_id = youtube_video_id(url)
    if video_id is None:
        raise LearningError(f"unsupported URL (expected a single YouTube video URL): {url}")
    try:
        prompt_texts(config.learning.prompt_version)
    except ValueError as exc:
        raise LearningError(f"learning.prompt_version: {exc}") from exc
    try:
        ws = Workspace(learning_root(config), validate_episode_id(video_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise LearningError(str(exc)) from exc
    if manifest is None:
        manifest = ws.new_manifest(source_entry(video_id))
    ws.dir.mkdir(parents=True, exist_ok=True)

    uri = canonical_url(video_id)
    result = LearningResult(ws.episode_id, ws.dir)

    def run(stage: str, cfg: dict, downstream: tuple[str, ...], action: Callable[[], list[str]],
            cleanup: Callable[[Workspace], None], inputs: list[dict] | None = None,
            after_failure: Callable[[], None] | None = None) -> None:
        try:
            ran = run_stage(ws, manifest, stage, inputs=inputs or [], cfg_hash=hashing.config_hash(cfg),
                            force=force, action=action, downstream=downstream)
        except StageError as exc:
            cleanup(ws)
            if after_failure is not None:
                after_failure()
            raise LearningError(str(exc)) from exc
        except KeyboardInterrupt:
            cleanup(ws)
            raise
        result.stages.append((stage, ran))
        if on_stage is not None:
            on_stage(ws.episode_id, stage, ran)

    run(subtitle.STAGE, subtitle.used_config(config), subtitle.DOWNSTREAM,
        lambda: subtitle.produce(ws, uri, config, lister or YtDlpChineseFetcher(config.ingest.js_runtimes)),
        subtitle.remove_outputs)

    if (manifest["stages"].get(subtitle.STAGE) or {}).get("status") != DONE:  # defensive: never without subtitle
        raise LearningError(f"{subtitle.STAGE} is not done; {media.STAGE} not run")
    run(media.STAGE, media.used_config(config), media.DOWNSTREAM,
        lambda: media.produce(ws, uri, config, downloader or ytdlp_clip),
        media.remove_outputs)

    if (manifest["stages"].get(media.STAGE) or {}).get("status") != DONE:  # defensive
        raise LearningError(f"{media.STAGE} is not done; {lesson.STAGE} not run")
    lesson_inputs = lesson.inputs(ws)
    lesson_cfg = lesson.used_config(config)
    if force or check_up_to_date(ws, manifest, lesson.STAGE, lesson_inputs,
                                 hashing.config_hash(lesson_cfg)) is not None:
        try:
            (preflight or learning_preflight)(config)
        except LearningPreflightError as exc:
            raise LearningError(str(exc)) from exc
    chat = client or OllamaClient(resolve_host(config.learning.ollama_host), timeout=config.learning.timeout)
    failure: dict = {}

    def keep_failure_log() -> None:
        # After record_failure: the log of the failed attempts survives, outside the failed entry's artifacts.
        if failure.get("log") is not None:
            atomic_write_json(ws.dir / lesson.LOG_NAME, failure["log"])

    run(lesson.STAGE, lesson_cfg, lesson.DOWNSTREAM,
        lambda: lesson.produce(ws, config, chat, sleep, failure),
        lesson.remove_outputs, lesson_inputs, keep_failure_log)
    return result
