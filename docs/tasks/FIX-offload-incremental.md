# Task: FIX-offload-incremental — Đẩy bản dọc ngay khi băm xong, không chặn tắt web

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-26 "Chấp nhận tất cả đề xuất khác" (đề xuất ORCHESTRATOR sau lần chạy thật HD2b)
- Parallel group: P1 (cùng FIX-ytdlp-timeout-wait, ARC1 — owned paths rời nhau)
- Owned paths: `src/auto_short/store/offload.py`, `src/auto_short/web/app.py` (chỉ `offload_pass` / `_offload_loop` / lifespan dừng vòng đẩy), `tests/test_store_offload.py`, contract này
- Dependencies: HD2b (#167)
- Base commit / branch: `8cd3d13` (`main`) / `fix/offload-incremental`
- Human Lead approval: APPROVED 2026-10-26
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi thứ tự / cách dừng của vòng đẩy HD2b; luật HD1 G1 / G2, giao diện, config không đổi.

## Bối cảnh (2026-10-26, ORCHESTRATOR, chạy thật HD2b trên 8080)

- `offload.candidates()` băm sha256 **mọi** bản dọc chưa xác nhận (72 file, 57 GB) trước khi `offload_pass` đẩy file đầu tiên → lượt đầu mất nhiều phút mới đẩy.
- Việc băm chạy trong `asyncio.to_thread`; khi web nhận Ctrl-C, uvicorn in "Finished server process" nhưng tiến trình không thoát (thread executor không bị ngắt) → `auto-short-web-restart` báo "server … did not stop", 8080 tắt tới khi ORCHESTRATOR gửi SIGTERM.

## Goal

Lượt đẩy chỉ băm tới file chưa xác nhận đầu tiên theo đúng thứ tự HD2b (tập không có HD trước, rồi dung lượng giảm dần — thứ tự lấy từ `stat`, không cần sha) rồi đẩy file đó; tắt web trong lúc băm / đẩy → vòng đẩy dừng trong vài giây, tiến trình thoát, file đang dở không bị xác nhận / xóa.

## Scope

- In scope:
  - `candidates` / API tương đương: sắp thứ tự bằng `stat` + cache `vertical_sha` sẵn có; băm lười, dừng ở ứng viên đầu tiên cần đẩy (hoặc trả iterator). Snapshot Bộ nhớ (`pending`, `bytes_pending`) tính từ `stat` + cache, không băm hết.
  - Cờ dừng (`threading.Event`) do lifespan đặt khi tắt; kiểm giữa các khối khi băm (tự đọc từng khối, không gọi hàm băm không ngắt được) và trước PUT / confirm / release; dừng → không xác nhận, không giải phóng, không ghi cache sha dở.
  - Lifespan: sau khi đặt cờ thì cancel + chờ task vòng đẩy (có giới hạn ngắn).
  - Test.
- Out of scope: ngắt một lần `PUT` đang gửi giữa chừng (giới hạn bởi `timeout_seconds` của kho; ghi Known limitations nếu còn); đổi luật xác nhận / giải phóng; giao diện.

## Authority / key decisions

- HD2b contract (`docs/tasks/HD2b-store-offload.md`): thứ tự ứng viên, `_vertical_snapshot` (băm ngoài `backup._LOCK`), luật HD1 G1 / G2 qua `review.backup.confirm` / `release`.

## Phải giữ nguyên

- Luật xác nhận / giải phóng HD1 / HD2b; bỏ qua tập có job / lease (`backup_busy`); cache sha chỉ ghi khi stat không đổi; mọi test HD1 / HD2a / HD2b hiện có.

## Code bị thay / xóa

- Vòng băm toàn bộ trong `candidates()` thay bằng băm lười; xóa nhánh không còn dùng.

## Acceptance Criteria

1. 3 bản dọc chưa xác nhận: một lượt chỉ băm file đầu tiên theo thứ tự (đếm số lần băm bằng hàm giả) rồi đẩy nó; lượt sau đẩy file kế.
2. Snapshot Bộ nhớ có `pending` / `bytes_pending` đúng mà không băm file chưa có cache.
3. Đặt cờ dừng khi đang băm → hàm trả trong ≤ 1 khối đọc, không confirm / release, không ghi cache sha; vòng đẩy kết thúc.
4. Lifespan tắt app (TestClient đóng) khi vòng đẩy đang băm file lớn giả lập → đóng trong vài giây.
5. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_offload.py tests/test_hd_backup.py tests/test_store_client.py tests/test_store_download.py` — AC 1–4.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- ORCHESTRATOR: restart 8080 sang commit branch (hỏi có / không) khi vòng đẩy đang băm → restart thành công không cần SIGTERM.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API.

- [ ] Restart 8080 lúc đang đẩy: script báo "restarted".

## Result

- (điền khi READY)
