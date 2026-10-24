# Task: PKG2 — Thumbnail cho tập (bản ngang HD + bản dọc), cả bộ kinh

## Status / Approval

- Status: READY
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

Trên trang bộ kinh (ví dụ Kinh Địa Tạng, 102 tập), HUMAN LEAD bấm "Thumbnail cả bộ": hệ thống dựng thumbnail cho mọi tập có bản ngang HD và / hoặc bản dọc, chọn cấu hình kiểu / ảnh chung, xem trước, dựng lưới cả bộ và tải một file zip để upload tay.

## Scope

- In scope:
  - **Tập đủ điều kiện**: tập của playlist có bản ngang HD (`work/<id>/source_hd.mp4`, cùng điều kiện tải "bản ngang HD" hiện có) → thumbnail **16:9 1280×720**; tập có bản dọc hoàn chỉnh (`render.full.read_meta` / file hợp lệ) → thêm thumbnail **9:16 1080×1920**. Bản dọc dùng chung file 16:9 của tập (HUMAN LEAD chọn "cả 9:16 và 16:9").
  - **Chữ** (HUMAN LEAD chọn kiểu "Kinh Địa Tạng — Tập N", không AI, không gõ tay): tên bộ kinh + số tập + người giảng lấy deterministic từ header tập — `titles.json` `header.fields` nếu có, nếu không thì `titling.logic.resolve_header` (+ `titling.playlist.playlist_header`, "Tên bộ kinh" CP8.11) trên `metadata.json`. Không có số tập → tập bị bỏ qua, ghi lý do.
  - **Bố cục tập** version 2: 3 kiểu A/B/C và font / bố cục theo § Vòng 2; dùng `render/text.py`, textfile + `expansion=none`, JPEG ≤ 2 MB.
  - **Cấu hình cả bộ**: theo § Vòng 2; một asset `image` đã duyệt dùng chung, hoặc không ảnh. Preview tạm trước khi dựng cả bộ.
  - **Lưu**: `output/<episode_id>/thumbs/` gồm `landscape-<key>.jpg`, `vertical-<key>.jpg`, `thumbs.json` (schema_version, video_id, playlist_id, header dùng, asset_id, files với key / sha256, skipped_reason, updated_at). Key = hash(header, cấu hình cả bộ, asset sha, layout version, SHA các font của kiểu, khuôn). Dựng lại cùng key → không gọi ffmpeg. Header / ảnh đổi → key mới, file cũ bị thay.
  - **Web**: nút "Thumbnail cả bộ" trên trang bộ kinh → một job `episode_thumbs` (làn render, key theo playlist, khóa trùng); trang `/playlists/{pid}/thumbs` hiện lưới (tập, ảnh xem trước 16:9 / 9:16, cấu hình cả bộ, trạng thái bỏ qua + lý do); `GET /files/playlists/{pid}/thumbs.zip` (tên trong zip `T<tập 3 số>_ngang.jpg`, `T<tập>_doc.jpg`, theo quy ước tên `T<tập>` CP8.21), tải từng file ở trang tập.
- Out of scope: chữ theo chủ đề / AI; kiểu ngoài A/B/C; override riêng từng tập; thumbnail Short / khai thị 4–7 phút; upload YouTube; duyệt từng tập (lưới + zip là bước HUMAN LEAD xem, G7).

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

- Vòng 2 thay bố cục tập version 1; xóa luân phiên ảnh, `set_override`, nhánh dựng một tập, PUT từng tập, selector ảnh từng tập và test override vòng 1. Ba template PKG1 giữ nguyên.

## Acceptance Criteria

1. Tập có HD → 1 JPEG 1280×720; tập có bản dọc → thêm 1 JPEG 1080×1920; cả 3 kiểu A/B/C với chữ tiếng Việt có dấu, đo / thu nhỏ từng dòng trong khung, lỗi rõ khi thiếu glyph ("Kinh Địa Tạng Bồ Tát Bổn Nguyện", "TẬP 102").
2. Tập không có header / số tập hoặc không có HD lẫn bản dọc → bỏ qua kèm lý do, job vẫn xong các tập khác.
3. Cấu hình cả bộ được validate / ghi atomic; một ảnh dùng chung hoặc không ảnh; preview hai khuôn của tập đầu đủ điều kiện không ghi output tập / cấu hình.
4. Chạy lại cả bộ không đổi gì → 0 lần gọi ffmpeg; đổi cấu hình / SHA font dùng → key mới cho cả bộ.
5. Zip chứa đúng các file hợp lệ với tên `T<NNN>_ngang.jpg` / `T<NNN>_doc.jpg`; file hỏng / sha lệch không vào zip.
6. Lỗi ffmpeg một tập không để file dở, không đụng file khác; route kiểm id / tên (không traversal), cần đăng nhập.

## Required verification

- `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`
- `PYTHONPATH=src python -m pytest -q -n auto`; `node scripts/framework-check.mjs` (ORCHESTRATOR).
- Chạy thật trên bản sao danh sách Địa Tạng (output vào thư mục tạm): dựng vài tập 16:9 + 9:16, gửi HUMAN LEAD xem (ORCHESTRATOR).

## Manual test checklist (Tech Lead)

Chạm public API (route mới sau đăng nhập), không chạm security model / database.

- [ ] Trên 8080 ghim commit branch: "Thumbnail cả bộ" Địa Tạng, chọn kiểu / ảnh / focus / chữ, xem trước, dựng lưới và tải zip.

## Vòng 2 — thiết kế theo bộ kinh (HUMAN LEAD 2026-10-24, G8)

HUMAN LEAD chê bố cục vòng 1 ("không đẹp"), gửi 6 thumbnail tham khảo; ORCHESTRATOR làm mẫu bằng ffmpeg, HUMAN LEAD duyệt:

- **3 kiểu** (mỗi bộ kinh chọn một): `A` nền tối + chữ serif vàng ánh kim + ô đỏ "TẬP N" (Thái Thượng); `B` thanh vàng trên / dưới, chữ trắng hẹp Anton, ô đỏ (Thập Thiện); `C` thủy mặc nền giấy, ảnh tách nền đứng, chữ serif nâu, dải xanh (Hoa Nghiêm). Bản tham chiếu dựng hình: `docs/tasks/assets/PKG2-style-prototype.py` (A/B/C), `docs/tasks/assets/PKG2-photo-gallery.py` (mặt nạ elip mờ cho ảnh bất kỳ, colorkey cho ảnh nền trắng).
- **Một ảnh chung cho cả bộ** (bỏ xoay vòng theo tập); HUMAN LEAD chọn từ bảng ảnh. Địa Tạng: **kiểu A, ảnh 67** (`post-images/67.jpg`).
- **Font** (G8, OFL, đã thêm vào `render/fonts/` kèm `OFL-*.txt`): `PlayfairDisplaySC-Bold.ttf`, `OldStandard-Bold.ttf`, `Anton-Regular.ttf`; đủ glyph tiếng Việt (kiểm bằng `Font.missing`).
- **Cấu hình theo bộ kinh** `output/_compilations/<pid>/thumbs.json` (hoặc file playlist-scoped tương đương): `style`, `asset_id`, `focus_x` (0–1, mặc định 0.5), `title_lines` (mặc định tách từ tên bộ: dòng nhỏ "KINH" nếu tên bắt đầu bằng "Kinh", dòng lớn = 2 từ kế, dòng vừa = phần còn lại; sửa tay được), `credit` (mặc định "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG" theo speaker header). Đổi cấu hình → key mới cho mọi tập của bộ.
- 9:16 (1080×1920) theo cùng kiểu: chữ nửa trên, ảnh nửa dưới, ô "TẬP N" giữa.
- Override ảnh từng tập vòng 1 → thay bằng cấu hình cả bộ (xóa code / route / test override từng tập).

## Result

