# Task: STN1 — Tên bản HD / HD Mobile trên kho có giảng sư, bỏ hậu tố `(rN)`

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — mặc định của project (HUMAN LEAD 2026-10-25, tiết kiệm quota Claude); hết quota → subagent `implementer`
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-03 (chat): "đổi thành [HD Mobile] Kinh Địa Tạng Bồ Tát Bổn Nguyện - PS. Tịnh Không - Tập 1"; bản `(r2)` xen kẽ bản cũ khi sắp xếp
- Parallel group: —
- Owned paths: `tools/store/store.py`, `scripts/backup/backup.template.ps1`, `scripts/backup/make_backup.py` (nếu cần truyền giảng sư), `tests/test_backup*.py`, `src/auto_short/store/offload.py`, `src/auto_short/store/shorts.py` (chỉ nếu dùng chung hàm đặt tên), `src/auto_short/config.py` (`[store]`), `src/auto_short/publish/thumbs.py`, `tests/test_store_*.py`, `tests/test_publish_thumbs.py`, `tests/test_vertical_silence_intro.py` (bổ sung khi review: test `(r2)` bản dọc cũ là "Code bị thay"), `docs/workflow/ops-notes.md` (cách chạy lệnh đổi tên trên 3090), file này
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

- Main changes: CLI `rename-vertical` chạy thử / `--apply` cho HD + vertical, ghi nối metadata qua `_publish`, kế thừa thứ tự cột Export-Csv từ `danh-sach.csv` khi chưa có index; chuyển bản lưu trữ vào `_cu`, giữ bản trùng tên. `put` vertical nhận alias tên cũ / mới, SHA mới bỏ revision và lưu bản trước; rollback bản trước nếu bước thay file thất bại. Thêm `[store] speaker_label`, cập nhật offload, backup generator/template và PUB2. Short giữ revision; HD conditional replace giữ đường dẫn hiện hành.
- Tests (IMPLEMENTER, sandbox): targeted cuối **257 passed, 15 deselected**. `git diff --check` PASS. Không chạy full suite hoặc gọi HTTP/mạng thật.

  | AC | Test (tên trong các file đã sửa / thêm) |
  |---|---|
  | AC1 | `test_rename_hd_vertical_dry_run_apply_idempotent` (102 dọc: 64 r2 + 38 thường, 102 ngang thường/r2, archive, `/index` qua handler bộ nhớ, cột/CRLF); `test_rename_refuses_unsafe_plan_without_changes` |
  | AC2 | `test_rename_hd_vertical_dry_run_apply_idempotent` (lần hai byte và mtime giữ nguyên) |
  | AC3 | `test_vertical_put_accepts_transition_names_and_archives_only_after_validation`; `test_vertical_custom_label_and_failed_update_preserve_current`; regression `test_short_revisions_keep_history_and_current_index` |
  | AC4 | `test_vertical_speaker_config_and_existing_speaker`; `test_push_confirm_release_rules`; `test_store_rejects_invalid_speaker_label` |
  | AC5 | `test_store_names_with_optional_speaker_match_thumbnail` (cả hai chế độ PUB2, ba tag cũ/mới, mẫu tập 7) |
  | AC6 | `tests/test_backup_stn1.py::test_backup_names_and_existing_file_resolution`; test generator/template hiện hữu trong `test_hd_backup.py` (không sửa file này) |
  | AC7 | `test_hd_replace_after_rename_uses_current_path`; `test_hd_conditional_replace_preserves_identity_csv_and_rejects_conflicts` |

- Lệnh verification: prefix `PYTHONPATH=/home/ntnghia/projects/yas-stn1/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`; các đường dẫn dưới đây tương đối từ worktree.
  - Lượt đầu 123 PASS / 1 FAIL: assertion của test mới giả định archive không trùng tên. Sửa test mới để kiểm đủ hai bản lưu trữ khi trùng tên; không sửa test cũ để che lỗi.
  - `tests/test_store_server.py tests/test_publish_thumbs.py tests/test_backup_stn1.py -q -p no:cacheprovider -x --tb=short`: 200 PASS trước khi thêm 6 ca bảo toàn file khi upload lỗi / giảng sư tuỳ chỉnh; các ca bổ sung PASS trong lượt gộp cuối.
  - `tests/test_store_offload.py -q -p no:cacheprovider -x --tb=short -k 'not test_loop_uses_thread_and_short_success_delay and not test_lifespan_stops_hash_worker'`: 44 PASS, 2 deselected.
  - `tests/test_hd_backup.py -q -p no:cacheprovider -x --tb=short -k 'generator or template or hd_intro_released_backup_sha_is_stored_identity'`: 7 PASS, 13 deselected.
  - Lượt gộp cuối: 5 file trên, cùng cờ `-q -p no:cacheprovider -x --tb=short`, `-k` loại đúng 2 ca offload và 13 ca HD backup dùng `logged()` / TestClient; **257 PASS, 15 deselected**.
