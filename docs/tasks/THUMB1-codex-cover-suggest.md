# Task: THUMB1-codex-cover-suggest — Trang thumbnail cả bộ: Codex gợi ý 4 mẫu → chọn → dựng (tập + khai thị)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, module + trang mới); dự phòng subagent `implementer` (Sonnet) cho test web / socket
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "Với trang dựng thumnail cả bộ nên sửa lại luôn, dùng codex gợi ý 4 mẫu để user chọn sau đó render. Không cần các bước phức tạp như hiện tại" + "bắt đầu luôn với thumnail cho khai thị ghép vào thumail khai thị"; trả lời 3 câu hỏi cùng ngày: G1 nút trên web (8080 tự gọi Codex), G2 chữ khai thị = tiêu đề + TẬP N, G3 thay hẳn trang cũ.
- Parallel group: —
- Owned paths: `src/auto_short/packaging/cover.py`, `src/auto_short/packaging/cover_suggest.py` (mới), `src/auto_short/packaging/khaithi_thumbs.py` (mới), `src/auto_short/packaging/episode.py` (chỉ phần dựng cả bộ gọi thêm khai thị + zip), `src/auto_short/packaging/__main__.py`, `src/auto_short/web/episode_thumbs.py`, `src/auto_short/web/static/thumbs.html`, `src/auto_short/web/static/thumbs.js`, phần nút tải thumbnail khai thị trên trang tập khai thị (`src/auto_short/web/static/` file trang tập hiện có, chỉ thêm link), `src/auto_short/config.py` (mục `[thumbs]` mới), `config.example.toml`, `tests/test_packaging_cover.py`, `tests/test_cover_suggest.py` (mới), `tests/test_khaithi_thumbs.py` (mới), `tests/test_web_episode_thumbs.py`, contract này
- Dependencies: COV1 (#179/#180, ảnh mẫu + "TẬP N"), PKG2 (đường dựng thumbnail tập), CP8.9 (khai thị `<id>.kt`, `titles.json` / `review.json`)
- Base commit / branch: `62b9f65` (`origin/main`) / `feature/thumb1-codex-covers`
- Human Lead approval: APPROVED 2026-10-28 ("bắt đầu luôn" + G1–G3)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (1) web 8080 lần đầu gọi một AI CLI bên ngoài (`codex exec`, quota ChatGPT của HUMAN LEAD) — tích hợp mới; (2) thay trang / API thumbnail cả bộ PKG2 (gỡ form A/B/C); (3) thêm artifact mới (thumbnail khai thị từng clip).

## Bối cảnh / quyết định

- COV1: thumbnail tập = ảnh bìa AI (tên kinh + chủ giảng vẽ sẵn, **khung trống**) + chữ "TẬP N" do code viết. Ảnh bìa đến nay do ORCHESTRATOR chạy Codex `image_generation` bằng tay, đo box bằng mắt rồi `cover install` (CLI). Trang `/playlists/<pid>/thumbs` vẫn là form PKG2 8 bước (kiểu A/B/C, gõ dòng, ảnh chung, thanh trượt, kiểu riêng bản dọc…) và bỏ qua form khi bộ có ảnh bìa.
- Video khai thị (`<id>.kt`, clip `k01`, `k02`…, 9:16 4–7 phút) chưa có thumbnail.
- D-THUMB1-1 (G1): trang có nút **"Gợi ý 4 mẫu"** → 8080 chạy job nền gọi `codex exec` (không `danger-full-access`; sandbox `workspace-write` trong thư mục tạm riêng; model / effort / timeout từ config) → Codex vẽ 4 ảnh bìa dọc khác phong cách **và tự đo khung trống** (ghi `boxes.json`). Trang hiện 4 mẫu đã viết thử chữ → HUMAN LEAD chọn 1.
- D-THUMB1-2: sau khi chọn, job thứ hai cho Codex vẽ **cùng phong cách** (ảnh đã chọn là ảnh tham chiếu `-i`) 3 ảnh còn lại: ngang tập, dọc khai thị, ngang khai thị. Ảnh khai thị có **một khung trống lớn** (đủ 3 dòng tiêu đề + 1 dòng "TẬP N"). Tổng 7 ảnh / bộ, không gọi AI mỗi tập / mỗi clip.
- D-THUMB1-3 (G2): thumbnail khai thị = ảnh bìa khai thị + tiêu đề clip (`review.json` override > `titles.json`, như tiêu đề đang in trong video) tự xuống 1–3 dòng + dòng nhỏ "TẬP N", căn giữa khung. Mỗi clip 2 khổ.
- D-THUMB1-4 (G3): trang mới chỉ còn: Gợi ý 4 mẫu → chọn → (3 ảnh còn lại) → **Dựng cả bộ** (tập + khai thị) → Tải zip. Gỡ form A/B/C, ảnh chung, thanh trượt, kiểu riêng bản dọc, nút "Xem trước" PKG2. Bộ đã có ảnh bìa (VLT, Địa Tạng) dùng tiếp; muốn đổi thì "Gợi ý 4 mẫu" lại.
- D-THUMB1-5: HUMAN LEAD là người kiểm dấu tiếng Việt (AI có thể vẽ sai dấu): trang hiện ảnh đủ lớn + nút phóng to; chọn = xác nhận. Không OCR tự động.

## Goal

Trên `/playlists/<pid>/thumbs`: bấm "Gợi ý 4 mẫu" → vài phút sau có 4 ảnh bìa dọc (đã viết thử "TẬP 1") → chọn 1 → hệ thống tự vẽ thêm bản ngang + 2 bản khai thị cùng phong cách → xem thử (tập 1 / tập cuối / 1 clip khai thị) → "Dựng cả bộ" ra thumbnail 2 khổ cho mọi tập **và mọi clip khai thị** của bộ → tải zip.

## Scope

- In scope:
  - **Config** `[thumbs]`: `codex_bin` (mặc định `codex`), `codex_model` (mặc định `gpt-6.1-sol`), `codex_effort` (`medium`), `codex_timeout_minutes` (30), `enabled` (true). Thiếu binary → nút báo "chưa cài Codex trên máy chủ", không crash.
  - **`packaging/cover_suggest.py`**: dựng prompt tiếng Việt (tên bộ kinh + chủ giảng từ `episode.header` của tập đầu bộ; ghi chú phong cách tùy chọn ≤ 200 ký tự từ người dùng; yêu cầu: chữ đúng dấu, không thêm chữ, khung trang trí để trống với nền phẳng tối đồng màu, không logo / watermark / chân dung người thật; 4 phong cách khác nhau rõ rệt; tự đo khung bằng Python/PIL trong sandbox và ghi `boxes.json`). Chạy `codex exec -C <tmp> --skip-git-repo-check -s workspace-write -m <model> -c model_reasoning_effort=<effort> -o <tmp>/last.txt [-i ref.png] -` với prompt qua stdin, timeout, kill cả nhóm tiến trình khi hủy / quá giờ. Validate đầu ra trước khi nhận: đúng tên file, PNG đọc được (probe), kích thước gần đúng tỉ lệ khổ, ≤ 15 MB, box nằm trong ảnh, đủ lớn (tái dùng `cover._box` sau chuẩn hóa), vùng box tương đối đồng màu (độ lệch chuẩn độ sáng dưới ngưỡng — bắt khung có chữ / không có khung). Ảnh lệch → loại mẫu đó, giữ mẫu khác; < 1 mẫu hợp lệ → job fail với lý do.
  - **Lưu trạng thái**: `output/_compilations/<pid>/cover/suggest/<run_id>/` (ảnh, `boxes.json`, `prompt.md`, `state.json`: phase `options` | `variants`, status, lỗi, mẫu đã chọn, tokens nếu đọc được từ log). Giữ 3 lượt gần nhất, xóa lượt cũ hơn (không đụng ảnh đã cài).
  - **Job**: chạy trong thread riêng của service thumbnail (không dùng làn `prepare` / `ai` / `render`, để không chặn và không bị hàng đợi prepare chặn); tối đa 1 job Codex toàn máy chủ; restart 8080 → job đang chạy thành `failed: máy chủ khởi động lại` (không chạy lại tự động). Hủy được.
  - **`cover.py`**: thêm khổ `kt_vertical`, `kt_landscape` vào `cover.json` (schema tăng, đọc được bản cũ); `install` từ ảnh của lượt gợi ý (cùng đường kiểm như CLI). CLI `cover install --shape` nhận thêm 2 khổ mới.
  - **`packaging/khaithi_thumbs.py`**: thumbnail mỗi clip khai thị × 2 khổ: tiêu đề (tái dùng `thumbnail._fit_line` / `_draw_text` / font Old Standard của COV1; tự xuống ≤ 3 dòng, co chữ vừa khung) + "TẬP N" nhỏ hơn ở dưới, cùng màu vàng kim + bóng như COV1. File `output/<id>.kt/thumbs/<clip>-<shape>-<key>.jpg` + `thumbs.json`; cache key gồm sha ảnh bìa, box, tiêu đề, số tập, layout version, font sha, khổ. Bộ không có ảnh khai thị → bỏ qua (ghi lý do), không fallback A/B/C.
  - **"Dựng cả bộ"** (job làn `render` như hiện tại): thumbnail tập (COV1) + thumbnail khai thị mọi clip của các tập trong bộ. Zip cả bộ gồm cả khai thị (`khai-thi/T<ep>_KT<NN>_<shape>.jpg`).
  - **Web**: trang `thumbs.html` / `thumbs.js` viết lại gọn: (1) trạng thái ảnh bìa hiện tại (4 khổ); (2) "Gợi ý 4 mẫu" + ô ghi chú phong cách tùy chọn + tiến trình / hủy; (3) lưới 4 mẫu (ảnh có "TẬP 1" viết thử, bấm để phóng to) + nút "Chọn mẫu này"; (4) sau khi có 3 ảnh còn lại: xem thử tập 1, tập cuối, 1 clip khai thị, 2 khổ + nút "Dùng bộ ảnh này" (cài) / "Vẽ lại 3 ảnh" / "Gợi ý lại"; (5) "Dựng cả bộ" + tiến trình + "Tải zip" + "Xem từng tập" (lưới hiện có). Trang tập khai thị: link tải thumbnail của từng clip khi đã có.
  - API mới dưới `/api/playlists/{pid}/thumbs/suggest…` (tạo lượt, xem trạng thái, chọn mẫu, cài, hủy) + phục vụ ảnh lượt gợi ý qua route có kiểm id / tên file (không path traversal, không symlink). Thumbnail khai thị: `/files/episodes/{id}.kt/thumbs/{name}`.
- Out of scope:
  - Thumbnail video ghép yêu thích (compilation) và video ghép chủ đề PKG3 (giữ nguyên).
  - Tự kiểm dấu bằng OCR; tự đăng thumbnail lên YouTube (PUB2 giữ nguyên, tự dùng file mới qua `episode.valid_files`).
  - Sửa box bằng tay trên web (CLI `cover install --box` vẫn còn cho trường hợp đặc biệt).
  - Đổi intro bản dọc VERT2 (vẫn dùng thumbnail tập).

## Authority / key decisions

- `docs/decisions/PKG-video-packaging-authorization.md` (đóng gói ACCEPTED), COV1 contract (D-COV1-1/2), CP8.9 (khai thị), CP8.3 (web auth / job / phục vụ file), HUMAN LEAD G1–G3 ở trên.
- Security: prompt chứa tên bộ kinh từ metadata YouTube + ghi chú người dùng → coi là dữ liệu, đặt trong khối trích dẫn của prompt; Codex chỉ ghi trong thư mục tạm; server chỉ nhận file đúng tên đã liệt kê, kiểm bằng probe; không truyền token / mật khẩu / đường dẫn ngoài thư mục tạm vào prompt. Route chỉ cho người đã đăng nhập.

## Implementation approach

- Tách logic thuần (prompt, validate, state) khỏi subprocess: `run_codex` nhận `runner` để test giả lập Codex (ghi file mẫu) — test không gọi Codex thật, không mạng.
- Đo "vùng đồng màu" bằng ffmpeg (`signalstats` / `crop` trên box) hoặc PIL nếu đã là dependency; không thêm dependency mới.
- Thumbnail khai thị tái dùng hàm dựng của COV1 (`cover.build_episode` tổng quát hóa thành nhiều dòng) thay vì viết encoder mới.
- Trang mới: tái dùng polling job / lưới tập / zip hiện có trong `thumbs.js`.

## Phải giữ nguyên

- Thumbnail tập của bộ đã có ảnh bìa (VLT, Địa Tạng): byte-identical khi không đổi ảnh (cache key COV1 không đổi).
- `episode.valid_files` / `build_episode` cho VERT2 intro và PUB2; bộ **chưa có** ảnh bìa vẫn dựng được thumbnail PKG2 mặc định ở backend (VERT2 intro cần), chỉ UI bị gỡ.
- Route tải từng file / zip hiện có (đường dẫn, kiểm hash); PKG3 thumbnail video ghép chủ đề.
- CLI `cover install|remove|show` cho 2 khổ cũ.

## Code bị thay / xóa

- `thumbs.html` / `thumbs.js`: form kiểu A/B/C, dòng tiêu đề, người giảng, ảnh dùng chung + gallery, thanh trượt focus, "Bản dọc dùng kiểu riêng", nút "Xem trước" → xóa.
- `episode_thumbs.py`: route `PUT …/thumbs/settings`, `POST …/thumbs/preview` và `SettingsIn` → xóa nếu không còn caller (GET settings / gallery asset: xóa nếu trang mới không dùng); test tương ứng trong `tests/test_web_episode_thumbs.py` → xóa / thay bằng test trang mới.
- `episode.read_settings` / `write_settings` / `preview`: giữ nếu backend PKG2 mặc định còn dùng; xóa phần chỉ phục vụ form cũ.

## Acceptance Criteria

1. Codex giả lập ghi 4 ảnh + `boxes.json` → lượt gợi ý `options` có 4 mẫu hợp lệ, mỗi mẫu có ảnh xem thử "TẬP 1"; mẫu sai tên / không đọc được / sai tỉ lệ / box ngoài ảnh / box không đồng màu bị loại với lý do; 0 mẫu hợp lệ → fail có lý do; timeout / hủy → kill tiến trình, status `failed` / `cancelled`.
2. Lệnh Codex dựng đúng: `-s workspace-write`, `-C <tmp>`, `--skip-git-repo-check`, model / effort từ config, prompt qua stdin, `-i` ảnh tham chiếu ở phase 2; không bao giờ `danger-full-access`; prompt chứa tên kinh / chủ giảng / ghi chú trong khối dữ liệu.
3. Chọn mẫu → phase `variants` sinh đúng 3 ảnh (ngang, dọc KT, ngang KT) cùng validate; "Dùng bộ ảnh này" cài 4 khổ vào `cover.json` (schema mới, đọc được `cover.json` COV1 cũ) atomically; lượt cũ quá 3 bị xóa, ảnh đã cài không bị xóa.
4. Thumbnail khai thị: tiêu đề override > AI, ≤ 3 dòng vừa khung, "TẬP N", 2 khổ đúng kích thước `EPISODE_SIZES`; cache: đổi tiêu đề / ảnh / box → dựng lại, không đổi → dùng lại; bộ không có ảnh KT → bỏ qua có lý do.
5. "Dựng cả bộ" dựng tập + khai thị; zip có cả `khai-thi/…`; thumbnail tập VLT / Địa Tạng không đổi byte khi ảnh bìa không đổi.
6. Web: trang mới không còn form A/B/C; API suggest yêu cầu đăng nhập, chặn id lượt / tên file lạ (traversal, symlink); chỉ 1 job Codex cùng lúc (lượt thứ 2 → 409); restart → job đang chạy thành `failed`; thiếu binary → 503 / thông báo rõ.
7. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_cover_suggest.py tests/test_packaging_cover.py` — AC 1–3.
- `<prefix> tests/test_khaithi_thumbs.py tests/test_packaging_episode.py` — AC 4–5.
- `<prefix> tests/test_web_episode_thumbs.py tests/test_publish_thumbs.py tests/test_vertical_silence_intro.py` — AC 5–6 (TestClient: ORCHESTRATOR chạy ngoài sandbox).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): 1 bộ chưa có ảnh bìa (Cảm Ứng Thiên hoặc Thập Thiện) — Gợi ý 4 mẫu bằng Codex thật, ghi thời gian + tokens; HUMAN LEAD chọn + kiểm dấu; dựng cả bộ gồm khai thị; HUMAN LEAD xem thumbnail khai thị.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model; chạm web API nội bộ có auth (thêm route) và gọi AI CLI ngoài → manual test là gate trước merge.

- [ ] Gợi ý 4 mẫu ra 4 ảnh khác phong cách, chữ đúng dấu, "TẬP 1" nằm gọn trong khung.
- [ ] Chọn mẫu → 3 ảnh còn lại cùng phong cách; xem thử tập 1 / tập cuối / khai thị ổn.
- [ ] Dựng cả bộ + tải zip có thumbnail khai thị; tiêu đề dài 3 dòng vẫn vừa khung.
- [ ] Bộ VLT / Địa Tạng: trang hiện ảnh bìa đang dùng, thumbnail không đổi.

## Result

- Main changes (IMPLEMENTER 2026-10-28): implementation sẵn sàng ORCHESTRATOR review trong Owned paths. **Status giữ `IN_PROGRESS`, chưa đạt gate READY**: các lệnh HTTP / full suite và chạy Codex thật được giao ORCHESTRATOR, không chạy trong sandbox theo chỉ thị bàn giao. Không commit / push / PR.
  - `[thumbs]` có đủ 5 tham số + validation; thiếu binary / tắt cấu hình trả 503 có thông báo tiếng Việt.
  - `cover_suggest.py`: prompt tiếng Việt, metadata / ghi chú trong JSON trích dẫn (escape cả dấu xuống dòng); hai phase `options` / `variants`, runner tiêm được; `codex exec` sandbox `workspace-write`, stdin, model / effort / timeout theo config, `-i ref.png` phase 2. Subprocess có process group riêng, timeout / hủy kill cả group; giữ tối đa 3 lượt trong namespace `cover/suggest/<run_id>/`, lưu prompt, box, log, token nếu đọc được, trạng thái / lỗi.
  - Chỉ nhận tên PNG cho phép, chữ ký PNG + probe + decode, ≤15 MB, tối thiểu 256 px mỗi chiều / tối đa 40 triệu pixel, tỉ lệ sai lệch ≤6%, box nguyên trong ảnh trước / sau scale-crop. Box tập ≥40% rộng / 5% cao; box khai thị ≥65% rộng / 28% cao; độ lệch chuẩn kênh xám <12 / 255, trung bình ≤110 / 255. Loại riêng từng mẫu options; variants phải đủ cả 3 ảnh. Không OCR; dấu tiếng Việt do HUMAN LEAD duyệt.
  - Cover schema 2 đọc được schema 1; CLI nhận `kt_vertical` / `kt_landscape`. Cài cả bộ qua validator CLI trong staging, ghi ảnh tên theo SHA, rồi đổi **một** `cover.json` atomically: lỗi không thay bộ đang dùng. `COVER_LAYOUT_VERSION` / cache key tập giữ nguyên; `draw_lines` tổng quát hóa encoder COV1, graph một dòng giữ nguyên.
  - `khaithi_thumbs.py`: nhận diện bằng `khaithi.json` canonical; `review.resolve_titles` / `added_entries` giữ precedence, bỏ override stale / clip đã xóa, hỗ trợ clip thêm tay. `wrap_balanced` + `_fit_line` đo ≤3 dòng tiêu đề và dòng TẬP nhỏ hơn, cùng font / màu / bóng COV1. Hai JPEG / clip, manifest + key SHA cover / box / title / tập / font / layout / khổ; không có cover KT thì bỏ qua kèm lý do. Ghi staging, chỉ phục vụ file hiện hành có SHA đúng. Số KT theo thứ tự video, nên `m01` không trùng `k01` trong zip.
  - `build_playlist` dựng thêm khai thị có marker, giữ summary PKG2 khi không có tập KT; job render báo số ảnh KT / lý do bỏ qua. Zip giữ tên tập cũ, thêm `khai-thi/T<ep>_KT<NN>_<shape>.jpg`, kiểm SHA lại trước khi thêm.
  - Service có thread Codex riêng, khóa toàn service tối đa 1 job, 409 nếu trùng; restart đánh dấu lượt đang chạy failed, không tự chạy lại. API create/status/select/install/cancel/images + current covers dùng auth middleware hiện có; kiểm run id / allowlist tên ảnh / symlink. Gỡ routes settings / preview / gallery cũ; giữ backend PKG2 cho VERT2 / PUB2.
  - Trang mới: 4 khổ ảnh hiện tại, ghi chú, gợi ý / hủy, mẫu có TẬP 1 + phóng to, chọn / vẽ lại / cài bộ ảnh, preview tập đầu / cuối / clip KT thật hai khổ nếu có, dựng / polling / zip / lưới tập. Trang tập KT chỉ thêm link tải thumbnail từng clip, dùng `kind` canonical và chỉ hiện khi endpoint trả file hợp lệ.
- Tests — AC → bằng chứng:

  | AC | Test / trạng thái |
  |---|---|
  | 1 | `test_options_variants_install_and_command`, `test_invalid_candidates_removed_individually` (8 nhánh), `test_zero_valid_and_variants_require_all_three`, `test_job_terminal_failure_state`, `test_real_process_group_killed` (subprocess cục bộ + child sleep, timeout / hủy thật) — PASS |
  | 2 | `test_options_variants_install_and_command`, `test_prompt_quotes_untrusted_data_and_config_validation` — PASS; chỉ runner giả, không gọi Codex / image_generation thật |
  | 3 | `test_options_variants_install_and_command` (4+3 PNG, 6 preview, cài 4 khổ, dọn lượt giữ ảnh cài), `test_install_set_atomic_manifest_and_legacy_schema`, `test_redraw_requires_explicit_install_again` — PASS |
  | 4 | `test_override_stale_rejected_and_two_shapes_cache`, `test_long_title_fits_at_most_three_lines`, `test_cover_box_image_layout_font_and_number_invalidate`, `test_kt_download_validation_fails_closed`, `test_no_kt_cover_skipped_with_reason_and_playlist_build` — PASS |
  | 5 | `test_playlist_build_contains_kt_and_episode_bytes_unchanged`, `test_playlist_zip_includes_only_verified_kt_files`, `test_added_clip_keeps_distinct_video_number_in_zip`, toàn bộ `test_packaging_cover.py` / `test_packaging_episode.py` — PASS. PUB2 / VERT2 regression command còn chờ ORCHESTRATOR |
  | 6 | `test_service_one_codex_job_cancel_and_restart`, `test_restart_ids_and_symlinks` — PASS, không socket. Đã viết auth / missing binary / traversal / symlink / suggest→install→zip / KT download / trang mới trong `test_web_episode_thumbs.py`, **chưa chạy** theo chỉ thị sandbox |
  | 7 | `framework-check`, `git diff --check`, kiểm cú pháp Python / JS — PASS; full suite **chưa chạy** |

  Prefix `P`: `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/thumb1-codex-covers/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`. Tất cả lệnh pytest dùng `timeout 295s`.
  - `timeout 295s P tests/test_cover_suggest.py tests/test_packaging_cover.py tests/test_khaithi_thumbs.py tests/test_packaging_episode.py -x --tb=short`: lượt đầu **116 passed, 1 failed** (98.05 s), phát hiện summary PKG2 đổi khi chỉ chuyển header sang `.kt`; đã sửa integration để nhận diện khai thị qua marker canonical, không sửa test cũ. Lượt kế **146 passed** (108.39 s). Sau thêm test khóa service + clip thêm tay và dùng wrapper canonical: **148 passed** (111.40 s).
  - Sau sửa cờ cài khi vẽ lại, thêm regression test: `timeout 295s P tests/test_cover_suggest.py -x --tb=short`: **19 passed** (28.48 s), gồm test mới `test_redraw_requires_explicit_install_again`.
  - `timeout 295s node scripts/framework-check.mjs`: **PASS**, exit 0 (`/tmp/thumb1-framework-check.log`). `git diff --check`: **PASS**, exit 0. `node --check src/auto_short/web/static/thumbs.js`, `node --check src/auto_short/web/static/app.js`, parse AST Python: **PASS**.
- Diff + / − (app, test): app **+899 / −290**; test **+585 / −134** (gồm file mới chưa stage; không tính contract). Đếm bằng `git diff --numstat` + số dòng file mới từ `git ls-files --others --exclude-standard`.
- Helper mới (đã tìm, lý do không tái dùng):
  - Đã đọc `cover.py` / `episode.py` / `thumbnail.py` và tìm `rg -n 'def _fit_line|def _encode|def probe_media|def _run'`, `rg -n 'def resolve_titles|def read_review|class Resolved|def added_entries'`, `rg -n 'def .*wrap|wrap.*def|balanced|TextFit|class Font'` trên render / review / packaging trước khi chốt helper. Tìm link tải / polling / jobs ở web hiện có để tái dùng.
  - `cover_suggest` prompt / validate / state / retention / recover / previews: namespace và lifecycle lượt AI mới, không có artifact hiện hành tương đương; tái dùng `_no_symlinks`, `probe_media`, `_box`, `atomic_write_json`, `read_json_dict`, `cover.install/build_episode`, `episode.header`, KT resolver. Dùng ffmpeg crop→gray + stdlib statistics; không thêm PIL / dependency.
  - `_process/run_codex`: `_run` media hiện có chỉ chạy lệnh đồng bộ, không có stdin prompt, polling cancellation / timeout hay kill process group; cần runner riêng và tiêm runner giả.
  - `cover.install_set`: gọi `install` trực tiếp 4 lần lên bộ hiện tại sẽ lộ bộ ảnh cài dở; tái dùng nguyên validator đó trong staging rồi publish manifest một lần. `draw_lines` mở rộng đường render một dòng, không thêm encoder.
  - KT `titles/title_lines/cache_key/read/build_episode/valid_files`: manifest clip × khổ và cache riêng với tiêu đề; khác manifest tập / layout A/B/C. Tái dùng canonical `khaithi.read`, review resolver, `wrap_balanced`, Font / `_fit_line` / `_draw_text` / `_encode`, SHA và validator đường dẫn; không nhân bản thuật toán ngắt dòng / đo chữ.
  - Service methods chỉ nối lifecycle mới vào thread / HTTP; tái dùng `checked`, `mutable`, `invoke`, `safe/response/job_view` và render queue hiện có. `_thumbs` tái dùng `_section/_str/_bool/_int` của config.
  - Test tái dùng `seed_episodes`, `source_image`, `episode_media` sẵn có; thêm fake Codex ghi PNG / boxes và seed KT marker + titles để có fixture đúng boundary, không gọi AI / mạng.
- Review: IMPLEMENTER tự rà Owned paths / diff / AC / cache COV1 / atomic install / path traversal / symlink / cancellation / clip numbering. ORCHESTRATOR (2026-10-28) đọc `cover_suggest.py`: lệnh `codex exec -s workspace-write -C <tmp>`, không `danger-full-access`; dữ liệu trong khối JSON "không phải chỉ thị"; kill cả process group khi hủy / quá giờ; validate PNG / tỉ lệ / box / vùng khung tối đồng màu. Full suite vòng 1: 1 fail `test_http_suggest_choose_install_build_zip_and_kt_links` (preview_url 404: `response()` gọi `safe()` lần hai làm URL thành "[đã ẩn đường dẫn]") → Codex resume sửa (+3/−1 app, +41 test; 370k tokens, 150 s; patch áp tay vì resume chạy nhầm sandbox worktree khác). Vòng 2: web + regression **209 passed**; full suite `-n auto` **3353 passed, 1 skipped** (201 s); `framework-check` PASS; `git diff --check` PASS. Codex: lượt đầu 1104 s / 160k tokens. Không gọi agent khác, không mạng, không Codex / image_generation thật, không thêm dependency.
- Important findings / decisions: marker `khaithi.json` là owner nhận diện loại tập, suffix `.kt` chỉ là ràng buộc namespace; header fallback `.kt/titles.json` của PKG2 không tự biến thành một tập KT. `episode.py` chỉ đổi `build_playlist`; backend mặc định / settings / preview / cache key tập được giữ. Bộ cài dùng ảnh có tên SHA để manifest 4 khổ có điểm publish duy nhất; schema 2 vẫn đọc cover COV1 schema 1.
- Known limitations / lệnh chưa chạy (ORCHESTRATOR):
  - `timeout 295s P tests/test_web_episode_thumbs.py tests/test_publish_thumbs.py tests/test_vertical_silence_intro.py -x --tb=short`: **chưa chạy**; chỉ thị không TestClient / HTTP / `tests/test_web_*.py` trong sandbox không có socket loopback. Không khẳng định AC6 PASS đầy đủ.
  - `timeout 295s P -n auto`: **chưa chạy**, theo chỉ thị không full suite trong sandbox. Không khẳng định AC7 PASS đầy đủ.
  - Codex thật trên 8080 cho Cảm Ứng Thiên hoặc Thập Thiện, thời gian / tokens thật, HUMAN LEAD chọn / kiểm dấu / xem thumbnail KT, kiểm bộ ảnh VLT / Địa Tạng: **chưa chạy**; toàn bộ manual checklist còn mở.
- Working tree cuối phiên: branch `feature/thumb1-codex-covers`, HEAD hiện `dbf4af0` (đầu phiên `9142d82`). `git diff 9142d82 HEAD --name-only` chỉ có `docs/tasks/THUMB2-codex-compilation-thumbs.md`: commit tài liệu xuất hiện ngoài thao tác của IMPLEMENTER, không sửa / hoàn nguyên. Diff THUMB1 vẫn trong Owned paths; số dòng trên không tính các commit THUMB2.
- PR: draft (chờ chạy thật Codex + manual checklist của HUMAN LEAD trước khi merge).
