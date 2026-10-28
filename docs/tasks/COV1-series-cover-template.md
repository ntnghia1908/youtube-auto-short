# Task: COV1-series-cover-template — Thumbnail tập từ ảnh bìa mẫu AI của bộ kinh + số tập

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "Quá đẹp rồi, chọn hình 2 và làm theo đề xuất. Vậy việc tạo thumnail giao cho codex làm thay vì cách làm hiện tại trên web. Tôi cũng muốn làm lại kinh địa tạng HD và mobile"
- Parallel group: —
- Owned paths: `src/auto_short/packaging/cover.py` (mới), `src/auto_short/packaging/episode.py`, `src/auto_short/packaging/__main__.py` hoặc CLI packaging hiện có (lệnh cài ảnh mẫu), `tests/test_packaging_cover.py`, test hiện có của `packaging/episode.py` khi khẳng định hành vi bị thay, contract này
- Dependencies: PKG2 / PKG2.1 (thumbnail tập), VERT2 (intro bản dọc dùng `episode.valid_files` / `build_episode`)
- Base commit / branch: `dba3222` (`feature/vert2-silence-thumb-intro`) / `feature/cov1-series-cover`
- Human Lead approval: APPROVED 2026-10-28
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thay nguồn thumbnail tập của PKG2 (quyết định đóng gói PKG) cho bộ kinh có ảnh mẫu.

## Bối cảnh / quyết định

- HUMAN LEAD thấy thumbnail PKG2 (kiểu A/B/C chữ trên nền tối) chưa đẹp; ảnh bìa AI (Codex `image_generation`) đẹp hơn nhiều. Chọn phong cách "ảnh 2" (hoa sen vàng, nền xanh ngọc).
- D-COV1-1: mỗi bộ kinh × khổ (`vertical` 9:16, `landscape` 16:9) có **một ảnh bìa mẫu** do AI vẽ một lần (ORCHESTRATOR dùng Codex, HUMAN LEAD duyệt bằng mắt): tên kinh + chủ giảng đã có trong ảnh, **khung số tập để trống**. Code chỉ viết "TẬP N" vào khung → số tập luôn đúng, không gọi AI mỗi tập.
- D-COV1-2: bộ kinh có ảnh mẫu cho một khổ → thumbnail khổ đó của mọi tập lấy từ ảnh mẫu (thay PKG2 A/B/C); khổ / bộ chưa có ảnh mẫu → PKG2 như cũ. Web (lưới thumbnail, tải về), intro bản dọc (VERT2), PUB2 dùng chung đường `episode.build_episode` / `valid_files` nên tự theo.

## Goal

Cài ảnh mẫu + toạ độ khung cho một bộ kinh bằng một lệnh; sau đó thumbnail mỗi tập (hai khổ) = ảnh mẫu + chữ "TẬP N" vàng kim căn giữa khung, chữ tự co vừa khung, đúng dấu.

## Scope

- In scope:
  - Lưu ảnh mẫu: `output/_compilations/<pid>/cover/<shape>.png` + `cover.json` (`schema_version`, mỗi khổ: `file`, `sha256`, `box` [x, y, w, h] theo pixel ảnh mẫu, `prompt` tùy chọn). Ảnh mẫu đúng kích thước khổ của PKG2 (`thumbnail.EPISODE_SIZES`) sau khi cài (lệnh cài scale / crop giữa nếu ảnh nguồn khác kích thước, box quy đổi theo).
  - Lệnh CLI cài / gỡ ảnh mẫu (`--playlist`, `--shape`, `--image`, `--box x,y,w,h`), kiểm ảnh đọc được, box nằm trong ảnh.
  - `packaging/cover.py`: dựng JPEG một khung bằng ffmpeg (tái dùng `thumbnail._draw_text` / `_encode` / font có sẵn — serif đậm như style A, màu vàng kim + bóng đổ nhẹ để hợp ảnh mẫu), chữ `TẬP {N}` (N = số tập từ `episode.header`), co cỡ chữ cho vừa ~80 % chiều rộng và ~85 % chiều cao box (tính cả dấu; sửa từ 60 % sau chạy thật 2026-10-28 vì chữ quá nhỏ), căn giữa; giới hạn dung lượng `MAX_BYTES` như PKG2.
  - `episode.py`: `build_episode` / `valid_files` / `cache_key` dùng ảnh mẫu khi có (khóa cache gồm sha ảnh mẫu, box, số tập, phiên bản layout cover); `preview` cũng theo.
  - Test.
