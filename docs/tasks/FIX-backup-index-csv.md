# Task: FIX-backup-index-csv — `backup.ps1` không làm mất dòng của tập đã giải phóng trong `danh-sach.csv`

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`): sửa nhỏ trong một template + test văn bản
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-25 (handoff "FIX backup.ps1 … viết contract S1, Codex sửa"); `docs/decisions/HD2-external-store-3090.md` G3 (`index.csv` / CSV của script sao lưu là nguồn ánh xạ `video_id` ↔ file)
- Parallel group: —
- Owned paths: `scripts/backup/backup.template.ps1`, `scripts/backup/make_backup.py` (chỉ chữ hướng dẫn ổ mặc định), `tests/test_hd_backup.py` (thêm test template), file này
- Dependencies: none
- Base commit / branch: `e48a1ec` (`main`) / `fix/backup-index-csv`
- Human Lead approval: APPROVED (2026-10-25, handoff)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Chạy `backup.ps1` nhiều lượt không làm mất dòng `danh-sach.csv` của tập đã giải phóng ở lượt trước; kho 3090 (`tools/store/store.py` đọc `danh-sach.csv` + `index.csv`) luôn thấy mọi file đã sao lưu. Mặc định `-Dest` là ổ `E:`.

## Bối cảnh (2026-10-25, ORCHESTRATOR)

- `scripts/backup/backup.template.ps1:328` `$rows | Export-Csv … -Path $Index` ghi đè `danh-sach.csv` mỗi lượt chỉ với tập VM còn giữ (`$e.hd_url` / `$e.vertical.url`); tập đã giải phóng lượt trước không vào `$rows` → dòng biến mất. `SHA256SUMS.txt` chỉ ghi thêm nên vẫn giữ. Hậu quả thật: 41 tập Địa Tạng đã giải phóng không có trong index kho → render "đợi 3090". HUMAN LEAD đã vá dữ liệu bằng `fix-index-csv.ps1` (thêm 82 dòng vào `E:\KinhDiaTang_HD\index.csv`); FIX này chặn lỗi tái diễn.
- Ổ sao lưu thật là `E:` (`E:\KinhDiaTang_HD`); template mặc định `D:` nên HUMAN LEAD phải luôn gõ `-Dest`.

## Scope

- In scope: trước khi ghi `danh-sach.csv`, đọc file hiện có (nếu có), giữ các dòng cũ mà lượt này không ghi lại (khóa `tap` + `loai`) và file của dòng đó còn trong thư mục đích; dòng lượt này thắng khi trùng khóa; ghi theo thứ tự tập / loại. CSV hỏng / không đọc được → ghi log cảnh báo và giữ hành vi cũ (chỉ dòng mới), không dừng script. Đổi `D:` → `E:` ở mặc định `-Dest` và các dòng hướng dẫn (template + help `--dest-name` của `make_backup.py`). Thêm test văn bản cho template.
- Out of scope: `tools/store/store.py`, `index.csv` (do kho PUT ghi), luồng tải / xác nhận / giải phóng, `rename.template.ps1`.

## Authority / key decisions

- HD2 G3: CSV của script sao lưu là nguồn ánh xạ cho kho; script không xóa gì trên máy 3090 (giữ).
- S1 cục bộ: khóa gộp là `tap` + `loai` (một file mỗi tập / loại theo `BackupName`); bỏ dòng cũ khi file không còn trên đĩa (đã đổi tên / người dùng xóa) để kho không trỏ tới file mất.

## Implementation approach

- Một khối ngay trước `Export-Csv`: `Import-Csv -Encoding UTF8` trong `try`, dựng tập khóa từ `$rows`, thêm dòng cũ hợp lệ, sắp xếp, `Export-Csv` như cũ (`-NoTypeInformation -Encoding UTF8`, cùng cột `tap,loai,file,video_id,tieu_de`). Log số dòng giữ lại.

## Phải giữ nguyên

- Cột, encoding (UTF-8 BOM của PowerShell 5.1), tên file `danh-sach.csv`; mọi assertion hiện có trong `tests/test_hd_backup.py`; script không xóa file backup; `Read-Host` vẫn đúng 2 lần.

## Code bị thay / xóa

- Dòng `$rows | Export-Csv …` đơn lẻ được thay bằng khối gộp; không để lại đường ghi đè cũ.

## Acceptance Criteria

1. Lượt chạy không còn `hd_url` cho tập đã giải phóng vẫn giữ dòng cũ của tập đó (file còn trên đĩa) trong `danh-sach.csv`.
2. Dòng lượt này ghi đè dòng cũ cùng `tap` + `loai`; dòng cũ có file đã mất bị bỏ; CSV cũ hỏng không làm dừng script.
3. Mặc định `-Dest` và chữ hướng dẫn dùng `E:`.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_hd_backup.py tests/test_store_server.py` — AC 1–3 (văn bản template + generator; kho đọc CSV).
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- ORCHESTRATOR: sinh lại `backup.ps1` bằng `make_backup.py` (Địa Tạng) và gửi HUMAN LEAD; VM không có PowerShell nên hành vi PowerShell chỉ được kiểm khi HUMAN LEAD chạy trên 3090.

## Manual test checklist (Tech Lead)

- [ ] Trên 3090 chạy `backup.ps1 -Release` (không cần `-Dest`): `danh-sach.csv` sau lượt chạy vẫn có dòng của các tập đã giải phóng; log ghi số dòng giữ lại; `GET /index` của kho vẫn đủ 52 / 52 tập.

## Handoff

- Outgoing / incoming ORCHESTRATOR: —
- Nguồn duyệt chuyển giao: —
- Phase / blocker / next action: giao Codex.
- HEAD + working tree lúc bàn giao: —

## Result

- Main changes: gộp CSV cũ theo khóa `tap|loai`, dòng mới thắng; chỉ giữ dòng cũ có file còn tồn tại qua `Test-Path -LiteralPath`; lỗi đọc/gộp CSV → cảnh báo và chỉ ghi dòng mới. Log số dòng giữ lại, sắp theo `tap,loai`, cố định cột `tap,loai,file,video_id,tieu_de`. Mặc định và hướng dẫn template/help dùng `E:`.
- Tests (2026-10-25; chạy trong worktree bàn giao):
  - Lệnh đúng handoff: `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-backup-index-csv/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_hd_backup.py tests/test_store_server.py -x --tb=short` → không có output, treo; ngắt bằng Ctrl-C, exit 130, không PASS.
  - Fallback: `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-backup-index-csv/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_hd_backup.py -x --tb=short -o faulthandler_timeout=30` → `Timeout (0:00:30)!`; stack tại `test_backup_accepts_only_current_sha` → `logged` → `web_helpers.login` → Starlette TestClient / AnyIO chờ `Future.result`; ngắt Ctrl-C, exit 130. Chưa chứng minh nguyên nhân là socket/sandbox.
  - Cùng env/Python trên, `-m pytest -q tests/test_hd_backup.py -k 'template or generator' -x --tb=short` → `6 passed, 13 deselected in 7.80s` (exit 0).
  - Cùng env/Python trên, `-m pytest -q tests/test_store_server.py -x --tb=short` → `88 passed in 0.51s` (exit 0).
  - `node scripts/framework-check.mjs` → PASS (exit 0); `git diff --check` → không output (exit 0).
  - Không chạy full suite `-n auto` khi nhóm web liên quan đang treo; không chạy `.ps1` vì VM không có PowerShell.
- AC → test: AC1–2 → `test_template_merges_existing_index_and_keeps_fixed_columns` (kiểm văn bản, chưa xác nhận runtime PowerShell); AC3 → `test_template_defaults_and_instructions_use_e_drive`, `test_generator_builds_scripts_with_parameters`; các assertion cũ giữ nguyên trừ kỳ vọng ổ `D:` đổi thành `E:` đúng behavior mới. AC4 chưa xác nhận; ORCHESTRATOR cần chạy verification còn thiếu.
- Diff + / − (app, test): app +24 / −4 (`backup.template.ps1` +23 / −3; `make_backup.py` +1 / −1, chỉ help); test +30 / −1; tài liệu Result tính riêng.
- Helper mới (đã tìm, lý do không tái dùng): không có; đã đọc template/generator/tests, tái dùng `Log`, `$Index`, `$Dest`, `$rows`.
- Review: tự rà diff trong owned paths; không thêm prompt hay lệnh xóa file; vẫn hai `Read-Host`; giữ `Export-Csv -NoTypeInformation -Encoding UTF8`. Chờ ORCHESTRATOR review độc lập.
- Important findings / decisions: branch `fix/backup-index-csv`, HEAD `60cf6f2`, working tree sạch lúc nhận; không đổi ngoài owned paths / mục Result. Implementation hoàn tất, verification bị chặn; giữ Status IN_PROGRESS.
- Known limitations: test văn bản không chứng minh hành vi PowerShell 5.1; manual checklist trên 3090 và full suite còn chờ ORCHESTRATOR/HUMAN LEAD.
- ORCHESTRATOR (2026-10-25, ngoài sandbox): review diff (gộp đúng khóa, `-NoVertical` cũng không còn làm mất dòng Doc cũ); `tests/test_hd_backup.py tests/test_store_server.py` **107 passed**; full suite `-n auto` **2798 passed, 1 skipped**; `framework-check`, `git diff --check` PASS. Codex: 1 lượt, 45k tokens. Sinh lại `backup.ps1` Địa Tạng bằng `make_backup.py` (50 HD + 0 Doc sha — VM không còn `vertical.mp4` nào của bộ này; file ngoài bảng kiểm theo dung lượng như cũ), gửi HUMAN LEAD. Còn: manual checklist trên 3090.
- PR: #161
