# Task: FIX-publish-thumbs-shapes — Fixture `test_publish_thumbs` theo PKG3.1 G8 (bỏ `episode.shapes`)

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite
- Implementer: codex — sửa fixture test (HUMAN LEAD 2026-10-25 ưu tiên Codex)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 chọn "FIX test_publish_thumbs"
- Parallel group: P1 (song song RENDER-short-first; owned paths rời nhau)
- Owned paths: `tests/test_publish_thumbs.py`, contract này.
- Dependencies: none
- Base commit / branch: `b05fbaf` (origin/main) / `fix/publish-thumbs-shapes`
- Human Lead approval: HUMAN LEAD 2026-10-25
- Implementation authorized: YES

## Goal

Full suite trên main không còn 19 error `tests/test_publish_thumbs.py` (`AttributeError: module 'auto_short.packaging.episode' has no attribute 'shapes'`, fixture dòng ~97). PUB2 (#141) và PKG3.1 merge cùng ngày: PKG3.1 G8 thay `episode.shapes(cfg, id)` bằng `list(thumbnail.EPISODE_SIZES)` (cả hai khung cho mọi header hợp lệ). Code chạy thật `publish/thumbs.py` dùng `episode.valid_files`, không bị ảnh hưởng.

## Scope

- In scope: fixture / helper trong `tests/test_publish_thumbs.py` dựng ảnh thumbnail theo API hiện có của `packaging.episode` / `packaging.thumbnail` (G8: cả `landscape` lẫn `vertical`).
- Out of scope: `src/` (không sửa), test chập chờn `test_lower_thread_priority…`.

## Authority / key decisions

- PKG3.1 G8 (`docs/decisions/PKG-video-packaging-authorization.md` / contract PKG3.1); PUB2 contract cho hành vi test giữ nguyên.

## Implementation approach

- Thay vòng `episode.shapes(cfg, ident)` bằng `thumbnail.EPISODE_SIZES` (hoặc helper hiện có trả cùng tập khung); giữ `episode.cache_key`, tên file, `thumbs.json` như `episode` đang ghi. Nếu assertion của test giả định chỉ có 1 khung khi không có bản dọc, sửa theo G8 và ghi lý do trong READY report.

## Phải giữ nguyên

- Mọi test PUB2 vẫn kiểm cùng hành vi (khớp tên file, journal, dừng khi API lỗi, journal hỏng không ghi đè).
- Không sửa `src/`.

## Code bị thay / xóa

- Lời gọi `episode.shapes` trong test.

## Acceptance Criteria

1. `tests/test_publish_thumbs.py` không còn error / fail.
2. Không file `src/` nào đổi.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_publish_thumbs.py -q`.
- Full suite (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Chỉ sửa test; không có manual test.

## Result

- Main changes: fixture `episodes` dựng ảnh cho mọi khung `thumbnail.EPISODE_SIZES` (G8) thay `episode.shapes`; `test_match_shapes_normalization_skips_and_duplicates`: hàng thứ 7 (video dọc của tập 102 trên YouTube) giờ "sẵn sàng" vì G8 luôn có ảnh dọc kể cả khi tập chưa có bản dọc — trước G8 hàng này bị bỏ qua vì thiếu ảnh; các kiểm "bỏ qua" khác giữ nguyên.
- Tests: ORCHESTRATOR chạy `tests/test_publish_thumbs.py` 30 passed (Codex cũng 30 passed trong sandbox); full suite 2716 passed, 1 skipped, 0 error; 1 fail chập chờn đã biết `test_lower_thread_priority…` (chạy lại riêng PASS).
- Diff + / − (app, test): app 0; test +6 / −3.
- Helper mới (đã tìm, lý do không tái dùng): không.
- Review: ORCHESTRATOR đọc diff, ACCEPTED vòng 1. IMPLEMENTER Codex (`gpt-6.1-sol`, effort medium), 1 vòng, ≈ 31 k token.
- Important findings / decisions: không sửa `src/`; `publish/thumbs.py` chạy thật dùng `episode.valid_files` nên không bị lỗi runtime.
- Known limitations: không.
- PR: #150
