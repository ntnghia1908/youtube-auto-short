# Task: FIX-publish-thumbs-shapes — Fixture `test_publish_thumbs` theo PKG3.1 G8 (bỏ `episode.shapes`)

## Status / Approval

- Status: APPROVED
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

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
