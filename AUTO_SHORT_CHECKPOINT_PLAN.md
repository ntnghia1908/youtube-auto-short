# YouTube Auto Short — Checkpoint Plan

## 1. Purpose

`youtube-auto-short` is an independent project for automatically converting Vietnamese Dharma lecture videos into YouTube Shorts.

The system should reduce manual editing work by automating:

- identifying suitable short-form segments;
- selecting coherent clip boundaries;
- generating short titles/hooks;
- composing the video into the target Short format;
- rendering the final videos;
- supporting batch processing and resumable execution.

The source video is already Vietnamese. Therefore this project does **not** contain translation, text-to-speech dubbing, voice replacement, or language conversion.

---

## 2. Reference Projects

### 2.1 Framework source

Development follows Framework v4 adopted from `ntnghia1908/dang-vu-spring`.

Framework v4 is the authoritative development process for this project. It defines S0/S1/S2 classification, task contracts, decision gates, execution profiles, implementation workflow, verification, review, and READY state.

The project must not bypass the Framework v4 process.

### 2.2 Engineering reference

`ntnghia1908/youtube-vietnamese-dubber` is an engineering reference only.

It is **not** a dependency, shared runtime library, fork target, or source of project-specific rules. The Auto Short project remains independent.

Lessons intentionally reused from the dubbing project:

- artifact-oriented pipeline stages;
- resumable execution;
- cache and dependency-aware invalidation;
- provenance and hashes;
- validation of AI output;
- bounded batch retry/failure isolation;
- human review at AI-sensitive boundaries;
- measurement of local AI/GPU performance.

Translation, glossary, TTS, dubbing, and voice replacement are explicitly out of scope.

---

# 3. Core Architecture Principles

## 3.1 Artifact-first pipeline

Do not build `video -> AI -> final.mp4` as one opaque operation.

Use inspectable intermediate artifacts:

`source -> metadata.json -> transcript.json -> shots.json -> candidates.json -> clips.json -> titles.json -> render manifest -> final Shorts`

Every major stage should produce stable output that can be inspected, tested, resumed, and reused.

## 3.2 Resumability is a requirement

A completed stage should not rerun unnecessarily. If transcript already exists, do not run transcript acquisition again unless its inputs/configuration make it stale. The same rule applies to clip selection, title generation, and rendering.

## 3.3 Dependency-aware invalidation

Artifacts should retain enough provenance to determine when downstream artifacts are stale.

Example:

`transcript changed -> clip selection may be stale -> titles may be stale -> rendering is stale`

Unrelated stages should not be recomputed.

## 3.4 Provenance

Important artifacts should identify their source relationship. For example, a clip should retain source timestamps, transcript segment IDs, selection model, and relevant source hashes.

## 3.5 AI output validation

LLM output must be validated before becoming a trusted artifact. Validate JSON/schema, required fields, transcript references, timestamps, duplicates, duration constraints, and unsupported values.

## 3.6 Failure isolation

A failure in one AI batch should not invalidate the entire video. Retry should be bounded; repeated failure should become an explicit recorded failure rather than silent corruption.

## 3.7 Human review

AI-generated clip candidates and titles must remain reviewable. Automatic approval may exist only as an explicit project decision, not as an implicit behavior.

---

# 4. Checkpoint Roadmap

## CP0 — Framework Bootstrap + Pilot

**Goal:** Bootstrap Framework v4 and prove the framework can operate correctly in the new repository.

Scope:
- Framework Core;
- Project Layer;
- Claude Code adapter;
- framework checker;
- project profile;
- execution profile;
- current state;
- adoption record;
- S0 pilot;
- S1 low-risk pilot.

Out of scope: Whisper, Ollama, FFmpeg, video processing, AI clip selection.

**Gate:** CP0 must reach READY before CP1.

---

## CP1 — Product Contract + Architecture Baseline

**Change class:** S2.

Define and approve:
- input contract;
- output contract;
- Short duration policy;
- 9:16 composition;
- clip selection boundaries;
- title/header structure;
- yellow-panel layout;
- subtitle policy;
- artifact model;
- pipeline boundaries;
- execution profile;
- dependency policy;
- local GPU/Ollama assumptions.

Do not implement the complete pipeline in CP1. Architecture and dependency decisions go through the Framework v4 decision gate.

**Gate:** HUMAN LEAD approves the architecture baseline.

---

## CP2 — Media Input + Artifact Workspace

**Goal:** Create the foundation for reliable pipeline execution.

Scope:
- input video handling;
- project/episode workspace;
- metadata artifact;
- artifact naming;
- manifest;
- hashing/provenance foundation;
- resumability;
- stage status;
- basic CLI pipeline skeleton.

This explicitly applies the artifact-first and resumability lessons from `youtube-vietnamese-dubber`.

**Success:** A video can enter a workspace and produce stable metadata artifacts without AI processing.

---

## CP3 — Transcript Acquisition & Normalization

**Goal:** Produce a reliable Vietnamese timestamped transcript while avoiding unnecessary local transcription.

### Acquisition priority

The pipeline MUST use this order:

`1. YouTube transcript/captions -> 2. local subtitle source if available -> 3. faster-whisper fallback`

The system must **not run Whisper before checking whether an acceptable YouTube transcript is available**.

### YouTube transcript acceptance

Presence alone is insufficient. A candidate transcript must be validated for:

- usable timestamps;
- non-empty text;
- expected language or compatible language metadata;
- sufficient segment coverage;
- schema correctness;
- suitability for downstream clip selection.

If the YouTube transcript is missing or fails validation, fall back to the next provider.

### Provider abstraction

Conceptually define a transcript acquisition boundary such as:

`TranscriptProvider -> YouTube / Local Subtitle / Whisper`

The exact package/interface is an implementation decision and must not be prematurely fixed in CP2.

### Artifact

`transcript.json` must normalize all providers into the same downstream contract.

It should record at minimum:

- transcript source;
- acquisition method;
- language;
- source/hash information;
- normalized segments;
- timestamps.

Example:

```json
{
  "source": "youtube",
  "language": "vi",
  "method": "youtube_transcript",
  "transcript_sha256": "...",
  "segments": []
}
```

Whisper fallback should record the local model/method used.

### Out of scope

- translation;
- TTS;
- dubbing;
- clip selection;
- title generation.

**Success:** Every accepted transcript, regardless of provider, produces the same normalized `transcript.json` contract.

---

## CP4 — Shot / Segment Analysis

**Goal:** Understand the relationship between transcript boundaries and video boundaries.

Scope:
- shot detection;
- scene/visual boundaries;
- transcript-to-shot mapping;
- candidate segment generation;
- duration constraints;
- boundary validation.

Do not blindly cut at fixed time intervals. Candidate clips should preserve coherent spoken ideas.

**Success:** Candidate segments contain source timestamps, transcript references, duration, and boundary information.

---

## CP5 — AI Clip Selection

**Goal:** Use Ollama to select coherent Short candidates from analyzed source material.

Input:
- transcript;
- timestamps;
- shot information;
- duration constraints;
- approved selection rules.

Output: `clips.json`.

Validate JSON/schema, timestamps, transcript references, duplicate clips, duration, and missing segments.

Changing unrelated rendering configuration must not rerun AI selection.

**Success:** AI-selected clips are reproducible, inspectable, and traceable to source transcript artifacts.

---

## CP6 — AI Title / Hook Generation

**Goal:** Generate the text shown in the Short template.

Two conceptual layers:

### Header

Prefer source metadata, series information, episode information, or explicit configuration. Do not unnecessarily use AI for deterministic metadata.

### Short title / hook

Generate from the selected clip. It must be short, accurate, Vietnamese, and avoid unsupported claims or invented information.

