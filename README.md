# YouTube Auto Short

Greenfield project for automatically turning Vietnamese long-form lecture videos into YouTube Shorts.

## Current stage

**CP8 — End-to-end Auto Short MVP.** One command, `auto-short run <youtube-url|path>`, runs every stage below in order and resumes after an error or Ctrl-C (contract: `docs/decisions/CP8-pipeline-contract.md`). Implemented stages:

- `ingest`: a YouTube URL or a local video enters a per-episode workspace and gets a `metadata.json` and a resumable `manifest.json`. Conventions: `docs/decisions/CP2-workspace-contract.md`.
- `transcript`: a Vietnamese `transcript.json` with segment/word timestamps, from the YouTube caption, else a local subtitle, else `faster-whisper`. Contract: `docs/decisions/CP3-transcript-contract.md`.
- `analysis`: shot/silence detection and deterministic clip candidates (`candidates.json`). Contract: `docs/decisions/CP4-analysis-contract.md`.
- `selection`: a local Ollama model picks up to 25 non-overlapping, self-contained clips among the candidates (`clips.json` + `selection_log.json`). Contract: `docs/decisions/CP5-selection-contract.md`.
- `titling`: a deterministic header and an AI title/hook per clip (`titles.json` + `titling_log.json`). Contract: `docs/decisions/CP6-titling-contract.md`.
- `render`: each titled clip becomes a 1080x1920 Short (black background, yellow header/title panels, centre-cropped source video, silences shortened) in `output/<episode_id>/shorts/` + `render_manifest.json`. Contract: `docs/decisions/CP7-render-contract.md`.

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

Ingest, transcription, analysis, AI clip selection, title generation and composition/render are implemented (subtitles are off, CP1 §7) and chained by `auto-short run` (CP8); human review and batch processing (CP9) are planned.

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

Whole pipeline in one command (ingest -> transcript -> analysis -> selection -> titling -> render):

```bash
auto-short run https://youtu.be/rbjfCfFq3Dk
auto-short run input/lecture.mp4 --series "Thập Thiện Nghiệp Đạo Kinh" --episode 9   # local video
# Options: --episode-id ID (ingest), --subtitle PATH (transcript), --speaker/--series/--episode (titling),
#          --force-from STAGE (re-run STAGE even if up to date; later stages follow), --no-preflight, --config PATH
```

`run` first checks that Ollama answers and has the `[selection]` and `[titling]` models (`--no-preflight` skips
this, e.g. when those stages are already done). stdout gets the same line per stage as the single-stage
commands below, then `<episode_id>\tdone (<rendered>/<clips> Shorts)\t<output dir>`; stderr gets the stage logs and
a timing table. Re-running the same command after an error or Ctrl-C (exit 1 / 130) skips the stages that are up
to date and continues from the first one that is not; re-running when everything is done skips all six stages
(well under a second). The review stage is not run yet: AI titles are auto-approved. Rules:
`docs/decisions/CP8-pipeline-contract.md`.

Single stages:

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

AI clip selection (after analysis; needs Ollama, default `http://127.0.0.1:11437`, env `OLLAMA_HOST` overrides):

```bash
# One Ollama call per continuous content window (between hard breaks); the model proposes unit
# ranges that each present one complete idea; code keeps only existing candidates, then picks
# up to 25 non-overlapping clips (score >= 7, complete start and end). Pure connectors at the very
# start of a clip ("cho nên", "thế là", ...) are cut using word timing (head cut).
# Default model: qwen3:30b with thinking (~8 min for a 1-hour video).
auto-short selection <episode_id>   # options: --force, --config PATH
```

Output: `work/<episode_id>/clips.json` (selected clips, referencing `candidates.json` by `candidate_id`) and
`selection_log.json` (every prompt, raw response, the status of each proposal and each head cut). Rules and schemas:
`docs/decisions/CP5-selection-contract.md`; parameters in `[selection]` of `config.example.toml`. Changing
`ollama_host`/`timeout` does not re-run the stage; changing the model, `think`, options or limits does.

AI title / hook (after selection; same Ollama host rules, section `[titling]`):

```bash
# Header (no AI): speaker / series / episode from --speaker/--series/--episode > [titling.header]
# > regex title_pattern on the video title; default lines "HT.Tịnh Không" / "<series> (tập <n>)".
# Then one Ollama call per clip: 3 title options (<= 60 chars) each quoting evidence from the clip
# text; code keeps the first valid one. Default: qwen3:14b, thinking off, prompt v2 (~35 s for 13 clips).
auto-short titling <episode_id>   # options: --force, --config PATH, --speaker S, --series S, --episode N
```

Output: `work/<episode_id>/titles.json` (header + one title per clip, `untitled` when no option passed
validation) and `titling_log.json` (prompts, raw responses, every option with its reject reason). Rules and
schemas: `docs/decisions/CP6-titling-contract.md`; parameters in `[titling]` of `config.example.toml`. A local
video without a matching title needs `--series`/`--episode` (or `[titling.header]` values).

Render the Shorts (after titling; system `ffmpeg`, no AI):

```bash
# One ffmpeg run per titled clip: the clip's source range minus the silence trims of its candidate,
# centre-cropped to 1080x1210, header + title panels drawn with the bundled Be Vietnam Pro font.
# H.264 crf 22 / AAC 192k; ~5 min for 13 clips (826 s of Shorts) on a 48-thread CPU.
auto-short render <episode_id>    # options: --force, --config PATH
```

Output: `output/<episode_id>/shorts/<clip_id>.mp4` and `output/<episode_id>/render_manifest.json` (layout,
display lines and font size per clip, segments, sha256 of every input and file). Titles come straight from
`titles.json` (`[render] title_source = "titles"`, i.e. AI titles are auto-approved until the review stage exists);
`untitled` clips are skipped with a warning. A long title first makes the title panel taller (3 lines), and only
shrinks the font when that is not enough. Rules and schema: `docs/decisions/CP7-render-contract.md`; parameters in
`[render]` of `config.example.toml` (`output_dir` and `threads` do not re-run the stage; any other key does).

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
