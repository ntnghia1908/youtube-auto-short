# Task: FIX-theme-offloaded-shorts — Ghép chủ đề nhận khai thị đã chuyển lên kho 3090 (SHO1)

## Status / Approval

- Status: IN_PROGRESS
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`, fix nhỏ có bằng chứng rõ); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "các video khai thị ghép rồi của VLT đã mất?" — bug hồi quy của SHO1, sửa trong boundary SHO1 / TC3 đã duyệt
- Parallel group: P1 (song song THUMB1, path rời)
- Owned paths: `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_render/__init__.py`, `tests/test_theme_index.py`, `tests/test_theme_plan.py`, `tests/test_web_theme_plan.py`, `tests/test_theme_render.py`, contract này
- Dependencies: SHO1a / SHO1b (Short lên kho), TC3 / TC3.2 (ghép chủ đề)
- Base commit / branch: `62b9f65` (`origin/main`) / `fix/theme-offloaded-shorts`
- Human Lead approval: APPROVED 2026-10-28 (bug report)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Bằng chứng (8080 `62b9f65`, 2026-10-28)

- `GET /api/playlists/PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_/theme-plan`: `index_summary` total 215, indexed 4, ineligible 176 (48 × `[Errno 2] No such file or directory`); 4 plan đều `check.state = "stale"` (`<id>.kt/kNN: no longer indexed`), `output = null`. File `output/_compilations/<pid>/theme/{d2d95528d136-r1,e7809c5c400a-r1,0281de6b6e0f-r2,667178c6583f-r2}.mp4` vẫn còn.
- `output/5wv5_Q0Utn8.kt/shorts/` trống từ 2026-10-27 09:39 (`[store] offload_shorts = true`, SHO1).
- Nguyên nhân: `theme_index._prepare` (`:213-214`) `_file(video, sha)` → `stat()` FileNotFoundError → `audit_playlist` (`:273-275`) ghi ineligible; `theme_plan._current` chỉ giữ "indexed" → `_check` stale → `web/theme_plan.output()` None. `theme_render._reference` (`:57-77`) cũng chỉ nhận file local / kept copy → ghép lại (revision mới) sẽ lỗi "Short tham chiếu bị thiếu".

## Goal

Khai thị đã lên kho (SHO1) vẫn được chỉ mục chủ đề tính là dùng được; 4 video ghép VLT hiện lại không cần dựng lại; ghép lại bản mới mượn Short tham chiếu từ kho.

## Scope

- In scope:
  - Index: clip không có file local nhưng `ep.short_locations` trả `StoredShort` cho đúng clip với sha256 = sha của manifest/record → `render_sha256` = sha đó (giống giá trị cũ khi còn file local) → `input_fingerprint` không đổi. Có thể thêm trường không vào fingerprint (như `source_status`) để biết clip ở kho. Sha lệch / không có bản ghi → giữ lỗi hiện tại.
  - Render: `_reference` trả location; trong ExitStack mượn bằng `store.shorts.borrow_short` (như ghép yêu thích CP8.33, `web/compilations.py:410`); kho tắt → lỗi đợi / RenderError rõ như đường nguồn hiện có (`:138-148`); giữ fallback kept copy.
  - Tránh import vòng (`web.episodes` ← theme_index): import trễ hoặc helper sẵn có ở tầng thấp hơn nếu có.
- Out of scope: thay đổi `theme_plan` / `web/theme_plan` (không cần nếu fingerprint giữ nguyên); thumbnail / trang Đóng gói (THUMB2); tốc độ tải trang Yêu thích.

## Phải giữ nguyên

- Fingerprint / `render_sha256` của clip còn local; lý do ineligible khác; kept copy; luật SHO1 (không tự tải lại vĩnh viễn khi chỉ đọc chỉ mục — chỉ đọc bản ghi, không gọi mạng).

## Code bị thay / xóa

- Không có (mở rộng `_prepare` / `_reference`).

## Acceptance Criteria

1. Clip có `store.json` hợp lệ, không có file local → indexed, cùng `input_fingerprint` + `render_sha256` như trước khi offload; sha bản ghi lệch → vẫn ineligible.
2. Plan đã duyệt trước khi offload vẫn `approved` sau offload; `web` view có `output` (không null).
3. Render với Short tham chiếu ở kho: mượn qua StoreClient giả, so audio chạy; kho tắt → lỗi đợi / thông báo rõ, không crash; file mượn được dọn.
4. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_theme_index.py tests/test_theme_plan.py tests/test_theme_render.py tests/test_store_shorts.py` — AC 1–3.
- `<prefix> tests/test_web_theme_plan.py` — AC 2 (TestClient: ORCHESTRATOR).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- Chạy thật (ORCHESTRATOR): bản sao `theme_index.json` + gọi chỉ mục trên dữ liệu VLT thật (không ghi đè bản live) → đếm indexed tăng, 4 plan `approved`; sau merge + restart 8080: trang Yêu thích VLT hiện lại 4 video.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API → điểm danh sau automated verification.

- [ ] Trang Yêu thích VLT: 4 video ghép hiện "xong", Xem / Tải được.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
