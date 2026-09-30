"""End-to-end pipeline: ingest -> transcript -> analysis -> selection -> titling -> render.

Canonical contract: docs/decisions/CP8-pipeline-contract.md. This module only orchestrates the
existing ``run_<stage>`` functions; skip/stale/resume stay with each stage (CP2 D6).
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import khaithi
from .analysis import AnalysisError, run_analysis
from .config import Config
from .ingest import IngestError, run_ingest
from .render import RenderError, run_render
from .selection import SelectionError, run_selection
from .selection.client import resolve_host
from .titling import TitlingError, run_titling
from .transcript import TranscriptError, run_transcript
from .workspace import WorkspaceError, validate_episode_id

log = logging.getLogger("auto_short")

# P1 order (CP1 §8) without ``review``: not implemented before CP9, titles are auto-approved.
PIPELINE_STAGES = ("ingest", "transcript", "analysis", "selection", "titling", "render")

STAGE_ERRORS: tuple[type[Exception], ...] = (IngestError, TranscriptError, AnalysisError, SelectionError,
                                             TitlingError, RenderError)

PREFLIGHT = "preflight"
PREFLIGHT_TIMEOUT = 10.0


class PipelineError(Exception):
    """Invalid pipeline arguments."""


class PreflightError(Exception):
    """Ollama is unreachable or a configured model is missing; no stage ran."""


class OllamaUnavailable(PreflightError):
    """FIX-ollama-wait O1: Ollama cannot be reached (connection error / timeout / HTTP 502-504), as opposed to a
    missing model or bad response (plain :class:`PreflightError`). The web waits for the GPU on this."""


@dataclass(frozen=True)
class StageRun:
    stage: str
    ran: bool  # False when skipped as up to date
    seconds: float
    result: Any  # the stage's ``…Result``


@dataclass
class PipelineResult:
    episode_id: str | None = None
    stages: list[StageRun] = field(default_factory=list)
    failed_stage: str | None = None
    error: Exception | None = None
    rendered: int | None = None  # from render_manifest.json ``stats`` after render
    clips: int | None = None
    output_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class PipelineInterrupted(KeyboardInterrupt):
    """Ctrl-C during ``stage``; the stage already recorded ``failed`` / ``interrupted`` (CP2 run_stage)."""

    def __init__(self, stage: str, result: PipelineResult):
        super().__init__(stage)
        self.stage = stage
        self.result = result


@dataclass(frozen=True)
class StageDeps:
    """Injectable stage dependencies (tests); None = the stage's default."""

    downloader: Callable | None = None  # ingest
    fetcher: Any = None  # transcript
    backend: Any = None  # transcript
    analyzer: Any = None  # analysis
    selection_client: Any = None  # selection
    titling_client: Any = None  # titling
    render_runner: Callable | None = None  # render
    runners: Mapping[str, Callable] = field(default_factory=dict)  # replace a run_<stage> function


# --- E8 Ollama preflight --------------------------------------------------------------------

Opener = Callable[..., Any]


