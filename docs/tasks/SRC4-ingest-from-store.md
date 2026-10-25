# Task: SRC4 — Ingest lấy video gốc từ kho 3090 trước YouTube

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC3-SRC4-store-first-sources.md` G5–G6 (ACCEPTED 2026-10-25, G5–G6)
- Parallel group: SRC3 ∥ SRC4 (Owned paths rời nhau)
- Owned paths: `src/auto_short/ingest/stage.py` (`_ingest_youtube`, `needs_download`); `src/auto_short/store/borrow.py` hoặc `src/auto_short/store/index_cache.py` (mới, index kho nhớ tạm); `src/auto_short/web/jobs.py` (chỗ gọi `needs_download` nếu cần truyền cache; amendment A1 — ORCHESTRATOR 2026-10-25: thêm đúng phần đăng ký / gỡ listener và đánh thức scheduler khi index kho refresh xong, không đổi luật backoff / probe); `tests/test_ingest_youtube.py`, `tests/test_youtube_wait.py`, `tests/test_src4_ingest_store.py` (mới); file này
- Dependencies: SRC1 (#154), SRC2 (#155) — làm sau khi merge
- Base commit / branch: `docs/src3-src4` (xếp chồng SRC2 #155 → SRC1 #154; rebase lên main sau merge) / `feature/src4-ingest-from-store`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt cả hai"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì đổi nguồn dữ liệu của ingest (kho 3090 thay YouTube).

## Goal

Xử lý video mới (SRC2 đã đẩy 488 video chưa xử lý lên 3090) không cần YouTube: ingest tải từ kho, YouTube chỉ là dự phòng; làn prepare không phải chờ khi YouTube chặn mà kho có bản.

## Scope

- In scope: G5, G6.
- Out of scope: tập local; khai thị (giữ CP8.9 K5 dùng nguồn tập gốc); sửa tập đã dọn (SRC3).

## Authority / key decisions

- G5: `_ingest_youtube` thử `StoreClient.fetch(video_id, "source", …)` (kiểm sha kho) trước `ytdlp_download`; kho tắt / lỗi / không có → YouTube như cũ. `manifest.source` như ingest YouTube (uri YouTube canonical, sha / size file thật) + `via = "store"`.
- G6: `needs_download` → False khi index kho (nhớ tạm, TTL ≥ 5 phút, lỗi → coi như không có) có `source` của video.

## Implementation approach

- Index kho nhớ tạm dùng chung (một chỗ), không gọi mạng trong `needs_download` khi cache còn hạn.
- `_ingest_youtube`: nhánh kho trước, file tải vào thư mục tạm của workspace rồi đặt như bản YouTube; kiểm thời lượng bằng `youtube_info` nếu bản YouTube cũng kiểm.
- SRC1 sao lưu thấy bản workspace trùng sha kho → không đẩy lại.

## Phải giữ nguyên

- `IngestBlocked` / `YoutubeWait` khi phải đi YouTube và bị chặn; khai thị reuse; tập `archived` vẫn bị ingest từ chối (SRC3 lo phần sửa).

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Video có trên kho: ingest lấy từ kho, không gọi YouTube; manifest ghi `via = "store"` và sha thật.
2. Kho tắt / lỗi / sai sha → YouTube như cũ.
3. `needs_download` False khi kho có bản; job prepare chạy lúc YouTube đang chặn.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_ingest_youtube.py tests/test_youtube_wait.py tests/test_src4_ingest_store.py -x --tb=short` — AC 1–3.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- Chạy thật trên 8080: xử lý 1 video chưa xử lý đã có trên 3090 → log không có yt-dlp, manifest `via = "store"`.

## Manual test checklist (Tech Lead)

- [ ] Thêm 1 tập Vô Lượng Thọ chưa xử lý: tải nhanh từ 3090, Short ra bình thường.

## Result

- Amendment A1 — ORCHESTRATOR 2026-10-25: mở Owned paths của `web/jobs.py` cho listener / wakeup scheduler sau refresh index; đã thực hiện, không đổi backoff / probe.
- Files: `ingest/stage.py`, `store/index_cache.py` (mới), `web/jobs.py`, `tests/test_src4_ingest_store.py` (mới), contract này.
- Ingest: reuse khai thị → kho → YouTube; HEAD + fetch kiểm SHA / size, probe như nhánh YouTube, giữ đuôi file, canonical uri + `via = "store"`. Lỗi / thiếu title playlist → dọn tạm rồi fallback. Giữ nguyên `_used_config` / cache key và IngestBlocked.
- F1: `needs_download` dùng snapshot không chặn (cũ hoặc rỗng), refresh nền một worker; không gọi mạng đồng bộ dưới scheduler lock. Cache có TTL 300 s cho hit / miss / lỗi, khóa chỉ bảo vệ state; ingest chờ snapshot mới ngoài scheduler lock.
- F2: helper `_playlist_source_title` đọc `<workspace>/<titling.playlist.PLAYLISTS_DIR>/*.json`; metadata kho có title thật, channel None; không có title hợp lệ → G6 trả True và ingest đi YouTube. Không import web từ ingest.
- Helper cache: `source_entry`, `has_source`, `invalidate`, `_refresh`; A1 thêm `add_listener` / `remove_listener` (đăng ký idempotent, gỡ được) và callback `JobRunner._store_index_refreshed`. Refresh cập nhật snapshot rồi nhả khóa cache trước khi gọi listener; lỗi listener bị nuốt và log debug. Runner đăng ký trong start, gỡ trong stop; callback chỉ lấy scheduler lock rồi notify_all.
- Đã đọc / tìm helper bằng `rg` ở `store/client.py`, `store/borrow.py`, `titling/playlist.py`, `web/monitor.py::_load_playlist_index`, lifecycle `web/jobs.py`. Tái dùng StoreClient.head/fetch, hashing.fingerprint, probe, _source_entry, youtube_info, canonical_url và PLAYLISTS_DIR. Chưa có cache / listener tương đương; borrow_hd có lifecycle / failure policy khác. Test tái dùng FakeDownloader, Clock, Net, wait_for.

