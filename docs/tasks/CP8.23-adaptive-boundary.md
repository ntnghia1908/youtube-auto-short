# Task: CP8.23 — Ngưỡng im lặng chia khúc tự chọn theo từng tập

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
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

- Main changes: `analysis/candidates.py` (`boundary_ladder`, `coarse_fraction`, `choose_boundary`: ladder 3.0 -> 2.5 -> 2.0 -> floor 1.5, first step with <= 10 % of unit time in units longer than `max_duration`, else the floor); `analysis/stage.py` (`analyze` uses it, `params.min_boundary_silence` = chosen value, `params.min_boundary_silence_base` = 3.0 only when adapted, log line "adaptive boundary silence a -> b"; `used_config` omits `min_boundary_silence_floor` while default so config hashes / existing episodes do not go stale); `config.py` + `config.example.toml` (`[analysis] min_boundary_silence_floor`, default 1.5; floor >= `min_boundary_silence` disables adaptation); khai thị uses the same code with its own `max_duration`. `tools/measure_adaptive_boundary.py` (read-only measurement). Tests pin the pre-CP8.23 rules where they assert fixed analysis output (`tests/conftest.py` cfg fixture, `selection_helpers.real_docs`, `test_analysis_candidates.CFG` with floor 3.0).
- Measurement (88 episodes in `work/`, regenerated `candidates.json` vs stored, same shots/silences, criterion = share of unit time in units > `max_duration` <= 10 %): 73 of 88 have fraction 0 at 3.0 s. Natural gap: 5 episodes at 0.07-0.09 (kept at 3.0), next 0.15 / 0.17 / 0.23 -> 10 % separates them. 76 of 88 regenerate identical to stored (AC1; includes `Bpbfep2Scrw` and all other Shorts not listed below; the 2 non-identical at 3.0 are `7w4nSj3PguI.kt` and `W2d-xS4ttTw.kt`, stale since before CP8.9 A3 - not caused by this task). 12 differ: 

| Episode | frac @3 / 2.5 / 2.0 / 1.5 | chosen | candidates (old -> new) | in 60-90 s (old -> new) |
|---|---|---|---|---|
| `rBvztHKbNe4` | .92 / .45 / .10 / 0 | 1.5 | 3 -> 1511 | 1 -> 298 |
| `9NQFsvecC04` | .90 / .25 / .07 / 0 | 2.0 | 5 -> 326 | 2 -> 61 |
| `yZai50V4p44` | .76 / .37 / .06 / 0 | 2.0 | 12 -> 456 | 1 -> 92 |
| `2mVA5If4M3w` | .47 / .22 / .15 / 0 | 1.5 | 100 -> 566 | 25 -> 119 |
| `sMO7wrxLTQ4` | .23 / .09 / 0 / 0 | 2.5 | 201 -> 477 | 33 -> 78 |
| `7w4nSj3PguI` | .17 / .10 / .07 / 0 | 2.5 | 518 -> 877 | 113 -> 187 |
| `1OoN3Otnr9w` | .15 / 0 / 0 / 0 | 2.5 | 435 -> 977 | 90 -> 194 |
| `rBvztHKbNe4.kt` | .64 / .15 / 0 / 0 | 2.0 | 7 -> 348 | - |
| `9NQFsvecC04.kt` | .82 / 0 / 0 / 0 | 2.5 | 3 -> 64 | - |
| `yZai50V4p44.kt` | .29 / .12 / 0 / 0 | 2.0 | 14 -> 474 | - |

  (the other two differing rows are the stale `.kt` above, unchanged threshold). Floor 1.5 reaches fraction 0 on every episode, so the floor is never exceeded in the data.
- Tests: `python -m pytest -q -n auto` 1414 passed, 1 skipped; `node scripts/framework-check.mjs` PASS. New unit tests (AC5): ladder values, long silences -> unchanged and no extra params key, short silences -> lower step, never fine -> floor and floor never crossed, floor = base disables, default floor not in `used_config`. `validate()` runs inside `analyze` with the chosen threshold (AC3).
- AC6 real run (copy in `~/.cache/auto-short-cp823-test/`, config with `[enhance] enabled = false`; real Ollama qwen3:30b; no render; log `run.log`). Titles + `source_start`-`source_end` (s):
  - `rBvztHKbNe4` (Short, threshold 1.5): 8 clips. k01 616.1-686.6 "Tâm như mặt đất - Học theo Địa Tạng Bồ Tát"; k02 725.8-834.3 "Tâm địa bình đẳng - Không phân biệt yêu ghét"; k03 1177.4-1212.3 "Danh khả danh phi thường danh"; k04 1354.3-1449.5 "Bí tạng trong tâm tánh"; k05 1588.6-1697.0 "Hiếu kính mở kho báo tự tánh".
  - `9NQFsvecC04` (Short, 2.0): 6 clips. k01 1462.1-1533.0 "Tâm địa và mục tiêu tu tập"; k02 1721.4-1809.6 "Tự tánh bị chướng ngại"; k03 2144.8-2224.0 "Niệm Phật là pháp môn tối thượng"; k04 2518.0-2584.1 "Sai lầm về Bổ nguyện niệm Phật"; k05 3231.0-3344.4 "Sự chấp nhận của Ấn Tổ và thành công bản dịch".
  - `rBvztHKbNe4.kt` (khai thị 4-7 min, 2.0): 7 clips. k01 48.1-383.1 "Pháp giới U Minh trong Kinh Địa Tạng"; k02 725.8-1174.4 "Sở tri chướng và cách tránh"; k03 1354.3-1648.4 "Khó ở chỗ nào"; k04 1789.9-2139.4 "Tâm địa và bốn bồ tát"; k05 2318.9-2608.3 "Khái niệm không chấp trước".
  - `9NQFsvecC04.kt` (khai thị, 2.5): 5 clips. k01 12.5-365.8 "Lý do giảng Kinh Địa Tạng làm nền tảng"; k02 1202.1-1499.7 "Giải thích tên Kinh Địa Tạng Bổ Nguyện"; k03 2467.1-2768.2 "Pháp môn niệm Phật và bản dịch kinh"; k04 2770.2-3082.9; k05 3084.9-3365.4.
  - Before: 1 Short + 1 khai thị per episode. Titles were not generated (titling not run).
- Review: pending.
- Important findings / decisions: criterion 10 % and floor 1.5 / step 0.5 kept as the contract's defaults (data shows a natural gap between 0.09 and 0.15). Ladder step and 10 % are module constants (not config). A floor >= `min_boundary_silence` is accepted (adaptation off) instead of a config error so existing configs (e.g. `min_boundary_silence = 1.0`) keep working. The contract's metadata line `Change class` was reduced to `S2` (framework-check rejected the trailing text). Episodes changed only when analysis is re-run with `--force` (config hash unchanged, so nothing goes stale).
- Known limitations: the criterion looks only at unit length, not at clip quality; manual listening checklist still pending (HUMAN LEAD). Selection per unit count may produce long khai thị windows at low thresholds (more candidates, e.g. 1511 for Short).
- PR: none (not pushed).
