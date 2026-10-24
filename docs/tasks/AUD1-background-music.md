# Task: AUD1 — Nhạc nền tùy chọn cho video ghép chủ đề

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + chạy thật + gửi mẫu nghe
- Implementer: codex — mở rộng module có spec rõ; Sonnet `implementer` nếu quota Codex ≥ ngưỡng
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (G1, G3, G5, G6 ACCEPTED)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/music.py` (mới), mở rộng `packaging/variant.py`, `web/packaging.py`, `web/static/package.{html,js}`, `tests/test_packaging_music.py` (mới), `tests/test_packaging_visual.py` (chỉ khi `variant.py` đổi chữ ký), `tests/test_web_packaging.py`, contract này
- Dependencies: VIS1 (`variant.py`, PR #133 chưa merge → branch từ đầu PR #133); kho asset PKG1 (`kind: music`)
- Base commit / branch: `8fed0d9` (đầu `feature/vis1-ambient`, PR #133) / `feature/aud1-music` — rebase lên main sau khi #133 merge
- Human Lead approval: boundary PKG ACCEPTED 2026-10-24
- Implementation authorized: YES

## Goal

HUMAN LEAD chọn một bản nhạc đã duyệt cho variant (hình Original hoặc ambient), nghe thử 3 đoạn 30 giây, chỉnh mức nhạc, duyệt rồi dựng cả bài. Mặc định "Chỉ giọng giảng"; giọng giảng không bị biến đổi, chỉ cộng thêm nhạc nhỏ phía dưới.

## Scope

- In scope:
  - Variant spec thêm `{music: null | {asset_id, level_lu, fade_in, fade_out, loop_crossfade}}`; `null` = Voice Only (mặc định). Key variant đổi khi bất kỳ trường nào đổi.
  - Mix: giọng TC3 giữ gain 1.0, không nén / chuẩn hóa / limiter; nhạc lặp có crossfade ở điểm nối, `afade` vào / ra, gain đặt sao cho loudness nhạc = loudness giọng (đo `ebur128`) + `level_lu` (mặc định −20 LU, cho phép −30…−12); `amix normalize=0`; AAC 48 kHz stereo theo `[render] audio_bitrate`. Hình: `-c:v copy` từ TC3 (Original) hoặc từ variant VIS1.
  - Kiểm: true peak theo ngưỡng ở mục Quyết định (vượt → lỗi rõ, gợi ý giảm mức nhạc, không tự hạ giọng); tương quan envelope giọng (tái dùng `theme_render/audio.compare` + ngưỡng của nó) giữa mix và TC3 đạt; thời lượng audio = TC3 ± 1 khung AAC; số kênh 2.
  - Xem thử: 3 đoạn 30 giây (đầu / giữa / cuối) xuất `.m4a`, nghe trên trang trước khi dựng cả bài.
- Out of scope: ducking theo tiếng nói (AUD1.1); xử lý / lọc nhiễu giọng; tạo nhạc bằng AI; tải nhạc từ mạng; tìm / nạp nhạc vào kho (ORCHESTRATOR đề xuất nguồn theo G3, HUMAN LEAD duyệt, nạp bằng CLI `python -m auto_short.packaging assets add --kind music` có sẵn).

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R1–R9, G3.
- `src/auto_short/theme_render/audio.py` (envelope, `compare`) — tái dùng, không sửa.

## Implementation approach

- Một lần encode audio cho cả bài, video copy; đo loudness trước bằng `ebur128` trên TC3 + nhạc để tính gain (deterministic, ghi vào metadata).
- Voice Only + hình Original = chính file TC3 (không tạo variant).

Quyết định ORCHESTRATOR khi authorize (2026-10-24, trong boundary):

- **Spec**: canonical `{"visual": <visual VIS1> | null, "music": <music>}`; `visual: null` = hình Original (TC3). `music: null` → spec chuẩn hóa về đúng dạng VIS1 `{"visual": …}` để **key variant VIS1 hiện có không đổi**; `{"visual": null, "music": null}` bị từ chối (đó là chính TC3). Music chuẩn hóa: `asset_id` (sha nhạc đã duyệt, `kind: music`), `level_lu` −30…−12 bước 0,5 (mặc định −20), `fade_in` 0–10 s (mặc định 3), `fade_out` 0–15 s (mặc định 5), `loop_crossfade` 0,5–8 s (mặc định 3), làm tròn 0,1; nhạc phải dài ≥ 2 × `loop_crossfade` + 1 s.
- **Key** = hash(spec, sha nhạc, `MUSIC_VERSION`, `audio_bitrate`, sha256 TC3); khi `visual` khác null key cũng phụ thuộc spec visual (nên phụ thuộc key VIS1 tương ứng).
- **Nguồn hình**: `visual: null` → `-c:v copy` từ TC3. `visual` ambient → `-c:v copy` từ file variant VIS1 cùng spec visual + cùng TC3 (bản không nhạc) phải đã dựng và không stale (không bắt buộc đã duyệt); thiếu → lỗi rõ "hãy dựng hình ambient trước". Không encode lại hình.
- **Vòng lặp nhạc**: dựng một lần (trong thư mục tạm) "đơn vị lặp" PCM / FLAC dài `L − loop_crossfade` mà `loop_crossfade` giây cuối là crossfade (equal-power) giữa đuôi bài và đầu bài, rồi `-stream_loop -1` đơn vị đó → điểm nối liền mạch, không có filter `aloop` tràn bộ nhớ. Gain, `afade` vào ở 0, `afade` ra kết thúc đúng tại cuối audio TC3, cắt ở thời lượng audio TC3 (`amix duration=first`, `normalize=0`, giọng là input đầu, gain 1.0). Nhạc mono / sample rate khác → `aformat` 48 kHz stereo trước mix.
- **Loudness**: `voice_lufs` = integrated loudness TC3 (cả bài), `music_lufs` = integrated loudness bản nhạc gốc; `gain_db = voice_lufs + level_lu − music_lufs`; ghi cả ba vào record. Nhạc gần im lặng (`music_lufs` < −60 hoặc không đo được) → lỗi.
- **True peak** (số đo thật: TC3 `bddcede7d89d-r2` có I = −14,1 LUFS, true peak **−0,5 dBTP** — giọng tự nó đã vượt −1 dBTP nên ngưỡng tuyệt đối −1 dBTP sẽ luôn fail mà không được hạ giọng): ngưỡng = `max(−1,0; true_peak_TC3 + 0,5)` dBTP, đo `ebur128=peak=true` trên TC3 và trên mix; vượt → `PackageError` gợi ý giảm `level_lu`. Ghi cả hai số đo + ngưỡng vào record.
- **Kiểm sau mix**: `audio.compare(mix, TC3)` đạt (corr ≥ 0,9, lag ≤ 0,04 s, chênh ≤ 0,1 s); |duration audio mix − TC3| ≤ 1024/48000 s; 2 kênh, 48 kHz, AAC; hình: streamhash video (`-map 0:v -c copy -f streamhash`) bằng của nguồn hình (TC3 hoặc variant VIS1).
- **File / record**: dùng chung tiền tố variant: `variant-<key12>.mp4|json` (listing / xóa / duyệt / tải dùng lại route VIS1). Record music: cùng các trường chung với VIS1 (`schema_version`, `key`, `spec`, `tc3`, `chapters`, `description`, `sha256`, `size`, `duration`, `build_seconds`, `built_at`, `approved_at`) + `music` (asset id, `voice_lufs`, `music_lufs`, `gain_db`, `true_peak`, `true_peak_tc3`, `true_peak_limit`, `corr`, `lag`) + `video_source` (`tc3` hoặc key VIS1 + sha256 file nguồn hình) + `encoding` riêng (`music_version`, `audio_bitrate`); `validate` rẽ nhánh theo spec có `music` hay không, record VIS1 cũ vẫn hợp lệ. Variant music không có `loop_key` → xóa variant music không đụng `loop-*.mp4` của VIS1. Stale nếu TC3 đổi, nhạc hết duyệt / đổi, hoặc (ambient) variant VIS1 nguồn bị xóa / đổi sha.
- **Xem thử**: 3 file `preview-<key12>-{1,2,3}.m4a` (đầu / giữa / cuối, mỗi đoạn 30 s, giữa = tâm bài), audio-only, cùng gain / pha vòng lặp / fade như bản đủ tại vị trí đó; chỉ giữ bộ xem thử mới nhất mỗi plan-rev; không cần dựng hình. Route tải hiện có mở rộng nhận `.m4a` với tên đúng mẫu.
- **R6**: duyệt mức nhạc = nút **Duyệt** của variant (ghi `approved_at`, như VIS1); chỉ variant đã duyệt, không stale mới tải "bản đăng".
- **Job / hủy / ổ đĩa**: tái dùng `VisualTarget`-kiểu target + `visual_key` + cơ chế hủy job của VIS1; từ chối dựng khi ổ < 3 GB; ghi qua thư mục tạm + `os.replace`, lỗi / hủy không để file dở, không đụng TC3 / variant VIS1.
- **Trang Đóng gói**: chọn "Nhạc nền: Chỉ giọng giảng (mặc định) | <nhạc đã duyệt>", chọn hình (Original | variant ambient đã dựng), thanh mức −30…−12 LU, fade; nút "Nghe thử 3 đoạn" (3 thẻ `<audio>`), "Dựng cả bài"; danh sách variant hiện nhạc + mức. Kho chưa có nhạc duyệt → hiện ghi chú "Chưa có nhạc đã duyệt trong kho".

## Phải giữ nguyên

- Voice Only luôn chọn được và là mặc định; file TC3 và variant VIS1 không nhạc không bị ghi đè; key / record / route VIS1 hiện có không đổi.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Từ cùng TC3 có cả Voice Only và Voice + nhạc; bản nhạc: thời lượng, 2 kênh, true peak trong ngưỡng, nhạc ≈ giọng + `level_lu` (sai số ≤ 1 LU).
2. Tương quan envelope giọng mix vs TC3 đạt ngưỡng `audio.compare`; test cố ý đặt nhạc +0 LU / đảo giọng → bị phát hiện (fail).
3. Điểm nối loop nhạc không có bước nhảy biên độ (RMS cửa sổ 20 ms quanh điểm nối trong ngưỡng).
4. Đổi nhạc / mức / fade → key mới; không đổi → dùng lại file.
5. Mix lỗi / hủy không để file dở, không đụng TC3 / variant khác.
6. Xem thử 3 × 30 giây tạo được, nghe được trên trang.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_music.py tests/test_packaging_visual.py tests/test_web_packaging.py` — AC1–6 trên audio tổng hợp (sine / tiếng nói mẫu ngắn trong test).
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`.
- Chạy thật trên một TC3 30–40 phút với nhạc HUMAN LEAD duyệt; gửi đoạn mẫu ở 2–3 mức để HUMAN LEAD chọn bằng tai.

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
