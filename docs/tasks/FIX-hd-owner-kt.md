# Task: FIX-hd-owner-kt — Bản HD / dọc của video chỉ còn phần khai thị (`<id>.kt`)

## Status / Approval

- Status: IN_PROGRESS
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite, kiểm trên dữ liệu thật (chỉ đọc)
- Implementer: claude-code `implementer` (Sonnet) — route + test web (sandbox Codex chặn loopback)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 "ok cả hai" (sửa lỗi tập 1–9 Kinh Địa Tạng: dùng thư mục `.kt` khi video gốc đã xóa)
- Parallel group: —
- Owned paths: `src/auto_short/enhance/state.py`, `src/auto_short/render/full.py`, `src/auto_short/review/backup.py`, `src/auto_short/web/episodes.py`, `src/auto_short/web/routes/episodes.py`, `src/auto_short/web/routes/playlists.py`, `src/auto_short/web/app.py`, `src/auto_short/web/context.py`, `src/auto_short/web/playlists.py` (`hd_progress`, bổ sung khi review 2026-10-25), `scripts/backup/make_backup.py` (bảng sha, bổ sung khi review), `tests/test_hd_owner_kt.py` (mới), test hiện có của module trên chỉ khi hành vi đổi theo task, contract này.
- Dependencies: HD1a (cùng branch, PR #144)
- Base commit / branch: `0882b2c` / `feature/hd1a-backup-release`
- Human Lead approval: HUMAN LEAD 2026-10-25
- Implementation authorized: YES

## Goal

Video mà phần Short đã bị xóa, chỉ còn phần khai thị `work/<id>.kt/` (giữ `source_hd.mp4` riêng, không còn `work/<id>/`): web vẫn thấy bản HD, tải được bản HD / dọc, tạo được bản dọc, xác nhận / giải phóng (HD1a) được — như video còn đủ. Thực tế: Kinh Địa Tạng tập 1–9 (`9NQFsvecC04`, `rBvztHKbNe4`, `ND1Eu4aax44`, `ja52PvWoU4o`, `1VAkCR8kK5I`, `LeqFAlSS2oA`, `GLHlwvZdU4c`, `RLkVp6Bsevc`, `ztfEEXhnBf4`), mỗi tập ≈ 2 GB HD trong `.kt`, script sao lưu báo "chưa sẵn sàng".

## Scope

- In scope: quy tắc "chủ" của bản HD / bản dọc (CP8.27 / CP8.32 `owner_id` / `hd_owner` / `render_full.owner_of`): `<id>` nếu `work/<id>/` tồn tại, **ngược lại** `<id>.kt` nếu `work/<id>.kt/` tồn tại; áp cho cả id gốc lẫn id `.kt` gửi vào route (playlist dùng id gốc). Route tải HD / dọc, view episode / playlist, job bản dọc, `review/backup.py` confirm / release.
- Out of scope: Short, khai thị render, theme index / ghép chủ đề (đã đọc nguồn theo workspace của từng clip), enhance service (khai thị `follows`), đổi vị trí file đã có.

## Authority / key decisions

- Quyết định cục bộ S1: hàm mới nhận `config` (vd `enhance_state.owner_for(config, episode_id)`), giữ `owner_id` thuần chuỗi cho chỗ không cần ổ đĩa; mọi chỗ trong Owned paths quyết định thư mục HD / dọc đi qua hàm mới. Bản dọc của video chỉ còn `.kt` nằm ở `output/<id>.kt/full/vertical.mp4`.
- Video còn `work/<id>/`: hành vi không đổi (cùng đường dẫn, cùng key).

## Implementation approach

- Thêm `owner_for`; thay ở các điểm quyết định thư mục HD / dọc (`web/episodes.hd_owner` / `hd_source`, `render_full.owner_of` / `vertical_dir` / `vertical_path` theo config, `review/backup._owner_dir`, route `source-hd` / `vertical` / `backup` / `release`, `routes/playlists` cột HD / dọc, `app.py` auto vertical).
- Tái dùng `khaithi.SUFFIX`, `Workspace` / đường dẫn `config.workspace.dir`.

## Phải giữ nguyên

- Mọi test hiện có của video còn `work/<id>/` pass không sửa.
- HD1a: hard link `.kt` của video còn đủ vẫn bị xóa cùng khi release.

## Code bị thay / xóa

- Không có (thêm hàm, đổi lời gọi).

## Acceptance Criteria

1. Video chỉ còn `work/<id>.kt/` có `source_hd.mp4` hợp lệ: `GET /api/playlists/{pid}` (entry `<id>`) có `hd_url`; `GET /api/episodes/<id>/source-hd` và `/<id>.kt/source-hd` trả file; tạo bản dọc ghi `output/<id>.kt/full/vertical.mp4`, route `vertical` trả file.
2. `POST /backup` + `/release` với `<id>` hoặc `<id>.kt` thao tác trên `work/<id>.kt/` và `output/<id>.kt/full/`.
3. Video còn đủ: đường dẫn / kết quả không đổi (test hiện có).

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_hd_owner_kt.py tests/test_hd_backup.py -q` + test hiện có của module đã sửa.
- Full suite (ORCHESTRATOR).
- Kiểm chỉ-đọc trên dữ liệu thật: `hd_source` của 9 tập trên trả `kind=hd` (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Không chạm database / security model; route nội bộ đổi cách tìm thư mục → manual test là điểm danh.

- [ ] Chạy lại `backup.ps1 -NoRelease` trên 3090: tập 1–9 tải được bản HD.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Known limitations:
- PR: #144 (cùng branch HD1a)
