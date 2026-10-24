# Task: PKG1 — Thumbnail + tiêu đề cho video ghép chủ đề

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + chạy test web / full suite / chạy thật
- Implementer: codex — module mới tự chứa, spec rõ (project-profile §7); Sonnet `implementer` nếu quota Codex ≥ ngưỡng
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` (ACCEPTED 2026-10-24, G1–G6)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/` (mới: `__init__.py`, `assets.py`, `record.py`, `thumbnail.py`, `__main__.py` CLI kho asset), `src/auto_short/render/fonts/BeVietnamPro-ExtraBold.ttf` (G4, đã thêm: bản chính thức google/fonts `ofl/bevietnampro`, Regular cùng nguồn trùng sha256 bản đang đóng gói), `src/auto_short/web/packaging.py` (mới), `src/auto_short/web/static/package.html` + `package.js` (mới), sửa nhỏ: `web/app.py` (đăng ký service + job view, như `theme_plan_web`), trang đăng ký trong `web/packaging.py` (hoặc `web/routes/pages.py`), `web/static/theme_plan.js` (link "Đóng gói"), `config.py` + `config.example.toml` (`[packaging]`), `tests/test_packaging_thumbnail.py`, `tests/test_web_packaging.py`, contract này, module map `docs/ai/project-profile.md`
- Dependencies: TC3 (đã merge); không dependency thư viện mới
- Base commit / branch: `7381e1f` / `feature/pkg1-thumbnail`
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

## Goal

Trên trang kế hoạch chủ đề đã xuất video, HUMAN LEAD mở "Đóng gói", thấy 3–4 tiêu đề có căn cứ và 3 thumbnail 1280×720 khác kiểu nhau, sửa dòng chữ lớn, chọn + duyệt rồi tải về để upload tay lên YouTube.

## Scope

- In scope:
  - Kho asset `library.json` dưới `[packaging] asset_dir` (R5): `id` = sha256, `file`, `kind` (`image` | `loop` | `music`), `tags`, `source`, `license`, `approved`, thông số (`width`, `height`, `duration`) đo bằng `ffprobe`. CLI `python -m auto_short.packaging assets add|approve|list`; `import-post-images --license <text>` nạp ảnh thư viện bài đăng kèm nguồn từ `sources.tsv` (chỉ chạy sau G2). Web chỉ đọc danh sách.
  - Tiêu đề: `title_options` của plan TC2 đã duyệt (giữ nguyên thứ tự, kiểu A / B) + một phương án "truyền thống" ghép deterministic từ nhãn chủ đề và speaker (`theme_plan.speaker_for_clips`), không gọi AI. Sửa tay qua cùng validate `_title_problem` của TC2 (giới hạn độ dài, cấm giật tít / emoji / ngoặc kép).
  - Dòng chữ lớn (headline): mặc định = nhãn chủ đề, sửa tay, ≤ 3 dòng, đo / ngắt bằng `render/text.py`.
  - 3 template, version hóa: `classic` (nền vàng ấm gradient, ảnh người giảng bên phải, chữ trái), `minimal` (ảnh người giảng + dải tối, chữ ngắn), `scenic` (ảnh cảnh làm mờ + chữ giữa). Dựng một khung bằng ffmpeg (`drawtext` + font ExtraBold, `overlay`), JPEG 1280×720, ≤ 2 MB; vùng an toàn chừa góc phải dưới (nhãn thời lượng của YouTube). Thiếu ảnh → nền ffmpeg tự tạo.
  - Hồ sơ `pkg/<plan>-r<rev>/package.json`: `schema_version`, `plan_id`, `revision`, `plan_fingerprint`, `tc3_sha256`, `title_options`, `title`, `headline`, `thumbnails[]` (`template`, `template_version`, `asset_ids`, `file`, `sha256`, `key`), `selected`, `state` (`draft` | `approved` | `stale`), `approved_at`, `updated_at`.
  - Cache: dựng lại cùng đầu vào → dùng file cũ (key khớp + sha256 khớp), không chạy ffmpeg.
  - Web: trang `/playlists/{pid}/theme-plans/{plan_id}/package`; API xem / sửa tiêu đề + headline / dựng thumbnail (job `theme_package`, làn render) / chọn + duyệt / tải thumbnail (`Content-Disposition` tên theo tiêu đề) / "Copy tiêu đề" + "Copy mô tả" (mô tả lấy từ metadata TC3).
- Out of scope: thumbnail cho khai thị 4–7 phút / CP8.33; upload YouTube; A/B log (PKG1.1 bỏ); upload asset qua web; AI viết headline.

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R1–R9, G2, G4, G5.
- TC2 title rules: `src/auto_short/theme_plan/__init__.py` (`SYSTEM`, `_title_problem`, `_compose_title`) — tái dùng, không sửa.

## Implementation approach

