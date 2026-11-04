# Task: IMG4 — Hình AI vẽ đa dạng: chọn phong cách hoặc trộn ngẫu nhiên

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S2 (sửa D-IMG1-3 trong `docs/decisions/CP8.15-community-post-contract.md`)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex, mặc định của project (HUMAN LEAD 2026-10-25); hết quota thì subagent `implementer`
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-04 (chat): "AI vẽ hình bìa đăng hiện theo phong cách cố định (10 hình), có cách nào cho hình đa dạng hơn (hoặc có option để đổi phong cách)"; chọn phương án "Ô chọn + Ngẫu nhiên"
- Parallel group: —
- Owned paths: `src/auto_short/post/imggen.py`, `src/auto_short/web/post_image_gen.py`, route vẽ ảnh trong `src/auto_short/web/` (chỉ phần nhận tham số), `src/auto_short/web/static/thumbs.html`, `thumbs.js`, `app.js` (chỉ ô vẽ AI), `tests/test_imggen_img1.py`, `tests/test_web_imggen_img1.py`, `docs/decisions/CP8.15-community-post-contract.md` (chỉ D-IMG1-3), file này
- Dependencies: none
- Base commit / branch: `895e7ce` (origin/main) / `feature/img4-image-styles`
- Human Lead approval: accepted 2026-11-04 (chat: "Duyệt cả hai")
- Implementation authorized: YES

## Goal

Ở ô "Vẽ AI", người dùng chọn **Phong cách** (mặc định "Trộn ngẫu nhiên") và có thể gõ thêm mô tả. Mỗi lần vẽ ra 10 ảnh trông khác nhau rõ rệt, khác cả lần vẽ trước với cùng từ khóa.

## Scope

- In scope:
  - Danh mục cố định khoảng 16 phong cách (id, nhãn tiếng Việt, mô tả prompt). Danh mục gồm "Tịnh Độ rực rỡ" (đúng 5 kiểu hiện tại, chọn kiểu này thì prompt giữ y như nay), thủy mặc, Thangka, sơn mài Việt Nam, bích họa Đôn Hoàng, màu nước, khắc gỗ / Đông Hồ, kính màu (vitrail), tối giản nhiều khoảng trống, hoàng hôn điện ảnh, tranh lụa Việt, chạm khắc đá / phù điêu, ánh nến ấm, giấy cắt nhiều lớp, thiếp vàng, sương sớm. Danh sách cuối do ORCHESTRATOR chốt trong review.
  - "Trộn ngẫu nhiên": chọn 10 phong cách khác nhau. Ưu tiên phong cách chưa dùng trong các lượt vẽ gần nhất của cùng từ khóa (đọc `state` lượt cũ trong cache, trong khoảng `candidate_ttl_hours`), dùng hết rồi mới quay vòng.
  - Chọn một phong cách: cả 10 ảnh theo phong cách đó, mỗi ảnh một bố cục / góc nhìn khác (toàn cảnh, cận cảnh, góc thấp, từ trên cao, chi tiết biểu tượng…).
  - Ô "Mô tả thêm" (tùy chọn, ≤ 200 ký tự). Nội dung này đi vào khối dữ liệu không tin cậy (BEGIN_DATA_JSON), không ghép thẳng vào chỉ thị.
  - Lưu `style` (id hoặc `random`), danh sách phong cách đã dùng cho từng ảnh và `extra` vào `state.json` / `meta.json`. Mỗi ảnh ứng viên hiện nhãn phong cách của nó.
  - Sửa D-IMG1-3 theo cách mới.
- Out of scope: đổi kích thước / tỉ lệ / số ảnh (vẫn 10, vuông 1:1, 1024×1024); đổi kiểm tra ảnh (P5a, trùng sha, symlink); model / công cụ khác ngoài Codex; ảnh cho thumbnail video, bản dọc.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` D-IMG1-3, sửa trong task này: phong cách lấy từ danh mục, theo lựa chọn của người dùng; mặc định trộn ngẫu nhiên 10 phong cách khác nhau.
- Giữ các ràng buộc an toàn của IMG1: không vẽ người thật, không chữ / logo, chỉ ghi file trong thư mục làm việc, từ khóa và mô tả thêm là dữ liệu không tin cậy.

## Implementation approach

- `imggen.STYLES`: tuple các phong cách. `prompt(keyword, style="random", extra="", recent=())` trả về prompt và danh sách 10 phong cách đã chọn. Phần ràng buộc chung (không người thật, không chữ, tên file `image-N.png`) dùng lại nguyên văn.
- Chọn ngẫu nhiên bằng `random.Random` có thể truyền seed, để test xác định được kết quả.
- `create(config, keyword, style=..., extra=...)` kiểm `style` thuộc danh mục hoặc `random`, kiểm độ dài `extra`. Web truyền 2 tham số mới; thiếu tham số thì mặc định `random`.

## Phải giữ nguyên

- Toàn bộ luồng chọn / cài ảnh P5c, kiểm tra ảnh, hủy vẽ, trạng thái `running/done/failed/cancelled`, đếm tokens.
- Chọn "Tịnh Độ rực rỡ" thì ra đúng prompt hiện tại (test so chuỗi).

## Code bị thay / xóa

- Chuỗi prompt cố định 5 phong cách × 2 bố cục trong `imggen.prompt`: chuyển thành mục "Tịnh Độ rực rỡ" của danh mục, không giữ bản sao.

## Acceptance Criteria

1. Web có ô chọn phong cách (mặc định "Trộn ngẫu nhiên") và ô mô tả thêm. Lượt vẽ gửi cả hai lên server.
2. `random`: prompt có 10 phong cách khác nhau. Với cùng từ khóa, lượt sau ưu tiên phong cách chưa dùng ở lượt trước (test có seed + lượt cũ trong cache).
3. Một phong cách cụ thể: prompt yêu cầu 10 bố cục khác nhau của phong cách đó. "Tịnh Độ rực rỡ" ra đúng prompt cũ.
4. `style` lạ, hoặc `extra` > 200 ký tự / có ký tự điều khiển: trả lỗi tiếng Việt, không tạo lượt vẽ. `extra` chỉ nằm trong khối dữ liệu JSON.
5. `state.json` / `meta.json` có `style`, `styles` (theo ảnh), `extra`. Ứng viên hiện nhãn phong cách.
6. D-IMG1-3 được cập nhật. Test IMG1/IMG2 cũ vẫn PASS hoặc được cập nhật theo AC 3.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest tests/test_imggen_img1.py tests/test_web_imggen_img1.py -q`, chứng minh AC 1–5
- Full suite (ORCHESTRATOR chạy ngoài sandbox)
- Chạy thật 1 lượt "Trộn ngẫu nhiên" + 1 lượt một phong cách trên 8080, gửi ảnh mẫu cho HUMAN LEAD

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API ngoài (chỉ thêm tham số cho route nội bộ của web). Manual test là điểm danh.

- [ ] Vẽ "Trộn ngẫu nhiên" 2 lần cùng từ khóa: 2 lô trông khác nhau
- [ ] Vẽ 1 phong cách cụ thể: 10 ảnh cùng chất liệu, khác bố cục

## Result

- Main changes: `imggen.STYLES` 16 phong cách (`tinh-do` = 5 kiểu × 2 bố cục cũ), `LAYOUTS` 10 bố cục; `prompt(keyword, style, extra, recent, rng)` trả prompt + phong cách theo ảnh; `random` chọn 10 kiểu, kiểu chưa dùng / lâu chưa dùng của cùng từ khóa trong cache còn hạn trước (`_recent_styles`). `create` kiểm `style` / `extra`; state / meta có `style`, `styles`, `extra`; ứng viên có `style`, `style_label`. Route `POST /api/post-images/generate` nhận `style`, `extra`; danh mục trả trong `generate.styles`. UI `app.js`: ô chọn phong cách, ô mô tả thêm, nhãn dưới ứng viên. D-IMG1-3 cập nhật.
- Tests (ORCHESTRATOR, ngoài sandbox, 2026-11-04): `test_imggen_img1.py` + `test_web_imggen_img1.py` 96 passed; full suite `--deselect` test chập chờn đã biết (chạy riêng PASS): **4024 passed, 1 skipped** (26:30).
- AC → test: AC1 `test_shared_image_ui_style_controls_submission_and_labels`, `test_generate_route_parameters_without_http_transport`; AC2 `test_random_seed_unique_styles_and_least_recent_rotation`, `test_random_uses_same_keyword_cache_within_ttl`; AC3 `test_specific_style_has_ten_distinct_layouts`, `test_tinh_do_prompt_matches_original_verbatim`; AC4 `test_invalid_style_or_extra_creates_nothing`, `test_extra_only_in_untrusted_json_and_persisted`; AC5 `test_ten_candidates_files_thumbs_and_add_only_picked`; AC6 D-IMG1-3 + test IMG1/IMG2 cũ PASS.
- Diff + / −: app +140 / −30, test +227 / −8, docs +1 / −1.
- Helper mới: `_recent_styles` (lọc lịch sử phong cách theo từ khóa / TTL; tái dùng `_runs`, `imgsearch.tokens`).
- Review: ORCHESTRATOR thêm một câu hướng dẫn khi có `extra` (trước đó `extra` chỉ nằm trong khối dữ liệu, không câu nào bảo dùng) + test. Implementer: Codex 1 vòng (effort high, 84.470 tokens).
- Known limitations: chưa vẽ thật trên 8080 (chờ HUMAN LEAD cho restart).
- PR:
