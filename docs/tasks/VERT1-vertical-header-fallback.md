# Task: VERT1-vertical-header-fallback — Bản dọc tự tạo dòng tiêu đề khi chưa có Short

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, hành vi mới qua 3 module); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28 "Sửa code để bản dọc tự tạo dòng tiêu đề khi không có Short" (trả lời đề xuất ORCHESTRATOR cùng ngày)
- Parallel group: —
- Owned paths: `src/auto_short/render/full.py`, `src/auto_short/titling/stage.py`, `src/auto_short/web/episodes.py` (`video_download_name`), `src/auto_short/web/routes/playlists.py` (`_vertical_status`), `tests/test_vertical_header_fallback.py`, `tests/test_web_hd_cp827.py` (ORCHESTRATOR bổ sung 2026-10-28: test cũ khẳng định hành vi bị thay), contract này
- Dependencies: CP8.27 H4 (bản dọc), CP8.32 V3 ("Tạo bản dọc cả bộ"), CP13.2 H1 ("Chuẩn bị + HD"), HD2b (offload)
- Base commit / branch: `8de2f9d` (`main`) / `feature/vert1-header-fallback`
- Human Lead approval: APPROVED 2026-10-28 (yêu cầu trực tiếp)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ nới điều kiện của tính năng bản dọc sẵn có; header tính bằng `resolve_header` sẵn có (tất định, không AI); không đổi schema file, dependency, security model, public API (chỉ đổi lý do / danh sách "bỏ qua" của endpoint cả bộ).

## Bối cảnh (2026-10-28, ORCHESTRATOR)

- Vô Lượng Thọ 374 tập: 1–30 có bản dọc trên kho, 31–50 đang tạo; 324 tập (51–374) chưa xử lý Short.
- `render/full.py` `_run_vertical` đòi `titles.json` (chỉ bước titling tạo, sau AI selection) → không có Short thì không dựng được bản dọc. Header của `titles.json` lại tất định: `titling.logic.resolve_header(cfg.header, metadata title, cli, playlist=playlist_header)`.
- `_vertical_status` (playlists) chỉ nhận tập `rendered` / `complete`.

## Goal

Tập đã tải (ít nhất "Chuẩn bị + HD" xong, có nguồn HD hiệu lực) dựng được bản dọc mà không cần Short: dòng tiêu đề / người giảng lấy từ cùng quy tắc header của bước titling. "Tạo bản dọc cả bộ" xếp cả tập "Đã chuẩn bị — chờ cắt". Khi sau này làm Short, bản dọc vẫn hiện hành (key không đổi), không render lại.

## Scope

- In scope:
  - Helper header tất định dùng chung (trong `titling/stage.py`), `run_titling` dùng lại helper đó (không nhân bản logic gọi `resolve_header` + `playlist_header`).
  - `_run_vertical`: `titles.json` có → dùng header của file như hiện tại; không có → helper (cli rỗng). Header không giải được → `RenderError` tiếng Việt rõ ràng (nêu cần "Tên bộ kinh" hoặc mẫu tiêu đề).
  - `video_download_name`: thiếu `titles.json` → số tập từ helper (tên `…Tập<N>_Doc.mp4` thay vì `<id>_Doc.mp4`); lỗi header → giữ fallback cũ.
  - `_vertical_status`: state `prepared` được xét như `rendered` / `complete`; tập `new` lý do "chưa tải — bấm Chuẩn bị + HD trước".
  - Test.
- Out of scope: tự xếp bản dọc sau "Chuẩn bị + HD" (auto vertical CP8.35); job tải-không-phiên-âm; đổi UI ngoài chữ lý do; ghi `titles.json` từ bản dọc; xếp hàng thật 324 tập (vận hành, ORCHESTRATOR / HUMAN LEAD làm sau merge).

## Authority / key decisions

- CP6 titling header (G2) — `titling/logic.py` `resolve_header`; CP8.11 D5 `playlist_header`.
- D-local VERT1-1: bản dọc **không** ghi `titles.json` (file thuộc titling; packaging / ZIP / store đọc nó như dấu hiệu titling xong).

## Implementation approach

