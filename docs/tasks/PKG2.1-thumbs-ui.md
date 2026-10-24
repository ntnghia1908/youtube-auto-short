# Task: PKG2.1 — Trang thumbnail cả bộ dễ dùng + kiểu riêng cho bản dọc

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + test web / full suite + xem trang trên 8080
- Implementer: claude-code `implementer` (Sonnet) — HUMAN LEAD 2026-10-24 yêu cầu chạy song song với Codex VIS1; việc có vòng test web / UI
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` G5, G7 (HUMAN LEAD góp ý trang PKG2 ngày 2026-10-24)
- Parallel group: PKG-2026-10-24 (song song VIS1, HUMAN LEAD duyệt 2026-10-24; owned paths rời nhau, worktree / branch riêng)
- Owned paths: `src/auto_short/packaging/episode.py`, `src/auto_short/web/episode_thumbs.py`, `src/auto_short/web/static/thumbs.html`, `src/auto_short/web/static/thumbs.js`, `tests/test_packaging_episode.py`, `tests/test_web_episode_thumbs.py`, contract này
- Dependencies: PKG2 (đã merge, #132). Branch / PR riêng với VIS1.
- Base commit / branch: `9db5a6a` (main) / `feature/pkg2.1-thumbs-ui`
- Human Lead approval: boundary PKG ACCEPTED; yêu cầu HUMAN LEAD 2026-10-24
- Implementation authorized: YES

## Goal

HUMAN LEAD (thường trên điện thoại) chọn kiểu / ảnh rồi bấm dựng mà không phải kéo qua cả kho ảnh; trạng thái chỉ cần tiến độ chung; bản dọc 9:16 chọn được kiểu / ảnh riêng, mặc định dùng chung với bản ngang.

## Scope

Góp ý HUMAN LEAD 2026-10-24: "chọn hình xong phải kéo tuốt dưới mới nhấn nút dựng được"; "trạng thái từng tập không cần quá chi tiết, chỉ cần biết process chung"; "nên có chức năng chọn riêng cho bản ngang và dọc, mặc định dùng chung 1 kiểu".

- In scope:
  - **Nút luôn thấy**: thanh hành động (Xem trước, Dựng cả bộ, Tải zip, trạng thái ngắn) `position: sticky; bottom: 0` có nền, luôn hiện ở đáy màn hình khi cuộn form.
  - **Chọn ảnh gọn**: hiện "Ảnh đang chọn" (ảnh nhỏ + số / "Không ảnh") + nút "Đổi ảnh"; lưới ảnh nằm trong `<details>` (mặc định đóng), cuộn trong khung `max-height: 50vh; overflow: auto`. Chọn ảnh xong thì đóng lại.
  - **Xem trước ngay dưới cấu hình** (trên thanh hành động), không đẩy xuống cuối trang.
  - **Tiến độ chung**: một dòng tổng hợp từ view (`Đã có thumbnail X/Y tập — ngang a, dọc b · N tập bỏ qua`), lý do bỏ qua gộp theo loại kèm số lượng; khi job chạy: thanh `<progress>` + summary job. Lưới từng tập chuyển vào `<details>` "Xem từng tập" mặc định đóng (chỉ dựng DOM khi mở).
  - **Kiểu riêng cho bản dọc**: settings thêm `vertical`: `null` (mặc định = dùng chung) hoặc `{style, asset_id, focus_x}`; `title_lines`, `credit` dùng chung. Trang: ô "Bản dọc dùng kiểu riêng" — bật thì hiện nhóm kiểu / ảnh / vị trí cho bản dọc (cùng cơ chế chọn ảnh gọn ở trên). Khi `vertical = null`, settings hiệu lực cho từng khuôn và cache key **bằng đúng** key hiện tại (không dựng lại thumbnail đã có). Bản dọc ghi đè → chỉ key bản dọc đổi. `thumbs.json` của tập ghi asset theo từng khuôn (đọc được file cũ chỉ có `asset_id`). Xem trước hiện cả hai khuôn theo settings hiệu lực. Asset của nhóm dọc cũng qua `assets.usable(..., kind="image")`.
- Out of scope: kiểu ngoài A/B/C; tiêu đề / credit riêng cho bản dọc; override từng tập; đổi bố cục ảnh (`thumbnail.py`); đổi zip / route tải.

## Authority / key decisions

- PKG2 contract (§ Vòng 2), boundary PKG R5–R9.
- Tương thích ngược: file settings / `thumbs.json` hiện có (không có `vertical`, một `asset_id`) đọc được, không phải dựng lại.

## Implementation approach

- `episode.py`: hàm settings hiệu lực theo khuôn (`landscape` = các trường gốc; `vertical` = gốc + ghi đè), `cache_key` / `context` / `valid_files` / `build_episode` / `preview` dùng settings hiệu lực theo khuôn. `validate_settings` thêm `vertical`.
- `episode_thumbs.py`: body PUT / preview nhận `vertical` (Strict, tùy chọn); view thêm số liệu tiến độ gộp (đếm có file theo khuôn, bỏ qua theo lý do) để JS không phải tự đếm.
- `thumbs.html/js`: bố cục như Scope; giữ style JS hiện có (`AutoShort.el/api`), tiếng Việt.

## Phải giữ nguyên

- Key / file thumbnail hiện có khi không bật kiểu riêng; zip, route tải, job `episode_thumbs`, làn render.

## Code bị thay / xóa

- Lưới từng tập luôn mở ở cuối trang → thay bằng dòng tiến độ + `<details>`.

## Acceptance Criteria

1. Settings không có `vertical` → key 16:9 và 9:16 của mọi tập không đổi so với trước (test so key với giá trị tính bằng code cũ / fixture).
2. Bật kiểu riêng cho dọc → chỉ thumbnail dọc có key mới; dựng lại không gọi ffmpeg cho bản ngang.
3. `vertical` sai (kiểu lạ, asset chưa duyệt, focus ngoài 0–1) → 400 trước khi chạy ffmpeg.
4. View trả số liệu tiến độ gộp đúng (có file theo khuôn, bỏ qua theo lý do).
5. Trang: thanh hành động sticky; lưới ảnh và lưới từng tập trong `<details>` đóng mặc định (test HTML tĩnh / JS tối thiểu như test PKG2 hiện có).

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`.

