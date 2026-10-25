# Task: SRC4 — Ingest lấy video gốc từ kho 3090 trước YouTube

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC3-SRC4-store-first-sources.md` G5–G6 (ACCEPTED 2026-10-25, G5–G6)
- Parallel group: SRC3 ∥ SRC4 (Owned paths rời nhau)
- Owned paths: `src/auto_short/ingest/stage.py` (`_ingest_youtube`, `needs_download`); `src/auto_short/store/borrow.py` hoặc `src/auto_short/store/index_cache.py` (mới, index kho nhớ tạm); `src/auto_short/web/jobs.py` (chỉ chỗ gọi `needs_download` nếu cần truyền cache); `tests/test_ingest_youtube.py`, `tests/test_youtube_wait.py`, `tests/test_src4_ingest_store.py` (mới); file này
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

- Main changes:
