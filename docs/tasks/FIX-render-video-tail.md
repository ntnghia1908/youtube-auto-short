# Task: FIX-render-video-tail — Render lỗi số frame khi clip kéo quá cuối luồng video

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `2e4ba41` (`main`) / `fix/render-video-tail` (worktree `../youtube-auto-short-vtail`)
- Human Lead approval: APPROVED 2026-10-10 ("duyệt FIX-render-video-tail", T1–T4)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm một bước vào filter graph video mà `docs/decisions/CP7-render-contract.md` R6 là canonical owner (kế hoạch + filter graph), kèm một lỗi mới có điều kiện ở render.

## Bối cảnh (bug 2026-10-10)

Bản khai thị Kinh Vô Lượng Thọ tập 14 (`nXAUHQDPQLA.kt`): render `failed` với lỗi `.k06.mp4.part: output check failed: video frames 9976 != 9978`. Chạy lại vẫn lỗi.

- `source.mp4`: luồng video kết thúc ở 3328.392 s (`nb_frames` 99752, `30000/1001`), trong khi luồng audio và format kết thúc ở 3328.421 s.
- Clip k06 (khai thị cuối bài) có `source_end` = 3328.421, tức cuối audio. R3/V5 lập kế hoạch frame theo thời gian clip nên cần 9978 frame, nhưng nguồn chỉ còn hình cho 9976 frame. Kiểm tra R9 / CP8.1 V5 (số frame chính xác) báo lỗi. Đây là lỗi deterministic.
- Quét 2026-10-10 các tập có `source.mp4` trong `work/`: chỉ clip này có điểm cuối vượt cuối luồng video.
- Gỡ tạm (S0, 2026-10-10): điểm cắt tay k06 kết thúc ở 3328.221 s (`review.json` `cuts`; −0.2 s, chỉ bỏ khoảng lặng 3327.95–3328.42).

## Goal

Clip có điểm cuối vượt cuối luồng video một khoảng nhỏ vẫn render thành công, đúng số frame kế hoạch: frame cuối của nguồn được lặp lại cho đủ, audio giữ nguyên. Nếu luồng video thiếu nhiều hơn giới hạn thì render báo lỗi rõ nguyên nhân thay vì lỗi đếm frame.

## Decisions (đề xuất, chờ HUMAN LEAD)

- **T1. Bù đuôi:** render đọc thời điểm kết thúc luồng video của file nguồn được dùng để encode (`start_time + duration` của luồng video; nguồn HD / enhance nếu render dùng nguồn đó). Gọi `m` là số frame kế hoạch nằm sau cuối luồng video. Nếu `0 < m ≤ ceil(0.1 s × fps)` thì lặp frame cuối `m` lần (`tpad=stop_mode=clone`) để đủ đúng tổng `n_k` kế hoạch.
- **T2. Quá giới hạn:** nếu `m` vượt giới hạn T1 thì Short đó lỗi với thông báo `video stream ends at X s, before the clip end Y s`. Không encode, không đi tới bước kiểm tra frame.
- **T3. Không đổi khi không cần:** khi `m = 0` (mọi Short hiện có trừ trường hợp trên) thì filter graph giữ nguyên từng ký tự. `RENDER_PLAN_VERSION` và `render_key` giữ nguyên; không Short nào bị render lại.
- **T4. R9 / V5 giữ nguyên:** vẫn kiểm số frame chính xác và dung sai thời lượng 0.1 s. Không nới dung sai.

## Scope

- In scope:
  - `render/plan.py`: thêm tham số tùy chọn số frame cần lặp ở cuối, áp cho cả hai nhánh `_video_cut` và `_video_dissolve`, trước `pad`.
  - `render/stage.py`: tính `m` từ probe nguồn, áp T1/T2.
  - Cập nhật CP7 R6 (bước bù đuôi, giới hạn) và R9 (lỗi T2), kèm dòng sửa đổi có ngày.
  - Test: unit test cho phép tính `m` và graph (m = 0 thì graph không đổi; m = 2 thì có `tpad` clone 2; m vượt giới hạn thì lỗi T2). Test tích hợp với nguồn ffmpeg nhỏ có audio dài hơn video vài frame, clip tới cuối file, render qua `verify_output` đúng số frame.
- Out of scope:
  - Đổi selection / cut (C4) để không chọn điểm cuối vượt luồng video.
  - Bản dọc cả tập (CP8.27) và enhance (CP13): chỉ sửa nếu cùng hàm; nếu không thì ghi thành limitation.
  - Bỏ điểm cắt tạm của k06 (HUMAN LEAD tự quyết sau merge, có thể bấm "Về như AI chọn").

## Authority / key decisions

- `docs/decisions/CP7-render-contract.md` R3, R6, R9; CP8.1 V5; CP8.2 T5 (`render_key`).
- T1–T4 ở trên.

## Implementation approach

- Probe luồng video nguồn đã có ở render (chọn fps, `probe_media`); dùng lại, không thêm lần gọi ffprobe nếu tránh được.
- Hàm thuần tính `m` từ kế hoạch frame (`frame_plan`, chỉ số grid của frame cuối) và thời điểm cuối luồng video.

## Acceptance Criteria

1. Nguồn có video ngắn hơn audio ≤ 0.1 s, clip tới cuối audio: Short render `done`, `nb_frames` = kế hoạch, thời lượng video / audio trong 0.1 s, frame cuối được lặp.
2. Thiếu > 0.1 s: Short lỗi với thông báo T2, không có file `.part` sót lại.
3. Short không chạm cuối luồng video: filter graph giống hệt trước khi sửa, `render_key` không đổi (test so chuỗi graph và key trên fixture có sẵn).
4. Decision CP7 R6 / R9 đã cập nhật (dòng sửa đổi có ngày).
5. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH = worktree `src`): AC 1–3, 5.
- `node scripts/framework-check.mjs`: AC 4.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API contract. Điểm danh trên 8080 (ghim commit nhánh): bản khai thị tập 14 `nXAUHQDPQLA.kt`, bấm "Về như AI chọn" cho k06 (điểm cuối 3328.421 s), render lại → `done`; xem đuôi Short không giật / đen.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
