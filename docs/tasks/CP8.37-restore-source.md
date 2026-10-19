# Task: CP8.37 — Khôi phục video nguồn của tập đã dọn

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol, high)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-19 “về việc khôi phục nguồn tôi đồng ý chức năng khôi phục nguồn” (đề xuất của ORCHESTRATOR: nút “Khôi phục nguồn” tải lại video gốc, mở khóa để sửa tiêu đề / render lại)
- Parallel group: —
- Owned paths: `src/auto_short/review/archive.py` (thêm restore), `src/auto_short/web/storage.py` (chỉ `complete_since` tính cả mốc khôi phục), `src/auto_short/web/app.py` (route + job wiring), `src/auto_short/web/static/app.js` / trang tập (nút + trạng thái), tests restore mới + tests storage liên quan, `docs/decisions/CP8.3-web-contract.md` (W9 + W7 route, header), contract này
- Dependencies: TC3.1 kho `work/_theme_sources` (đã merge #98)
- Base commit / branch: `bf38297` / `feature/cp8.37-restore-source`, worktree `/home/ntnghia/youtube-auto-short-restore`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-19; route mới nằm trong phạm vi đã duyệt)
- Implementation authorized: YES

## Goal

Tập đã dọn nguồn (archived, `archive.json`) có nút **“Khôi phục nguồn”**: hệ thống lấy lại đúng video gốc (byte giống hệt bản ingest), bỏ trạng thái archived của mọi phần của video (Short + khai thị) → sửa tiêu đề, khôi phục Short, render lại dùng được như trước khi dọn. Đo 2026-10-19: 13/13 video tải lại trong kho TC3.1 trùng sha256 ingest.

## Scope

- In scope: hàm `restore_source(episode_id, config, *, downloader, …)`; job làn `prepare` (YouTube chặn → chờ như FIX-youtube-botcheck-wait, kiểm ổ W9); route `POST /api/episodes/{id}/restore-source` (202 job / 200 job đang có / 409 không archived / 422 không khôi phục được); nút trên trang tập (chỗ hiện thông báo “đã dọn video nguồn”) + trạng thái job; giữ nguồn sau khôi phục không bị tự dọn ngay.
- Out of scope: chạy lại pipeline / AI, đổi luật dọn tay, video nguồn local, TC1–TC3.

## Authority / key decisions

- Chỉ khôi phục khi **sha256 (và kích thước) bằng `manifest.json` `source`** của workspace: lấy từ kho `work/_theme_sources/<video>/` nếu có (hard link, không tốn ổ), không thì tải bằng downloader ingest vào thư mục tạm trong workspace rồi kiểm; lệch → lỗi “video tải lại khác bản gốc; không khôi phục được (xóa tập rồi chạy lại)”, không ghi gì. Đặt file đúng `manifest.source.path`; xong mới xóa `archive.json`. Video có `.kt`: khôi phục cả hai phần đang archived (mỗi phần theo manifest của nó; cùng sha thì dùng chung file nguồn).
- Mốc khôi phục: ghi `work/<id>/restored.json` {restored_at}; `complete_since` (storage) lấy max cả mốc này → tự dọn chỉ chạy sau ân hạn (`auto_archive_grace_minutes`) tính từ lúc khôi phục.
- CP8.32 K2 sweep (xóa `source.*` của tập archived) không đụng vì tập không còn archived; thứ tự: đặt file → xóa archive.json trong cùng lock của runner / submit_lock như `auto_archive_pass` để sweep / auto-archive không chen giữa.

## Implementation approach

- Theo mẫu `render/full.fetch_original` + `VerticalTarget` (bước làn prepare, `YoutubeWait`) và `archive_source` (lock, log); tái dùng `theme_render.sources.cached_source`.

## Acceptance Criteria

1. Tập archived + kho có nguồn khớp sha → khôi phục không tải; archive.json bị xóa; `check_not_archived` qua; sửa tiêu đề / render chạy được.
2. Không có trong kho → tải (downloader inject), khớp → như 1; lệch sha / kích thước → lỗi rõ, workspace không đổi.
3. Video có Short + `.kt` archived → cả hai được khôi phục.
4. Sau khôi phục, auto-archive không dọn lại trước ân hạn tính từ `restored_at`.
5. Route / job: 202, trùng → job cũ, 409 không archived, lỗi → job failed có message; YouTube chặn → chờ, không fail.
6. Full suite PASS; CP8.3 cập nhật.

## Required verification

- Tests restore mới + `tests/test_storage_suggest.py` + tests archive / vertical liên quan (ORCHESTRATOR chạy ngoài sandbox), full suite, framework-check, `git diff --check`.
- Chạy thật (ORCHESTRATOR, được HUMAN LEAD đồng ý): khôi phục một tập đã dọn có nguồn trong kho, sửa tiêu đề một Short, render.

## Manual test checklist (Tech Lead)

Thêm route HTTP (trong phạm vi HUMAN LEAD duyệt) → manual test là gate trước merge.

- [ ] Trên 8080: tập đã dọn → “Khôi phục nguồn” → sửa tiêu đề Short → render xong.

## Result

- Main changes: `restore_source` kiểm size + sha256 theo từng manifest trước khi ghi; cache TC3.1 hard link, thiếu cache thì downloader inject vào thư mục tạm; khôi phục mọi phần archived, dùng chung inode khi cùng nguồn. Đặt nguồn → `restored.json` tại lúc hoàn tất → bỏ cờ archive trong `submit_lock`, rollback khi ghi lỗi. Không đổi manifest / artifact pipeline. `complete_since` tính cả `restored_at`; auto-archive kiểm lại mốc dưới lock, sweep / callback dọn bản dọc tôn trọng job restore. Route + job prepare (duplicate giữa hai phần, YouTube wait, disk check, persistence/rebuild), nút / polling / trạng thái trên trang tập; cập nhật W7 / W9 và thông báo archived.
- Scope: xác nhận lúc bắt đầu branch `feature/cp8.37-restore-source`, HEAD `f4755a5`, tree sạch. Chỉ Owned paths; **không sửa `jobs.py`** (kind `restore_source` định nghĩa trong `web/app.py`, target tự khai báo `lane_steps`). Không thêm dependency, không mạng thật, không commit / push.
- Tests (2026-10-19, conda env `auto-short`, `PYTHONPATH=/home/ntnghia/youtube-auto-short-restore/src`):
  - PASS: 55 tests restore / storage, 10 HTTP cases deselected, 8.71 s. Lệnh: `/home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_restore_source_cp837.py tests/test_storage_suggest.py tests/test_storage_cp86.py -k 'not http and not storage_api and not auto_archive_after_grace and not old_render_recommended and not disk_status_and_submit_block and not archive_route_and_archived_episode_rules and not archive_refused_while_job_active' -x --tb=short`. Có test ffmpeg thật: restore → khôi phục Short / sửa title → render; kiểm mismatch không đổi workspace, hai phần, rollback, ân hạn sau tải dài, stale auto-archive snapshot, route status qua endpoint trực tiếp, restart và YouTube wait/retry.
  - PASS: 7 regression vertical, 18 deselected, 4.35 s: `tests/test_web_vertical_cp832.py -k 'effective_source_rules or run_vertical_from_original_real_encode_and_reuse or refetch_wrong_video_is_refused_and_cleaned or refetch_different_bytes_warns_but_is_used or auto_archive_waits_for_a_vertical_job or ac5_short_jobs_start_before_queued_verticals or vertical_fetch_prefetch_is_bounded' -x --tb=short` (cùng Python / PYTHONPATH trên).
  - PASS: chạy lại 2 test `publication_uses_submit_lock` / `route_statuses_duplicate` sau bổ sung kiểm callback dọn cũ + chặn bản dọc khi đang restore.
  - PASS: `node --check src/auto_short/web/static/app.js`, `node scripts/framework-check.mjs`, `git diff --check`.
  - **Chưa PASS HTTP / full suite**: lệnh required không lọc (`tests/test_restore_source_cp837.py tests/test_storage_suggest.py tests/test_storage_cp86.py -x --tb=short`) timeout 45 s (exit 124) khi tới TestClient HTTP trong sandbox. Full suite `python -m pytest -q -n auto -x --tb=short` cũng timeout 45 s; log `/tmp/cp837-full-suite.log` có F/E trước timeout, không có traceback cuối để phân loại, không suy ra tất cả chỉ do sandbox. ORCHESTRATOR cần chạy HTTP / full suite ngoài sandbox và xử lý findings; không claim AC6 PASS.
- Review: implementation hoàn tất để ORCHESTRATOR review; task giữ IN_PROGRESS vì required verification / manual test trên 8080 chưa hoàn tất. Manual restore dữ liệu thật, sửa title và render do ORCHESTRATOR thực hiện theo authorization ở trên.
- PR: chưa; không commit / push.
