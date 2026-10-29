# Task: HDI1-hd-thumbnail-intro — Bản HD trên kho 3090 có 3 giây thumbnail đầu video (thay bản HD)

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, nhiều module đọc HD + giao thức kho); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tạo thêm 1 bản địa tạng hd để tôi test trước" → xem bản thử `output/_samples/dt-hd-intro/DiaTang_Tap1_HD_intro.mp4` → "Ok viết task riêng" → "G1 a. G2 b nhưng chỉ dùng cho địa tạng làm 1 bản test trước. Hiện tại địa tạng hd đã có trên 3090" → "Bản HD intro đè luôn bản HD" → chọn "Đè + ghi độ lệch"
- Parallel group: —
- Owned paths: `src/auto_short/render/hd_intro.py` (mới), `src/auto_short/enhance/state.py` (`EffectiveSource` thêm độ lệch + sha lưu kho; đọc `hd_intro.json`), mọi chỗ đọc file HD để render: `src/auto_short/render/full.py`, `src/auto_short/render/stage.py`, `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_render/__init__.py` (ORCHESTRATOR 2026-10-29: đường render video ghép chủ đề — cùng ý "mọi đường đọc HD" đã duyệt, contract ghi thiếu), `src/auto_short/store/borrow.py`, `src/auto_short/review/backup.py` (chỉ sha HD đã giải phóng), `src/auto_short/store/client.py` (thao tác thay thế), `tools/store/store.py` (thay thế có kiểm sha cũ), `src/auto_short/web/routes/episodes.py` + `src/auto_short/web/app.py` / `src/auto_short/web/jobs.py` (route + kind job `hd_intro`), `src/auto_short/web/static/` (chỉ nút trên trang tập), `src/auto_short/config.py` + `config.example.toml` (mục `[hd_intro]`), `tests/test_hd_intro.py` (mới) + test hiện có của các module trên (chỉ thêm ca độ lệch / thay thế), contract này
- Dependencies: THUMB1 (#182, thumbnail tập khổ ngang qua `episode.valid_files`), VERT2 (`render/full.intro_image`), HD1 / HD2a / HD2b (HD đã giải phóng, mượn HD từ kho)
- Base commit / branch: `721fb7f` (xếp chồng trên THUMB1 #182, chưa merge) / `feature/hdi1-hd-intro`; PR base đổi sang `main` sau khi THUMB1 merge
- Human Lead approval: APPROVED 2026-10-29 (G1 a, G2 = đè bản HD trên kho + ghi độ lệch, chỉ Địa Tạng, 1 bản test trước)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (1) thay **dữ liệu gốc** trên kho 3090 (bản HD) — bản cũ mất sau khi thay; (2) mọi đường đọc HD (bản dọc, Short, video ghép chủ đề, mượn HD) phải bù độ lệch; (3) giao thức kho thêm thao tác thay thế (HUMAN LEAD chép `tools/store/store.py` lên 3090).

## Goal

Với bộ kinh bật trong config (hiện chỉ Địa Tạng `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`), trang tập có nút "Tạo HD có intro": job dựng bản HD ngang có 3 giây đầu là thumbnail tập khổ ngang (Bồ Tát + "TẬP N"), phần bài giảng giữ nguyên gói (không encode lại), rồi **thay bản HD trên kho 3090**. Sau đó "Tải HD" trả bản có intro; bản dọc / Short / video ghép vẫn dựng đúng mốc thời gian (bỏ phần intro). Làm **1 tập test trước** (Địa Tạng tập 1), HUMAN LEAD duyệt rồi mới làm cả bộ.

## Scope

- In scope:
  - **`render/hd_intro.py`**: HD hiệu lực (mượn từ kho như HD2a) + thumbnail ngang hợp lệ (`episode.valid_files`, dựng nếu thiếu như `full.intro_image`) → intro đúng `round(3 × fps)` khung (90 khung = 3,003 s ở 30000/1001) cùng codec / profile / kích thước / pix_fmt / timescale với HD; âm im lặng cùng codec (aac / opus) / sample rate / số kênh, cắt đúng độ dài khung; ghép concat demuxer `-c copy` + `+faststart`. **G1 = a**: HD khác 16:9 (Địa Tạng 1440×1080) → thu thumbnail vừa khung, viền đen. Codec ngoài h264 + aac/opus → lỗi rõ.
  - Kiểm trước khi thay: tổng thời lượng = HD + intro (±1 khung); pts gói đầu của phần HD (hình và tiếng) lệch ≤ 20 ms so với mốc intro; sau khi bỏ `offset` (giải mã thử vài khung đầu / giữa / cuối) khung hình giống HD gốc (`framemd5` hoặc so pixel) — sai → xóa, báo lỗi, không đụng kho.
  - **Ghi nhận độ lệch**: `hd_intro.json` trong workspace owner (cùng chỗ `enhance.json` / `backup.json`): `original` {sha256, size}, `stored` {sha256, size}, `frames`, `fps`, `offset_seconds` (chính xác = frames / fps), `thumb_sha256`, `version`, `replaced_at`. Ghi **trước** khi thay trên kho (trạng thái `pending`), cập nhật `done` sau khi `head` kho khớp sha / size mới; lỗi giữa chừng → lần sau đối chiếu `head` để biết bản nào đang ở kho.
  - **`EffectiveSource`**: thêm `offset` (giây, mặc định 0) và `stored_sha256` (sha bytes trên kho / file); `sha256` (danh tính nội dung) **giữ sha gốc** → cache key bản dọc / Short / video ghép không đổi, 64 bản dọc Địa Tạng không bị coi là cũ.
  - **Mọi đường đọc file HD** áp `offset`: input `-ss <offset>` (giải mã chính xác khung) + trừ khỏi thời lượng probe: `render/full.py` (bản dọc), `render/stage.py` (render / sửa Short, khai thị từ HD), `theme_index` / `theme_render` (video ghép chủ đề), bất kỳ chỗ nào probe thời lượng HD. Mượn HD (`store/borrow.py`) kiểm theo `stored_sha256`; `review/backup.py` sha HD đã giải phóng = `stored`.
  - **Kho**: `tools/store/store.py` thêm thay thế có điều kiện: `PUT` loại `hd` kèm header `X-Replace-Sha256: <sha hiện có>` → chỉ thay khi sha hiện có khớp (ghi file tạm rồi `os.replace`, cập nhật `danh-sach.csv`), không khớp → 409; không có header → hành vi cũ (409 khi khác sha). `client.replace(...)`. Server cũ (chưa chép) trả 409 → job báo "cần cập nhật store.py trên 3090", không đổi gì.
  - **Điều kiện chạy**: chỉ tập có HD đã giải phóng lên kho (không có `source_hd.mp4` cục bộ); từ chối khi có job bản dọc / Short / khai thị đang chờ hoặc chạy cho video đó; bộ không bật → 404.
  - **Web**: `POST /api/episodes/{id}/hd-intro` (job làn `render`, kind `hd_intro`), trạng thái trong view HD của trang tập ("HD có intro ✓" / "cần tạo lại" khi thumbnail ngang đổi); nút "Tạo HD có intro". "Tải HD" giữ route `source-hd` (giờ trả bản có intro).
  - **Bản test**: trước khi thay ở tập test đầu tiên, giữ bản HD gốc cục bộ tại `output/_samples/hdi1-original/<id>.mp4` (ngoài cơ chế tự động; ORCHESTRATOR xóa sau khi HUMAN LEAD duyệt).
- Out of scope:
  - Nút "cả bộ" (thêm sau khi HUMAN LEAD duyệt bản test; có thể chỉ gọi route từng tập).
  - Gỡ intro / khôi phục bản gốc tự động; bộ kinh có `source_hd.mp4` cục bộ chưa giải phóng; tự đăng YouTube.

## Authority / key decisions

- VERT2 (intro 3 giây = thumbnail tập), HD1 / HD2a / HD2b (giải phóng / mượn HD), CP8.3 (auth / job / file), HUMAN LEAD 2026-10-29 duyệt bản thử + G1 a + "đè luôn bản HD" + "đè + ghi độ lệch".
- Danh tính nội dung (sha gốc) tách khỏi sha bytes lưu kho: bản dọc / Short đã dựng vẫn hiện hành; độ lệch chỉ ảnh hưởng cách đọc file.
- Thứ tự vận hành: 63 bản dọc Địa Tạng đang chờ (2026-10-29) phải xong trước khi thay HD các tập đó (điều kiện chạy chặn sẵn).

## Implementation approach

- Tách hàm thuần (lệnh ffmpeg từ probe, kiểm thời lượng / pts, `hd_intro.json`) khỏi subprocess; test bằng video nhỏ ffmpeg tạo trong `tmp_path` (h264 + aac và h264 + opus; 16:9 và 4:3); kho giả lập bằng server test hiện có / client giả — không mạng thật.
- Tái dùng: `full.intro_image`, `store.borrow`, `offload.push_vertical` (mẫu đẩy + `head`), `ep.hd_source`, `probe_media`. Quy trình đã chứng minh: `/home/ntnghia/.claude/jobs/1c1feb65/tmp/hd_sample.py` (ops, ngoài repo).
- Một helper chung cho "input HD có offset" (vd. trả `["-ss", str(offset), "-i", path]` và thời lượng đã trừ) để mọi caller dùng, không rải `-ss` thủ công.

## Phải giữ nguyên

- Cache key / tính hiện hành của bản dọc, Short, video ghép chủ đề (danh tính = sha gốc).
- HD chưa có intro: mọi đường đọc byte-identical như trước (offset 0, không thêm `-ss`).
- Giao thức kho cũ (không header thay thế → hành vi cũ); loại / định danh khác không đổi.

## Code bị thay / xóa

- Các chỗ mở file HD trực tiếp trong `render/full.py`, `render/stage.py`, `theme_render` chuyển sang helper input HD có offset (không giữ đường cũ song song).

## Acceptance Criteria

1. HD h264 + aac / opus (16:9, 4:3) → bản có intro: 3 giây đầu là thumbnail ngang (4:3 có viền đen), phần sau giữ nguyên gói, thời lượng đúng ±1 khung, lệch mốc hình / tiếng ≤ 20 ms; codec lạ / thiếu thumbnail / thiếu HD → lỗi rõ, không file dở, không đụng kho.
2. `hd_intro.json` ghi `pending` trước khi thay, `done` sau khi `head` kho khớp; thay lỗi → kho giữ bản cũ hoặc bản mới đúng sha, lần sau tự đối chiếu; bản mượn / tạm bị xóa.
3. Sau khi thay: `EffectiveSource.sha256` = sha gốc, `offset` = frames / fps, `stored_sha256` = sha mới; bản dọc / Short / video ghép dựng từ HD có intro cho **khung hình giống** khi dựng từ HD gốc (test so khung); bản dọc hiện có vẫn "hiện hành"; mượn HD kiểm theo sha mới.
4. Kho: `PUT` `hd` + `X-Replace-Sha256` đúng → thay + CSV cập nhật; sai sha → 409, không đổi; không header → hành vi cũ; client báo rõ khi server chưa hỗ trợ.
5. Route / job: cần đăng nhập; bộ không bật / id lạ → 404; HD chưa giải phóng → 409; đang có job bản dọc / Short / khai thị của video → 409; đổi thumbnail ngang → "cần tạo lại".
6. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_hd_intro.py` + test kho / borrow / full / stage / theme_index liên quan — AC 1–5 (test socket / web: ORCHESTRATOR chạy ngoài sandbox).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh, sau khi HUMAN LEAD chép `tools/store/store.py` lên 3090 và 63 bản dọc Địa Tạng xong): Địa Tạng tập 1 "Tạo HD có intro" → `head` kho khớp sha mới → tải "Tải HD" so với bản thử đã duyệt; dựng thử 1 Short / đoạn bản dọc từ HD mới so khung với bản cũ; HUMAN LEAD xem 10 giây đầu.

## Manual test checklist (Tech Lead)

- [ ] Trang tập Địa Tạng có "Tạo HD có intro"; sau khi xong "Tải HD" có 3 giây thumbnail, tiếng khớp môi.
- [ ] Bộ khác không có nút.
- [ ] Bản dọc / Short Địa Tạng vẫn hiện "đã có", không đòi dựng lại.

## Result

- **READY — phần IMPLEMENTER theo delegation (code + verification không socket), bàn giao ORCHESTRATOR review.** Không còn blocker phạm vi: ORCHESTRATOR đã xác nhận `theme_render/__init__.py` + test tương ứng trong Owned paths. Auth / full suite / media thật vẫn giao ORCHESTRATOR; **không claim AC6 hoặc các kiểm tra chưa chạy là PASS**.
- Không commit / push / PR, không gọi agent khác, không gọi mạng / kho thật. HEAD làm việc `a0a164c`; chỉ có `AGENTS.md` ở root, đã đọc trước khi sửa.

Thay đổi theo file / nhóm:

- `render/hd_intro.py`: spec / lệnh intro + concat copy; kiểm duration / pts qua hash payload gói và khung đầu / giữa / cuối; runner tiêm được. Bù encoder priming theo millisecond edit list MP4 (AAC 1024 mẫu, Opus 312 mẫu). Job mượn vào thư mục tạm, giữ gốc khi `keep_original`, pending trước replace, done sau HEAD đúng sha / size; phục hồi pending, cập nhật backup HD + snapshot kho. Thumbnail đổi: tách gói bài giảng rồi thay intro, không ghép chồng; mirror metadata `.kt`.
- `enhance/state.py`, `render/full.py`, `render/stage.py`: tách SHA nội dung / SHA lưu kho, offset từ frames/fps; helper input seek / timestamp offset cho `-copyts`, trừ thời lượng. Offset 0 giữ nguyên lệnh. Không đổi key / plan version.
- `theme_render/__init__.py`: `_source` kiểm bytes theo `stored_sha256`; `_hd_source` chỉ chọn descriptor khi đường dẫn thực tế đúng file HD của `source_reference`, tránh áp offset cho nguồn gốc tải lại. Dùng `hd_input_command` và `hd_duration`; giữ SHA gốc / fingerprint / encode key / cache. Kiểm mốc cuối theo thời lượng bài giảng đã trừ intro. `theme_index` giữ cache qua `hd_fingerprint`, không có input ffmpeg cần sửa tại đó.
- `store/borrow.py`, `review/backup.py`: kiểm / đọc / ghi SHA bytes lưu kho; không coi HD vắng mặt là file cục bộ. `tools/store/store.py`, `store/client.py`: conditional replace chỉ HD, kiểm SHA bytes cũ, file tạm + rename, cập nhật checksum / CSV; lỗi server cũ hướng dẫn cập nhật; PUT không header giữ hành vi cũ.
- `config.py`, `config.example.toml`: `[hd_intro] playlists = []`. `web/jobs.py`, `web/app.py`, `web/routes/episodes.py`: key riêng / làn render / restore queue / route / gate 404–409 / view current–stale / chặn xóa khi job hoạt động. `web/static/app.js`, `episode.html`: nút, trạng thái và polling trên trang tập.
- Tests: mới `test_hd_intro.py`; thêm ca trong `test_store_server`, `test_store_client`, `test_hd_backup`, `test_render_stage`, `test_vertical_silence_intro`, `test_theme_index`, `test_theme_render`, `test_web_hd_cp827`.

Helper mới / tái dùng:

- Đã tìm `rg -n 'hd_path|effective_source|source_hd|borrow' src/auto_short`, cùng `ffmpeg_command`, `probe_media`, `intro_image`, `source_reference`; không có helper offset / conditional replace / kiểm concat HD tương ứng.
- Chung: `hd_intro_record`, `hd_source`, `hd_input_args`, `hd_input_command`, `hd_duration`. `hd_input_command` dùng `-itsoffset` trên input `-copyts`; FFmpeg tự áp offset vào seek đang có, không cộng lần thứ hai vào `-ss`.
- Thêm `_hd_source(record, path)` trong theme renderer để chọn descriptor cho cả kiểm SHA và encode, không đổi tuple trả về của `_source`. Không nhân bản logic offset / parse metadata.
- Module mới có helper spec / command / verify / metadata / `run_intro`; tái dùng `_run`, `probe_media`, `plan.source_fps` / `fps_text`, `episode.valid_files` / `build_episode`, `borrow_hd`, `atomic_write_json`, client `_path` / `_open` / `head`. Intro dọc trong `full` encode bài giảng nên không thay được concat copy ngang. Không thêm dependency.

| AC | Test | Kết quả |
|---|---|---|
| 1 | `test_stream_copy_timing_padding_and_offset_frames` (AAC/Opus × 16:9/4:3), `test_invalid_inputs_and_failed_verification_remove_output` | PASS |
| 2 | `test_pending_recovery_identity_borrow_and_current`, `test_fetch_failure_cleans_private_partial`, `test_real_job_rebuild_replaces_intro_without_stacking` | PASS |
| 3 | `test_hd_intro_offset_preserves_short_frames_and_keys`, `test_hd_intro_offset_keeps_full_key_and_original_duration`, `test_hd_intro_stored_bytes_keep_content_identity_and_index_cache`, `test_hd_intro_preserves_landscape_frames_identity_and_cache` | PASS: Short / bản dọc / index / video ghép; mượn SHA mới trong ca AC2 |
| 4 | `test_hd_conditional_replace_preserves_identity_csv_and_rejects_conflicts`, `test_hd_replace_bad_body_and_other_kinds_do_not_change_store`, `test_hdi1_replace_client_streams_header_and_old_server_error` | PASS, handler bộ nhớ không socket |
| 5 | `test_route_gates_and_render_lane_without_sockets`; stale thumbnail trong ca pending/recovery; `test_hd_intro_auth_and_keep_original_body` | Gate / stale PASS; auth TestClient chưa chạy |
| 6 | framework / diff checks dưới đây | PASS hai check; full suite chưa chạy |

AC3 liệt kê 4 test vì 4 đường độc lập: Short, bản dọc, cache index, render video ghép. Test video ghép so **toàn bộ framemd5 video sau khi ghép**, chạy audio gate thật, kiểm fingerprint / cache / lệnh offset 0 / SHA bị đổi sau audit; không gọi downloader.

Lệnh đã chạy ở vòng hoàn tất (từ root worktree):

```sh
env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/hdi1-hd-intro/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_hd_intro.py tests/test_store_server.py tests/test_render_stage.py tests/test_vertical_silence_intro.py tests/test_theme_index.py tests/test_theme_render.py tests/test_enhance_state.py tests/test_store_client.py::test_hdi1_replace_client_streams_header_and_old_server_error tests/test_hd_backup.py::test_hd_intro_released_backup_sha_is_stored_identity -x --tb=short
# 326 passed, 2 deselected, 213.28 s.

env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_render_stage.py -m slow -x --tb=short
# 2 passed, 18 deselected, 25.33 s.

node scripts/framework-check.mjs
# PASS: framework structure.
git diff --check
# PASS.
node --check src/auto_short/web/static/app.js
# PASS.
env PYTHONPATH=src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m compileall -q src/auto_short tools/store/store.py tests/test_theme_render.py
# PASS.
```

Chưa chạy, giao ORCHESTRATOR ngoài sandbox theo delegation:

- `<prefix> tests/test_web_hd_cp827.py tests/test_store_client.py tests/test_hd_backup.py` (TestClient / server socket), đặc biệt auth mới `test_hd_intro_auth_and_keep_original_body`.
- `<prefix> -n auto` (full suite / xdist có socket); không claim AC6 PASS.
- Kho thật 3090 / Địa Tạng tập 1, mẫu gốc và HUMAN LEAD xem 10 giây đầu: chưa chạy, không có tác động kho thật.

Dòng +/− tổng task (kể cả 2 file mới chưa stage, không tính contract): ứng dụng `+606 / −27`; tests `+523 / −0`; config example `+4 / −0`. Vòng bổ sung theme renderer: ứng dụng `+20 / −3`, test `+63 / −0`.

Rà các đường đọc HD: full / stage / theme renderer đã áp helper; download HD chủ ý trả bytes có intro. Các chỗ còn lại trong `hd_path|effective_source|source_hd|borrow_hd` quản lý / hiển thị / assemble, chưa thấy caller render HD khác bị sót. Rủi ro chưa xác minh: auth / full suite ngoài sandbox và media Địa Tạng thật, không còn blocker code được biết trong phạm vi task.

ORCHESTRATOR review + verification (2026-10-29, ngoài sandbox):

- Codex 2 vòng: vòng 1 205.819 tokens, vòng 2 (offset `theme_render`) 263.445 tokens; session `01a18743-1f7f-7c21-94cc-bf331ce3850c`. Inventory ⊆ Owned paths (có `theme_render/__init__.py` đã bổ sung).
- Review: `EffectiveSource.sha256` giữ sha gốc, `stored_sha256` + `offset` từ `hd_intro.json` `done`; offset 0 giữ nguyên lệnh (`hd_input_args` / `hd_input_command`); `store.py` thay thế chỉ `hd`, kiểm sha cũ trước và sau khi tải (dưới lock), file tạm + `os.replace`, cập nhật CSV + `SHA256SUMS.txt`; job ghi `pending` trước `client.replace`, đối chiếu `head` khi chạy lại, `keep_original` kiểm sha bản giữ lại trước khi thay. Không có finding blocking.
- Full suite `-n auto` (gồm test web / TestClient / socket): lần 1 **3547 passed, 1 failed, 1 skipped** — `test_web_vertical_cp832.py::test_ac3_youtube_block_waits_not_fails` (dựa thời gian retry 0,3 s; file không đổi trong diff; chạy riêng 3 lần PASS); lần 2 **3548 passed, 1 skipped**. AC5 auth (`test_hd_intro_auth_and_keep_original_body`) PASS trong full suite. `framework-check` PASS, `git diff --check` PASS.
- Chưa chạy: chạy thật Địa Tạng tập 1 (chờ 63 bản dọc Địa Tạng xong + HUMAN LEAD chép `tools/store/store.py` lên 3090).