- `packaging/record.py`: đường dẫn `pkg/<plan>-r<rev>/`, cache key, đọc / ghi / kiểm schema, tính stale từ `ThemePlans.output`.
- `thumbnail.py`: template = dataclass (màu, bố cục, vị trí chữ) → filtergraph ffmpeg một khung; test so pixel thô bằng `ffmpeg -f rawvideo` ở vài điểm mẫu + kích thước file, không thêm thư viện ảnh.
- Web mỏng: `web/packaging.py` theo mẫu `web/theme_plan.py` (`invoke`, `no_store`, kiểm `checked(pid)`), chỉ gọi `packaging/`.

## Phải giữ nguyên

- File TC3 và route `/files/playlists/{pid}/theme/{name}`; plan TC2 (không ghi vào plan).
- Thư viện ảnh bài đăng (`post-images/`, chia lại ảnh) — chỉ đọc khi import.
- `render/fonts/BeVietnamPro-Regular.ttf` và layout Short.

## Code bị thay / xóa

- Không có (chỉ thêm mới).

## Acceptance Criteria

1. Từ một plan đã xuất video, dựng được 3 thumbnail JPEG 1280×720 khác template; chữ tiếng Việt có dấu (NFC, ví dụ "Niệm Phật vãng sanh — buông xả") đúng glyph, không tràn vùng an toàn; headline quá dài → lỗi rõ ràng, không cắt chữ âm thầm.
2. Trang hiển thị tiêu đề TC2 + phương án truyền thống; sửa tay đi qua validate TC2 (tiêu đề giật tít / emoji bị từ chối).
3. Chọn + duyệt ghi `package.json` `approved`; tải được thumbnail đã chọn; đổi plan revision hoặc file TC3 → `stale`, không còn tải như bản hợp lệ.
4. Dựng lại cùng đầu vào không gọi ffmpeg (runner giả đếm 0 lần) và trả cùng file.
5. Asset chưa `approved` hoặc thiếu `license` không được chọn; CLI import ghi `source` từ `sources.tsv`.
6. Lỗi ffmpeg giữa chừng không để file dở trong `pkg/`, không đụng file TC3.
7. Không đăng nhập → 401 / redirect như route hiện có; tên file / id trong route đi qua regex (không path traversal).

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_thumbnail.py tests/test_web_packaging.py` — AC1–7 (ffmpeg thật cho AC1 trên khung nhỏ; còn lại runner giả).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR).
- `node scripts/framework-check.mjs`.
- Chạy thật trên bản kế hoạch có sẵn (`output/_compilations/*/theme/`): dựng 3 thumbnail, gửi HUMAN LEAD xem (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Chạm public API (route mới, sau đăng nhập), không chạm security model / database. Manual test là điểm danh sau automated verification.

- [ ] 8080 ghim commit branch (HUMAN LEAD cho restart): mở "Đóng gói", dựng, sửa headline, duyệt, tải.
- [ ] HUMAN LEAD chấm mắt 3 template trên điện thoại (kích thước nhỏ như trang chủ YouTube).

## Result

- Main changes: IMPLEMENTER hoàn tất `packaging/` (kho asset + CLI, hồ sơ/cache/stale, 3 template ffmpeg), web service + trang chọn/sửa/dựng/duyệt/tải, link Đóng gói, `[packaging]`, module map. Không sửa TC1–TC3 / post / font Regular. ExtraBold có sẵn ở HEAD, không đổi font.
- Tests (env `auto-short`; prefix `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH`):
  - `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_thumbnail.py`: **18 PASS** (2 case ffmpeg thật: 3 template × có/không ảnh; NFC/glyph/pixel/vùng an toàn; còn lại runner giả).
  - `PYTHONPATH=src python -m pytest -q -x tests/test_web_packaging.py -k service`: **6 PASS, 7 deselected**; không socket. Có kiểm TC3 trước job, dedup/làn render, cache, duyệt, revision/fingerprint/TC3/tamper stale.
  - `timeout 45s env PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH PYTHONPATH=src python -m pytest -q -x tests/test_web_packaging.py -o faulthandler_timeout=20`: **exit 124** sau 6 service case; HTTP treo ngay `TestClient.post("/login")` trong fixture TC2, traceback AnyIO/asyncio. **7 HTTP case chưa xác minh**, gồm auth/file route/Content-Disposition; chuyển ORCHESTRATOR chạy ngoài sandbox.
  - Python mặc định (`/home/ntnghia/miniconda3/bin/python`) không có pytest; lần đầu lệnh thumbnail trả `No module named pytest`, đã dùng đúng env ở trên.
  - `node --check src/auto_short/web/static/package.js`, `node --check src/auto_short/web/static/theme_plan.js`, `git diff --check`, `node scripts/framework-check.mjs`: PASS.
- Diff + / − (app, test): **app +888 / −1** (gồm config example); **test +403 / −0**. Đếm tracked bằng `git diff --numstat -- src/auto_short config.example.toml tests/test_packaging_thumbnail.py tests/test_web_packaging.py`; file mới chưa stage bằng `git diff --no-index --numstat /dev/null <file>`. Không tính docs và diff boundary của writer khác.
- Helper mới (đã tìm, lý do không tái dùng):
  - Đã chạy `rg -n '^def |^class ' src/auto_short/post/images.py src/auto_short/theme_plan/__init__.py src/auto_short/theme_render/__init__.py src/auto_short/render/text.py src/auto_short/render/stage.py src/auto_short/workspace.py src/auto_short/compilation/store.py src/auto_short/hashing.py src/auto_short/review/names.py`; tìm thêm `rg -n 'escape|quote|def .*path|def .*text' src/auto_short/render/plan.py src/auto_short/theme_render/__init__.py src/auto_short/render/full.py` và các service/fixture TC2.
  - Mới: `assets.list_assets/add/approve/usable/import_post_images/_save` cho kho content-addressed có license + approval; post image library không có schema/quyền dùng này. Import tái dùng `post.images.list_images` và chỉ đọc nguồn.
  - Mới: `record.directory/fingerprint/title_options/new/cache_key/validate/read/status/write` cho schema/namespace PKG1, `thumbnail.Template/fit/key/reusable/_graph/build/ready` cho JPEG 16:9/ba template/duyệt bản đăng; artifact Short và TC3 có schema/layout khác. Regex playlist trong core chỉ bảo vệ thành phần đường dẫn, không import web; kiểm playlist đầy đủ ở adapter.
  - Mới: `Packages`, `ThumbnailTarget`, `render_key`, `invoke/no_store/register` cùng helper UI cho lifecycle PKG1; không dùng job key TC3 vì đây là output/job riêng. Tái dùng `ThemePlans.find/checked/output(verify=True)`, response/safe/job_view, JobRunner/Step/RENDER.
  - Tái dùng `config_hash` (canonical JSON), `sha256_file`, `atomic_write_json`, `utc_now`, `store.directory`, `Font/nfc/check_glyphs/wrap_greedy/fit_title`, `escape_option`, `probe_media/_run/_last_line/RenderError`, TC2 `speaker_for_clips/_compose_title/_title_problem`, `clean_part/truncate_utf8/content_disposition`. Không có bản sao helper hashing / ghi JSON / escape / đo chữ / validate title.
- Review: ORCHESTRATOR chạy ngoài sandbox: `tests/test_web_packaging.py` 3 FAIL (preview 404) — `response()`/`safe()` che URL `/files/...` thành "[đã ẩn đường dẫn]"; micro-fix ORCHESTRATOR ở `Packages.view` (safe dữ liệu trước rồi gắn URL, `JSONResponse` như TC2). Sau sửa: PKG1 31 passed; full suite `python -m pytest -q -n auto` 2276 passed, 1 skipped; framework-check PASS. Chạy thật 3 template với ảnh người giảng + chữ "Kinh Địa Tạng — Tập 74": glyph đúng. Codex: 130k tokens, 1 vòng. Review Codex thứ hai: gộp cùng PKG2.
- Important findings / decisions: stale tính khi đọc, giữ nguyên record/file cũ để tra cứu nhưng không cấp preview/tải như bản hợp lệ; chỉ bản approved được attachment. JPEG qscale tăng khi cần giảm dung lượng (quy ước ffmpeg). Không gọi mạng, agent, commit/push/PR. Boundary có diff G3 do writer khác trong session, IMPLEMENTER không sửa/hoàn tác.
- Known limitations: HTTP/AC7 chưa PASS trong môi trường này; full suite, chạy trên dữ liệu thật và chấm mắt trên điện thoại chưa chạy theo phân công. Không claim các verification đó đã PASS.
- PR: không tạo theo chỉ thị.

| AC | Test | Bằng chứng |
|---|---|---|
| 1 | `test_vietnamese_three_real_templates_and_safe_area`, `test_headline_rejected_without_partial_files` | PASS; ffmpeg thật + pixel/glyph/NFC/1280×720/≤2 MB |
| 2 | `test_traditional_title_uses_source_speaker_without_ai`, `test_service_title_validation_job_lane_dedup_cache_and_approval`, `test_http_titles_and_validation` | Core/service PASS; HTTP pending |
| 3 | `test_record_stale_and_schema_validation`, `test_service_stale_preserves_old_record`, `test_http_approve_download_and_stale` | Core/service PASS; tải HTTP pending |
| 4 | `test_cache_checks_key_and_file_sha`, `test_service_title_validation_job_lane_dedup_cache_and_approval` | PASS; cache không gọi media runner, file hỏng dựng lại |
| 5 | `test_assets_require_approval_license_and_source`, `test_cli_import_provenance_and_config` | PASS; import giữ source/license, không ghi thư viện post |
| 6 | `test_ffmpeg_failure_rolls_back_all_templates_and_keeps_tc3`, `test_service_job_rechecks_input_and_reports_failure` | PASS; lỗi ở cả 3 vị trí encode, không file dở, TC3 nguyên vẹn |
| 7 | `test_http_auth_ids_and_static_page` | HTTP pending (401/redirect, regex/traversal, symlink) |
