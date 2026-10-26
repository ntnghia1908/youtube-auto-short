# Task: FIX-ytdlp-timeout-wait — Tải YouTube bị timeout thì đợi, không fail

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`, fix nhỏ); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-26 "Chấp nhận tất cả đề xuất khác" (đề xuất ORCHESTRATOR cùng ngày, sau khi 26 tập fail ingest)
- Parallel group: P1 (cùng FIX-offload-incremental, ARC1 — owned paths rời nhau)
- Owned paths: `src/auto_short/ingest/youtube.py`, `tests/test_youtube_wait.py`, contract này
- Dependencies: FIX-youtube-botcheck-wait (Y1–Y4), SRC4 (mượn nguồn từ kho khi YouTube chặn)
- Base commit / branch: `8cd3d13` (`main`) / `fix/ytdlp-timeout-wait`
- Human Lead approval: APPROVED 2026-10-26
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ mở rộng nhận dạng Y1 của FIX-youtube-botcheck-wait; không đổi hàng đợi, dependency, security model, public API.

## Bối cảnh (2026-10-26, ORCHESTRATOR)

- Đêm 2026-10-25 → 26: 49 workspace (26 tập Vô Lượng Thọ / Cảm Ứng Thiên / Thập Thiện, Short + khai thị) fail ingest với `yt-dlp download failed: ERROR: [download] Got error: The read operation timed out` (tải ~1 MB/s). Hàng đợi prepare cạn từ 25 xuống 1; HUMAN LEAD phải xếp lại tay.
- `ingest/youtube.py` `_BLOCK_MARKERS` chỉ nhận bot check / 429 → timeout là `DownloadError` thường → job fail, làn chạy job kế, job kế cũng timeout.

## Goal

Lỗi mạng tạm thời của yt-dlp khi tải (timeout đọc, kết nối bị reset / đóng giữa chừng) đi đúng đường "YouTube tạm chặn" sẵn có: job không fail, quay về đầu làn `prepare`, làn đợi 15 → 120 phút rồi tự thử lại; SRC4 vẫn mượn nguồn từ kho được như khi bị chặn.

## Scope

- In scope:
  - Thêm dấu hiệu vào nhận dạng Y1 (`is_blocked_message`), ít nhất: `the read operation timed out`, `read timed out`, `connection reset by peer`, `connection aborted`, `remote end closed connection`, `incompleteread` / `incomplete read`. So khớp không phân biệt hoa thường, sau khi bỏ mã màu ANSI (như hiện tại).
  - Docstring `YoutubeBlocked` / `is_blocked_message` ghi rõ nhóm "lỗi mạng tạm thời".
  - Test.
- Out of scope: đổi khoảng chờ / banner (chữ banner "YouTube tạm chặn" giữ nguyên); tùy chọn retry / `socket_timeout` của yt-dlp; tự xếp lại tập đã fail (HUMAN LEAD đã xếp lại 26 tập 2026-10-26).

## Authority / key decisions

- `docs/tasks/FIX-youtube-botcheck-wait.md` Y1–Y4 (giữ nguyên cơ chế đợi).

## Implementation approach

- Mở rộng `_BLOCK_MARKERS` (hoặc tuple thứ hai cho lỗi mạng, cùng hàm `is_blocked_message`); không đổi chỗ raise `YoutubeBlocked`.

## Phải giữ nguyên

- Lỗi khác (video riêng tư / bị xóa / "Video unavailable" / sai định dạng) vẫn fail như cũ; mọi test FIX-youtube-botcheck-wait, SRC4, TC3.2 hiện có.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Downloader giả ném lỗi `... Got error: The read operation timed out` (có mã ANSI) → `YoutubeBlocked`; job quay về đầu làn, không fail (như AC1 của FIX-youtube-botcheck-wait).
2. Mỗi dấu hiệu mới được nhận dạng; "Video unavailable" / "Private video" vẫn là `DownloadError` thường.
3. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_youtube_wait.py` — AC 1–2.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 3.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API.

- [x] Lần sau gặp timeout: banner "YouTube tạm chặn" hiện, job không fail (2026-10-26, xem Result).

## Result

- READY, merge PR #169 (2026-10-26). Codex: 1 vòng, effort medium, ~38k tokens. Code +10 / −4, test +49 / −15; helper mới: không.
- AC1 `test_block_requeues_head_lane_waits_then_all_done_in_order[timeout]`; AC2 `test_detector_temporary_network_errors`, `test_ytdlp_download_raises_blocked_vs_plain`; AC3 ORCHESTRATOR full suite `-n auto` 3115 PASS, 1 skipped; framework-check, `git diff --check` PASS.
- Chạy thật 8080 `20501e1` 2026-10-26: xếp lại 26 tập (47 job) fail ingest đêm 25 → 26/10 (43 × read timeout, 3 × Broken pipe, 1 × SSL handshake timeout). Gặp timeout ngay: log "prepare lane waits 15 min (block #1)", job về đầu làn, không fail; `GET /api/episodes` → `youtube.blocked = true`, `next_check` +15 phút (nguồn banner), queue `pending 47`.
