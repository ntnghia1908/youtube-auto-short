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
- Owned paths: `src/auto_short/render/full.py`, `src/auto_short/titling/stage.py`, `src/auto_short/web/episodes.py` (`video_download_name`), `src/auto_short/web/routes/playlists.py` (`_vertical_status`), `tests/test_vertical_header_fallback.py`, contract này
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

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
