# Task: FIX-theme-store-index — ghép chủ đề dùng chung snapshot kho của SRC4 (`store/index_cache`)

## Status / Approval

- Status: READY
- Type: REFACTOR
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`): gộp hai cache cùng chức năng
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-26 ("làm luôn 2 FIX", sau đề xuất trong `docs/workflow/current-state.md` Next action 4); contract TC3.2 / SRC4 (READY, đã merge #159, #160)
- Parallel group: FIX-store-wait-persist (đường dẫn rời nhau)
- Owned paths: `src/auto_short/store/index_cache.py`, `src/auto_short/web/theme_plan.py`, `src/auto_short/store/backup.py` + `src/auto_short/store/redownload.py` (chỉ gọi `index_cache.invalidate()` sau khi kho xác nhận), `tests/test_web_theme_plan.py`, `tests/test_src4_ingest_store.py` hoặc test mới `tests/test_store_index_cache.py`, file này
- Dependencies: none
- Base commit / branch: `2c29133` (`main`) / `fix/theme-store-index`
- Human Lead approval: APPROVED (2026-10-26)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Một snapshot `/index` kho duy nhất trong tiến trình web: TC3.2 (`theme_plan.StoreSources`) và SRC4 (`store/index_cache`) không gọi `/index` riêng nữa; nguồn vừa đẩy lên kho (SRC1 / SRC2) được thấy ngay ở lượt đọc sau.

## Bối cảnh (2026-10-26, ORCHESTRATOR)

- `web/theme_plan.py:92` `StoreSources`: snapshot 5 phút, không chặn, lọc dòng `kind == "source"` có `sha256` hợp lệ (`SHA`), lỗi kho → rỗng. Dùng ở `needs_download` (gọi khi giữ khóa scheduler → không được chờ mạng) và `view()`.
- `store/index_cache.py` (SRC4): snapshot 5 phút toàn tiến trình, chế độ `blocking=False` không chờ, lỗi kho → rỗng 5 phút, có listener khi làm mới, `invalidate()`. Không lọc sha256.
- Hai cache trùng chức năng → hai lần gọi `/index` mỗi 5 phút, và có thể lệch nhau. `push_source` (SRC1) và `redownload.step` (SRC2) không invalidate → nguồn mới chỉ thấy sau tối đa 5 phút.

## Scope

- In scope: thêm vào `index_cache` một hàm đọc tập `video_id` nguồn (vd. `source_ids(config, *, blocking=False) -> frozenset[str]`) chỉ gồm dòng có sha256 64 hex; `theme_plan` dùng hàm này (không chặn) thay `StoreSources`, xóa class `StoreSources` và `self.store_sources`; gọi `index_cache.invalidate()` sau khi `push_source` / `redownload.step` được kho xác nhận. Cập nhật test `StoreSources` thành test cho hàm mới (không gọi mạng thật, TTL, lỗi kho, kho tắt).
- Out of scope: định dạng `/index`, `tools/store/store.py`, logic chọn nguồn ingest / restore của SRC3 / SRC4, UI.

## Authority / key decisions

- TC3.2: request thread / khóa scheduler không bao giờ chờ kho (giữ: dùng `blocking=False`).
- SRC4: snapshot toàn tiến trình, TTL 300 s, lỗi kho được cache (giữ).
- S1 cục bộ: lọc sha256 chỉ áp cho tập id mới (dòng thiếu sha256 không dùng được cho ghép chủ đề); `source_entry` / `has_source` của SRC4 giữ nguyên hành vi.

## Implementation approach

- `index_cache.source_ids`: đọc snapshot hiện có giống `source_entry` (khởi động làm mới nền khi hết hạn, không chờ khi `blocking=False`), trả `frozenset` id có `SHA` hợp lệ; kho tắt → rỗng. Tách phần dùng chung với `source_entry` thành helper nội bộ thay vì chép code.
- `theme_plan`: thay hai chỗ `.snapshot()` bằng `index_cache.source_ids(config, blocking=False)`; xóa `StoreSources`, import `StoreClient` / `StoreError` nếu không còn dùng.
- `backup.push_source` / `redownload.step`: `index_cache.invalidate()` ngay sau khi HEAD xác nhận khớp.

## Phải giữ nguyên

- Hành vi `source_entry`, `has_source`, listener, `invalidate`; kết quả `view()` / `needs_download` với cùng dữ liệu kho; mọi test SRC4 / TC3.2 / SRC1 / SRC2 hiện có.

## Code bị thay / xóa

- Xóa `theme_plan.StoreSources` (và thuộc tính `store_sources` của service); test `test_sources_store_snapshot_async_ttl_and_failure_without_http` thay bằng test tương đương cho `index_cache.source_ids`.

## Acceptance Criteria

1. Không còn `StoreSources`; `grep -rn "StoreClient.from_config(.*).index()" src/` chỉ còn trong `index_cache` (và client / công cụ CLI không thuộc web nếu có).
2. `source_ids` không chặn, lọc sha256, TTL 300 s, lỗi kho → rỗng, kho tắt → rỗng; `needs_download` / `view()` cho kết quả như trước.
3. Sau `push_source` / `redownload.step` thành công, lượt đọc sau thấy nguồn mới (snapshot bị invalidate).
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_theme_plan.py tests/test_src4_ingest_store.py tests/test_theme_index.py tests/test_store_client.py` + test mới nếu có — AC 1–3 (TestClient: ORCHESTRATOR chạy nếu sandbox không chạy được).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4 (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

- [ ] Không bắt buộc: trang ghép chủ đề vẫn đếm đúng "kho" / "YouTube" trong ô Nguồn (ORCHESTRATOR xem qua API sau restart).

## Handoff

- Outgoing / incoming ORCHESTRATOR: —
- Nguồn duyệt chuyển giao: —
- Phase / blocker / next action: giao Codex.
- HEAD + working tree lúc bàn giao: —

## Result

- Main changes: thêm `index_cache.source_ids(config, *, blocking=False)` trả `frozenset[str]` đã lọc SHA `[a-f0-9]{64}`, dùng `_snapshot` chung với `source_entry`; `theme_plan` dùng cache chung ở `needs_download` / `view`, xóa `StoreSources`. Giữ `SHA`, `StoreClient`, `StoreError` vì vẫn có caller khác. `push_source` / `redownload.step` invalidate ngay sau HEAD xác nhận, không tạo import vòng.
- AC → test:
  - AC1: `grep -rn "StoreSources\|store_sources" src/ tests/` không có kết quả; `grep -rn "StoreClient.from_config(.*).index()" src/` chỉ còn `store/index_cache.py`.
  - AC2: `tests/test_web_theme_plan.py::test_sources_store_snapshot_async_ttl_and_failure_without_http` kiểm cache nguội, gọi từ thread khác không chặn, refresh nền, TTL đúng 300 s, lỗi được cache, kho tắt, lọc kind / SHA và dùng chung snapshot với `source_entry` / `has_source`. Test `test_needs_download_store_snapshot_bypasses_youtube_backoff_without_http`, `test_sources_view_counts_distinct_owners_without_io`, `test_sources_real_view_without_http` giữ assertion và kiểm `blocking=False`; tests SRC4 giữ nguyên.
  - AC3: `tests/test_store_index_cache.py::test_confirmed_upload_invalidates_source_snapshot` (4 cases: push / redownload × HEAD khớp / không khớp) kiểm generation/cache và lượt đọc sau thấy nguồn mới, HEAD không khớp không invalidate. Cache được invalidate setup/teardown; fake store/downloader, không mạng thật.
  - AC4 (ORCHESTRATOR 2026-10-26): targeted `test_store_index_cache.py test_web_theme_plan.py test_src4_ingest_store.py test_theme_index.py test_store_client.py` **259 passed**; full suite `-n auto` **2996 passed, 1 skipped**; `framework-check` PASS; `git diff --check` PASS. ORCHESTRATOR review: regex sha256 biên dịch sẵn (`index_cache.SHA256`). Codex: 1 vòng, ~70,4k tokens, effort medium.
- Verification đã chạy (mọi lệnh pytest dùng prefix `timeout 300 env PYTHONPATH=$PWD/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`):
  - `-q -x tests/test_store_index_cache.py tests/test_web_theme_plan.py -k 'source'`: **43 passed, 55 deselected**.
  - `-q -x tests/test_web_theme_plan.py -k 'without_http or without_io or without_hash or js_ or favorites_tab_panel'`: **68 passed, 26 deselected**.
  - `-q -x tests/test_store_index_cache.py tests/test_src4_ingest_store.py tests/test_theme_index.py tests/test_store_backup.py tests/test_store_redownload.py -k 'not background'`: **195 passed, 19 deselected**.
  - `-q -x tests/test_store_index_cache.py tests/test_store_client.py tests/test_store_backup.py tests/test_store_redownload.py`: **4 passed, 1 setup error** tại `test_client_index_head_fetch`: `PermissionError: [Errno 1] Operation not permitted` khi tạo socket loopback. Các file sau đó không chạy trong lệnh này.
  - `timeout 300 node scripts/framework-check.mjs`: **PASS**.
  - `git diff --check`: **PASS**.
- Verification bị sandbox chặn:
  - `-q -x tests/test_web_theme_plan.py tests/test_src4_ingest_store.py tests/test_theme_index.py`: **timeout 300 s, exit 124**, chưa có output (TestClient).
  - `-q -x tests/test_store_index_cache.py tests/test_src4_ingest_store.py tests/test_theme_index.py tests/test_store_backup.py tests/test_store_redownload.py`: **timeout 300 s, exit 124**, có tiến độ test nhưng không có summary.
  - Cùng lệnh trên với `-k 'not a2_background_group_progress_and_readonly_storage'`: **timeout 300 s, exit 124**. Sau đó chạy `-k 'not background'` PASS 195 tests như trên.
  - `-q -x tests/test_store_backup.py -k background -vv`: **timeout 300 s, exit 124** tại `test_background_io_uses_thread_and_waits_retry_seconds`; `test_background_one_upload_cache_report_and_render_pause` đã PASS.
- ORCHESTRATOR cần chạy lại required verification có TestClient / socket, test background async, full suite `-q -n auto`. Không tuyên bố AC4 PASS trong sandbox.
- Không commit / push / PR; chỉ sửa owned paths và mục Result. Status contract giữ nguyên để ORCHESTRATOR review và hoàn tất required verification.
