# Task: FIX-store-wait-persist — job "đợi 3090" không mất khi restart web

## Status / Approval

- Status: IN_PROGRESS
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`): đổi định dạng file hàng đợi + khôi phục job
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-26 ("làm luôn 2 FIX", sau đề xuất trong `docs/workflow/current-state.md` Next action 4); `docs/decisions/HD2-external-store-3090.md` (HD2a: job đợi kho tự chạy lại khi kho trả lời)
- Parallel group: FIX-theme-store-index (đường dẫn rời nhau)
- Owned paths: `src/auto_short/web/jobs.py`, `src/auto_short/web/app.py` (chỉ khi cần cho khôi phục / `store_retry_pass`), `tests/test_store_wait_persist.py` (mới), file này
- Dependencies: none
- Base commit / branch: `2c29133` (`main`) / `fix/store-wait-persist`
- Human Lead approval: APPROVED (2026-10-26)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Job render / bản dọc / khôi phục nguồn đang "đợi 3090" (HD đã giải phóng nằm trên kho, kho chưa cho mượn được) vẫn còn sau khi restart web và tự chạy lại khi kho trả lời, như trước khi restart.

## Bối cảnh (2026-10-26, ORCHESTRATOR)

- `jobs.py` ~1097: `StoreWaitJob` → `job.status = INTERRUPTED`, `job.error = "đợi 3090: …"`, **không** đặt `job.resume`. `_snapshot_locked` chỉ lưu job INTERRUPTED có `resume` → job đợi 3090 không vào `.web_queue.json`; restart là mất.
- `app.py` `store_retry_pass` quét `runner.jobs()` (bộ nhớ) tìm job INTERRUPTED kind `render` / `vertical` / `restore_source` có error bắt đầu `WAIT_PREFIX` và là job mới nhất của key; với `restore_source` cần `target.restored is True`.
- `_rebuild_job` (app.py) đã dựng lại được cả 3 kind từ `spec` (restore_source giữ `edits`, `restored`). Hệ quả cũ: mất job `restore_source` = mất các chỉnh sửa người dùng đang chờ.

## Scope

- In scope: lưu các job đợi 3090 vào file hàng đợi (mục mới, ví dụ `"store_wait"`: entry như `_entry` + chuỗi `error`); `restore()` dựng lại chúng thành job INTERRUPTED với cùng `error`, không vào hàng / làn nào, là `latest` của key, để `store_retry_pass` hiện có chạy lại được. Lưu lại file khi job vào / rời trạng thái đợi (job mới submit thay thế, xóa tập…). Entry dựng lại không được (rebuild trả None / lỗi) → bỏ qua kèm log như entry khác.
- Out of scope: logic `store_retry_pass` / điều kiện sha256; job đợi HD (`parked`); đổi `WAIT_PREFIX`; UI.

## Authority / key decisions

- HD2a: đợi 3090 không phải lỗi; web tự submit lại khi kho có đúng sha256 đã giải phóng (giữ).
- S1 cục bộ: file hàng đợi giữ `version: 1`; mục mới là tùy chọn → file cũ không có mục vẫn đọc được, code cũ đọc file mới bỏ qua mục lạ.

## Implementation approach

- `_snapshot_locked`: thêm danh sách job `INTERRUPTED`, kind ∈ {render, vertical, restore_source}, `error` bắt đầu `WAIT_PREFIX` (import từ `..store.borrow` hoặc hằng chung, tránh import vòng), là `self._latest[key]`. Đảm bảo `_save_locked` được gọi sau khi `StoreWaitJob` đặt trạng thái (kiểm hiện đã gọi trong `finally` chưa).
- `restore()`: đọc mục mới, `_rebuild`, tạo `Job` status INTERRUPTED + `error`, đặt `_jobs` / `_latest`, không thêm vào `_queues` / `_parked`; bỏ qua nếu key đã có job active.

## Phải giữ nguyên

- Định dạng và hành vi các mục `lanes`, `parked`, `youtube`, `paused`; mọi test hiện có (đặc biệt `tests/test_store_client.py`, `tests/test_src3_auto_restore.py`, test hàng đợi CP8.22); không ghi file ngoài `.web_queue.json`.

## Code bị thay / xóa

- Không xóa; chỉ thêm vào snapshot / restore.

## Acceptance Criteria

1. Job render, vertical, restore_source (đã `restored`, có `edits`) đang đợi 3090 → lưu → app mới `restore()` → job INTERRUPTED cùng error, `spec` giữ nguyên (edits, restored).
2. Sau restart, `store_retry_pass` với kho có đúng sha256 submit lại đúng các job đó; kho chưa sẵn sàng → vẫn đợi; job đã bị thay bằng job mới hơn / tập đã xóa không được lưu hay chạy lại.
3. File hàng đợi không có mục mới (cũ) vẫn khôi phục như trước.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_wait_persist.py tests/test_store_client.py tests/test_src3_auto_restore.py` — AC 1–3 (TestClient: ORCHESTRATOR chạy nếu sandbox không chạy được).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4 (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

- [ ] Không bắt buộc: chỉ xảy ra khi kho 3090 tắt lúc render tập đã giải phóng; test tự động phủ restart.

## Handoff

- Outgoing / incoming ORCHESTRATOR: —
- Nguồn duyệt chuyển giao: —
- Phase / blocker / next action: giao Codex.
- HEAD + working tree lúc bàn giao: —

## Result

- (điền khi READY)
