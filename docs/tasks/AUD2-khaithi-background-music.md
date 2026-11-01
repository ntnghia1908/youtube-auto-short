# Task: AUD2 — Nhạc nền tùy chọn cho khai thị ngắn và khai thị ghép

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session: contract, review, chạy thật, dựng mẫu nghe
- Implementer: codex — module tự chứa, có code AUD1 cũ (`48c7677a`) để tái dùng; dự phòng subagent `implementer` (Sonnet) nếu quota Codex ≥ ngưỡng
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-01: làm lại nhạc nền cho khai thị ngắn (clip 4–7 phút) và khai thị ghép (CP8.33 + TC3), chỉ đăng YouTube; boundary PKG chỉ phủ TC3 và đã bị THUMB2 gỡ AUD1, "PKG cho khai thị 4–7 phút và CP8.33" ghi là để sau → cần task S2 riêng
- Parallel group: —
- Owned paths: `src/auto_short/packaging/music.py` (mới), `src/auto_short/packaging/assets.py` (trường metadata nhạc tùy chọn + nạp từ manifest), `src/auto_short/packaging/__main__.py` (CLI `assets add` thêm cờ metadata, `assets import-music`), `src/auto_short/config.py` + `config.example.toml` (chỉ mục `[music]`), `src/auto_short/web/music.py` (mới: service + route + job kind), `src/auto_short/web/app.py` / `web/jobs.py` (chỉ đăng ký route / job kind), `src/auto_short/web/static/app.js`, `episode.html`, `favorites.js`, `theme_plan.js`, `style.css` (khối "Nhạc nền" trên thẻ), `docs/assets/music-manifest.json` (mới, chỉ metadata), `tests/test_music_mix.py` (mới), `tests/test_web_music.py` (mới), `tests/test_packaging_assets.py` (nếu có, phần metadata), contract này
- Dependencies: KTI1 / KTI2 (merged: `render/intro.offset` / `clip_record`, sidecar `intro` / `content_offset`), CP8.33, TC3, SHO1 (`store/shorts.borrow_short` khi clip đã lên kho 3090), kho asset PKG1 (`kind: music`)
- Base commit / branch: `a6837e3` (`origin/main`; rebase nếu main đã đi trước, kiểm VM trước khi code) / `feature/aud2-khaithi-music`
- Human Lead approval: APPROVED 2026-11-01 (G1, G2, G4–G8 theo đề xuất; G3 = chỉ dùng 1 bài)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm route + job web có auth, thêm mục config `[music]`, thêm trường cho `library.json`, và tạo thêm sản phẩm video để đăng.

## Bối cảnh

