# Task: HD1a — Xác nhận sao lưu bằng sha256, giải phóng bản HD / dọc trên VM, script 3090

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite, chạy thật trên bản sao dữ liệu, sinh script
- Implementer: claude-code `implementer` (Sonnet) — có route + test web (sandbox Codex chặn loopback, project-profile §7)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: `docs/decisions/HD1-hd-backup-release.md` ACCEPTED (HUMAN LEAD 2026-10-24, G1–G3 + G6–G7; tên `[HD Mobile]`)
- Parallel group: —
- Owned paths: `src/auto_short/review/backup.py` (mới), `src/auto_short/enhance/state.py`, `src/auto_short/enhance/service.py`, `src/auto_short/render/stage.py`, `src/auto_short/render/full.py`, `src/auto_short/web/episodes.py`, `src/auto_short/web/routes/episodes.py`, `src/auto_short/web/routes/playlists.py`, `src/auto_short/web/app.py`, `src/auto_short/web/jobs.py`, `src/auto_short/web/static/app.js`, `scripts/backup/` (mới), `tests/test_hd_backup.py` (mới), test hiện có của các module trên chỉ khi hành vi đổi theo HD1, contract này.
- Dependencies: HD1 ACCEPTED
- Base commit / branch: `28cb7e2` (main `b6fb02c` + HD1) / `feature/hd1a-backup-release`
- Human Lead approval: HD1 ACCEPTED 2026-10-24 ("duyệt đề xuất HD1", đổi tên bản dọc thành `[HD Mobile]`)
- Implementation authorized: YES

## Goal

Máy 3090 chạy script sao lưu: tải bản HD ngang + bản dọc, kiểm sha256, **xác nhận với VM bằng sha256**, rồi (hỏi một lần) **giải phóng** `source_hd.mp4` + `full/vertical.mp4` của các tập đã sao lưu đủ. Sau khi giải phóng: Short / khai thị đã render không thành cũ, không tự render lại, enhance không xếp lại tập, web hiện "HD đã chuyển ra máy ngoài".

## Scope

- In scope: HD1 G1 (route xác nhận + `backup.json`), G2 (route giải phóng), G3 (trạng thái `released`), G6 (script 3090 trong repo + generator), G7.
- Out of scope: HD1 G4 / G5 (gắn playlist HD YouTube, lấy lại nguồn — task HD1b); dọn Short / khai thị; sửa PUB2.

## Authority / key decisions

- `docs/decisions/HD1-hd-backup-release.md` G1–G3, G6, G7 (canonical). Sửa CP13.1 E5 / E6 và CP8.6 đúng như HD1 G3, không hơn.
- Owner: luôn thao tác trên video gốc (`enhance_state.owner_id`; `<id>.kt` → `<id>`), như route tải HD / dọc hiện có.
- sha256 bản dọc: tính trên VM lần đầu cần, cache trong `backup.json` theo kích thước + mtime_ns (không băm lại mỗi lần gọi).
- G3 cho tập `released`: `enhance.json` giữ `state: done`, `source_hd_sha256` / `_size`, thêm `released: true` + `released_at`. Render (`render/stage.py`) với tập `released` và không có file HD: **từ chối render** với thông báo "HD đã chuyển ra máy ngoài" (HD1b sẽ thêm nguồn từ YouTube), không rơi về bản gốc im lặng; mọi đường tự render lại / tự xếp enhance / tự dựng bản dọc bỏ qua tập `released`; khóa render của Short đã có không đổi (không bị coi là cũ).
- Tên file script: ngang `[HD] <bộ kinh> - Tập N.mp4`, dọc `[HD Mobile] <bộ kinh> - Tập N.mp4`, ảnh cùng tên `.jpg`; file `[HD Dọc] …` cũ trong thư mục đích được đổi tên (giữ dòng sha đã kiểm trong file tổng sha).

## Implementation approach

