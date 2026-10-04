# Task: FIX-doc-match-050 — Hạ ngưỡng khớp văn bản gốc của tập (D3) từ 0,6 xuống 0,5

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `4906e11` (`main`) / `fix/doc-match-050` (worktree `../youtube-auto-short-docmatch`)
- Human Lead approval: APPROVED 2026-10-04 ("hạ ngưỡng khớp văn bản từ 0,6 xuống 0,5" — theo đề xuất ORCHESTRATOR cùng ngày)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi decision D3 đã accepted trong `docs/decisions/CP8.15-community-post-contract.md` (canonical owner); thay đổi code chỉ là hằng số.

## Bối cảnh (đo 2026-10-04, CP8.24 P3)

`match_ratio` tập ↔ trang văn bản: trang đúng 0,587 (Địa Tạng tập 1 — Whisper trên âm thanh cũ 480p), 0,608 (Địa Tạng tập 2), các bộ khác 0,67–0,91; trang sai ≈ 0,03. Với 0,6, Địa Tạng tập 1 bị loại ("văn bản gốc khớp 59% < 60%: không dùng"). Mỗi Short vẫn qua D4 (`ratio ≥ 0.6` riêng từng Short), nên hạ D3 không làm chữ sai lọt vào bài.

## Goal

Tập có `match ≥ 0,5` dùng văn bản gốc; D4 không đổi.

## Scope

- In scope: `MIN_MATCH = 0.5` trong `src/auto_short/post/doc.py`; cập nhật D3 trong `docs/decisions/CP8.15-community-post-contract.md` (ghi lý do + ngày, HUMAN LEAD 2026-10-04); thông báo log / UI có in ngưỡng thì khớp số mới; test biên (0,49 không dùng, 0,5 dùng).
- Out of scope: D4 (`MIN_RATIO`), CP8.25 (tự tìm văn bản), soạn lại bài các tập cũ (cache `doc.json` lưu `match`, `usable` tính lại theo ngưỡng mới khi soạn lần sau).

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` D3, D4; `docs/tasks/CP8.19-post-doc-source.md`; `docs/tasks/CP8.24-doc-pages.md` P3 (số đo).

## Acceptance Criteria

1. `match = 0.5` → dùng văn bản; `match = 0.49` → không dùng; `doc.json` cũ với `match = 0.587` dùng được mà không tải lại.
2. D4 không đổi (test hiện có PASS).
3. Decision D3 ghi ngưỡng 0,5 + lý do; không còn chỗ nào trong tài liệu hiện hành nói D3 = 0,6 như luật đang áp dụng (file task lịch sử giữ nguyên).

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1, 2.
- `node scripts/framework-check.mjs` — AC 3.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: bài đăng Địa Tạng tập 1 có nguồn "văn bản gốc" sau khi soạn lại.

## Result

- Main changes: `MIN_MATCH` 0.6 → 0.5 (`post/doc.py`); D3 trong CP8.15 contract ghi ngưỡng 0,5 + lý do + ngày; log `stage.py` in ngưỡng động nên không cần sửa.
- Tests: thêm biên 0.49 / 0.5 / 0.587 và cache `match = 0.587` dùng được không tải lại (`tests/test_post_doc.py`); `pytest -q -n auto`: 1450 passed, 1 skipped; framework-check PASS.
- Review: ORCHESTRATOR 2026-10-04 — ACCEPTED, không có blocking finding (hằng số + D3 + test biên; D4 giữ nguyên; chạy lại 300 test post PASS). Ghi chú ngoài scope: D1 trong CP8.15 chưa nhắc `doc_videos_per_page` (CP8.24) — pointer nên thêm ở lần sửa decision kế tiếp.
- Important findings / decisions:
- Known limitations:
- PR: #65
