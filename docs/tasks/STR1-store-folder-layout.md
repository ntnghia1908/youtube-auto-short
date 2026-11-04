# Task: STR1 — Kho 3090: thư mục con theo loại, Short / Khai thị chia theo tập

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2 (sửa SHO1 G1 "tên phẳng trong thư mục bộ kinh" và cách đặt file của HD2 G1)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex, mặc định của project (HUMAN LEAD 2026-10-25); hết quota thì subagent `implementer`
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-04 (chat): "Kho 3090 hoạt động tốt nhưng khá rối: tất cả hình, bản gốc, ngang... đều nằm trong cùng một thư mục, nên structure lại cây thư mục"; chọn phương án "Theo loại + Short theo tập"
- Parallel group: —
- Owned paths: `tools/store/store.py`, `tools/store/setup-store.ps1` (nếu cần), script mới `tools/store/sap-xep-kho.ps1`, `scripts/backup/backup.template.ps1`, `scripts/backup/make_backup.py` (nếu cần), `tests/test_store_*.py`, `tests/test_backup*.py`, `docs/guides/store-3090.md`, `docs/decisions/SHO1-short-store-3090.md` (chỉ G1), `docs/decisions/HD2-external-store-3090.md` (chỉ ghi chú G1), `docs/workflow/ops-notes.md` (cách chạy trên 3090), `tests/test_vertical_silence_intro.py`, `tests/test_hd_backup.py` (bổ sung khi review: assertion đường dẫn phẳng là "Code bị thay"), file này
- Dependencies: none (STN1 đã merge)
- Base commit / branch: `895e7ce` (origin/main) / `feature/str1-store-folder-layout`
- Human Lead approval: accepted 2026-11-04 (chat: "Duyệt cả hai")
- Implementation authorized: YES

## Goal

Mỗi thư mục bộ kinh trên 3090 có dạng:

```text
<bộ kinh>\
├─ HD\                 [HD] … - Tập N.mp4
├─ HD Mobile\          [HD Mobile] … - Tập N.mp4
├─ Goc\                [Goc] ….mp4
├─ Hinh\               thumbnail .jpg của backup.ps1
├─ Short\Tap 05\       [Short] … - Tập 5 - k01.mp4
├─ KhaiThi\Tap 05\     [KhaiThi] … - Tập 5 - k01.mp4
├─ Short\Khac\         Short không có số tập
├─ _cu\, _cu-…\        giữ nguyên như hiện nay
└─ index.csv, index-short.csv, danh-sach.csv, SHA256SUMS.txt, backup-log.txt
```

Web 8080 vẫn xem / tải / đẩy mọi loại file như trước. `backup.ps1` (kể cả `-Release`, `-ThumbsOnly`) ghi vào đúng thư mục con.

## Scope

- In scope:
  - **Vị trí file suy ra từ loại + tên**: CSV và `SHA256SUMS.txt` vẫn ghi **tên file** (không thêm `\`), nên định dạng metadata, `backup.ps1` cũ và lịch sử sha không đổi. Kho tìm file ở thư mục con đúng loại trước, không thấy thì tìm ở chỗ cũ (gốc bộ kinh), nên trong lúc sắp xếp kho vẫn chạy.
  - `PUT` mới ghi vào thư mục con (tự tạo). Bản thay thế vẫn chuyển bản cũ vào `_cu\` như STN1.
  - Lệnh sắp xếp: `store.py reorganize --series <id|all> [--apply]`, có wrapper `sap-xep-kho.ps1`. Mặc định chạy thử: in danh sách sẽ chuyển, file không nhận ra (để nguyên tại chỗ), và trùng đích (dừng, không ghi đè). `--apply` khóa kho giống `rename_vertical`, dùng `rename` trong cùng ổ đĩa (không chép), chạy lại không lỗi, ghi log.
  - `backup.ps1`: tải / đối chiếu / `-Release` / đổi tên `[HD Dọc]` cũ / thumbnail đều theo thư mục con. Đọc được thư mục cũ (phẳng) và thư mục mới.
  - Sửa SHO1 G1, ghi chú HD2 G1, cập nhật hướng dẫn `store-3090.md`, ops-notes.
- Out of scope: đổi tên file; xóa file; đổi API / kiểu dữ liệu phía VM (`src/auto_short/store/*` không đổi, trừ khi test chỉ ra cần); thư mục `luu-tru-short.ps1` (`E:\LuuTru_Short`); chuyển `_cu*`.

## Authority / key decisions

- HD2 G1 / G8 (an toàn đường dẫn): mọi thư mục con đi qua `no_links` / `inside`. Tên thư mục con là hằng số trong code, không lấy từ request.
- SHO1 G1, sửa trong task này: bỏ câu "phẳng trong thư mục bộ kinh". Tên file giữ nguyên, thư mục con suy ra theo bảng ở Goal.
- `[Trial before bulk]`: chạy thật 1 bộ kinh nhỏ trước, HUMAN LEAD xem Explorer + web 8080 rồi mới `all`.

## Implementation approach

- Một hàm duy nhất `subdir(kind, name)` → `HD` / `HD Mobile` / `Goc` / `Hinh` / `Short\Tap NN` / `KhaiThi\Tap NN` / `Short\Khac`. Số tập lấy từ ` - Tập N` trong tên, 2 chữ số. Dùng cho đọc, ghi, sắp xếp và `backup.ps1` (bên PowerShell viết lại cùng quy tắc, có test so bảng mẫu).
- Đọc theo thứ tự: thư mục con → gốc. `index` / `lookup` / `head` / `GET` dùng chung một hàm tìm.
- Bản dọc đời cũ `[HD Dọc]` đi vào `HD Mobile\` (cùng loại `vertical`).

## Phải giữ nguyên

- API kho, token, Range, sha256, 409 khi trùng, không xóa qua API, cache index.
- Định dạng `index.csv` / `danh-sach.csv` / `index-short.csv` / `SHA256SUMS.txt`.
- Chạy `rename_vertical` (STN1) sau khi sắp xếp vẫn đúng.

## Code bị thay / xóa

- Ghép đường dẫn `inside(folder, name)` cho file media trong `store.py`: thay bằng hàm tìm theo thư mục con. Không để lại 2 cách ghép song song.
- Các `Join-Path $Dest $name` cho file media trong `backup.template.ps1`: thay bằng hàm đường dẫn theo loại.

## Acceptance Criteria

1. Kho phẳng cũ (chưa sắp xếp): `index`, `GET`, `HEAD`, Range trả đúng như trước (test với cây thư mục mẫu).
2. `PUT` HD / dọc / gốc / Short / Khai thị ghi vào đúng thư mục con. Bản thay thế: bản cũ vào `_cu\`.
3. `reorganize --series <id|all>` chạy thử không đổi gì trên đĩa và in đúng kế hoạch. `--apply` chuyển hết file nhận ra, để nguyên file lạ, trùng đích thì dừng trước khi chuyển. Chạy lại lần 2: không còn gì để chuyển.
4. Sau `--apply`: `index` giống hệt trước (cùng video_id / kind / file / sha / size).
5. Đường dẫn ngoài thư mục bộ kinh, symlink / junction ở thư mục con: bị từ chối.
6. `backup.ps1` (chạy thử bằng `make_backup.py` / test hiện có) dùng thư mục con cho mp4 và `.jpg`, `-Release` tìm thấy file ở cả 2 kiểu cây.
7. SHO1 G1, HD2 ghi chú, `store-3090.md`, ops-notes được cập nhật.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_store_*.py tests/test_backup*.py -q`, chứng minh AC 1–6
- Full suite (ORCHESTRATOR chạy ngoài sandbox)
- Chạy thật: chép kho mẫu nhỏ trên VM, chạy `store.py` thật + `reorganize --series <id|all> --apply`, so `index` trước / sau
- Trên 3090 (HUMAN LEAD chạy): chép `store.py`, chạy thử `sap-xep-kho.ps1` cho 1 bộ, xem kế hoạch, `-Apply`, kiểm web 8080 xem / tải 1 HD, 1 dọc, 1 Short, rồi mới `all`

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm dữ liệu thật trên kho 3090 (di chuyển file), không chạm database, security model hay API. Manual test trên 3090 là gate trước khi chạy `all`.

- [ ] Chạy thử 1 bộ: danh sách hợp lý, không có file lạ quan trọng
- [ ] `-Apply` 1 bộ: Explorer đúng cây, web 8080 mở được HD / dọc / Short
- [ ] `backup.ps1` chạy lại trên bộ đã sắp xếp: không tải lại, thumbnail vào `Hinh\`

## Result

- Main changes: `store.py` vị trí media qua `subdir` / `media_path` (thư mục loại trước, gốc phẳng sau); PUT / bản dọc thay thế ghi thư mục con, `_cu\` ở gốc bộ; `reorganize --series <id|all> [--apply]` kiểm toàn bộ trước khi chuyển, log vào `backup-log.txt`; wrapper `tools/store/sap-xep-kho.ps1`. `backup.template.ps1`: `StoreSubdir` / `BackupPath` cho tải, thumbnail (`Hinh\`), CSV cũ, `-Release`, đổi `[HD Dọc]` (cập nhật cả tên trong CSV / SUMS). SHO1 G1, HD2 G1, guide, ops-notes cập nhật. `src/auto_short/store/*` không đổi.
- Tests (ORCHESTRATOR, ngoài sandbox, 2026-11-04):
  - Kho + backup (8 file `test_store_*`, `test_backup_stn1`, `test_hd_backup`, …): 367 passed, 1 skipped (thực thi PowerShell — VM không có `pwsh`).
  - Full suite `--deselect` test chập chờn đã biết (`test_lower_thread_priority…`, chạy riêng PASS): **4010 passed, 2 skipped** (25:58).
  - Chạy thật: kho mẫu phẳng (6 HD/dọc/gốc, 9 Short/KT, 2 jpg, 1 file lạ, `_cu`) + `store.py` server thật port 18391: dry-run 17 file, không đổi đĩa; `--apply` → cây đúng Goal; `index` trước = sau (15 mục); GET sha + Range 206 đúng trước và sau; lần 2: 0 file; PUT Short mới → `Short\Tap 03\`; file lạ / `_cu` giữ nguyên.
- AC → test: AC1 `test_http_read_routes` + Range; AC2 `test_str1_put_layout_and_http_reads`, `test_str1_flat_vertical_replacement_archives_then_publishes_in_subdir`, `test_store_revision_roundtrip`; AC3–4 `test_str1_reorganize_plan_apply_index_unchanged_and_idempotent`, `test_str1_collision_in_all_stops_before_any_move`, `test_str1_partial_blocks_reorganize` + chạy thật; AC5 `test_path_validation`, `test_str1_media_subdirectory_links_refused`; AC6 `test_str1_powershell_layout_rules_and_call_sites`, `test_hd_backup` template (thực thi PS: chưa); AC7 docs.
- Diff + / −: app +286 / −49 (gồm wrapper), test +290 / −20, docs +74 / −13.
- Helper mới: `subdir`, `media_path`, `media_kind`, `_media_files` (Python), `StoreSubdir`, `BackupPath` (PS, cùng quy tắc, có test bảng mẫu) — `inside` không có lựa chọn cây mới / cũ; backup script độc lập không import được Python.
- Review: ORCHESTRATOR review diff; sửa 2 test giả định cây phẳng (`test_hd_backup.py:346`, `test_vertical_silence_intro.py::test_store_revision_roundtrip` — `_cu` / SUMS ở gốc bộ), owned paths bổ sung tương ứng. Implementer: Codex 1 vòng (effort high, 141.882 tokens).
- Important findings / decisions: khóa `reorganize` chỉ trong một process → guide bắt buộc `Stop-ScheduledTask AutoShortStore` + dừng backup trước khi chạy.
- Known limitations: PowerShell chưa thực thi (chỉ test tĩnh); gate 3090 (1 bộ nhỏ → `all`) do HUMAN LEAD chạy sau merge.
- PR:
