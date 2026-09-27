# Task: CP8.1 — Video Dissolve at Silence Cuts

## Status / Approval

- Status: READY
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

- Main changes: `src/auto_short/render/plan.py` (`dissolve_plan` V2, `dissolves` cho manifest, `_video_dissolve` V3: `split` + `trim` từng segment kéo dài + `xfade=fade`/`concat`, `pad` sau blend; không điểm nối nào blend → graph CP7 nguyên văn), `stage.py` (`encode.dissolve`, `shorts[].dissolves`, V5 `nb_frames` = kế hoạch, validate `dissolves`), `config.py` + `config.example.toml` (`[render] dissolve = 0.15`, 0–1 s, trong `config_hash`); decision record `docs/decisions/CP7-render-contract.md` (R6, R9, R11, § Quyết định khi implement, § Chuyển cảnh: sửa đổi CP8.1).
- Tests: `pytest -q` 353 passed (11 mới: kế hoạch kẹp theo gap/1 segment/gap âm/segment ngắn, `at`, `dissolve = 0` = graph CP7 nguyên văn, cấu trúc graph 4 segment, render lavfi 4 segment (D = 4/2/4): `nb_read_frames` = 190 = kế hoạch, framemd5 trước encode so `dissolve = 0` chỉ khác đúng các frame blend, audio trùng; V5 `verify_output`; config). `node scripts/framework-check.mjs` PASS.
  - AC1: render cả 13 clip với `dissolve = 0` (workspace + output tạm) → 13/13 mp4 sha256 trùng output CP7 (vd `k04` `3daa8138…`); graph `dissolve = 0` so chuỗi với `plan.py` CP7 (`e020d63`) trên 13 clip thật: 13/13 trùng.
  - AC3/AC4: `auto-short render rbjfCfFq3Dk --force` (mặc định 0.15): 13/13 rendered, R9 + V5 PASS trong stage; kiểm độc lập `ffprobe -count_frames`: 1080×1920 h264 yuv420p 30000/1001, AAC 48 kHz 2 kênh, `nb_read_frames` = `nb_frames` = kế hoạch cả 13 clip, lệch thời lượng ≤ 0.017 s; PCM audio (s16le) 13/13 trùng bản CP7; entry manifest trùng CP7 ngoài `sha256` + `dissolves`; `encode.dissolve` 0.15; 157 điểm nối: 143 × D = 4, 7 × D = 2 (gap 2–3 frame), 7 × D = 0 (gap 0–1 frame). `k04` framemd5 trước encode: 1077 frame cả hai bản; 21 frame khác nhau đều trong 7 cửa sổ dissolve (đúng D − 1 frame cuối mỗi cửa sổ), mọi frame ngoài cửa sổ trùng hash, audio trùng. Render lại `k04` hai lần → byte-identical.
  - AC5 (V6): 13 Short 325.0 s wall (`/usr/bin/time`), bản `dissolve = 0` cùng máy cùng lúc 294.0 s (CP7 ghi ≈ 260–300 s) → ≈ 1.1×; đỉnh RSS 2.6 GB (`k03`, cắt thẳng 2.0 GB). Máy đang có tải khác (load 8–15 / 48 core).
- Review: ACCEPTED (ORCHESTRATOR, diff-first; chạy lại `pytest tests/test_render_plan.py tests/test_render_config.py` PASS). Không có blocking finding. Hai điểm lệch được chấp nhận trong boundary: (1) nhánh segment dùng `trim` thay `select` — V3 cho phép cách tương đương; cùng frame (framemd5 k04 trùng), RAM đỉnh 13.7 → 2.6 GB; (2) kẹp thêm `n // 2` và `max(0, …)` ngoài V2 — chỉ tác động segment < 4 frame (không xảy ra ở video test), tránh cửa sổ dissolve chồng nhau; đã ghi R6. Non-blocking: xfade để frame đầu cửa sổ 100 % đoạn trước (D = 4 thực chất blend 3 frame) — giống mẫu HUMAN LEAD đã chọn.
- Important findings / decisions: (1) `select` trong nhánh segment chỉ kết thúc ở EOF input → `concat`/`xfade` giữ frame mọi segment sau trong RAM: `k03` đỉnh RSS 13.7 GB, cả lượt 13 Short 373.7 s; chuyển sang `trim=start_pts/end_pts` (cùng frame: framemd5 `k04` trùng từng frame, packet mã hóa trùng) → 2.6 GB, 325 s. (2) Kẹp thêm ngoài V2: `e_j ≤ n_j // 2, n_{j+1} // 2` (segment < 2e frame, không có ở video test) để cửa sổ không chồng và input `xfade` đủ dài; `e_j ≥ 0` khi làm tròn làm hai segment chạm/chồng 1 frame. (3) `xfade` frame đầu cửa sổ vẫn 100 % segment trước → blend thật D − 1 = 3 frame (3/4, 1/2, 1/4), như mẫu HUMAN LEAD đã xem. (4) `at` = frame đầu segment j+1 / fps (tâm cửa sổ); entry `skipped` → `dissolves: null`, clip 1 segment → `[]`.
- Known limitations: như decision record CP7 § Giới hạn đã biết; dissolve không áp ở đầu/cuối Short (ngoài scope).
- PR:
