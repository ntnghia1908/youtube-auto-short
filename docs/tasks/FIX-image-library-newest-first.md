# Task: FIX-image-library-newest-first — Thư viện ảnh hiện ảnh mới nhất ở đầu

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1 — thứ tự danh sách trả về của `GET /api/post-images`; không đổi dữ liệu / tên file / dependency
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — ưu tiên Codex (HUMAN LEAD 2026-10-25); quota 5 giờ 6 %, tuần 12 %
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-23: "khi tạo ảnh bằng ai các ảnh mới được thêm vào thư viện nên để ở đầu để người dùng không cần cuộn xuống mới xem được ảnh mới"
- Parallel group: —
- Owned paths: `src/auto_short/web/routes/post_images.py` (chỉ `api_post_images`), test mới `tests/test_web_image_library_order.py`, kỳ vọng thứ tự trong `tests/test_web_imgsearch_cp830.py` (ORCHESTRATOR thêm khi verify: test cũ khẳng định thứ tự tên tăng dần mà task này cố ý đổi), file này
- Dependencies: none
- Base commit / branch: `1233704` (origin/main) / `fix/image-library-newest-first` (worktree `~/projects/yas-imgnew`)
- Human Lead approval: accepted 2026-11-23
- Implementation authorized: YES

## Bằng chứng (2026-11-23)

- Thư viện thật: 312 ảnh `01.jpg` … `312.png` (số tăng dần theo `imgsearch.next_name`, rộng 2 rồi 3 chữ số).
- `post_images.list_images` sắp theo tên dạng chuỗi (`sorted(iterdir())`) → thứ tự `01…09, 10, 100…109, 11, 110…`; ảnh mới `307–312` nằm giữa lưới (sau `31`), người dùng phải cuộn tìm.
- Lưới thư viện (trang Thư viện ảnh và hộp chọn ảnh của bài đăng) vẽ đúng thứ tự API trả (`renderImageGrid`).

## Goal

Ảnh vừa thêm vào thư viện (AI vẽ, tìm ảnh, tải lên) hiện ở đầu lưới, ở cả trang Thư viện ảnh và hộp chọn ảnh.

## Scope

- In scope: `GET /api/post-images` trả `images` theo thứ tự mới nhất trước: mtime giảm dần; cùng mtime thì số trong tên giảm dần (tên số đứng trước tên không phải số), rồi tên.
- Out of scope: `post_images.list_images` (giữ thứ tự tên — dùng cho `next_name`, `find_by_sha256`, `post_redistribute.plan`), đổi tên file, JS, giao diện.

## Implementation approach

- Sắp lại `infos` trong `api_post_images` bằng một key nhỏ (stat mtime của `image_dir / name`; file biến mất giữa chừng → mtime 0, không lỗi).

## Phải giữ nguyên

- Các field mỗi ảnh và các key khác của response; `list_images` và mọi nơi gọi nó.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Ảnh có mtime mới hơn đứng trước, bất kể tên (vd `312.png` mới nhất đứng đầu, trước `99.jpg`).
2. Cùng mtime: `100.jpg` trước `99.jpg` trước `abc.jpg`.
3. Thư viện rỗng → `[]`; response giữ nguyên các field.
4. Full suite PASS.

## Required verification

- `PYTHONPATH=<worktree>/src pytest -q tests/test_web_image_library_order.py tests/test_web_imggen_img1.py tests/test_web_post_cp815.py tests/test_web_imgsearch_cp830.py` (ORCHESTRATOR ngoài sandbox — TestClient).
- `pytest -q -n auto` (ORCHESTRATOR) — AC4.

## Manual test checklist (Tech Lead)

- [ ] 8080 = commit của task: trang Thư viện ảnh mở ra thấy ảnh mới nhất (312…) ở đầu.

## Result

- Implementation hoàn tất trên base `1233704`; chờ ORCHESTRATOR verification/review trước READY toàn task.
- `api_post_images` sắp mtime giảm dần, tên số giảm dần trước tên không phải số, rồi tên tăng dần; stat lỗi dùng mtime 0. Không đổi `post_images.list_images` hoặc response fields.
- AC1 → `test_newest_mtime_first_and_response_fields`; AC2 → `test_same_mtime_numeric_descending_then_name`; AC3 → `test_empty_library` + kiểm response trong test AC1. Thêm `test_disappearing_file_uses_zero_mtime` cho file biến mất sau listing.
- Tái dùng `gen_cfg`, `fake_codex`, `make_app`, `login`, `make_png`, `make_jpeg`, `list_images`; tìm bằng `rg -n '^def .*|^from .*import'` và đọc các test/helper liên quan. Helper mới: key cục bộ `newest_first` (chưa có key đúng rule này), fixture `client` để dùng chung app/login trong file test; `list_then_remove` chỉ mô phỏng race stat lỗi.
- PASS: `python -m py_compile src/auto_short/web/routes/post_images.py tests/test_web_image_library_order.py` (cả Python mặc định và env `auto-short`); `git diff --check`.
- Test chưa xác minh: Python mặc định thiếu pytest; `PYTHONPATH=src timeout 20s /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_web_image_library_order.py -x --tb=short` treo, bị timeout (exit 124, không có kết quả test). ORCHESTRATOR chạy required TestClient verification và full suite / AC4 ngoài sandbox. Manual test chưa chạy.
- Diff implementation: route +11/−0; test mới +96/−0. Chỉ sửa hai file được giao và mục Result này; không commit/push/PR, không gọi agent khác hoặc mạng.
- ORCHESTRATOR verification (ngoài sandbox, env `auto-short`):
  - Lần 1: targeted 72 passed / 2 failed; full suite `pytest -q -n auto` 4846 passed / 2 failed — cả 2 là `test_web_imgsearch_cp830.py::test_find_candidates_serve_thumbs_and_add[lanes|serial]` khẳng định thứ tự cũ `01, 02, 03`. Sửa kỳ vọng thành `03, 02, 01` (đúng AC1/AC2; cùng mtime vẫn ra thứ tự này nhờ số giảm dần).
  - Lần 2: targeted **74 passed**; full suite **4848 passed, 2 skipped** (3m01s).
- Thời gian / tokens Codex: 1 vòng, effort medium, 55 988 tokens; không có vòng sửa.
