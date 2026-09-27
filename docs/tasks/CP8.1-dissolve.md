# Task: CP8.1 — Video Dissolve at Silence Cuts

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `3aa86d9` (main) / `feature/cp8.1-dissolve` (worktree riêng, song song CP8 — tập file không giao nhau)
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; V1–V6; P1 giữ schema v1 additive; P2 bật mặc định 0.15 s)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì sửa decision record đã ACCEPTED `docs/decisions/CP7-render-contract.md` (R6 "không fade/crossfade ở điểm nối", § Chuyển cảnh "để CP10") và thêm key `[render]` + trường `render_manifest.json`. Lựa chọn dissolve 0.15 s đã do HUMAN LEAD chốt 2026-09-27 (sau xem mẫu vòng 2); re-plan cùng ngày kéo từ CP10 lên CP8.1 (`AUTO_SHORT_CHECKPOINT_PLAN.md`). Không thêm dependency.

## Goal

Ở mỗi điểm nối do rút khoảng lặng (giữa hai `segments` liên tiếp của một clip), hình chuyển bằng dissolve ≈ 0.15 s thay cho cắt thẳng; audio vẫn cắt thẳng; thời lượng, số frame, audio của mỗi Short giữ nguyên như bản CP7.

## Scope

- In scope:
  - `src/auto_short/render/plan.py`: kế hoạch dissolve theo frame (V2) + filter graph có `xfade`; `stage.py`: ghi trường mới vào `render_manifest.json`, validation (V5).
  - Config `[render] dissolve` (V1) + `config.example.toml`.
  - Tests: logic kế hoạch dissolve (kẹp, gap nhỏ, 1 segment, không kéo ra ngoài clip), cấu trúc filter graph, tích hợp lavfi (≥ 3 segment) kiểm frame count/thời lượng, và `dissolve = 0` cho đúng filter graph CP7.
  - Render lại thật `rbjfCfFq3Dk` (13 Short), đo thời gian; gửi HUMAN LEAD 2 Short có nhiều điểm nối để xem.
  - Docs: `docs/decisions/CP7-render-contract.md` (R6, § Chuyển cảnh: sửa đổi CP8.1, schema), `AUTO_SHORT_CHECKPOINT_PLAN.md` CP10 (bỏ mục dissolve nếu có pointer), contract Result.
- Out of scope:
  - Fade/crossfade audio (HUMAN LEAD: không fade audio); kiểu chuyển cảnh khác (zoom, wipe); dissolve ở đầu/cuối Short.
  - Cache render từng Short (CP8.2); CLI `run`/pipeline (CP8); README (CP8 đang sửa — tránh xung đột; chỉ thêm một dòng nếu cần sau merge).

## Authority / key decisions

