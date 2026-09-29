# Task: CP8.14 — Bố cục Short: video lớn, title nổi trên đáy video, tránh giao diện YouTube Shorts

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `fc19e28` (`origin/main`, sau merge PR #27) / `feature/cp8.14-title-layout` (worktree `../youtube-auto-short-cp814`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE; phương án **V16** chốt sau 6 vòng mẫu; L2–L6 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi layout đã duyệt ở `docs/decisions/CP1-product-contract.md` §4 (product contract, layout theo ảnh mẫu) và `docs/decisions/CP7-render-contract.md` R4 / R5 / R11 (canonical owner layout pixel + fit title), đổi mặc định + thêm / bỏ key `[render]`, đổi `render_key` của mọi Short (tập cũ chạy lại sẽ render lại). Không đổi security model, API web, job model, dependency, schema `render_manifest.json` (vẫn v1, cùng key).

## Vấn đề

Layout hiện tại đặt title panel ở y 1573–1865 (title 2 dòng) / 1542–1895 (3 dòng). Trên app YouTube, người xem thấy title bị giao diện Shorts đè (tên kênh, mô tả, nút Share / Remix).

Vùng bị che, đo từ ảnh chụp của HUMAN LEAD 2026-09-29 (xem Short từ **tài khoản khác**, điện thoại 923×2000; khung Short hiện ở tỉ lệ 0.92, cắt ≈ 38 px mỗi bên), quy về khung 1080×1920:

| Vùng | Khung 1080×1920 |
|---|---|
| Hàng tên kênh / mô tả / ngày (đáy) | y ≥ ≈ 1625 |
| Cột nút phải (thích, bình luận, Save, Share, Remix) | x ≥ ≈ 905, y ≥ ≈ 990 |
| Nút ← / tìm kiếm / ⋮ (trên) | y ≈ 40–95, ở hai góc |
| Mép trái / phải bị cắt | x < 38, x > 1042 |

Xem bằng tài khoản chủ kênh thì bị che nhiều hơn (ước lượng ban đầu ~25 % đáy); chuẩn của task là người xem khác.

## Goal

Short mới: header nhỏ gọn ở trên, video lớn hơn, title nổi trên đáy video với mép dưới ở y 1600 (trên hàng tên kênh). Tập cũ giữ file cũ cho tới khi chạy lại.

## Phương án đã chốt — V16 (mẫu scratch)

Mẫu: tập `rbjfCfFq3Dk` (nguồn 1440×1080), clip `k01` (title 3 dòng) và `k04` (title 2 dòng), code `main` `25f5b59` + vá tạm `plan.layout` / `Geometry.title_max_h` trong script scratch. Các vòng bị loại: header → title → video (A/B/C), title neo 1420 (D/M/E, vùng che cũ), cỡ chữ cũ + lấn video (P/Q/R), title che chữ Hán burn-in (M2/N/X), video 1.26 / 1.36 W.

| Thành phần | Hiện tại | V16 |
|---|---|---|
| Header panel | 0.79 × 0.27 W (853 × 292), chữ 0.062 W (67 px), căn giữa dọc theo khối | **0.85 × 0.17 W (918 × 184)**, chữ **0.045 W (49 px; mẫu fit còn 48 px, 2 dòng)**, đỉnh ở `min_frame_margin` (y 22) |
| Khe header → video | 0.005 W (5) | giữ |
| Video | 1.12 W (1210), crop 964 × 1080 | **1.16 W (1254)**, y 211–1465, crop 930 × 1080 (nguồn 4:3) |
| Title panel | 0.81 W, cao ≥ 0.27 W, chữ 0.0815 W (88 px), ngay dưới video | **0.75 W (810)**, cao ≥ **0.21 W (227)**, chữ **0.065 W (70 px)**, căn giữa ngang, **mép dưới cố định y 1600**, nổi trên video |
| Title 2 / 3 dòng | 1573–1865 / 1542–1895 | 1373–1600 / 1303–1600 (đè video 92 / 162 px) |

Chấp nhận (HUMAN LEAD): góc phải title (x 905–945, ≈ 40 px) bị cột nút đè một chút; chữ Hán burn-in của nguồn có thể lộ phía trên title (không bắt buộc che).

## Scope

- In scope:
  - `src/auto_short/render/plan.py`: `Geometry` / `layout` theo L1; `title_max_h` theo L3; kiểm hình học L4.
  - `src/auto_short/render/stage.py` chỉ nếu cần cho L3 (fit title) và log layout.
  - `src/auto_short/config.py`, `config.example.toml`: mặc định + key theo L2.
  - Tests: `tests/test_render_plan.py`, `tests/test_render_text.py`, `tests/test_render_stage.py` và test khác assert tọa độ / cỡ chữ / key cũ — cập nhật theo layout mới đã duyệt (đổi hành vi đã duyệt, không che lỗi; ghi lý do ở Result); test mới cho L1–L4.
  - Docs: CP7 R4 (bảng + luật vị trí), R5 (cỡ chữ mẫu, `title_panel_max_height` suy ra), R11 (ví dụ layout), "Giới hạn đã biết"; bảng số đo ảnh mẫu giữ làm lịch sử; CP1 §4 (sơ đồ + ghi sửa đổi CP8.14); `AUTO_SHORT_CHECKPOINT_PLAN.md` (mục CP8.14); `docs/ai/project-profile.md` nếu cần pointer; `docs/workflow/current-state.md`; Result.
- Out of scope: render lại tập cũ tự động (L5); font, màu, bo góc, padding, luật ngắt dòng; phát hiện / che chữ burn-in; vùng an toàn theo từng thiết bị; layout riêng theo tập / bộ kinh; web (xem trước title dùng `fit_clip_title` + `geometry` sẵn có nên tự theo layout mới, không sửa code web).

## Authority / key decisions

- Authority: CP1 §4; CP7 R4, R5, R9, R11; CP8.2 T2 (xem trước title), T5 (`render_key`, tái dùng từng Short); CP2 D6 (stale theo `config_hash`).
- Quyết định (đề xuất — HUMAN LEAD duyệt / sửa trước APPROVE):
  - **L1 Layout V16** (HUMAN LEAD chốt 2026-09-29): header đỉnh ở `min_frame_margin`, căn giữa ngang; video full W ngay dưới header (`gap_header_video`); title căn giữa ngang, mép dưới ở `title_bottom`, cao thêm **lên trên** khi 3 dòng, vẽ **đè lên video** (overlay sau video, như header / title hiện nay). Bỏ căn giữa dọc khối nội dung; phần dưới video (y 1465–1920) để nền đen.
  - **L2 Config `[render]`:** mặc định mới `header_panel_width` 0.85, `header_panel_height` 0.17, `header_font_size` 0.045, `video_height` 1.16, `title_panel_width` 0.75, `title_panel_height` 0.21, `title_font_size` 0.065. **Thêm** `title_bottom` = 1.4815 (× W = 1600 px, mép dưới title). **Bỏ** `gap_video_title` (title không còn nằm dưới video; key cũ trong `config.toml` bị bỏ qua như mọi key lạ hiện nay). `min_frame_margin` giữ, nghĩa mới: lề trên của header.
  - **L3 Chiều cao tối đa title:** không thêm key; `title_panel_max_height` = chiều cao cần cho **3 dòng ở cỡ chữ mẫu** = `ceil(3 × line_spacing × cỡ mẫu + 2 × panel_padding_y)` = 297 px (mặc định). Luật fit R5 giữ: ở cỡ mẫu panel = max(0.21 W, cần); không vừa thì panel = tối đa và thu chữ; dưới `min_font_scale` → `failed`. (Mẫu scratch dùng 300 px; chỉ khác với title phải thu chữ.)
  - **L4 Kiểm hình học** (`PlanError` khi config sai): `title_bottom` ≤ 1920; header + khe + video ≤ 1920; đỉnh title cao nhất (`title_bottom − title_panel_max_height`) ≥ đáy header; panel rộng ≤ W (như cũ).
  - **L5 Tập cũ:** không render lại tự động. Short cũ giữ nguyên tới khi tập chạy lại (resume / web "Xử lý" / sửa title / khôi phục Short): stage `render` stale (`config_hash` đổi) → **mọi Short của tập encode lại** theo layout mới, một lần. Hệ quả: **sửa title một Short của tập cũ sẽ render lại cả tập** (vài phút với 13 Short). `RENDER_PLAN_VERSION` không cần tăng (layout nằm trong `render_key`, `config_hash` đổi); implementer xác nhận bằng test.
  - **L6 Schema:** `render_manifest.json` giữ v1, cùng key; `layout` chỉ đổi giá trị (title_panel có thể giao video). R9 không đổi.

## Implementation approach

- `Geometry`: bỏ `gap_video_title`, thêm `title_bottom` (px) và `title_max_h` theo L3 (cần cỡ chữ + line_spacing + padding_y → tính trong `geometry(cfg)`); `fixed_height` bỏ hoặc đổi nghĩa.
- `layout`: header y = `min_frame_margin`; video y = header đáy + khe; title y = `title_bottom − title_h`.
- Filter graph không đổi (overlay header / title sau video) — xác nhận title vẽ trên video bằng test / frame.
- Kiểm lại một tập thật trong scratch (hard-link `work/`, `output/` riêng), không đụng `output/` chính.

## Acceptance Criteria

1. Layout mặc định: header (81, 22, 918, 184); video (0, 211, 1080, 1254); title x 135, rộng 810, mép dưới 1600; title 2 dòng ở 70 px cao 227, 3 dòng ở 70 px cao 297 (≤ tối đa); title dài hơn → panel 297, thu chữ; dưới `min_font_scale` → `failed`.
2. Title luôn vẽ trên video (pixel vùng giao là panel vàng + chữ), mép dưới title ≤ 1600 < 1625 với mọi title hợp lệ.
3. Key L2: mặc định mới có hiệu lực; `title_bottom` được validate; config sai hình học (L4) báo lỗi rõ.
4. Tập đã render bằng layout cũ: `auto-short status` báo render `stale`; chạy lại → mọi Short encode lại, `render_manifest.json` hợp lệ R9; tập chưa chạy lại giữ file cũ nguyên byte.
5. Web / CLI xem trước title (CP8.2 T2) cho dòng / cỡ chữ / chiều cao panel khớp Short render ra.
6. Mọi test PASS; test đổi assert tọa độ / cỡ chữ / key có lý do ở Result.

## Required verification

- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` — toàn bộ PASS.
- `node scripts/framework-check.mjs` PASS.
- Scratch render thật `rbjfCfFq3Dk` (bản hard-link, `output_dir` scratch, toàn bộ 13 Short) — AC1, AC2, AC4: `render_manifest.json` + `ffprobe` + frame `k01` / `k04` so với mẫu V16 (khác biệt chỉ được đến từ L3 297 vs 300 px, với title thu chữ).
- Manual (HUMAN LEAD, điểm danh — không chạm security / public API): tải vài Short mới về điện thoại, đăng thử, xem bằng tài khoản khác; trên web scratch (port 8093) sửa title một Short của tập cũ → cả tập render lại theo L5, xem trước khớp Short.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract → manual test là điểm danh sau automated verification.

- [ ] Short mới xem trên app YouTube (tài khoản khác): header + title đọc được, title không bị hàng tên kênh che.
- [ ] Tập cũ trên web scratch: sửa title → cả tập render lại, Short mới theo V16.
- [ ] Xem trước title trên web khớp Short render ra.

## Result

- Main changes:
  - `src/auto_short/config.py`: mặc định `[render]` theo L2 (`header_panel_width` 0.85, `header_panel_height` 0.17, `header_font_size` 0.045, `video_height` 1.16, `title_panel_width` 0.75, `title_panel_height` 0.21, `title_font_size` 0.065); thêm `title_bottom` 1.4815 (số, 0.1–2); bỏ `gap_video_title` (key cũ trong `config.toml` bị bỏ qua).
  - `src/auto_short/render/plan.py`: `Geometry` bỏ `gap_video_title` / `fixed_height`, thêm `title_bottom`, `title_max_h` (trường), `header_y`, `video_y`; `title_max_height(cfg)` = `ceil(block_height(3, px(title_font_size) × line_spacing, panel_padding_y × W) − 1e-9)` — cùng biểu thức với `text.fit_title` (L3, 297 px mặc định); kiểm L4 trong `geometry()`; `layout()` theo L1 (header ở `min_frame_margin`, video ngay dưới, title `y = title_bottom − h`, không căn giữa dọc). Filter graph, `stage.py`, schema `render_manifest.json`, `RENDER_PLAN_VERSION` (vẫn 1) không đổi.
  - `config.example.toml`, `README.md` (1 dòng: crop 1080x1254 thay 1080x1210 — số cũ sai sau thay đổi).
  - Docs: CP7 R4 (bảng + luật vị trí + L3 + L4 + lịch sử), R5 (cỡ chữ mẫu, fit 227 / 297), R11 (ví dụ layout, header, `k03`), "Giới hạn đã biết", metadata; CP1 §4 (sơ đồ V16, ghi chú bảng gốc, "Sửa đổi CP8.14"); `AUTO_SHORT_CHECKPOINT_PLAN.md` mục CP8.14. `docs/ai/project-profile.md` không cần pointer mới.
- Tests: `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` → **898 passed** (trước thay đổi: 881; thêm 17 test). Test đổi assert — lý do: hành vi đã duyệt thay đổi (L1–L3), không che lỗi:
  - `test_render_plan.py`: số layout / geometry mặc định (AC1), filter graph (crop 930×1080, scale 1254, pad y 211, overlay 81:22 / 135:1303, panel 810×297, cỡ 49/70); `test_taller_title_panel_recentres_block` → `…grows_upwards_over_the_video` (L1 bỏ căn giữa dọc); `test_geometry_rejects_block_taller_than_frame` → bảng L4 tham số hóa.
  - `test_render_text.py`: cỡ mẫu lấy từ config (49/70); các test tái hiện ảnh mẫu CP7 (ngắt header greedy, ngắt cân, tie-break) giữ nguyên số liệu nhưng truyền hình học ảnh mẫu tường minh (`REF_HEADER`, `REF_TITLE_INNER`); title 3 dòng / thu chữ đổi câu mẫu (câu cũ nay 2 dòng / vừa 70 px); ca header thất bại dài hơn (panel mới vẫn thu chữ được câu cũ).
  - `test_render_stage.py`: header 48 px 2 dòng, title panel 227, cả hai title test 2 dòng ở 70 px; log CLI header; `HASH_KEYS` có `title_bottom`, không `gap_video_title`.
  - `test_review.py`: xem trước 70 px, panel ≥ 227.
  - `test_khaithi_ac1.py`: hash `render` mặc định đổi (L2/L5 cố ý; hash cũ ghi trong comment). Các hash khác giữ.
  - Test mới: AC1 layout + `title_max_h` khớp fit với nhiều cấu hình; AC2 render lavfi title 3 dòng / thu chữ (68 px), pixel vùng title giao video là vàng panel, video phía trên, nền đen dưới, mép dưới 1600; AC3 validate `title_bottom`, key cũ bị bỏ qua, 8 ca L4; AC4 tập render bằng layout cũ giữ nguyên byte sau `set_title`, lần chạy sau `run (config changed)` encode lại cả 2 Short (0 reused); AC5 `preview_title` = dòng / cỡ / panel của manifest.
- Verification khác:
  - `node scripts/framework-check.mjs` → PASS (exit 0).
  - Scratch render thật `rbjfCfFq3Dk` (hard-link `work/`, `review.json` + `manifest.json` chép riêng, `output_dir` scratch): `render: run (config changed)`, 13/13 encoded, 0 reused, 826.2 s Short trong 326 s. Layout gốc: header (81, 22, 918, 184), video (0, 211, 1080, 1254) crop 930×1080 x 255, title (135, 1373, 810, 227); header 48 px 2 dòng; 13/13 title 70 px (5 × 3 dòng panel 297 y 1303, 8 × 2 dòng panel 227 y 1373), mép dưới 1600 cho cả 13. `ffprobe` 13/13: h264 1080×1920 yuv420p 30000/1001, AAC 48 kHz stereo, lệch thời lượng ≤ 0.016 s, sha256 khớp manifest. `k01` / `k04` **byte-identical** với mẫu V16 (sha256 `d4883d8b…` / `3aecf124…`); `render_key` khác mẫu (config hash khác) như dự kiến. Frame `k01` / `k04` (t = 5 s): pixel title trong vùng giao video = `#FEDB00` (±2), dưới video nền đen. `work/` / `output/` chính không đổi (sha256 26 file trước / sau).
- Review:
- Important findings / decisions:
  - AC4 "`auto-short status` báo render `stale`": **không đúng với code hiện tại** — `status` chỉ in trạng thái đã lưu trong `manifest.json` (`done`) và không so `config_hash`; đổi config chỉ được phát hiện khi stage chạy lại (`check_up_to_date` → log `render: run (config changed)`). Hành vi L5 (file cũ giữ nguyên tới khi chạy lại, lúc đó encode lại cả tập) đúng và đã test. Không sửa `status` (ngoài scope); ghi ở CP7 "Giới hạn đã biết".
  - L4 "header + khe + video ≤ 1920" implement là **đáy video** (`min_frame_margin` + header + khe + video) ≤ 1920 vì header bắt đầu ở `min_frame_margin`; thêm kiểm `title_panel_height` ≤ `title_panel_max_height` (giữ kiểm tương đương của CP7).
  - L3 với mặc định: title 3 dòng ở 70 px cần 296.1 → panel 297 = tối đa, nên mẫu V16 (tối đa 300) và code cho cùng kết quả với mọi title vừa 3 dòng ở 70 px; `RENDER_PLAN_VERSION` không cần tăng (test AC4: `render_key` đổi theo config).
- Known limitations: như CP7 "Giới hạn đã biết" (CP8.14): góc phải title ≈ 40 px dưới cột nút phải; chữ Hán burn-in có thể lộ phía trên title; header dòng dài bị ngắt 3 dòng thì thu chữ để vừa 184 px (vd. 53 ký tự → 34 px); sửa title một Short của tập cũ → render lại cả tập (một lần); `status` không báo stale trước khi chạy lại.
- PR: 