| AC / review | Test chính trong tests/test_src4_ingest_store.py | Kết quả hiện tại |
|---|---|---|
| 1 / F2 | test_store_ingest_and_skip_preserve_cache_key; test_store_extension_and_khaithi_reuse_before_store | PASS: SHA / via / title playlist / đuôi / reuse / cache key |
| 2 / F2 | test_store_fallback_cleans_temporary_files; test_fallback_retains_ingest_blocked; test_missing_playlist_title_falls_back_to_youtube | PASS: 8 nhánh lỗi kho + 7 dạng title thiếu / lỗi; dọn tạm, giữ IngestBlocked |
| 3 / F1 | test_needs_download_refresh_never_blocks_scheduler; test_prepare_from_store_runs_while_youtube_blocked; test_index_ttl_shared_hits_misses_and_invalidation | PASS: cold / stale trả ngay, TTL; job kho chạy khi YouTube còn block, không đổi assertion / fake clock / backoff |
| A1 | test_refresh_listeners_run_after_publish_outside_cache_lock; test_runner_start_registers_once_and_stop_removes_listener | PASS: thread khác lấy được khóa cache trong callback; snapshot đã cập nhật kể cả kho lỗi, listener lỗi không ngắt refresh, start idempotent / stop gỡ / restart đăng ký lại |
| 4 | Full suite / API đầy đủ / manual 8080 | Chưa chạy lại; ORCHESTRATOR phụ trách ngoài sandbox |

AC3 còn test lỗi cache / concurrent isolation riêng để phủ các nhánh đồng thời. MemoryStore chạy kiểm SHA thật của StoreClient.fetch với transport bytes trong bộ nhớ; fixture cấm socket connect.

Lệnh duy nhất chạy verification lượt A1 (bọc `timeout 240`):

```text
env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/src4-ingest-from-store/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_src4_ingest_store.py tests/test_ingest_youtube.py tests/test_youtube_wait.py -k 'not test_api_youtube_status_and_banner'
```

**59 passed, 1 deselected in 2.89s**, exit **0**. Failure cold-cache scheduler trước A1 đã được giải quyết; test prepare giữ nguyên assertion có ý nghĩa. Không chạy full suite / test API đã loại / framework checker / manual 8080 trong lượt A1 theo yêu cầu chỉ chạy lệnh trên. Kết quả ngoài sandbox trước A1 do ORCHESTRATOR cung cấp: 56 passed, 1 failed; không dùng làm bằng chứng cho bản hiện tại.

Delta riêng A1 so với snapshot trước lượt sửa (`/tmp/src4-review-before/a1-*`): ứng dụng **+33 / -0** (index_cache +24, jobs +9), test **+56 / -0**. Tổng so với HEAD: ứng dụng **+178 / -7**, test **+364 / -0**, không tính contract (đo bằng git diff --numstat và git diff --no-index --numstat cho file mới / snapshot).

Implementation A1 sẵn sàng ORCHESTRATOR review; không còn blocker đã biết trong lệnh test được giao. Contract giữ **IN_PROGRESS** tới khi ORCHESTRATOR hoàn tất review và required verification còn lại. Không commit / push / PR, gọi mạng thật hay agent khác.

ORCHESTRATOR (2026-10-25, ngoài sandbox): review 3 vòng (F1 không gọi mạng dưới lock scheduler; F2 tiêu đề tập từ playlist docs, thiếu → YouTube; A1 đánh thức scheduler). Targeted `test_src4_ingest_store.py test_ingest_youtube.py test_youtube_wait.py` 57 passed (trước A1, 1 fail đã sửa ở A1); full suite `-n auto` **2886 passed, 1 skipped**; `framework-check`, `git diff --check` PASS. Codex tokens: 77k + 114k + vòng A1. Còn: chạy thật 8080 (chờ HUMAN LEAD cho restart). Theo dõi sau: TC3.2 `StoreSources` dùng lại `index_cache` khi cả hai merge.

Chạy thật (2026-10-25 17:14, code `66ccddb` = SRC4 `f7849ae` + SRC3 + TC3.2, kho 3090 thật):
- Không có video playlist nào vừa chưa xử lý, vừa có `source` trên kho, vừa không có bản cục bộ: ứng viên duy nhất `1VAkCR8kK5I` (Địa Tạng 5) có phần `.kt` còn giữ `source.mp4`, nên qua 8080 ingest sẽ dùng lại bản `.kt` (đúng thứ tự khai thị → kho → YouTube) chứ không đi kho.
- Thay vào đó gọi `run_ingest("https://youtu.be/1VAkCR8kK5I")` với config thật của web (`[store]` bật, token thật) nhưng `workspace.dir` là thư mục tạm (chép `_playlists`), downloader YouTube thay bằng hàm dừng lỗi nếu bị gọi: log `ingest: fetched 1VAkCR8kK5I from store` sau 6 s (219 MB); `manifest.source.via = "store"`, uri `https://youtu.be/1VAkCR8kK5I`, sha `86001eb5…` / 219 246 244 B = sha ingest gốc của `.kt`; downloader YouTube không được gọi → **AC1 PASS** (thật, ngoài web). Workspace tạm đã xóa; dữ liệu web không đổi.
- AC3 (`needs_download` False khi YouTube chặn): chỉ có test tự động — YouTube không chặn lúc chạy.
- READY; manual checklist do HUMAN LEAD.