- `docs/decisions/CP7-render-contract.md` R3 (`segments`), R6 (render, encode), R9 (validation), R11 (schema), § Chuyển cảnh (cách kéo dài vào khoảng lặng bị trim, `xfade=fade`, kẹp khi trim ngắn — đã thử trên `k04`, script scratch CP7).
- Quyết định (DECIDE cùng APPROVE TASK):
  - **V1 Config:** `[render] dissolve = 0.15` (giây, mặc định; `0` = cắt thẳng như CP7). Vào `config_hash` → đổi giá trị render lại mọi Short.
  - **V2 Kế hoạch (theo frame, deterministic):** `e = round(dissolve × fps / 2)` frame mỗi phía (0.15 s @ 29.97 → e = 2, dissolve D = 4 frame). Với điểm nối j: `gap` = số frame lưới bị trim giữa segment j và j+1; `e_j = min(e, gap // 2)`; segment j kéo dài `e_j` frame về sau, segment j+1 kéo dài `e_j` frame về trước (lấy từ phần khoảng lặng bị trim, không bao giờ ra ngoài `[source_start, source_end]`); hai segment chồng `D_j = 2 e_j` frame, blend `xfade=transition=fade`. `D_j = 0` → nối thẳng (`concat`). Tổng frame video = tổng frame CP7 (frame_plan), audio không đổi.
  - **V3 Filter graph:** nhánh video tách theo segment (`split` + `select` từng segment đã kéo dài) rồi `xfade` nối dần; các bước crop/scale/format áp trên từng nhánh trước blend, `pad` + overlay panel sau blend (như script thử CP7). Implement được chọn cách tương đương nếu nhanh hơn, miễn đúng V2.
  - **V4 Schema `render_manifest.json`:** thêm (additive, giữ `schema_version: 1`) `encode.dissolve` (giây cấu hình) và mỗi `shorts[]` thêm `dissolves`: `[{"at": <giây trên timeline Short tại điểm nối>, "frames": D_j}]` (P1).
  - **V5 Validation:** R9 giữ nguyên (thời lượng video/audio lệch ≤ 0.1 s); thêm: số frame video (`ffprobe -count_frames` hoặc `nb_frames`) = tổng frame kế hoạch.
  - **V6 Hiệu năng:** đo thời gian render 13 Short so với CP7 (≈ 5 min). Chậm hơn > 2× → báo ORCHESTRATOR trước READY (không tự đổi thiết kế).
- Đề xuất cần HUMAN LEAD chốt:
  - **P1 Schema:** thêm trường additive, giữ v1 (đề xuất). Khác: nâng `schema_version: 2`.
  - **P2 Mặc định:** dissolve bật mặc định 0.15 s (đề xuất). Khác: mặc định 0, bật bằng config.

## Implementation approach

- Tái dùng `frame_plan` + kiểm chứng: chạy `dissolve = 0` phải cho filter graph y hệt CP7 (test so chuỗi).
- Kiểm chứng mạnh: với `rbjfCfFq3Dk` k04, so `framemd5` của video trước khi encode giữa `dissolve = 0` và `0.15`: mọi frame ngoài các cửa sổ dissolve phải trùng hash; số frame trùng.
- Tham khảo script thử (scratch CP7, không vào repo): mở rộng `select` mỗi segment `[first − e_in, first + n + e_out − 1]`, `xfade` offset = (độ dài tích lũy − D)/fps.

## Acceptance Criteria

1. `[render] dissolve = 0` → filter graph và mp4 giống hệt CP7 (sha256 file trùng với output hiện có của ít nhất 1 clip).
2. `dissolve = 0.15`: mỗi điểm nối có gap ≥ 4 frame được blend 4 frame; gap nhỏ hơn thì kẹp (`D_j` = 2⌊gap/2⌋, có thể 0); không kéo ra ngoài đoạn clip; test đơn vị bao phủ các trường hợp.
3. Render thật `rbjfCfFq3Dk`: 13 Short, R9 + V5 PASS; framemd5 k04: frame ngoài cửa sổ dissolve trùng bản `dissolve = 0`, tổng frame trùng; audio (PCM) trùng bản CP7.
4. `render_manifest.json` có `encode.dissolve` và `shorts[].dissolves` đúng V4.
5. Thời gian render đo và ghi Result (V6).
6. Mọi test hiện có PASS; `node scripts/framework-check.mjs` PASS; decision record CP7 cập nhật.

## Required verification

- `pytest -q` — AC1 (graph), AC2, AC6.
- `auto-short render rbjfCfFq3Dk` (config mặc định mới) + `ffprobe` + đo thời gian — AC3, AC4, AC5.
- Script so sánh framemd5 / PCM k04 (scratch) — AC3; render `dissolve = 0` một clip, so sha256 với output CP7 lưu trước — AC1.
- `node scripts/framework-check.mjs` — AC6.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model, public API. Manual test là điểm danh.

- [ ] Xem 2 Short nhiều điểm nối (vd `k04`): chỗ rút lặng mềm hơn, không thấy bóng chồng rõ.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
