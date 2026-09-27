# Task: CP7 — Short Composition / Renderer

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `0fdf649` (main, sau merge PR #8) / `feature/cp7-render`
- Human Lead approval: accepted (APPROVE TASK, 2026-09-27; R1–R11; P1, P2, P4, P5 theo đề xuất; **P3 sửa**: title dài → panel title cao thêm trước, không đủ mới thu nhỏ chữ)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì CP7: (a) tạo artifact contract `render_manifest.json` và file Short mà CP8 (end-to-end), CP9 (review) dùng lại; (b) chốt font OFL đóng gói trong repo (CP1 §4) và rule ngắt dòng / fit chữ dùng xuyên header + title; (c) render ghi ra ngoài workspace (`output/`, CP1 §2) — mở rộng cách xử lý artifact của CP2; (d) nguồn title trước khi có CP9 (sửa pointer CP6 G5, xem P1); (e) mở rộng config + CLI. Quyết định R1–R11 dưới đây duyệt cùng APPROVE TASK. Không thêm dependency Python (font là asset, CP1 §4).

## Goal

Từ một episode đã có `clips.json` (CP5) và `titles.json` (CP6), stage `render` dựng mỗi clip `titled` thành một Short `output/<episode_id>/shorts/<clip_id>.mp4` 1080×1920 theo đúng layout mẫu CP1 §4 (nền đen, header vàng, video nguồn crop giữa, title vàng), với đoạn nguồn `[clip.source_start, clip.source_end]` đã rút khoảng lặng theo `trims` của candidate (CP1 §5, CP4 A8, CP5 B11), kèm `output/<episode_id>/render_manifest.json` (clip, title, source hash, render config hash — CP1 §2). Cùng input + config → cùng kết quả (roadmap CP7 Success).

## Scope

- In scope:
  - Subpackage `src/auto_short/render/`: kế hoạch đoạn giữ lại (R3), đo chữ + ngắt dòng + fit (R5), hình học layout (R4), dựng lệnh `ffmpeg` (R6), validation (R9), stage (R10).
  - Font OFL đóng gói trong repo (R7): tải file font ứng viên, render mẫu so sánh, HUMAN LEAD chốt; commit file font + `OFL.txt`.
  - Artifact `render_manifest.json` (schema v1) + `shorts/<clip_id>.mp4`.
  - Config `[render]` (typed, `tomllib`), `config.example.toml`.
  - CLI `auto-short render <episode_id> [--force] [--config PATH]`; `status` hiển thị stage `render`.
  - Tests `pytest`: logic thuần (đoạn giữ lại, đo chữ, ngắt dòng/fit, layout, validation) không cần video; test tích hợp nhỏ với video tổng hợp bằng `ffmpeg` lavfi (vài giây) cho stage/skip/stale/ffprobe.
  - Chạy thật trên `rbjfCfFq3Dk` (13 clip) + mẫu so sánh với ảnh mẫu; gửi mẫu (ảnh + vài clip) cho HUMAN LEAD xem/nghe.
  - Docs: decision record `docs/decisions/CP7-render-contract.md` (ACCEPTED sau review); CP1 §4 (font đã chốt, rule fit P3: title panel cao thêm trước), CP6 G5 (pointer nguồn title, theo P1); project profile (module map `render/` → implemented, authority order); README (usage); current-state.
- Out of scope:
  - Review/sửa title, approve/reject clip, `review.json` (CP9); render clip `untitled` (CP6 P3 — bỏ qua cho tới CP9).
  - Chạy cả pipeline một lệnh (CP8); batch nhiều episode (CP9).
  - Subtitle / lower panel (CP1 §7: tắt); redesign layout, đổi màu/tỉ lệ CP1 §4.
  - Chuẩn hóa loudness, fade/crossfade ở điểm rút lặng, reframe theo mặt người (có thể đề xuất ở CP10 nếu nghe/xem thấy cần).
  - Render từng clip lẻ / cache từng clip giữa các lần chạy, GPU encode (CP11).
  - Upload YouTube (CP1 §2).

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP7; `docs/decisions/CP1-product-contract.md` §2 (output), §3, §4 (layout + sửa đổi CP6: title 3 dòng / thu nhỏ chữ; font OFL chốt ở CP7 bằng so sánh trực quan), §5 (rút khoảng lặng `max_pause` 1.0 s, không jump cut ý), §7 (subtitle tắt), §8 (render deterministic; auto-approve chỉ là config explicit), §10 (dependency); `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP4-analysis-contract.md` A8, A10 (`trims`); `docs/decisions/CP5-selection-contract.md` B7, B11 ("Cho CP7"); `docs/decisions/CP6-titling-contract.md` G2 (header ≤ 3 dòng, ngắt dòng hiển thị là của CP7), G5 (nguồn title), G6 (`untitled`), G7.
- Dữ kiện đo 2026-09-26 (main `0fdf649`, `work/rbjfCfFq3Dk`):
  - Nguồn: H.264 1440×1080 (4:3), 29.97 fps, Opus 48 kHz stereo, 3622 s.
  - `clips.json`: 13 clip, `selected_seconds` 826.2 s (31.3–98.6 s/clip), 2 clip có `head_cut` (`k04`, `k10`). `titles.json`: 13/13 `titled`, header `["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]`; title 28–51 ký tự, 9/13 dài hơn ≈ 36 ký tự (sức chứa 2 dòng ở cỡ chữ mẫu, CP6) → cần 3 dòng hoặc thu nhỏ chữ.
  - Ảnh mẫu (`docs/decisions/assets/cp1-layout-reference.jpg`, 576×1280): header "Thập Thiện Nghiệp Đạo Kinh (tập 14)" tự xuống dòng → header hiển thị 3 dòng; chữ header/title sans-serif nét thường, căn giữa; bước dòng ≈ 0.068 W (header) và ≈ 0.087 W (title) — đo chính xác khi implement.
  - `ffmpeg` 6.1.1 có `libfreetype`, `libharfbuzz` (`drawtext` có `text_shaping`), `libfribidi`, `libfontconfig`, `libass`, `libx264`; có filter `drawtext`, `drawbox`, `overlay`, `concat`, `trim/atrim`, `select/aselect`.
  - Máy không cài font Noto / Be Vietnam / Roboto hệ thống → font phải đóng gói trong repo (CP1 §4), không dựa fontconfig.
  - `output/` đã có trong `.gitignore`.
- Quyết định (DECIDE cùng APPROVE TASK):
  - **R1 Stage / artifact:** stage `render` (CP1 §8, đã có trong `STAGES`), subpackage `src/auto_short/render/`. Artifact `render_manifest.json` + `shorts/<clip_id>.mp4` trong thư mục output của episode (R8). `render_manifest.json` ghi atomic, không chứa timestamp (CP2 D5).
  - **R2 Clip được render:** mọi clip của `clips.json` có entry `titles.json` `status = titled`, theo thứ tự `clips.json`; clip `untitled` → không render, ghi `status: "skipped"`, `skip_reason: "untitled"` + cảnh báo stderr (CP6 G6/P3). `clips: []` hoặc không clip nào `titled` → stage `done`, không file mp4, cảnh báo. Title/header lấy theo P1.
  - **R3 Đoạn giữ lại (deterministic):** đoạn nguồn `[clip.source_start, clip.source_end]` (đã tính `head_cut`, B11) trừ các `trims` của candidate (`candidates.json` theo `candidate_id`) giao đoạn đó; trim bị `source_start` cắt ngang chỉ tính phần trong đoạn (B11 "Cho CP7"). Kết quả `segments` = danh sách `[a, b]` tăng dần, không chồng nhau. Kiểm `Σ (b − a)` = `clip.duration` (sai lệch ≤ 1 ms) — lệch → `failed` (dữ liệu không nhất quán, chạy lại selection/analysis). `clips.json.candidates_sha256` và `titles.json.clips_sha256` / `candidates_sha256` phải khớp input đã đọc, nếu không → `failed`.
  - **R4 Layout (CP1 §4, không redesign):** khung W×H = 1080×1920, nền `#000000`; header panel rộng 0.79 W, cao 0.27 W; video full W, cao 1.12 W (= 1210 px, làm tròn chẵn), scale + crop giữa theo chiều ngang (nguồn 4:3 giữ ≈ 67 % bề ngang); title panel rộng 0.81 W, cao 0.27 W, khe dưới video 0.01 W; khe header→video 0.005 W; khối nội dung căn giữa theo chiều dọc. Panel `#FEDB00`, bo góc (bán kính đo từ ảnh mẫu khi implement), chữ đen căn giữa từng dòng, khối chữ căn giữa theo chiều dọc trong panel. Mọi tỉ lệ là tham số `[render]` (mặc định = số trên) vào `config_hash`. Tọa độ pixel đã tính ghi ở `render_manifest.json` `layout`. Không vẽ gì ở vùng đen còn lại (không subtitle, CP1 §7). Nguồn có tỉ lệ khác (16:9, dọc) → cùng rule scale-to-fill + crop giữa.
  - **R5 Đo chữ, ngắt dòng, fit (dùng chung header + title):**
    - Đo bề rộng chữ bằng bảng advance width của chính file font (đọc `cmap` + `hmtx` + `unitsPerEm` của TTF bằng stdlib `struct`; không thêm dependency). Ký tự không có glyph trong font → `failed` (font không hỗ trợ đủ dấu tiếng Việt là lỗi cấu hình).
    - Cỡ chữ mẫu: header `header_font_size`, title `title_font_size` (tỉ lệ theo W, đo từ ảnh mẫu khi implement; title ≈ 1.3–1.5× header), bước dòng `line_spacing` × cỡ chữ; lề trong panel `panel_padding` (tỉ lệ W).
    - Ngắt dòng chỉ tại khoảng trắng; với mỗi cỡ chữ, chọn cách ngắt có **ít dòng nhất**, trong đó ưu tiên **dòng dài nhất ngắn nhất** (ngắt cân, như "Các bậc thang / tu học Phật pháp").
    - Fit **title** (**P3, HUMAN LEAD 2026-09-27: panel cao thêm trước, không đủ mới thu nhỏ**):
      1. Ở cỡ chữ mẫu, ngắt dòng theo bề rộng trong của panel (rộng không đổi). Nếu ≤ 3 dòng: chiều cao panel = `max(title_panel_height, chiều cao khối chữ + 2 × panel_padding)` — tức title 2 dòng giữ panel mẫu, title 3 dòng làm panel **cao thêm** vừa đủ.
      2. Nếu ở cỡ mẫu cần > 3 dòng, hoặc panel cần cao hơn `title_panel_max_height` (tỉ lệ W, mặc định sao cho khối nội dung vẫn nằm trong khung 1920 với lề trên/dưới ≥ `min_frame_margin`, đo khi implement): panel = `title_panel_max_height`, giảm cỡ chữ dần (bước 1 px) tới khi ≤ 3 dòng và vừa panel đó.
      3. Cỡ chữ phải giảm dưới `min_font_scale` × cỡ mẫu (mặc định 0.6) mới vừa → `failed` (không cắt chữ).
      - Panel title cao thêm thì khối nội dung (header + video + title) vẫn căn giữa theo chiều dọc (CP1 §4) → layout tính **theo từng clip**, ghi ở entry `shorts[].layout` của `render_manifest.json`.
    - Fit **header**: panel header cố định (ảnh mẫu đã hiển thị header 3 dòng trong panel mẫu); giảm cỡ chữ dần tới khi ≤ 3 dòng và vừa panel; dưới `min_font_scale` → `failed`. Header chung cho mọi clip nên fit một lần.
    - Dòng hiển thị + cỡ chữ đã chọn ghi ở `render_manifest.json`.
  - **R6 Render (một lệnh `ffmpeg` mỗi clip, system binary CP1 §10):**
    - Video: lấy các `segments` (R3) nối liền, scale + crop (R4); ảnh nền (nền đen + 2 panel bo góc + chữ) dựng bằng `ffmpeg` (lavfi `color` + vẽ panel + `drawtext` với `fontfile` đóng gói, `text_shaping` bật) rồi `overlay` video lên — cách dựng chi tiết (filter graph, một hay hai bước) do implement chọn, miễn đúng R4/R5 và không thêm dependency.
    - Cắt chính xác theo thời gian (decode rồi chọn, không stream-copy); audio và video cắt cùng `segments`; không fade/crossfade ở điểm nối (điểm nối nằm trong khoảng lặng, CP4 A8).
    - Encode (**P4**): H.264 `libx264`, `yuv420p`, `crf` 18, `preset` `medium`, `+faststart`; fps giữ nguồn nếu ≤ 30, ngược lại 30 (CP1 §2); AAC 48 kHz stereo 192 kb/s. Tham số encode vào `config_hash`; `threads` (thực thi) không vào hash.
    - Ghi vào file tạm cùng thư mục rồi `os.replace`; `ffmpeg` lỗi → stage `failed`, `error` = clip + dòng cuối stderr ffmpeg.
  - **R7 Font (CP1 §4, P2):** ứng viên OFL hỗ trợ đủ dấu tiếng Việt: **Be Vietnam Pro**, **Noto Sans**, **Roboto** (bản OFL hiện hành). Tải TTF tĩnh từ repo chính thức (`github.com/google/fonts` hoặc repo của font), ghi URL + commit/phiên bản + sha256. Render ảnh so sánh (mỗi font: một khung thật từ video test, header thật, 2 title thật — một ngắn, một dài nhất — đặt cạnh ảnh mẫu) gửi HUMAN LEAD; HUMAN LEAD chốt font + weight. Chỉ font được chốt được commit: `src/auto_short/render/fonts/<file>.ttf` + `OFL.txt` (package data). `font_file` (path trong package) + sha256 file font vào `config_hash`.
  - **R8 Vị trí output (P5):** `<output_dir>/<episode_id>/` với `[render] output_dir` mặc định `"output"` (CP1 §2), cấu hình thực thi như `workspace.dir` (không vào hash). `render_manifest.json` và `shorts/*.mp4` nằm ở đó; entry manifest episode (CP2 D5) ghi các path này **absolute** (file ngoài workspace). Vì `run_stage` của CP2 chỉ xóa artifact trong workspace, stage render tự dọn: trước khi chạy xóa `shorts/*.mp4` và `render_manifest.json` do lần render trước ghi (theo `render_manifest.json` cũ / artifact list trong manifest, chỉ file trong `<output_dir>/<episode_id>/`); lỗi giữa chừng → xóa mọi file đã ghi của lần chạy đó. Không sửa `run_stage` của CP2 (quyết định khi implement nếu cần hook nhỏ → báo ORCHESTRATOR trước).
  - **R9 Validation trước khi ghi `render_manifest.json` (vi phạm → `failed`):** mỗi clip của `clips.json` có đúng một entry, cùng thứ tự, `clip_id`/`candidate_id` khớp; entry `rendered` có file tồn tại và `ffprobe` cho 1080×1920, `h264`, `yuv420p`, fps đúng R6, `aac` 48 kHz, thời lượng video và audio đều lệch `duration` kế hoạch ≤ 0.1 s; `sha256` file khớp; entry `skipped` không có file; `segments` đúng R3; header/title dòng hiển thị ≤ 3 dòng, fit đúng R5.
  - **R10 Stage / resume / CLI** — dùng `run_stage` của CP2 nguyên trạng:
    - Yêu cầu `titling` = `done` và `clips.json`, `titles.json`, `candidates.json`, `metadata.json` tồn tại; chưa done → stage `failed` + `error`, không file.
    - `inputs` = `clips.json`, `titles.json`, `candidates.json`, `metadata.json` (relative + sha256) và media nguồn theo manifest `source` (hash cache CP2 D6).
    - `config_hash` = mọi key `[render]` trừ `output_dir`, `threads` + sha256 file font. Đổi config stage khác không chạy lại render.
    - `artifacts` = `render_manifest.json` + các mp4 (absolute, R8). Chạy lại titling/selection → render stale (D6).
    - CLI `auto-short render <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<rendered (<n>/<m> clips)|skipped (up to date)>\t<path render_manifest.json>`; stderr: font, layout, header (dòng + cỡ chữ), mỗi clip (title dòng + cỡ chữ, số segment, thời lượng, thời gian render), tổng, cảnh báo clip bỏ qua; exit code CP2 D8.
  - **R11 Schema v1** (thứ tự key cố định; giá trị minh họa):

    ```json
    // render_manifest.json
    {"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
     "source_sha256": "<manifest source.sha256>",
     "clips_sha256": "<sha256 canonical JSON clips.json>",
     "titles_sha256": "<sha256 canonical JSON titles.json>",
     "candidates_sha256": "<sha256 canonical JSON candidates.json>",
     "render_config_hash": "<config_hash R10>",
     "title_source": "titles",
     "font": {"family": "…", "file": "fonts/….ttf", "sha256": "…"},
     "layout": {"width": 1080, "height": 1920, "background": "#000000", "panel_color": "#FEDB00",
                "header_panel": {"x": 113, "y": 55, "w": 853, "h": 292, "radius": 32},
                "video": {"x": 0, "y": 352, "w": 1080, "h": 1210, "crop": {"w": 964, "h": 1080, "x": 238, "y": 0}},
                "title_panel": {"x": 103, "y": 1573, "w": 875, "h": 292, "radius": 32}},
     "encode": {"vcodec": "libx264", "crf": 18, "preset": "medium", "pix_fmt": "yuv420p", "fps": "30000/1001",
                "acodec": "aac", "sample_rate": 48000, "channels": 2, "audio_bitrate": "192k"},
     "header": {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
                "display_lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo", "Kinh (tập 9)"], "font_size": 52},
     "stats": {"clips": 13, "rendered": 13, "skipped": 0, "seconds": 826.196},
     "shorts": [{"clip_id": "k01", "candidate_id": "c00123", "status": "rendered", "skip_reason": null,
                 "file": "shorts/k01.mp4", "sha256": "…", "title": "…",
                 "title_display_lines": ["…", "…", "…"], "title_font_size": 68,
                 "layout": {"header_panel": {…}, "video": {…}, "title_panel": {…}},
                 "source_start": 77.372, "source_end": 124.9, "segments": [[77.372, 80.1]], "duration": 38.379}]}
    ```

    - `layout` cấp gốc là layout mẫu (title panel cao mẫu); `shorts[].layout` là layout thật của clip (khác gốc khi panel title cao thêm, P3).
    - Số pixel/cỡ chữ ở trên là minh họa (tính từ tỉ lệ R4: khối 292 + 5 + 1210 + 11 + 292 = 1810 px, lề trên 55 px); giá trị thật do công thức + đo ảnh mẫu khi implement.
    - `file` relative theo thư mục output của episode; `shorts` cùng thứ tự/số phần tử với `clips.json.clips`; `stats.seconds` = Σ `duration` clip `rendered`.
- Đề xuất HUMAN LEAD đã chốt (cùng APPROVE TASK):
  - Các P dưới đây: P1, P2, P4, P5 chốt theo đề xuất (APPROVE TASK 2026-09-27); P3 chốt theo phương án sửa.
  - **P1 Nguồn title trước CP9.** CP6 G5 ghi "CP7 render dùng title đã duyệt, không đọc thẳng `titles.json`", nhưng `review.json` (CP9) chưa có; CP1 §8: MVP mặc định render mọi clip AI chọn, auto-approve chỉ là config explicit. Đề xuất: `[render] title_source = "titles"` (giá trị duy nhất ở CP7, ghi rõ trong `config.example.toml` là auto-approve title AI; CP9 thêm `"review"` và đổi mặc định) — header + title lấy từ `titles.json`, ghi `title_source` ở `render_manifest.json`; sửa pointer CP6 G5 theo đó. Phương án khác: chặn CP7 cho tới CP9 (không khả thi cho CP8); tạo `review.json` tối thiểu ngay ở CP7 (lấn scope CP9).
  - **P2 Font:** 3 ứng viên R7; HUMAN LEAD chốt sau khi xem ảnh so sánh (trong vòng thực thi, như chốt model ở CP5/CP6). Phương án thêm: Montserrat / Inter nếu cả ba chưa giống mẫu.
  - **P3 Fit title dài — chốt (HUMAN LEAD 2026-09-27):** panel title **cao thêm trước** để giữ cỡ chữ mẫu ở 3 dòng; không đủ (quá `title_panel_max_height` hoặc > 3 dòng) mới thu nhỏ chữ (R5). Sửa CP1 §4 theo đó (chiều cao title panel 0.27 W là tối thiểu, không cố định). Đề xuất ban đầu (panel cố định, chỉ thu nhỏ) không chọn.
  - **Chốt sau phase 1 (HUMAN LEAD 2026-09-27, theo đề xuất ORCHESTRATOR, số đo ảnh mẫu trong Result/decision record):**
    - **P2 font:** **Be Vietnam Pro Regular** (google/fonts `23e54b5`, v1.002, sha256 `cd1ef6e9…4b4fe4c3`).
    - **Ngắt dòng header:** kiểu lấp đầy dòng trên (greedy) như ảnh mẫu ("Thập Thiện Nghiệp Đạo / Kinh (tập 9)"); title giữ ngắt cân (R5) + tie-break phụ tránh dòng đầu quá ngắn (tổng bình phương phần thiếu nhỏ nhất). Sửa R5 theo đó.
    - **Lề khung:** `min_frame_margin` 0.02 W (22 px) → `title_panel_max_height` ≈ 358 px (một tham số suy ra từ tham số kia, không đặt cả hai độc lập).
    - Quyết định ORCHESTRATOR trong boundary: lề trong panel tách ngang/dọc; bo góc 0.055 W; cỡ chữ theo x-height đo (header 0.0330 W, title 0.0434 W); bước dòng ≈ 1.05× cỡ chữ; căn giữa dọc theo khối cap-height (OS/2 `sCapHeight`).
  - **Sửa P4 (HUMAN LEAD 2026-09-27, sau xem mẫu):** `crf` **22** thay cho 18 (đo 60 s video k03: 18 → 19 MB, 20 → 15 MB, 22 → 11 MB, 23 → 10 MB).
  - **Fade ở điểm nối (HUMAN LEAD 2026-09-27):** làm 1 mẫu thử (A/B cùng clip, có/không fade audio ngắn) để nghe; chưa vào scope CP7 cho tới khi HUMAN LEAD quyết sau khi nghe.
  - **P4 Encode:** `crf` 18 / `preset` medium / AAC 192k (R6). Phương án khác: `crf` 20–23 (file nhỏ hơn), `preset` slow.
  - **P5 Output:** `output/<episode_id>/` ngoài workspace theo CP1 §2 (R8). Phương án khác: render vào `work/<id>/shorts/` (đúng hoàn toàn CP2, không cần tự dọn) rồi copy sang `output/` ở CP8.

## Implementation approach

- `render/text.py`: đọc TTF (`cmap` format 4/12, `hmtx`, `head.unitsPerEm`), bề rộng chuỗi NFC; ngắt dòng cân + fit (R5). Test bằng font đã commit (không cần ffmpeg).
- `render/plan.py`: `segments` (R3), layout pixel (R4), dựng filter graph / tham số ffmpeg (thuần, test được bằng so chuỗi/cấu trúc).
- `render/stage.py`: đọc + kiểm input, lặp clip, gọi `ffmpeg` qua `subprocess` (inject được trong test), `ffprobe` kiểm output (R9), tự dọn output (R8), ghi `render_manifest.json`; `run_stage` CP2 nguyên trạng.
- Font: trong vòng thực thi, trước khi commit font — tải 3 ứng viên vào thư mục tạm (ngoài repo), render ảnh so sánh, dừng hỏi HUMAN LEAD chốt (P2), rồi mới commit font được chọn.
- Test tích hợp: video lavfi `testsrc2` 1440×1080 29.97 fps + `sine` ~8 s, `candidates.json`/`clips.json`/`titles.json` tối thiểu có `head_cut` + trim bị cắt ngang; kiểm ffprobe, thời lượng, skip, stale, lỗi ffmpeg, clip `untitled`.
- Tái dùng: `hashing`, `workspace`, `config`, pattern CLI hiện có; `selection`/`titling` chỉ import hàm dùng lại (nếu cần), không sửa code CP5/CP6.

## Acceptance Criteria

1. `auto-short render rbjfCfFq3Dk` sinh `output/rbjfCfFq3Dk/shorts/k01.mp4 … k13.mp4` và `render_manifest.json` đúng schema R11; manifest episode có stage `render` `done`; `status` hiển thị `render done`.
2. Mọi mp4: 1080×1920, `h264` `yuv420p`, fps 29.97 (nguồn ≤ 30), `aac` 48 kHz stereo; thời lượng video và audio lệch `clip.duration` ≤ 0.1 s (R9).
3. `segments` mỗi clip đúng R3: bắt đầu tại `clip.source_start` (kể cả 2 clip `head_cut`), trim bị cắt ngang được tính đúng, `Σ` = `clip.duration` ≤ 1 ms; test đơn vị cho trim trước/giao/sau `source_start`.
4. Layout đúng R4 (tọa độ trong `render_manifest.json` khớp công thức; test đơn vị) và **so sánh trực quan với ảnh mẫu được HUMAN LEAD chấp nhận** (CP1 §4 acceptance) — ảnh cạnh nhau: khung render thật vs ảnh mẫu.
5. Chữ header + title: đủ dấu tiếng Việt, ≤ 3 dòng, không chạm/tràn mép panel — kiểm tự động trên khung trích từ mp4 (các hàng/cột pixel sát mép trong panel là màu panel) cho cả 13 clip + header; title dài nhất (51 ký tự) và ngắn nhất (28 ký tự) đúng rule fit R5 (title 3 dòng: panel cao thêm, giữ cỡ chữ mẫu nếu vừa `title_panel_max_height`); khối nội dung căn giữa theo `shorts[].layout`.
6. Font đã chốt (P2) được commit cùng `OFL.txt`, nạp từ package (không dựa fontconfig/font hệ thống); sha256 font nằm trong `config_hash`.
7. Resume: chạy lại không đổi → `skipped (up to date)`, không gọi ffmpeg, `render_manifest.json` byte-identical; đổi key `[render]` trong hash → chạy lại; `output_dir`/`threads` không; chạy lại titling (`--force`) → render `stale`.
8. Determinism: render lại (`--force`) cùng input/config trên cùng máy → `render_manifest.json` byte-identical và sha256 mọi mp4 không đổi (nếu x264/muxer không byte-stable thì chứng minh bằng `framemd5` video + audio giống nhau và ghi lại lý do — báo ORCHESTRATOR trước khi nới AC).
9. Clip `untitled` không được render, ghi `skipped`/`untitled` + cảnh báo; `clips: []` → `done`, không mp4 (test).
10. Lỗi (titling chưa done, sha lệch, `Σ segments` lệch, glyph thiếu, fit dưới `min_font_scale`, ffmpeg lỗi) → stage `failed` + `error` rõ, không để lại mp4/manifest render dở trong `output/<id>/`; exit 1 (test).
11. Không thêm dependency Python; không sửa code/test CP2–CP6 ngoài đăng ký CLI/config (`cli.py`, `config.py`); `pytest` toàn bộ PASS; `node scripts/framework-check.mjs` PASS.
12. Docs cập nhật theo Scope (decision record ACCEPTED sau review, CP1 §4 font + rule fit, CP6 G5 pointer theo P1, project profile, README, current-state).

## Required verification

- `conda run -n auto-short pytest -q` — AC3, AC5 (logic fit), AC7, AC9, AC10, AC11.
- `conda run -n auto-short auto-short render rbjfCfFq3Dk` (sau khi chốt font) + `ffprobe` từng mp4 — AC1, AC2.
- Script kiểm độc lập (không import `auto_short`): đọc `clips.json`/`candidates.json`/`titles.json`/`render_manifest.json`, tự dựng lại `segments` và sha256 input, ffprobe từng file, trích khung giữa mỗi mp4 (`ffmpeg -ss … -frames:v 1 -f rawvideo rgb24`) và kiểm mép panel + nền đen ngoài khối nội dung — AC1–AC5.
- Chạy lại không đổi → skip + so sha256 manifest; `--force` → so sha256 mp4 (hoặc `framemd5`) — AC7, AC8.
- Ảnh so sánh font (P2) và ảnh render thật cạnh ảnh mẫu + 2–3 mp4 mẫu (có `head_cut`, title 3 dòng) gửi HUMAN LEAD — AC4, AC6.
- `node scripts/framework-check.mjs` — AC11, AC12.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract. Manual test ở CP7 là **gate** cho AC4 (so sánh trực quan với ảnh mẫu là acceptance theo CP1 §4) và chốt font (P2); phần còn lại là điểm danh sau automated verification.

- [ ] Chọn font từ ảnh so sánh (P2).
- [ ] Xem ảnh render thật cạnh ảnh mẫu: tỉ lệ panel, bo góc, màu, cỡ chữ, vị trí video (AC4).
- [ ] Xem/nghe 2–3 Short (có `head_cut`, title 3 dòng): chữ rõ, đủ dấu; điểm rút lặng không giật/lộp bộp khó chịu; tiếng/hình khớp.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
