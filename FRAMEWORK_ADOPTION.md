# Framework v4 Adoption Record

## Reference

- Framework source/reference repository: `ntnghia1908/dang-vu-spring`
- Reviewed snapshot: `main` at commit `c5092ce` (V4-06, rollback window closed)
- Adoption basis: Framework v4 Quick Start and Tech Lead Handbook, cross-checked against the current Framework v4 files in the reference repository.

Framework changes after adoption are recorded in `docs/ai/framework-history.md`.

## Adopted

- Repository-as-source-of-truth principle.
- HUMAN LEAD / ORCHESTRATOR / IMPLEMENTER role model.
- S0 / S1 / S2 classification.
- Decision gates.
- Task contract lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`.
- Approval-before-execution and bounded autonomous execution.
- One writer per branch; bounded parallelism only for disjoint file boundaries.
- Required verification, diff-first review, convergence and circuit breaker.
- Outside-scope finding rule.
- READY and HUMAN LEAD integration gate.
- Three-layer architecture: Framework Core → Project Layer → Tool Adapter.
- Canonical-owner principle for normative rules.
- Greenfield adoption order from the handbook: Core → Project Layer → module rules as needed → execution profile → adapter → integration mechanism → checker → pilot.

## Adapted

- `docs/ai/project-profile.md` is new and describes a media/AI greenfield project rather than Spring/React/MySQL.
- Module map is planned and contains no implementation claims.
- `framework-check.mjs` is rewritten for this repository instead of copied from `dang-vu-spring`, because the reference checker contains project-specific paths/assumptions.
- Integration mechanism is branch → commit → push → PR → HUMAN LEAD merge.
- Claude adapter points to this repository's current-state and task structure.
- Project currently allows both `single-agent` and `dual-agent`; each task must select its profile.

## Not adopted

- Spring Boot, React, MySQL and related project architecture rules.
- Database baseline/frozen-schema policy from `dang-vu-spring`.
- Authentication/authorization rules from `dang-vu-spring`.
- `backend/` / `frontend/` module rules.
- `dang-vu-spring` business scope, glossary and deployment assumptions.
- `dang-vu-spring` model/vendor-specific assumptions in the framework core.
- `youtube-vietnamese-dubber` as runtime dependency or source of truth.

## CP0 boundary

This adoption record does not authorize video processing implementation. Whisper, Ollama, FFmpeg, model versions, package manager and rendering/template decisions remain future task/decision inputs.

## Verification status

CP0 checker is intended to prove structural adoption. Behavioral pilot of each execution surface belongs to a later pilot task, consistent with the Framework v4 handbook.
