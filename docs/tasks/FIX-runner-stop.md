# Task: FIX-runner-stop — dừng server không để lại ffmpeg mồ côi, không treo

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `e7a9d05` (`main`) / `fix/runner-stop` (worktree `../youtube-auto-short-stop`).
- Human Lead approval: APPROVED (2026-10-18: "đồng ý task sửa nhỏ")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1: sửa hành vi dừng của `JobRunner.stop` (CP8.3 W5 / CP8.22 lưu hàng đợi giữ nguyên); không đổi API, config, dependency, security model.

## Bối cảnh / bằng chứng (2026-10-18, ORCHESTRATOR)

1. **ffmpeg mồ côi.** Khởi động lại 8080 (Ctrl-C) lúc ≈ 05:51 UTC, server cũ ở `main` (một slot render). Log server cũ theo thứ tự: `job 18 failed [IleoZob08m4]: bản dọc: ffmpeg failed: exit 255` (bị SIGINT) → **`start vertical job 19 [dknZSTJdq-4]`** (một job mới bắt đầu *trong lúc đang dừng*) → `job still running after 30 s; exiting anyway`. Sau đó ffmpeg của job 19 (PID 81792, PPID 1) chạy tiếp ≈ 11 phút, ≈ 880 % CPU, cùng lúc server mới chạy lại đúng bản dọc đó (job 3, cùng file đích) → tốn gấp đôi CPU, có thể ghi đè file của nhau; HUMAN LEAD phải `kill` tay.
2. **Treo khi dừng.** Khi test CP8.35 (`test_ac5_false_after_true_clears_the_wish`, trước `995771c`) dừng app lúc một job đang chạy: `stop()` treo mãi ở `with self._lock:` (jobs.py, sau vòng `join`). Faulthandler: không thread làn nào sống mà khóa vẫn bị giữ. Nguyên nhân (IMPLEMENTER CP8.35): `_interrupt` dùng `PyThreadState_SetAsyncExc(KeyboardInterrupt)`; nếu ngoại lệ rơi vào lúc thread làn đang trong `with self._lock` (hoặc giữa acquire / release của Condition) thì RLock bị rò, thread chết vẫn giữ khóa.

## Goal

Ctrl-C server lúc đang có job chạy: không job mới nào bắt đầu sau khi bắt đầu dừng; mọi tiến trình con (ffmpeg, …) của server đã kết thúc khi server thoát; `stop()` luôn kết thúc trong khoảng `timeout` + vài giây, không treo.

## Scope

- In scope: `web/jobs.py` (`stop`, `_interrupt` / cách ngắt job, vòng `_work` / `_take_locked` khi `_stopping`, các bước nối tiếp của một job — vd job `vertical` fetch → render — không bắt đầu bước mới khi đang dừng); nếu cần, chỗ chạy tiến trình con (ffmpeg) để giết được cả cây (vd process group). Giữ CP8.22: job đang chạy / chưa xong được lưu và quay lại hàng đợi ở lần khởi động sau.
- Out of scope: đổi `timeout` mặc định; đổi hành vi làn khi không dừng; CP8.36 (render song song — nhánh khác cũng sửa `jobs.py`, giữ thay đổi gọn để gộp dễ).

## Acceptance Criteria

1. Sau khi `stop()` bắt đầu, không job / bước nào mới bắt đầu (test: job đang chạy bị ngắt + job khác chờ trong làn → không job thứ hai nào start; log không có `start … job` sau `stopping`).
2. Khi `stop()` trả về, không còn tiến trình con nào của server (test với tiến trình con thật, vd `sleep` / script bỏ qua SIGINT: sau grace thì SIGTERM / SIGKILL; cả tiến trình cháu nếu có).
3. `stop()` không treo kể cả khi ngắt rơi vào lúc thread làn đang giữ khóa runner (test tái hiện được, vd ngắt lặp nhiều lần quanh vùng có khóa; hoặc chứng minh cơ chế mới không thể rò khóa) — kết thúc trong `timeout` + ≤ 5 s.
4. CP8.22: job bị ngắt vẫn được lưu và khôi phục ở lần khởi động sau (test cũ PASS không sửa).
5. Toàn bộ suite PASS.

## Required verification

- `python -m pytest -q -n auto` — PASS (test mới `tests/test_web_stop_fix.py` cho AC 1–4; chạy test AC 3 lặp ≥ 30 lần với `-o faulthandler_timeout=20` không treo).
- `node scripts/framework-check.mjs` — PASS.
- `git status --short --ignored`: mọi file cần đều được track.

## Manual test checklist (Tech Lead)

Không chạm public API, database, security model.

- [ ] 8080 đang render (vd bản dọc): Ctrl-C → server thoát; `ps` không còn ffmpeg nào của server cũ; khởi động lại → job quay lại hàng đợi, chạy lại một lần (không trùng).

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
