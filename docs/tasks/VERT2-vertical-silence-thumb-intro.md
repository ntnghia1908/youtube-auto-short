# Task: VERT2-vertical-silence-thumb-intro — Bản dọc cắt khoảng lặng + 3 giây thumbnail đầu video

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, render + kho); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "Bản dọc tôi cần cắt khoảng lặng", "Thumbnail … ghép thẳng vào video … gắn hình vào đầu video khoảng 3 giây đầu"; chọn G1–G3 bên dưới cùng ngày
- Parallel group: —
- Owned paths: `src/auto_short/render/full.py`, `src/auto_short/store/offload.py`, `src/auto_short/store/client.py` (`put`: kind `vertical`), `tools/store/store.py` (quy tắc bản mới cho kind `vertical`), `src/auto_short/web/routes/episodes.py` (`api_episode_vertical_make`), `tests/test_vertical_silence_intro.py`, test hiện có của các module trên khi khẳng định hành vi bị thay, contract này
- Dependencies: VERT1 (PR #177, nhánh nền), CP7 (rút lặng Short), PKG2 (thumbnail tập), HD2b (offload), SHO1b B1 (bản `(rN)` trên kho)
- Base commit / branch: `d9298e7` (`feature/vert1-header-fallback`) / `feature/vert2-silence-thumb-intro`
- Human Lead approval: APPROVED 2026-10-28 (G1–G3)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi nội dung mọi bản dọc mới (thời lượng, khung đầu) và hợp đồng kho 3090 cho kind `vertical` (PUT khác sha → bản mới), mở rộng sửa đổi SHO1 G1.

## Quyết định HUMAN LEAD (2026-10-28)

- **G1 Khoảng lặng**: như Short — đoạn lặng dài hơn `max_pause` (tham số của `candidates.json`, hiện 1,0 s) rút còn `max_pause`; dữ liệu `silences.json` của tập (cùng kiểm `silences_sha256` như `render.stage.load_silences`).
- **G2 Thumbnail**: **thêm** 3 giây ảnh thumbnail dọc 9:16 (PKG2) **trước** video, tiếng im lặng; video dài thêm 3 s.
- **G3 Bản cũ**: bản dọc VLT chưa đăng làm lại (mượn HD từ kho, render lại, đẩy bản mới); bộ khác giữ nguyên trừ khi HUMAN LEAD bấm. Kho giữ file cũ (HD2 G1 "không xóa qua API"); bản mới `… (r2).mp4` như SHO1b B1.
- Ghi chú ORCHESTRATOR (đã báo HUMAN LEAD): YouTube không đảm bảo lấy khung đầu làm thumbnail video dài; gắn tự động chắc chắn vẫn là PUB2 (chờ `youtube-client.json`).

## Goal

Bản dọc mới = 3 s ảnh thumbnail dọc của tập (im lặng) + toàn tập đã rút khoảng lặng như Short, khung tiêu đề / người giảng như hiện tại. Bản dọc cũ (plan version trước) không còn "hiện hành": bấm "Tạo bản dọc" của tập (kể cả khi bản cũ đã ở kho) dựng lại và đẩy lên kho thành bản mới.

## Scope

- In scope:
  - **A cắt lặng**: segments = `review.cuts.kept_segments_ms(0, duration, silences, max_pause)` (tái dùng); biên đoạn làm tròn theo khung (`render.plan.frame_plan` hoặc tương đương) và audio cắt **đúng cùng mốc thời gian** đó → không lệch tiếng/hình tích lũy. Filter **dạng luồng** (`select`/`aselect` + `setpts`/`asetpts`, hoặc `trim` theo luồng) — **không** dùng `asplit`/`split` N nhánh + `concat` như Short (video 1 giờ, hàng trăm đoạn → đệm khung hình tràn RAM). Thiếu `silences.json` / `candidates.json` / sha không khớp → `RenderError` rõ ràng.
  - **B intro**: ảnh dọc từ `packaging.episode` (bộ kinh chứa video; `read_settings` → mặc định nếu chưa lưu; `build_episode` nếu chưa có / cũ); 3 s ảnh (scale/pad đúng khung bản dọc, cùng fps / pix_fmt) + `anullsrc` cùng sample rate / layout; ghép trước nội dung. Không dựng được ảnh (`PackageError` / header lỗi) → render không intro, `vertical.json` `intro: null` + log cảnh báo.
  - **C key / meta / hiện hành**: `FULL_PLAN_VERSION` tăng; key gồm max_pause, sha `silences.json`, sha ảnh intro, độ dài intro; `vertical.json` thêm `plan_version`, `intro` (sha ảnh / giây), `trimmed_seconds`. `current()` đòi `plan_version == FULL_PLAN_VERSION` (bản cũ không có → không hiện hành); `verify()` kiểm thời lượng mong đợi (intro + tổng segments).
  - **D offload**: bản dọc local không hiện hành → bỏ qua lặng lẽ (không lỗi lặp, không đẩy, không release).
  - **E route tập**: `POST /api/episodes/{id}/vertical` khi kho có bản dọc **nhưng** bản local / meta không hiện hành → xếp job dựng lại (không còn trả sớm); hiện hành → giữ trả sớm như cũ.
  - **F kho**: `StoreClient.put` kind `vertical` khác sha → gửi PUT; `tools/store/store.py`: kind `vertical` khóa đã có file khác sha → ghi bản mới `… (rN).mp4` (số nhỏ nhất chưa dùng), index trỏ sang bản mới, file cũ giữ trên đĩa và `SHA256SUMS.txt` — đúng quy tắc SHO1b B1 của `short`; `hd` / kind khác giữ 409.
  - Test.
- Out of scope: bản HD ngang (không ghép intro); PUB2; tự xếp làm lại hàng loạt (vận hành sau merge, ORCHESTRATOR làm theo danh sách HUMAN LEAD); UI mới; đổi tham số `max_pause`; chỉnh giao diện thumbnail VLT ("Đóng gói" — việc riêng HUMAN LEAD đã hẹn).

## Authority / key decisions

- G1–G3 trên; CP7 (rút lặng), PKG2 / PKG2.1 (thumbnail tập), HD2 G1, SHO1b B1, HD2b D2.

## Implementation approach

- `full.py`: tách hàm thuần dựng segments / filter (test được không cần ffmpeg); ffmpeg 3 input (HD, ảnh `-loop 1 -t 3`, `anullsrc`), filter script như hiện tại.
- Nếu tái dùng hàm từ `render.plan` thì không đổi hành vi Short.

## Phải giữ nguyên

- Short: plan, filter, key, test.
- VERT1: header không cần `titles.json`; tên file tải về.
- HD2a mượn HD từ kho cho tập đã giải phóng; HD2b release sau khi kho xác nhận.
- Kho: `short` (rN) như SHO1b; `hd` vẫn 409 khi khác sha.

## Code bị thay / xóa

- Nhánh dựng bản dọc liền mạch không cắt (filter cũ một đoạn) trong `full.py` → thay bằng filter có segments + intro.
- Nhánh `if render_full.on_store(...) is not None: return` vô điều kiện trong `api_episode_vertical_make` → chỉ khi hiện hành.
- `client.put` `if kind != "short": raise StoreMismatch(...)` → `kind not in ("short", "vertical")`.

## Acceptance Criteria

1. Hàm segments: silences giả (gồm lặng ngắn hơn / dài hơn `max_pause`, lặng đầu / cuối) → segments đúng như `kept_segments_ms`; biên đã làm tròn khung; audio / video dùng cùng mốc.
2. Render thật bằng ffmpeg (clip tổng hợp vài giây có đoạn câm): file ra dài = 3 s + tổng segments (± 1 khung); 3 s đầu là ảnh (so màu / khung đầu), tiếng 3 s đầu im lặng; chênh lệch thời lượng audio / video ≤ 1 khung.
3. Không dựng được ảnh → file ra không intro, `intro: null`, vẫn cắt lặng.
4. `vertical.json` cũ (không `plan_version`) → `current()` False; offload bỏ qua không lỗi; route tập khi kho có bản cũ → xếp job (202); khi hiện hành → không xếp.
5. Kho: PUT `vertical` khác sha → bản `(r2)`, HEAD trả bản mới, file cũ còn; `hd` khác sha → 409; `client.put` vertical khác sha gửi PUT.
6. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_vertical_silence_intro.py tests/test_web_hd_cp827.py tests/test_web_vertical_cp832.py tests/test_vertical_header_fallback.py tests/test_store_offload.py tests/test_store_client.py` + test kho (`tools/store`) — AC 1–5.
- `… -m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR): 1 tập VLT render bản dọc mới; đo thời lượng trước / sau, xem 3 s đầu + vài điểm cắt (nghe có giật không); đẩy lên kho thành `(r2)` — sau khi HUMAN LEAD chép `store.py` mới lên 3090.

## Manual test checklist (Tech Lead)

Chạm hợp đồng kho 3090 (API nội bộ, không public) → manual test sau chạy thật.

- [ ] Nghe 2–3 điểm cắt lặng trên bản dọc mới: nhịp tự nhiên, không giật tiếng.
- [ ] 3 s đầu: ảnh thumbnail đúng tập.
- [ ] Kho 3090: thư mục bộ kinh có bản `(r2)`, bản cũ còn.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