- Lệnh không hoàn tất: lệnh 4 file HUMAN LEAD giao + `tests/test_backup_stn1.py` treo tại `test_loop_uses_thread_and_short_success_delay`, đã dừng (exit 130). Chạy chẩn đoán `timeout -s INT -k 3s 35s ... tests/test_store_offload.py tests/test_hd_backup.py -vv -p no:cacheprovider -x --tb=short -o faulthandler_timeout=20`: stack ở asyncio selector, test offload dòng `asyncio.run(run())`, timeout exit 137. Không sửa test lifecycle để né hạn chế môi trường; ca lifespan còn lại và 13 ca TestClient không chạy trong lượt cuối.
- Diff + / − (app, test): app **+191 / −17**; test **+239 / −2** (gồm file mới chưa stage). Hai assertion offload cũ cập nhật tên theo AC4.
- Helper mới (đã tìm, lý do không tái dùng): đã đọc và tìm bằng `rg -n 'def |revision|r[0-9]' src/auto_short/store/shorts.py tools/store/store.py`, tra `_destination`, `_publish`, `_metadata`, `_rows`, `stored_series` và fixtures hiện hữu. Tái dùng các helper đường dẫn/metadata và `_destination` (đã dùng `stored_series`), đưa regex revision có sẵn thành `REVISION`. `hd_name` / `vertical_key` cần cho tên canonical và alias, vì `_destination` dựa workspace VM và không thể import vào store stdlib độc lập. `_archive_plan` đặt tên archive không ghi đè, helper cũ chưa có hành vi này. `rename_vertical` là operation CLI mới. PowerShell `LegacyBackupName` tách thân hàm cũ; `ExistingBackupName` chọn tên thực tế qua file/CSV để checksum, thumbnail, release cùng trỏ đúng file; `Rename-LegacyMobile` chỉ đổi prefix nên không thay thế được.
- Review: IMPLEMENTER đã đọc diff, đối chiếu Owned paths và AC; không đổi dependency/API HTTP. Chờ review độc lập của ORCHESTRATOR; chưa tuyên bố READY toàn bộ vì verification ngoài sandbox còn thiếu.
- Important findings / decisions: khoá chỉ có hiệu lực trong process; khi chạy CLI phải dừng server và writer khác trước (hướng dẫn ở `ops-notes.md`). Không đổi G1–G3. Bản sao dữ liệu / migration thật chưa thực hiện.
- Known limitations: thiếu PowerShell trên VM, chỉ kiểm script sinh ra và nội dung template. ORCHESTRATOR chạy lại các ca bị loại / required verification ngoài sandbox, full suite và bản sao metadata/file rỗng; sau merge HUMAN LEAD triển khai 3090 rồi kiểm xem/tải 8080. Chưa gọi mạng, không commit/push/PR.
- ORCHESTRATOR review (2026-11-03, claude-code):
  - Sửa: `publish/thumbs.py` — Codex đổi `FILE_NAME` sang `(.+?)` làm tên bộ có " - " (vd Thập Thiện "… - Lão Pháp Sư … (biên dịch mới 2023)") bị cắt; giữ regex tham lam cũ + `_same_series` (bằng, hoặc bắt đầu bằng "<bộ> - "). Test `test_series_containing_dash_still_matches_with_and_without_speaker`.
  - Sửa: `tests/test_vertical_silence_intro.py::test_store_revision_roundtrip[vertical]` khẳng định `(r2)` cho bản dọc (hành vi bị thay theo contract) → viết lại theo STN1: tên chuẩn có giảng sư, bản trước vào `_cu`, cùng sha tên cũ không tạo file.
  - Full suite (`-n 4`, nice 10): lượt 1 **3789 passed, 1 failed** (ca trên), 1 skipped; sau sửa, 7 file liên quan **316 passed**.
  - Chạy thật bản sao: metadata từ `/index` kho 3090 thật (tunnel 18090; tên + sha thật, file rỗng, `index.csv` + `SHA256SUMS.txt`), 5 series. Chạy thử: KĐT 204 dòng, VLT 748, CƯT 72, TTN 1. `--apply` cả 4 → self-test 1710 file (hd 476, vertical 549) như trước; index: 476 hd + 549 vertical đều có "PS. Tịnh Không", 0 tên `(rN)`; source 685 không đổi; chạy thử lại 0 dòng đổi (idempotent); thư mục con `_cu-khong-intro` không bị đụng.
  - Diff + / − tổng: app +198 / −18, test +263 / −11.
  - Giới hạn: tên bản dọc không theo mẫu `[tag] X - Tập N.mp4` → `put` khác sha bị 400 (thực tế 549 / 549 bản dọc kho đều đúng mẫu). PowerShell (`backup.template.ps1`) chưa chạy được trên VM. CLI phải chạy khi đã dừng task `AutoShortStore` (ops-notes).
- PR: #198
