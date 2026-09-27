# CP7 — Short Composition / Renderer Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (R1–R11, P1–P5 duyệt cùng APPROVE TASK 2026-09-27, P3 sửa; font, ngắt dòng header, lề khung HUMAN LEAD 2026-09-27 sau phase 1; sửa P4 `crf` 22; AC4 chấp nhận (cắt thẳng); chuyển cảnh video → CP10; review ACCEPTED). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.1, APPROVE TASK V1–V6, P1, P2): dissolve video 0.15 s ở điểm nối (R6, R11, § Chuyển cảnh). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.2, APPROVE TASK T1–T6): title override `review.json`, tái dùng từng Short (R2, R6, R8, R10, R11). Sửa đổi HUMAN LEAD 2026-09-27 (CP8.5, APPROVE TASK X2): Short bị xóa `skip_reason: "rejected"` (R2, R11) |
| Checkpoint | CP7 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP7 |
| Task contract | `docs/tasks/CP7-render.md`; sửa đổi CP8.1: `docs/tasks/CP8.1-dissolve.md`; sửa đổi CP8.2: `docs/tasks/CP8.2-title-override.md`; sửa đổi CP8.5: `docs/tasks/CP8.5-web-review.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §2, §4, §5, §7, §8, §10; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP4-analysis-contract.md` A8; `docs/decisions/CP5-selection-contract.md` B11; `docs/decisions/CP6-titling-contract.md` G2, G5, G6, G7 |

File này là **canonical owner** của layout pixel, font đóng gói, đo chữ / ngắt dòng / fit, cách dựng lệnh `ffmpeg`, vị trí output và schema `render_manifest.json` mà CP8 (end-to-end) và CP9 (review) dùng lại. Nơi khác chỉ trỏ tới đây. Layout mẫu và tỉ lệ gốc: `docs/decisions/CP1-product-contract.md` §4; stage framework (manifest v1, skip/stale, config hash, CLI exit code): `docs/decisions/CP2-workspace-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/render/` (`text.py`, `plan.py`, `stage.py`, `fonts/`).

## R1. Stage / artifact

- Stage `render` (CP1 §8), subpackage `src/auto_short/render/`.
- Artifact: `<output_dir>/<episode_id>/shorts/<clip_id>.mp4` + `<output_dir>/<episode_id>/render_manifest.json` (R8). `render_manifest.json` ghi atomic, không timestamp (CP2 D5).

## R2. Clip được render, nguồn title

- Mọi clip của `clips.json` có title — entry `titles.json` `status = titled` **hoặc** override hợp lệ trong `review.json` (CP8.2) — theo thứ tự `clips.json`. Clip `untitled` không override → `status: "skipped"`, `skip_reason: "untitled"`, không file, cảnh báo stderr (CP6 G6). `clips: []` hoặc không clip nào có title → stage `done`, không mp4, cảnh báo.
- Nguồn title/header (P1): `[render] title_source = "titles"` — giá trị duy nhất, nghĩa là auto-approve title AI (CP1 §8); header + title đọc từ `titles.json`, `title_source` ghi ở `render_manifest.json`. CP9 thêm `"review"`.
- **Sửa đổi CP8.2:** title của clip = override `review.json` hợp lệ > `titles.json` `title`; khóa override, cảnh báo override bị bỏ qua, `title_origin`: canonical ở `docs/decisions/CP8.2-title-override-contract.md` T3–T4.
- **Sửa đổi CP8.5** (HUMAN LEAD 2026-09-27): clip bị xóa trong `review.json` (`rejected`) → `status: "skipped"`, `skip_reason: "rejected"`, không file (mp4 cũ bị xóa ở bước commit), ưu tiên hơn `untitled`; log INFO, không cảnh báo. `skip_reason` ∈ `untitled` | `rejected` (R9 kiểm). Canonical: `docs/decisions/CP8.2-title-override-contract.md` T7.

## R3. Đoạn giữ lại

- Tính bằng millisecond nguyên (CP4 A8): đoạn `[clip.source_start, clip.source_end]` trừ các `trims` của candidate (`candidates.json` theo `candidate_id`) giao đoạn đó; trim bị `source_start`/`source_end` cắt ngang chỉ tính phần trong đoạn (CP5 B11 "Cho CP7"); đoạn độ dài 0 bị bỏ. `segments` = `[a, b]` giây, tăng dần, không chồng nhau.
- `Σ (b − a)` phải bằng `clip.duration` (±1 ms), nếu không → `failed` ("data inconsistent, re-run analysis/selection"). `clips.json.candidates_sha256` và `titles.json.clips_sha256` / `candidates_sha256` phải khớp sha256 canonical JSON của input đã đọc; entry `titles.json` phải khớp `clips.json` (id, `candidate_id`, thứ tự) — nếu không → `failed`.

## R4. Layout

Khung 1080×1920, nền `#000000`, panel `#FEDB00` (CP1 §4). Mọi tỉ lệ là key `[render]` theo W = 1080 (mặc định trong ngoặc; px = `round(tỉ lệ × W)`):

| Thành phần | Mặc định | px |
|---|---|---|
| Header panel | rộng `header_panel_width` 0.79, cao `header_panel_height` 0.27 (cố định) | 853 × 292 |
| Khe header → video | `gap_header_video` 0.005 | 5 |
| Video | full W, cao `video_height` 1.12 (làm tròn lên số chẵn) | 1080 × 1210 |
| Khe video → title | `gap_video_title` 0.01 | 11 |
| Title panel | rộng `title_panel_width` 0.81, cao tối thiểu `title_panel_height` 0.27 (P3: cao thêm tới `title_panel_max_height`) | 875 × 292…358 |
| Bo góc panel | `panel_radius` 0.055 (đo từ ảnh mẫu) | 59 |
| Lề khung tối thiểu | `min_frame_margin` 0.02 | 22 |

- `title_panel_max_height` **không phải key**: suy ra = `1920 − 2 × min_frame_margin − (header + khe + video + khe)` = 358 px (HUMAN LEAD 2026-09-27: một tham số).
- Panel căn giữa ngang (`x = (1080 − w) // 2`); khối nội dung (header + video + title) căn giữa dọc (`top = (1920 − khối) // 2`) → layout tính **theo từng clip** (title panel cao thêm thì khối dịch lên). Mặc định: title 292 → top 55; title 353 → top 24; title 358 → top 22.
- Video: crop giữa nguồn theo tỉ lệ 1080:1210 (nguồn rộng hơn → cắt ngang, ngược lại → cắt dọc; kích thước chẵn) rồi scale lanczos về 1080×1210. Nguồn 1440×1080 → crop 964×1080 tại x 238.
- Không vẽ gì ở vùng đen còn lại (subtitle tắt, CP1 §7).
- Bo góc: alpha panel `255 × clip(r − d + 0.5, 0, 1)` với `d` = khoảng cách tới cung góc (khử răng cưa 1 px).

## R5. Chữ: đo, ngắt dòng, fit

- Font: **Be Vietnam Pro Regular** (R7). Bề rộng = tổng advance `hmtx` (qua `cmap` format 4/12, `head.unitsPerEm`) của chuỗi NFC, đọc bằng `struct` (không dependency). Ký tự không có glyph → `failed` (lỗi cấu hình font).
- `ffmpeg drawtext` shape bằng HarfBuzz (kerning), rộng hơn tổng `hmtx` tối đa 0.5 % (đo trên header + 13 title ở 67/88 px). Ngắt dòng so với bề rộng trong × (1 − 0.01) (hằng `WIDTH_SAFETY` trong code).
- Cỡ chữ mẫu: `header_font_size` 0.062 W = **67 px**, `title_font_size` 0.0815 W = **88 px** — suy từ x-height đo trên ảnh mẫu (0.0330 W / 0.0434 W) chia x-height Be Vietnam Pro (530/1000). Title ≈ 1.33× header.
- Bước dòng = `line_spacing` 1.05 × cỡ chữ (70.35 / 92.4 px; ảnh mẫu 0.0651 W / 0.0868 W = 70.3 / 93.75 px).
- Lề trong panel: ngang `panel_padding_x` 0.03 W (32 px), dọc `panel_padding_y` 0.035 W (38 px). Bề rộng trong = panel − 2 × padding_x. Khối chữ n dòng cần `n × bước dòng + 2 × padding_y`. (0.04 W ngang như đề xuất phase 1 không cho dòng mẫu "Thập Thiện Nghiệp Đạo" (769 px ở 67 px) vừa panel 853 → ảnh mẫu tự không tái hiện được; 0.03 W tái hiện đúng.)
- Ngắt dòng chỉ tại khoảng trắng, so trong đơn vị font (số nguyên → tie chính xác):
  - **Header** (HUMAN LEAD 2026-09-27): mỗi dòng logic của `titles.json.header.lines` ngắt kiểu **lấp đầy dòng trên** (greedy) như ảnh mẫu → `HT.Tịnh Không / Thập Thiện Nghiệp Đạo / Kinh (tập 9)`.
  - **Title**: ngắt **cân** — ít dòng nhất, rồi dòng dài nhất ngắn nhất, rồi tie-break tổng bình phương phần thiếu `Σ (bề rộng trong − bề rộng dòng)²` nhỏ nhất (tránh dòng đầu quá ngắn).
- Fit **header**: panel cố định; từ cỡ mẫu giảm 1 px tới khi tổng dòng ≤ 3 và khối vừa panel; dưới `ceil(min_font_scale × cỡ mẫu)` (0.6) → `failed`. Fit một lần cho episode.
- Fit **title** (P3):
  1. Ở cỡ mẫu, ngắt cân (≤ 3 dòng). Nếu có cách ngắt và khối cần ≤ `title_panel_max_height`: panel = `max(title_panel_height, ceil(khối cần))` — 2 dòng giữ 292 px, 3 dòng ở 88 px cần 353 px.
  2. Ngược lại: panel = `title_panel_max_height`, giảm cỡ 1 px tới khi ≤ 3 dòng và vừa.
  3. Dưới `ceil(min_font_scale × cỡ mẫu)` → `failed` (không cắt chữ).
- Vị trí dọc: khối cap-height (đỉnh chữ hoa dòng đầu tới baseline dòng cuối, OS/2 `sCapHeight`) căn giữa trong panel (như ảnh mẫu, lệch ≤ 2 px @576); baseline từng dòng làm tròn px, vẽ bằng `drawtext y_align=baseline`. Ngang: mỗi dòng căn giữa theo bề rộng đã shape (`x = (w − text_w)/2`).
- Dòng hiển thị + cỡ chữ ghi ở `render_manifest.json` (`header.display_lines`/`font_size`, `shorts[].title_display_lines`/`title_font_size`).

## R6. Render (một lệnh `ffmpeg` mỗi clip)

- Input seek `-ss (đầu đoạn đầu − 1 s) -t … -copyts` (giữ timestamp tuyệt đối của nguồn), decode rồi chọn, không stream-copy.
- Video: `fps=<fps ra>` đưa frame lên lưới tuyệt đối `k / fps`; mỗi segment lấy `n_k` frame liên tiếp từ frame `round(a × fps)`, với `n_k` = hiệu của `round(thời gian ra cộng dồn × fps)` → video lệch audio ≤ nửa frame dù nhiều segment; `select` + `setpts=N/fps/TB`; crop + scale (R4); đệm lên 1080×1920 nền đen.
- Chuyển cảnh video ở điểm nối (**sửa đổi HUMAN LEAD 2026-09-27, CP8.1**; trước đó cắt thẳng): `[render] dissolve` (giây, mặc định 0.15; `0` = cắt thẳng; trong `config_hash`). Theo frame, deterministic:
  - `e = round(dissolve × fps / 2)` frame mỗi phía (0.15 s @ 29.97 → e = 2). Điểm nối j (giữa segment j và j+1): `gap` = số frame lưới bị trim giữa `first_j + n_j` và `first_{j+1}`; `e_j = max(0, min(e, gap // 2, n_j // 2, n_{j+1} // 2))`; `D_j = 2 e_j`. Segment j lấy thêm `e_j` frame sau, segment j+1 thêm `e_j` frame trước — lấy từ phần khoảng lặng bị trim, không bao giờ ra ngoài `[source_start, source_end]` (segment đầu không kéo về trước, segment cuối không kéo về sau). Kẹp `n // 2` (quyết định khi implement, ngoài V2): mỗi segment cho mỗi phía tối đa nửa số frame của nó → hai cửa sổ dissolve liên tiếp không chồng nhau; chỉ có tác dụng với segment ngắn hơn 2e frame (không có ở video test).
  - Nhánh video: `split` → mỗi segment `trim=start_pts=first − e_in:end_pts=first + n + e_out` (sau `fps=` pts là chỉ số lưới, time base 1/fps → đúng các frame `select` `[first − e_in, first + n + e_out − 1]` sẽ lấy) + `setpts=PTS-STARTPTS` + crop/scale/đổi màu (per frame) → nối trái sang phải bằng `xfade=transition=fade` dài `D_j` frame, `offset` = (độ dài tích lũy − D_j)/fps (`D_j = 0` → `concat`) → `setpts=N/fps/TB` → `pad`. Tổng frame = tổng `n_k` (như cắt thẳng); cửa sổ dissolve là D_j frame giữa hai bên điểm nối; frame đầu cửa sổ `xfade` vẫn 100 % segment trước, nên phần hòa trộn thật là D_j − 1 frame (3/4, 1/2, 1/4 với D = 4).
  - Không điểm nối nào có `D_j > 0` (`dissolve = 0`, 1 segment, mọi gap < 2 frame) → filter graph **y hệt** cắt thẳng ở trên (mp4 byte-identical bản CP7).
  - Audio vẫn cắt thẳng (không đổi).
