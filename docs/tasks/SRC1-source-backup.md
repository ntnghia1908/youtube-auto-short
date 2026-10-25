# Task: SRC1 — Sao lưu video gốc lên kho 3090 trước khi tự dọn

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; quota 2026-10-25: 5 giờ 6 %, tuần 1 %. Test web (TestClient) và full suite do ORCHESTRATOR chạy ngoài sandbox.
- Authorization mode: task
- Authorization source: `docs/decisions/SRC1-source-backup-3090.md` (PROPOSED; cần ACCEPTED trước implementation)
- Parallel group: —
- Owned paths: `tools/store/store.py`; `src/auto_short/store/client.py`; `src/auto_short/store/backup.py` (mới); `src/auto_short/store/borrow.py` (chỉ hàm mượn `source`); `src/auto_short/config.py` (chỉ `StoreConfig.backup_source`); `src/auto_short/review/archive.py` (`archive_source`, `restore_source`); `src/auto_short/web/app.py` (chỉ `auto_archive_pass` + vòng nền sao lưu); `src/auto_short/web/storage.py` + `src/auto_short/web/static/` phần tab Bộ nhớ (dòng "đã sao lưu"); `src/auto_short/theme_render/__init__.py` (chỉ `_source`); `tests/test_store_server.py`, `tests/test_store_client.py`, `tests/test_store_backup.py` (mới), `tests/test_restore_source_cp837.py`, `tests/test_storage_cp86.py`, `tests/test_theme_render.py`, `tests/test_config.py`; file này
- Dependencies: HD2a (kho + kênh, đã merge); không dependency mới
- Base commit / branch: `3394246` (origin/main) / `feature/src1-source-backup`
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa decision HD2 (kind mới) và quy tắc tự dọn W9 S5; luồng dữ liệu VM → 3090 mới.

## Goal

Không video gốc nào bị xóa khỏi VM khi chưa có bản đúng sha256 trên 3090. 188 bản gốc đang có (62,8 GB) và 14 bản trong kho nguồn ghép được đẩy dần lên 3090, video ♥ trước. Ghép chủ đề và "Khôi phục nguồn" lấy lại từ 3090 trước khi phải tải YouTube.

## Scope

- In scope: decision SRC1 G2–G7 + G4a (phần đẩy; tải lại 4 video mất hẳn từ YouTube thuộc TC3.2 / lệnh có sẵn).
- Out of scope: 130 bản gốc không ♥ đã xóa; xóa trên 3090; HD2b G5 / G6; đổi định dạng file.

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

- Main changes:
