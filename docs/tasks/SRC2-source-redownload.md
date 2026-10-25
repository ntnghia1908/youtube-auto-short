# Task: SRC2 — Tải lại toàn bộ video gốc đã xóa lên kho 3090

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC1-source-backup-3090.md` G4a + G8 (HUMAN LEAD 2026-10-25: "Tải hết toàn bộ video nguồn về backup để khi xử lý không còn phụ thuộc youtube chặn"); decision ACCEPTED 2026-10-25; G8a (A2) HUMAN LEAD 2026-10-25
- Parallel group: —
- Owned paths: `src/auto_short/store/redownload.py` (mới); `src/auto_short/theme_render/sources.py` (chỉ tách hàm kiểm / tải dùng chung, coi 403 là "chặn" trong đường tải lại); `src/auto_short/web/app.py` (chỉ wiring vòng tải lại nền); `src/auto_short/web/storage.py` + `src/auto_short/web/static/` phần tab Bộ nhớ (dòng tiến độ tải lại); `tests/test_store_redownload.py` (mới), `tests/test_theme_source_cache.py`; file này; amendment A1 (ORCHESTRATOR, 2026-10-25, cờ `[store] redownload` đã nêu ở mục Authority cần nơi khai báo): `src/auto_short/config.py` (chỉ `StoreConfig.redownload`), `tests/test_config.py`; amendment A2 (HUMAN LEAD 2026-10-25 "Tải luôn video chưa xử lý", decision G8a): cùng Owned paths, thêm video playlist chưa ingest
- Dependencies: SRC1 (kind `source`, `push_source`, `backup_state`) — làm sau SRC1 merge
- Base commit / branch: `5b8da78` (`feature/src1-source-backup`, PR #154 READY chưa merge; PR SRC2 xếp chồng, rebase lên main sau khi #154 merge) / `feature/src2-source-redownload`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt tất cả theo đề xuất"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì: tạo lưu lượng tải YouTube nền kéo dài (≈ 1,5 ngày) từ IP production và ghi dữ liệu lên 3090.

## Goal

Mọi tập đã bị dọn nguồn có bản video gốc trên 3090 (kiểm kê 2026-10-25: 116 tập, 63,4 GB; 4 video ♥ VLT tập 16, 17, 19, 20 trước), tải chậm để không bị YouTube chặn. Từ đó ghép chủ đề / khôi phục nguồn lấy từ 3090 (SRC1 G5), không cần YouTube.

## Scope

- In scope: SRC1 G8 + phần tải lại của G4a; CLI kiểm kê `python -m auto_short.store.redownload --config … --dry-run`.
- In scope (A2): video trong `work/_playlists/*.json` chưa có workspace (G8a, 488 video ≈ 480 giờ), xếp sau tập `archived`.
- Out of scope: ingest / prepare lấy nguồn từ 3090 (SRC4); chọn / đổi chất lượng tải; xóa trên 3090; nâng yt-dlp (TC3.2 G3).

## Authority / key decisions

- SRC1 G8: một video mỗi lượt, nghỉ ngẫu nhiên 600–1200 s, backoff khi chặn (dùng lại tham số và vòng của `sources.run`), chỉ khi làn prepare rảnh và `youtube_status` không đang backoff; kho tắt → nghỉ `retry_seconds`.
- Cục bộ (ORCHESTRATOR): tải vào thư mục tạm dưới `work/_theme_sources/` (cùng ổ, rename được); ♥ → giữ làm cache (`meta.json` như TC3.1) và đẩy; không ♥ → đẩy xong xóa bản tạm. Đầy đĩa (< 20 GB trống) → dừng, ghi log. Cờ `[store] redownload` (mặc định tắt) bật / tắt vòng này.

## Implementation approach

- Tách phần tải + kiểm thời lượng / sha của `fetch_to_cache` thành hàm dùng chung (giữ hành vi `fetch_to_cache`).
- `redownload.py`: `pending(config)` (tập `archived`, chưa có ở kho / cache, thứ tự ♥ → bộ kinh → tập), `step(config, …)` tải một video → `push_source` → dọn, trả trạng thái; `main` cho `--dry-run`.
- Web: vòng nền như `auto_archive_pass`, gọi `step` khi đủ điều kiện; tiến độ "tải lại nguồn: đã xong N / M, đang chờ YouTube đến …" trên tab Bộ nhớ.

## Phải giữ nguyên

- CLI `python -m auto_short.theme_render.sources` và cache TC3.1; `archive.json` / restore CP8.37; FIX-youtube-botcheck-wait cho job prepare thường (vòng này nhường job thật).

## Code bị thay / xóa

- Không có (tách hàm, không xóa).

## Acceptance Criteria

1. `pending` liệt kê đúng tập đã xóa chưa có bản ở kho / cache, ♥ trước; `--dry-run` không ghi, không mạng.
2. `step` tải → kiểm thời lượng → đẩy kho → xác nhận HEAD → xóa bản tạm (không ♥) / giữ cache (♥); lỗi ở bất kỳ bước nào không để file dở, không ghi sai `meta.json`.
3. 403 / bot-check / 429 → backoff, không đánh dấu hỏng; lỗi khác → ghi lý do, bỏ qua video, sang video kế sau khoảng nghỉ.
4. Vòng nền không chạy khi prepare bận, YouTube backoff, kho tắt hoặc đĩa < 20 GB; cờ tắt → không chạy.
5. Full suite PASS.
6. (A2) `pending` thêm video playlist chưa có workspace, bỏ `available` false / đã có trên kho / cache, xếp sau `archived`; `step` kiểm thời lượng với `duration` của playlist entry, không tạo workspace / sửa playlist, tên `[Goc] <bộ kinh> - Tập N.mp4` trong thư mục playlist, đẩy + HEAD rồi xóa bản tạm; `--dry-run` và tab Bộ nhớ tách hai nhóm.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_redownload.py tests/test_theme_source_cache.py tests/test_store_backup.py -x --tb=short` — AC 1–4.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật: `--dry-run` trên dữ liệu thật ra 116 (hoặc số mới) và 4 ♥ đầu danh sách, nhóm chưa xử lý ≈ 488; bật cờ trên 8080 (hỏi trước khi sửa `config.toml` / restart), 1 video ♥ về cache + có trên 3090.

## Manual test checklist (Tech Lead)

Không chạm database / public API; tạo lưu lượng YouTube nền (gate: HUMAN LEAD bật cờ).

- [ ] Sau 1–2 giờ: tab Bộ nhớ tiến độ tăng; thư mục bộ kinh trên E: có `[Goc] …` mới.
- [ ] Ghép lại "Chuyển hóa tâm niệm" (VLT) sau khi 4 video ♥ xong.

## Result

- **A2 (2026-10-25): IMPLEMENTER hoàn tất**, trên baseline `431fc15` (lượt SRC2 đầu + decision G8a / amendment A2 đã được commit từ bên ngoài). Chờ ORCHESTRATOR review / verification ngoài sandbox; chưa xác nhận AC5 / chuyển READY. Không commit, push, PR, gọi agent khác hay dịch vụ thật.
- Files sửa trong A2: `src/auto_short/store/redownload.py`, `src/auto_short/theme_render/sources.py`, `src/auto_short/web/app.py`, `src/auto_short/web/storage.py`, `src/auto_short/web/static/app.js`, `tests/test_store_redownload.py`, `tests/test_theme_source_cache.py`, contract này. Không sửa decision / `backup.py`, config hoặc test cũ.
- Main changes: `pending` thêm video playlist chưa có workspace thường / owner `.kt`, bỏ unavailable / trùng / cache hợp lệ / source trên kho, xếp sau archived rồi theo playlist / số tập. Dry-run in hai nhóm, giờ từng nhóm và tổng, vẫn chỉ đọc cục bộ và báo chưa đối chiếu kho. Video chưa ingest dùng URI canonical + duration playlist để kiểm cùng dung sai; không tạo workspace / sửa playlist / giữ cache / ghi ingest sha hay `differs_from_ingest`. PUT đúng file, HEAD sha + size rồi dọn tạm. Tab Bộ nhớ hiện riêng `đã dọn: N / M; chưa xử lý: N / M` từ snapshot nền, giữ trạng thái tải / backoff / tạm dừng.
- Tìm / tái dùng A2: `rg -n 'def .*entry|def .*playlist|available|duration|owner_for' src/auto_short/web/playlists.py src/auto_short/titling/playlist.py src/auto_short/enhance/state.py`; đọc `_destination`, `cached_source`, `download_verified`. `_destination` hiện đã đặt tên từ playlist khi không có manifest, nên dùng nguyên helper này, không copy formatter hay sửa SRC1. Dùng lại `owner_for`, `canonical_url`, `read_json_dict`, `_positive`, `_matches_duration` (qua helper chung), probe/hash và `StoreClient.put/head/index`.
- Helper mới A2: `unprocessed_entries` đọc / lọc tham chiếu playlist mà không tạo workspace; `local_groups` gom kiểm kê cục bộ theo hai nhóm (không có helper cũ nào kết hợp inventory archived + playlist chưa ingest). Helper mở rộng: `cached_source(..., reference=...)` kiểm cache TC3 còn nguyên sau khi workspace mất, so URI/video, thời lượng, provenance nội bộ, size + SHA; `download_verified(..., reference=...)` kiểm tải không cần manifest, không bịa provenance; `pending(..., groups=...)` trả nhóm cho counters. `local_pending`, `step`, `main` và wiring / snapshot hiện có được tái dùng, không thêm dependency.

| AC | Test / bằng chứng |
|---|---|
| 1–4, A1 | Toàn bộ test targeted cũ giữ nguyên và chạy cùng test mới; kiểm kê / dry-run, PUT + HEAD / cache / cleanup, 403 / bot-check / 429 / fairness, gate prepare đang chạy / chờ, kho / disk / node / flag, thread + lifespan và config vẫn PASS ở lệnh bên dưới |
| 6 (A2) | `test_a2_pending_groups_order_cache_workspace_and_offline_hours`: nhóm / thứ tự numeric / dedup, unavailable / malformed, workspace thường / `.kt` kể cả chưa có manifest, cache hợp lệ / hỏng, một index, dry-run hai nhóm + giờ và snapshot file không đổi |
| 6 (A2) | `test_a2_step_playlist_duration_naming_no_provenance_or_workspace` (14 trường hợp): dung sai ở biên / quá biên, duration thiếu / NaN / 0, unavailable, tên theo episode / title playlist, download / PUT / HEAD / sha lỗi, 403 / Ctrl-C, không provenance / workspace / sửa playlist / cache, dọn partial |
| 6 (A2) | `test_a2_background_group_progress_and_readonly_storage`: archived trước, hai counters tiến 0→2 / nhóm; storage request không tạo client / gọi mạng |
| TC3 regression | `test_playlist_reference_validates_cache_after_workspace_removal` (7 trường hợp): URI khác / sai kiểu, sha, duration, provenance, bytes; default policy vẫn cần manifest. Test cache / CLI cũ và `tests/test_theme_render.py` giữ PASS |
| 5 | Chưa chạy full suite trong sandbox; ORCHESTRATOR phải chạy ngoài sandbox, cùng test async SRC1 bị loại bên dưới |

Verification A2 (2026-10-25, `PYTHONPATH` đúng worktree):

```sh
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src2-source-redownload/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_redownload.py tests/test_theme_source_cache.py tests/test_store_backup.py tests/test_config.py -k 'not test_background_io_uses_thread_and_waits_retry_seconds' -x --tb=short
# 185 passed, 1 deselected in 4.75s.
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src2-source-redownload/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_render.py -x --tb=short
# 35 passed in 28.09s.
timeout 60 node scripts/framework-check.mjs
# exit 0, PASS: framework structure; output A2 lưu /tmp/src2-a2-framework-check.log.
git diff --check
timeout 60 node --check src/auto_short/web/static/app.js
# cả hai exit 0.
```

- Giữ `-k` loại đúng test async SRC1: lượt trước chạy riêng `timeout 30 env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_backup.py::test_background_io_uses_thread_and_waits_retry_seconds -x --tb=short -o faulthandler_timeout=10` → timeout / exit 124 tại `selectors.select` / `asyncio.run`. Không chạy lại test này trong A2, không sửa test cũ và không tuyên bố PASS cho nó. Test lifecycle SRC2 dùng điều khiển coroutine + thread thật, không socket, đã PASS.
- Không chạy full suite `python -m pytest -q -n auto`, TestClient / server thật, CLI trên dữ liệu production, YouTube / kho 3090 / Ollama, bật config / restart 8080: theo giới hạn sandbox. ORCHESTRATOR / HUMAN LEAD còn kiểm AC5, dry-run thật hai nhóm và tải thử.
- Diff A2 so với `431fc15` (`git diff --stat -- src tests`): **7 files, +279 / −48**; ứng dụng **+131 / −48**, tests **+148 / −0**. Contract cập nhật Result riêng; không có file mới / untracked.
- ORCHESTRATOR review + verification ngoài sandbox (2026-10-25): Codex 2 lượt cùng session (`01a17308…`): lượt 1 117 696 tokens, A2 176 063 tokens; không chuyển Sonnet (quota 5 giờ 26 %). Review không có finding chặn.
- 6 file targeted (redownload, theme_source_cache, store_backup, config, storage_cp86, web_app; gồm test async SRC1 từng treo trong sandbox): **228 PASS**. Full suite `-n auto`: **2856 PASS, 1 skipped** (135 s). `node scripts/framework-check.mjs`, `git diff --check`: PASS.
- Dry-run dữ liệu thật: **Đã dọn 49 video (49,3 giờ, ≈ 26,8 GB), 0 ♥; Chưa xử lý 488 video (479,4 giờ)**; tổng 537. Chênh với kiểm kê "116 / 4 ♥": 130 `archive.json` là workspace (Short + `.kt`) của 68 video; 18 video đã có trong `_theme_sources` (4 ♥ đã được job ghép VLT tải về) → còn 49.
- Chạy thật 8080 (2026-10-25, HUMAN LEAD duyệt "Có, bật cả hai"): `config.toml` `[store] backup_source = true`, `redownload = true`; 8080 restart ở `c3355ed`. Lượt đầu: SRC1 sao lưu `5wv5_Q0Utn8` (♥ VLT T17, 491 331 773 B), sha kho = sha `_theme_sources` `a5ca8fac…`; SRC2 tải lại `Bi7kVGbnPfE` (VLT T1, đã dọn) → kho xác nhận sha `e2c35af2…` 689 211 693 B, không còn thư mục `.…-redownload-` trên VM. **PASS**. Manual 1–2 giờ (tiến độ tab Bộ nhớ, `[Goc] …` trên E:) do HUMAN LEAD xem.