- Vòng 2 IMPLEMENTER: A/B/C cho cả hai khuôn (renderer revision 3 sau vòng sửa review bên dưới); A/B có gradient vàng qua alphamerge / mask + lớp bóng, C giữ serif nâu / số tập đỏ nâu / dải xanh và nền giấy với wash nội bộ (không thêm asset cảnh ngoài). Chân dung nhận diện nền trắng qua 4 pixel RGB góc (mọi channel ≥ 240) để colorkey; ảnh khác dùng elip geq alpha; focus dời crop. Mọi chữ qua textfile / expansion=none / escape_option, đo bằng Font.width + check_glyphs và thu nhỏ trong khung.
- Cấu hình playlist-scoped `output/_compilations/<pid>/thumbs.json`: style, asset_id (null = không ảnh), focus_x, title_lines, credit; ghi atomic. Key chứa cấu hình + header + asset SHA + version + SHA các font của kiểu. Record tập có playlist_id; record cũ được thay khi dựng lại. Xóa toàn bộ cơ chế xoay ảnh / override / PUT từng tập / UI / test vòng 1.
- Web: GET/PUT settings; POST preview nhận cấu hình chưa lưu, trả hai JPEG dưới dạng data URL, dọn thư mục tạm cả khi lỗi, không ghi vào tập. Gallery dùng GET `/files/playlists/{pid}/thumbs/assets/{asset_id}` (auth + usable). Dựng cả bộ vẫn qua job render / dedup và không tự phục hồi sau restart. Giữ zip / tải ảnh / chống traversal + SHA. UI chọn A/B/C, ảnh có số, focus, title_lines / credit, xem trước, dựng cả bộ và zip; giữ node ảnh không đổi khi polling.
- Tái dùng / helper mới:
  - Đã tìm `rg -n 'def .*preview|rawvideo|colorkey|alphamerge|focus_x' src/auto_short` và đọc `post/dhash.py`, `render/text.py`, `thumbnail.py`, hai prototype.
  - Dùng tiếp `_draw_text`, `_encode`, `thumbnail.reusable`, assets.usable, atomic_write_json, core header / HD / vertical helpers và safe() trước URL.
  - `_EpisodeGraph`, `_portrait`, `_fit_line`, `episode_badge`, `font_hashes`, `white_background`: chuyển prototype thành renderer hai khuôn với kiểm font, mask / textfile và runner tiêm được. `post.dhash.decode_gray` resize ảnh và tự gọi subprocess, không giữ RGB góc gốc / không dùng runner tiêm được nên không tái dùng cho nhận diện nền trắng.
  - `settings_path`, `validate_settings`, `default_settings`, `read_settings`, `write_settings`, `preview`: schema cấu hình mới theo playlist và preview tạm; record PKG1 gắn plan/revision không phù hợp. JS `draft`, `lock`, `edited`, `picture`, `draw`, `load`, `request`, `act` thay UI override, giữ cấu hình chưa lưu và gọi preview / build.
- AC → test chính (tên trong hai file PKG2; HTTP chưa chạy trong sandbox):

  | AC | Test |
  |---|---|
  | 1 | `test_real_styles_dimensions_fonts_fit_and_portrait_masks` (3 kiểu × 2 khuôn, ffmpeg thật); `test_hd_eligibility_uses_completed_enhance_or_high_resolution_original` |
  | 2 | `test_skips_missing_input_and_continues`; `test_header_kt_and_playlist_fallback_and_vertical_without_source`; `test_service_failed_episode_continues_and_queue_not_restored` |
  | 3 | `test_playlist_settings_rebuild_all_and_cache`; `test_settings_validation_and_asset_approval` (parametrize); `test_preview_is_temporary_and_text_is_not_filter_syntax` |
  | 4 | `test_cache_sha_header_key_and_removal_of_old_files` (cả đổi font SHA); `test_service_job_lane_dedup_cache_and_playlist_settings` |
  | 5 | `test_service_zip_only_verified_files_and_series_name`; `test_http_build_grid_download_zip_and_tamper` |
  | 6 | `test_failure_keeps_previous_files_and_other_episode_and_no_partial_files`; `test_rejects_traversal_and_symlink_artifacts`; `test_http_auth_ids_traversal_and_static` |

  HTTP bổ sung: `test_http_settings_validation_preview_and_rebuild` kiểm API settings / preview / gallery / đổi cả bộ; phục vụ verification ORCHESTRATOR, cùng AC3.
- Tests env auto-short (`PATH=/home/ntnghia/miniconda3/envs/auto-short/bin:$PATH`):
  - `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_packaging_thumbnail.py`: **58 passed in 16.38s** trên code cuối.
  - `PYTHONPATH=src python -m pytest -q -x tests/test_web_episode_thumbs.py tests/test_web_packaging.py -k service`: **12 passed, 10 deselected in 3.07s** trên code cuối (một deprecation warning Starlette hiện có).
  - `node --check src/auto_short/web/static/thumbs.js`; `git diff --check`: **PASS**. `PYTHONPATH=src python -m pytest --collect-only -q tests/test_web_episode_thumbs.py`: **9 tests collected**, không coi collect là HTTP PASS.
- Diff + / − (`git diff --numstat`, HEAD hiện tại `5218b51`): app **+466 / −153**; tests **+160 / −76**; không tính font / prototype đã có trước lượt IMPLEMENTER.
- Review trước vòng sửa: IMPLEMENTER tự rà diff, render thật và xem ảnh A ngang / C dọc; ORCHESTRATOR đã review và yêu cầu sửa 5 điểm (bên dưới). Vòng cuối phát hiện cache hit vẫn ghi updated_at (test rollback fail khi qua ranh giới giây); đã sửa giữ nguyên record khi không đổi, thêm thời gian giả khác biệt để test ổn định rồi chạy lại PASS các lệnh trên.
- Known limitations / verification bàn giao:
  - IMPLEMENTER không chạy TestClient HTTP / full suite do giới hạn sandbox loopback và phân công ORCHESTRATOR. Sau vòng sửa cần chạy lại `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py`, `PYTHONPATH=src python -m pytest -q -n auto`, `node scripts/framework-check.mjs`; manual trên bản sao Địa Tạng (style A / ảnh 67 do HUMAN LEAD chọn từ kho).
  - Contract giữ IN_PROGRESS tới review / required verification của ORCHESTRATOR. Không commit / push / PR, không mạng / agent khác. Font và prototype giữ nguyên byte; HEAD thay đổi do commit ngoài lượt IMPLEMENTER, không sửa / revert thay đổi bên ngoài.

### Vòng sửa theo review ORCHESTRATOR (2026-10-24)

- Bằng chứng ORCHESTRATOR báo cho bản trước sửa: targeted có HTTP **80 passed**; full suite **2325 passed / 1 skipped**; framework-check **PASS**; dựng thật Địa Tạng tập 102, 3 kiểu × 2 khuôn, kiểu A đạt. Các kết quả này không được coi là verification của diff sau sửa.
- Đã xử lý đủ 5 điểm: B ngang tops 100/180/318, credit 425, ô tập giữ 480; C slot 2 căn giữa dải xanh, khung đo có lề 24px hai bên; tên bộ dài được wrap theo từ ≤40 ký tự / dòng và dừng ở 3 dòng; draft JS bỏ dòng trắng; import ảnh mới gắn tag stem, gallery lấy tag đầu làm nhãn / sắp tag số theo số, nhóm còn lại theo id, ảnh không tag dùng thứ tự dự phòng. Renderer revision tăng 2 → 3 để cache không giữ ảnh B/C cũ. Không thêm helper ứng dụng / không đổi cấu trúc khác.
- Test → điểm review: test render thật hiện có thêm assert đáy dòng 3 / credit / vùng số tập cho A/B/C × hai khuôn (C ngang giữ số tập trên credit) và assert căn giữa / lề dải C; `test_default_settings_truncates_long_series_at_word_boundary`; `test_import_post_images_tags_original_number` đặt cạnh test import; `test_service_gallery_labels_and_numeric_tag_order`. Node smoke gọi `draft()` lấy từ JS thật xác nhận loại dòng trống.
- Verification sandbox sau sửa, env auto-short:
  - `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_packaging_thumbnail.py`: **60 passed in 16.42s**.
  - `PYTHONPATH=src python -m pytest -q -x tests/test_web_packaging.py tests/test_web_episode_thumbs.py -k service`: **13 passed, 10 deselected in 3.32s**, một deprecation warning Starlette hiện có.
  - `git diff --check`, `node --check src/auto_short/web/static/thumbs.js`, Node smoke dòng trắng: **PASS**.
- Numstat toàn diff chưa commit so với HEAD `5218b51` (gồm diff vòng 2 được giữ nguyên): app **+485 / −154**, tests **+223 / −77**. Chỉ sửa Owned paths + `packaging/assets.py` đã được cho phép riêng. Không commit / push / PR / mạng / agent khác. Chờ ORCHESTRATOR xem lại ảnh B/C và chạy lại HTTP / full suite / framework-check cho bản sau sửa.

### Verification ORCHESTRATOR (2026-10-24, sau vòng sửa)

- ORCHESTRATOR sửa thêm 1 dòng: credit mặc định cắt ≤ 60 ký tự (tên người giảng dài không làm hỏng settings mặc định).
- Ngoài sandbox, env auto-short: `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_web_episode_thumbs.py tests/test_packaging_thumbnail.py tests/test_web_packaging.py` **83 passed** (gồm HTTP TestClient); `PYTHONPATH=src python -m pytest -q -n auto` **2328 passed, 1 skipped**; `node scripts/framework-check.mjs` **PASS**; `node --check thumbs.js`, `git diff --check` PASS.
- Kho ảnh thật: `python -m auto_short.packaging assets import-post-images --license "HUMAN LEAD G2 2026-10-24"` → 129 ảnh (tag = tên file), duyệt cả 129; ảnh 67 = `dc54dc63…`. Bản kho không tag trước vòng sửa đổi tên sang `~/.cache/packaging-assets-untagged-20261024`.
- Chạy thật trên playlist Địa Tạng (workspace thật, output thư mục tạm; bản dọc giả lập bằng `vertical.json` thật + file sparse cùng kích thước, vì thumbnail không đọc nội dung video): settings mặc định `["Kinh", "Địa Tạng", "Bồ Tát Bổn Nguyện"]` + "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG"; kiểu A + ảnh 67 tập 10 / 12 / 88 / 102 (ngang + dọc) đạt; tập 102 kiểu B / C sau sửa: hết chồng chữ, dải C căn giữa. Ảnh đã gửi HUMAN LEAD. 88 / 102 tập đủ điều kiện (tập 1–9, 74, 76–78, 100 chưa có HD / bản dọc).
- Codex: vòng 2 391 987 tokens, vòng sửa 616 781 tokens (effort medium); 1 vòng sửa.

### Vòng sửa 2 — reviewer thứ hai (HEAD a4f5ce8)

- Finding 1: drawtext `y_align=text` dịch baseline theo dấu trên, làm dòng giữa ngắn ("Niệm", "Ỗ Ộ") chạm dòng sau; fit bề rộng và ước lượng 1.25 em không đủ. Sửa: mọi pass chữ / bóng / mask của **bố cục tập** dùng `y_align=baseline`. Baseline mỗi slot được hiệu chỉnh bằng dòng tham chiếu cố định của thiết kế đã duyệt; không đổi theo chữ người dùng. `_fit_line` kiểm cả bề rộng lẫn biên mực trên/dưới, gồm padding raster / stroke / shadow; giảm cỡ đến khi nằm trọn trước dòng kế, credit, dải xanh hoặc trong ô tập. Chữ Địa Tạng mặc định có đỉnh mực lệch không quá 2px so với tops cũ trong test, giữ thứ tự riêng của C ngang. Ba template PKG1 / `_draw_text` mặc định không đổi.
- Helper mới `Font.ink_bounds(text, size)`: offset đỉnh/đáy mực so với baseline từ `cmap` + `loca` + bbox `glyf` (gồm glyph composite / dấu tiếng Việt), fallback bbox toàn font `head` khi không có glyf. Đã đọc / tìm `rg -n 'ink_bounds|ascender|descender|def baselines' src/auto_short/render/text.py`: ascender/descender hhea có thể không bao dấu chồng trên; `baselines` hiện có dựa cap-height, không đo được biên mực. Không thêm dependency.
- Finding 2: nhánh elip gán alpha độc lập khiến RGB đen của PNG trong suốt thành mảng đen. Sửa: nhân feather bằng `alpha(X,Y)` gốc thay vì 255. `EPISODE_LAYOUT_VERSION` **3 → 4** để vô hiệu cache trước hai sửa này.
- Finding → test:

  | Finding | Test sau sửa |
  |---|---|
  | Căn dọc / chiều cao | `test_episode_baselines_and_ink_bounds_do_not_overlap`: 18 ca (A/B/C × ngang/dọc × Địa Tạng/Niệm/Ỗ Ộ), baseline cố định, biên mực + hiệu ứng không chồng, credit / ô tập / dải C hợp lệ, default tops lệch ≤2px; test render 6 kiểu/khuôn hiện có kiểm mọi drawtext dùng baseline |
  | Biên mực thực tế | `test_real_accent_masks_match_baseline_metrics`: ffmpeg thật render riêng 3 mask A ngang với "Niệm", đo hàng pixel mực, khớp bbox trong 2px và cách dòng sau ít nhất 8px |
  | Alpha PNG | `test_real_transparent_portrait_preserves_original_alpha`: PNG RGBA đen trong suốt + chủ thể đỏ đục, render JPEG C ngang; pixel trong suốt ra nền giấy (mọi kênh >180, lệch nền không ảnh ≤5), chủ thể đỏ vẫn còn |

- Verification sandbox, Python env `auto-short`, ffmpeg **6.1.1**:
  - `PYTHONPATH=src python -m pytest -q -x tests/test_packaging_episode.py tests/test_packaging_thumbnail.py`: **80 passed in 20.42s**.
  - `PYTHONPATH=src python -m pytest -q -x tests/test_web_packaging.py tests/test_web_episode_thumbs.py -k service`: **13 passed, 10 deselected in 4.38s**, một deprecation warning Starlette hiện có.
  - `git diff --check`: **PASS**. Không chạy lại HTTP / full suite trong sandbox; kết quả ORCHESTRATOR ở mục trước thuộc bản trước vòng sửa 2, không claim PASS cho diff mới.
- Numstat source / test so với `a4f5ce8`: `packaging/thumbnail.py` **+49/−15**, `render/text.py` **+27/−0**, `tests/test_packaging_episode.py` **+94/−10**; tổng app **+76/−15**, test **+94/−10** (không tính mục Result này).
- Không commit / push / PR / mạng / agent khác. READY bàn giao IMPLEMENTER; chờ ORCHESTRATOR rà ảnh sau sửa và chạy verification ngoài sandbox.

### Reviewer thứ hai + verification cuối (ORCHESTRATOR, 2026-10-24)

- `codex exec review --base main` (read-only, PKG1 + PKG2): 2 finding P2 ở trên. ORCHESTRATOR tái hiện finding 1 bằng render thật ("Kinh / Niệm / Phật vãng sanh", kiểu A: dấu nặng dưới Ệ chạm dòng 3); cả hai đã sửa ở vòng sửa 2. Không finding nào còn mở.
- Sau vòng sửa 2, ngoài sandbox: targeted (`tests/test_packaging_episode.py tests/test_web_episode_thumbs.py tests/test_packaging_thumbnail.py tests/test_web_packaging.py tests/test_render_text.py`) **116 passed**; `PYTHONPATH=src python -m pytest -q -n auto` **2348 passed, 1 skipped**; `node scripts/framework-check.mjs` **PASS**. Render lại Địa Tạng tập 102 A / B / C × 2 khuôn: không đổi so với bản đã gửi HUMAN LEAD; ca "Niệm" tự thu nhỏ, hết chồng.
- Codex vòng sửa 2: 888 650 tokens (effort medium); tổng PKG2 vòng 2: 1 lượt thiết kế + 2 vòng sửa.
- Còn lại: manual test checklist trên 8080 (ghim commit branch) — HUMAN LEAD.
