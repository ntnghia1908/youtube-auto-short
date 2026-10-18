# TC1–TC3 — Implementation Authorization Boundary: AI Thematic Compilations

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Authority | HUMAN LEAD — feature boundary approval on 2026-10-18; repository documentation/push explicitly requested on 2026-10-18 |
| Governance | Framework v4.4 — boundary-authorized, dual-agent default |
| Scope | TC1 Theme Indexer → TC2 Compilation Planner → TC3 Landscape Renderer |
| Integration | Separate HUMAN LEAD approval remains required for push/PR/merge and production deployment |

> This record documents the already-approved feature boundary. The original approval was given in conversation ("đồng ý với phạm vi trên") on 2026-10-18. This file was added *after* TC1 and TC-WEB1 were implemented/integrated; it does not claim to have existed beforehand or rewrite their historical authorization evidence.

## 1. Authorization

- HUMAN LEAD approves implementation of TC1–TC3 **only within the feature scope and constraints below**.
- For a task fully inside this boundary, ORCHESTRATOR may create task graph and task contracts, record `Authorization mode: boundary`, `Authorization source: docs/decisions/TC1-TC3-implementation-authorization.md` and `Implementation authorized: YES`, then delegate implementation **without another per-task APPROVE TASK**.
- The task still needs a matching base commit/branch, bounded Owned paths, acceptance criteria and required verification. Use the existing v4.4 workflow, adapters, reviewer and circuit breaker; do not bypass decision gates.
- HUMAN LEAD retains authority over scope, architecture, significant shared abstractions, new dependency, database/security/public API contracts, breaking changes, commit/push/PR/merge and rollout according to `docs/ai/workflow.md` and `docs/ai/project-profile.md`. This record **does not approve unspecified changes in those categories**. Stop and request a focused decision when needed.
- A local task commit after valid authorization is permitted by the current project integration policy. Feature implementation push/PR, merge and deployment require separate HUMAN LEAD integration approval; the present **documentation-only push request** does not authorize them.

## 2. Product goal and MVP limits

Create a cohesive 30–40 minute thematic teaching compilation, assembled **only from previously HUMAN LEAD-curated, rendered 5–7 minute Khai thị clips**, respecting exact edited speech and provenance, with HUMAN LEAD selection/approval of the proposed compilation before output.

**Input eligibility:**

- Exactly one selected playlist / bộ kinh per compilation for MVP. Read playlist-scoped `output/_compilations/<playlist_id>/favorites.json` (❤️) as the explicit **source-clip curation signal**.
- Include only episodes identified by valid `khaithi.json` and actually rendered, usable clips whose **final measured duration is 300–420 seconds inclusive**. A hearted regular Short is not eligible.
- Exclude rejected, unrendered, missing, stale or non-reconstructable clips. A ❤️ favorite is not the same as `watched.json`; watched/published/not-rejected alone is not approval.
- ❤️ is **input curation**, not final compilation approval. HUMAN LEAD must still be able to review/approve chosen topic, clips and order.
- Kept/archived favorites are eligible for *landscape* only if the original or an equivalent verified full-frame source and all final edit decisions can actually be reconstructed. A preserved 9:16-only MP4 is insufficient; record an explicit ineligibility reason.

**Out of scope for MVP:** source-video mining or new clip extraction, cross-playlist compilation, generating synthetic speech/new quotations, vector database, novel external dependency, loops/repeats to pad duration, automatic publishing/YouTube upload, replacing CP8.33 existing compilation behavior, general media-pipeline refactors, arbitrary framework upgrades.

## 3. TC1 — Theme Indexer (already implemented)

- Build a per-playlist thematic index for eligible clips using the existing Ollama client and the **final edited content**, not the whole episode transcript or raw encompassing source interval.
- Persist reproducible theme/subtheme, brief synopsis, key messages, source provenance, evidence, edited segment ranges, model/prompt identity, fingerprint and explicit eligibility/uncertainty.
- Invalidate on meaningful changes to media/source, render, cut/review, transcript, model/prompt or approval/favorite status; reject unsupported or fabricated transcript claims.
- TC1 is historically documented in `docs/tasks/TC1-theme-index.md` and merged through PR #96. The read-only preview extension TC-WEB1 is separately authorized in `docs/tasks/TC-WEB1-theme-index-preview.md`, also merged through PR #96; rollout history is in those records/current-state. **Do not reopen or rewrite their completed contracts solely to change the historical citation.**

## 4. TC2 — AI Thematic Compilation Planner (next feature task)

- Consume validated, currently eligible TC1 index records within **one** playlist. Discover/suggest a coherent theme and select non-overlapping, nonduplicate clips that belong to that theme.
- Prefer a **30–40 minute** natural playlist of approximately 5–10 distinct 5–7 minute clips; do not repeat clips or loop/pad. If there is not enough thematically consistent approved material, report the shortfall and let HUMAN LEAD choose a different topic or wait for more clips.
- Show the proposed theme, clip titles, evidence/synopsis, duration, source references and proposed listening order. HUMAN LEAD can remove/reorder/select and explicitly approve the final plan.
- Write a versioned `compilation_plan.json` (or equivalent task-approved artifact), including clip identities, eligibility/fingerprint snapshot, thematic rationale, order, calculated duration, human approval marker/revision and traceable source references. Stale source or human changes invalidate approval.
- Reuse existing UI/compilation components if possible; **specific new HTTP routes, request/response schema, security exposure and required accepted decision amendments are separate decision gates**. Do not silently treat this scope statement as API contract approval.

