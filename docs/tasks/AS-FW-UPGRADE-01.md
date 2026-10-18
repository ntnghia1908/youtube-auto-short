# AS-FW-UPGRADE-01 — Upgrade Auto Short Framework v4.2 → v4.4 + ADR-003

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Human Lead: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session (Opus preferred if available)
- Implementer: claude-code — native `.claude/agents/implementer` (Sonnet), one writer
- Authorization mode: task
- Authorization source: HUMAN LEAD approved `AS-FW-UPGRADE-01` on 2026-10-18 in conversation (the current Auto Short v4.2 workflow governs this migration task)
- Base commit / branch: `6f796c068aaad03852aacc2fb962062fc5e23d79` / `feature/as-fw-upgrade-01`
- Framework source: `ntnghia1908/ai-dev-framework` main `aa9688d1b987aae6dc58f7c518f3b6cac7965930` (merged PR #8)
- Human Lead approval: APPROVED for the bounded migration task; separate documentation-only setup commit/push authorized
- Implementation authorized: YES
- Parallel group: —
- Owned paths: see **Scope — Allowed paths** below
- Dependencies: accepted ADR-001/002/003 in the kit; current Auto Short project authorities

**Integration gate:** The initial branch + this task-contract commit/push is authorized for Claude handoff. Subsequent implementation commit/push, PR and merge require a separate HUMAN LEAD decision. Do not interpret `Implementation authorized: YES` as integration permission.

## Goal

Upgrade `youtube-auto-short` from its existing adopted Framework v4.2 to the v4.4 workflow and ADR-003 **adaptive native dual-agent** capability, so that the HUMAN LEAD can open the project with Claude Code or Codex without cross-provider nested CLI orchestration. Preserve Auto Short business/application code, current decisions, history, existing task contracts, integration controls and runtime state.

This is **a framework migration only**, not authorization for a new Auto Short feature, Codex production readiness or parallel implementation.

## Scope

### Allowed paths (explicit ownership boundary)

- `docs/tasks/AS-FW-UPGRADE-01.md` — task/evidence and handoff.
- `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` — versioned Core copies from the approved kit; compare differences first.
- `docs/ai/agent-adapter-contract.md`, `docs/ai/adapter-descriptor.schema.json` — new Core contract/schema copies, if required for full v4.4 adoption.
- `docs/ai/project-profile.md` — **minimal targeted edits only** to §7 execution/governance/adapter policy (and required authority pointers); never overwrite the project-specific module map, policies, test policy or integration rules.
- `docs/ai/framework-history.md`, `FRAMEWORK_ADOPTION.md` — factual adoption/migration entry, source SHA and remaining limitations; preserve existing entries.
- `docs/tasks/_template.md` — v4.4/ADR-003 fields and optional `Orchestrator` / `Handoff`.
- `framework.config.json` — preserve project-specific `requiredFiles`, `requiredTokens`, paths; enable `claude-code`, `copilot` (existing), `codex`; no fixed `agents.orchestrator` **only as approved for this project**; `governance.taskAuthorization=boundary` and `maxParallelImplementers=3`, with operational write concurrency **1** until a separate isolation pilot.
- `AGENTS.md` — minimal vendor-neutral adaptive bootstrap pointer; keep project boundary; `CLAUDE.md` must remain an unchanged minimal `@AGENTS.md` bridge.
- `.claude/rules/execution.md`, `.claude/agents/implementer.md` — reconcile Claude-specific adapter rules only if needed; preserve effective Sonnet tool permissions and current-state import.
- `adapters/claude-code/**`, `adapters/copilot/**`, `adapters/codex/**` — install **necessary** kit adapter descriptors/docs; native Codex default is documented only, no `.codex/*.toml` in this task. Do **not** automatically adopt ChatGPT Product Agent or Product Layer unless it already belongs to this project.
- `scripts/framework-check.mjs` — inspect, compare and upgrade only if verified to preserve existing task/history semantics; **see compatibility gate** below.
- `tests/framework-migration.test.mjs` — OPTIONAL new, isolated Node structural migration tests (no changes to application tests).
- `docs/ai/framework-migration-notes.md` — OPTIONAL short compatibility/evidence note, only if an unavoidable limitation needs recording.

Paths are allowed **only** for changes required by the stated acceptance criteria; optional files are not instructions to create them.

### Out of scope

- All `src/**`, existing `tests/**` (except the optional new file above), `tools/**`, `config.toml` and production/runtime settings, `pyproject.toml`, dependencies, `README.md` application documentation, `work/**`, `output/**`, deployments and running web/worker processes.
- Existing `docs/tasks/*.md` **other than this task**, `docs/decisions/**`, accepted project contracts, the historical implementation/authorization record. **No mass edits** to historical task contracts or decisions.
- `.codex/config.toml`, `.codex/agents/*.toml`, Sol→Luna optimization, multi-writer pilot, cross-provider nested subprocess, live Codex delegation, and other repositories.
- Changing the project architecture, API or security model.
- Commit/push of implementation, opening PR or merging without separate approval.

## Authority / key decisions

1. HUMAN LEAD approved upgrading Auto Short to v4.4 + ADR-003 on 2026-10-18. This project-specific S2 approval explicitly authorizes adopting adaptive Claude/Codex native dual-agent, leaving **no fixed orchestrator binding** for new tasks, and the `boundary/3` configuration. **Existing in-progress/approved task profiles, implementer assignments and authorization are not retroactively changed.**
2. **Boundary authorization is not automatic:** a new feature still needs a documented HUMAN LEAD-approved Implementation Authorization Boundary. The project must STOP before implementation if a proposed task lacks applicable authority.
3. New Framework default `maxParallelImplementers=3` is a configuration ceiling; actual write concurrency stays 1 until a separately approved worktree-isolation pilot demonstrates safe parallelism.
4. Preserve the repository's project-specific authority order, tests, integration policy (branch → local commit after authorization → push/PR after separate HUMAN LEAD approval → HUMAN LEAD merge), existing feature worktrees, untracked files, and real application code.
5. The kit's checker v4.4 validates new authorization metadata. Auto Short contains approximately **84 historical task contracts** from v4.2. **Do not fabricate approvals, add blanket `Authorization mode: boundary` to old tasks, rewrite accepted decisions, move old tasks to hide them from validation, disable checks silently or claim PASS without running the actual checker.**
6. **Compatibility/decision gate:** perform a read-only checker migration impact test as the **first technical step**. If v4.4 checker rejects legacy tasks or other historical records, present precise failure counts, representative samples and a **minimal, honest backwards-compatibility plan** (e.g. a documented, bounded legacy validation policy). STOP for HUMAN LEAD approval before implementing any new checker exception, changing `taskDir`, rewriting history or weakening active-task authorization. Do not let this known issue trigger an 84-file rewrite.
7. HUMAN LEAD approved compatibility option A on 2026-10-18 in conversation: a bounded, frozen `legacyTasks` list in `framework.config.json` (83 task files at base `6f796c0`) validated with v4.2 rules, a minimal checker change plus an explicit-mode fix for the kit contradiction, no rewrite of historical tasks. Canonical policy: `docs/ai/framework-migration-notes.md`.
8. Main implementation agent is Claude Code Opus→Sonnet, independently reviewed. Codex native worker is **not yet runtime-piloted**; do not claim that it is.

## Implementation approach (short)

1. Verify `origin/main` SHA `6f796c068aaad03852aacc2fb962062fc5e23d79`, feature branch, HEAD (expect the single task-contract setup commit after base), tracked/untracked status and other worktrees; never reset other work.
2. Read the project's authoritative project profile, current state, accepted decisions and this task; compare the **actual** kit SHA `aa9688d1b987aae6dc58f7c518f3b6cac7965930` files with project v4.2 copies. Do not assume project `docs/ai/` is interchangeable with kit templates.
3. **Preflight compatibility before edits:** enumerate historical task schemas, compare v4.4 checker behavior and prepare any required HUMAN LEAD decision (see compatibility gate). Avoid large reads/refactors beyond audit needs.
4. Stage the smallest safe Core v4.4 and adapter/Project Layer adoption consistent with approved authority, preserving user-facing application code and existing adapter conventions.
5. Verify checker/new-task fixture, old task/history compatibility, `git diff --check`, owned paths, version/history alignment, bridge and unchanged runtime/application files.
6. Have native Sonnet IMPLEMENTER make bounded changes and run required verification; ORCHESTRATOR independently re-runs/checks verification, reviews diff and records any known limitation. STOP at READY or BLOCKED; no implementation commit/push without HUMAN LEAD approval.

## Acceptance Criteria

1. Project identifies its exact kit baseline and migration target, and records factual migration history (no claim of verified live Codex behavior).
2. Accepted Core v4.4 workflow/profile copied accurately (or difference justified with HUMAN LEAD approval); existing Project Layer policies, current-state, project contracts and authority order preserved.
3. Claude Code native Opus/Sonnet and Codex native worker are documented as the **default adaptive dual-agent execution options**; existing Copilot option remains; `single-agent` remains permitted. No cross-provider CLI subprocess or additional service.
4. Project-specific config preserves requiredFiles/requiredTokens, enables needed adapters, removes fixed orchestrator only as explicitly authorized here, and uses `boundary/3` while operational concurrency is 1; no task implementation without approved boundary.
5. **All historical task/decision contents are byte-for-byte unchanged.** If validation migration requires a new policy exception, it must be separately approved before implementation.
6. Framework structure validation for the target adoption must actually PASS. If it does not PASS due to the unresolved compatibility gate, report BLOCKED with evidence rather than claiming READY.
7. `CLAUDE.md` remains a minimal `@AGENTS.md` bridge; no hard-coded Codex model ID or `.codex/*.toml`. New task template expresses native dual-agent and supports short handoff.
8. No changes to application source, existing application tests, dependencies, runtime configuration or running processes; only allowed paths changed.
9. Independent review, honest verification evidence and remaining limitations documented. No PR/merge without HUMAN LEAD decision.

## Required verification

- `git status --short --untracked-files=all`; `git worktree list`; `git diff --check`; `git diff --name-only 6f796c068aaad03852aacc2fb962062fc5e23d79` — inspect all touched files including untracked.
- Compare `docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, copied schema and adapter descriptors with the pinned kit SHA; verify `frameworkVersion=4.4` and matching framework-history heading.
- Run `node scripts/framework-check.mjs` with the final adopted structure. Do **not** substitute a legacy checker PASS for full v4.4 verification; report limitations separately.
- Verify legacy contracts/decisions retained and authoritative, with a representative historical validation set and no fabricated authorization.
- A safe temp fixture for new task under documented boundary and disabled/mismatched adapter binding must respectively PASS/FAIL; use the checker actually shipped in project.
- `git diff 6f796c068aaad03852aacc2fb962062fc5e23d79 -- src/ tests/ tools/ config.toml pyproject.toml` must be empty (except permitted optional new `tests/framework-migration.test.mjs`, if created).
- Framework-only Node tests, if introduced, must pass. **Do not run GPU/media pipeline or production web/worker processes** merely to migrate agent documents.

## Manual test checklist (Tech Lead)

- [ ] Existing `docs/decisions` and 84 task contracts not rewritten.
- [ ] Project's web/API/security, runtime, module map and integration remain unchanged.
- [ ] `boundary/3` is documented, but **one writer only** pending separate pilot.
- [ ] Claude and Codex CLI can each bootstrap and read correct project authority (runtime pilot later; report status honestly).
- [ ] No actual Codex native delegation/cross-review/parallel pilot claimed complete.
- [ ] No migration of other repositories.

## Result

- Main changes: Core v4.4 files (`workflow.md`, `execution-profiles.md`, `agent-adapter-contract.md`, `adapter-descriptor.schema.json`), `_template.md`, `.claude/rules/execution.md` and `adapters/{claude-code,copilot,codex}/{adapter.json,README.md}` copied verbatim from kit `aa9688d`; `framework.config.json` (4.4, three adapters, `boundary/3`, no `agents` block, `legacyTasks`); `scripts/framework-check.mjs` = kit v4.4 checker + `legacyTasks` validation + explicit-mode fix; new `docs/ai/framework-migration-notes.md`; targeted edits to `project-profile.md` §7, `AGENTS.md`, `framework-history.md` (`## v4.4`), `FRAMEWORK_ADOPTION.md`; new `tests/framework-migration.test.mjs`.
- Tests / checker: IMPLEMENTER and ORCHESTRATOR (independent re-run, 2026-10-18) — `node scripts/framework-check.mjs` rc=0 (`PASS: framework structure`, 83 legacy tasks under v4.2 rules); `node --test tests/framework-migration.test.mjs` 6/6 pass; `git diff --check` clean; no diff under `src/`, existing `tests/`, `tools/`, `config.toml`, `pyproject.toml`, `docs/decisions/`, `CLAUDE.md`; in `docs/tasks/` only this file and `_template.md` changed; copied Core/adapter files byte-identical to kit `aa9688d`.
- Review: ORCHESTRATOR reviewed diff — no blocking findings; legacy branch reuses the v4.2 field/section rules unchanged.
- Important findings / decisions: kit v4.4 checker gave 163 FAIL on legacy tasks and contradicts its own comment (explicit `task` mode rejected under boundary); resolved by HUMAN LEAD option A (see Authority 7).
- Known limitations: Codex native worker, cross-agent review, handoff and multi-writer parallelism are not runtime-piloted; operational write concurrency stays 1.
- Integration: HUMAN LEAD approved implementation commit + push + PR (no merge) on 2026-10-18 in conversation; checker and migration tests re-run before commit (rc=0, 6/6).
- PR: opened for HUMAN LEAD review; merge by HUMAN LEAD only

## Handoff

Open the project with Claude Code on `feature/as-fw-upgrade-01`. Read `AGENTS.md`, `docs/ai/project-profile.md`, `docs/workflow/current-state.md` and this approved task. Verify HEAD includes the documentation-only setup commit. Run read-only compatibility preflight first. If new v4.4 checker would require rewriting historical approvals or adding a policy exception, STOP and present a short HUMAN LEAD decision proposal; otherwise implement inside owned paths, independently verify, and stop at READY. No implementation push/PR/merge.
