# Task: SRC1 — Sao lưu video gốc lên kho 3090 trước khi tự dọn

## Status / Approval

- Status: IN_PROGRESS (chờ chạy thật 3090)
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; quota 2026-10-25: 5 giờ 6 %, tuần 1 %. Test web (TestClient) và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SRC1-source-backup-3090.md` (ACCEPTED 2026-10-25)
- Parallel group: —
- Owned paths: `tools/store/store.py`; `src/auto_short/store/client.py`; `src/auto_short/store/backup.py` (mới); `src/auto_short/store/borrow.py` (chỉ hàm mượn `source`); `src/auto_short/config.py` (chỉ `StoreConfig.backup_source`); `src/auto_short/review/archive.py` (`archive_source`, `restore_source`); `src/auto_short/web/app.py` (chỉ `auto_archive_pass` + vòng nền sao lưu); `src/auto_short/web/storage.py` + `src/auto_short/web/static/` phần tab Bộ nhớ (dòng "đã sao lưu"); `src/auto_short/theme_render/__init__.py` (chỉ `_source` + amendment A1 (ORCHESTRATOR, 2026-10-25, theo BLOCKED của IMPLEMENTER): lời gọi `_source` trong `render_landscape` để truyền thư mục tạm `.render-` của job, nơi đặt file mượn từ kho); `tests/test_store_server.py`, `tests/test_store_client.py`, `tests/test_store_backup.py` (mới), `tests/test_restore_source_cp837.py`, `tests/test_storage_cp86.py`, `tests/test_theme_render.py`, `tests/test_config.py`; file này
- Dependencies: HD2a (kho + kênh, đã merge); không dependency mới
- Base commit / branch: `3394246` (origin/main) / `feature/src1-source-backup`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt tất cả theo đề xuất"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa decision HD2 (kind mới) và quy tắc tự dọn W9 S5; luồng dữ liệu VM → 3090 mới.

## Goal

Không video gốc nào bị xóa khỏi VM khi chưa có bản đúng sha256 trên 3090. 188 bản gốc đang có (62,8 GB) và 14 bản trong kho nguồn ghép được đẩy dần lên 3090, video ♥ trước. Ghép chủ đề và "Khôi phục nguồn" lấy lại từ 3090 trước khi phải tải YouTube.

## Scope

- In scope: decision SRC1 G2–G7 + G4a (phần đẩy; tải lại bản đã xóa thuộc SRC2).
- Out of scope: tải lại bản đã xóa (SRC2); xóa trên 3090; HD2b G5 / G6; đổi định dạng file.

## Authority / key decisions

- `docs/decisions/SRC1-source-backup-3090.md` (G1, G4 HUMAN LEAD chọn 2026-10-25); `docs/decisions/HD2-external-store-3090.md`.
- Cục bộ (ORCHESTRATOR): `[store] backup_source` mặc định `false`; khi `true` mà `[store] enabled = false` → config lỗi rõ ràng. Thư mục `_khac` cho video không có bộ kinh. PUT không nối tiếp (gửi lại cả file khi đứt) — file gốc ≤ ≈ 0,7 GB.

## Implementation approach

- Server: `KINDS` thêm `Goc → source`; `validate_identity` nhận `source`; PUT ghi dòng `loai = Goc` vào `index.csv` như bản dọc. Client: `KINDS` thêm `source`, hàm `put(video_id, kind, series, name, path, sha256)` streaming, kiểm phản hồi.
- `store/backup.py`: `backup_state(config, video_id)` (HEAD, so sha / size), `push_source(config, video_id)` (file workspace hoặc cache, tên theo G2), `backup_order(config)` (sắp đến hạn tự dọn → ♥ → còn lại; bỏ đã có).
- `archive_source`: khi `backup_source` bật → cần `backup_state` khớp trước khi xóa, ghi `backup` vào `archive.json`; không khớp → `ReviewError("chưa sao lưu lên 3090 …")` (tự dọn ghi log rồi bỏ qua như hiện nay).
- Web: vòng nền (như `auto_archive_pass`, chu kỳ riêng) đẩy một file mỗi lượt khi làn render rảnh; kho tắt → nghỉ `retry_seconds`.
- Lấy lại: `restore_source` và theme_render `_source` thử kho (`kind = source`, kiểm sha) trước YouTube; file mượn cho ghép xóa sau job.

## Phải giữ nguyên

- Ngoại lệ khai thị (FIX-keep-khaithi-source), E5 enhance, CP8.32 dọc, grace `restored.json`; `[store]` tắt → hành vi cũ từng byte.
- API kho `hd` / `vertical` và `index.csv` hiện có; token không ghi log.
- TC3 fail closed khi nguồn không kiểm được; kiểm audio từng clip.

## Code bị thay / xóa

- Không có (chỉ thêm nhánh; YouTube vẫn là dự phòng cuối).

## Acceptance Criteria

1. Server / client nhận, liệt kê, HEAD, GET `source`; sai sha → không publish; `hd` / `vertical` không đổi.
2. `backup_source` bật: tự dọn và nút dọn chỉ xóa khi kho có đúng sha + size; kho tắt / sai sha → không xóa, file còn nguyên, `archive.json` không ghi.
3. Vòng nền đẩy đúng thứ tự (sắp đến hạn → ♥ → còn lại), bỏ đã có, gồm file cache `_theme_sources`, nghỉ khi kho tắt, không chạy khi có render đang chạy.
4. `restore_source` và ghép chủ đề lấy bản từ kho trước YouTube; sai sha → thử nguồn kế tiếp; file mượn cho ghép bị xóa sau job (cả khi lỗi).
5. Tab Bộ nhớ hiện "đã sao lưu N / M" và số còn chờ.
6. `backup_source` tắt → toàn bộ test cũ PASS không sửa.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_client.py tests/test_store_backup.py tests/test_restore_source_cp837.py tests/test_storage_cp86.py tests/test_theme_render.py tests/test_config.py -x --tb=short` — AC 1–5.
- `… -m pytest -q -n auto` (ORCHESTRATOR, ngoài sandbox) — AC 6.
- `node scripts/framework-check.mjs`; `git diff --check`.
- Chạy thật (sau khi HUMAN LEAD chép `store.py` lên 3090): đẩy 1 video ♥ (`xMUOoyHdIDs`, cache), HEAD khớp sha; mượn lại vào thư mục tạm và so sha.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / public API; chạm kênh VM ↔ 3090 (security model HD2, cùng token). Manual là gate trước khi bật `backup_source` trên 8080.