Output: `titles.json`.

Record clip ID, title, model, prompt/version where required, and source hash.

---

## CP7 — Short Composition / Renderer

**Goal:** Render one approved clip into the approved Short format.

Scope:
- 9:16 composition;
- source crop/position;
- upper panel;
- yellow title panel;
- lower panel;
- subtitle;
- typography;
- FFmpeg rendering;
- render manifest.

The exact visual design must come from the approved CP1 product contract. Do not redesign it during implementation.

**Success:** One approved clip renders deterministically into the target Short format.

---

## CP8 — End-to-End Auto Short MVP

Connect:

`input -> metadata -> transcript -> analysis -> clip selection -> title -> render -> Short`

MVP requirements:
- one source video;
- multiple candidate clips;
- AI selection;
- AI title;
- automatic rendering;
- resumability;
- inspectable artifacts.

**Success:** One command can process a source video through the complete pipeline.

---

## CP8.1 — Video Dissolve at Silence Cuts

> Re-plan HUMAN LEAD 2026-09-27: moved forward from CP10.

Video dissolve 0.15 s at every silence-shortening cut, extending segments into the trimmed silence (method and choice: `docs/decisions/CP7-render-contract.md` § Chuyển cảnh). Audio stays a hard cut.

**Success:** Rendered Shorts show a short dissolve instead of a visual jump at each cut; duration and audio unchanged.

---

## CP8.2 — Manual Title + Single-Short Rerender

> Re-plan HUMAN LEAD 2026-09-27: title editing pulled forward from CP9.

Scope:
- per-Short title override (typed by the user, or picked from the AI `alternatives`), stored as an artifact, never calling AI again;
- render uses the override when present;
- rerendering after an edit re-encodes only the edited Short (per-Short render cache); other Shorts are reused byte-identical.

**Success:** Editing one Short's title and rerendering takes one Short's render time and changes only that file.

---

## CP8.3 — Web MVP

> Re-plan HUMAN LEAD 2026-09-27: new scope. Stack FastAPI + uvicorn (dependency proposal in the task contract); reachable on the LAN, so it requires a password.

Scope:
- submit a YouTube URL (or local path); Ollama preflight; run the CP8 pipeline in the background;
- per-stage progress from the episode manifest;
- list episodes and their Shorts; play and download each Short;
- edit a Short's title and rerender that Short only (CP8.2).

**Success:** From a browser on the LAN, one URL becomes reviewed, downloadable Shorts without using the CLI.

---

## CP8.4 — YouTube Upload (skipped)

> HUMAN LEAD 2026-09-27: wanted if feasible; otherwise Shorts are downloaded and uploaded by hand. Amends CP1 §2 when opened.
>
> **Skipped — HUMAN LEAD 2026-09-27.** Not implemented; Shorts stay downloaded and uploaded by hand (CP8.5 workflow). The notes below are kept for reference only; reopening needs a new HUMAN LEAD decision.

Upload a reviewed Short to the user's own channel from the web (YouTube Data API v3, OAuth). Prerequisites and constraints are decided in its task contract: Google Cloud OAuth client created by the user, token storage (security gate), Google API dependency, daily upload quota, and API-uploaded videos from an unaudited project being locked to private.

---

## CP8.5 — Web Review Workflow

> HUMAN LEAD 2026-09-27, after the CP8.3 manual test. Workflow: listen → edit title if needed → download to mobile → upload to YouTube by hand.

Scope:
- download file names `Tập<episode>_S<n>_<title>.mp4` (and inside the zip) instead of the video id;
- delete one Short (excluded from later renders) or a whole episode;
- per-Short "Đã đăng" (published) tick to track what is already on YouTube.

---

## CP8.8 — Per-Playlist Hashtags

> From the backlog, HUMAN LEAD 2026-09-27 (`docs/tasks/CP8.8-playlist-hashtags.md`).

