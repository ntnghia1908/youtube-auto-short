# Task: AUD1 — Nhạc nền tùy chọn cho video ghép chủ đề

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + chạy thật + gửi mẫu nghe
- Implementer: codex — mở rộng module có spec rõ; Sonnet `implementer` nếu quota Codex ≥ ngưỡng
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (chờ G1, G3, G5)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/music.py` (mới), mở rộng `packaging/variant.py`, `web/packaging.py`, `web/static/package.{html,js}`, `tests/test_packaging_music.py`, `tests/test_web_packaging.py`, contract này
- Dependencies: VIS1 (`variant.py`); kho asset PKG1 (`kind: music`)
- Base commit / branch: điền khi authorize / `feature/aud1-music`
- Human Lead approval: pending
- Implementation authorized: NO

## Goal

HUMAN LEAD chọn một bản nhạc đã duyệt cho variant (hình Original hoặc ambient), nghe thử 3 đoạn 30 giây, chỉnh mức nhạc, duyệt rồi dựng cả bài. Mặc định "Chỉ giọng giảng"; giọng giảng không bị biến đổi, chỉ cộng thêm nhạc nhỏ phía dưới.

## Scope

- In scope:
  - Variant spec thêm `{music: null | {asset_id, level_lu, fade_in, fade_out, loop_crossfade}}`; `null` = Voice Only (mặc định). Key variant đổi khi bất kỳ trường nào đổi.
  - Mix: giọng TC3 giữ gain 1.0, không nén / chuẩn hóa / limiter; nhạc lặp có `acrossfade` ở điểm nối, `afade` vào / ra, gain đặt sao cho loudness nhạc = loudness giọng (đo `ebur128`) + `level_lu` (mặc định −20 LU, cho phép −30…−12); `amix normalize=0`; AAC 48 kHz stereo theo `[render] audio_bitrate`. Hình: `-c:v copy` từ TC3 (Original) hoặc từ variant VIS1.
  - Kiểm: true peak ≤ −1 dBTP (vượt → lỗi rõ, gợi ý giảm mức nhạc, không tự hạ giọng); tương quan envelope giọng (tái dùng `theme_render/audio.compare` + ngưỡng của nó) giữa mix và TC3 đạt; thời lượng audio = TC3 ± 1 khung AAC; số kênh 2.
  - Xem thử: 3 đoạn 30 giây (đầu / giữa / cuối) xuất `.m4a`, nghe trên trang trước khi dựng cả bài; duyệt mức nhạc ghi vào `package.json`.
- Out of scope: ducking theo tiếng nói (AUD1.1); xử lý / lọc nhiễu giọng; tạo nhạc bằng AI; tải nhạc từ mạng.

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R1–R9, G3.
- `src/auto_short/theme_render/audio.py` (envelope, `compare`) — tái dùng, không sửa.

## Implementation approach

- Một lần encode audio cho cả bài (filtergraph `[1:a]aloop/acrossfade…[m];[0:a][m]amix`), video copy; đo loudness trước bằng `ebur128` trên TC3 + nhạc để tính gain (deterministic, ghi vào metadata).
- Voice Only + hình Original = chính file TC3 (không tạo variant).

## Phải giữ nguyên

- Voice Only luôn chọn được và là mặc định; file TC3 và variant VIS1 không nhạc không bị ghi đè.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Từ cùng TC3 có cả Voice Only và Voice + nhạc; bản nhạc: thời lượng, 2 kênh, true peak ≤ −1 dBTP, nhạc ≈ giọng + `level_lu` (sai số ≤ 1 LU).
2. Tương quan envelope giọng mix vs TC3 đạt ngưỡng `audio.compare`; test cố ý đặt nhạc +0 LU / đảo giọng → bị phát hiện (fail).
3. Điểm nối loop nhạc không có bước nhảy biên độ (RMS cửa sổ 20 ms quanh điểm nối trong ngưỡng).
4. Đổi nhạc / mức / fade → key mới; không đổi → dùng lại file.
5. Mix lỗi / hủy không để file dở, không đụng TC3 / variant khác.
6. Xem thử 3 × 30 giây tạo được, nghe được trên trang.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_music.py tests/test_web_packaging.py` — AC1–6 trên audio tổng hợp (sine / tiếng nói mẫu ngắn trong test).
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`.
- Chạy thật trên một TC3 30–40 phút với nhạc HUMAN LEAD cung cấp; gửi đoạn mẫu ở 2–3 mức để HUMAN LEAD chọn bằng tai.

## Manual test checklist (Tech Lead)

Chạm public API (route mới, sau đăng nhập), không chạm security model / database.

- [ ] HUMAN LEAD nghe thử trên loa và tai nghe điện thoại; chọn mức mặc định.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