- Helper nhận `config`, workspace dir / metadata, cli tùy chọn → dict `{"lines","fields","sources"}` như `resolve_header`; lỗi → `TitlingError`. `_run_vertical` bắt `TitlingError` → `RenderError`.
- `split_header(lines, fields.speaker)` giữ nguyên; key bản dọc vẫn dựa trên display lines → giống hệt khi titling sau này cho cùng header.

## Phải giữ nguyên

- Tập có `titles.json`: header, key, tên file, mọi hành vi cũ (kể cả series / episode người nhập tay lúc xử lý).
- `run_titling` cho cùng đầu vào ra cùng header / cfg hash.
- Mượn HD từ kho (HD2a), offload / release (HD2b), auto vertical (CP8.35) vẫn đòi Short như cũ.
- Mọi test hiện có của `test_web_vertical_cp832.py`, `test_web_auto_vertical_cp835.py`, titling, store.

## Code bị thay / xóa

- Lệnh gọi `resolve_header(... playlist=lambda: playlist_header(...))` inline trong `run_titling` → thay bằng helper.
- Nhánh `raise RenderError("chưa có tiêu đề (titles.json) …")` trong `_run_vertical` → thay bằng fallback.

## Acceptance Criteria

1. Workspace có manifest + `metadata.json` + nguồn HD, không `titles.json`; tiêu đề khớp `title_patterns` hoặc video nằm trong bộ kinh có "Tên bộ kinh" → `run_vertical` tạo file; `vertical.json` `header` = lines của `resolve_header`; không có `titles.json` sau đó.
2. Sau AC1, ghi `titles.json` với header do `run_titling` tính cho cùng metadata → `render_full.current` vẫn True và `run_vertical` lần 2 reuse (key không đổi).
3. Không giải được header → `RenderError` (không traceback lạ), không tạo file.
4. `video_download_name(..., "Doc")` cho tập AC1 chứa số tập.
5. `POST /api/playlists/{id}/vertical`: tập `prepared` có HD → queued; tập `new` → skipped với lý do mới; tập `rendered` như cũ.
6. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_vertical_header_fallback.py tests/test_web_vertical_cp832.py tests/test_web_auto_vertical_cp835.py tests/test_titling*.py` — AC 1–5 (ORCHESTRATOR chạy phần web ngoài sandbox).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR, sau khi 20 job bản dọc VLT 31–50 xong): 8080 lên commit nhánh; 1 tập VLT "Chuẩn bị + HD" → "Tạo bản dọc cả bộ" → bản dọc lên kho 3090, xem khung tiêu đề.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract → điểm danh.

- [ ] Xem bản dọc của 1 tập chưa có Short: dòng tiêu đề / người giảng đúng như bản dọc tập đã có Short.

## Result

- Main changes: IMPLEMENTER hoàn tất 2026-10-28; giữ IN_PROGRESS, chờ ORCHESTRATOR chạy web / full suite và review trước READY. Sửa `titling/stage.py`, `render/full.py`, `web/episodes.py` (`video_download_name`), `web/routes/playlists.py` (`_vertical_status`); thêm `tests/test_vertical_header_fallback.py`.
- Tests (Python và PYTHONPATH đúng worktree được giao, không gọi mạng thật):
  - `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short tests/test_vertical_header_fallback.py tests/test_titling_stage.py tests/test_titling_logic.py tests/test_titling_added_cp9.py -k 'not test_ac5_playlist_queues_prepared_and_rendered_skips_new_and_unfinished'` → **110 passed, 1 deselected**, 2.33 s (sau khi sửa assertion để tính việc ngắt dòng của layout hiện có).
  - `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short tests/test_web_vertical_cp832.py tests/test_web_auto_vertical_cp835.py -k 'test_effective_source_rules or test_run_vertical_from_original_real_encode_and_reuse or test_refetch_wrong_video_is_refused_and_cleaned or test_refetch_different_bytes_warns_but_is_used or test_auto_archive_waits_for_a_vertical_job or test_ac1_ui_boxes_and_defaults or test_wish_file_unreadable_is_ignored'` → **7 passed, 30 deselected**, 7.25 s; có render thật bằng ffmpeg, không TestClient.
  - `node scripts/framework-check.mjs` → PASS; `git diff --check` → PASS.

  | AC | Test trong `test_vertical_header_fallback.py` | Kết quả IMPLEMENTER |
  |---|---|---|
  | 1 | `test_ac1_vertical_without_titles` (patterns / playlist) | PASS |
  | 2 | `test_ac2_titling_keeps_header_hash_and_vertical_key` | PASS |
  | 3 | `test_ac3_unresolved_header_is_render_error_and_name_falls_back` | PASS |
  | 4 | AC1 kiểm số tập từ cả hai nguồn; AC3 kiểm fallback; `test_existing_titles_keep_manual_header_and_download_name` | PASS |
  | 5 | `test_ac5_playlist_queues_prepared_and_rendered_skips_new_and_unfinished` | PASS (ORCHESTRATOR, ngoài sandbox) |
  | 6 | Full suite `-q -n auto` | PASS (ORCHESTRATOR) |

- Diff + / − (app, test): app **+40 / −13**; test **+179 / −0** (file mới, dùng `git diff --no-index --numstat /dev/null tests/test_vertical_header_fallback.py` để tính khi chưa stage).
- Helper mới (đã tìm, lý do không tái dùng): `titling.stage.resolve_workspace_header(config, workspace_dir, metadata=None, cli=None)` ghép đọc metadata với quy tắc header sẵn có. Đã tìm bằng `rg -n 'resolve_header|playlist_header|split_header|def .*header|def run_titling|def _run_vertical|def video_download_name|def _vertical_status' src/auto_short tests/render_helpers.py tests/titling_helpers.py`. Tái dùng `resolve_header`, `playlist_header`, `split_header`; `packaging.episode.header` chỉ trả fields và áp validation thumbnail nên không thay thế được helper này. Test tái dùng `HEADER` của `render_helpers`, workspace / client giả của `titling_helpers`, fixture / workspace / HD / playlist của `test_web_vertical_cp832`; thêm hai fixture cục bộ cho workspace prepared và ffprobe / ffmpeg giả vì chưa có helper phù hợp (đã tìm `CompletedProcess`, `fake.*(probe|ffmpeg)`, `def .*runner` trong các test helper / render liên quan).
- Review: IMPLEMENTER tự soát diff theo scope / AC; giữ nhánh ưu tiên `titles.json`, cfg hash titling, key và schema vertical; không sửa auto vertical / borrow / offload. Review độc lập chờ ORCHESTRATOR.
- Important findings / decisions: `vertical.json.header` hiện lưu dòng hiển thị đã fit của panel trên, người giảng ở `speaker`; test so sánh nội dung qua `split_header` và cho phép layout ngắt dòng. Không đổi schema hay ghi `titles.json` từ bản dọc.
- Known limitations: theo chỉ thị giao việc, không chạy TestClient do sandbox thiếu socket loopback; không thử khởi chạy rồi đợi treo. Hai lệnh Required verification pytest không lọc (AC1–5 và `-q -n auto`) chưa chạy; ORCHESTRATOR chạy ngoài sandbox. Chạy thật và manual checklist chưa thực hiện.
- ORCHESTRATOR 2026-10-28:
  - Review diff: đúng scope / Code bị thay; lỗi header ở `video_download_name` được nuốt → tập chưa có workspace giữ tên theo id.
  - `pytest -q tests/test_vertical_header_fallback.py tests/test_web_vertical_cp832.py tests/test_web_auto_vertical_cp835.py tests/test_titling_logic.py tests/test_titling_stage.py tests/test_titling_added_cp9.py tests/test_web_titles.py` → **167 passed**.
  - Full suite lần 1: 1 fail `test_web_hd_cp827.py::test_run_vertical_without_hd_or_header` — test khẳng định hành vi cũ (thiếu `titles.json` → lỗi) mà contract thay; đổi tên thành `test_run_vertical_without_hd_then_without_titles`, phần cuối khẳng định dựng được + không ghi `titles.json`. Lần 2: **3273 passed, 1 skipped**. `framework-check` PASS, `git diff --check` PASS.
  - Codex: 1 vòng, 84.930 tokens, không vòng sửa.
  - Chạy thật: chờ 20 job bản dọc VLT 31–50 xong rồi pin 8080 lên nhánh.
- PR: (điền khi mở)
