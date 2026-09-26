# Task: CP0 — Framework v4 + Project Bootstrap

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Base commit / branch: `39d3cf30e2c12b64592ed6538b293546468421f9` / `feature/cp0-framework-bootstrap`
- Human Lead approval: explicitly approved in conversation
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE is inferred from Git after merge.

## Goal

Bootstrap `youtube-auto-short` as a clean greenfield project using the universal portions of Framework v4, with a project-specific Project Layer and tool adapters, without importing `dang-vu-spring` project rules.

## Scope

### In scope
- Framework Core: `AGENTS.md`, `docs/ai/workflow.md`, `docs/ai/execution-profiles.md`.
- Project Layer: `docs/ai/project-profile.md`, `docs/workflow/current-state.md`.
- Task contract template.
- Claude Code bridge/adapter and GitHub Copilot pointer.
- Framework checker adapted to this project's paths.
- README and Framework adoption record.
- Initial `.gitignore`.

### Out of scope
- Whisper/Ollama/FFmpeg implementation.
- Video download, transcription, shot detection, clip selection, title generation or rendering.
- Locking a Python package manager, model, media codec version or deployment stack.
- Creating module-specific AGENTS files before conventions exist.

## Authority / key decisions

- Framework source/reference: `ntnghia1908/dang-vu-spring` main at `c5092ce`.
- Adoption basis: Framework v4 Quick Start + Tech Lead Handbook + current Framework v4 files in reference repository.
- Greenfield adoption follows Core → Project Layer → module rules as needed → execution profile → adapter → integration mechanism → checker → pilot.
- `youtube-vietnamese-dubber` is reference-only and is not runtime/source authority.
- Canonical roadmap: `AUTO_SHORT_CHECKPOINT_PLAN.md` from `main` (HUMAN LEAD decision, 2026-09-26: YouTube transcript first). `docs/roadmap/checkpoint-plan.md` is removed so the roadmap has one canonical owner.

## Implementation approach

- Keep universal workflow semantics in Framework Core.
- Put project identity, boundaries, policies and integration in Project Profile.
- Keep tool-specific behavior in adapters.
- Adapt the checker instead of copying project-specific assumptions from `dang-vu-spring`.

## Acceptance Criteria

1. Repository has a single current Framework v4 workflow authority.
2. Bootstrap order and invariants are defined in root `AGENTS.md`.
3. Project-specific authority/module/integration information is in Project Profile.
4. Current operational state has one canonical location.
5. Task template supports S1/S2 contracts.
6. Claude/Copilot adapters point to shared framework rules instead of duplicating them.
7. Framework checker runs with Node stdlib only and checks this project's structure.
8. Adoption record explicitly separates adopted framework semantics from non-adopted `dang-vu-spring` project rules.
9. No video/AI implementation is introduced in CP0.

## Required verification

- `node scripts/framework-check.mjs` — structural framework checks PASS.
- Repository tree inspection — all CP0 acceptance files exist and no feature implementation was introduced.
- Diff review against this task contract — scope remains CP0 only.

## Manual test checklist (Tech Lead)

Task type: S2 documentation/governance bootstrap; no database, security model or public API contract.
Manual verification is post-automation review and is not a database/security/API pre-merge gate.

- [ ] Open root `AGENTS.md` → bootstrap order and invariants are visible.
- [ ] Open `docs/ai/project-profile.md` → project is described as greenfield and `youtube-vietnamese-dubber` is reference-only.
- [ ] Open `docs/ai/workflow.md` → S0/S1/S2 and decision gates are defined.
- [ ] Run `node scripts/framework-check.mjs` → PASS.
- [ ] Confirm no Whisper/Ollama/FFmpeg feature code was added.

## Result

- Main changes: Framework v4 Core, Project Layer, Claude/Copilot adapters, checker, adoption record; `CLAUDE.md` reduced to a minimal `@AGENTS.md` bridge; canonical roadmap set to `AUTO_SHORT_CHECKPOINT_PLAN.md`.
- Tests: `node scripts/framework-check.mjs` → exit 0. Initial run on fresh clone FAILED (`CLAUDE.md must be a minimal AGENTS.md bridge`), fixed once. Negative tests on a scratch copy (missing `AGENTS.md`, extra rule in `CLAUDE.md`, non-CURRENT `workflow.md`) → exit 1 with the expected message. Tree inspection: no `src/`, no Whisper/Ollama/FFmpeg or media code.
- Review: ACCEPTED (single-agent separate review: contract → diff → AC → evidence). AC1–AC9 met.
- Pilots: S0 = current-state CP1 pointer sync (`f1072b7`); S1 = `docs/tasks/CP0-S1-pilot-task-contract-check.md`, approved by HUMAN LEAD and READY.
- Important findings / decisions: framework adoption is a greenfield adaptation, not a fork of `dang-vu-spring`. Branch renamed to `feature/cp0-framework-bootstrap` per project profile (HUMAN LEAD, 2026-09-26). Non-blocking: this contract's original approval was recorded as "in conversation".
- Known limitations: Copilot surface and Claude Code auto-loading of `CLAUDE.md`/`.claude/rules` are structurally checked only, not behaviorally validated.
- PR: https://github.com/ntnghia1908/youtube-auto-short/pull/1 (awaiting HUMAN LEAD merge)