Per bộ kinh hashtag list on the web (full ordered list replacing `#<series>` + `[web] hashtags` for "Copy" title), with preview and reset to default.

---

## CP8.9 — Khai thị Videos (custom length)

> HUMAN LEAD 2026-09-28 (`docs/tasks/CP8.9-khai-thi.md`, amendment A1). Contract: `docs/decisions/CP8.9-khai-thi-contract.md`.

Besides Shorts, the same video yields longer "khai thị" videos (same 9:16 template, one complete teaching each, length in a chosen minute range, default 4–7 min) in a separate episode `<id>.kt` that reuses the Short episode's download and transcript. Web: "Xử lý" makes both; a bộ kinh episode is "Xong" when both are published. CLI: `run --khai-thi`.

---

## CP8.10 — Queue Optimisation

> HUMAN LEAD 2026-09-28 (CP8.9 amendment A2.4; task `docs/tasks/CP8.10-queue-lanes.md`, Q0–Q8). Contract: `docs/decisions/CP8.3-web-contract.md` W5 (lanes `prepare` / `ai` / `render`, `[web] queue_mode`), W7 (`lane`, `waiting`); `docs/decisions/CP8-pipeline-contract.md` E7 (`stages`).

Download the video + captions ahead for jobs waiting in the queue, and let the AI stages (GPU) of one video overlap with the render (CPU) of another, instead of running one whole pipeline at a time.

---

## CP8.11 — Series / Episode Recognition

> HUMAN LEAD 2026-09-28 (`docs/tasks/CP8.11-series-recognition.md`, D1–D7; done before CP8.10, whose id was already taken). Contract: `docs/decisions/CP6-titling-contract.md` G2 (Sửa đổi CP8.11), `docs/decisions/CP8.3-web-contract.md` W7, W10.

The titling header recognizes the series name / episode number from more video title forms (`[titling.header] title_patterns`, first match wins; e.g. `Tập 11/128: Giảng "Thái Thượng Cảm Ứng Thiên" | …`) without flags; episodes already titled are not re-run. Fallback for unusual titles: a "Tên bộ kinh" set on the bộ kinh page (web), used only when no pattern matches.

---

## CP8.12 — Episode Page: Shorts / Khai thị Bar + Collapsible Stages

> HUMAN LEAD 2026-09-28 (`docs/tasks/CP8.12-episode-ui.md`, U1–U4, S1). Contract: `docs/decisions/CP8.3-web-contract.md` W6 (Sửa đổi CP8.12).

On the episode page (desktop and phone): a two-button bar [Shorts | Khai thị] pinned to the top of the screen switches between the Short and khai thị pages of the same video; the 6-step list collapses to one line when the episode is done and opens by itself while running or on error. A deleted target / missing episode shows a message instead of an error page. Amendment A1: the bộ kinh page gets an "Đang xử lý" filter (episodes with a queued / running job).

---

## CP8.13 — Bộ kinh Filter Groups + Loop Button

> HUMAN LEAD 2026-09-28 (`docs/tasks/CP8.13-playlist-groups-loop.md`, G1–G5, S2). Contract: `docs/decisions/CP8.3-web-contract.md` W6, W7, W10 (Sửa đổi CP8.13); `docs/decisions/CP8.9-khai-thi-contract.md` A1.4 (Sửa đổi CP8.13).

The bộ kinh page groups episodes by what is left to do: Chưa xử lý / Đang xử lý / Lỗi / dở dang (failed or unfinished, "Chạy tiếp") / Đang làm (rendered, not every Short posted) / Xong; the home page summary counts đang xử lý / lỗi / dở dang / đang làm. An episode row no longer carries a "Khai thị" link (the khai thị page is reached from the episode page bar). On the episode page each video has a "🔁 Lặp lại" toggle (replay from the start when it ends).

---

