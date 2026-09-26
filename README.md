# YouTube Auto Short

Greenfield project for automatically turning Vietnamese long-form lecture videos into YouTube Shorts.

## Current stage

**CP0 — Framework v4 + project bootstrap**

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

This pipeline is planned, not implemented in CP0.

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
