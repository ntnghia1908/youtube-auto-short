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

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