- Out of scope: gọi AI từ code; UI cài ảnh mẫu trên web (dùng CLI); đổi PKG2 A/B/C; PKG3 (thumbnail video ghép chủ đề); PUB2.

## Implementation approach

- Ảnh mẫu là input; chữ vẽ bằng `drawtext` như PKG2 (không thêm dependency).
- Box đo bằng mắt bởi ORCHESTRATOR khi cài; `cover.json` là nguồn duy nhất.

## Phải giữ nguyên

- Bộ không có ảnh mẫu: PKG2 thumbnail, cache key, test giữ nguyên byte.
- `valid_files` chỉ trả file hiện hành, hash-verified.
- VERT2 intro: `intro_image` không đổi code; đổi ảnh mẫu → thumbnail mới → sha intro mới.

## Code bị thay / xóa

- Không có (thêm nhánh ảnh mẫu; PKG2 giữ cho bộ không có ảnh mẫu).

## Acceptance Criteria

1. Lệnh cài: ảnh 1080x1920 + box → `cover.json` đúng sha / box; ảnh sai kích thước được chuẩn hoá và box quy đổi; box ngoài ảnh / ảnh hỏng → lỗi rõ, không ghi.
2. Bộ có ảnh mẫu dọc: `build_episode` tập 51 → file `vertical` = ảnh mẫu với chữ "TẬP 51" trong box (pixel ngoài box giống ảnh mẫu trong ngưỡng nén JPEG; trong box khác ảnh mẫu); khổ ngang chưa có mẫu → PKG2 như cũ.
3. Đổi ảnh mẫu / box → `valid_files` không còn trả file cũ; build lại ra file mới.
4. Số tập 1–3 chữ số đều vừa box (không tràn).
5. Bộ không có ảnh mẫu → thumbnail + cache key giữ nguyên (test PKG2 hiện có PASS).
6. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_packaging_cover.py tests/test_packaging_thumbnail.py` + test packaging/web thumbs hiện có — AC 1–5.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR): cài 4 ảnh mẫu (VLT, Địa Tạng × 2 khổ) → dựng thumbnail vài tập (1, 51, 102) → HUMAN LEAD duyệt bằng mắt.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API.

- [ ] Thumbnail VLT tập 51 + Địa Tạng tập 1 cả hai khổ: chữ số tập đẹp, nằm giữa khung.

## Result

- Main changes (IMPLEMENTER 2026-10-28): implementation hoàn tất trong Owned paths; **chưa READY, BLOCKED ở verification AC6** do sandbox không có socket. Giữ Status `IN_PROGRESS` để ORCHESTRATOR chạy verification còn lại / review.
  - Thêm `packaging/cover.py`: `cover.json` schema 1, `shapes.<shape> = {file, sha256, box, prompt?}`; chuẩn hoá PNG theo `EPISODE_SIZES` bằng scale + crop giữa (`exact=1`), quy đổi box; kiểm probe / decode / SHA / symlink; thay file nguyên tử và rollback ảnh nếu ghi metadata lỗi; gỡ theo khổ.
  - Chữ `TẬP N`: OldStandard-Bold (`old`; HUMAN LEAD 2026-10-28 chọn thay PlayfairDisplaySC-Bold vì số old-style khó đọc), vàng kim + bóng 2 px; đo cả dấu bằng `Font` / `_fit_line`, căn giữa box, giới hạn `FIT_WIDTH` 80 % rộng / `FIT_HEIGHT` 85 % cao (`COVER_LAYOUT_VERSION` 3); JPEG dùng `_encode` / `MAX_BYTES` hiện có.
  - `episode.py`: cover ưu tiên theo khổ trong build / preview / valid_files, cache gồm SHA ảnh + box + số tập + `COVER_LAYOUT_VERSION` + SHA font + shape. `asset_id` / `asset_ids` đọc được nguồn `cover:<sha>`. Khổ không có mẫu giữ nguyên key và đường render PKG2.
  - CLI `python -m auto_short.packaging [--config F] cover install|remove|show`; `install` nhận `--playlist`, `--shape`, `--image`, `--box`, `--prompt-file` tùy chọn.
  - Files đổi: `src/auto_short/packaging/{cover.py,episode.py,__main__.py}`, `tests/test_packaging_cover.py`, contract này.
- Tests — AC → bằng chứng (tên test dưới đây thuộc `test_packaging_cover.py` trừ khi ghi khác):

  | AC | Test |
  |---|---|
  | 1 | `test_install_normalizes_box_sha_and_prompt`; `test_invalid_install_preserves_previous_cover`; `test_cli_install_show_remove_and_bad_box` |
  | 2 | `test_build_preview_and_other_shape_remains_byte_identical`; `test_number_fits_and_pixels_change_only_inside_box` (JPEG 2 khổ; sai lệch xám ngoài box trung bình < 2, cực đại < 24 / 255; trong box có chữ) |
  | 3 | `test_cache_invalidates_cover_only` (ảnh / box / số / layout / font, gỡ mẫu); `test_tampered_cover_or_thumbnail_is_never_current`; `test_vert2_intro_rebuilds_when_cover_changes` |
  | 4 | `test_number_fits_and_pixels_change_only_inside_box` (1, 51, 102 × 2 khổ); `test_small_box_and_missing_glyph_fail_before_ffmpeg` |
  | 5 | `test_packaging_episode.py::test_keys_unchanged_without_vertical_override`; `test_packaging_thumbnail.py::test_episode_filtergraph_identical_to_pre_refactor`; test build / preview ở AC2 so byte khổ không có mẫu |
  | 6 | Framework checker + diff check PASS; full suite chưa chạy trong sandbox; không khẳng định AC6 PASS |

  Prefix cho các lệnh pytest dưới đây: `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/fix-ytdlp-timeout/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.
  - `<prefix> tests/test_packaging_cover.py tests/test_packaging_thumbnail.py -x --tb=short`: **122 passed**, 59.55 s (33 test cover).
  - `<prefix> tests/test_packaging_episode.py tests/test_packaging_thumbnail.py -x --tb=short`: **173 passed**, 51.94 s.
  - `<prefix> tests/test_web_episode_thumbs.py -k service -x --tb=short`: **8 passed, 7 deselected**, 4.35 s; 1 warning Starlette/httpx có sẵn.
  - `<prefix> tests/test_publish_thumbs.py tests/test_vertical_silence_intro.py -x --tb=short`: **44 passed**, 17.84 s; transport giả / gọi handler trực tiếp, không socket.
  - Sau khi thêm `crop exact=1`: `<prefix> tests/test_packaging_cover.py -k install -x --tb=short`: **13 passed, 20 deselected**, 6.99 s.
  - `node scripts/framework-check.mjs`: PASS. `git diff --check`: PASS. Các lệnh test bổ sung dùng `timeout 295s`; không lệnh nào vượt 5 phút.
