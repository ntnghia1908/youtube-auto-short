# Task: SHO1b — sửa / ghép Short đã giải phóng lên kho 3090 + Bộ nhớ

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, tính năng mới chạm render / job / ghép / kho); quota 2026-10-26: 5 giờ 12 %, tuần 2 %; dự phòng subagent `implementer` (Sonnet). Test web (TestClient), HTTP server và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SHO1-short-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-26 "duyệt tất cả"), G5 + G7 + phần ghép Short của G6; sửa đổi G1 "Short sửa → bản mới" (HUMAN LEAD 2026-10-26 chọn "Lưu bản mới, giữ bản cũ")
- Parallel group: —
- Owned paths: `tools/store/store.py` (chỉ quy tắc bản mới của kind `short`); `src/auto_short/store/shorts.py` (lấy lại, mượn, snapshot Bộ nhớ); `src/auto_short/store/client.py` (chỉ khi cần cho `fetch` Short; và `put`: kind `short` khác sha → gửi PUT để kho tạo bản `(rN)`, kind khác giữ `StoreMismatch` — HUMAN LEAD duyệt 2026-10-26); `src/auto_short/render/stage.py` (chỉ điểm móc lấy lại ở `run_render`); `src/auto_short/web/jobs.py` (chỉ `add_short_target` → `StoreWaitJob`); `src/auto_short/web/app.py` (`store_retry_pass`, snapshot Bộ nhớ từ `shorts_offload_pass`); `src/auto_short/web/compilations.py`; `src/auto_short/web/storage.py` (snapshot + `report`); `src/auto_short/web/static/app.js` (dòng Bộ nhớ); `tests/test_store_server.py`, `tests/test_store_shorts.py`, `tests/test_store_shorts_edit.py` (mới), test compilation / storage hiện có liên quan (chỉ thêm test); `docs/decisions/SHO1-short-store-3090.md` (dòng sửa đổi G1); contract này
- Dependencies: SHO1a (#174, đã merge), HD2a, HD2b, FIX-store-wait-persist (đã merge); không dependency mới
- Base commit / branch: `main` `1ff1330` (sau #174) / `feature/sho1b-short-store-edit`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-26 "duyệt tất cả" (SHO1) + chọn "Lưu bản mới, giữ bản cũ"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi quy tắc API kho (kind `short` nhận bản mới thay vì 409), luồng VM ↔ 3090 mới (lấy lại khi sửa, mượn khi ghép), job đợi kho mới.

## Goal

Tập đã giải phóng Short lên 3090 vẫn sửa được như tập thường: sửa tiêu đề / cắt / xóa / khôi phục / thêm Short → job tự lấy lại mọi Short từ kho rồi dựng lại đúng Short đổi; video ghép dùng được Short đã giải phóng; tab Bộ nhớ hiện Short trên 3090 và hàng chờ đẩy. Sau khi merge, bật `offload_shorts` trên 8080 không còn tập nào "giải phóng mà không sửa được".

## Scope

- In scope:
  - **B1 kho — bản mới của Short (sửa đổi G1)**: `PUT /files/<video_id>/short/<clip>` khi khóa đã có file **khác sha** → không 409 nữa: ghi file mới tên `… - k03 (r2).mp4` (`(r3)` … số nhỏ nhất chưa dùng), dòng `index-short.csv` của khóa trỏ sang file mới; file cũ **giữ nguyên trên đĩa và trong `SHA256SUMS.txt`** (không xóa qua API). `HEAD` / `GET` trả bản hiện hành. Cùng sha bản hiện hành → 200 như cũ. Kind `hd` / `vertical` / `source` giữ 409. Ghi tạm + đổi tên nguyên tử, kiểm sha khi `PUT` như cũ.
  - **B2 lấy lại khi sửa (G5)**: helper trong `store/shorts.py` (ví dụ `restore_released(config, episode_id)`), gọi ở đầu `run_render` (sau kiểm "archived", trước nhánh HD của HD2a): phần có `output/<episode>/store.json` `released` → với mỗi clip vắng trên VM: `client.fetch(…, "short", …, clip=…)` vào đúng chỗ Short trên VM, kiểm sha = `store.json`, đặt lại mtime = `mtime_ns` đã ghi (vân tay ARC1 không đổi); đủ mọi clip → xóa `store.json`, rồi render như bình thường (T5 tái dùng Short không đổi, chỉ Short sửa được dựng lại). `[store]` tắt → `RenderError` rõ ("Short của tập đang ở kho 3090; bật [store] để sửa"); kho tắt / thiếu / lệch sha → `StoreWait` (`WAIT_PREFIX` "đợi 3090: …"); file đã lấy được giữ lại (file VM thắng record), lần sau chỉ lấy phần còn thiếu. Chỉ phần (`<id>` hoặc `<id>.kt`) mà job render.
  - **B3 đợi 3090 + chạy tiếp**: `add_short_target` đổi `StoreWait` → `StoreWaitJob` như `render_target`. `store_retry_pass` nhận thêm job render / thêm Short đang "đợi 3090" vì Short: kho trả lời và `HEAD` mọi clip đã giải phóng khớp sha → submit lại `KIND_RENDER` (`render_target`; job thêm Short không gọi lại AI — tiêu đề đã ghi `review.json`). Giữ nguyên nhánh HD hiện có; lưu / khôi phục khi restart (FIX-store-wait-persist) phải đúng cho cả hai.
  - **B4 ghép Short (G6)**: `compilations.py` liệt kê Short qua `short_locations` (Short đã giải phóng vẫn hiện ở Yêu thích / chọn được), thời lượng lấy từ `render_manifest` khi file vắng (không ffprobe file vắng). Job `compilation` mượn tạm Short trên kho (mẫu `store/borrow.py`: tải vào thư mục tạm dưới thư mục bộ kinh, kiểm sha, xóa sau khi ghép xong / lỗi, không đụng `store.json`); kho tắt / lệch → job `failed` "Short … đang ở kho 3090, 3090 không trả lời — bấm Ghép lại sau" (quyết định cục bộ: không thêm job đợi cho ghép). `keep_favorites` (xóa tập có Short yêu thích, G11): Short đã giải phóng → tải từ kho vào bản giữ (kiểm sha); không tải được → hủy xóa tập với thông báo rõ, không mất bản yêu thích. Temp mượn nằm trong `store_temp_files` để dọn sót.
  - **B5 Bộ nhớ (G7)**: vòng `shorts_offload_pass` cập nhật snapshot (mẫu `update_offload`): "Short trên 3090: N tập, X GB" (đếm từ `store.json` trên VM, không gọi kho), hàng chờ: đủ điều kiện / còn chờ ngày (mọi Short đã đăng, chưa đủ grace) / lỗi + lỗi cuối. `report()` trả khối `shorts_offload`; `app.js` hiện một dòng như `#vertical-offload`, chỉ khi cờ bật hoặc có tập đã giải phóng.
- Out of scope: bật cờ trên 8080 (HUMAN LEAD sau merge + chép `store.py` lên 3090); xóa file trên 3090 (kể cả bản cũ `(rN)`); nút bấm tay; đổi điều kiện G2 / luồng đẩy G3 của SHO1a (ngoài việc đẩy lại gặp B1); bản dọc / HD / nguồn.

## Authority / key decisions

- SHO1 G5, G6 (ghép), G7, G8 ACCEPTED; sửa đổi G1 (B1) HUMAN LEAD 2026-10-26. HD2 G1 "không xóa qua API" giữ. HD2a G4 / FIX-store-wait-persist: mẫu đợi 3090.
- Quyết định cục bộ (S1 trong S2 này): ghép Short gặp kho tắt → `failed` có thông báo, không đợi tự động (người dùng bấm "Ghép lại").
- `publish.py`: dấu "Đã đăng" của Short dựng lại thành cũ (sha khác) → tập không còn "Xong" tới khi đăng lại — đúng G5, không đổi.

## Implementation approach

- Tái dùng của SHO1a: `store/shorts.py` (đọc `store.json`, tên đích qua `store/backup.py` `_destination`, `_sha256_file`, `atomic_write_json`), `web/episodes.py` `short_locations` / `StoredShort` / `short_files`, `StoreClient.fetch(…, clip=)`; của HD2a: `store/borrow.py` (`WAIT_PREFIX`, `_FETCH` / đếm mượn), `render.stage.StoreWait`, `web/jobs.py` `StoreWaitJob`, `app.py` `store_retry_pass`.
- Kho: tìm tên `(rN)` trong thư mục bộ kinh dưới lock ghi hiện có; `index-short.csv` thay dòng của khóa (ghi nguyên tử như `_publish`).
- Lấy lại chạy trong job render (đã giữ khóa tập → vòng đẩy SHO1a bỏ qua tập bận); không thêm lock mới nếu không cần.

## Phải giữ nguyên

- `offload_shorts = false` và tập chưa giải phóng: render / ghép / xóa tập / Bộ nhớ như trước (không gọi kho).
- Kind `hd` / `vertical` / `source`: API + 409; `index.csv`, `danh-sach.csv`, `backup.ps1`; nhánh HD của `run_render` / `store_retry_pass`.
- SHO1a: xem / tải / ZIP / ARC1 của tập đã giải phóng; mọi test SHO1a, HD2a / HD2b, SRC1–SRC4, ARC1, CP8.2 T5, CP8.33 hiện có.

## Code bị thay / xóa

- `compilations.py`: hai chỗ dựng `files` từ `short_files` (liệt kê `clips`, `keep_favorites`) chuyển sang `short_locations` + mượn / tải; không giữ song song nhánh cũ.
- Kho: nhánh 409 "Existing file has a different sha256" không còn áp dụng cho kind `short` (thay bằng B1).

## Acceptance Criteria

1. B1: `PUT` Short khác sha cho khóa đã có → 200/201, file `(r2)` mới, `index-short.csv` trỏ file mới, file cũ + dòng `SHA256SUMS.txt` cũ còn; `HEAD` / `GET` trả bản mới; `PUT` lại cùng sha → 200 không thêm file; kind cũ vẫn 409.
2. B2: tập đã giải phóng (cả `<id>` và `<id>.kt`), sửa tiêu đề một Short → job lấy lại mọi Short (sha + mtime đúng), xóa `store.json`, chỉ Short sửa được encode lại (các Short khác tái dùng T5); `[store]` tắt → lỗi rõ, không đổi gì.
3. B2/B3: kho tắt khi sửa → job "đợi 3090: …", `render_manifest.json` / `store.json` không đổi; kho bật lại → `store_retry_pass` tự chạy lại và xong; restart web giữa lúc đợi → vẫn tự chạy lại; lấy dở (một phần clip) → lần sau chỉ lấy phần thiếu.
4. B3: thêm Short / xóa / khôi phục / cắt trên tập đã giải phóng đều đi qua B2; job thêm Short đợi 3090 chạy lại bằng render, không gọi AI lần hai.
5. Sau khi sửa và Short sửa được "Đã đăng" lại đủ grace: vòng đẩy SHO1a đẩy lại tập → kho lưu `(r2)` cho Short đổi, Short không đổi trả 200, VM giải phóng lại.
6. B4: Yêu thích liệt kê Short đã giải phóng; ghép có Short trên kho → video ghép đúng (mượn, temp bị xóa sau); kho tắt → job failed với thông báo, không còn temp; xóa tập có Short yêu thích đã giải phóng → bản giữ đúng sha; kho tắt → không xóa tập, báo rõ.
7. B5: `/api/storage` có `shorts_offload` (tập + byte đã giải phóng, đủ điều kiện / chờ ngày / lỗi); tab Bộ nhớ hiện dòng; báo cáo không gọi kho.
8. Cờ tắt / tập chưa giải phóng: không gọi kho; full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_shorts.py tests/test_store_shorts_edit.py` + test compilation / storage liên quan — AC 1–7 (test cần socket / TestClient: ORCHESTRATOR chạy ngoài sandbox).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 8.
- ORCHESTRATOR chạy thật (không bật cờ trên 8080), theo cách SHO1a: bản sao cô lập + kho tạm `tools/store/store.py` mới (cổng khác): giải phóng một tập có khai thị → sửa tiêu đề 1 Short → lấy lại + chỉ 1 Short encode lại; đánh dấu đăng + đẩy lại → `(r2)` trên kho tạm, file cũ còn; tắt kho → "đợi 3090" → bật → tự chạy lại; ghép một video có Short đã giải phóng; `/api/storage` có `shorts_offload`.

## Manual test checklist (Tech Lead)

Chạm public API kho (quy tắc bản mới kind `short`) và luồng dữ liệu VM ↔ 3090; không chạm security model (token / kênh cũ), không database. Sau khi merge, chép `store.py` lên 3090, bật `offload_shorts` trên 8080:

- [ ] Một tập đã giải phóng: phát / tải Short, "Tải cả hai"; tắt 3090 → báo "3090 đang tắt".
- [ ] Sửa tiêu đề một Short của tập đó → job chạy xong, Short mới đúng tiêu đề.
- [ ] Tab Bộ nhớ hiện "Short trên 3090: …".

## Result

- IMPLEMENTER vòng 2 (2026-10-26): **READY bàn giao ORCHESTRATOR** sau sửa `StoreClient.put()` đúng patch HUMAN LEAD đã duyệt; AC5 đã PASS. Giữ Status `IN_PROGRESS` để ORCHESTRATOR review / verify full suite, socket/TestClient và checklist kho tạm ngoài sandbox trước READY toàn task. Không commit / push / PR, không gọi agent khác / mạng thật, không thêm dependency. Vòng 2 tiếp tục từ WIP `7ea2f5c`; base toàn task `72154a0f302001c28e7e79a63cd3b87ff0505c70`, branch `feature/sho1b-short-store-edit`.
- **Boundary finding vòng 1 — đã xử lý**: `StoreClient.put()` từng chặn mọi file khác sha/size trước PUT, làm title/cut không đẩy lại được. HUMAN LEAD đã duyệt patch tối thiểu (bản duyệt `/home/ntnghia/.local/share/auto-short/handoff-sho1b/sho1b-client-short-put.patch`): cùng sha+size → return; khác byte mà kind `short` → tiếp tục PUT để server tạo `(rN)`; kind khác giữ `StoreMismatch`. Đã áp đúng patch, không cần helper ứng dụng mới. Test mới `test_put_existing_identity_short_revises_others_refuse` dùng transport giả tại `urlopen`, 4 kind × 3 trạng thái metadata (cùng / khác SHA / khác size), không thay test cũ.
- ORCHESTRATOR 2026-10-26: HUMAN LEAD **duyệt** mở `client.py` `put` theo patch đề xuất (đã ghi vào Owned paths); giao Codex vòng sửa.
- Main changes: server cấp revision nhỏ nhất chưa tồn tại, giữ media/checksum cũ, thay một dòng hiện hành qua CSV tạm + `os.replace`; restore đúng phần trước HD, tải thiếu qua fetch có kiểm sha rồi đặt mtime_ns, giữ phần đã tải khi chờ; thêm Short gặp chờ chuyển phần việc còn lại thành KIND_RENDER để dùng nguyên persistence/rebuild có sẵn; retry HEAD mọi clip trước submit, giữ nhánh HD. Ghép liệt kê vị trí chung, duration metadata khi vắng, mượn bản riêng và dọn bằng context; giữ yêu thích tải bản có kiểm sha và rollback khi xóa tập thất bại. Snapshot Bộ nhớ chỉ đọc metadata/stat trên VM; temp ghép được kiểm kê và bảo vệ trong lúc đang mượn.
- Helper mới (đã tìm bằng `rg -n 'def (fetch|short_locations|short_files|borrow_hd|render_target|restore_released|fetch_released|borrow_short|offload_snapshot|update_shorts_offload)' src/auto_short/store src/auto_short/web src/auto_short/render`):
  - `fetch_released`: bọc `StoreClient.fetch(..., clip=)` hiện có + khôi phục mtime_ns; fetch cũ không đặt timestamp ARC1. Dùng chung cho restore / mượn / giữ yêu thích.
  - `restore_released`: vòng đời lấy lại phần Short + xóa record khi đủ; `borrow_hd` xóa bản mượn sau job, không phù hợp với việc lấy lại vĩnh viễn để sửa. Dùng lại `short_locations` / `StoredShort`, không viết parser record khác.
  - `borrow_short`: context bản riêng dưới thư mục bộ kinh, dùng lại `_BORROWED` / `_LOCK` và verified fetch. `borrow_hd` cố định tên/đích HD nên không dùng trực tiếp cho nhiều clip; bản riêng không cần khóa `_FETCH` hay chia sẻ file giữa job.
  - `offload_snapshot`: dùng lại `episode_sizes` / `short_offload_plan` và metadata vị trí, bổ sung byte đã giải phóng + chờ grace; snapshot bản dọc không chứa thông tin này.
  - `StorageCache.update_shorts_offload`: cùng mẫu `update_offload`, khối trạng thái riêng của Short; giữ snapshot bản dọc hiện hành.
  - Fixture mới `memory_store` trong test mới: ghép real `StoreClient` với `test_store_server.request` (HTTP parser thực qua memory); cần kiểm toàn tuyến PUT/HEAD/GET/fetch và SHA thực, không mở socket.
- Chỉ đổi **một assertion cũ** ở `test_short_put_index_range_and_conflict`: 409 → 422 cho request cố tình khai SHA sai với body. Sau sửa đổi G1, SHA khác được nhận để kiểm body nên phải trả 422; thêm test revision thực, vẫn giữ test alias 409 và các kind cũ 409. Không sửa test để che lỗi AC5.

| AC | Test / bằng chứng | Kết quả |
|---|---|---|
| 1 | `test_short_revisions_keep_history_and_current_index`; `test_short_put_index_range_and_conflict`; `test_put_stream_hash_atomic_publish` (các test kind cũ trong server) | PASS server: bản mới, HEAD/GET hiện hành, checksum và byte cũ, retry cùng sha, khởi tạo lại kho |
| 2 | `test_restore_released_exact_metadata_and_partial_retry`; `test_restore_store_disabled_and_local_file_wins`; `test_released_edits_reuse_unchanged_short_and_reoffload` | PASS restore cả `<id>` / `<id>.kt`, sha/mtime, chỉ encode Short đổi; title/cut re-offload đã PASS vòng 2 |
| 3 | `test_restore_released_exact_metadata_and_partial_retry`; `test_short_wait_persists_and_retries_render_without_ai`; regression `tests/test_store_wait_persist.py` | PASS: down/missing/SHA/corrupt, giữ record/manifest, tiếp tục phần thiếu, restart cả serial/lanes |
| 4 | `test_released_edits_reuse_unchanged_short_and_reoffload` (title/cut/reject/restore/add); `test_short_wait_persists_and_retries_render_without_ai` | PASS phần render và reuse; thêm Short retry/restart không gọi AI lần hai |
| 5 | `test_released_edits_reuse_unchanged_short_and_reoffload[title/cut]`; `test_put_existing_identity_short_revises_others_refuse`; `test_short_revisions_keep_history_and_current_index` | PASS vòng 2: sửa → đăng lại → đủ grace → kho `(r2)`, Short không đổi không thêm bản; sha/size khác chỉ được gửi PUT với kind Short |
| 6 | `test_compilation_released_clips_borrow_and_cleanup`; `test_keep_released_favorites_or_abort_delete`; `test_real_compilation_mixes_released_and_local_short` | PASS: liệt kê, duration không probe file vắng, video thật đúng thứ tự/thời lượng, lỗi fetch/assemble không sót temp, hủy xóa + rollback sau tải dở |
| 7 | `test_short_storage_snapshot_and_orphan_temp_sweep`; kiểm cú pháp JS | PASS API gọi trực tiếp không socket: eligible/chờ ngày/lỗi/byte/tập, không gọi kho; UI chưa test trình duyệt |
| 8 | test default-off SHO1a, regression HD/store-wait/storage/compilation + render/CP9/client | Targeted PASS; full suite chưa chạy trong sandbox |

Lịch sử verification vòng 1 (lỗi AC5 đã xử lý; kết quả hiện hành vòng 2 ở cuối; mọi pytest dùng đúng prefix `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`; các lượt cuối bọc `timeout 240s`):

1. `-q tests/test_store_server.py tests/test_store_shorts.py tests/test_store_shorts_edit.py -k 'not (released_edits and (title or cut))' -x --tb=short`: **166 passed, 2 deselected**, 19.97 s (hai case title/cut bị chặn AC5 đã chạy riêng ở (2)).
2. `-q tests/test_store_shorts_edit.py -k released_edits --tb=short`: **2 failed, 3 passed, 27 deselected** (32.57 s). Title/cut đều qua encode/reuse rồi fail tại client PUT khi re-offload. Lượt đầu dùng nguồn giả 5 fps gây lượng tử hóa duration cut; đã đổi fixture mới về 25 fps, không đổi renderer, lỗi còn lại đúng client PUT.
3. `-vv tests/test_storage_cp86.py tests/test_storage_suggest.py tests/test_store_offload.py tests/test_compilation.py tests/test_store_wait_persist.py -k 'not storage_api_and_page and not old_render_recommended_with_injected_clock and not disk_status_and_submit_block and not archive_route_and_archived_episode_rules and not archive_refused_while_job_active and not storage_api_merged_video and not auto_archive_after_grace and not auto_archive_skips_video_with_khaithi and not auto_archive_unticking_in_grace and not auto_archive_disabled_and_job_waits and not auto_archive_never_touches_local_source and not lifespan_stops_hash_worker and not loop_uses_thread_and_short_success_delay' -x --tb=short`: **108 passed, 15 deselected**, 20.64 s (log `/tmp/sho1b-regression.log`).
4. `-q tests/test_render_reuse.py tests/test_render_cp9.py tests/test_store_client.py -k 'not cli_title_render and not force_config_and_plan_version_encode_all and (not client or short_client_socket_free_roundtrip or short_client_requires_valid_clip)' -x --tb=short`: **24 passed, 30 deselected**, 101.05 s.
5. `-q tests/test_render_reuse.py -m slow -x --tb=short`: **2 passed, 11 deselected**, 31.19 s.
6. `git diff --check`, `node --check src/auto_short/web/static/app.js`, `node scripts/framework-check.mjs`: PASS; framework và diff-check đã chạy lại sau khi cập nhật Result.

Không chạy được / không tuyên bố PASS:

- Full `… -m pytest -q -n auto`, bộ web TestClient và kho HTTP có socket, checklist kho tạm chạy thật theo contract: giao ORCHESTRATOR ngoài sandbox theo contract và chỉ dẫn HUMAN LEAD, sandbox không có loopback. Không thử gọi 3090 thật.
- Lượt regression đầu dùng bộ lọc như (3) nhưng còn `test_loop_uses_thread_and_short_success_delay` bị treo trong lifespan; đã hủy bằng Ctrl-C, exit 130, **không coi lượt đó PASS**; lượt (3) loại test này và hoàn tất. ORCHESTRATOR cần chạy riêng test lifespan này ngoài sandbox.
- Vòng 2 không chạy full suite / test socket / TestClient lifespan theo chỉ dẫn HUMAN LEAD; 13 case client cần socket/TestClient bị deselect. AC5 nay đã PASS bằng real handler qua memory transport, không còn boundary blocker.

Verification vòng 2 (đúng env, không socket / TestClient lifespan):

- `timeout 240s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_shorts.py tests/test_store_shorts_edit.py -x --tb=short`: **168 passed**, 28.59 s; không bỏ title/cut hay case nào trong ba file.
- `timeout 240s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_client.py -k 'client_token_from_env_only or config_store_section or put_streams_file_and_length_without_chunked_encoding or put_maps_http_errors_without_token or put_heads_existing_identity_without_sending_body or put_rejects_invalid_series_before_sending_body or released_vertical_reused_without_encode_or_job or short_client_socket_free_roundtrip or short_client_requires_valid_clip or put_existing_identity_short_revises_others_refuse' -x --tb=short`: **35 passed, 13 deselected**, 1.19 s. Deselect các case socket/TestClient; có test client mới cho cả bốn kind và SHA/size.
- `git diff --check`; `node scripts/framework-check.mjs`: **PASS**, chạy lại sau cập nhật Result.

Dòng thay đổi không tính docs: **vòng 2 so với `7ea2f5c`: app +3 / −2; test +38 / −0**. **Tổng task so với `72154a0`: app +242 / −27; test +458 / −1** (`git diff 72154a0 --numstat -- src tools tests`). Không helper ứng dụng mới trong vòng 2; tái dùng client / memory transport hiện có. Giữ Status `IN_PROGRESS`, chờ ORCHESTRATOR review và required full verification trước READY toàn task theo workflow §7.

### ORCHESTRATOR verification (2026-10-26, ngoài sandbox)

- Review diff vòng 1 + 2: inventory ⊆ Owned paths; thêm `tests/test_store_client.py` (chỉ thêm 1 test, hệ quả trực tiếp của phần `put` HUMAN LEAD đã duyệt). `client.py` diff đúng patch duyệt. Codex: vòng 1 162.594 tokens, vòng 2 (resume, effort medium) tổng phiên 350.302 tokens; 1 vòng sửa (boundary `put`).
- Targeted đủ socket / TestClient: `tests/test_store_server.py tests/test_store_shorts.py tests/test_store_shorts_edit.py tests/test_store_client.py` → **216 passed**.
- Full suite `PYTHONPATH=<worktree>/src … -m pytest -q -n auto -p no:cacheprovider` → **3264 passed, 1 skipped**, 121 s (gồm `test_loop_uses_thread_and_short_success_delay` và các test lifespan sandbox bỏ qua).
- `node scripts/framework-check.mjs`, `git diff --check`, `git diff 72154a0 --check`: PASS.
- Chạy thật trên bản sao cô lập (chép thật `work/` + `output/` của `slaGPHK7gfM` Cảm Ứng Thiên tập 44 và `.kt`, 10 Short + 3 khai thị, không HD; kho tạm `tools/store/store.py` của branch ở 127.0.0.1:18098; config tạm `offload_shorts = true`; publish tick đánh lại trong bản sao; không đụng 8080 / 3090 / YouTube):
  - Đẩy lần 1: released, 3,0 s, VM còn 0 mp4, `store.json` 10 Short.
  - Sửa tiêu đề k01 → `run_render`: lấy lại từ kho, **encoded 1 / reused 9** (33,8 s), 9 Short còn lại byte giống hệt, `store.json` đã xóa, manifest có tiêu đề mới.
  - Đẩy lại: kho có `[Short] … - k01 (r2).mp4`, giữ `… - k01.mp4` cũ, dòng `index-short.csv` hiện hành trỏ `(r2)`.
  - Tắt kho, sửa tiêu đề k02, job render qua runner → `interrupted` "đợi 3090: không kết nối được kho: URLError", lưu `.web_queue.json`, `store.json` giữ nguyên. Bật kho, app mới: `restore()` = 1, `store_retry_pass()` = `['slaGPHK7gfM']`, job done "10/10 Shorts (1 encoded, 9 reused)"; đẩy lại → `k02 (r2)`.
  - Ghép (concat) k01 Short + 1 khai thị, cả 13 clip đều ở kho: job done, video 71,5 MB, ffprobe 332,56 s = 88,658 + 243,873; không còn `.store-shorts-*`; `store.json` hai phần giữ nguyên.
  - `/api/storage` (TestClient, đăng nhập) 200: `shorts_offload` = `{"enabled": true, "episodes": 2, "bytes": 322573525, "eligible": 0, "waiting_days": 0, "failed": 0, "last_error": null}`.
- Chưa kiểm: UI tab Bộ nhớ trên trình duyệt (chỉ API + `node --check`); 3090 thật (cần chép `store.py` sau merge). Cờ `offload_shorts` giữ tắt trên 8080.
- **READY** — chờ HUMAN LEAD review PR.
