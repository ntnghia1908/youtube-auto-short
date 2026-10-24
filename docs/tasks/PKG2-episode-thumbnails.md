# Task: PKG2 — Thumbnail cho tập (bản ngang HD + bản dọc), cả bộ kinh

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session, review + test web / full suite + chạy thật trên bộ Địa Tạng
- Implementer: codex — mở rộng module PKG1 vừa viết, spec rõ (project-profile §7)
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/PKG-video-packaging-authorization.md` G7 (HUMAN LEAD 2026-10-24: ưu tiên trước VIS1)
- Parallel group: —
- Owned paths: `src/auto_short/packaging/episode.py` (mới), mở rộng `packaging/thumbnail.py` (bố cục tập 16:9 + 9:16, không đổi 3 template PKG1), `src/auto_short/web/episode_thumbs.py` (mới), `src/auto_short/web/static/thumbs.html` + `thumbs.js` (mới), sửa nhỏ: `web/app.py` (đăng ký), `web/static/playlist.html` / `app.js` (nút "Thumbnail cả bộ" trên trang bộ kinh, link tải ở trang tập), `tests/test_packaging_episode.py`, `tests/test_web_episode_thumbs.py`, contract này, module map `docs/ai/project-profile.md`
- Dependencies: PKG1 (cùng branch `feature/pkg1-thumbnail`, tuần tự, một writer)
- Base commit / branch: commit PKG1 READY trên `feature/pkg1-thumbnail`
- Human Lead approval: inherited from boundary (G7)
- Implementation authorized: YES

## Goal

Trên trang bộ kinh (ví dụ Kinh Địa Tạng, 102 tập), HUMAN LEAD bấm "Thumbnail cả bộ": hệ thống dựng thumbnail cho mọi tập có bản ngang HD và / hoặc bản dọc, hiện lưới để xem, cho đổi ảnh từng tập, rồi tải một file zip để upload tay.

## Scope

- In scope:
  - **Tập đủ điều kiện**: tập của playlist có bản ngang HD (`work/<id>/source_hd.mp4`, cùng điều kiện tải "bản ngang HD" hiện có) → thumbnail **16:9 1280×720**; tập có bản dọc hoàn chỉnh (`render.full.read_meta` / file hợp lệ) → thêm thumbnail **9:16 1080×1920**. Bản dọc dùng chung file 16:9 của tập (HUMAN LEAD chọn "cả 9:16 và 16:9").
  - **Chữ** (HUMAN LEAD chọn kiểu "Kinh Địa Tạng — Tập N", không AI, không gõ tay): tên bộ kinh + số tập + người giảng lấy deterministic từ header tập — `titles.json` `header.fields` nếu có, nếu không thì `titling.logic.resolve_header` (+ `titling.playlist.playlist_header`, "Tên bộ kinh" CP8.11) trên `metadata.json`. Không có số tập → tập bị bỏ qua, ghi lý do.
  - **Bố cục tập** (version hóa, `EPISODE_LAYOUT_VERSION`): dòng tên bộ kinh (vừa, ≤ 2 dòng), "TẬP N" (rất lớn), dòng người giảng (nhỏ); ảnh người giảng chiếm một bên (16:9) hoặc nửa dưới (9:16); nền màu ấm theo style. Dùng `render/text.py` + font ExtraBold + filtergraph ffmpeg như PKG1 (textfile, `expansion=none`). JPEG ≤ 2 MB.
  - **Ảnh khác nhau giữa các tập**: chọn deterministic từ asset `image` đã duyệt (sắp theo id) bằng `episode_number mod n`; HUMAN LEAD đổi ảnh một tập trên lưới (ghi override). Không có asset duyệt → nền gradient, vẫn dựng được.
  - **Lưu**: `output/<episode_id>/thumbs/` gồm `landscape-<key>.jpg`, `vertical-<key>.jpg`, `thumbs.json` (schema_version, header dùng, asset_id, override, key, sha256, updated_at). Key = hash(chữ, asset sha, layout version, font sha, khuôn). Dựng lại cùng key → không gọi ffmpeg. Header / ảnh đổi → key mới, file cũ bị thay.
  - **Web**: nút "Thumbnail cả bộ" trên trang bộ kinh → một job `episode_thumbs` (làn render, key theo playlist, khóa trùng); trang `/playlists/{pid}/thumbs` hiện lưới (tập, ảnh xem trước 16:9 / 9:16, nút đổi ảnh, trạng thái bỏ qua + lý do); `GET /files/playlists/{pid}/thumbs.zip` (tên trong zip `T<tập 3 số>_ngang.jpg`, `T<tập>_doc.jpg`, theo quy ước tên `T<tập>` CP8.21), tải từng file ở trang tập.
- Out of scope: chữ theo chủ đề / AI; nhiều template cho tập; thumbnail Short / khai thị 4–7 phút; upload YouTube; duyệt từng tập (lưới + zip là bước HUMAN LEAD xem, G7).

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` R3 (thư mục output khác — xem G7), R5, R7, R8, R9, G2, G4, G7.
- Header: `docs/decisions/CP6-titling-contract.md` (header deterministic), CP8.11 "Tên bộ kinh"; bản dọc: `render/full.py` (CP8.32).