- Diff + / − (app, test): app **+231 / −18**; test **+254 / −0**. Đếm từ `git diff --numstat` và `git diff --no-index --numstat /dev/null <file mới>` (không stage).
- Helper mới (đã tìm, lý do không tái dùng):
  - Đã grep `rg -n 'probe|atomic_write_json|def .*image|def .*box|cache_key|recorded_asset|asset_ids' src/auto_short/packaging src/auto_short/ingest tests/test_packaging* tests/test_web_episode_thumbs.py` và `rg -n '^def |EPISODE_|STYLE_FONTS|class .*Line' src/auto_short/packaging/thumbnail.py src/auto_short/render/text.py src/auto_short/packaging/assets.py` trước khi thêm helper.
  - `cover.directory/read/current/install/remove`: namespace / schema / lifecycle ảnh mẫu mới, khác kho asset có license; tái dùng `episode.settings_path/_no_symlinks`, `probe_media`, `read_json_dict`, `atomic_write_json`, `sha256_file`.
  - `cover._box`: cần kiểm hình chữ nhật trước và sau crop; helper có sẵn chỉ định nghĩa layout/badge, không kiểm box ảnh đầu vào.
  - `cover.number_line/build_episode`: một nhãn căn giữa box tuỳ ý khác layout A/B/C cố định; tái dùng `thumbnail._fit_line/_draw_text/_encode/EpisodeLine`, `STYLE_FONTS/EPISODE_FONTS`, `Font/check_glyphs`. Không thêm thuật toán đo chữ / encoder khác.
  - Test `cfg` tái dùng `seed_episodes`; `source_image` dựng ảnh lavfi nhiều kích thước / màu, `gray` giải mã kênh xám để so pixel; đã tìm `rg -n 'def .*rgb|def .*gray|def .*pixel|source_image|number_line' tests src/auto_short/packaging`, helper RGB hiện có ở test render không cung cấp dữ liệu xám cho 2 kích thước này.
- Review: IMPLEMENTER tự rà diff / AC / cache / rollback / symlink; không thấy blocking finding trong implementation. Review độc lập của ORCHESTRATOR còn chờ. Không commit / push / PR; không gọi mạng, agent khác hoặc công cụ tạo ảnh.
- Important findings / decisions: box bị crop ra ngoài ảnh hoặc quá nhỏ sau quy đổi bị từ chối trước khi ghi; cover có SHA sai / file thiếu không âm thầm quay về PKG2. Hai file được replace riêng, kiểm SHA ngăn phục vụ dữ liệu lệch nếu tiến trình bị ngắt giữa hai lần replace; ghi metadata lỗi thông thường đã có rollback được test.
- Known limitations / lệnh chưa chạy:
  - `<prefix> -n auto` (full suite) và `<prefix> tests/test_web_episode_thumbs.py` đầy đủ (7 test HTTP TestClient): không chạy vì ràng buộc không socket / loopback của sandbox; ORCHESTRATOR cần chạy ngoài sandbox. Các service test đã chạy riêng.
  - Chạy thật cài 4 mẫu VLT / Địa Tạng × 2 khổ và HUMAN LEAD duyệt ảnh tập 1 / 51 / 102: còn chờ ORCHESTRATOR; IMPLEMENTER chỉ dùng ảnh tổng hợp cục bộ.
- Chạy thật (ORCHESTRATOR, 2026-10-28): `cover install` 4 mẫu — VLT `PLOynZc0cJJfA3FSfw_GxZ7uG2cGdDwRR_` (`vlt-vertical.png` box 305,1630,470,125; `vlt-landscape.png` 200,726,530,118 → 133,484,354,79 sau chuẩn hoá 1280×720), Địa Tạng `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4` (`kdt-alt-a.png` 210,1724,660,88; `kdt-alt-a-landscape.png` 170,754,655,82 → 113,503,437,54). Box đo bằng mắt trên ảnh phóng to, thu vào trong viền hoa văn. Dựng thử tập 1 / 51 / 102 / 374 bằng `cover.build_episode` vào thư mục tạm (không ghi `thumbs/` tập thật): với 60 % chiều cao chữ quá nhỏ (khung ngang Địa Tạng chỉ cao 54 px) → ORCHESTRATOR đổi thành hằng `FIT_HEIGHT` 0.85 (`FIT_WIDTH` 0.8 giữ), `COVER_LAYOUT_VERSION` 2, test dùng hằng. Ảnh xem trước: `~/.local/share/auto-short/covers/preview-2026-10-28/`. Test packaging / thumbnail / episode / web thumbs / VERT2 intro / publish thumbs: **265 passed**. Full suite `-n auto`: **3320 passed, 1 skipped** (182 s). HUMAN LEAD duyệt ảnh: chờ; HUMAN LEAD thấy số tập kiểu old-style của Playfair SC khó đọc → so 4 font có sẵn, HUMAN LEAD chọn Old Standard (layout v3).
- PR: chưa tạo theo chỉ thị.