## CP8.14 — Short Layout V16: Title Clear of the YouTube Shorts UI

> HUMAN LEAD 2026-09-29 (`docs/tasks/CP8.14-title-layout.md`, L1–L6, phương án V16, S2). Contract: `docs/decisions/CP1-product-contract.md` §4 (Sửa đổi CP8.14); `docs/decisions/CP7-render-contract.md` R4, R5, R11.

The title panel was hidden by the YouTube Shorts UI (channel / description row at the bottom). New layout: a compact header at the top of the frame, a taller full-width video right below it, and the title panel floating over the bottom of the video with its bottom edge fixed at y 1600 (it grows upwards for 3 lines); smaller header / title fonts. New `[render]` defaults, `title_bottom` added, `gap_video_title` removed. Existing episodes keep their Shorts until they run again; then every Short of the episode is rendered once with the new layout.

---

## CP8.15 — Community Post Text From a Short

> HUMAN LEAD 2026-09-29 (`docs/tasks/CP8.15-community-post.md`, P1–P13, S2). Contract: `docs/decisions/CP8.15-community-post-contract.md`; sửa đổi `docs/decisions/CP8.3-web-contract.md` W5, W6, W7.

Every rendered Short (and khai thị video) gets an optional YouTube community-post companion: its literal caption
text, punctuated by Ollama (never allowed to change a word, deterministically validated, falling back to raw text
on failure), an image from a library outside the repo (upload or found from a link), an optional link back to the
Short, assembled into a copy-paste post, and its own "Đã đăng bài" tick independent of the Short's "Đã đăng". No
new dependency (image bytes sniffed by hand, HTML parsed with stdlib `html.parser`, links fetched with
`urllib.request` behind an SSRF-safe check). Re-plan 2026-09-29 note (below, CP9): the batch / community-post idea
from the original CP9 scope is delivered here, scoped to one Short at a time (no "process the whole bộ kinh" step).

---

## CP8.16 — Post Tab + Automatic Compose

> HUMAN LEAD 2026-09-30 (`docs/tasks/CP8.16-post-tab-auto.md`, R1–R5, S2). Amends `docs/decisions/CP8.15-community-post-contract.md` P1, P4, P9 and `docs/decisions/CP8.3-web-contract.md` W5, W6, W7.

The community post moves out of each Short card into a "Bài đăng" tab of the video (bar [Shorts | Khai thị | Bài đăng],
Short and khai thị posts together). Posts are composed automatically after a Short is rendered (and recomposed when the
source text changes, unless ticked "Đã đăng bài" or hand-edited); the compose job has its own runner key so it never
blocks editing a Short. The source line reads "HT. Tịnh Không". No new dependency, `posts.json` schema unchanged.

---

## CP9 — Human Review + Batch Processing

> Re-plan HUMAN LEAD 2026-09-27: phần batch mức playlist (bộ kinh: liệt kê, bấm xử lý từng tập, xếp hàng, trạng thái "Xong" suy ra khi đăng hết) kéo lên CP8.7 (`docs/tasks/CP8.7-playlist.md`, `docs/decisions/CP8.3-web-contract.md` W10). CP9 còn: tự xử lý hàng loạt, approval state, failed-item isolation đầy đủ.
>
> **Re-plan HUMAN LEAD 2026-09-29:** CP9 chỉ còn hai việc (`docs/tasks/CP9-clip-review.md`): (1) thêm Short từ đề xuất AI còn lại hoặc từ đoạn chọn trên transcript (AI đặt title); (2) sửa điểm đầu/cuối Short (theo dòng caption + tinh chỉnh ±0.2 s). Các mục khác bên dưới đã làm ở CP8.x (sửa title CP8.2, xóa/khôi phục CP8.5, render lại từng Short CP8.2, bộ kinh + hàng đợi CP8.7/CP8.10, lỗi / chạy tiếp CP8.13); "xử lý tất cả" một bộ kinh và approval state riêng: không làm.
>
> Contract: `docs/decisions/CP8.2-title-override-contract.md` T1, T8 (`review.json` `cuts` / `added`, luật đoạn tay); `docs/decisions/CP7-render-contract.md` R2, R3, R9, R11; `docs/decisions/CP8.3-web-contract.md` W5–W8.