## Implementation approach

- `packaging/episode.py`: liệt kê tập đủ điều kiện, tính header, chọn asset, dựng + cache, ghi `thumbs.json`; dùng runner tiêm được.
- `thumbnail.py`: thêm hàm dựng bố cục tập cho cả hai khuôn, tách phần dùng chung (copy font / textfile / vòng chất lượng JPEG) thay vì chép lại.
- Web theo mẫu `web/packaging.py` (lưu ý thứ tự `safe()` rồi mới gắn URL, như bản sửa PKG1).

## Phải giữ nguyên

- `source_hd.mp4`, `full/vertical.mp4|json`, `titles.json`, layout Short / bản dọc; 3 template PKG1 và route PKG1.
- Dọn / archive tập (CP8.6): xóa tập vẫn xóa `output/<id>/` như cũ (thumbnail đi theo).

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Tập có HD → 1 JPEG 1280×720; tập có bản dọc → thêm 1 JPEG 1080×1920; chữ tiếng Việt có dấu đúng (tên bộ dài như "Kinh Địa Tạng Bồ Tát Bổn Nguyện" vừa ≤ 2 dòng, "TẬP 102").
2. Tập không có header / số tập hoặc không có HD lẫn bản dọc → bỏ qua kèm lý do, job vẫn xong các tập khác.
3. Hai tập liên tiếp dùng ảnh khác nhau khi kho có ≥ 2 ảnh duyệt; đổi ảnh một tập chỉ dựng lại tập đó.
4. Chạy lại cả bộ không đổi gì → 0 lần gọi ffmpeg.
5. Zip chứa đúng các file hợp lệ với tên `T<NNN>_ngang.jpg` / `T<NNN>_doc.jpg`; file hỏng / sha lệch không vào zip.
6. Lỗi ffmpeg một tập không để file dở, không đụng file khác; route kiểm id / tên (không traversal), cần đăng nhập.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs` (ORCHESTRATOR).
- Chạy thật trên bản sao danh sách Địa Tạng (output vào thư mục tạm): dựng vài tập 16:9 + 9:16, gửi HUMAN LEAD xem (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Chạm public API (route mới sau đăng nhập), không chạm security model / database.

- [ ] Trên 8080 ghim commit branch: "Thumbnail cả bộ" Địa Tạng, xem lưới, đổi ảnh 1 tập, tải zip.

## Vòng 2 — thiết kế theo bộ kinh (HUMAN LEAD 2026-10-24, G8)

HUMAN LEAD chê bố cục vòng 1 ("không đẹp"), gửi 6 thumbnail tham khảo; ORCHESTRATOR làm mẫu bằng ffmpeg, HUMAN LEAD duyệt:

- **3 kiểu** (mỗi bộ kinh chọn một): `A` nền tối + chữ serif vàng ánh kim + ô đỏ "TẬP N" (Thái Thượng); `B` thanh vàng trên / dưới, chữ trắng hẹp Anton, ô đỏ (Thập Thiện); `C` thủy mặc nền giấy, ảnh tách nền đứng, chữ serif nâu, dải xanh (Hoa Nghiêm). Bản tham chiếu dựng hình: `docs/tasks/assets/PKG2-style-prototype.py` (A/B/C), `docs/tasks/assets/PKG2-photo-gallery.py` (mặt nạ elip mờ cho ảnh bất kỳ, colorkey cho ảnh nền trắng).
- **Một ảnh chung cho cả bộ** (bỏ xoay vòng theo tập); HUMAN LEAD chọn từ bảng ảnh. Địa Tạng: **kiểu A, ảnh 67** (`post-images/67.jpg`).
- **Font** (G8, OFL, đã thêm vào `render/fonts/` kèm `OFL-*.txt`): `PlayfairDisplaySC-Bold.ttf`, `OldStandard-Bold.ttf`, `Anton-Regular.ttf`; đủ glyph tiếng Việt (kiểm bằng `Font.missing`).
- **Cấu hình theo bộ kinh** `output/_compilations/<pid>/thumbs.json` (hoặc file playlist-scoped tương đương): `style`, `asset_id`, `focus_x` (0–1, mặc định 0.5), `title_lines` (mặc định tách từ tên bộ: dòng nhỏ "KINH" nếu tên bắt đầu bằng "Kinh", dòng lớn = 2 từ kế, dòng vừa = phần còn lại; sửa tay được), `credit` (mặc định "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG" theo speaker header). Đổi cấu hình → key mới cho mọi tập của bộ.
- 9:16 (1080×1920) theo cùng kiểu: chữ nửa trên, ảnh nửa dưới, ô "TẬP N" giữa.
- Override ảnh từng tập vòng 1 → thay bằng cấu hình cả bộ (xóa code / route / test override từng tập).

## Result

- Main changes (IMPLEMENTER):
  - `packaging/thumbnail.py`: `_draw_text` / `_encode` dùng chung PKG1 + PKG2; mở rộng kiểm cache cho tên file tập. Key, version và bố cục ba template PKG1 giữ nguyên. Bố cục tập version 1: series ≤ 2 dòng cân bằng, `TẬP N` và speaker một dòng; 1280×720 / 1080×1920, JPEG ≤ 2 MB.
  - `packaging/episode.py`: header từ titles / titles khai thị / resolve_header + playlist_header; điều kiện HD gọi trực tiếp `enhance.state.effective_source`, bản dọc dùng `full.ready_file`; ảnh approved luân phiên + override; staging, record atomic, SHA cache, dọn key cũ sau thành công, lỗi từng tập được ghi và tiếp tục.
  - `web/episode_thumbs.py`: service / job render `episode_thumbs:<pid>` / dedup, trang lưới, API dựng + override, preview / tải từng ảnh và zip chỉ chứa ảnh hiện hành khớp SHA. `safe()` chạy trước khi thêm URL. Job không khôi phục tự động sau restart.
  - `static/thumbs.html` / `thumbs.js`, nút "Thumbnail cả bộ" trong playlist và link tải thumbnail ở trang tập. Route file nhận tên có key và hai alias cố định `landscape.jpg` / `vertical.jpg` cho link trang tập; alias cũng phải qua kiểm record / key / SHA, không thêm API tra cứu.
  - Module map cập nhật PKG2.
- AC → test (tên rút gọn; tất cả thuộc hai file test PKG2):

  | AC | Test |
  |---|---|
  | 1 | `test_real_episode_jpegs_dimensions_vietnamese_and_two_line_series` (2 ca, ffmpeg thật); `test_hd_eligibility_uses_completed_enhance_or_high_resolution_original` (5 ca) |
  | 2 | `test_skips_missing_input_and_continues` (3 ca); `test_header_kt_and_playlist_fallback_and_vertical_without_source`; `test_service_failed_episode_continues_and_queue_not_restored` |
  | 3 | `test_rotation_approved_assets_and_override_only_rebuilds_one_episode`; `test_service_job_lane_dedup_cache_and_single_override`; `test_http_override_rebuilds_only_selected_episode` (chờ ORCHESTRATOR) |
  | 4 | `test_cache_sha_header_key_and_removal_of_old_files`; `test_service_job_lane_dedup_cache_and_single_override` |
  | 5 | `test_service_zip_only_verified_files_and_series_name` (4 ca); `test_http_build_grid_download_zip_and_tamper` (chờ ORCHESTRATOR) |
  | 6 | `test_failure_keeps_previous_files_and_other_episode_and_no_partial_files` (2 ca); `test_rejects_traversal_and_symlink_artifacts` (4 ca); `test_http_auth_ids_traversal_and_static` (chờ ORCHESTRATOR) |

- Tests trong sandbox (Python env `auto-short`, đặt `PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH`):
  - `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_packaging_thumbnail.py`: **37 passed**.
  - `PYTHONPATH=src python -m pytest -q -x tests/test_web_episode_thumbs.py tests/test_web_packaging.py -k service`: **12 passed, 10 deselected**, một cảnh báo deprecation từ dependency Starlette hiện có.
  - `PYTHONPATH=src python -m pytest --collect-only -q tests/test_web_episode_thumbs.py`: **9 tests collected**; không coi collect là HTTP PASS.
  - `git diff --check`; `node --check src/auto_short/web/static/thumbs.js`; `node --check src/auto_short/web/static/app.js`: PASS.
  - Lần gọi đầu bằng Python base: dừng ngay `No module named pytest`; đã chạy lại bằng env repo như trên.
- Diff + / − (bao gồm file mới chưa stage, đo bằng `git diff --numstat` và `git diff --no-index --numstat /dev/null <file mới>`): app **+653 / −36**; tests **+464 / −0**.
- Helper mới (đã tìm, lý do không tái dùng):
  - Lệnh tìm: `rg -n 'def (.*cache.*|.*reus.*|.*thumb.*|.*zip.*|.*header.*|.*directory.*)|textfile=|escape_option|quality in' src/auto_short/packaging src/auto_short/render/text.py src/auto_short/render/full.py src/auto_short/titling/logic.py src/auto_short/titling/playlist.py src/auto_short/web/packaging.py src/auto_short/review/names.py`.
  - Thumbnail: `_draw_text` / `_encode` là phần tách từ PKG1; `episode_text` / `build_episode` bổ sung bố cục ba tầng + hai khuôn, dùng `wrap_balanced`, `Font`, `escape_option`. `thumbnail.reusable` được dùng chung, chỉ truyền regex tên tập; không chép kiểm file.
  - Episode: `_no_symlinks`, `directory`, `playlist`, `read`, `_new` quản lý schema / đường dẫn `thumbs.json` riêng (record PKG1 gắn plan/revision); `header`, `shapes`, `images`, `context`, `cache_key`, `valid_files`, `set_override`, `build_episode`, `build_playlist` ghép các helper core đã có cho điều kiện tập / cache / atomic publication. Tái dùng `assets.list_assets/usable`, `resolve_header`, `playlist_header`, `effective_source`, `full.ready_file`, hashing, `atomic_write_json`, `utc_now`.
  - Web: `render_key`, `ThumbnailTarget`, `EpisodeThumbs` và `register` theo mẫu PKG1; zip dùng stdlib + `review.names.content_disposition/clean_part/truncate_utf8` (helper zip Short không xuất JPEG). JS `episodeThumbnailLinks` tạo link trong trang tập từ hai alias kiểm chứng.
  - Test: `seed_episodes` / `add_images` được dùng chung từ test core sang test web; tái dùng `test_packaging_thumbnail.fake_media` và fixture app offline hiện có.
- Review: IMPLEMENTER tự rà diff / AC, chỉ Owned paths; chờ ORCHESTRATOR review độc lập.
- Important findings / decisions: theo G7, tập còn bản dọc hoàn chỉnh có cả thumbnail ngang + dọc dù video nguồn đã dọn. Không import web từ core.
- Known limitations / verification bàn giao ORCHESTRATOR:
  - Không chạy HTTP TestClient do sandbox chặn loopback (theo delegation); chưa claim auth / HTTP PASS. Lệnh còn lại: `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`.
  - Chưa chạy `PYTHONPATH=src python -m pytest -q -n auto`, `node scripts/framework-check.mjs`, chạy thật trên bản sao Địa Tạng và manual checklist; thuộc ORCHESTRATOR theo contract / delegation.
  - Triển khai sẵn sàng bàn giao IMPLEMENTER; contract giữ IN_PROGRESS tới review / required verification của ORCHESTRATOR.
- PR: không commit / push / PR; không agent khác / không mạng thật.
