# Task: CP8.23 — Ngưỡng im lặng chia khúc tự chọn theo từng tập

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2 (đổi luật chia khúc A6 của CP4 — ảnh hưởng mọi bộ kinh)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `61923a6` (`main`) / `feature/cp8.23-adaptive-boundary` (worktree `../youtube-auto-short-adaptb`)
- Human Lead approval: APPROVED 2026-10-04 ("Ok đồng ý hết" — đề xuất ORCHESTRATOR cùng ngày: ngưỡng im lặng tự chọn theo giọng giảng của tập, bộ khác không đổi; phạm vi ghi dưới đây)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Bối cảnh (đo 2026-10-04, ORCHESTRATOR)

Địa Tạng tập 2 (`rBvztHKbNe4`) ra 1 Short + 1 khai thị; tập 1 (`9NQFsvecC04`) cũng 1 + 1. Nguyên nhân: ranh giới khúc (A6, `docs/tasks/CP4-analysis.md`) chỉ ở khoảng lặng ≥ `min_boundary_silence = 3.0` s; thầy giảng Địa Tạng ngừng 2–2,5 s nên cả tập chỉ 9–11 khúc (khúc dài nhất 15–17 phút), không ghép được đoạn 30–180 s.

Mô phỏng `analyze()` trên dữ liệu thật (không ghi `work/`):

| Tập | 3,0 s | 2,5 s | 2,0 s | 1,5 s |
|---|---|---|---|---|
| `rBvztHKbNe4` (Địa Tạng 2) | 11 khúc / 3 ứng viên / 1 trong 60–90 s / khúc dài nhất 952 s | 37 / 76 / 13 / 491 s | 79 / 328 / 55 / 333 s | 170 / 1511 / 298 / 130 s |
| `9NQFsvecC04` (Địa Tạng 1) | 9 / 5 / 2 / 1019 s | 37 / 70 / 10 / 325 s | 82 / 326 / 61 / 234 s | 153 / 1141 / 211 / 129 s |
| `Bpbfep2Scrw` (bộ thường) | 160 / 382 / 107 / 116 s | 194 / 542 / 151 / 116 s | 233 / 686 / 196 / 84 s | 302 / 1097 / 314 / 84 s |

Phân bố khoảng lặng (`silences.json`) ≥ 3 s: Địa Tạng 14–15, bộ thường 152.

## Goal

Mỗi tập tự chọn ngưỡng ranh giới khúc theo giọng giảng: tập đã chia tốt ở 3,0 s **giữ nguyên byte-for-byte**; tập ngừng ngắn (Địa Tạng) hạ ngưỡng theo bậc tới khi chia đủ mịn, có sàn. Short và khai thị đều hưởng.

## Scope

- In scope:
  - **B1 Luật thích nghi.** Bậc ngưỡng thử theo thứ tự `min_boundary_silence` (3,0) → … → sàn mới (`min_boundary_silence_floor`, mặc định đề xuất 1,5 s; bước 0,5 s). Dừng ở bậc đầu tiên thỏa tiêu chí "đủ mịn". Tiêu chí mặc định đề xuất: phần thời lượng nội dung nằm trong khúc dài hơn `max_duration` ≤ 10 %. IMPLEMENTER đo tiêu chí trên các tập có sẵn trong `work/` (≥ 10 tập bộ thường + 2 tập Địa Tạng + khai thị) và có thể chỉnh ngưỡng / bậc trong khuôn này; ghi số đo vào Result.
  - **B2 Ghi lại.** `candidates.json` `params.min_boundary_silence` = ngưỡng đã chọn (`validate()` và selection dùng giá trị này); thêm trường cho biết ngưỡng gốc / có thích nghi để log + UI chẩn đoán đọc được.
  - **B3 Không đổi tập cũ.** Tập mà bậc đầu (3,0 s) đã thỏa: `candidates.json` giống hệt trước (không làm analysis / selection stale). Tập bị đổi chỉ khi chạy lại analysis.
  - **B4 Khai thị** (`.kt`, `max_duration` 420 s): cùng luật theo `max_duration` của nó.
  - Config: khóa mới trong `[analysis]` (và phần khai thị nếu có), `config.example.toml`.
- Out of scope: đổi prompt / selection / AI; đổi `max_pause`, `hard_break_silence`; đổi điểm cắt theo câu (CP8.20 đã quyết không đổi); chạy lại hàng loạt các tập đã render.

## Authority / key decisions

- `docs/tasks/CP4-analysis.md` (A6, A7, A10), `docs/tasks/CP8.9-khai-thi.md` (A3.1), `docs/decisions/CP8.20-doc-cut-title-report.md` (không đổi điểm cắt).
- K1: thay đổi luật chia khúc là decision của task này (S2), HUMAN LEAD duyệt 2026-10-04.
- K2: không thêm dependency.

## Implementation approach

- Logic thuần trong `analysis/candidates.py` / `analysis/stage.py`: thử bậc ngưỡng với `find_cut_points` + `build_units` (rẻ, không gọi ffmpeg lại); chọn bậc; phần còn lại giữ nguyên.
- Giữ thứ tự khóa `PARAM_KEYS` / hash để B3 đúng; trường mới chỉ xuất hiện khi ngưỡng khác gốc nếu cần để giữ byte-for-byte.

## Acceptance Criteria

1. Tập bộ thường có trong `work/` (≥ 10 tập, gồm `Bpbfep2Scrw`): `candidates.json` tạo lại giống hệt bản hiện có (byte-for-byte hoặc sha256 bằng nhau).
2. `rBvztHKbNe4`, `9NQFsvecC04` (+ `.kt`): ngưỡng chọn < 3,0 s, số ứng viên trong 60–90 s ≥ 30 mỗi tập Short; khai thị ≥ 5 ứng viên trong khoảng.
3. `validate()` PASS với ngưỡng đã chọn; ranh giới vẫn là khoảng lặng thẳng hàng đầu segment (A6).
4. Sàn không bị vượt: tập không thỏa tiêu chí ở sàn dùng sàn và log rõ.
5. Test đơn vị cho bậc thích nghi (dữ liệu tổng hợp: lặng dài → không đổi; lặng ngắn → hạ bậc; không đủ ngay cả ở sàn → sàn).
6. Thử thật (bản sao dữ liệu, Ollama thật, không đụng `work/` chính): chạy analysis + selection cho Địa Tạng tập 1, 2 (Short + khai thị); ghi số Short / khai thị được chọn và vài tiêu đề + mốc thời gian vào Result để HUMAN LEAD nghe thử.

## Required verification

- Lệnh chuẩn `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 3, 5.
- Script đo (scratch, không commit hoặc commit dưới `tools/` nếu hữu ích) so `candidates.json` cũ / mới — AC 1, 2, 4.
- Thử thật AC 6.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Manual test sau automated verification là điểm danh:

- [ ] Nghe thử vài Short / khai thị Địa Tạng từ bản thử AC 6: đầu / cuối đoạn có cụt câu không.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