def _tags(host: str, opener: Opener, timeout: float) -> list[str]:
    url = f"{host}/api/tags"
    try:
        with opener(urllib.request.Request(url, method="GET"), timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise (OllamaUnavailable if exc.code in (502, 503, 504) else PreflightError)(
            f"HTTP {exc.code} from {url}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise OllamaUnavailable(f"timeout after {timeout:g} s calling {url}") from exc
    except urllib.error.URLError as exc:
        raise OllamaUnavailable(f"cannot reach Ollama at {host}: {exc.reason}") from exc
    except OSError as exc:
        raise OllamaUnavailable(f"error calling {url}: {exc}") from exc
    try:
        models = json.loads(raw)["models"]
        names = []
        for m in models:
            names += [n for n in (m.get("name"), m.get("model")) if isinstance(n, str)]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PreflightError(f"invalid response from {url}: {raw[:200]!r}") from exc
    return names


def _has_model(model: str, names: list[str]) -> bool:
    return model in names or (":" not in model and f"{model}:latest" in names)


def ollama_preflight(config: Config, *, opener: Opener | None = None,
                     timeout: float = PREFLIGHT_TIMEOUT) -> None:
    """E8: ``GET <host>/api/tags`` for the ``[selection]`` and ``[titling]`` hosts (env ``OLLAMA_HOST``
    overrides, like the stages) and check both models are listed. Raises :class:`PreflightError`."""
    open_ = opener or urllib.request.urlopen
    needed: dict[str, list[tuple[str, str]]] = {}
    for section, cfg in (("selection", config.selection), ("titling", config.titling)):
        needed.setdefault(resolve_host(cfg.ollama_host), []).append((section, cfg.model))
    for host, models in needed.items():
        names = _tags(host, open_, timeout)
        for section, model in models:
            if not _has_model(model, names):
                raise PreflightError(f"model {model!r} ([{section}] model) is not available at {host} "
                                     f"(ollama pull {model})")
        log.info("preflight: ollama %s ok (%s)", host, ", ".join(sorted({m for _, m in models})))


# --- E2-E5 run ------------------------------------------------------------------------------

_DEFAULT_RUNNERS: dict[str, Callable] = {
    "ingest": run_ingest, "transcript": run_transcript, "analysis": run_analysis,
    "selection": run_selection, "titling": run_titling, "render": run_render,
}


def _render_counts(result: PipelineResult, render_result: Any) -> None:
    path = Path(render_result.path)
    result.output_dir = path.parent
    rendered, clips = getattr(render_result, "rendered", None), getattr(render_result, "clips", None)
    if rendered is None or clips is None:
        try:
            stats = json.loads(path.read_text(encoding="utf-8"))["stats"]
            rendered, clips = stats["rendered"], stats["clips"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    result.rendered, result.clips = rendered, clips


def _check_stages(stages: Sequence[str] | None) -> tuple[str, ...]:
    if stages is None:
        return PIPELINE_STAGES
    if isinstance(stages, str):
        stages = [stages]
    stages = tuple(stages)
    unknown = [s for s in stages if s not in PIPELINE_STAGES]
    if unknown:
        raise PipelineError(f"unknown stage {unknown[0]!r} (one of: {', '.join(PIPELINE_STAGES)})")
    ordered = tuple(s for s in PIPELINE_STAGES if s in stages)
    if not stages or ordered != stages:
        raise PipelineError(f"stages must be a non-empty subset of {', '.join(PIPELINE_STAGES)} in that order, "
                            f"without duplicates (got {', '.join(stages) or 'none'})")
    return ordered


def run_pipeline(
    target: str,
    config: Config,
    *,
    episode_id: str | None = None,
    subtitle: Path | None = None,
    speaker: str | None = None,
    series: str | None = None,
    episode: str | None = None,
    force_from: str | None = None,
    preflight: Callable[[Config], None] | None = ollama_preflight,
    deps: StageDeps | None = None,
    on_stage: Callable[[StageRun], None] | None = None,
    stages: Sequence[str] | None = None,
) -> PipelineResult:
    """Run the stages in order (E2). The stage ``force_from`` runs with ``force=True``; later stages re-run
    because they are stale (E5). Stops at the first stage error: the returned result has ``failed_stage`` and
    ``error`` (E4). ``preflight`` (None = skip) runs before the first stage and raises :class:`PreflightError`
    (E8). Ctrl-C raises :class:`PipelineInterrupted` naming the running stage. ``on_stage`` is called after each
    stage that finished. ``stages`` (None = all six; CP8.10 web lanes): a non-empty subset of
    :data:`PIPELINE_STAGES` in pipeline order; without ``ingest`` the ``episode_id`` is required (the stages read
    the existing workspace). Each stage still skips when up to date (CP2 D6)."""
    if force_from is not None and force_from not in PIPELINE_STAGES:
        raise PipelineError(f"unknown stage {force_from!r} (one of: {', '.join(PIPELINE_STAGES)})")
    run_stages = _check_stages(stages)
    if "ingest" not in run_stages and episode_id is None:
        raise PipelineError("episode_id is required when the ingest stage is not run")
    if episode_id is not None:  # CP8.9 K1: a broken khaithi.json stops the run before any stage
        try:
            khaithi.read(Path(config.workspace.dir) / validate_episode_id(episode_id),
                         config.khaithi.max_minutes_limit)
        except khaithi.KhaithiError as exc:
            raise PipelineError(str(exc)) from exc
        except WorkspaceError:
            pass  # invalid id: reported by ingest
    deps = deps or StageDeps()
    result = PipelineResult(episode_id=episode_id)

    current = PREFLIGHT
    try:
        if preflight is not None:
            preflight(config)
        if "render" in run_stages:
            log.info("run: stage review is not run; AI titles are auto-approved ([render] title_source = %r)",
                     config.render.title_source)
        for stage in run_stages:
            current = stage
            runner = deps.runners.get(stage) or _DEFAULT_RUNNERS[stage]
            force = stage == force_from
            t0 = time.monotonic()
            try:
                if stage == "ingest":
                    kw = {"downloader": deps.downloader} if deps.downloader else {}
                    res = runner(target, config, episode_id=episode_id, force=force, **kw)
                    result.episode_id = res.episode_id
                else:
                    eid = result.episode_id
                    if stage == "transcript":
                        res = runner(eid, config, subtitle=subtitle, force=force, fetcher=deps.fetcher,
                                     backend=deps.backend)
                    elif stage == "analysis":
                        res = runner(eid, config, force=force, analyzer=deps.analyzer)
                    elif stage == "selection":
                        res = runner(eid, config, force=force, client=deps.selection_client)
                    elif stage == "titling":
                        res = runner(eid, config, force=force, speaker=speaker, series=series, episode=episode,
                                     client=deps.titling_client)
                    else:
                        res = runner(eid, config, force=force, run=deps.render_runner)
            except STAGE_ERRORS as exc:
                result.failed_stage, result.error = stage, exc
                return result
            run = StageRun(stage, bool(res.ran), round(time.monotonic() - t0, 3), res)
            result.stages.append(run)
            if stage == "render":
                _render_counts(result, res)
            if on_stage is not None:
                on_stage(run)
    except PipelineInterrupted:
        raise
    except KeyboardInterrupt as exc:
        raise PipelineInterrupted(current, result) from exc
    return result
