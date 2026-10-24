# Task: FIX-theme-index-summary — Dòng trạng thái ghép chủ đề tách "chờ AI index" khỏi "không dùng được"

## Status / Approval

- Status: READY
- Type: FIX
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + full suite
- Implementer: claude-code `implementer` (Sonnet) — sửa nhỏ web + test JS / TestClient (Codex sandbox không chạy test web)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-24 ("Giao luôn", sau khi hỏi vì sao Kinh Vô Lượng Thọ báo 134 clip không dùng được)
- Parallel group: PKG-2026-10-24 (song song VIS1 + PKG2.1, pilot worktree-isolation HUMAN LEAD duyệt 2026-10-24; owned paths rời nhau)
- Owned paths: `src/auto_short/web/theme_plan.py` (chỉ `index_summary` trong `ThemePlans.view`), `src/auto_short/web/static/theme_plan.js` (dòng `tp-summary`), `tests/test_web_theme_plan.py`, contract này
- Dependencies: —
- Base commit / branch: `9db5a6a` (main) / `fix/theme-index-summary`
- Human Lead approval: HUMAN LEAD 2026-10-24
- Implementation authorized: YES

## Goal

Bộ Kinh Vô Lượng Thọ hiện báo "0 clip khai thị dùng được / 134 không dùng được … 82 × not a khai thi episode; 52 × generation-disabled: preview không sinh metadata; chưa có index hợp lệ cho dữ liệu hiện tại". Thực tế 52 clip là khai thị hợp lệ chỉ chưa được AI index (bấm "AI gợi ý chủ đề" sẽ index), 82 là Short thường. Dòng trạng thái phải nói rõ điều đó bằng tiếng Việt.

## Scope

- In scope:
  - `index_summary` thêm `pending` = số record `status == "ai_error"` và `reason == GENERATION_DISABLED` (`web/theme_index.py`); `unusable` không còn tính nhóm này; `common_reasons` bỏ nhóm này. Giữ các khóa cũ (`total`, `usable`, `unusable`, `by_status`, `source_missing`, `common_reasons`) để tương thích.
  - Lý do hay gặp hiển thị tiếng Việt qua bảng dịch nhỏ phía JS (giữ nguyên chuỗi gốc nếu không có bản dịch): `not a khai thi episode` → "Short thường, không phải khai thị"; `kept source unreconstructable` → "khai thị đã lưu không dựng lại được nguồn"; `rejected` → "clip đã bị loại khi duyệt"; `episode outside selected playlist` → "tập không thuộc bộ kinh này".
  - Câu mẫu: `0 clip sẵn sàng · 52 clip khai thị chờ AI đọc nội dung (bấm "AI gợi ý chủ đề") · 82 không dùng cho ghép chủ đề (82 × Short thường, không phải khai thị) · 28 clip phải tải lại nguồn khi ghép`. Phần nào bằng 0 thì bỏ (trừ "sẵn sàng").
- Out of scope: đổi `theme_index` / `theme_plan` core, đổi điều kiện eligibility, tự chạy index, trang `theme_index.html/js`.

## Authority / key decisions

- `web/theme_index.py` `GENERATION_DISABLED`, `RefusingClient` (preview không gọi AI).

## Phải giữ nguyên

- Logic index / gợi ý; các khóa JSON hiện có của `index_summary`.

## Code bị thay / xóa

- Chuỗi `tp-summary` cũ trong `theme_plan.js`.

## Acceptance Criteria

1. Record `ai_error` + `GENERATION_DISABLED` đếm vào `pending`, không vào `unusable` / `common_reasons`; `ai_error` lý do khác vẫn là không dùng được.
2. Dòng `tp-summary` theo câu mẫu, lý do đã dịch, phần bằng 0 bị bỏ.
3. Test cũ của `index_summary` / `tp-summary` vẫn PASS hoặc được cập nhật đúng theo câu mới (giải thích trong Result).

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_web_theme_plan.py`
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`.

## Manual test checklist (Tech Lead)

- [ ] HUMAN LEAD mở trang ghép chủ đề Kinh Vô Lượng Thọ trên 8080 (ghim commit branch): dòng trạng thái đúng như Goal.

## Result

- Main changes: `index_summary.pending` (ai_error + GENERATION_DISABLED, import từ web/theme_index) tách khỏi `unusable` / `common_reasons`; JS ghép câu mẫu, bảng `REASONS` dịch lý do, bỏ phần bằng 0 (trừ "sẵn sàng").
- Tests: `test_index_summary_separates_pending_from_unusable` (AC1); JS scenario `summary`, `summary-zero` (AC2); test cũ không phải sửa (AC3). `tests/test_web_theme_plan.py` 54 passed; framework-check PASS. Full suite `-n auto` (ORCHESTRATOR): 2351 passed, 1 skipped.
- Diff + / − (app, test): app +21/−4 (js 14/1, py 7/3); test +35/−2
- Helper mới (đã tìm, lý do không tái dùng): không (hằng `REASONS` trong JS)
- Review: ORCHESTRATOR review diff — đúng contract, giữ khóa JSON cũ.
- Important findings / decisions: Sonnet `implementer` 2 phút, 40k tokens, 0 vòng sửa; chạy song song VIS1 + PKG2.1 (pilot worktree-isolation, HUMAN LEAD 2026-10-24).
- Known limitations: chỉ dịch 4 lý do hay gặp; lý do khác hiện chuỗi gốc tiếng Anh.
- PR:
