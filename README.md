# YouTube Auto Short

Greenfield project for automatically turning Vietnamese long-form lecture videos into YouTube Shorts.

## Current stage

**CP3 — Transcript acquisition & normalization.** Implemented stages:

- `ingest`: a YouTube URL or a local video enters a per-episode workspace and gets a `metadata.json` and a resumable `manifest.json`. Conventions: `docs/decisions/CP2-workspace-contract.md`.
- `transcript`: a Vietnamese `transcript.json` with segment/word timestamps, from the YouTube caption, else a local subtitle, else `faster-whisper`. Contract: `docs/decisions/CP3-transcript-contract.md`.

The project adopts the universal parts of AI Development Framework v4 from `ntnghia1908/dang-vu-spring`, while keeping this repository independent.

## What the project will eventually do

```text
Vietnamese source video
        ↓
transcription + timestamps
        ↓
content / shot analysis
        ↓
AI selects coherent Short segments
        ↓
AI generates title/panel text
        ↓
9:16 composition + subtitles
        ↓
multiple Short outputs
```

Only the first two steps (ingest, transcription) are implemented; the rest of the pipeline is planned.

## Setup

Requirements: conda (Miniconda) for a dedicated Python 3.12 env (never the `base` env) and `ffmpeg`/`ffprobe` on `PATH`.
YouTube downloads may also need a JavaScript runtime on `PATH` (default config uses `node`).

```bash
conda create -n auto-short python=3.12
conda activate auto-short
pip install -e ".[dev]"
cp config.example.toml config.toml   # local, gitignored; edit as needed
```

Run tests (no network needed):

```bash
pytest -q
```

## Usage

```bash
# Local file: referenced in place (not copied); episode id = <slug>-<sha256[:12]>
auto-short ingest input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4

# YouTube URL: downloaded to work/<video_id>/source.mp4 (best quality); episode id = video id
auto-short ingest https://youtu.be/rbjfCfFq3Dk

# Options: --episode-id ID, --force (re-run even if up to date), --config PATH
auto-short status <episode_id>
```

Transcript (after ingest):

```bash
# Tries YouTube caption (vi manual > vi-orig auto > vi auto) -> local subtitle -> faster-whisper;
# the first transcript that passes validation wins, later providers are not run.
auto-short transcript <episode_id>

# Local subtitle: --subtitle wins over a sidecar next to the local video
# (<stem>.vi.srt|.vi.vtt|.vi.json3|.srt|.vtt|.json3). Options: --force, --config PATH
auto-short transcript <episode_id> --subtitle path/to/lecture.srt
```

Output: `work/<episode_id>/transcript.json` (plus `transcript/youtube.<track>.json3` for YouTube captions).
The Whisper fallback (`large-v3-turbo`, CPU `int8` by default, see `[transcript.whisper]` in
`config.example.toml`) downloads its model (~1.6 GB) from Hugging Face into `models/` on first use.

Analysis (after transcript):

```bash
# ffmpeg scene + silence detection, then deterministic clip candidates (30-180 s after
# shortening silences to 1.0 s); intro/outro music and the intro announcement are excluded.
auto-short analysis <episode_id>   # options: --force, --config PATH
```

Output: `work/<episode_id>/shots.json`, `silences.json` and `candidates.json` (schemas and rules:
`docs/decisions/CP4-analysis-contract.md`; parameters in `[analysis]` of `config.example.toml`).
Detection takes about 90 s for a 1-hour video; changing any `[analysis]` key re-runs the stage.

`python -m auto_short ...` works the same. Re-running `ingest` skips when the source and the
relevant config are unchanged. Artifacts go to `work/<episode_id>/` (`manifest.json`, `metadata.json`).

## Reference project

`youtube-vietnamese-dubber` is used only to study existing patterns for media processing, transcription, Ollama interaction and FFmpeg rendering. It is not a dependency or authority for this repository.

## Framework bootstrap

Start with:

1. `AGENTS.md`
2. `docs/ai/project-profile.md`
3. `docs/workflow/current-state.md`
4. `docs/ai/workflow.md`
5. `docs/ai/execution-profiles.md`
6. task contract when working on an S1/S2 task

Check framework structure with:

```bash
node scripts/framework-check.mjs
```

## Repository policy

The repository is the source of truth. Human Lead decisions define boundaries; agents execute inside approved boundaries. See `FRAMEWORK_ADOPTION.md` for the adoption boundary.
