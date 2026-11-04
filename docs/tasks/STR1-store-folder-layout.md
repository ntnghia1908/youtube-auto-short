# Task: STR1 — Kho 3090: thư mục con theo loại, Short / Khai thị chia theo tập

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2 (sửa SHO1 G1 "tên phẳng trong thư mục bộ kinh" và cách đặt file của HD2 G1)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex, mặc định của project (HUMAN LEAD 2026-10-25); hết quota thì subagent `implementer`
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-04 (chat): "Kho 3090 hoạt động tốt nhưng khá rối: tất cả hình, bản gốc, ngang... đều nằm trong cùng một thư mục, nên structure lại cây thư mục"; chọn phương án "Theo loại + Short theo tập"
- Parallel group: —
- Owned paths: `tools/store/store.py`, `tools/store/setup-store.ps1` (nếu cần), script mới `tools/store/sap-xep-kho.ps1`, `scripts/backup/backup.template.ps1`, `scripts/backup/make_backup.py` (nếu cần), `tests/test_store_*.py`, `tests/test_backup*.py`, `docs/guides/store-3090.md`, `docs/decisions/SHO1-short-store-3090.md` (chỉ G1), `docs/decisions/HD2-external-store-3090.md` (chỉ ghi chú G1), `docs/workflow/ops-notes.md` (cách chạy trên 3090), file này
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
  - Lệnh sắp xếp: `store.py --reorganize <series|all> [--apply]`, có wrapper `sap-xep-kho.ps1`. Mặc định chạy thử: in danh sách sẽ chuyển, file không nhận ra (để nguyên tại chỗ), và trùng đích (dừng, không ghi đè). `--apply` khóa kho giống `rename_vertical`, dùng `rename` trong cùng ổ đĩa (không chép), chạy lại không lỗi, ghi log.
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
3. `--reorganize` chạy thử không đổi gì trên đĩa và in đúng kế hoạch. `--apply` chuyển hết file nhận ra, để nguyên file lạ, trùng đích thì dừng trước khi chuyển. Chạy lại lần 2: không còn gì để chuyển.
4. Sau `--apply`: `index` giống hệt trước (cùng video_id / kind / file / sha / size).
5. Đường dẫn ngoài thư mục bộ kinh, symlink / junction ở thư mục con: bị từ chối.
6. `backup.ps1` (chạy thử bằng `make_backup.py` / test hiện có) dùng thư mục con cho mp4 và `.jpg`, `-Release` tìm thấy file ở cả 2 kiểu cây.
7. SHO1 G1, HD2 ghi chú, `store-3090.md`, ops-notes được cập nhật.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_store_*.py tests/test_backup*.py -q`, chứng minh AC 1–6
- Full suite (ORCHESTRATOR chạy ngoài sandbox)
- Chạy thật: chép kho mẫu nhỏ trên VM, chạy `store.py` thật + `--reorganize --apply`, so `index` trước / sau
- Trên 3090 (HUMAN LEAD chạy): chép `store.py`, chạy thử `sap-xep-kho.ps1` cho 1 bộ, xem kế hoạch, `-Apply`, kiểm web 8080 xem / tải 1 HD, 1 dọc, 1 Short, rồi mới `all`

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm dữ liệu thật trên kho 3090 (di chuyển file), không chạm database, security model hay API. Manual test trên 3090 là gate trước khi chạy `all`.

- [ ] Chạy thử 1 bộ: danh sách hợp lý, không có file lạ quan trọng
- [ ] `-Apply` 1 bộ: Explorer đúng cây, web 8080 mở được HD / dọc / Short
- [ ] `backup.ps1` chạy lại trên bộ đã sắp xếp: không tải lại, thumbnail vào `Hinh\`

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
