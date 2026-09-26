"""Typed runtime configuration loaded from TOML (stdlib ``tomllib``)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILE = "config.toml"


class ConfigError(Exception):
    """Raised when a config file is missing or invalid."""


@dataclass(frozen=True)
class WorkspaceConfig:
    dir: Path = Path("work")


@dataclass(frozen=True)
class IngestConfig:
    youtube_format: str = "bv*+ba/b"
    js_runtimes: tuple[str, ...] = ("node",)


@dataclass(frozen=True)
class Config:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _str(section: dict, key: str, default: str, where: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value


def from_dict(data: dict) -> Config:
    ws = _section(data, "workspace")
    ing = _section(data, "ingest")
    defaults = IngestConfig()

    runtimes = ing.get("js_runtimes", list(defaults.js_runtimes))
    if not isinstance(runtimes, list) or not all(isinstance(x, str) and x for x in runtimes):
        raise ConfigError("ingest.js_runtimes must be a list of strings")

    return Config(
        workspace=WorkspaceConfig(dir=Path(_str(ws, "dir", "work", "workspace"))),
        ingest=IngestConfig(
            youtube_format=_str(ing, "youtube_format", defaults.youtube_format, "ingest"),
            js_runtimes=tuple(runtimes),
        ),
    )


def load(path: Path | None = None) -> Config:
    """Load config from ``path``; without a path use ./config.toml if present, else defaults."""
    if path is None:
        path = Path(DEFAULT_CONFIG_FILE)
        if not path.is_file():
            return Config()
    elif not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return from_dict(data)