- `review/backup.py`: đọc / ghi `work/<owner>/backup.json` (atomic), `confirm(config, eid, kind, sha256)`, `release(config, eid, allow_no_vertical=False)`, `vertical_sha` (cache). Tái dùng `enhance_state.read/write/hd_path/hd_fingerprint`, `render_full.vertical_path/read_meta`, `hashing.sha256_file`, khóa / kiểm job như `POST /api/episodes/{id}/archive` (CP8.6).
- Routes (`web/routes/episodes.py`): `POST /api/episodes/{id}/backup` `{kind, sha256}` → `{confirmed: {...}}`; `POST /api/episodes/{id}/release` `{allow_no_vertical?}` → `{released, freed, removed}`; 409 khi job / lease đang chạy, 422 khi điều kiện G2 không đạt (thông báo tiếng Việt rõ: "chưa xác nhận bản dọc", "sha không khớp file hiện tại"…). `hd_video` của `GET /api/episodes/{id}` + `vertical` / `hd_url` của playlist: thêm `released` / `backup` (thêm trường, không bỏ); tập `released` không có `hd_url` / `vertical.url`.
- `app.js`: chỗ hiện link tải HD / dọc hiện "HD đã chuyển ra máy ngoài (ngày)" khi `released`.
- `scripts/backup/make_backup.py` (generator: tham số playlist, đích tên bộ kinh, bảng sha từ VM — chuyển từ `~/.local/share/auto-short/backup/make-kdt-backup.py`) + `scripts/backup/backup.template.ps1` (chuyển từ `kdt-backup.template.ps1`, giữ mọi hành vi hiện có: `-Dest`, `-SkipDoc`, `-Have`, `-ThumbsOnly`, `-NoVertical`, tải tiếp, kiểm sha, thumbnail) + bước cuối G6: gọi `/backup` cho mỗi file sha khớp, in danh sách tập đủ điều kiện + GB, hỏi một lần (y/N) rồi gọi `/release`; `-Release` không hỏi, `-NoRelease` chỉ xác nhận. Script không tự xóa gì trên 3090.

## Phải giữ nguyên

- Route / hành vi hiện có: tải HD / dọc, "Dọn video nguồn" (archive), enhance cho tập chưa `released`, render tập có HD, theme index (đã xử lý "HD deleted; trust the recorded sha"), ghép chủ đề.
- Không đụng transcript, AI, Short đã render, bài đăng, thumbnail, cờ "Đã đăng".

## Code bị thay / xóa

- Không có trong `src/` (chỉ thêm). Ngoài repo: `~/.local/share/auto-short/backup/make-kdt-backup.py` + template được thay bằng `scripts/backup/` (ORCHESTRATOR xóa bản ngoài repo sau khi sinh script mới chạy được).

## Acceptance Criteria

1. `/backup` chỉ nhận sha256 bằng sha file hiện có (HD: `enhance.json` + kích thước; dọc: sha thật, cache); sai sha / không có file / id lạ → từ chối, không ghi.
2. `/release` xóa đúng `source_hd.mp4` + `full/vertical.mp4` khi cả hai (cái đang có) đã xác nhận với sha hiện tại; thiếu xác nhận, sha đổi sau xác nhận, job / lease enhance đang chạy → từ chối, không xóa gì; chưa có bản dọc → từ chối trừ `allow_no_vertical`. Ghi `released_at`, sha đã xóa.
3. Sau release: render key Short đã có không đổi (không stale); không job tự render lại / tự enhance / tự dựng dọc cho tập; render tay → lỗi rõ "HD đã chuyển ra máy ngoài"; `GET` episode / playlist trả `released`, không link HD / dọc; `.kt` dùng trạng thái của video gốc.
4. Transcript, `clips`, `titles`, Short, bài đăng, theme index của tập không đổi (so file trước / sau trong test).
5. Script: generator sinh `.ps1` với tham số playlist; template giữ hành vi cũ; bước xác nhận / giải phóng gọi đúng route, hỏi một lần, `-Release` / `-NoRelease`; tên `[HD Mobile]` + đổi tên `[HD Dọc]` cũ. (Kiểm bằng test Python trên nội dung sinh ra + ORCHESTRATOR chạy PowerShell `pwsh` nếu có; nếu không có `pwsh` thì ghi rõ chưa chạy.)

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_hd_backup.py -q` + test hiện có của module đã sửa — AC1–AC5.
- Full suite (ORCHESTRATOR).
- Chạy thật trên **bản sao** một tập Kinh Địa Tạng (thư mục work / output tạm, config trỏ vào đó): confirm → release → render tay bị từ chối, Short cũ vẫn current (ORCHESTRATOR).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API nội bộ web (route mới) và xóa dữ liệu → manual test là gate trước integration.

- [ ] 3090: chạy script mới với `-NoRelease` (chỉ xác nhận), xem danh sách tập đủ điều kiện.
- [ ] Giải phóng 1 tập, kiểm web hiện "HD đã chuyển ra máy ngoài", Short của tập vẫn tải được, không job lạ.

## Result

- Main changes: `review/backup.py` (confirm / release / vertical_sha cache / view, `backup.json`); routes `POST /api/episodes/{id}/backup`, `/release`; `enhance.json released` → `effective_source` None, render Short / khai thị / bản dọc từ chối "HD đã chuyển ra máy ngoài", auto re-render (`_release_hd`), auto vertical, enhance redo / bật lại bỏ qua tập released; view episode / playlist thêm `released`, `app.js` hiện "HD đã chuyển ra máy ngoài (ngày)"; `scripts/backup/` (generator tham số playlist / bộ kinh, template giữ hành vi cũ + bước G6, tên `[HD Mobile]` + đổi tên `[HD Dọc]` cũ).
- Tests: `tests/test_hd_backup.py` 17 test (AC1–AC5, AC4 so byte transcript / clips / titles / Short / manifest); targeted module 280 passed; full suite 2505 passed, 1 failed `test_prepare_parallel_cp829.py::test_lower_thread_priority_is_per_thread_and_inherited_by_children` (`assert 19 == 10`, chạy riêng 5/5 pass, không thuộc phạm vi HD1a — là test chập chờn ghi trong current-state); `node --check app.js` OK. **Chưa chạy** `.ps1` (VM không có PowerShell) → manual test 3090 là gate.
- Chạy thật trên bản sao (`uuymFxiObZE`, file nhỏ chép thật, media hard link): release trước xác nhận / sha sai / thiếu xác nhận dọc → từ chối; đủ → giải phóng 3,0 GB trong bản sao, file thật còn nguyên; render tập + `.kt` sau đó → từ chối; transcript / clips / titles / manifest không đổi. Generator thật: `backup.ps1` 93 HD + 41 Doc sha256 (`~/.local/share/auto-short/backup-hd1/`).
- Diff + / − (app, test): app +331 / −2 (gồm `backup.py` +213), test +360, scripts ≈ +198 / −57.
- Helper mới (đã tìm, lý do không tái dùng): `review/backup.py` (không có code xác nhận / giải phóng; `archive.py` chỉ xóa `source.*` — tái dùng mẫu kiểm job + `submit_lock`), `enhance.state.is_released`, PS `Post-Json`, `Rename-LegacyMobile`.
- Review: ORCHESTRATOR — thứ tự ghi trước / xóa sau; xóa thêm hard link `<id>.kt/source_hd.mp4` (cùng file, không xóa thì không giải phóng được) chấp nhận; ghép chủ đề vẫn tải lại bản gốc khi thiếu file (hành vi cũ; nguồn HD thuộc HD1b G5).
- Important findings / decisions: script chỉ đề nghị giải phóng tập đã xác nhận cả ngang lẫn dọc; không gửi `allow_no_vertical`.
- Known limitations: `backup.json` khóa trong process (web một process); 52 tập Kinh Địa Tạng chưa có bản dọc → chưa giải phóng được tới khi tạo bản dọc.
- PR: #144
