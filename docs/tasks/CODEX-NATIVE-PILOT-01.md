# CODEX-NATIVE-PILOT-01 — Verify native Codex dual-agent delegation with hashing unit tests

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Human Lead: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: codex — interactive main session, independent review
- Implementer: codex — built-in native worker (one actual worker/writer)
- Authorization mode: task
- Authorization source: HUMAN LEAD approved CODEX-NATIVE-PILOT-01 in conversation on 2026-10-18
- Human Lead approval: APPROVED 2026-10-18 for this bounded pilot
- Implementation authorized: YES
- Parallel group: —
- Owned paths: `docs/tasks/CODEX-NATIVE-PILOT-01.md`; `tests/test_hashing_codex_pilot.py` (new only)
- Dependencies: Auto Short merged framework v4.4 + ADR-003, PR #94
- Base commit / branch: `409cf5e5d5cd8ea291dab2b2c2767c720e737fc5` / `feature/codex-native-pilot-01`

This is **explicit task-level authorization**, compatible with project default `governance.taskAuthorization=boundary`. No general project boundary is granted or modified. The **only approved GitHub write now** is the setup commit that adds this task contract to the feature branch for Codex handoff. Implementation may modify owned files locally after runtime authorization checks, but **must not commit/push its implementation, open PR or merge without a separate HUMAN LEAD integration approval**.

## Goal

Demonstrate that interactive **Codex main session actually delegates implementation to a built-in native worker**, while main Codex acts as ORCHESTRATOR, independently reviews the resulting diff and reruns required verification. Use a tiny, non-production test-only change in the existing `src/auto_short/hashing.py` module.

A successful unit test alone is **not sufficient** to pass the pilot; native worker execution and review evidence are required.

## Scope

### In scope

1. Create `tests/test_hashing_codex_pilot.py` with a small set of deterministic pytest unit tests for existing behavior, using `tmp_path` and `monkeypatch` if needed:
   - `sha256_file` hashes known binary content accurately, including empty files if practical.
   - `fingerprint` returns resolved path, size, mtime_ns and SHA-256; matching cached fingerprint avoids recomputing the hash.
   - File content or mtime/size changed → `fingerprint` recomputes rather than accepting stale cache.
   - `canonical_json`/`config_hash` are deterministic across dictionary key ordering, and a meaningful config value change changes the hash.
2. Update the **Result section of this task contract only** with actual measured pilot evidence. Do not invent IDs, CLI version, models, tool names, or verification outcomes.
3. Codex main ORCHESTRATOR delegates this single bounded coding task to **one built-in native worker**, records the runtime thread identity and independently reviews and reruns checks.

### Out of scope

- **No edits to** `src/**`, any existing `tests/*` file, `framework.config.json`, `AGENTS.md`, `CLAUDE.md`, `docs/ai/**`, `docs/decisions/**`, `docs/workflow/**`, any other task contract, `adapters/**`, `scripts/**`, product/docs, dependencies, GPU, web or media pipeline.
- No `.codex/config.toml` or `.codex/agents/*.toml`. No Claude CLI, nested provider calls, alternate implementation agents, implicit `single-agent` fallback or parallel writes.
- No production service access, actual YouTube/Ollama requests or deployment.
- No implementation commit/push, PR or merge without separate approval.

## Authority / key decisions