- Audio: `asplit` + `atrim` từng segment theo giây tuyệt đối (chính xác tới sample) + `concat`, 48 kHz stereo. Không fade/crossfade (điểm nối nằm trong khoảng lặng, CP4 A8).
- Panel + chữ: mỗi panel là một frame RGBA (`color` + `geq` alpha bo góc + `drawtext` từng dòng với `fontfile` đóng gói, `textfile`, `expansion=none`, `text_shaping=1`), đổi sang YUV BT.709 rồi `overlay` (lặp frame cuối) lên video trong YUV 4:4:4; cuối cùng `yuv420p`. Đường dẫn trong filter graph được escape hai tầng; graph qua `-filter_complex_script`.
- Encode (P4, **sửa P4** HUMAN LEAD 2026-09-27 sau xem mẫu: `crf` 22 thay 18; đo 60 s video `k03`: crf 18 → 19 MB, 20 → 15 MB, 22 → 11 MB, 23 → 10 MB): `libx264` `crf` 22, `preset` medium, `yuv420p`, gắn BT.709 tv-range; fps giữ nguồn nếu ≤ 30, ngược lại 30; AAC 192 kb/s 48 kHz stereo; `+faststart`; `-fflags/-flags +bitexact`, bỏ metadata/chapter nguồn. `threads` (thực thi, không vào hash).
- Ghi `.<clip_id>.mp4.part` cùng thư mục, `ffprobe` kiểm (R9), rồi `os.replace` — **sửa đổi CP8.2:** `os.replace` dời tới bước commit sau khi mọi clip xong (R8). `ffmpeg` lỗi → `failed`, `error` = `clip <id>: ffmpeg failed: <dòng cuối stderr>`.

## R7. Font

- **Be Vietnam Pro Regular** v1.002 (OFL 1.1), từ `google/fonts` commit `23e54b51ddffbc7713c583748e3bd86f62b1fa4a`, `ofl/bevietnampro/BeVietnamPro-Regular.ttf`; sha256 `cd1ef6e9d7db28ad5cdb88a65ccbe693870e60d340b791f349d248342b4fe4c3`. Commit tại `src/auto_short/render/fonts/BeVietnamPro-Regular.ttf` + `fonts/OFL.txt` (sha256 `6b7f8f73…2a85`, cùng commit google/fonts); ship trong wheel (package data).
- `[render] font_file` = path trong package `auto_short.render` (mặc định `fonts/BeVietnamPro-Regular.ttf`, không absolute, không `..`); sha256 file font vào `config_hash`. Không dùng fontconfig / font hệ thống.
- Chọn font (P2, HUMAN LEAD 2026-09-27) trên 3 ứng viên OFL (Be Vietnam Pro, Noto Sans v2.015, Roboto v3.016; Regular + Medium): cùng x-height, bề rộng dòng Be Vietnam Pro khớp ảnh mẫu 0.94–1.02×, Noto 0.90–0.94×, Roboto 0.88–0.93×; nét chữ (stem 4/5 px @576) khớp Regular.

## R8. Output

- `<output_dir>/<episode_id>/`, `[render] output_dir` mặc định `"output"` (CP1 §2, `.gitignore`), thực thi (không vào hash) như `workspace.dir`. Entry manifest episode ghi path artifact **absolute** (file ngoài workspace).
- `run_stage` của CP2 dùng nguyên trạng; stage tự dọn, chỉ file nằm trong `<output_dir>/<episode_id>/`. File của lần render trước = artifact của entry `render` trong manifest + file liệt kê trong `render_manifest.json` cũ + chính nó.
- **Sửa đổi CP8.2** (thay luật cũ "trước khi chạy xóa mọi file của lần render trước; lỗi ở bất kỳ bước nào → xóa mọi file render của episode"): Short có `render_key` không đổi được tái dùng; Short encode giữ ở `.part` tới khi mọi clip xong, rồi commit (thay file, xóa file cũ không còn thuộc lần này, ghi `render_manifest.json`); lỗi chỉ xóa file lần chạy đó đã ghi, output thành công trước giữ nguyên. Canonical: `docs/decisions/CP8.2-title-override-contract.md` T5.
- Đổi `output_dir` không chạy lại stage (artifact cũ vẫn ở chỗ cũ); muốn render sang chỗ mới dùng `--force`.

## R9. Validation trước khi ghi `render_manifest.json` (vi phạm → `failed`)

Kiểm trên trạng thái sau commit (CP8.2 T5: file của Short encode lần này đọc ở `.part`, file cũ sắp xóa coi như không còn). Mỗi clip của `clips.json` có đúng một entry, cùng thứ tự, `clip_id`/`candidate_id` khớp; `segments` bằng R3 tính lại và `duration` = `clip.duration`; entry `rendered`: file tồn tại, sha256 khớp, `title_origin` hợp lệ, `render_key` 64 ký tự hex, `ffprobe` cho 1080×1920 `h264` `yuv420p`, `r_frame_rate` = fps R6, `aac` 48 kHz 2 kênh, thời lượng video **và** audio lệch thời lượng kế hoạch ≤ 0.1 s, số frame video (`nb_frames`) = tổng `n_k` kế hoạch (CP8.1 V5), `dissolves` = kế hoạch R6 tính lại, title 1–3 dòng hiển thị; entry `skipped`: không file, `dissolves` = `null`, `render_key` = `null`; header ≤ 3 dòng hiển thị; `stats` nhất quán.

## R10. Stage / resume / CLI

- Yêu cầu `titling` = `done` và `clips.json`, `titles.json`, `candidates.json`, `metadata.json` tồn tại; không thì `failed` + `error`, không file.
- `inputs` = 4 file trên (relative + sha256) + `review.json` nếu có (CP8.2 T4) + media nguồn (hash cache CP2 D6).
- **Sửa đổi CP8.6:** episode đã dọn video nguồn (`archive.json`) → `render` từ chối trước khi đụng manifest (không ghi `failed`, render cuối giữ nguyên). Canonical: `docs/decisions/CP8.3-web-contract.md` W9.
- `config_hash` = mọi key `[render]` trừ `output_dir`, `threads`, cộng `font_sha256`. Đổi config stage khác không chạy lại render; chạy lại titling/selection → render `stale` (D6).
- `artifacts` = `render_manifest.json` + các mp4 (absolute).
- CLI `auto-short render <episode_id> [--force] [--config PATH]`; stdout `<episode_id>\t<rendered (<n>/<m> clips)|skipped (up to date)>\t<path render_manifest.json>`; stderr: font + fps + kích thước nguồn, layout mẫu, header (dòng + cỡ), mỗi clip (dòng title, cỡ, cao panel, số segment, thời lượng, thời gian render), tổng, cảnh báo clip bỏ qua; exit code CP2 D8.

## R11. Schema v1 `render_manifest.json`

Thứ tự key cố định:

```json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
 "source_sha256": "<manifest source.sha256>",
 "clips_sha256": "…", "titles_sha256": "…", "candidates_sha256": "…",
 "render_config_hash": "<config_hash R10>", "title_source": "titles",
 "font": {"family": "Be Vietnam Pro", "file": "fonts/BeVietnamPro-Regular.ttf", "sha256": "cd1ef6e9…"},
 "layout": {"width": 1080, "height": 1920, "background": "#000000", "panel_color": "#FEDB00",
            "header_panel": {"x": 113, "y": 55, "w": 853, "h": 292, "radius": 59},
            "video": {"x": 0, "y": 352, "w": 1080, "h": 1210, "crop": {"w": 964, "h": 1080, "x": 238, "y": 0}},
            "title_panel": {"x": 102, "y": 1573, "w": 875, "h": 292, "radius": 59}},
 "encode": {"vcodec": "libx264", "crf": 22, "preset": "medium", "pix_fmt": "yuv420p", "fps": "30000/1001",
            "acodec": "aac", "sample_rate": 48000, "channels": 2, "audio_bitrate": "192k", "dissolve": 0.15},
 "header": {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
            "display_lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo", "Kinh (tập 9)"], "font_size": 67},
 "stats": {"clips": 13, "rendered": 13, "skipped": 0, "seconds": 826.196},
 "shorts": [{"clip_id": "k03", "candidate_id": "c00361", "status": "rendered", "skip_reason": null,
             "file": "shorts/k03.mp4", "sha256": "…", "title": "Tâm thiện thì tướng mạo cũng từ bi",
             "title_display_lines": ["Tâm thiện thì", "tướng mạo", "cũng từ bi"], "title_font_size": 88,
             "layout": {"header_panel": {"x": 113, "y": 24, …}, "video": {"x": 0, "y": 321, …},
                        "title_panel": {"x": 102, "y": 1542, "w": 875, "h": 353, "radius": 59}},
             "source_start": 964.228, "source_end": 1087.32, "segments": [[964.228, 966.979], …], "duration": 98.612,
             "dissolves": [{"at": 2.736, "frames": 2}, {"at": 6.607, "frames": 4}, …],
             "title_origin": "ai", "render_key": "…"}]}
```

- `layout` gốc = layout mẫu (title panel 0.27 W); `shorts[].layout` = layout thật của clip. `fps` là phân số chuỗi.
- Entry `skipped`: `file`, `sha256`, `title_display_lines`, `title_font_size`, `layout` = `null`; `title` = title của `titles.json` (`null` khi `untitled`); `segments`/`duration` vẫn ghi. CP8.5: entry `skip_reason: "rejected"` ghi `title` / `title_origin` = title sẽ dùng khi khôi phục (override nếu có).
- `file` relative theo `<output_dir>/<episode_id>/`; `stats.seconds` = Σ `duration` clip `rendered` (3 chữ số).
- CP8.1 (additive, giữ `schema_version: 1`, P1): `encode.dissolve` = giây cấu hình (key cuối của `encode`); `shorts[].dissolves` (sau `duration`) = mỗi điểm nối một phần tử theo thứ tự, `at` = giây trên timeline video của Short tại điểm nối (frame đầu của segment j+1 / fps, 3 chữ số — tâm cửa sổ dissolve), `frames` = `D_j` (0 = cắt thẳng); clip 1 segment → `[]`; entry `skipped` → `null`.
- CP8.2 (additive, giữ `schema_version: 1`): sau `dissolves`, `shorts[].title_origin` = `"ai" | "manual" | "alternative"` (`null` cho clip `untitled` không override) và `shorts[].render_key` = sha256 hex (key cuối của entry; `null` khi `skipped`). `title` = title thật được render (override nếu có). Định nghĩa: `docs/decisions/CP8.2-title-override-contract.md` T4, T5.

## Số đo ảnh mẫu (`docs/decisions/assets/cp1-layout-reference.jpg`, 576×1280)

Đo trên kênh G, biên sub-pixel theo độ phủ; bo góc fit trên 8 góc.

| Thành phần | @576 | theo W | @1080 |
|---|---|---|---|
| Header panel | 457.98 × 155.05 (y 128.03–283.08) | 0.795 × 0.269 | 859 × 291 |
| Khe header → video | ≈ 1.2 | ≈ 0.002 | ≈ 2 |
| Video | cao ≈ 647.4 | 1.124 | 1214 |
| Khe video → title | 6.05 | 0.0105 | 11 |
| Title panel | 468.16 × 155.64 | 0.813 × 0.270 | 878 × 292 |
| Bán kính góc | 31.6–31.9 | 0.055 | 59–60 |
| Header chữ | x-height 19, cap 25, bước dòng 37.5 | 0.0330 / 0.0434 / 0.0651 | 35.6 / 46.9 / 70.3 |
| Title chữ | x-height 25, cap ≈ 33.5, bước dòng 50 | 0.0434 / 0.058 / 0.0868 | 46.9 / 62.8 / 93.75 |
| Màu panel | (254, 219, 0) | | `#FEDB00` |

Hình học R4 giữ mặc định đã duyệt (sai khác số đo ≤ 6 px @1080). Ảnh mẫu là khung 9:20 nên lề trên/dưới của nó không dùng; khối nội dung 1.676 W = 1810 px khớp.

