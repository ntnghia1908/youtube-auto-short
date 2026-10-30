# Task: FIX-hdi1-midframe-check — Kiểm khung HD intro tua vào giữa khung, không vào biên khung

## Status / Approval

- Status: APPROVED
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

(chưa chạy)
