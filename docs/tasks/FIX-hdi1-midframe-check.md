# Task: FIX-hdi1-midframe-check — Kiểm khung HD intro tua vào giữa khung, không vào biên khung

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `medium`, fix nhỏ); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-30 yêu cầu đủ 102 tập Địa Tạng có trang bìa HD ("Bản HD của Kinh Địa Tạng có tổng cộng 102 tập …"); HUMAN LEAD 2026-10-29 "không cần hỏi lại ý tôi" cho việc sửa lỗi trong phạm vi HDI1 đã duyệt
- Parallel group: —
- Owned paths: `src/auto_short/render/hd_intro.py`, `tests/test_hd_intro.py`, contract này
- Dependencies: HDI1 (#183)
- Base commit / branch: `origin/main` `06f7f92` / `fix/hdi1-midframe-check`
- Human Lead approval: APPROVED 2026-10-30 (theo uỷ quyền 2026-10-29)
- Implementation authorized: YES

## Bằng chứng

Địa Tạng tập 85 (`dknZSTJdq-4`, 1440×1080, 30000/1001 fps, timebase 1/30000, 102186 khung) lỗi 2 lần: "HD intro: khung hình sau offset khác bản gốc tại 1704.803 s". Tái hiện trên bản sao mượn từ kho (2026-10-30, `hd_intro.render` → cùng lỗi):

| n | tua | gốc | bản ghép (+3.003 s) | trùng |
|---|---|---|---|---|
| 51093 | `n / fps` = 1704.8031 | 2a778858 | 9709a078 | **không** |
| 51093 | `(n + 0.5) / fps` | 9709a078 | 9709a078 | có |
| 0, 102184 | cả hai cách | — | — | có |

Khung kế bên của bản ghép (k = −2…2) trùng đúng các khung gốc → nội dung concat đúng; `frame_hash` tua `-ss` vào **đúng biên khung** nên sai số dấu phẩy động (`n / fps` + offset) chọn khung trước ở một file và khung sau ở file kia.

## Goal

Bước kiểm khung của HD intro (`verify` và nhánh tách bài giảng từ bản có intro trong `run_intro`) không còn báo sai khi bài giảng đúng.

## Scope

- In scope: tua vào **giữa khung** `(n + 0.5) / fps` ở mọi chỗ so khung bằng `frame_hash` trong `render/hd_intro.py` (`verify` + vòng kiểm trong `run_intro`); test hồi quy NTSC với khung ở mốc mà `n / fps` + offset rơi sai phía.
- Out of scope: KTI1 / VERT2 / compilation (không dùng chỗ này); đổi thuật toán gói / pts; dữ liệu kho.

## Phải giữ nguyên

- Khung đầu / giữa / cuối vẫn được so (cùng chỉ số n); lỗi thật (khung khác) vẫn bị bắt; file kho / sidecar `hd_intro.json` không đổi định dạng.

## Code bị thay / xóa

- 2 dòng `seconds = float(n / spec["fps"])` → tính giữa khung (helper chung nếu dùng 2 nơi).

## Acceptance Criteria

1. Video NTSC (30000/1001) mà `n / fps` tua sai phía → `verify` PASS; khung thật khác (thay 1 khung ở giữa) → vẫn `RenderError`.
2. Test HDI1 hiện có PASS không sửa assertion.
3. `git diff --check`, `node scripts/framework-check.mjs` PASS; full suite (ORCHESTRATOR).

## Required verification

- `timeout 290s env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_hd_intro.py`
- ORCHESTRATOR: full suite `-n auto`; chạy lại `render` trên bản sao tập 85 → PASS; sau merge + restart 8080: xếp lại HD intro tập 85.

## Result

IMPLEMENTER READY — 2026-10-30; chờ ORCHESTRATOR review và verification được giao riêng bên dưới.

- `src/auto_short/render/hd_intro.py`: thêm `frame_midpoint(n, fps)`, tính `(n + 1/2) / fps` bằng `Fraction` trước khi đổi sang float; dùng chung trong `verify` và vòng kiểm tách bài giảng của `run_intro`. Giữ nguyên chỉ số khung đầu / giữa / cuối, so hash và định dạng sidecar.
- `tests/test_hd_intro.py`: thêm 2 hàm test (3 ca), giữ nguyên toàn bộ assertion cũ; tái dùng `media`, `seed`, `MemoryStore`, fixture `config` / `image`.
- Contract này: cập nhật status và Result; không commit / push / PR, không gọi agent khác hoặc mạng thật.

| AC | Test / bằng chứng | Kết quả IMPLEMENTER |
|---|---|---|
| AC1 | `test_verify_ntsc_midpoint_seeks_and_changed_frame[False/True]`: fps 30000/1001, 102186 khung, n=51093; runner giả mô phỏng hash khác phía khi tua đúng biên, xác nhận toàn bộ giây `-ss` bằng giữa khung + offset tương ứng. Nội dung đúng PASS; hash khung giữa bị thay vẫn `RenderError`. | PASS (runner giả) |
| AC1, vòng `run_intro` | `test_ntsc_rebuild_seeks_midpoints`: media NTSC thật từ helper `media`, ghép rồi rebuild; runner ghi `-ss` và chạy ffmpeg thật, xác nhận cả 6 lần tua của vòng tách và 6 lần tua của `verify`. | PASS |
| AC2 | Toàn bộ `tests/test_hd_intro.py`, gồm test cũ không sửa assertion. | 26 passed |
| AC3 | `git diff --check`; `node scripts/framework-check.mjs`. Full suite thuộc ORCHESTRATOR. | Hai checker PASS; full suite chưa chạy |

Giới hạn AC1: không có bản sao tập 85 trong input của task; media tổng hợp ngắn không bảo đảm tái hiện cùng sai số chọn phía tại 1704.8031 s của hai timeline thực tế. Dùng phương án runner giả được ORCHESTRATOR cho phép trong prompt để mô phỏng lỗi biên và khung giữa có hash khác; đây không phải bằng chứng đã sửa byte của một khung trong media thật. Media thật bổ sung chứng minh ghép / tách và thời điểm tua, không tuyên bố tái hiện lỗi biên của tập 85.

Lệnh đã chạy trong worktree hiện tại:

```text
timeout 290s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/hdi1-hd-intro/.claude/worktrees/fix-hdi1-midframe/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_hd_intro.py
=> exit 0; 26 passed in 31.49s
git diff --check
=> exit 0; không có lỗi whitespace
node scripts/framework-check.mjs
=> exit 0; PASS framework structure và các kiểm tra contract / authority / adapter
```

Dòng thêm / xóa (`git diff --numstat`): ứng dụng **+7 / −2**; test **+60 / −0**. Helper mới: `frame_midpoint`; đã tìm bằng `rg -n 'midpoint|mid_frame|frame_time|0\.5.*fps|frame_hash' src/auto_short/render tests/test_hd_intro.py`, không có helper giữa khung tương đương để tái dùng.

Còn giao ORCHESTRATOR: full suite `-n auto`, render lại bản sao tập 85; sau merge / restart mới xếp lại HD intro tập 85. Chưa chạy hoặc claim PASS các bước này trong phiên IMPLEMENTER.

### ORCHESTRATOR (2026-10-30)

- Review diff: `frame_midpoint` dùng cho `verify` và vòng tách của `run_intro`; inventory ⊆ Owned paths. Codex 47.618 tokens, 1 vòng.
- Chạy thật trên bản sao HD tập 85 mượn từ kho (2.177.529.013 byte): code cũ `render` → lỗi "khác bản gốc tại 1704.803 s"; code mới → **render OK**. Kho không bị ghi.
- Full suite `-n auto`: **3538 passed, 1 failed, 1 skipped**. Lỗi `tests/test_web_stop_fix.py::test_ac2_orphaned_grandchild_and_children_started_after_the_interrupt` có sẵn trên `origin/main` (chạy riêng bằng `-k` trên main cũng lỗi: tiến trình cháu chưa thoát kịp khi máy đang chạy job 8080); chạy cả file trên nhánh này: 9 passed. Không liên quan `hd_intro`.
- Còn: sau merge + restart 8080 (làn rảnh) → xếp lại HD intro tập 85.