- [ ] Chép `tools/store/store.py` mới lên 3090, khởi động lại tác vụ kho; `GET /index` vẫn liệt kê bản HD Kinh Địa Tạng.
- [ ] Bật `backup_source` (agent hỏi trước khi sửa `config.toml` / restart 8080); sau một giờ tab Bộ nhớ hiện số đã sao lưu tăng; file `[Goc] …` xuất hiện trong thư mục bộ kinh trên E:.

## Result

- Main changes (IMPLEMENTER, 2026-10-25): đã triển khai bước 1–8; bàn giao ORCHESTRATOR review, **chưa đủ verification để chuyển lifecycle sang READY**. Không commit / push / PR, không gọi agent khác, không gọi dịch vụ thật.
- Files: `tools/store/store.py`; `src/auto_short/store/{client,backup}.py`; `src/auto_short/config.py`; `src/auto_short/review/archive.py`; `src/auto_short/theme_render/__init__.py` (`_source` + một lời gọi theo A1); `src/auto_short/web/{app,storage}.py`; `src/auto_short/web/static/{app.js,storage.html}`; bảy file test trong required verification; Result của contract này. Amendment A1 trong Owned paths do ORCHESTRATOR sửa trước khi IMPLEMENTER tiếp tục.
- Helper mới: `source_inventory` (mọi owner YouTube, gộp Short / khai thị, gồm archived; `favorite_videos` chỉ có ♥); `_source` / `_local_source` trong backup (đọc manifest, dùng lại `workspace_source`, `cached_source`, thêm trường hợp chỉ còn workspace khai thị); `_destination` (đã grep `backup.ps1`, `[HD Mobile]`, `Tập` trong web / source / tools, không tìm thấy generator; dùng lại `match_title`, `stored_series`, `clean_part`, `truncate_utf8`); `backup_state`, `push_source`, `backup_order` theo plan; `source_backup_pass` / `_source_backup_loop` theo mẫu vòng nền có sẵn; `StorageCache.update_source_backup` giữ kết quả HEAD ngoài request. Không cần sửa `borrow.py`: A1 cho phép dùng TemporaryDirectory hiện có của job.
- Chốt xóa đối chiếu SHA / size của từng file thực sắp xóa, băm sau khi HEAD trả lời; lỗi không ghi `archive.json`. Vòng nền tối đa một PUT / lượt, nhường làn render, nghỉ `retry_seconds`, cho video khác tiếp tục khi một bản bị kho từ chối. Restore giữ kiểm ingest chính xác; ghép chủ đề vẫn kiểm audio từng clip, file mượn được dọn cùng `.render-` kể cả lỗi / hủy.
- Diff ứng dụng (`src/` + `tools/`, tính cả file mới): **+302 / −9**; test: **+562 / −0**. Không sửa assertion cũ.

| AC | Test / bằng chứng |
|---|---|
| 1 | `test_store_server.py::test_source_put_index_head_get_and_bad_sha`; test client streaming / ánh xạ HTTP; `test_source_put_real_server_roundtrip` chờ ORCHESTRATOR |
| 2 | `test_store_backup.py`: archive thiếu bản / sai SHA / sai size / kho tắt / cache khác ingest / file dư / đổi byte trong HEAD đều giữ nguyên nguồn; đúng bản ghi backup; `test_auto_archive_waits_for_source_backup` |
| 3 | `test_store_backup.py`: ưu tiên hạn dọn → ♥ → còn lại, bỏ đã có / local, nguồn cache, khai thị-only; mỗi lượt một file, nhường render, kho tắt, bản xung đột không chặn bản khác. Test vòng asyncio / thread / retry chờ ORCHESTRATOR |
| 4 | `test_restore_source_cp837.py::test_src1_*`; `test_theme_render.py::test_src1_*`: kho trước YouTube, lỗi / SHA sai dự phòng, cleanup khi thành công / encode lỗi / hủy |
| 5 | `test_storage_cp86.py::test_src1_storage_reports_only_background_results`; kiểm report cache trong `test_store_backup.py`; `node --check` cho JS |
| 6 | Các test cũ thuộc lượt chạy bên dưới không đổi và PASS; full suite chờ ORCHESTRATOR |

Lệnh cuối cho toàn bộ test không cần socket (251 PASS, 22 deselected, 1 cảnh báo deprecation TestClient có sẵn; 37,74 s):

```sh
timeout 120 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src1-source-backup/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_server.py tests/test_store_client.py tests/test_store_backup.py tests/test_restore_source_cp837.py tests/test_storage_cp86.py tests/test_theme_render.py tests/test_config.py -k 'not background_io_uses_thread and not client_index_head_fetch and not client_resumes and not client_sha_mismatch and not client_bad_token and not source_put_real_server and not vertical_uses and not kt_owner_vertical and not run_render_uses and not concurrent_borrowers and not store_down_missing and not vertical_job_waits and not render_job_waits and not store_off_keeps and not http_auth_and_restore and not storage_api_and_page and not old_render_recommended and not disk_status_and_submit and not archive_route_and_archived and not archive_refused_while_job_active' -x --tb=short
```

- Các lượt test liên quan trước đó: 160 PASS; 168 PASS / 13 deselected; 80 PASS / 8 deselected; 170 PASS / 14 deselected. Không tính các lượt này thành coverage bổ sung của trạng thái cuối.
- `timeout 120 node scripts/framework-check.mjs`: PASS; `git diff --check`: PASS; `timeout 120 node --check src/auto_short/web/static/app.js`: PASS.
- Không chạy thành công: lượt `timeout 120 … -m pytest -q tests/test_store_backup.py tests/test_config.py tests/test_store_server.py -x --tb=short` gặp test mới `test_background_io_uses_thread_and_waits_retry_seconds`, hết timeout (124). Chẩn đoán riêng `timeout 15 … -m pytest -q tests/test_store_backup.py::test_background_io_uses_thread_and_waits_retry_seconds -o faulthandler_timeout=5 -x --tb=short` cũng 124; traceback thấy main thread chờ `selectors.select`, executor thread nhàn rỗi. Chưa chứng minh test vòng asyncio này PASS ngoài sandbox.
- Không chạy theo giới hạn: các test server loopback thật / TestClient, full suite `… -m pytest -q -n auto`, và manual đẩy / HEAD / mượn từ 3090. ORCHESTRATOR cần chạy required verification đầy đủ; manual vẫn là gate trước khi bật cấu hình trên 8080.
- Điểm cần review: I/O quét SHA khi lập thứ tự chưa benchmark với 188 nguồn thực; hành vi thread / retry và PUT qua socket cần xác minh ngoài sandbox. `backup_source` vẫn mặc định false; không sửa cấu hình vận hành.

### Review vòng 2 — F1 / F2 / F3

- Đã sửa `store/client.py`, `store/backup.py`, vòng sao lưu trong `web/app.py`, `test_store_client.py`, `test_store_backup.py`. Không sửa server, source validators hoặc quyết định xóa trong vòng này.
- F1: PUT HEAD trước khi gửi body; trùng SHA + size thì bỏ gửi, khác thì `StoreMismatch`. PUT 413 / 422 được ánh xạ `StoreMismatch`; series sai định dạng được từ chối trước khi gửi để tránh 400 sớm gây đứt luồng tương tự. Mọi `StoreError` trong `push_source` đều nhường lượt cho video kế. Bản ingest đúng SHA + size trên kho được tính là đã sao lưu dù cache khác byte; archive với `path` vẫn chỉ chấp nhận đúng file sắp xóa.
- F2: `_SourceMemo` / `_signature` / `_memo` giữ `(path, sha, size)` theo workspace, URL kho, video và chữ ký stat của nguồn, manifest, metadata thời lượng, cache và meta cache (path, dev, inode, size, mtime_ns, thêm ctime_ns). Chữ ký không đổi: không đọc lại nội dung video; xác nhận remote cùng SHA + size được dùng lại, không HEAD các video đã xong. Video chưa xong vẫn HEAD. Hash / HEAD tươi của nhánh archive không dùng memo. Dùng lại validator nguồn hiện có và SHA mà validator vừa kiểm, tránh hash lần hai.
- F3: `push_source` lấy SHA từ memo; sau PUT chỉ HEAD so với SHA + size đã gửi, không hash lại.
- Test mới / mở rộng: HEAD phát hiện trùng / khác SHA / khác size mà không gửi body; HTTP 413 / 422; PUT 200 / 201; series sai; lỗi gửi `StoreUnavailable` không chặn hàng; ingest trên kho tốt hơn cache; lượt order thứ hai không hash hoặc HEAD video đã xong, chưa xong vẫn HEAD; mtime / size / metadata cache / thời lượng thay đổi làm mất hiệu lực memo; cold push chỉ hash một lần; push dùng memo và không hash sau PUT; archive bỏ qua memo.
- Diff riêng vòng 2 (so với lúc nhận finding, không tính tài liệu): ứng dụng **+114 / −23**, test **+189 / −7**.
- Lượt 7 file với nguyên lệnh `timeout 120 … pytest … -k … -x --tb=short` ở Result bên trên: **265 PASS, 22 deselected**, 37,90 s. Sau điều chỉnh xóa xác nhận memo cũ khi HEAD không còn khớp, chạy lại hai file liên quan: **39 PASS, 14 deselected**, 1,43 s:

```sh
timeout 120 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src1-source-backup/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_backup.py tests/test_store_client.py -k 'not background_io_uses_thread and not client_index_head_fetch and not client_resumes and not client_sha_mismatch and not client_bad_token and not source_put_real_server and not vertical_uses and not kt_owner_vertical and not run_render_uses and not concurrent_borrowers and not store_down_missing and not vertical_job_waits and not render_job_waits and not store_off_keeps' -x --tb=short
```

- `timeout 120 node scripts/framework-check.mjs` và `git diff --check`: PASS. Không chạy lại các test cần socket / asyncio đã treo ở vòng trước; đặc biệt `test_source_put_real_server_roundtrip` vẫn cần ORCHESTRATOR chạy ngoài sandbox. Full suite và manual 3090 chưa chạy; không tuyên bố PASS hoặc chuyển lifecycle READY khi các gate đó chưa hoàn tất. Chưa benchmark cold scan với 188 file thật; test đếm hash đã xác minh lượt không đổi không đọc lại video.

### ORCHESTRATOR (Claude Code, 2026-10-25)

- Codex 3 vòng (session `01a17225…`): vòng 1 BLOCKED vì scope (`render_landscape` ngoài Owned paths) → amendment A1, 76 893 tokens; vòng 2 bước 1–8, ≈ 17 phút, 153 437 tokens; vòng 3 sửa finding, ≈ 11 phút, 204 072 tokens. Không chuyển Sonnet (quota Codex 5 giờ 20 %, tuần 3 %).
- Finding vòng 2 (đã sửa vòng 3): F1 PUT vào kho đã có bản khác sha → server trả 409 trước khi đọc body, client thấy `URLError` → `StoreUnavailable`, vòng nền kẹt đầu hàng mãi (`test_source_put_real_server_roundtrip` FAIL ngoài sandbox); F2 `backup_order` băm lại mọi nguồn (≈ 63 GB × 2) mỗi `retry_seconds`; F3 `push_source` băm 3 lần.
- Còn lại (chấp nhận): lượt đầu sau mỗi lần khởi động web băm toàn bộ nguồn một lần (memo trong tiến trình); video push lỗi bị bỏ qua tới khi mọi ứng viên khác đã thử.
- Verification ngoài sandbox trên diff cuối: 7 file required + `tests/test_web_app.py`: **309 PASS**; full suite `-n auto`: **2796 PASS, 1 skipped** (132 s); `node scripts/framework-check.mjs` PASS; `git diff --check` PASS.
- Chưa chạy: "chạy thật" 3090 (cần HUMAN LEAD chép `tools/store/store.py` lên 3090) → PR mở draft, READY sau bước này.
