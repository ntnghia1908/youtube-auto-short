# Task: FIX-process-archived-restore — "Xử lý" tập đã dọn tự khôi phục nguồn từ kho rồi chạy tiếp

## Status / Approval

- Status: IN_PROGRESS
- Type: FIX
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29 handoff: "FIX 'Xử lý tập đã dọn tự khôi phục nguồn từ kho'"
- Owned paths: `src/auto_short/web/context.py` (`queue_video`), `src/auto_short/web/app.py` (`RestoreSourceTarget` thêm bước xếp job sau khôi phục), `src/auto_short/web/playlists.py` (action cho tập đã dọn), `src/auto_short/web/static/app.js` (chỉ nhãn / confirm nút), test tương ứng (`tests/test_web_*restore*`, `tests/test_web_playlist*`), contract này
- Base commit / branch: `720dc10` (`origin/main`) / `fix/process-archived-restore`
- Human Lead approval: APPROVED 2026-10-29 (G1 = cả hai; "Duyệt, làm sau THUMB2")
- Implementation authorized: YES

## Hiện trạng (2026-10-29, đọc code)

- `queue_video` (`web/context.py:320`): kind có id đã dọn → 409 "đã dọn video nguồn; bấm Khôi phục nguồn"; không thử kho.
- Hàng bộ kinh: tập đã dọn (RENDERED / COMPLETE) không có nút (`web/playlists.py:58`, `:447`).
- Thêm khai thị cho tập đã dọn: chạy được nhưng tải lại nguồn riêng vào `work/<vid>.kt/`; Short vẫn ở trạng thái đã dọn.

## Goal

Bấm "Xử lý" (Short / khai thị) cho tập đã dọn → web tự xếp job "Khôi phục nguồn" (kho 3090 trước, YouTube sau, kiểm sha: `restore_source` hiện có), xong thì xếp tiếp các kind đã chọn; không bắt bấm "Khôi phục nguồn" trước, không tải nguồn hai lần.

## Scope

- `queue_video`: nhánh đã dọn → submit / nhập vào job `KIND_RESTORE_SOURCE` của `hd_owner` (logic busy / join như `routes/episodes.py:555-568`, như SRC3 `_defer_edit`), ghi kèm kind + tham số cần xếp; trả 202 kèm trạng thái "đang lấy lại nguồn".
- `RestoreSourceTarget`: khôi phục thành công → xếp các job pipeline đã ghi kèm (kind, phút khai thị, vertical); thất bại / hủy → không xếp, lỗi hiện trên job khôi phục.
- Restart giữa chừng: job khôi phục kèm danh sách xếp sau được khôi phục như SRC3 edits.
- Hàng bộ kinh: tập đã dọn có nút "Xử lý" khi còn kind chưa có (ví dụ chưa có khai thị) và "Xử lý lại" cho Short đã dọn (G1).
- Out of scope: đổi `restore_source`, chính sách dọn (`auto_archive`), Y2 bản dọc.

## Quyết định

- G1 (HUMAN LEAD 2026-10-29): **cả hai** — (a) thêm khai thị cho tập Short đã dọn; (b) "Xử lý lại" Short của tập đã dọn.

## Acceptance Criteria

1. Tập đã dọn + "Xử lý" → 1 job khôi phục (không 409), xong → job kind đã chọn được xếp và chạy với nguồn đã khôi phục (không tải thêm); bấm lặp → nhập vào job khôi phục đang có.
2. Khôi phục lỗi / hủy → không xếp job sau, lỗi rõ ràng; restart → danh sách xếp sau còn nguyên.
3. Tập chưa dọn: hành vi `queue_video` không đổi.
4. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

- Test targeted (job runner giả, store giả) + TestClient (ORCHESTRATOR); full suite `-n auto`.
- Chạy thật trên 8080: 1 tập đã dọn có bản trên kho → "Xử lý" khai thị → log thấy lấy từ kho, không gọi YouTube.

## Result

