# Task: FIX-store-wait-persist — job "đợi 3090" không mất khi restart web

## Status / Approval

- Status: READY
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

- READY (ORCHESTRATOR review 2026-10-26). Codex: 1 vòng, ~77,7k tokens, effort high.
- Main changes: `jobs.py` lưu mục tùy chọn `store_wait` bằng `_entry` + `error`, chỉ lấy job INTERRUPTED mới nhất thuộc ba kind và có `WAIT_PREFIX`; giữ `version: 1`. Mở rộng `_restore_one_locked` để tái dùng `_rebuild`, khôi phục job INTERRUPTED ngoài mọi queue / parked, bỏ qua trùng active và log entry lỗi. Import cục bộ `KIND_RESTORE_SOURCE` vì `context.py` import `jobs.py`; tái dùng `WAIT_PREFIX` từ `store.borrow`.
- Đã kiểm `StoreWaitJob → finally → _after → _save_locked`; submit mới đã ghi lại snapshot. Thêm `_save_locked` trong `forget()` để xóa tập loại job đợi khỏi file ngay. Không cần sửa `app.py` / `store_retry_pass`.

| AC | Test / bằng chứng |
|---|---|
| 1 | `test_store_wait_restart_then_retry_without_reapplying_edits`: render / vertical / restore_source × lanes / serial; giữ error, spec, step, clip_ids, restored và edits đã applied; không vào queue / parked. |
| 2 | Test trên: kho thiếu / sai SHA vẫn đợi, đúng SHA submit lại và hoàn tất, không download / apply edits lần hai. `test_superseded_or_deleted_store_wait_is_removed_from_disk`: thay job cùng key / xóa tập, kiểm ngay file và app mới không retry job cũ. |
| 3 | `test_legacy_queue_and_nonlist_store_wait_restore_normally`: file cũ thiếu mục mới / mục không phải list. `test_bad_store_wait_entry_is_skipped_without_losing_valid_entries`: entry hỏng, kind / error sai, rebuild None / exception, trùng job active; entry hợp lệ vẫn restore. |
| 4 | ORCHESTRATOR 2026-10-26: targeted `tests/test_store_wait_persist.py tests/test_store_client.py tests/test_src3_auto_restore.py` **113 passed**; full suite `-n auto` **3026 passed, 1 skipped**; `framework-check` PASS; `git diff --check` PASS. |

- Helper mới: không có helper production; mở rộng helper `_restore_one_locked` có sẵn. Fixture test mới `waiting_app` dựng job đợi bằng app/runner thật và client/render giả; tái dùng `app_for`, `endpoint`, `cfg`, `episode`, `fake_download`, `request`, `run` từ các test hiện có. Đã tìm bằng `rg -n 'StoreWait|store_retry_pass|_rebuild_job|_snapshot_locked|def restore|def _after|def drop|_save_locked|WAIT_PREFIX' src/auto_short/web/jobs.py src/auto_short/web/app.py src/auto_short/store/borrow.py tests/test_store_client.py tests/test_src3_auto_restore.py`.
- Verification đã chạy; mọi lệnh pytest dưới đây dùng tiền tố `timeout 300 env PYTHONPATH=$PWD/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short` tại worktree này:
  - `tests/test_store_wait_persist.py`: **34 PASS** (9.59 s, lần cuối; trước khi thêm hai nhánh entry lỗi: 30 PASS).
  - `tests/test_src3_auto_restore.py`: **52 PASS** (8.25 s).
  - `tests/test_store_client.py -k 'client_token_from_env_only or config_store_section or put_streams_file_and_length_without_chunked_encoding or put_maps_http_errors_without_token or put_heads_existing_identity_without_sending_body or put_rejects_invalid_series_before_sending_body'`: **14 PASS, 13 deselected** (0.62 s).
  - `tests/test_web_queue_cp822.py -k 'not api_pause_resume_submit_while_paused_and_restart and not restore_skips_job_whose_workspace_is_gone and not restore_vertical_job_with_only_khaithi_workspace and not restore_skips_vertical_job_whose_workspaces_are_gone'`: **8 PASS, 4 deselected** (1.22 s).
- `timeout 10 git diff --check`: **PASS**. Diff ứng dụng **+34 / −1**; test mới **+200 / −0** (`git diff --numstat`, file mới chưa stage đo bằng `git diff --no-index --stat /dev/null tests/test_store_wait_persist.py`; exit 1 của no-index chỉ báo có diff).
- Không chạy lệnh targeted nguyên file `tests/test_store_wait_persist.py tests/test_store_client.py` / bộ ba trong Required verification vì phần còn lại của `test_store_client.py` cần server loopback / TestClient; sandbox không có socket loopback, theo chỉ thị bàn giao chỉ chạy test không cần socket. Full suite `… -m pytest -q -n auto`, bốn test TestClient CP8.22 và `node scripts/framework-check.mjs` để ORCHESTRATOR chạy theo phân công. Không gọi dịch vụ thật; không commit / push / PR / gọi agent khác.