## Quyết định khi implement

- Ngắt dòng làm trong đơn vị font nguyên; `WIDTH_SAFETY` 1 % cho kerning (đo ≤ 0.5 %).
- `panel_padding_x` 0.03 W (không phải 0.04 W) để header mẫu tái hiện đúng (R5).
- Lưới frame tuyệt đối + đếm frame theo thời gian cộng dồn (R6) thay vì `trim` theo giây từng segment (sai số ±1 frame/segment cộng dồn với clip 22 segment).
- Dựng panel một frame rồi `overlay` lặp (không `geq`/`drawtext` mỗi frame); ghép trong YUV 4:4:4 + ma trận BT.709 cho panel (tránh lệch màu BT.601 mặc định của swscale).
- `-fflags/-flags +bitexact`, bỏ metadata nguồn: render lại cùng input/config/máy → mp4 byte-identical (đo: 13/13 + `render_manifest.json`).
- CP8.1: nhánh dissolve dùng `trim` thay `select` (V3 cho phép cách tương đương): `select` chỉ kết thúc khi hết input nên `concat`/`xfade` chờ EOF của nhánh trước và giữ frame (4:4:4 1080×1210) của mọi segment sau trong bộ nhớ — đo `k03` (22 segment): đỉnh RSS 13.7 GB với `select`, 2.6 GB với `trim` (cắt thẳng 2.0 GB); frame ra trùng hash từng frame (framemd5 `k04`), packet mã hóa trùng.

## Chuyển cảnh ở điểm nối (HUMAN LEAD 2026-09-27)

- Audio: cắt thẳng, **không fade** (nghe A/B `k04` với fade 15 ms: không khác; bước nhảy tại điểm nối đo trên PCM −66 … −82 dBFS, ngang nhiễu nền).
- Video: CP7 giữ **cắt thẳng** (AC4 chấp nhận). Đã thử trên `k04` (scratch, không vào `src/`): dissolve 0.25 / 0.5 / 0.15 s (kéo dài mỗi segment vào phần khoảng lặng bị trim, `xfade=fade`, số frame + audio giữ nguyên; trim ngắn hơn độ dài dissolve thì kẹp, trim 1 frame giữ cắt thẳng) và zoom luân phiên 1.12× ("punch-in"). Nhược điểm quan sát: dissolve dài lộ bóng mặt chồng khi người giảng đổi tư thế, chữ Hán burn-in chồng nhau; zoom làm mềm ảnh và đổi khung ở mọi điểm nối.
- **HUMAN LEAD chọn dissolve 0.15 s (≈ 4 frame) và để làm ở CP10**, không đưa vào CP7. CP10 dùng lại cách kéo dài vào khoảng lặng bị trim nêu trên.
- **Sửa đổi HUMAN LEAD 2026-09-27 (CP8.1):** re-plan kéo dissolve từ CP10 lên CP8.1 (`docs/tasks/CP8.1-dissolve.md`, V1–V6); bật mặc định `[render] dissolve = 0.15` (P2). Rule canonical ở R6 (kế hoạch + filter graph), R9 (V5), R11 (schema). Audio giữ cắt thẳng.

## Giới hạn đã biết

- H.264 4:2:0: cạnh panel/video ở tọa độ lẻ (khe 5 và 11 px, title 353 px) để lại viền màu 1 px ngay ngoài cạnh, biên độ ≤ 21/255 — không thấy bằng mắt; kiểm độc lập bỏ qua đúng 1 px sát cạnh, phần nền đen còn lại ≤ 15/255.
- Không xét SAR khác 1 của nguồn (pixel không vuông); nguồn test SAR 1.
- `min_frame_margin` 0.02 W: trên video test title 46–49 ký tự vẫn 3 dòng ở 88 px; hai title 51 ký tự (`k01`, `k02`) không ngắt được ≤ 3 dòng ở 88 px nên panel 358 px và thu nhỏ còn 85 / 86 px.
- Title không vừa 2 dòng ở 88 px (từ ≈ 34–36 ký tự, tùy chữ) sang 3 dòng; ngắt cân khi đó có thể cho 3 dòng ngắn (vd. "Tâm thiện thì / tướng mạo / cũng từ bi"). Không có luật "thu nhỏ để giữ 2 dòng" (P3 chọn panel cao thêm trước). 9/13 title test là 3 dòng.
