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
| Title 2 / 3 dòng | 1573–1865 / 1542–1895 | 1373–1600 / 1303–1600 (đè video 91 / 164 px) |

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
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
