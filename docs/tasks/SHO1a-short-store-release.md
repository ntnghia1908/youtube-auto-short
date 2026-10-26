# Task: SHO1a — Short + khai thị đã đăng hết lên kho 3090, web xem / tải từ kho

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, tính năng mới hai đầu kho / VM); quota 2026-10-26: 5 giờ 19 %, tuần 21 %; dự phòng subagent `implementer` (Sonnet). Test web (TestClient) và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SHO1-short-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-26 "duyệt tất cả"), G1 + G2 + G3 + G4 + G6 (trừ ghép Short) + G8
- Parallel group: —
- Owned paths: `tools/store/store.py`; `src/auto_short/store/client.py` (tham số `clip`); `src/auto_short/store/shorts.py` (mới: hồ sơ giải phóng, chọn tập, đẩy); `src/auto_short/config.py` (chỉ `StoreConfig.offload_shorts`); `src/auto_short/web/storage.py` (chỉ hàm thuần chọn tập theo G2); `src/auto_short/web/episodes.py` (helper vị trí Short G6, `short_files` / `all_zip` / `archive_zips`); `src/auto_short/web/routes/files_catchall.py` (phát / tải / ZIP từ kho); `src/auto_short/web/app.py` (vòng đẩy nền, theo mẫu `offload_pass`); `src/auto_short/review/archive.py` (chỉ chỗ đọc file Short, nếu cần cho G6); `tests/test_store_server.py`, `tests/test_store_client.py`, `tests/test_store_shorts.py` (mới), `tests/test_archive_zips.py`; contract này
- Dependencies: HD2a, SRC1, HD2b, ARC1 (đã merge); không dependency mới
- Base commit / branch: `docs/sho1-short-store` (PR #173, chứa quyết định + contract) / `feature/sho1a-short-store`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-26 "duyệt tất cả" (SHO1)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa API / danh mục kho HD2 G1 (kind `short` theo file), luật mới "file Short được vắng khi đã giải phóng", luồng VM ↔ 3090 mới.

## Goal

Bật `[store] offload_shorts`: Short + khai thị của video đã đăng hết đủ 5 ngày được đẩy lên kho 3090, kho khớp sha từng file thì VM xóa chúng (giải phóng tới ≈ 100 GB); trên web các Short đó vẫn liệt kê, phát, tải từng file, "Tải cả hai" và ZIP lưu trữ ARC1 như trước (VM chuyển tiếp từ kho). Cờ vẫn **tắt** trên 8080 cho tới khi SHO1b (sửa / ghép) merge.

## Scope

- In scope:
  - **K1 kho (G1)**: `kind = short` với đường dẫn `/files/<video_id>/short/<clip>` cho `GET` (Range) / `HEAD` / `PUT`; `<clip>` khớp `k[0-9]{2,3}\.mp4` (hoặc đúng regex clip id hiện có của web + `.mp4`); kind cũ giữ `/files/<video_id>/<kind>` (không nhận `clip`). Danh mục `index-short.csv` (`video_id`, `clip`, `file`), `SHA256SUMS.txt` chung; `GET /index` trả thêm dòng Short có `clip`. Khóa nhận diện Short = (`video_id`, `short`, `clip`); quy tắc 409 / 200 (cùng file) như kind cũ. Không xóa qua API.
  - **K2 client**: `head` / `put` / `open_stream` / `fetch` nhận `clip` tùy chọn (bắt buộc cho `short`).
  - **K3 chọn tập (G2)**: hàm thuần trong `storage.py` (cạnh `auto_archive_plan`, tái dùng `_videos` / `complete_since`): video mà mọi phần "Xong" giữ ≥ `auto_archive_grace_minutes`, không phần nào đang xử lý, có ít nhất một Short trên VM chưa giải phóng; **gồm cả video có khai thị**.
  - **K4 đẩy + giải phóng (G3)**: cờ `[store] offload_shorts` (mặc định `false`). Vòng nền một video mỗi lượt (như `offload_pass`: nhường khi có job của Short / khai thị, dừng hợp tác khi tắt web, lỗi một video không chặn video khác): mỗi Short `rendered` của `<id>` và `<id>.kt`: sha256 lấy từ `render_manifest.json` (kiểm lại file khớp sha trước khi đẩy) → `PUT` tên G1 → `HEAD` khớp sha + kích thước. Đủ mọi file của phần đó → ghi `output/<episode>/store.json` (`released`: clip → `{sha256, size, mtime_ns}`, `at`) bằng ghi nguyên tử, rồi mới xóa file. Thiếu / lệch → không xóa gì, thử lại lượt sau. Không đổi `render_manifest.json`, `publish.json`, bài đăng.
  - **K5 vị trí Short (G6)**: helper chung trong `web/episodes.py` trả mỗi Short `rendered`: trên VM (path) / trên kho (đã giải phóng, có sha / size / mtime) / không có. `short_files` cũ giữ nghĩa "file trên VM" cho chỗ cần file thật (ghép Short — SHO1b); liệt kê / đếm / ZIP / tải dùng helper mới. File vắng mà không có `store.json` → như hiện nay (không có file).
  - **K6 phát / tải (G4)**: `/files/<id>/<clip>.mp4` của Short trên kho: chuyển tiếp từ kho (giữ `Range`, `Content-Length`, `Content-Range`, tên file tải như cũ; `download=1` vẫn đánh dấu "Đã đăng" như cũ). `shorts.zip` / `all.zip` (cả `?archive=1`): entry trên kho đọc luồng từ kho, tên / nội dung như cũ, mtime entry = `mtime_ns` đã ghi. `/api/archive/zips`: vân tay ARC1 dùng size + mtime đã ghi (không đổi sau giải phóng). Kho tắt → file đơn 503 "3090 đang tắt"; ZIP có entry trên kho → 503 trước khi bắt đầu luồng (kiểm `available()`); kho rớt giữa luồng → đóng luồng (client thấy lỗi tải, script ARC1 tự kiểm ZIP thiếu).
- Out of scope (SHO1b): lấy lại Short khi dựng lại / sửa (G5), mượn khi ghép Short, tab Bộ nhớ (G7), bật cờ trên 8080. Không xóa trên 3090; không nút bấm tay.

## Authority / key decisions

- SHO1 G1–G4, G6, G8 (ACCEPTED). HD2 G1 / G2 / G8 (kho, kênh, token) giữ. W9 S5 (tự dọn nguồn) không đổi — K3 là hàm riêng.
- CP8.31 D1 (tải ZIP / `download=1` đánh dấu "Đã đăng"), ARC1 A1 (`?archive=1` không đánh dấu) giữ nguyên.

## Implementation approach

- Kho: tách phân tích đường dẫn thành (`video_id`, `kind`, `clip|None`); `_rows` đọc thêm `index-short.csv`; `_publish` ghi vào `index-short.csv` cho `short`. Lưu ý `index()` đang stat mọi file mỗi lần `lookup` — với ~4.000 Short nếu chậm thì lookup Short tra trực tiếp danh mục của thư mục (cache theo chữ ký file như `_rows`).
- VM: theo mẫu `store/offload.py` + `app.py` `offload_pass` (stop event, busy, lỗi theo tập); tên file / thư mục bộ kinh qua `store/backup.py` `_destination`. Phát từ kho theo mẫu `web/routes/episodes.py` (~dòng 516, `open_stream`). `_zip_stream` nhận entry có thể là luồng kho.

## Phải giữ nguyên

- `offload_shorts = false` (mặc định): không lượt đẩy nào, mọi route Short như trước (byte ZIP không đổi).
- Kind `hd` / `vertical` / `source`: API, `index.csv`, `danh-sach.csv`, `backup.ps1` không đổi; mọi test HD2a / HD2b / SRC1–SRC4 / ARC1 / CP8.17 / CP8.31 hiện có.
- Render không bị kích hoạt lại vì file Short vắng; trạng thái "Xong" / "đã đăng x/y" không đổi sau giải phóng.

## Code bị thay / xóa

- Không xóa. Chỗ liệt kê / ZIP / tải Short chuyển từ `short_files` sang helper K5.

## Acceptance Criteria

1. Kho nhận `PUT /files/<id>/short/k01.mp4` (cả `<id>.kt`), `HEAD` / `GET` Range đúng byte; tên / clip sai → 400; cùng khóa khác sha → 409; `index-short.csv` + `SHA256SUMS.txt` cập nhật; `index.csv` không đổi; kind cũ hoạt động như trước.
2. K3: video đã đăng hết đủ grace (kể cả có khai thị) được chọn; chưa đủ ngày / còn Short chưa đăng / đang xử lý / đã giải phóng hết → không.
3. K4: đẩy đủ + khớp → `store.json` ghi, file VM bị xóa; kho tắt / sha lệch / thiếu một file / file VM lệch sha manifest → không xóa file nào, thử lại sau; video khác vẫn chạy; tập có job → bỏ qua.
4. Sau giải phóng: trang tập / danh sách hiện đủ Short, "đã đăng x/y" và "Xong" như trước; không job render nào được tạo.
5. Phát / tải Short đã giải phóng: đúng byte (sha), `Range` 206; `download=1` đánh dấu "Đã đăng"; kho tắt → 503.
6. `shorts.zip`, `all.zip`, `all.zip?archive=1` cho tập đã giải phóng (một phần hoặc toàn bộ): entry đúng tên + byte; vân tay `/api/archive/zips` trước = sau giải phóng; kho tắt → 503.
7. `offload_shorts = false`: không lượt đẩy; full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_client.py tests/test_store_shorts.py tests/test_archive_zips.py` — AC 1–6 (test web / server cần socket: ORCHESTRATOR chạy ngoài sandbox).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- ORCHESTRATOR chạy thật (không bật cờ trên 8080): kho tạm chạy `tools/store/store.py` mới trên VM (thư mục tạm, cổng khác) + bản sao workspace của 1 tập đã đăng hết có khai thị → chạy một lượt đẩy, kiểm `store.json`, phát / tải / `all.zip?archive=1` khớp sha, vân tay ARC1 không đổi.

## Manual test checklist (Tech Lead)

Chạm public API kho (thêm kind) và luồng dữ liệu VM ↔ 3090; không chạm security model (token / kênh cũ), không database. Manual test sau SHO1b, khi bật cờ trên 8080:

- [ ] Một tập đã giải phóng: phát Short, tải 1 Short, "Tải cả hai" được (3090 bật); tắt 3090 → báo "3090 đang tắt".

## Result

- IMPLEMENTER handoff: READY cho ORCHESTRATOR review/verification ngoài sandbox; task giữ IN_PROGRESS vì chưa chạy required full suite / TestClient / chạy thật. Không commit, push, PR; không gọi agent khác, không thêm dependency, không bật cờ 8080.
- Main changes: K1–K6 đã implement trong Owned paths. Kho có danh mục Short riêng và khóa ba thành phần; VM kiểm sha từng file, xác nhận HEAD mọi file của cả video, kiểm lại grace/job/manifest/stat dưới submit lock, ghi nguyên tử mọi `store.json` trước lần unlink đầu tiên. Đọc vị trí ưu tiên file VM khi còn; lượt sau phục hồi được sau gián đoạn unlink. Phát Range, ZIP hỗn hợp và ARC1 dùng metadata đã lưu; preflight kho trước ZIP; lỗi luồng/thiếu byte/sai sha đóng upstream và không phát ZIP hoàn chỉnh.
- Tests vòng đầu (local sandbox, 2026-10-26): **164 passed** trong bốn lượt; 15 deselected (1 TestClient ARC1 + 14 client cần chọn/chạy ngoài sandbox). Tất cả test mới chạy được không cần socket. Không sửa nội dung test cũ.

| AC | Test chính |
|---|---|
| 1 | `test_short_put_index_range_and_conflict`, `test_short_rejects_invalid_clip_paths` (server); `test_short_client_socket_free_roundtrip` (client, real handler qua memory transport) |
| 2 | `test_short_plan_includes_khaithi_and_requires_every_part` |
| 3 | `test_short_release_failure_deletes_nothing_and_retries`, `test_short_release_recovers_after_record_commit`, `test_short_background_fair_retry_busy_and_default_off` |
| 4 | `test_short_release_atomic_records_and_unchanged_views`, `test_short_missing_without_current_release_record_stays_missing`, assertion không sinh job trong background test |
| 5 | `test_released_short_play_download_range_and_errors`, `test_released_routes_disabled_store_never_contact_it` |
| 6 | `test_released_zip_bytes_metadata_fingerprint_and_store_down`, `test_released_zip_failure_closes_upstream_without_complete_archive` |
| 7 | `test_short_background_fair_retry_busy_and_default_off`; regression local 164 PASS; full suite còn chờ ORCHESTRATOR |

Lệnh đã chạy thành công (prefix pytest dưới đây = `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`):

- `<prefix> tests/test_store_server.py` → **97 passed**.
- `<prefix> tests/test_store_shorts.py` → **24 passed**.
- `<prefix> tests/test_archive_zips.py -k 'not web_auth'` → **23 passed, 1 deselected**.
- `<prefix> tests/test_store_client.py -k 'short_client or test_put_ or token_from_env_only or config_store_section'` → **20 passed, 14 deselected**.
- Trước đó một lượt gộp cùng các node không socket → **163 passed, 1 deselected** (trước khi thêm test kho bị disable).
- `node scripts/framework-check.mjs` → PASS; `git diff --check` → PASS.

Lệnh không chạy được / dành ORCHESTRATOR:

- Lượt lọc rộng `<prefix> tests/test_store_server.py tests/test_store_shorts.py tests/test_archive_zips.py tests/test_store_client.py -k 'not web_auth and not fake and not vertical and not render and not concurrent and not store_down and not store_off'` chọn nhầm 5 test socket: **147 passed, 20 deselected, 5 setup errors** (`PermissionError: Operation not permitted`, tạo socket loopback bị sandbox chặn). Đã sửa cách chọn node cho các lượt cuối; không sửa test để né lỗi.
- Required `<prefix> tests/test_store_server.py tests/test_store_client.py tests/test_store_shorts.py tests/test_archive_zips.py` chưa chạy trọn: HTTP server / TestClient cần ngoài sandbox.
- Required `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -n auto` chưa chạy: full suite do ORCHESTRATOR, có socket/TestClient.
- Chạy thật kho tạm + workspace bản sao theo Required verification chưa chạy (cấm mạng/socket trong sandbox).

- Diff + / − (app, test): **app +405 / −63**, **test +511 / −0**, gồm hai file mới chưa stage; không tính contract. `git diff --numstat` cộng `wc -l` cho file mới.
- Helper mới (đã tìm bằng `rg -n 'def (short_files|all_zip|archive_zips|auto_archive_plan|_destination|offload_pass|_check_stop|sha256_file)|class _StoreResponse' src/auto_short tools/store`):
  - `StoredShort` / `short_locations`: `short_files` chỉ có Path; cần biểu diễn kho/thiếu và metadata gốc. `short_files` trở thành bộ lọc Path, giữ nghĩa cũ cho compilation.
  - `short_offload_plan`: tái dùng `_videos` / `complete_since`; không dùng `auto_archive_plan` vì hàm đó loại video có khai thị và yêu cầu nguồn còn dọn được.
  - `store.shorts.candidates` / `push_video`: không thể dùng `push_vertical` vì Short là nhiều file / hai phần và cần hồ sơ release riêng. Tái dùng `_destination`, `_matches`, `_check_stop`, `_sha256_file`, `atomic_write_json`, `RENDER_MANIFEST_NAME`, index invalidation. Dùng hàm băm của offload thay `hashing.sha256_file` để dừng hợp tác cả khi đang băm.
  - `shorts_offload_pass` / `_shorts_offload_loop`: vòng riêng theo mẫu vertical, có cờ/stop/failure rotation riêng; không thay policy vòng vertical.
  - `zip_body` (nội bộ router): preflight chung hai loại ZIP; tái dùng `_zip_stream` và `_StoreResponse` sẵn có cho luồng/đóng upstream, giữ nhánh ZIP cục bộ cũ.
  - Test `MemoryShortStore` / `prepared_shorts` dùng chung giữa hai file test, đặt trong module test Owned paths; transport client tái dùng `test_store_server.request`.
- Review: IMPLEMENTER đã rà diff theo contract/AC, giới hạn Owned paths và kiểm tra compatibility cục bộ; independent review và verification ngoài sandbox chờ ORCHESTRATOR.
- Important findings / decisions: record `released` khóa bằng clip id (`k01`), giá trị `{sha256, size, mtime_ns}`; `at` ở cấp document. Local file luôn thắng record khi cả hai tồn tại. `render_manifest.json`, `publish.json`, trạng thái và fingerprint không đổi do release.
- Known limitations: chưa tuyên bố full suite PASS; stream/auth/lifespan qua ASGI thực và giao tiếp kho thật cần verification ngoài sandbox. Sửa/ghép Short đã release vẫn thuộc SHO1b; giữ `offload_shorts = false` tới khi SHO1b merge.
- PR: không tạo (theo yêu cầu).

- Review F1 (ORCHESTRATOR vòng 1): đã sửa clip id theo `_CLIP_ID_RE` của web, chấp nhận Short thêm tay `m01`. Kho standalone chép regex kèm pointer nguồn; `StoreClient._path` cũng đổi cùng quy tắc (trước đó có cùng lỗi). `push_video` dùng `ep.valid_clip_id`; `short_locations` giữ gate `valid_clip_id` hiện có và bỏ điều kiện chỉ nhận `k...` dư thừa.
- Test F1: thêm `m01` vào server/client roundtrip; fixture clip tùy chọn cho release → đọc vị trí → phát/tải Range → ZIP đầy đủ/hỗn hợp, fingerprint và mtime; thêm 12 trường hợp kho từ chối clip có `..`, `/`, backslash, ký tự Windows cấm. Input `k1.mp4` / `k0001.mp4` nay hợp lệ theo web, nên case từ chối dùng input sai thực sự (`_k1`, id dài hơn 32 ký tự).
- Verification F1: chạy lại đúng bốn lệnh targeted không socket nêu trên → server **109 PASS**, shorts **24 PASS**, archive **34 PASS / 1 deselected**, client **22 PASS / 14 deselected**; tổng **189 PASS**. `git diff --check` PASS. Full suite / TestClient / chạy thật vẫn dành ORCHESTRATOR ngoài sandbox như trên.
- Diff riêng F1 so với bàn giao vòng đầu: **app +4 / −4**, **test +40 / −25** (không tính contract); chỉ bốn file app `tools/store/store.py`, `store/client.py`, `store/shorts.py`, `web/episodes.py` và bốn file test đã giao. Không commit/push, không thay đổi ngoài F1.

### ORCHESTRATOR verification (2026-10-26, ngoài sandbox)

- Full suite `env PYTHONPATH=<worktree>/src … -m pytest -q -n auto`: trước F1 **3192 passed, 1 skipped**; sau F1 **3217 passed, 1 skipped** (gồm mọi test TestClient / HTTP server của bốn file targeted). `node scripts/framework-check.mjs` PASS, `git diff --check` PASS.
- Chạy thật trên bản sao cô lập (workspace chép không mp4, `output/` hardlink, kho tạm `tools/store/store.py` mới ở 127.0.0.1:18099, config tạm `offload_shorts = true`, TestClient không lifespan): dữ liệu thật có **72 video đủ G2** (69 có khai thị). `FHVJA9E4msM` (Cảm Ứng Thiên tập 7, 24 Short + 13 khai thị): `push_video` → released, **giải phóng 1,54 GB**, `store.json` cả hai phần, 0 mp4 còn lại; kho có `index-short.csv` + tên `[KhaiThi] Thái Thượng Cảm Ứng Thiên - Tập 7 - k01.mp4`…; phát Short từ kho khớp sha, Range 206 `bytes 0-99/13633863`; vân tay `/api/archive/zips` trước = sau; `all.zip?archive=1` 37 entry cùng tên + nội dung (byte ZIP khác ở metadata entry `external_attr` — đúng SHO1 G4 "tên / nội dung entry như cũ", script ARC1 chỉ kiểm số entry + tổng byte); `/api/episodes/<id>` 200. Bản gốc trên VM không đổi (37 file, không `store.json`).
- Review ORCHESTRATOR: F1 (clip id chỉ `k…`, dữ liệu thật có `m01`) — đã sửa, 1 vòng. Không finding khác; inventory ⊆ Owned paths.
- Codex: 2 lượt (high + medium resume), tokens 256.227 (cộng dồn session).
- Diff tổng (app, test): xem `git diff --stat` của PR (≈ +572 / −72 trước file mới).
- Known limitations: cờ `offload_shorts` tắt trên 8080 tới khi SHO1b merge; ghép Short dùng Short đã giải phóng và lấy lại khi sửa thuộc SHO1b; `store.py` mới phải chép lên 3090 trước khi bật.
