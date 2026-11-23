# Task: FIX-audio-pad-concat — tạo `.m4a` có đệm im lặng mà không mã hóa lại audio

## Status / Approval

- Status: READY (chờ HUMAN LEAD thử kéo tua trên 8080)
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — IMPLEMENTER mặc định (quota 5 h 91 %)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-15 ("Ok đồng ý") sau số đo bên dưới
- Parallel group: —
- Owned paths: `src/auto_short/web/audio_cache.py`, `tests/test_web_audio.py`, file này; Amendment A: `src/auto_short/web/static/player.js`, `tests/test_web_listen.py`
- Dependencies: LISTEN2 (#215, Amendment G)
- Base commit / branch: `6650895` / `fix/audio-pad-concat`
- Human Lead approval: accepted 2026-11-15
- Implementation authorized: YES

## Goal

Short chưa có trong cache audio mở nhanh như trước LISTEN2 G. Đo trên VM (Short 5 phút `0embg26tGW4.kt/k01`, máy rảnh):
chép thẳng 0,3 s; hiện tại (`adelay` + mã hóa lại AAC toàn bài) **16,4 s**; mã hóa riêng 1,5 s im lặng rồi ghép (concat demuxer, `-c copy`) **0,5 s**, dài hơn gốc 1,52 s, đầu file −91 dB, giải mã không lỗi.

## Scope

- In scope: cách tạo file trong `cached_audio`; cache key đổi để file cũ (bản mã hóa lại) được tạo lại; test.
- Out of scope: client (`player.js` vẫn trừ `AUDIO_PAD = 1.5`), route, giới hạn cache, nguồn kho.

## Implementation approach

- `ffprobe` luồng audio đầu của nguồn: codec, sample rate, channel layout / channels.
- Nguồn AAC: tạo đoạn im lặng `anullsrc` cùng sample rate + layout, dài `AUDIO_PAD`, mã hóa AAC; tách audio nguồn `-c:a copy`; ghép bằng concat demuxer `-c copy -movflags +faststart`. Không mã hóa lại audio nguồn.
- Nguồn không phải AAC hoặc probe / ghép lỗi: dùng đường hiện tại (`adelay` + mã hóa lại) để vẫn có file.
- Cache key thêm nhãn cách làm mới (vd `concat-pad1.5`).

## Phải giữ nguyên

- Độ dài tăng ≈ `AUDIO_PAD` (sai số ≤ 0,08 s như test hiện có), đầu file im lặng, chỉ một luồng AAC, faststart.
- Khóa theo key, file tạm trong `.extract-*`, chỉ file hoàn chỉnh mới hiện ra, prune ≤ `MAX_BYTES`, kiểm sha256 / size khi nguồn ở kho.

## Code bị thay / xóa

- Lệnh `adelay` + `-c:a aac` thành đường dự phòng, không còn là đường chính.

## Acceptance Criteria

1. Nguồn AAC: lệnh xử lý audio nguồn dùng `-c:a copy` / `-c copy` (không `-c:a aac` trên toàn bài); kết quả dài hơn nguồn ≈ `AUDIO_PAD` (±0,08 s), đoạn `[0, AUDIO_PAD − 0,1]` im lặng, nội dung nguồn bắt đầu ở ≈ `AUDIO_PAD` (±0,08 s, kiểm bằng nguồn có tiếng ngay từ đầu).
2. Sample rate / channels của file ra bằng nguồn (thử ít nhất 44100 mono và 48000 stereo).
3. Nguồn không AAC (vd MP3 trong mp4/mkv) hoặc ghép lỗi → vẫn ra file có đệm qua đường dự phòng.
4. Cache key khác key của bản G (file cũ không được dùng lại); các test cache / lock / prune / kho hiện có vẫn PASS.

## Required verification

- `PYTHONPATH=src python -m pytest tests/test_web_audio.py -q -k "not http"` (IMPLEMENTER).
- ORCHESTRATOR: full suite `-n auto`; đo thời gian thật trên Short 5 phút; 8080 thử mở Short mới.

## Amendment A — kéo thanh tua video bị kéo ngược về audio (2026-11-16)

HUMAN LEAD (2026-11-16): "Video player hiện tại rất khó trượt" → chọn "Kéo thanh tua video". Log 8080 (`8436e2a`, client `9203abee…`): nhiều `video_resync` lúc trang hiện, drift 2,7 → 160 s. Nguyên nhân: từ LISTEN2 C audio là đồng hồ; khi người dùng kéo thanh tua của `<video>`, audio vẫn ở chỗ cũ, `timeupdate` của audio gọi `syncVideo()` và đặt `video.currentTime` về vị trí audio (drift > 0,5 s) trước / trong lúc kéo, nên video nhảy ngược.

Làm:
- `player.js`: sự kiện `seeking` của video không do code đặt (không `arm`) = người dùng đang tua → ghi mốc (vd `videoScrubUntil = now + 1500 ms`, gia hạn mỗi `seeking`). `syncVideo()` không `force` bỏ qua chỉnh drift khi `video.seeking` hoặc trong mốc này. `seeked` của người dùng giữ đường hiện có: audio nhảy tới `video.currentTime` (+ pad), `onAction("seek")`; xong thì xóa mốc để đồng bộ lại bình thường.
- Không đổi: tua bằng nút / Media Session / phòng (remote seek), video bị chỉnh khi lệch thật (không tua), trang ẩn.

AC A1 (harness `tests/test_web_listen.py`): video `seeking` do người dùng rồi audio `timeupdate` với drift lớn → không đặt lại `video.currentTime`, không log `video_resync`; `seeked` → audio `currentTime = vị trí + pad`, gửi `seek`; sau đó drift > 0,5 không do tua → vẫn resync như cũ; `seeking` do code (`arm`) không bật mốc. Cả trang Nghe một mình và phòng.

## Result

- IMPLEMENTER READY (2026-11-15), branch `fix/audio-pad-concat`, base `6650895`; chưa commit / push / PR.
- AAC: mã hóa riêng đệm im lặng, tách nguồn và ghép bằng stream copy; cache tag `concat-pad{AUDIO_PAD}`. Probe / tạo đệm / tách / ghép lỗi hoặc nguồn không AAC dùng lại `adelay` + AAC.
- Helper mới: `_concat_pad` (ứng dụng), `assert_padded_audio` (test: probe, độ dài, im lặng, onset, một luồng AAC, faststart). Đã tìm bằng `rg -n 'def _run|ffprobe|anullsrc|concat' src/auto_short/render/stage.py src/auto_short/compilation tests/conftest.py tests/web_helpers.py`; tái dùng `_run`, `probe_media`, fixture `short` / `video`. Helper compilation phục vụ video / spec riêng; concat list ở đây chỉ gồm hai tên tương đối cố định trong tmp nên không cần helper escape đường dẫn.

| AC | Test / bằng chứng |
|---|---|
| 1 | `test_audio_concat_copies_aac_and_preserves_format`: nguồn sine từ 0, kiểm lệnh copy, độ dài ±0,08 s, im lặng tới PAD −0,1 s, onset ±0,08 s; một luồng AAC và faststart |
| 2 | Test trên parametrize 44100 mono / 48000 stereo, so sample rate và channels nguồn / đích |
| 3 | `test_audio_concat_fallback`: MP3, probe unavailable / JSON lỗi / thiếu stream, lỗi tạo đệm / tách / concat (có file partial); layout thiếu được suy từ channels; kiểm file thật và dọn tmp |
| 4 | `test_audio_concat_ignores_old_pad_cache`; các test hiện có về cache/version, lock/prune, stream kho và sha256/size đều PASS |

- Verification: `PYTHONPATH=src python -m pytest tests/test_web_audio.py -q -k "not http"` → **25 passed, 1 deselected in 8.45s**. `git diff --check` PASS.
- Dòng thêm / xóa (`git diff --numstat`): ứng dụng **+38 / −7**; test **+96 / −2**.
- Chờ ORCHESTRATOR review và verification thuộc phần ORCHESTRATOR trong contract: full suite, đo Short 5 phút, thử web 8080. IMPLEMENTER không chạy các bước này; không gọi mạng thật hoặc agent khác.
- ORCHESTRATOR 2026-11-15: review OK. Đo `cached_audio` thật trên Short 5 phút (`0embg26tGW4.kt/k01`): tạo mới **0,74 s** (trước 16,4 s), lần sau 0,000 s, dài hơn nguồn 1,521 s. Full suite `-n auto` lần 1: 1 fail `test_theme_render.py::test_description_refresh_on_cache_hit_without_encoding` (không liên quan audio_cache; chạy riêng PASS, chạy lại file `-n auto` lúc fail lúc PASS = chập chờn); lần 2: **4448 passed, 2 skipped**.

- Amendment A — IMPLEMENTER READY (2026-11-16), branch `fix/audio-pad-concat`, HEAD `8436e2a`; chưa commit / push / PR.
- Video `seeking` của người dùng gia hạn `videoScrubUntil` 1500 ms; `syncVideo()` thường bỏ chỉnh drift khi đang seeking / còn mốc. `seeked` chuyển audio tới vị trí + pad, xóa mốc và gửi `seek`; force / trang ẩn giữ đường hiện có.
- Helper mới: không thêm helper ứng dụng; test có closure cục bộ `resyncs` đếm log qua các batch. Đã tìm bằng `rg -n 'arm|isProgrammed|programKey|syncVideo|seeked|seeking|function seek|position' src/auto_short/web/static/player.js` và `rg -n 'run_player_js|player_js|resync|seeking|seeked' tests/test_web_listen.py`. Tái dùng `arm`, `programKey`, `seek`, `position`, `syncVideo`, harness `run_player_js`; thêm tùy chọn `consume=false` cho `isProgrammed` để kiểm tra tại `seeking` mà giữ dấu cho `seeked`.

| AC Amendment A | Test / bằng chứng |
|---|---|
| A1 — một mình + phòng | `test_player_js_video_scrub_preserves_user_seek_and_resumes_sync[False/True]`: drift lớn trong thao tác tua không đổi video / log resync; gia hạn mốc; `seeked` đặt audio + pad và gửi đúng một `seek`; drift sau đó vẫn resync / log; seeking do `arm` giữ dấu, không bật mốc / gửi lệnh; hết mốc, native seeking và force được kiểm riêng |
| Giữ hành vi hiện có | Nhóm `player_js` gồm test Media Session, audio pad, remote controls phòng và trang ẩn đều PASS |

- Verification được giao: `PYTHONPATH=src python -m pytest tests/test_web_listen.py -q -k "player_js"` → **84 passed, 26 deselected in 6.05s**; `node --check src/auto_short/web/static/player.js` → **PASS** (exit 0). Không chạy full suite / gọi mạng thật / gọi agent khác.
- Review diff đối chiếu Amendment A: không còn finding trong phạm vi implementer; chờ ORCHESTRATOR review.
- Dòng thêm / xóa Amendment A (`git diff --numstat`, so với HEAD): ứng dụng **+11 / −4**; test **+46 / −0**.
- ORCHESTRATOR Amendment A 2026-11-16: review OK; full suite `-n auto` **4450 passed, 2 skipped**.