Scope:
- candidate review;
- approve/reject/edit clip;
- title review;
- batch processing;
- approval state;
- rerender approved clips;
- failed-item isolation;
- resume after interruption.

Human review should modify artifacts/state rather than require rerunning the entire pipeline.

---

## CP10 — Evaluation + Quality / Guardrails

> **Đóng — HUMAN LEAD 2026-09-29:** không làm. Chất lượng được HUMAN LEAD kiểm bằng tai khi review (sửa title / điểm cắt / xóa Short). Ghi chú dưới giữ để tham khảo; mở lại cần quyết định mới.

**Change class:** S2 where shared policy/architecture decisions are introduced.

Measure:
- clip coherence;
- start/end quality;
- duration;
- title relevance;
- subtitle synchronization;
- visual composition;
- render correctness;
- failure rate;
- AI invalid-output rate.

Do not optimize based on intuition alone when measurable evaluation is possible.

---

## CP11 — Performance / GPU / Cache Optimization

Investigate:
- Whisper GPU usage;
- Ollama GPU usage;
- model loading;
- batch size;
- context size;
- inference time;
- render performance;
- artifact cache hit rate;
- safe parallelism.

The dubbing project demonstrated that local AI processing can become a major runtime bottleneck and that GPU configuration materially affects throughput. Measure on the actual target machine before selecting optimization strategies.

---

## CP12 — Release Readiness

**Change class:** S2.

Verify:
- installation;
- configuration;
- CLI;
- pipeline recovery;
- artifact integrity;
- failure handling;
- model configuration;
- documentation;
- reproducibility;
- clean environment;
- representative end-to-end run.

**Final state:** The project can reliably process real Vietnamese lecture videos without manual source-level editing for every Short.

---

## Backlog (not scheduled)

- HUMAN LEAD 2026-09-27: support short clips in other formats, not only 9:16 Shorts (e.g. short horizontal clips). Needs its own product decision (CP1 §2/§4) when opened.

---

# 5. Cross-Checkpoint Invariants

## Framework

Every checkpoint follows Framework v4. A roadmap entry does not itself authorize implementation.

## Source of truth

The repository is the source of truth. Chat messages are not project state.

## Scope

Claude must not silently expand scope. Later-checkpoint discoveries are recorded, not implemented early.

## S-classification

Every meaningful change is classified S0, S1, or S2. S2 decisions must not be silently implemented.

## Verification

Never claim PASS without actual evidence. READY requires implementation evidence, verification evidence, review result, non-blocking findings, and outside-scope findings.

## Review

Single-agent execution still requires a separate review phase. Review is diff-first and contract-first.

## Artifacts

AI-generated artifacts must be inspectable, schema-valid, traceable, resumable, and cache-aware where appropriate.

## AI boundaries

AI must not silently change architecture, add dependencies, modify project policy, approve its own S2 decisions, skip required human approval, or claim unverified results.

---

# 6. Checkpoint Transition Rule

The project moves from CP(N) to CP(N+1) only when:

`CP(N) -> READY -> HUMAN LEAD integration decision -> next checkpoint opened`

A READY checkpoint does not automatically authorize the next checkpoint.

---

# 7. Initial Success Definition

The target workflow is:

`Vietnamese lecture video -> transcript acquisition -> automatic analysis -> coherent clip candidates -> AI selection -> AI title -> optional human review -> automatic render -> multiple YouTube Shorts`

while preserving:

- provenance;
- reproducibility;
- resumability;
- validation;
- human control;
- Framework v4 process compliance.
