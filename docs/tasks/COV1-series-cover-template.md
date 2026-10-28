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
  - `packaging/cover.py`: dựng JPEG một khung bằng ffmpeg (tái dùng `thumbnail._draw_text` / `_encode` / font có sẵn — serif đậm như style A, màu vàng kim + bóng đổ nhẹ để hợp ảnh mẫu), chữ `TẬP {N}` (N = số tập từ `episode.header`), co cỡ chữ cho vừa ~80 % chiều rộng và ~60 % chiều cao box, căn giữa; giới hạn dung lượng `MAX_BYTES` như PKG2.
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

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