## 5. TC3 — Full-frame 16:9 Landscape Renderer

- Render a **16:9 landscape MP4 from verified original/HD full-frame source**, rebuilding **exactly the approved clip's final spoken material and effective edits** (manual start/end, silence removals and other relevant accepted render decisions). Do not horizontally stretch/crop the finished 9:16 Short to pretend it is the original.
- Audit and reuse `render/stage.py:render_targets()` and `render/plan.py` kept-segment logic, CP8.32 effective source/archive restoration rules, and CP8.33 FFmpeg assembly, queue and chapter metadata as appropriate; do not assume `source_start`/`source_end` alone reproduce the approved clip.
- If the original source is missing, redownload differs/has unverifiable timing, approved edit decision is missing, or speech equivalence cannot be established, **fail closed** with a user-facing reason. Never silently substitute stale footage or invent a splice.
- Produce MP4, total duration and ordered YouTube chapters/description; verify audio/video synchronization, aspect ratio, durations and content provenance. Keep cache keys sensitive to source/edit/layout/content changes.
- Preserve CP8.33's existing vertical compilation outputs, favorites, kept files, queue priorities, and deletion semantics. Separate the new mode's IDs/artifacts/cache to avoid collisions; concrete schema/layout choices are task-level unless an architecture/API gate is reached.

## 6. Work plan, governance and quality gates

1. **TC1 — DONE** (existing merged implementation; do not implement again). **TC-WEB1 — DONE** (separate read-only preview scope). First check current main, worktrees and task status; do not rely on old chat prompts or stale SHAs.
2. **TC2 — NEXT.** ORCHESTRATOR first audits current TC1 + preview + CP8.33 interfaces, creates a bounded TC2 task contract referencing this file, checks any unresolved decision gate, then delegates authorized implementation.
3. **TC3 — AFTER TC2.** Use an independent task contract and acceptance tests; render integration only once a human-approved TC2 plan and reproducible final cuts exist.
4. Use Claude Code native Opus→Sonnet **or** Codex native workers as enabled by `framework.config.json`, choosing per task. One writer at a time for now. Do not nest provider CLIs or claim unverified runtime capabilities.
5. Fake/mocked AI in automated tests, tests for stale approvals and sources, provenance, nonduplication/target-duration and fail-closed landscape reconstruction. Run related tests, required full suite, `node scripts/framework-check.mjs` and `git diff --check`; report honest evidence.
6. Stop at READY or BLOCKED per workflow. HUMAN LEAD reviews compilation semantics manually and retains all integration/production gates.

## 7. Relationship to existing authority

- Framework/governance: `AGENTS.md`, `framework.config.json`, `docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, `docs/ai/project-profile.md`.
- Accepted media behavior: `docs/decisions/CP8.9-khai-thi-contract.md`, `docs/decisions/CP5-selection-contract.md`, `docs/decisions/CP7-render-contract.md`, `docs/decisions/CP8.3-web-contract.md`.
- Existing implementation contracts: `docs/tasks/CP8.32-vertical-original.md`, `docs/tasks/CP8.33-khaithi-compilation.md`, `docs/tasks/TC1-theme-index.md`, `docs/tasks/TC-WEB1-theme-index-preview.md`.
- This record authorizes the **new TC1–TC3 feature boundary**, not replacement of any existing canonical contract. Conflicts with accepted architecture/security/API rules or scope ambiguity go to HUMAN LEAD before code changes.

## 8. Audit trail

- 2026-10-18: HUMAN LEAD accepted the proposed TC1–TC3 feature scope, MVP-first, and allowed Claude Code/Codex interchangeably under the repo AI framework.
- 2026-10-18: TC1 + TC-WEB1 work already integrated under their respective session/task approvals (PR #96); this record is **subsequent formalization**, not evidence fabricated retrospectively.
- 2026-10-18: HUMAN LEAD requested this independent authorization document be pushed into repository for agent bootstrap/handoff. Documentation-only branch commit is authorized by that request; merge/feature integration is not implied.

## 9. Amendments

- **A1 — 2026-10-18 (HUMAN LEAD “duyệt 240–420”):** khoảng thời lượng eligible ở §2 (và TC1) đổi từ 300–420 s thành **240–420 s inclusive**. Lý do: audit read-only cả 3 bộ kinh có ♥ — 31 khai thị yêu thích đều 242–297 s, không clip nào ≥ 300 s. Mục tiêu 30–40 phút ở §4 giữ nguyên (khoảng 5–10 clip). Áp dụng qua TC2 (`docs/tasks/TC2-theme-compilation-planner.md`); không viết lại contract TC1 / TC-WEB1 đã hoàn tất.
