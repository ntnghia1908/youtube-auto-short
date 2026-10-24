# Task: VIS1 — Hình ambient cho video ghép chủ đề (Mode B)

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + chạy render thật 30–40 phút
- Implementer: codex — module mới, spec rõ; Sonnet `implementer` nếu quota Codex ≥ ngưỡng
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (chờ G1, G3, G5, G6)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/visual.py`, `src/auto_short/packaging/variant.py` (mới), mở rộng `packaging/record.py`, `web/packaging.py`, `web/static/package.{html,js}`, `tests/test_packaging_visual.py`, `tests/test_web_packaging.py`, contract này
- Dependencies: PKG1 (kho asset, `record.py`, trang đóng gói)
- Base commit / branch: điền khi authorize / `feature/vis1-ambient`
- Human Lead approval: pending
- Implementation authorized: NO

## Goal

Từ một video TC3 đã xuất, HUMAN LEAD chọn một ảnh hoặc loop đã duyệt (hoặc nền tạo sẵn), xem thử 20 giây, rồi dựng bản 16:9 1920×1080 có hình chuyển động chậm suốt 30–40 phút. **Tiếng giảng giữ nguyên bit** so với TC3; bản Original vẫn là mặc định.

## Scope

- In scope:
  - Variant spec `{visual: {mode: "ambient", asset_id | "generated:<preset>", motion, loop_seconds, crossfade}}`; key = hash(spec, sha256 TC3, sha asset, `VISUAL_VERSION`). Output `pkg/<plan>-r<rev>/variant-<key12>.mp4` + `.json` (spec, nguồn TC3, chapters + mô tả chép từ metadata TC3, sha256, duration, kiểm tra).
  - Dựng một clip lặp ngắn rồi lặp: ảnh tĩnh → Ken Burns chậm (zoom ≤ ~6 % mỗi chu kỳ, đi ra rồi về để đầu = cuối); loop video → nối crossfade đầu / cuối. Clip lặp encode một lần (`libx264`, GOP đóng, cùng fps), sau đó ghép bằng `-stream_loop` + `-c:v copy` với `-map` audio TC3 `-c:a copy`, `-t` = thời lượng audio, `+faststart`. Nếu kiểm tra sau ghép fail → fallback encode lại toàn bộ video (preset nhanh), audio vẫn copy.
  - Nền tạo sẵn (license-free, R5): 2–3 preset ffmpeg (gradient ấm chuyển chậm, ánh sáng mềm) để chạy không cần asset ngoài.
  - Xem thử: dựng 20 giây (clip lặp + audio TC3 đoạn đầu) trước khi dựng cả bài.
  - Job `theme_package` (làn render), hủy được, file tạm dọn khi lỗi / hủy; trang đóng gói liệt kê variant, trạng thái, tải, xóa variant.
- Out of scope: cảnh theo chapter (VIS1.1); nhạc (AUD1); AI sinh hình; overlay chữ trên video; ảnh người giảng giả cử động.

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R1–R9, G3, G6.
- Đo / kiểm media tái dùng `render.stage.probe_media`, `theme_render._verify` (cách kiểm), `compilation/probe.py`.

## Implementation approach

- Audio không qua filter nào → kiểm "lời giảng nguyên vẹn" bằng hash gói audio: `ffmpeg -map 0:a -c copy -f streamhash` của TC3 và variant phải bằng nhau (chính xác, mạnh hơn `audio.compare`).
- Kiểm hình: `ffprobe` 1920×1080, SAR 1:1, |duration video − audio| ≤ 1 khung + 1 GOP lặp; `blackdetect` (d=0.1) không có đoạn đen; điểm nối loop: chênh lệch khung cuối / đầu thấp (`ssim` ≥ 0,97 trên clip lặp).
- Dung lượng: CRF clip lặp chọn sao cho 40 phút ≈ ≤ 1 GB; ghi số đo thật vào Result.

## Phải giữ nguyên

- File TC3, route tải TC3, plan TC2; mode Original = file TC3 (không copy, không encode lại).
- Job runner / làn render và thứ tự ưu tiên hiện có (CP8.26, CP8.36).

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Dựng variant ambient từ một TC3 thật 30–40 phút: 1920×1080, SAR 1:1, H.264 + AAC; streamhash audio = TC3.
2. Không có đoạn đen (`blackdetect`), điểm nối loop đạt ngưỡng ssim; xem mắt không thấy giật / chớp.
3. Dựng lại cùng spec dùng file cũ; đổi asset / motion / TC3 → key mới; TC3 đổi → variant cũ `stale`.
4. ffmpeg lỗi / hủy job → không còn file dở trong `pkg/`, file TC3 nguyên sha256.
5. Asset chưa duyệt / thiếu license bị từ chối trước khi chạy ffmpeg.
6. Xem thử 20 giây tạo được và không ghi variant chính thức.
7. Thời gian dựng 40 phút ghi số đo (mục tiêu ≤ 15 phút trên VM nhờ stream copy).

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_visual.py tests/test_web_packaging.py` — AC3–6 (runner giả) + AC1–2 trên TC3 tổng hợp ~20 giây (ffmpeg thật).
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`.
- Chạy thật AC1, AC2, AC7 trên một plan đã xuất (ORCHESTRATOR), gửi HUMAN LEAD đoạn mẫu.

## Manual test checklist (Tech Lead)

Chạm public API (route mới, sau đăng nhập), không chạm security model / database.

- [ ] HUMAN LEAD xem đoạn đầu, giữa, điểm nối loop trên 8080 ghim commit branch.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
