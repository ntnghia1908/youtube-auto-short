# Task: SRC2 — Tải lại toàn bộ video gốc đã xóa lên kho 3090

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC1-source-backup-3090.md` G4a + G8 (HUMAN LEAD 2026-10-25: "Tải hết toàn bộ video nguồn về backup để khi xử lý không còn phụ thuộc youtube chặn"); decision ACCEPTED 2026-10-25
- Parallel group: —
- Owned paths: `src/auto_short/store/redownload.py` (mới); `src/auto_short/theme_render/sources.py` (chỉ tách hàm kiểm / tải dùng chung, coi 403 là "chặn" trong đường tải lại); `src/auto_short/web/app.py` (chỉ wiring vòng tải lại nền); `src/auto_short/web/storage.py` + `src/auto_short/web/static/` phần tab Bộ nhớ (dòng tiến độ tải lại); `tests/test_store_redownload.py` (mới), `tests/test_theme_source_cache.py`; file này
- Dependencies: SRC1 (kind `source`, `push_source`, `backup_state`) — làm sau SRC1 merge
- Base commit / branch: sau SRC1 / `feature/src2-source-redownload`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt tất cả theo đề xuất"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì: tạo lưu lượng tải YouTube nền kéo dài (≈ 1,5 ngày) từ IP production và ghi dữ liệu lên 3090.

## Goal

Mọi tập đã bị dọn nguồn có bản video gốc trên 3090 (kiểm kê 2026-10-25: 116 tập, 63,4 GB; 4 video ♥ VLT tập 16, 17, 19, 20 trước), tải chậm để không bị YouTube chặn. Từ đó ghép chủ đề / khôi phục nguồn lấy từ 3090 (SRC1 G5), không cần YouTube.

## Scope

- In scope: SRC1 G8 + phần tải lại của G4a; CLI kiểm kê `python -m auto_short.store.redownload --config … --dry-run`.
- Out of scope: tập chưa ingest; chọn / đổi chất lượng tải; xóa trên 3090; nâng yt-dlp (TC3.2 G3).

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

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_redownload.py tests/test_theme_source_cache.py tests/test_store_backup.py -x --tb=short` — AC 1–4.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 5.
- Chạy thật: `--dry-run` trên dữ liệu thật ra 116 (hoặc số mới) và 4 ♥ đầu danh sách; bật cờ trên 8080 (hỏi trước khi sửa `config.toml` / restart), 1 video ♥ về cache + có trên 3090.

## Manual test checklist (Tech Lead)

Không chạm database / public API; tạo lưu lượng YouTube nền (gate: HUMAN LEAD bật cờ).

- [ ] Sau 1–2 giờ: tab Bộ nhớ tiến độ tăng; thư mục bộ kinh trên E: có `[Goc] …` mới.
- [ ] Ghép lại "Chuyển hóa tâm niệm" (VLT) sau khi 4 video ♥ xong.

## Result

- Main changes:
