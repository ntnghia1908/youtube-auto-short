# Task: STN1 — Tên bản HD / HD Mobile trên kho có giảng sư, bỏ hậu tố `(rN)`

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — mặc định của project (HUMAN LEAD 2026-10-25, tiết kiệm quota Claude); hết quota → subagent `implementer`
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-03 (chat): "đổi thành [HD Mobile] Kinh Địa Tạng Bồ Tát Bổn Nguyện - PS. Tịnh Không - Tập 1"; bản `(r2)` xen kẽ bản cũ khi sắp xếp
- Parallel group: —
- Owned paths: `tools/store/store.py`, `scripts/backup/backup.template.ps1`, `scripts/backup/make_backup.py` (nếu cần truyền giảng sư), `tests/test_backup*.py`, `src/auto_short/store/offload.py`, `src/auto_short/store/shorts.py` (chỉ nếu dùng chung hàm đặt tên), `src/auto_short/config.py` (`[store]`), `src/auto_short/publish/thumbs.py`, `tests/test_store_*.py`, `tests/test_publish_thumbs.py`, `docs/workflow/ops-notes.md` (cách chạy lệnh đổi tên trên 3090), file này
- Dependencies: none
- Base commit / branch: `23d5088` (origin/main) / `feature/stn1-store-vertical-rename`
- Human Lead approval: accepted 2026-11-03 (chat: G1 cả bản ngang, G2 mọi bộ kinh, G3 ok)
- Implementation authorized: YES

## Goal

Trên kho 3090, mỗi tập chỉ còn một bản dọc `[HD Mobile] <bộ kinh> - PS. Tịnh Không - Tập N.mp4` và một bản ngang `[HD] <bộ kinh> - PS. Tịnh Không - Tập N.mp4` (không `(rN)`), web 8080 vẫn xem / tải được, bản dọc đẩy sau này dùng đúng tên đó, và PUB2 vẫn ghép được thumbnail cho video upload bằng tên mới.

## Bối cảnh (đo 2026-11-03)

- Kho Địa Tạng (`E:\KinhDiaTang_HD`, series `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`): 102 bản dọc hiện hành = 64 `… - Tập N (r2).mp4` (render lại có intro) + 38 `… - Tập N.mp4` (có intro từ đầu). 64 file cũ không intro còn nằm cạnh làm bản lưu trữ (`tools/store/store.py` `put`: đổi sha → tên `(rN)`, giữ file cũ).
- Metadata kho chỉ ghi nối: `index.csv` / `danh-sach.csv` (dòng sau thắng) + `SHA256SUMS.txt` (index chỉ nhận tên có trong SUMS). Đổi tên tay bằng Explorer làm kho mất file.
- `put` của bản dọc chỉ chấp nhận tên trùng tên gốc (bỏ `(rN)`) của dòng hiện hành → sau khi đổi tên, lần đẩy lại sẽ bị 409 nếu VM vẫn gửi tên cũ.
- `publish/thumbs.py` `FILE_NAME` lấy `(.+)` trước ` - Tập N` làm tên bộ → `… - PS. Tịnh Không` lệch tên bộ; `TITLE` đã chấp nhận đoạn giữa.

## Quyết định HUMAN LEAD (2026-11-03)

- G1: đổi tên cả `[HD Mobile]` (dọc) lẫn `[HD]` (ngang); `[Goc]` (source) và Short giữ nguyên.
- G2: một chuỗi giảng sư dùng chung mọi bộ kinh: cấu hình `[store] speaker_label = "PS. Tịnh Không"` (mặc định này). Bộ kinh mà tên bộ đã chứa "Tịnh Không" thì không chèn thêm.
- G3: bản lưu trữ cũ (khác sha, hoặc tên cũ) chuyển vào thư mục con `_cu\` của bộ, không xoá.
- Ops 2026-11-03: HUMAN LEAD đã chạy `don-ban-cu-kdt.ps1 -Apply` trên 3090 (64 bản dọc cũ Địa Tạng → `E:\KinhDiaTang_HD\_cu-khong-intro\`).

## Scope

- In scope:
  - `store.py` (3090): lệnh dòng lệnh `rename-vertical --series <id> --format … [--apply]`: với mỗi bản dọc hiện hành, (kind `hd` và `vertical`) đổi tên file sang tên mới, ghi nối dòng `index` + `SUMS` cho tên mới (giữ sha), chuyển file lưu trữ cũ cùng tập vào thư mục con theo G3; mặc định chạy thử, in bảng; giữ khoá `_put_lock` / `_lock` như `put`; không chạy khi có `.part`.
  - `put` bản dọc: tên gửi lên khớp tên hiện hành theo dạng chuẩn hoá (bỏ `(rN)`, bỏ đoạn giảng sư) để không 409 trong giai đoạn chuyển; bản mới khác sha → đặt tên mới không `(rN)`, file cũ chuyển vào thư mục con thay vì nằm cạnh.
  - `offload.push_vertical`: tên `[HD Mobile] <bộ kinh> - <giảng sư> - Tập N.mp4` theo G2.
  - `backup.template.ps1` (3090): `BackupName` sinh tên mới cho `[HD]` / `[HD Mobile]`; nhận file đã có theo tên cũ hoặc tên mới (không tải lại); `-Release` / `danh-sach.csv` vẫn khớp.
  - `replace` HD (HD2b, `render/hd_intro.py` dùng `row["file"]` hiện hành) phải chạy đúng sau đổi tên.
  - `publish/thumbs.py`: `FILE_NAME` nhận đoạn ` - <giảng sư>` tuỳ chọn trước ` - Tập N`.
- Out of scope: đổi tên video đã upload trên YouTube; Short / `index-short.csv` (SHO1b giữ nguyên); `[Goc]` source; script dọn một lần `output/_operations/kdt-store-cleanup-2026-11-03/don-ban-cu-kdt.ps1` (ops, không thuộc code).

## Phải giữ nguyên

- Index kho: một dòng hiện hành / (video_id, kind); sha256 và kích thước không đổi khi đổi tên.
- `put` HD / Short, `replace` HD (HD2b), redownload, offload Short (SHO1) không đổi hành vi.
- PUB2 nhận `[HD]`, `[HD Dọc]`, `[HD Mobile]` tên cũ như hiện tại.

## Code bị thay / xóa

- Nhánh đặt tên `(rN)` cho bản dọc trong `store.py` `put` (thay bằng tên không hậu tố + chuyển bản cũ); `(rN)` của Short giữ nguyên.

## Acceptance Criteria

1. `rename-vertical` (tên lệnh tuỳ IMPLEMENTER, vd `rename-hd`) chạy thử không đổi file / metadata; `--apply` trên thư mục mẫu (bản dọc: 64 `(r2)` + 38 thường; bản ngang thường + có `(rN)`; vài bản cũ nằm cạnh): mọi file HD / HD Mobile hiện hành đổi sang tên mới ở gốc, bản cũ trong `_cu\`, `/index` trả cùng số dòng, cùng sha, tên mới.
2. Chạy lại `--apply` lần hai: không đổi gì (idempotent).
3. `put` bản dọc cùng sha với tên cũ hoặc tên mới → 200, không tạo file; khác sha → file tên mới (không `(rN)`), file trước chuyển vào thư mục con, index trỏ file mới.
4. `push_vertical` gửi tên có giảng sư theo G2.
5. PUB2: `[HD Mobile] <bộ kinh> - PS. Tịnh Không - Tập 7.mp4` → vertical, `[HD] … - PS. Tịnh Không - Tập 7.mp4` → landscape, tập 7, sẵn sàng; tên cũ vẫn đúng.
6. `backup.template.ps1`: tên mới; file đã có theo tên cũ / mới đều được nhận, không tải lại (kiểm bằng test sinh script + đọc mẫu tên, PowerShell không có trên VM).
7. `replace` HD sau đổi tên: thay đúng file hiện hành (tên mới), không 409.

## Required verification

- `PYTHONPATH=src python -m pytest tests/test_store_*.py tests/test_publish_thumbs.py -q` — AC1–AC5.
- Full suite (ORCHESTRATOR, ngoài sandbox).
- Chạy thật: bản sao thư mục Địa Tạng (chỉ metadata + file rỗng cùng tên, sha thật) qua store.py trên VM; sau merge HUMAN LEAD chép `store.py` lên 3090, chạy thử rồi `--apply`; ORCHESTRATOR kiểm `/index` qua tunnel 18090 và mở 1 tập trên 8080.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API ngoài kho nội bộ; manual test sau automated verification là điểm danh.

- [ ] 3090: chạy thử in đủ 102 dòng; `--apply`; Explorer sắp xếp theo tên không còn xen kẽ.
- [ ] 8080: xem / tải bản dọc Địa Tạng tập 1 và 100.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