- IMPLEMENTER hoàn tất code trong Owned paths; chờ ORCHESTRATOR review và verification còn lại. Giữ `IN_PROGRESS`: chưa đủ điều kiện READY task vì TestClient / full suite / chạy thật chưa được xác minh trong sandbox này.
- Bootstrap: đọc toàn bộ contract, AGENTS.md gốc, project-profile, current-state, workflow / execution-profiles; `find src tests docs -name AGENTS.md -print` không có rule subtree bổ sung. Branch `fix/process-archived-restore`, HEAD `03db832`. Không commit / push / PR, không agent khác, không mạng thật.
- File đổi: `web/context.py` nhận / nhập yêu cầu từng kind vào restore của owner; giữ phút, series, số tập, vertical, prepare_only. `web/app.py` lưu / rebuild danh sách đó và chuyển giao ở bước cuối sau restore + edits; lỗi / hủy không chuyển giao. `web/playlists.py` mở action cho tập đã dọn; `web/static/app.js` chỉ nhãn theo kind đang chọn và confirm lấy lại nguồn. Test mới: `tests/test_web_process_restore.py`.
- Chi tiết chuyển giao: giữ reservation restore active trong snapshot, dùng `queue_video` với `_restored_job` nội bộ dưới `submit_lock` rồi runner lock. Riêng pipeline cùng khóa restore dùng `_enqueue_locked` có sẵn để tránh bị `submit` trả lại restore. Restart lúc đã xếp child: restore còn trong snapshot sẽ dựng lại child cùng khóa bị runner bỏ trùng; child khác khóa được nhập như bình thường. Có test checkpoint này ở cả serial / lanes.

| AC | Test / bằng chứng |
|---|---|
| 1 | `test_process_restore_store_join_and_restart`: store giả, 1 fetch, downloader YouTube phải fail nếu bị gọi; gọi ingest khai thị thật với probe giả để chứng minh K5 dùng lại nguồn; nhập kind / bấm lặp, phút / series / số tập / vertical. `test_manual_restore_accepts_pipeline_while_downloading`: nhập restore tay khi đang tải, có / không edit SRC3. `test_playlist_archived_actions`: action + ẩn khi đang chạy; JS syntax PASS. |
| 2 | `test_process_restore_store_join_and_restart`: checkpoint queued / restored / handoff. `test_process_restore_failure_cancel_and_normal`: SHA sai / hủy → không pipeline, lỗi có tiền tố khôi phục; prepare_only giữ nguyên qua chuyển giao. |
| 3 | `test_process_restore_failure_cancel_and_normal`: tập chưa dọn vẫn queue pipeline trực tiếp, không restore. Hồi quy SRC3 / CP8.37 / playlist thuần cũng PASS. |
| 4 | Targeted, framework-check, diff-check PASS; full suite chưa chạy, không claim AC4 PASS. |

Helper mới và tái dùng:

- Đã tìm bằng `rg -n 'def .*queue|def .*defer|def restore|def .*dispatch'` trong context.py, app.py, routes/episode_edit.py, jobs.py; đọc `_defer_edit`, `restore_job`, `restore_parts`, `RestoreSourceTarget`, `queue_video`, `submit`, `_enqueue_locked`, hook `on_finished`.
- Mới: `RestoreSourceTarget.dispatch` là bước cuối theo lanes / serial, và closure `_queue_restored` nối danh sách đã lưu với `queue_video` dưới khóa. Không dùng `on_finished` vì runner chỉ gọi hook này cho `EPISODE_KINDS`, không có restore; không đổi jobs.py ngoài ownership. `_defer_edit` chỉ áp mutation Short, không xếp pipeline / giữ các tham số trên, nên tái dùng pattern persistence, không sao chép mutation.
- Không thêm module / dependency / helper test dùng chung mới; tái dùng fixture / fake / endpoint helpers hiện có.

Dòng thêm / xóa (so HEAD, `git diff --numstat`; test mới đo bằng `git diff --no-index --numstat /dev/null tests/test_web_process_restore.py`): ứng dụng **+131 / −52**, test **+192 / −0**; contract không tính vào hai nhóm này.

Verification đã chạy:

- Prefix pytest: `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-archived/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`; lệnh cuối có `timeout 240`, mọi lệnh < 5 phút.
- `-q -x --tb=short tests/test_web_process_restore.py tests/test_src3_auto_restore.py tests/test_restore_source_cp837.py tests/test_web_playlist_groups_cp813.py::test_group_table_g1 tests/test_web_playlist_groups_cp813.py::test_view_groups_counts_and_summary tests/test_playlist_cp87.py::test_classify_url tests/test_playlist_cp87.py::test_classify_url_refused tests/test_playlist_cp87.py::test_build_document_and_episode_number tests/test_playlist_cp87.py::test_episode_complete_predicate -k 'not http_auth'` → **139 passed, 1 deselected** (27.76 s).
- Sau sửa cuối cho duplicate lúc restore đã đóng cửa edit: `-q -x --tb=short tests/test_web_process_restore.py` → **28 passed** (6.12 s).
- `node --check src/auto_short/web/static/app.js` → PASS.
- `node scripts/framework-check.mjs` → PASS.
- `git diff --check` → PASS.
- Một lệnh playlist bổ sung đã chọn nhầm các ca dùng TestClient (`test_import_playlist_lists_without_downloading`, `test_list_errors_and_timeout`, `test_episode_in_two_playlists_uses_first_by_id`, `test_playlist_hashtags_saved_during_refresh_survive`); đã ngắt bằng Ctrl-C, exit 130, không tính PASS. Danh sách không cần socket ở trên đã chạy lại thành công.

Verification chưa chạy / ORCHESTRATOR tiếp nhận:

- `python -m pytest -q -n auto` (full suite), các ca TestClient (bao gồm `test_http_auth_and_restore` đã deselect), và kiểm nhãn / confirm trong trình duyệt. Sandbox không có socket loopback; không yêu cầu / dùng danger-full-access.
- Chạy thật 8080 với một tập đã dọn có bản kho: Xử lý khai thị → log lấy kho, không gọi YouTube. IMPLEMENTER không gọi mạng thật theo handoff.
- ORCHESTRATOR (2026-10-29): review diff (inventory ⊆ Owned paths + 2 test cũ khẳng định hành vi bị đổi). Codex 110.615 tokens, effort medium, 1 vòng.
  - Test cũ khẳng định "tập đã dọn → 409" (hành vi contract này thay): `tests/test_storage_cp86.py::test_archive_route_and_archived_episode_rules` (bỏ ca gửi lại URL giữa test, trỏ sang `tests/test_web_process_restore.py`), `tests/test_web_khaithi_cp89.py::test_submit_duplicate_and_archived` (archive.json giả không khôi phục được → 422 cho mọi kind).
  - Targeted + TestClient: `tests/test_web_process_restore.py tests/test_restore_source_cp837.py tests/test_src3_auto_restore.py tests/test_playlist_cp87.py tests/test_web_playlist_groups_cp813.py` **170 passed**; `tests/test_storage_cp86.py tests/test_web_khaithi_cp89.py tests/test_web_process_restore.py` **73 passed**.
  - Full suite `-n auto`: **3565 passed, 1 failed, 1 skipped** — `tests/test_web_packaging.py::test_music_registered_endpoints_socket_free` (ngoài phạm vi, chạy riêng 2 lần PASS; lần trước `test_theme_render.py::test_description_refresh_on_cache_hit_without_encoding` cũng chập chờn, riêng PASS).
  - Còn: chạy thật 8080 (1 tập đã dọn có bản trên kho → "Xử lý" khai thị → log lấy từ kho) khi làn rảnh.
  - ORCHESTRATOR chạy thật 8080 (2026-10-29 20:44, nhánh cục bộ `test/8080-kti1-fix` = KTI1 + FIX `275757b`): VLT tập 51 `n82hmHnlN4Y` (đã dọn nguồn, có Short, chưa có khai thị) → `POST /api/episodes` kinds `["khaithi"]` 4–7 phút (như nút "Xử lý") → **202**, job `restore_source` (không 409) → log `review: restored source n82hmHnlN4Y (download)`, **không có dòng `[youtube] n82hmHnlN4Y`** (lấy từ kho 3090) → pipeline khai thị tự xếp, `ingest: reused the source of n82hmHnlN4Y (hardlink, no download)` → 6/6 clip, post 6 Short. AC chạy thật **PASS**. Chưa thử "Xử lý lại" Short của tập đã dọn trên dữ liệu thật (chỉ test tự động; tránh AI chọn lại đoạn của Short đã đăng).