- AUD1 (#136, #137) chỉ áp dụng cho tuyển tập TC3, gắn với trang Đóng gói. THUMB2 (#184, `be0be424`) đã gỡ `music.py` / `variant.py` / `visual.py` cùng trang này. Code cũ ở `48c7677a` chỉ để tham khảo: tái dùng thuật toán (đo `ebur128`, đơn vị lặp có crossfade equal-power, `amix normalize=0`, kiểm true peak, `audio.compare`, streamhash), **không** restore `variant.py` / trang Đóng gói.
- Còn trên main: `packaging/assets.py` (`KINDS` có `music`, `add` / `approve` / `usable`), CLI `python -m auto_short.packaging assets add|approve|list`, `theme_render/audio.py` (`compare`, không sửa).
- Kho trên VM: AUD1 Result ghi có bản CC0 "The Budding of Consciousness" (`6a5f3380fb46…`). HUMAN LEAD không hài lòng bài này, nên **không** dùng làm mặc định và không hiện trong danh sách chọn (G7). Kho VM **chưa kiểm được** trong phiên này (xem "Kiểm môi trường").
- Video nguồn mix: (1) clip khai thị `output/<id>.kt/shorts/<clip>.mp4` 4–7 phút, có thể có intro 3 s (KTI1, sidecar `intro` / `content_offset`), có thể đã lên kho 3090 (SHO1); (2) video ghép yêu thích `output/_compilations/<pid>/<cid>.mp4` (9:16); (3) tuyển tập `output/_compilations/<pid>/theme/<plan>-r<rev>.mp4` (16:9). (2) và (3) có thể có intro 3 s đầu (KTI2 D-KTI2-4), mô tả có chapter.
- Đo 5 file HUMAN LEAD gửi (manifest `docs/assets/music-manifest.json`). Đều MP3 320 kbps, 44,1 kHz stereo, không có tag ID3. Loudness chênh nhau tới 15 LU (Voices −10,6 LUFS, Falling Snow −25,5 LUFS), nên gain phải tính theo số đo từng bài, không dùng một hệ số chung. 4/5 bài có đoạn fade / im lặng cuối 1,4–9 s, Falling Snow im 1,1 s ở đầu → lặp thẳng sẽ hụt ở điểm nối (xem D-AUD2-5).

## Quyết định đề xuất (HUMAN LEAD duyệt / sửa)

- **D-AUD2-1 Mặc định không nhạc** (đề xuất HUMAN LEAD): mọi video giữ như hiện tại. Bản có nhạc chỉ dựng khi bấm trên **từng video**; không có thao tác hàng loạt, không tự dựng khi render / ghép lại / dựng lại KTI. File gốc không bị ghi đè, sidecar / manifest gốc không đổi.
- **D-AUD2-2 File riêng**: bản có nhạc nằm cạnh nguồn trong thư mục `music/`: (1) `output/<id>.kt/music/<clip>-<key12>.mp4|json`; (2) `output/_compilations/<pid>/music/<cid>-<key12>.mp4|json`; (3) `output/_compilations/<pid>/theme/music/<plan>-r<rev>-<key12>.mp4|json`. Ghi qua thư mục tạm cùng ổ + `os.replace`; lỗi / hủy không để file dở. Mỗi video giữ **một** bản nhạc hiện hành: dựng bản mới (key khác) thì bản cũ bị xóa sau khi bản mới publish thành công.
- **D-AUD2-3 Giọng giảng nguyên vẹn**: giọng là input đầu của `amix`, gain 1,0, không nén / chuẩn hóa / limiter / lọc. Hình `-c:v copy` (streamhash hình = nguồn). Kiểm sau mix: `audio.compare(mix, nguồn)` đạt ngưỡng sẵn có (corr ≥ 0,9, lag ≤ 0,04 s, chênh thời lượng ≤ 0,1 s); thời lượng audio = nguồn ± 1 khung AAC; AAC 48 kHz stereo theo `[render] audio_bitrate`.
- **D-AUD2-4 Mức nhạc chỉnh được, không hardcode**: `level_lu` = loudness nhạc so với loudness giọng, chọn trên từng video (−30…−12, bước 0,5). Mặc định lấy từ config `[music] default_level_lu` (đề xuất **−22**, theo mốc AUD1: bản khai thị có nhạc HUMAN LEAD gửi đo được nhạc ≈ 22–26 LU dưới giọng). `gain_db = voice_lufs + level_lu − music_lufs`. `voice_lufs` đo trên **phần nội dung**, bỏ intro im lặng (`content_offset`). `music_lufs` đo trên đoạn nhạc sau khi cắt (D-AUD2-5). Nhạc < −60 LUFS → lỗi.
- **D-AUD2-5 Lặp cho video dài + crossfade**: trước khi lặp, tự cắt im lặng đầu / cuối mỗi bài (ngưỡng −50 dBFS, `silencedetect`, deterministic, ghi điểm cắt vào record). Manifest / kho có thể ghi `loop_end` riêng cho bài có đuôi fade dài (G4). Đơn vị lặp được dựng một lần, có crossfade equal-power (`qsin`) giữa đuôi và đầu bài, rồi phát bằng `-stream_loop -1`, không dùng `aloop`. `loop_crossfade` mặc định từ config (đề xuất 4 s, cho phép 0,5–8 s); bài phải dài ≥ 2 × crossfade + 1 s. Mỗi video chỉ dùng **một** bài, lặp lại (G3: HUMAN LEAD 2026-11-01 "Chỉ dùng 1 bài"); không có danh sách nhiều bài.
- **D-AUD2-6 Fade vào / ra**: `fade_in` mặc định 3 s (0–10), `fade_out` mặc định 5 s (0–15). Fade ra kết thúc đúng tại cuối audio nguồn; video ngắn hơn tổng fade → co fade theo tỉ lệ. Mặc định trong `[music]`, chỉnh được trên từng video.
- **D-AUD2-7 Intro 3 s thumbnail (KTI1 / KTI2)** (G2): đề xuất **nhạc bắt đầu từ 0 s**: fade vào trong 3 s thumbnail, đạt mức `level_lu` đúng lúc giọng vào (`fade_in` = `content_offset` khi có intro, trừ khi người dùng chỉnh). Lựa chọn khác: intro vẫn im lặng, nhạc vào tại `content_offset`. Cả hai cách đều không đổi hình / hòa tan 1 s của intro, và `voice_lufs` luôn đo bỏ intro.
- **D-AUD2-8 Ghi công**: asset có `attribution` khác rỗng → record ghi dòng ghi công. Nút "Copy mô tả" của bản có nhạc trả mô tả gốc (chapter giữ nguyên, vì timeline không đổi) + một dòng `Nhạc: <attribution>` ở cuối. Riêng clip khai thị (hiện chỉ copy tiêu đề) có thêm nút "Copy ghi công", chỉ hiện khi cần. Bài không yêu cầu ghi công (như Falling Snow) → không thêm dòng nào.
- **D-AUD2-9 Stale**: nguồn đổi (sha256 khác, ví dụ dựng lại KTI → `(rN)`, ghép lại, plan r+1), asset hết duyệt / đổi sha, hoặc `MUSIC_VERSION` đổi → bản nhạc hiện "cũ — dựng lại", không bị tự xóa / tự dựng lại, không tải như bản hợp lệ.
- **D-AUD2-10 Clip đã lên kho 3090**: dựng bằng bản sao mượn qua `store/shorts.borrow_short` (kiểm sha + sidecar intro). 3090 không trả lời → job dừng, lý do "đang ở kho 3090, thử lại sau". Bản có nhạc chỉ lưu local, không offload (G6).

## Goal

Trên thẻ clip khai thị (trang tập) và thẻ video ghép (tab "Video đã ghép" trang Yêu thích), HUMAN LEAD có thể chọn một bài đã duyệt hoặc "Không nhạc" (mặc định), chỉnh mức / fade, nghe thử, dựng bản có nhạc rồi xem / tải / copy mô tả có ghi công. File gốc giữ nguyên.

## Scope

- In scope:
  - **Kho nhạc**: thêm vào asset entry các trường tùy chọn `title`, `artist`, `attribution`, `loop_end` (giữ `schema_version 1`, entry cũ vẫn hợp lệ). CLI: `assets add --title --artist --attribution`; `assets import-music <manifest.json> --dir <thư mục mp3>` chỉ nạp bài có `license_status: verified`, kiểm sha256 khớp manifest, và **từ chối** bài `pending` / thiếu file / lệch sha. Bài đã nạp vẫn cần `assets approve` như PKG1. Thêm `assets unapprove <id>` (G7): bài bị gỡ duyệt không hiện trong danh sách chọn, bản nhạc đã dựng từ bài đó thành "cũ". Thêm hoặc thay bài sau này: cập nhật manifest → `import-music` → `approve`, không cần sửa code.
  - **`packaging/music.py`**: `measure`, `trim_silence`, `loop_unit` (một bài), `mix(source, intro_offset, spec) → mp4`, `preview(...) → m4a`, các kiểm theo D-AUD2-3. Hàm thuần nhận `run` tiêm vào (test không cần ffmpeg thật cho nhánh lỗi).
  - **Spec + key**: `{asset_id, level_lu, fade_in, fade_out, loop_crossfade, intro_mode}` chuẩn hóa, làm tròn 0,1. Key = hash(spec, sha asset, sha256 nguồn, `MUSIC_VERSION`, `audio_bitrate`). Spec không đổi → dùng lại file.
  - **Xem thử**: 2 đoạn `.m4a` audio-only, mỗi đoạn 30 s: đoạn 1 từ 0 s (gồm intro + lúc giọng vào), đoạn 2 lấy quanh **điểm nối vòng lặp đầu tiên** để nghe crossfade (video ngắn hơn bài nhạc thì lấy giữa). Gain / pha lặp / fade giống bản đủ tại vị trí đó. Chỉ giữ bộ xem thử mới nhất của mỗi video.
  - **Web**: job kind `music` (làn render, một job mỗi video, trùng → 409; hủy dùng cơ chế job hiện có); route dưới auth chung. Thẻ có khối "Nhạc nền" thu gọn: chọn bài (danh sách nhạc đã duyệt, có title — artist), thanh mức, fade, [Nghe thử] (2 thẻ `<audio>`), [Dựng bản có nhạc], rồi trình phát + [Tải bản có nhạc] + [Copy mô tả / ghi công] + [Xóa bản nhạc]. Kho chưa có nhạc duyệt → ghi chú "Chưa có nhạc đã duyệt trong kho". Tên file tải: tên tải hiện có + ` (nhạc)`.
  - Từ chối dựng khi ổ < 3 GB trống.
- Out of scope: Short thường (không khai thị); bản dọc / HD của tập; ducking theo tiếng nói (AUD1.1); lọc / xử lý giọng; tải nhạc từ mạng; AI tạo nhạc; tự đăng / thay video trên YouTube; offload bản nhạc lên kho 3090; khôi phục trang Đóng gói / VIS1; xóa bài CC0 cũ khỏi kho.

## Authority / key decisions

- HUMAN LEAD 2026-11-01 (tin nhắn giao việc); `docs/decisions/PKG-video-packaging-authorization.md` R2 (lời giảng nguyên vẹn), R3 (output riêng + ghi qua tạm), R4 (stale), **R5 (chỉ asset có source + license + approved, không tự tải)**, R7 (không dependency mới), G3 (nguồn nhạc được phép: YouTube Audio Library, ghi công khi bài yêu cầu) áp dụng tương tự cho phạm vi mới. Boundary PKG không tự mở rộng; task này được duyệt riêng.
- `theme_render/audio.py` `compare` + ngưỡng: tái dùng, không sửa. `render/intro.py` `offset` / `clip_record`: tái dùng, không sửa.
- Dependency: chỉ ffmpeg / ffprobe + stdlib (CP1 §10), không thêm gì.

## Implementation approach

- Một lần encode audio cho cả video, hình `-c:v copy`, `-map_metadata` / chapter giữ như nguồn. Video 4–7 phút: ước tính vài giây đến dưới 1 phút. TC3 40 phút: ~2 phút (AUD1 đo 131 s).
- True peak: ngưỡng = `max(−1,0; true_peak_nguồn + 0,5)` dBTP như AUD1. Vượt → lỗi rõ, gợi ý giảm mức nhạc, không tự hạ giọng.
- Tái dùng từ `48c7677a:src/auto_short/packaging/music.py`: `measure`, `loop_unit`, `music_filter`, `check_audio`, `video_hash`, giao thức publish + rollback. Bỏ phần phụ thuộc `variant` / `visual` (`video_source`, spec `visual`).

## Phải giữ nguyên

- File gốc, sidecar `.intro.json`, `render_manifest.json`, `<cid>.json`, record TC3, mô tả / chapter gốc; mọi route / nút hiện có (Xem, Tải, Copy, Đã đăng, thumbnail); KTI1 / KTI2 / THUMB2 không đổi byte. Video không chọn nhạc: không đổi gì, không tạo file. Entry `library.json` cũ (kể cả CC0 `6a5f…`) vẫn đọc được.

## Code bị thay / xóa

- Không có (thêm mới; code AUD1 cũ đã bị xóa ở `be0be424`).

## Acceptance Criteria

1. Không chọn nhạc → không có file mới, nguồn byte-identical. Chọn nhạc → file riêng: 2 kênh, 48 kHz AAC, thời lượng audio = nguồn ± 1 khung AAC, streamhash hình = nguồn, true peak ≤ ngưỡng, loudness nhạc ≈ giọng + `level_lu` (đo riêng phần nhạc, sai số ≤ 1 LU) ở ít nhất 3 mức (−18 / −22 / −26).
2. Giọng giữ nguyên: `audio.compare` đạt. Test cố ý đặt nhạc +0 LU qua runner tiêm lỗi, hoặc đảo giọng → fail đúng gate.
3. Video dài hơn bài nhạc: nhạc lặp đủ thời lượng. Tại mọi điểm nối, RMS cửa sổ 20 ms hai bên trong ngưỡng (không có bước nhảy / hụt). Im lặng đầu / cuối bài được cắt trước khi lặp.
4. Fade vào bắt đầu ở 0 s, fade ra kết thúc đúng cuối audio. Video có intro: theo G2 (mặc định: nhạc fade vào trong intro, đạt mức đúng lúc `content_offset`). `voice_lufs` đo bỏ intro.
5. Đổi bài / mức / fade / crossfade / nguồn → key mới. Không đổi → dùng lại file (không encode). Nguồn đổi sha hoặc asset hết duyệt → "cũ", không tải được như bản hợp lệ.
6. Lỗi / hủy giữa chừng không để file dở, không đụng nguồn hay bản nhạc hiện hành. Bản mới chỉ thay bản cũ sau khi publish thành công.
7. Asset `pending` / chưa duyệt / thiếu source / thiếu license / lệch sha → không nạp hoặc không dùng được. `import-music` nạp đúng bài `verified` với metadata đầy đủ. Bài có `attribution` sinh dòng `Nhạc: …` trong mô tả copy; bài không yêu cầu không sinh dòng nào.
8. Web: route yêu cầu đăng nhập, chặn id / tên file lạ (traversal, symlink); job trùng → 409; xem thử 2 × 30 s nghe được; thẻ clip khai thị, video ghép yêu thích và tuyển tập đều có khối "Nhạc nền" với "Không nhạc" là mặc định. Clip đã lên kho 3090 dựng được qua bản mượn; 3090 không trả lời → lỗi có lý do.
9. Full suite PASS; `framework-check`, `git diff --check`, `node --check` các JS sửa: PASS.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_music_mix.py` — AC 1–7 (audio tổng hợp: sine + tiếng có envelope kiểu giọng; không socket, Codex chạy được).
- `PYTHONPATH=src python -m pytest -q -x tests/test_web_music.py tests/test_web_compilation.py tests/test_web_theme_plan.py` — AC 8 (TestClient: ORCHESTRATOR chạy ngoài sandbox).
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 9.
- Chạy thật (ORCHESTRATOR, trên **bản sao** dữ liệu, không restart 8080 khi chưa duyệt): 1 clip khai thị có intro + 1 tuyển tập TC3, dùng Falling Snow (bài duy nhất đã xác minh), mức −18 / −22 / −26 LU, mỗi mức 1 đoạn 30–45 s (gồm intro → giọng vào, và một điểm nối) để HUMAN LEAD nghe bằng tai.

## Manual test checklist (Tech Lead)

Chạm public API (route + job mới sau đăng nhập) và config, không chạm database / security model → manual test là gate trước merge.

- [ ] HUMAN LEAD nghe mẫu trên loa và tai nghe điện thoại; chọn `default_level_lu`.
- [ ] Nghe điểm nối vòng lặp và đoạn intro → giọng; không nghe thấy hụt / giật.
- [ ] Thẻ clip / video ghép: "Không nhạc" mặc định, dựng / tải / copy dễ dùng trên điện thoại.
- [ ] Upload thử 1 video có nhạc lên YouTube (riêng tư): kiểm Content ID / bản quyền trên Studio.

## Gate — HUMAN LEAD đã quyết 2026-11-01

HUMAN LEAD: "G3. Chỉ dùng 1 bài. Còn lại đồng ý." → G1, G2 (fade từ 0 s), G4, G5, G6, G7 (ẩn), G8 (−22 tạm, chốt sau khi nghe) theo cột Đề xuất.

| ID | Câu hỏi | Đề xuất |
|---|---|---|
| G1 | Phạm vi nguồn: clip khai thị 4–7 phút + video ghép yêu thích CP8.33 + tuyển tập TC3; Short thường **không** có nhạc | Đồng ý |
| G2 | Intro 3 s: nhạc fade vào ngay từ 0 s (thumbnail có nhạc) hay intro im lặng, nhạc vào tại `content_offset` | Fade từ 0 s |
| G3 | Video dài: một bài lặp, hay cho phép chọn danh sách nhiều bài nối nhau (crossfade), rồi lặp cả danh sách | **Quyết: chỉ dùng 1 bài** (HUMAN LEAD 2026-11-01) |
| G4 | Cắt im lặng đầu / cuối tự động (−50 dBFS) + cho phép `loop_end` riêng từng bài trong manifest | Đồng ý |
| G5 | Config mới `[music]`: `default_level_lu = -22`, `fade_in = 3`, `fade_out = 5`, `loop_crossfade = 4`; route + job kind `music` (sau đăng nhập); trường tùy chọn mới trong `library.json` | Đồng ý |
| G6 | Bản có nhạc chỉ lưu local (clip 4–7 phút ≈ 50–150 MB, TC3 ≈ 0,3–1,5 GB), xóa tay; không offload lên kho 3090 | Đồng ý |
| G7 | Bài CC0 "The Budding of Consciousness" (`6a5f…`): ẩn khỏi danh sách chọn (đánh dấu không dùng bằng CLI `assets unapprove`) hay xóa khỏi kho | Ẩn (không xóa file) |
| G8 | `default_level_lu` cuối cùng: chọn sau khi nghe mẫu (manual checklist) | −22 tạm thời |

## Kiểm môi trường (ORCHESTRATOR, 2026-11-01)

- Phiên này chạy trong container cloud, không gắn VM (`list_computer_folders` rỗng). **Chưa kiểm được trên VM**: `git status` / nhánh worktree 8080, `assets list` (bài CC0 `6a5f…` còn không), ffmpeg / ffprobe, dung lượng ổ. Cần làm ở phiên có VM trước khi implement:

  ```bash
  cd ~/projects/youtube-auto-short && git status -sb && git log --oneline -1
  ```

  ```bash
  python -m auto_short.packaging assets list
  ```

  ```bash
  ffmpeg -version | head -1; ffprobe -version | head -1; df -h ~/projects
  ```

- Trong container: repo `claude/lucid-dijkstra-9gqla4` = `origin/main` `a6837e3`, working tree sạch trước khi thêm contract; ffmpeg / ffprobe có ở `/usr/bin`; ổ trống 30 GB. `.gitignore` đã có `*.mp3`.
- File nhạc: nhận đủ **6/6** bài (BGM-01 Whispering Stream gửi sau, cùng ngày). Số đo từng bài: `docs/assets/music-manifest.json`. Tên, nghệ sĩ và thời lượng khớp danh sách HUMAN LEAD (sai ≤ 1 s). File không có tag ID3, nên nguồn / license lấy theo xác nhận của HUMAN LEAD.
- License: chỉ BGM-06 Falling Snow `verified`. BGM-01…05 để `pending`, không nạp kho cho đến khi HUMAN LEAD xác nhận trong Studio (loại license + có yêu cầu ghi công không, và nếu có thì chép nguyên dòng ghi công Studio cung cấp).

## Result

- (chưa implement)
