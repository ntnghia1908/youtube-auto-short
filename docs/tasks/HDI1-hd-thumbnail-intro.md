# Task: HDI1-hd-thumbnail-intro — Bản HD trên kho 3090 có 3 giây thumbnail đầu video (thay bản HD)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, nhiều module đọc HD + giao thức kho); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tạo thêm 1 bản địa tạng hd để tôi test trước" → xem bản thử `output/_samples/dt-hd-intro/DiaTang_Tap1_HD_intro.mp4` → "Ok viết task riêng" → "G1 a. G2 b nhưng chỉ dùng cho địa tạng làm 1 bản test trước. Hiện tại địa tạng hd đã có trên 3090" → "Bản HD intro đè luôn bản HD" → chọn "Đè + ghi độ lệch"
- Parallel group: —
- Owned paths: `src/auto_short/render/hd_intro.py` (mới), `src/auto_short/enhance/state.py` (`EffectiveSource` thêm độ lệch + sha lưu kho; đọc `hd_intro.json`), mọi chỗ đọc file HD để render: `src/auto_short/render/full.py`, `src/auto_short/render/stage.py`, `src/auto_short/theme_index/__init__.py`, `src/auto_short/store/borrow.py`, `src/auto_short/review/backup.py` (chỉ sha HD đã giải phóng), `src/auto_short/store/client.py` (thao tác thay thế), `tools/store/store.py` (thay thế có kiểm sha cũ), `src/auto_short/web/routes/episodes.py` + `src/auto_short/web/app.py` / `src/auto_short/web/jobs.py` (route + kind job `hd_intro`), `src/auto_short/web/static/` (chỉ nút trên trang tập), `src/auto_short/config.py` + `config.example.toml` (mục `[hd_intro]`), `tests/test_hd_intro.py` (mới) + test hiện có của các module trên (chỉ thêm ca độ lệch / thay thế), contract này
- Dependencies: THUMB1 (#182, thumbnail tập khổ ngang qua `episode.valid_files`), VERT2 (`render/full.intro_image`), HD1 / HD2a / HD2b (HD đã giải phóng, mượn HD từ kho)
- Base commit / branch: `721fb7f` (xếp chồng trên THUMB1 #182, chưa merge) / `feature/hdi1-hd-intro`; PR base đổi sang `main` sau khi THUMB1 merge
- Human Lead approval: APPROVED 2026-10-29 (G1 a, G2 = đè bản HD trên kho + ghi độ lệch, chỉ Địa Tạng, 1 bản test trước)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (1) thay **dữ liệu gốc** trên kho 3090 (bản HD) — bản cũ mất sau khi thay; (2) mọi đường đọc HD (bản dọc, Short, video ghép chủ đề, mượn HD) phải bù độ lệch; (3) giao thức kho thêm thao tác thay thế (HUMAN LEAD chép `tools/store/store.py` lên 3090).

## Goal

Với bộ kinh bật trong config (hiện chỉ Địa Tạng `PLOynZc0cJJfDMY5-Fd0su_Ea3TGdZ2wk4`), trang tập có nút "Tạo HD có intro": job dựng bản HD ngang có 3 giây đầu là thumbnail tập khổ ngang (Bồ Tát + "TẬP N"), phần bài giảng giữ nguyên gói (không encode lại), rồi **thay bản HD trên kho 3090**. Sau đó "Tải HD" trả bản có intro; bản dọc / Short / video ghép vẫn dựng đúng mốc thời gian (bỏ phần intro). Làm **1 tập test trước** (Địa Tạng tập 1), HUMAN LEAD duyệt rồi mới làm cả bộ.

## Scope

- In scope:
  - **`render/hd_intro.py`**: HD hiệu lực (mượn từ kho như HD2a) + thumbnail ngang hợp lệ (`episode.valid_files`, dựng nếu thiếu như `full.intro_image`) → intro đúng `round(3 × fps)` khung (90 khung = 3,003 s ở 30000/1001) cùng codec / profile / kích thước / pix_fmt / timescale với HD; âm im lặng cùng codec (aac / opus) / sample rate / số kênh, cắt đúng độ dài khung; ghép concat demuxer `-c copy` + `+faststart`. **G1 = a**: HD khác 16:9 (Địa Tạng 1440×1080) → thu thumbnail vừa khung, viền đen. Codec ngoài h264 + aac/opus → lỗi rõ.
  - Kiểm trước khi thay: tổng thời lượng = HD + intro (±1 khung); pts gói đầu của phần HD (hình và tiếng) lệch ≤ 20 ms so với mốc intro; sau khi bỏ `offset` (giải mã thử vài khung đầu / giữa / cuối) khung hình giống HD gốc (`framemd5` hoặc so pixel) — sai → xóa, báo lỗi, không đụng kho.
  - **Ghi nhận độ lệch**: `hd_intro.json` trong workspace owner (cùng chỗ `enhance.json` / `backup.json`): `original` {sha256, size}, `stored` {sha256, size}, `frames`, `fps`, `offset_seconds` (chính xác = frames / fps), `thumb_sha256`, `version`, `replaced_at`. Ghi **trước** khi thay trên kho (trạng thái `pending`), cập nhật `done` sau khi `head` kho khớp sha / size mới; lỗi giữa chừng → lần sau đối chiếu `head` để biết bản nào đang ở kho.
  - **`EffectiveSource`**: thêm `offset` (giây, mặc định 0) và `stored_sha256` (sha bytes trên kho / file); `sha256` (danh tính nội dung) **giữ sha gốc** → cache key bản dọc / Short / video ghép không đổi, 64 bản dọc Địa Tạng không bị coi là cũ.
  - **Mọi đường đọc file HD** áp `offset`: input `-ss <offset>` (giải mã chính xác khung) + trừ khỏi thời lượng probe: `render/full.py` (bản dọc), `render/stage.py` (render / sửa Short, khai thị từ HD), `theme_index` (video ghép chủ đề), bất kỳ chỗ nào probe thời lượng HD. Mượn HD (`store/borrow.py`) kiểm theo `stored_sha256`; `review/backup.py` sha HD đã giải phóng = `stored`.
  - **Kho**: `tools/store/store.py` thêm thay thế có điều kiện: `PUT` loại `hd` kèm header `X-Replace-Sha256: <sha hiện có>` → chỉ thay khi sha hiện có khớp (ghi file tạm rồi `os.replace`, cập nhật `danh-sach.csv`), không khớp → 409; không có header → hành vi cũ (409 khi khác sha). `client.replace(...)`. Server cũ (chưa chép) trả 409 → job báo "cần cập nhật store.py trên 3090", không đổi gì.
  - **Điều kiện chạy**: chỉ tập có HD đã giải phóng lên kho (không có `source_hd.mp4` cục bộ); từ chối khi có job bản dọc / Short / khai thị đang chờ hoặc chạy cho video đó; bộ không bật → 404.
  - **Web**: `POST /api/episodes/{id}/hd-intro` (job làn `render`, kind `hd_intro`), trạng thái trong view HD của trang tập ("HD có intro ✓" / "cần tạo lại" khi thumbnail ngang đổi); nút "Tạo HD có intro". "Tải HD" giữ route `source-hd` (giờ trả bản có intro).
  - **Bản test**: trước khi thay ở tập test đầu tiên, giữ bản HD gốc cục bộ tại `output/_samples/hdi1-original/<id>.mp4` (ngoài cơ chế tự động; ORCHESTRATOR xóa sau khi HUMAN LEAD duyệt).
- Out of scope:
  - Nút "cả bộ" (thêm sau khi HUMAN LEAD duyệt bản test; có thể chỉ gọi route từng tập).
  - Gỡ intro / khôi phục bản gốc tự động; bộ kinh có `source_hd.mp4` cục bộ chưa giải phóng; tự đăng YouTube.

## Authority / key decisions

- VERT2 (intro 3 giây = thumbnail tập), HD1 / HD2a / HD2b (giải phóng / mượn HD), CP8.3 (auth / job / file), HUMAN LEAD 2026-10-29 duyệt bản thử + G1 a + "đè luôn bản HD" + "đè + ghi độ lệch".
- Danh tính nội dung (sha gốc) tách khỏi sha bytes lưu kho: bản dọc / Short đã dựng vẫn hiện hành; độ lệch chỉ ảnh hưởng cách đọc file.
- Thứ tự vận hành: 63 bản dọc Địa Tạng đang chờ (2026-10-29) phải xong trước khi thay HD các tập đó (điều kiện chạy chặn sẵn).

## Implementation approach

- Tách hàm thuần (lệnh ffmpeg từ probe, kiểm thời lượng / pts, `hd_intro.json`) khỏi subprocess; test bằng video nhỏ ffmpeg tạo trong `tmp_path` (h264 + aac và h264 + opus; 16:9 và 4:3); kho giả lập bằng server test hiện có / client giả — không mạng thật.
- Tái dùng: `full.intro_image`, `store.borrow`, `offload.push_vertical` (mẫu đẩy + `head`), `ep.hd_source`, `probe_media`. Quy trình đã chứng minh: `/home/ntnghia/.claude/jobs/1c1feb65/tmp/hd_sample.py` (ops, ngoài repo).
- Một helper chung cho "input HD có offset" (vd. trả `["-ss", str(offset), "-i", path]` và thời lượng đã trừ) để mọi caller dùng, không rải `-ss` thủ công.

## Phải giữ nguyên

- Cache key / tính hiện hành của bản dọc, Short, video ghép chủ đề (danh tính = sha gốc).
- HD chưa có intro: mọi đường đọc byte-identical như trước (offset 0, không thêm `-ss`).
- Giao thức kho cũ (không header thay thế → hành vi cũ); loại / định danh khác không đổi.

## Code bị thay / xóa

- Các chỗ mở file HD trực tiếp trong `render/full.py`, `render/stage.py`, `theme_index` chuyển sang helper input HD có offset (không giữ đường cũ song song).

## Acceptance Criteria

1. HD h264 + aac / opus (16:9, 4:3) → bản có intro: 3 giây đầu là thumbnail ngang (4:3 có viền đen), phần sau giữ nguyên gói, thời lượng đúng ±1 khung, lệch mốc hình / tiếng ≤ 20 ms; codec lạ / thiếu thumbnail / thiếu HD → lỗi rõ, không file dở, không đụng kho.
2. `hd_intro.json` ghi `pending` trước khi thay, `done` sau khi `head` kho khớp; thay lỗi → kho giữ bản cũ hoặc bản mới đúng sha, lần sau tự đối chiếu; bản mượn / tạm bị xóa.
3. Sau khi thay: `EffectiveSource.sha256` = sha gốc, `offset` = frames / fps, `stored_sha256` = sha mới; bản dọc / Short / video ghép dựng từ HD có intro cho **khung hình giống** khi dựng từ HD gốc (test so khung); bản dọc hiện có vẫn "hiện hành"; mượn HD kiểm theo sha mới.
4. Kho: `PUT` `hd` + `X-Replace-Sha256` đúng → thay + CSV cập nhật; sai sha → 409, không đổi; không header → hành vi cũ; client báo rõ khi server chưa hỗ trợ.
5. Route / job: cần đăng nhập; bộ không bật / id lạ → 404; HD chưa giải phóng → 409; đang có job bản dọc / Short / khai thị của video → 409; đổi thumbnail ngang → "cần tạo lại".
6. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix: `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q`.

- `<prefix> tests/test_hd_intro.py` + test kho / borrow / full / stage / theme_index liên quan — AC 1–5 (test socket / web: ORCHESTRATOR chạy ngoài sandbox).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh, sau khi HUMAN LEAD chép `tools/store/store.py` lên 3090 và 63 bản dọc Địa Tạng xong): Địa Tạng tập 1 "Tạo HD có intro" → `head` kho khớp sha mới → tải "Tải HD" so với bản thử đã duyệt; dựng thử 1 Short / đoạn bản dọc từ HD mới so khung với bản cũ; HUMAN LEAD xem 10 giây đầu.

## Manual test checklist (Tech Lead)

- [ ] Trang tập Địa Tạng có "Tạo HD có intro"; sau khi xong "Tải HD" có 3 giây thumbnail, tiếng khớp môi.
- [ ] Bộ khác không có nút.
- [ ] Bản dọc / Short Địa Tạng vẫn hiện "đã có", không đòi dựng lại.

## Result

- (chưa thực hiện)