- Framework ADR-003 accepted in `ntnghia1908/ai-dev-framework` and migrated through Auto Short PR #94; Codex native subagent remains **unverified until this pilot produces actual runtime evidence**.
- Source of truth: `AGENTS.md`, `docs/ai/project-profile.md` §7, `docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, `adapters/codex/README.md`, and this approved task contract.
- One active writer; no overlap with other live Auto Short worktrees. Verify branch, HEAD, `git status --short --untracked-files=all` and `git worktree list` **before modifying any file**. Never reset, clean or overwrite other worktrees.
- Native worker must be invoked using mechanisms available in **this actual Codex CLI session**. Docs or model responses are not proof of delegation; obtain a worker thread / subagent UI or tool-call record from runtime. If unavailable, STOP as BLOCKED with evidence; ask HUMAN LEAD before changing execution profile.
- Worker may share working directory and permissions with main session; prompts alone are not filesystem isolation. Only one worker is permitted in this pilot.
- Keep changes narrowly inside the two owned paths. No new architecture, dependency, security, API or framework policy decisions.

## Implementation approach

1. Codex main session bootstraps project authority, confirms pinned base and clean feature worktree; checks `codex --version`, actual model information exposed by runtime, and whether built-in worker delegation is available.
2. Main ORCHESTRATOR sends the implementation instructions, one owned test-file path, AC and required verification to **one native worker**. If native worker cannot be started, STOP BLOCKED; do not write tests in main session to simulate success.
3. Native worker writes **only** `tests/test_hashing_codex_pilot.py` and runs targeted verification; reports evidence and limitations. No implementation commit/push.
4. Main ORCHESTRATOR checks worker thread evidence, reviews **tracked + untracked diff**, owned paths, acceptance criteria, and reruns verification **independently**.
5. Main ORCHESTRATOR records actual outcomes below and stops READY or BLOCKED for HUMAN LEAD review.

## Acceptance Criteria

1. Real native Codex worker delegation shown by runtime evidence: CLI version, reported active model where available, worker thread ID or native delegation tool record (e.g. `/subagents`), and actual worker execution; a textual claim without runtime provenance **does not count**.
2. The worker writes one **new** test file `tests/test_hashing_codex_pilot.py`, covering file hash, cache reuse/invalidation, deterministic config hash; no source changes.
3. Relevant tests PASS on the actual branch, with command, count and exit status. Main ORCHESTRATOR independently reruns required verification and reviews results; the worker's own summary is not sufficient.
4. Project checker continues to PASS; existing legacy task contracts, governance and Framework version are unchanged.
5. `git diff --check`, tracked/untracked inventory and owned path audit show **only** the approved test file and this task's Result update.
6. No implementation commit/push/PR/merge or fallback to a different agent. Any unavailable native feature results in BLOCKED and a concise explanation.

## Required verification

- `python -m pytest -q tests/test_hashing_codex_pilot.py` — worker and ORCHESTRATOR separately, exit code required.
- `node scripts/framework-check.mjs` — ORCHESTRATOR independently, exit code required.
- `python -m pytest -q -n auto` — full required suite per project test policy before READY, if the environment supports it. If environment cannot run required suite, report BLOCKED or request explicit HUMAN LEAD approval for a limited test gate; never claim full-suite PASS.
- `git diff --check`; `git status --short --untracked-files=all`; `git diff --name-only 409cf5e5d5cd8ea291dab2b2c2767c720e737fc5`; review untracked test file content explicitly. No unapproved path modifications.
- Native delegation provenance: actual worker thread/tool record (thread ID, runtime interface or transcript excerpt); `codex --version`; runtime-reported model if visible; main ORCHESTRATOR independent review/retest record.

## Manual test checklist (Tech Lead)

- [ ] Codex actually started a native worker; not a single main agent impersonating two roles.
- [ ] Worker and main ORCHESTRATOR are logically distinct; main reran tests.
- [ ] No project source, dependencies, framework policy or other existing tests changed.
- [ ] No concurrent writer or unexpected worktree changes.
- [ ] No commit/push of implementation or PR without explicit integration decision.

## Result

- Status: READY — pilot thực thi 2026-10-18; HUMAN LEAD APPROVE COMMIT + PUSH + PR ngày 2026-10-18; không authorize merge.
- Authorization / Git: task APPROVED, Implementation authorized YES; branch `feature/codex-native-pilot-01`, working tree sạch trước delegation. HEAD `eeb06d63a24f69f17de804ac6fe0473d230d99b8` là setup commit chỉ thêm contract này trên base `409cf5e5d5cd8ea291dab2b2c2767c720e737fc5` (đã kiểm log/diff); HEAD không đổi sau implementation. Đã kiểm `git worktree list`; worker duy nhất của pilot ghi trong worktree riêng này, không thao tác worktree khác.
- Codex CLI version / main model (runtime reported): `codex --version` → `codex-cli 0.163.0`, exit 0. Runtime không công bố exact active model ID của main; không suy đoán từ tên CLI/config.
- Native worker evidence / thread ID / worker model (runtime reported): ORCHESTRATOR gọi native `collaboration.spawn_agent` với `task_name="hashing_worker"`, không override model; tool trả `{"task_name":"/root/hashing_worker"}`. `collaboration.list_agents` xác nhận `/root` và `/root/hashing_worker` đang running. Worker bootstrap, tạo test, chạy targeted verification và trả FINAL_ANSWER riêng; main sau đó review và retest. Canonical worker thread identity: `/root/hashing_worker`; runtime không cung cấp UUID hoặc exact worker model ID. Không gọi CLI/provider khác, không fallback single-agent, không tạo worker thứ hai.
- Changes (tracked + untracked): worker chỉ tạo `tests/test_hashing_codex_pilot.py` (6 cases); ORCHESTRATOR chỉ cập nhật Result của contract này. Test bao phủ empty/binary vượt chunk, resolved fingerprint fields, cache reuse không hash, invalidation riêng size/mtime qua `os.utime`, nested key ordering/Unicode và config value change.
- Worker verification (command, exit code): `/home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_hashing_codex_pilot.py` → 6 passed in 1.40s, exit 0; `git diff --check` → exit 0.
- ORCHESTRATOR independent verification (command, exit code): cùng lệnh targeted ở trên → 6 passed in 0.71s, exit 0; `/home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -n auto` → 1932 passed, 1 skipped, 1116 warnings in 96.85s, exit 0; `node scripts/framework-check.mjs` → PASS, exit 0. Python dùng conda env `auto-short`; pytest mặc định loại marker slow theo project policy.
- Scope and diff-first review: ACCEPTED, không có blocking finding. Main đọc toàn bộ test untracked, review contract → diff → AC → verification; kiểm spies bắt hash reuse/recompute và metadata invalidation tách biệt. `git diff --check`, `git status --short --untracked-files=all`, `git diff --name-only 409cf5e5d5cd8ea291dab2b2c2767c720e737fc5`, inventory untracked xác nhận chỉ hai owned paths; source, existing tests, framework/policy/dependency không đổi. Không commit/push/PR/merge implementation.
- Findings / limitations: sandbox command ban đầu lỗi `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`; lệnh cần thiết chạy lại bằng escalation được phê duyệt, không thay permission/config repository. Full suite có deprecation warnings Starlette/httpx/cookies và 1 skipped; không sửa ngoài scope. Exact model IDs không được runtime expose; delegation evidence là native tool record/thread và worker execution thực tế, không phải model suy đoán. Git inventory không chứng minh trạng thái mọi tiến trình ngoài session; không phát hiện thay đổi bất ngờ trong pilot worktree.
- Conclusion: READY — native delegation, independent review và required verification hoàn tất. HUMAN LEAD đã authorize commit đúng hai owned paths, push `origin/feature/codex-native-pilot-01` và tạo PR vào `main`; không merge. Evidence verification giữ nguyên vì không đổi tests/source; integration chỉ cập nhật authorization trong Result.
- PR: AUTHORIZED — title `test: verify Codex native dual-agent pilot`, base `main`; URL do integration report ghi nhận sau khi tạo.

## Handoff

Use **Codex CLI**, not Claude Code. Open the dedicated worktree on `feature/codex-native-pilot-01`. Read `AGENTS.md`, project profile and this approved contract, verify branch/HEAD/status/worktrees. Use the built-in native worker to add only `tests/test_hashing_codex_pilot.py`, collect true runtime thread evidence, independently rerun checks in main Codex session, and STOP at READY/BLOCKED. No implementation commit/push/PR/merge.