## Manual test checklist (Tech Lead)

- [ ] HUMAN LEAD mở trang thumbnail cả bộ trên điện thoại (8080 ghim commit branch): chọn ảnh, bấm dựng không phải cuộn xa; bật kiểu riêng cho dọc, xem trước, dựng.

## Result

- Main changes: `episode.effective(settings, shape)` (key / dựng / preview theo settings hiệu lực từng khuôn; `vertical` null thì dict y hệt cũ nên key không đổi); `settings.vertical` + `validate_settings`; `thumbs.json` thêm `asset_ids` (đọc được file cũ chỉ có `asset_id`); view có `progress`; PUT / preview nhận `vertical`; trang: thanh hành động sticky, ảnh chọn gọn + `<details>` Đổi ảnh, tiến độ chung, `<details>` Xem từng tập, ô Bản dọc dùng kiểu riêng.
- Tests: `PYTHONPATH=<worktree>/src pytest tests/test_packaging_episode.py tests/test_web_episode_thumbs.py` = 99 passed; `node scripts/framework-check.mjs` PASS. AC1 `test_keys_unchanged_without_vertical_override` (8 key chụp từ code cũ) + `test_legacy_settings_file_and_record_without_vertical_still_valid`; AC2 `test_vertical_override_changes_only_vertical_key_and_rebuild`, `test_http_vertical_override_only_rebuilds_vertical`; AC3 `test_invalid_vertical_override_rejected_before_ffmpeg`, `test_vertical_override_asset_must_be_approved`, `test_http_vertical_override_validation_preview_and_save`; AC4 `test_service_progress_counts_per_shape_and_reasons`; AC5 `test_page_has_sticky_action_bar_and_collapsed_lists`.
- Diff + / − (app, test): app +220 / −70, test +210 / −1.
- Helper mới (đã tìm, lý do không tái dùng): `effective`, `recorded_asset`, `_check_look` (episode.py; tách phần kiểm style / focus / asset dùng chung cho gốc và `vertical`), `EpisodeThumbs.progress`, `VerticalIn` (pydantic); JS `showPicked` / `fillGallery` dùng chung hai nhóm chọn ảnh. Không có helper tương đương sẵn trong repo.
- Review: ORCHESTRATOR review diff `episode.py` (key hiệu lực theo khuôn, đọc `thumbs.json` cũ). Full suite `-n auto` (ORCHESTRATOR): 2376 passed, 1 skipped. Kiểm AC1 trên dữ liệu thật bộ Địa Tạng (102 tập, chỉ đọc): `valid_files` code main = code PKG2.1 = 88 ngang / 41 dọc dùng lại được.
- Important findings / decisions: Sonnet `implementer` 6 phút, 102k tokens, 0 vòng sửa; chạy song song VIS1 + FIX-theme-index-summary (pilot worktree-isolation, HUMAN LEAD 2026-10-24). AC3: kiểu / focus sai qua HTTP trả 422 (pydantic Strict, như trường gốc PKG2), asset chưa duyệt trả 400.
- Known limitations: thanh `<progress>` tính `with_any / total` nên không tới 100 % khi có tập bỏ qua (dòng chữ vẫn đúng số); hành vi DOM chưa có test tự động (repo không có harness DOM), cần xem thật trên điện thoại.
- PR:
