# Task: SRC2 — Tải lại toàn bộ video gốc đã xóa lên kho 3090

## Status / Approval

- Status: IN_PROGRESS
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

- IMPLEMENTER hoàn tất trong Owned paths + A1; chờ ORCHESTRATOR review / verification ngoài sandbox, chưa xác nhận AC5 / chuyển READY. Không commit, push, PR, gọi agent khác hay dịch vụ thật.
- Files: `src/auto_short/config.py`, `src/auto_short/theme_render/sources.py`, `src/auto_short/store/redownload.py` (mới), `src/auto_short/web/app.py`, `src/auto_short/web/storage.py`, `src/auto_short/web/static/app.js`, `src/auto_short/web/static/storage.html`, `tests/test_store_redownload.py` (mới), `tests/test_theme_source_cache.py`, `tests/test_config.py`, contract này.
- Main changes: cờ `store.redownload` mặc định tắt + validate; kiểm kê archived theo ♥ → playlist → số tập bằng một index; CLI dry-run chỉ đọc cục bộ, báo chưa đối chiếu kho và tổng / ♥ / GB; tải riêng từng file, kiểm bằng helper chung, PUT đúng file + HEAD sha/size trước publish cache ♥ hoặc xóa tạm; backoff riêng 3600–21600 s, gap 600–1200 s, fairness lỗi thường; vòng nền `to_thread` nhường prepare đang chạy / chờ và kiểm YouTube, kho, node, đĩa ≥ 20 GB; cancel trong lifespan; tab Bộ nhớ chỉ đọc snapshot.
- Tìm / tái dùng: đã đọc `store/backup.py`, `store/client.py`, `theme_render/sources.py`, `web/storage.py`; dùng `rg -n 'StoreConfig|backup_source|store ='`, `rg -n 'source_backup|lifespan|auto_archive|youtube_status'`, `rg -n 'def running|def .*queued|def youtube_status|def jobs|def list|lane|def pending'` để tìm API sẵn có. Tái dùng `_local_source`, `_source`, `_destination`, `_matches`, `favorite_videos`, `is_archived`, `iter_manifests`, `StoreClient.put/head/index`, `atomic_write_json` và probe/hash hiện có. Không dùng trực tiếp `push_source` vì nó chọn workspace/cache, còn SRC2 phải gửi đúng file vừa tải chưa publish.
- Helper mới: `download_verified` tách tải / kiểm khỏi `fetch_to_cache`, giữ exception policy tại caller; `local_pending` kiểm kê không mạng cho dry-run, `pending` lọc bằng index; `free_bytes` kiểm ổ của work; `_publish_cache` publish nguyên directory và rollback cache cũ khi rename lỗi; `step` điều phối một video; `main` dry-run; `redownload_pass` / `_redownload_loop` giữ scheduling / backoff; `StorageCache.update_redownload` lưu snapshot. Không có helper hiện hữu kết hợp kiểm kê offline / tải riêng rồi PUT + HEAD trước publish; không thêm dependency.

| AC | Test / bằng chứng |
|---|---|
| 1 | `test_pending_inventory_order_single_index_and_local_only_dry_run`: archived / YouTube / owner `.kt`, loại workspace/cache/kho, ♥ trước, số tập 2 trước 10, một index, snapshot file không đổi, cấm tạo client trong dry-run |
| 2 | `test_step_exact_bytes_head_cache_provenance_and_cleanup`; `test_step_failures_clean_temporary_and_preserve_old_entry` (14 trường hợp: tải, kiểm, PUT/HEAD, metadata, rename, Ctrl-C); `test_shared_download_validates_private_file_without_publishing` |
| 3 | `test_background_blocked_backoff_doubles_caps_and_retries_same_video`; `test_background_generic_error_moves_on_then_retries_after_others`; `test_fetch_http403_remains_normal_error` — 403 chỉ đổi policy ở SRC2, prepare / CLI nguồn giữ policy cũ |
| 4 | `test_background_gates_never_download` (10 gate, gồm prepare mới bận sau index); `test_step_low_disk_stops_before_store_or_temp`; `test_background_thread_sleep_snapshot_and_lifespan_cancellation` (điều khiển coroutine trực tiếp, thread thật, không socket) |
| A1 | `test_source_redownload_config`: mặc định tắt, bật hợp lệ, thiếu enabled và sai kiểu đều ConfigError |
| 5 | Chưa chạy full suite trong sandbox; ORCHESTRATOR phải chạy ngoài sandbox, cùng test async SRC1 bị loại bên dưới |

Verification (2026-10-25, `PYTHONPATH` trỏ đúng worktree):

```sh
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src2-source-redownload/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_redownload.py tests/test_theme_source_cache.py tests/test_store_backup.py tests/test_config.py -k 'not test_background_io_uses_thread_and_waits_retry_seconds' -x --tb=short
# 162 passed, 1 deselected (4.42 s ở lượt cuối trước ghi Result).
timeout 240 env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src2-source-redownload/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_render.py -x --tb=short
# 35 passed in 28.45s.
timeout 60 node scripts/framework-check.mjs
# exit 0, PASS: framework structure (và các checks thành phần).
git diff --check
timeout 60 node --check src/auto_short/web/static/app.js
# cả hai exit 0.
```

- Lệnh targeted ban đầu không `-k` timeout 240 s (exit 124) ở test lifecycle asyncio bản đầu của SRC2. Hai lượt chẩn đoán riêng test này với `timeout 30` (một lượt `-vv -o faulthandler_timeout=10`) cũng exit 124; đã thay test mới bằng điều khiển coroutine / thread, không event loop socket. Test cũ giữ nguyên.
- Chạy riêng `timeout 30 env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_backup.py::test_background_io_uses_thread_and_waits_retry_seconds -x --tb=short -o faulthandler_timeout=10` → exit 124; stack dừng tại `selectors.select` / `asyncio.run`, không phải assertion fail. Vì vậy deselect đúng test này ở lệnh targeted; không tuyên bố PASS cho nó.
- Không chạy `python -m pytest -q -n auto`, TestClient / server thật, CLI trên dữ liệu production, tải YouTube / kho 3090 / Ollama, bật config / restart 8080: theo giới hạn và phân công sandbox của HUMAN LEAD. Full suite, dry-run dữ liệu thật và thử một video ♥ thuộc ORCHESTRATOR / HUMAN LEAD.
- Diff (source + tests, gồm hai file mới chưa stage): **10 files, +723 / −17**; ứng dụng **+319 / −17**, tests **+404 / −0**. `git diff --stat -- src tests` cho 8 file tracked: +204 / −17; `git diff --no-index --stat /dev/null src/auto_short/store/redownload.py`: +142; tương tự `tests/test_store_redownload.py`: +377. Contract bổ sung Result riêng.
- Có thay đổi ngoài task xuất hiện trong session ở `docs/decisions/SRC1-source-backup-3090.md` (G8a); IMPLEMENTER không sửa / revert / tính vào diff task và không mở rộng SRC2 sang video chưa ingest.
