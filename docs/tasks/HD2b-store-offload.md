# Task: HD2b — Đẩy bản dọc lên kho 3090 + tự giải phóng, tải qua web từ kho, Bộ nhớ

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review, full suite, chạy thật với kho 3090 thật
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet) khi quota Codex ≥ ngưỡng
- Authorization mode: task
- Authorization source: `docs/decisions/HD2-external-store-3090.md` ACCEPTED (HUMAN LEAD 2026-10-25), G5 + G6 + G7; HUMAN LEAD 2026-10-26 "viết contract HD2b cho mục 3" (giải phóng ~50 GB bản dọc Vô Lượng Thọ / Cảm Ứng Thiên không có luồng sao lưu)
- Parallel group: —
- Owned paths: `src/auto_short/store/offload.py` (mới), `src/auto_short/store/client.py` (chỉ thêm đọc luồng có Range nếu thiếu), `src/auto_short/render/full.py` (bản dọc trên kho vẫn "hiện hành" — làm rõ 2026-10-26), `src/auto_short/config.py` (`[store] offload`), `src/auto_short/review/backup.py` (tái dùng `confirm` / `release`, không đổi luật), `src/auto_short/web/app.py` (vòng đẩy), `src/auto_short/web/routes/episodes.py` + `src/auto_short/web/routes/playlists.py` (link tải tập đã giải phóng), `src/auto_short/web/storage.py` (G7), `src/auto_short/web/static/app.js`, `tests/test_store_offload.py` (mới), `tests/test_store_download.py` (mới), `config.toml` (bật cờ — ORCHESTRATOR, khi chạy thật), contract này
- Dependencies: HD2a, SRC1 (mẫu vòng sao lưu `_source_backup_loop`), FIX-theme-store-index (snapshot `/index` dùng chung) — merge trước nếu đụng cùng file
- Base commit / branch: `01ab1a3` (`main`, sau #163–#166) / `feature/hd2b-store-offload`
- Human Lead approval: APPROVED (2026-10-26 "đồng ý cả 2": contract + D1 + D2)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Bản dọc trên VM được đẩy lên kho 3090, kho xác nhận đúng sha256 thì VM tự xác nhận sao lưu (HD1 G1) và giải phóng (HD1 G2); link tải trên web vẫn dùng được (VM chuyển tiếp từ kho). Kết quả đo được: ~50 GB bản dọc của Vô Lượng Thọ / Cảm Ứng Thiên (≈ 60 file `output/<id>/full/vertical.mp4`, dựng 16–22/10, không có bản HD) rời VM; bản dọc mới dựng về sau cũng tự rời VM.

## Bối cảnh (2026-10-26, ORCHESTRATOR)

- Đĩa VM 502 GB, dùng 331 GB: HD Địa Tạng chưa giải phóng 100,8 GB, Short 82 GB, nguồn 52,6 GB, bản dọc 50 GB (VLT 25,4 + CƯT 24,6).
- `backup.ps1` (HD1 G6) chỉ được sinh cho Kinh Địa Tạng; VLT / CƯT không có bản HD (`source_hd.mp4`) nên không có lượt sao lưu nào chạm tới bản dọc của chúng → không bao giờ được giải phóng.
- HD1 G2: giải phóng khi **mọi file đang có** (HD, dọc) đã xác nhận đúng sha hiện tại; tập không có HD chỉ cần bản dọc. Luật này giữ nguyên.
- Kho (HD2a G1) đã nhận `kind` `hd` / `vertical` / `source` qua `PUT` có sha256, `HEAD` trả sha + kích thước; SRC1 đã có vòng đẩy nguồn một file mỗi lượt (`app.py` `_source_backup_loop`, `store/backup.py` `push_source`) — làm theo cùng mẫu.

## Quyết định HUMAN LEAD (gate) — D1, D2 ĐỒNG Ý 2026-10-26

- **D1 — Đẩy bù bản dọc đã có**: HD2 G6 viết cho "bản dọc mới dựng". Đề xuất: vòng đẩy xử lý **mọi** `full/vertical.mp4` hiện hành chưa xác nhận (kể cả 60 file VLT / CƯT cũ), không chỉ file dựng sau khi bật. Không đồng ý → chỉ file mới, 50 GB hiện tại vẫn nằm trên VM.
- **D2 — Tự giải phóng tập không có HD**: đề xuất tự gọi HD1 G2 ngay sau khi kho xác nhận (không hỏi), kể cả tập chỉ có bản dọc (VLT / CƯT); tập có HD chưa xác nhận thì chỉ xác nhận bản dọc, không giải phóng (luật G2 cũ). Không đồng ý → chỉ xác nhận, giải phóng vẫn bấm tay / `backup.ps1 -Release`.

## Scope

- In scope:
  - **G6 bản dọc**: cờ `[store] offload` (mặc định tắt). Vòng nền một file mỗi lượt (`retry_seconds`), nhường khi làn render đang ghi đúng file đó / có job bản dọc của tập: chọn `vertical.mp4` hiện hành chưa xác nhận (theo D1) → `PUT kind=vertical` (tên `[HD Mobile] <bộ kinh> - Tập N.mp4`, HD2 G3 / HD1 G6) → `HEAD` khớp sha + kích thước → `review.backup.confirm(kind="vertical")` → (theo D2) `review.backup.release`. Kho tắt / lỗi → giữ file, thử lại lượt sau; lỗi một tập không chặn tập khác (mẫu `source_backup_failed`). Sau khi đẩy: `index_cache.invalidate()`.
  - **G5 tải qua web**: link tải bản dọc / HD của tập đã giải phóng hiện lại (playlist + trang tập, cùng tên file như trước); VM chuyển tiếp luồng từ kho (giữ `Range`, `Content-Length`, tên file); kho tắt → 503 "3090 đang tắt". Không lưu bản sao trên VM.
  - **G7 Bộ nhớ**: tab Bộ nhớ hiện tiến độ đẩy (đã đẩy / còn lại / lỗi, dung lượng sẽ giải phóng) và dung lượng file tạm mượn từ kho (`work/**` file tạm của HD2a G4 / SRC3); dọn file mượn sót (tạm cũ hơn một ngưỡng, không thuộc job đang chạy) khi khởi động web.
- Out of scope: đẩy `source_hd.mp4` (`offload_hd`) và giải phóng HD khi chưa có bản dọc (đổi luật HD1 G2 — quyết định riêng); Short (`output/<id>/shorts/`); theme_render mượn từ kho; xóa file trên 3090; generator `backup.ps1` (tùy chọn ổ đã xong ở #161).

## Authority / key decisions

- HD2 G6: file mới lên thẳng kho, kho xác nhận sha → VM xác nhận + giải phóng tự động; cờ `[store] offload` mặc định tắt (giữ).
- HD2 G5: tải qua web từ kho, 503 khi kho tắt (giữ).
- HD1 G1 / G2: chỉ xác nhận khi sha kho = sha file hiện có trên VM; giải phóng chỉ khi mọi file đang có đã xác nhận, không có job / vertical job / lease enhance đang chạy (giữ — offload gọi đúng các hàm này, không viết lại điều kiện).
- HD2 G8: không thêm dependency; token không ghi log.

## Implementation approach

- `store/offload.py`: `candidates(config)` (bản dọc hiện hành chưa xác nhận, theo D1; thứ tự: tập của bộ không có HD trước, rồi theo dung lượng giảm dần), `push_vertical(config, owner, *, client)` (tái dùng `review.backup.vertical_sha`, `store/backup._destination` / `_matches` nếu đúng kiểu, `StoreClient.put/head`), trả trạng thái để web ghi snapshot.
- `web/app.py`: `_offload_loop` + `offload_pass` giống `_source_backup_loop` / `source_backup_pass`; snapshot cho `storage.report()["offload"]`.
- Route tải: tái dùng route tải hiện có; nhánh tập `released` → luồng từ kho (đọc từng khối, không đọc cả file vào RAM).
- `config.toml` của VM: ORCHESTRATOR bật `offload = true` khi chạy thật, sau khi HUMAN LEAD duyệt READY.

## Phải giữ nguyên

- Luật HD1 G1 / G2 / G3, `backup.ps1` vẫn chạy được song song (tập đã xác nhận / giải phóng bởi offload được script coi là "đã giải phóng trên VM", CSV giữ dòng — #161); Short / khai thị / bài đăng không đổi trạng thái; mọi test HD1 / HD2a / SRC1–SRC4 hiện có.

## Làm rõ kỹ thuật (ORCHESTRATOR 2026-10-26, trong D1 / D2)

- `review.backup.release` hiện đòi `enhance.json` `done` + có `source_hd.mp4`; HD1 G2 viết "cả hai file (cái nào đang có)" và D2 duyệt giải phóng tập chỉ có bản dọc → `release` nhận thêm trường hợp không có HD: chỉ xóa bản dọc đã xác nhận đúng sha, ghi `backup.json` `released.vertical`; **không** đặt `enhance.json` `released` (cờ đó vẫn nghĩa "HD ở máy ngoài"). Điều kiện cho tập có HD giữ nguyên.
- `render_full.current` trả False khi `full/vertical.mp4` đã xóa → vòng bản dọc tự động / "Tạo bản dọc cả bộ" sẽ dựng lại. Bản dọc đã giải phóng (meta còn, `backup.json` `released.vertical` khớp kích thước meta, `hd_sha256` khớp nguồn hiệu lực / HD đã giải phóng) được coi là hiện hành, nằm trên kho. Thêm `render/full.py` vào Owned paths.

## Code bị thay / xóa

- Không xóa; link "HD đã chuyển ra máy ngoài" (HD1 G3 c) thay bằng link tải từ kho khi `[store] enabled`, giữ chữ cũ khi kho tắt cấu hình.

## Acceptance Criteria

1. Bật `offload`: bản dọc chưa xác nhận được `PUT`, kho khớp sha → `backup.json` có xác nhận `vertical`; tập không có HD được giải phóng (D2), tập có HD chưa xác nhận chỉ được xác nhận.
2. Kho tắt / sha lệch / lỗi một tập → không xác nhận, không xóa, thử lại sau; tập khác vẫn chạy.
3. Không động tới file đang được job bản dọc / render ghi; tập có job đang chạy không bị giải phóng.
4. Tải bản dọc / HD của tập đã giải phóng qua web: đúng byte (sha), hỗ trợ `Range`; kho tắt → 503.
5. Tab Bộ nhớ hiện tiến độ đẩy + dung lượng file tạm; file mượn sót được dọn khi khởi động.
6. `offload = false` (mặc định): không có lượt đẩy nào, hành vi như trước.
7. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_store_offload.py tests/test_store_download.py tests/test_hd_backup.py tests/test_store_client.py` — AC 1–6.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- ORCHESTRATOR chạy thật: bật `offload` trên 8080 (restart hỏi có / không), theo dõi 2–3 tập VLT đầu tiên: `GET /index` kho có `vertical`, `backup.json` xác nhận + giải phóng, tải lại qua web đúng sha; rồi để chạy hết, đo dung lượng `output/` trước / sau.

## Manual test checklist (Tech Lead)

- [ ] Trang bộ Vô Lượng Thọ: tập đã giải phóng vẫn bấm tải bản dọc được (từ 3090).
- [ ] Tab Bộ nhớ: thấy tiến độ đẩy và dung lượng giảm.

## Handoff

- Outgoing / incoming ORCHESTRATOR: —
- Nguồn duyệt chuyển giao: —
- Phase / blocker / next action: APPROVED; session mới: tạo branch `feature/hd2b-store-offload` từ main (sau khi #165, #166 merge), giao Codex.
- HEAD + working tree lúc bàn giao: —

## Result

- (điền khi READY)
