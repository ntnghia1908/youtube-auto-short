# Task: PUB3.2 — Lên lịch chừa chỗ cho mã thiếu; bản trùng không lên lịch

## Status / Approval

- Status: DRAFT — chờ HUMAN LEAD duyệt
- Type: FEATURE
- Change class: S1 — đổi cách chọn giờ của `publish schedule`; không đổi schema journal, không thêm thao tác ghi YouTube mới
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, test, chạy thử (dry-run) trên 1 kênh, chạy thật sau khi HUMAN LEAD duyệt bảng
- Implementer: codex — hàm thuần `schedule.plan` + nối `check.inventory` vào lệnh `schedule`
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-19 "nếu thiếu chỗ nào thì lên lịch tới đúng chỗ đó rồi chừa khoảng thiếu để sau khi upload lên thì đắp vào. Nếu trùng thì không lên lịch luôn"
- Parallel group: —
- Owned paths: `src/auto_short/publish/schedule.py`, `src/auto_short/publish/__main__.py` (lệnh `schedule` truyền inventory), `tests/test_publish_schedule_gaps.py` (mới), contract này
- Dependencies: PUB3 (#218), PUB3.1 `check.inventory` / `check.compare` (#221) — đã merge
- Base commit / branch: `e058298` / `feature/pub32-schedule-gaps`
- Human Lead approval: chưa
- Implementation authorized: NO

## Goal

Lịch mỗi loại (dọc / khai thị / Short) đi đúng thứ tự mã trên website, kể cả khi trên kênh còn thiếu bản nháp. Mã thiếu được **giữ chỗ** (khung giờ để trống); khi HUMAN LEAD upload bổ sung, lần `schedule` sau đặt video đó vào đúng khung đã giữ. Bản nháp trùng mã không được lên lịch cho tới khi HUMAN LEAD xóa bớt.

## Scope

- In scope: thuật toán chọn khung trong `schedule.plan` (giữ chỗ cho mã thiếu, lấp chỗ đã giữ, bỏ qua bản trùng); lệnh `schedule` đọc inventory website như `check`; bảng dry-run ghi rõ "giữ chỗ cho T… (thiếu)" và "trùng — chưa lên lịch".
- Out of scope: đổi giờ video đã có lịch; xóa video; thay đổi khung giờ (G1 PUB3); `check` / trang Lịch YouTube (chỉ đọc kết quả mới qua dòng cảnh báo hiện có).

## Authority / key decisions

- **G1 thứ tự theo website**: với mỗi loại, dãy mã mong đợi = `check.inventory` (mã website có), sắp theo (bộ, tập, clip). Mỗi mã chiếm một khung theo thứ tự đó, nối sau khung của mã liền trước đã có lịch.
- **G2 giữ chỗ cho mã thiếu**: mã nằm **giữa** hai mã đã có trên kênh (lỗ hổng, cùng định nghĩa `missing` của `check.compare`) và chưa có video → nhận khung "giữ chỗ" trong kế hoạch (không gọi YouTube), các mã sau nối tiếp sau khung đó. Mã ở cuối dãy chưa upload (sau mã lớn nhất trên kênh) → không giữ chỗ.
- **G3 lấp chỗ**: video mới của mã đã có lịch liền trước và liền sau → nhận khung trống sớm nhất **sau** khung của mã liền trước và **trước** khung của mã liền sau (khung không trùng với video nào đã có lịch cùng loại). Không còn khung trống giữa hai mốc đó → đặt khung trống sớm nhất sau mã liền trước và ghi cảnh báo "lệch thứ tự" trong bảng.
- **G4 bản trùng**: mã có ≥ 2 bản nháp riêng tư chưa lịch, hoặc 1 bản nháp trong khi mã đã có bản công khai / có lịch → không lên lịch bản nào trong số nháp đó; bảng ghi "trùng — xóa bớt rồi chạy lại" + id các bản. (Thay quy tắc cũ "bản upload sớm nhất được lên lịch".)
- **G5 không đổi lịch cũ**: video đã có `publishAt` / công khai giữ nguyên; journal, `--limit`, `--only`, thêm playlist, `selfDeclaredMadeForKids` như PUB3 / PUB3.1.

## Implementation approach

- `schedule.plan(videos, now, expected=None)`: `expected` = tập mã website theo loại; `None` → hành vi cũ (giữ test cũ PASS).
- Lấp chỗ: dựng danh sách khung đã dùng cùng loại; khung trống = khung hợp lệ theo `SLOTS[kind]` không bị chiếm.
- `__main__` lệnh `schedule --playlist`: tính `check.inventory(cfg, pid)` và truyền vào.

## Phải giữ nguyên

- Khung giờ G1 PUB3, journal, bỏ qua video công khai / có lịch, thêm playlist, hạn mức (không thêm lời gọi API).
- Test cũ PASS không sửa, trừ test khẳng định quy tắc trùng cũ (ghi rõ trong Result nếu đổi).

## Code bị thay / xóa

- Quy tắc trùng trong `plan` ("bản upload sớm nhất trong các nháp được lên lịch") → G4.

## Acceptance Criteria

1. G2: thiếu T30_KT06 giữa T30_KT05 và T31_KT01 → T31_KT01 nhận khung sau khung giữ chỗ; mã cuối chưa upload không giữ chỗ.
2. G3: upload T30_KT06 sau đó → nhận đúng khung giữ chỗ; hết khung giữa hai mốc → khung sớm nhất sau mã trước + cảnh báo "lệch thứ tự".
3. G4: 2 nháp cùng mã, hoặc nháp + bản đã công khai / có lịch → không bản nháp nào được lên lịch, bảng ghi trùng.
4. G5 + test cũ PASS; `expected=None` giữ hành vi cũ.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_publish_schedule_gaps.py tests/test_publish_schedule.py tests/test_publish_check.py` (IMPLEMENTER).
- Full suite `-n auto` (ORCHESTRATOR).
- Dry-run thật 1 kênh (CƯT: thiếu T30_KT06–07), gửi bảng cho HUMAN LEAD trước khi `--apply`.

## Manual test checklist (Tech Lead)

- [ ] HUMAN LEAD xem bảng dry-run CƯT: chỗ giữ cho mã thiếu đúng, bản trùng không lên lịch.

## Result

(chưa có)
