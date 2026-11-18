# Task: PUB3.2 — Lên lịch chừa chỗ cho mã thiếu; bản trùng chỉ lên lịch 1 bản

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1 — đổi cách chọn giờ của `publish schedule` + tùy chọn dời lịch video riêng tư đã có lịch (G6); không đổi schema journal
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, test, chạy thử (dry-run) trên 1 kênh, chạy thật sau khi HUMAN LEAD duyệt bảng
- Implementer: codex — hàm thuần `schedule.plan` + nối `check.inventory` vào lệnh `schedule`
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-19 "nếu thiếu chỗ nào thì lên lịch tới đúng chỗ đó rồi chừa khoảng thiếu để sau khi upload lên thì đắp vào. Nếu trùng thì không lên lịch luôn" → sửa: "Trùng thì lên lịch 1 bản bản còn lại bỏ. duyệt PUB3.2 và áp dụng luôn cho các tập đang thiếu"
- Parallel group: —
- Owned paths: `src/auto_short/publish/schedule.py`, `src/auto_short/publish/__main__.py` (lệnh `schedule` truyền inventory, tùy chọn `--reflow`), `tests/test_publish_schedule_gaps.py` (mới), contract này
- Dependencies: PUB3 (#218), PUB3.1 `check.inventory` / `check.compare` (#221) — đã merge
- Base commit / branch: `e058298` / `feature/pub32-schedule-gaps`
- Human Lead approval: accepted 2026-11-19 ("duyệt PUB3.2")
- Implementation authorized: YES

## Goal

Lịch mỗi loại (dọc / khai thị / Short) đi đúng thứ tự mã trên website, kể cả khi trên kênh còn thiếu bản nháp. Mã thiếu được **giữ chỗ** (khung giờ để trống); khi HUMAN LEAD upload bổ sung, lần `schedule` sau đặt video đó vào đúng khung đã giữ. Bản nháp trùng mã: chỉ một bản được lên lịch, các bản còn lại bỏ qua. Áp dụng cho cả các mã đang thiếu hiện nay (G6).

## Scope

- In scope: thuật toán chọn khung trong `schedule.plan` (giữ chỗ cho mã thiếu, lấp chỗ đã giữ, bỏ qua bản trùng); lệnh `schedule` đọc inventory website như `check`; bảng dry-run ghi rõ "giữ chỗ cho T… (thiếu)" và "trùng — chưa lên lịch".
- Out of scope: xóa video; đổi giờ video đã công khai; thay đổi khung giờ (G1 PUB3); `check` / trang Lịch YouTube (chỉ đọc kết quả mới qua dòng cảnh báo hiện có).

## Authority / key decisions

- **G1 thứ tự theo website**: với mỗi loại, dãy mã mong đợi = `check.inventory` (mã website có), sắp theo (bộ, tập, clip). Mỗi mã chiếm một khung theo thứ tự đó, nối sau khung của mã liền trước đã có lịch.
- **G2 giữ chỗ cho mã thiếu**: mã nằm **giữa** hai mã đã có trên kênh (lỗ hổng, cùng định nghĩa `missing` của `check.compare`) và chưa có video → nhận khung "giữ chỗ" trong kế hoạch (không gọi YouTube), các mã sau nối tiếp sau khung đó. Mã ở cuối dãy chưa upload (sau mã lớn nhất trên kênh) → không giữ chỗ.
- **G3 lấp chỗ**: video mới của mã đã có lịch liền trước và liền sau → nhận khung trống sớm nhất **sau** khung của mã liền trước và **trước** khung của mã liền sau (khung không trùng với video nào đã có lịch cùng loại). Không còn khung trống giữa hai mốc đó → đặt khung trống sớm nhất sau mã liền trước và ghi cảnh báo "lệch thứ tự" trong bảng.
- **G4 bản trùng**: mã có ≥ 2 bản nháp riêng tư chưa lịch → lên lịch **một** bản (upload sớm nhất, như PUB3), các bản còn lại "bỏ qua — trùng" + id; mã đã có bản công khai / có lịch → mọi nháp mới của mã đó bỏ qua (như PUB3). Bảng có dòng tóm tắt các bản bỏ qua để HUMAN LEAD xóa.
- **G6 áp dụng cho mã đang thiếu (dời lịch, `--reflow`)**: tùy chọn mới của `schedule`. Với mỗi loại, dựng lại dãy khung theo G1–G2 cho các video **riêng tư đã có lịch trong tương lai** (≥ now + 1 giờ) sau mã thiếu đầu tiên: video công khai và video có lịch trước mốc đó giữ nguyên; các video riêng tư có lịch phía sau được dời (`videos.update` `status.publishAt`, giữ `privacyStatus` private, `selfDeclaredMadeForKids` như cũ) sang khung mới chừa chỗ cho mã thiếu. Lỗ hổng nằm trong vùng đã công khai thì không mở được → mã thiếu đó khi upload theo G3 (khung trống sớm nhất ≥ now). Dry-run mặc định in bảng "dời T… dd/mm HH:MM → dd/mm HH:MM" + chỗ giữ; `--apply` mới ghi; journal ghi bản ghi mới cho mỗi video dời (giữ bản cũ). Chạy thật: 1 kênh trước, HUMAN LEAD xem bảng.
- **G5 không đổi lịch cũ (trừ `--reflow` G6)**: video đã có `publishAt` / công khai giữ nguyên; journal, `--limit`, `--only`, thêm playlist, `selfDeclaredMadeForKids` như PUB3 / PUB3.1.

## Implementation approach

- `schedule.plan(videos, now, expected=None)`: `expected` = tập mã website theo loại; `None` → hành vi cũ (giữ test cũ PASS).
- Lấp chỗ: dựng danh sách khung đã dùng cùng loại; khung trống = khung hợp lệ theo `SLOTS[kind]` không bị chiếm.
- `__main__` lệnh `schedule --playlist`: tính `check.inventory(cfg, pid)` và truyền vào.

## Phải giữ nguyên

- Khung giờ G1 PUB3, journal, bỏ qua video công khai / có lịch, thêm playlist, hạn mức (không thêm lời gọi API).
- Test cũ PASS không sửa, trừ test khẳng định quy tắc trùng cũ (ghi rõ trong Result nếu đổi).

## Code bị thay / xóa

- Không thay quy tắc trùng (G4 giữ "bản upload sớm nhất"), chỉ thêm dòng tóm tắt.

## Acceptance Criteria

1. G2: thiếu T30_KT06 giữa T30_KT05 và T31_KT01 → T31_KT01 nhận khung sau khung giữ chỗ; mã cuối chưa upload không giữ chỗ.
2. G3: upload T30_KT06 sau đó → nhận đúng khung giữ chỗ; hết khung giữa hai mốc → khung sớm nhất sau mã trước + cảnh báo "lệch thứ tự".
3. G4: 2 nháp cùng mã → đúng 1 bản (upload sớm nhất) được lên lịch, bản kia bỏ qua + có trong dòng tóm tắt; nháp + bản đã công khai / có lịch → nháp bỏ qua.
4. G5 + test cũ PASS; `expected=None` giữ hành vi cũ.
5. G6: `--reflow` dry-run không gọi ghi; chỉ dời video riêng tư có lịch ≥ now + 1 giờ phía sau mã thiếu; công khai / có lịch gần không đổi; thứ tự sau dời đúng G1–G2; `--apply` ghi `publishAt` + journal; hạn mức hết giữa chừng → dừng an toàn, chạy lại tiếp được (idempotent).

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_publish_schedule_gaps.py tests/test_publish_schedule.py tests/test_publish_check.py` (IMPLEMENTER).
- Full suite `-n auto` (ORCHESTRATOR).
- Dry-run thật 1 kênh (CƯT: thiếu T30_KT06–07), gửi bảng cho HUMAN LEAD trước khi `--apply`.

## Manual test checklist (Tech Lead)

- [ ] HUMAN LEAD xem bảng dry-run CƯT: chỗ giữ cho mã thiếu đúng, bản trùng không lên lịch.

## Result

(chưa có)
