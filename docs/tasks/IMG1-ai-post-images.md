# Task: IMG1-ai-post-images — Thư viện ảnh bài đăng: nhập từ khóa, Codex vẽ 5 ảnh, người dùng duyệt

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`, module mới, spec rõ; quota còn); dự phòng subagent `implementer` (Sonnet) cho test web / socket
- Authorization mode: boundary
- Authorization source: HUMAN LEAD 2026-11-01: "tôi muốn có thêm chức năng cho codex tạo hình thêm cho thư viện bài đăng, Chỉ cần user nhập keywork AI tạo thêm 5 ảnh, người dùng duyệt. Hiện tại đã có chức năng tìm hình trên web có thể tận dụng feat này nếu tiện"; trả lời gate cùng ngày: "Không vẽ mặt" (kèm đồng ý bắt đầu), khổ = "khổ phù hợp nhất với bài post youtube".
- Parallel group: —
- Owned paths: `src/auto_short/post/imggen.py` (mới), `src/auto_short/web/post_image_gen.py` (mới), `src/auto_short/web/routes/post_images.py`, `src/auto_short/web/app.py` + `src/auto_short/web/context.py` (chỉ nối service), `src/auto_short/web/static/app.js` + `src/auto_short/web/static/posts.html` (chỉ hộp thoại "Thư viện ảnh"), `tests/test_imggen_img1.py` (mới), `tests/test_web_imggen_img1.py` (mới), `docs/decisions/CP8.15-community-post-contract.md` (mục P5e mới, P13, dòng Implementation tham chiếu), contract này
- Dependencies: CP8.30 (P5c ứng viên), THUMB1 (`cover_suggest.run_codex`, `[thumbs]`, `EpisodeThumbs.codex_lock`)
- Base commit / branch: `a6837e3` (`origin/main`) / `feature/img1-ai-post-images`
- Human Lead approval: inherited from boundary (nguồn ở trên)
- Implementation authorized: YES

Lifecycle: `DRAFT → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm route API và thêm một chỗ web gọi Codex (quota ChatGPT của HUMAN LEAD); thêm rule nội dung ảnh AI vào contract CP8.15.

## Goal

Trong hộp thoại "Thư viện ảnh": nhập từ khóa, bấm **"AI vẽ 5 ảnh"** → vài phút sau có tối đa 5 ảnh vuông trong lưới ứng viên đang dùng cho tìm ảnh → bấm chọn ảnh ưng ý, "Thêm vào thư viện". Ảnh không chọn không vào thư viện.

## Scope

- In scope: nút + tiến độ + hủy trên UI; job nền gọi Codex; lọc ảnh; lưu ứng viên; xem lại lượt gần nhất khi mở lại hộp thoại; ghi nguồn ảnh AI vào `sources.tsv`.
- Out of scope: chọn phong cách / số ảnh / khổ ảnh trên UI; góp ý vẽ lại; lưu keyword thành lịch sử; tự gán ảnh vào bài; đổi P5b / P5c; thêm config mới; thêm dependency.

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P5a, P5c, P13 (canonical; task thêm P5e).
- D-IMG1-1: dùng lại ô từ khóa và lưới ứng viên P5c. Ứng viên AI lưu đúng định dạng P5c trong `<image_dir>-candidates/<search_id>/`, nên route file ứng viên và `POST /api/post-images/candidates/add` chạy nguyên, không sửa.
- D-IMG1-2 (HUMAN LEAD): không vẽ mặt / chân dung người thật. Từ khóa là người thật → vẽ cảnh hoặc biểu tượng (hoa sen, chùa…). Phật, Bồ Tát vẽ bình thường. Như THUMB1: không chữ, không logo, không watermark (AI viết sai dấu tiếng Việt).
- D-IMG1-3 (HUMAN LEAD: "khổ phù hợp nhất với bài post youtube"): vuông 1:1, `1024×1024` (khổ gốc của công cụ vẽ, ≥ 600 px của P5a). YouTube không công bố thông số chính thức; đa số hướng dẫn bên thứ ba khuyên 1:1 vì hiển thị tốt trên điện thoại. 5 ảnh khác phong cách rõ rệt.
- D-IMG1-4: không dùng hàng đợi job. Một lượt Codex mất nhiều phút (THUMB1 đo 8 phút 16 s cho 4 ảnh), nếu chạy ở làn `prepare` sẽ chặn ingest. Dùng thread riêng như `EpisodeThumbs.suggest` và **dùng chung `EpisodeThumbs.codex_lock`**: toàn web chỉ một lượt Codex; đang bận → 409.
- D-IMG1-5: dùng lại `[thumbs]` (`enabled`, `codex_bin`, `codex_model`, `codex_effort`, `codex_timeout_minutes`), `cover_suggest.available`, `cover_suggest.run_codex`. Không thêm config.
- D-IMG1-6: nguồn ảnh trong `sources.tsv` là `codex-ai:<từ khóa urlquote>` (vẫn 2 cột, không khoảng trắng); `origin` ứng viên = `"codex"`.
- D-IMG1-7: từ khóa là dữ liệu không tin cậy: đặt trong khối dữ liệu JSON `ensure_ascii` với chỉ thị không thực thi, như `cover_suggest.prompt`.

## Implementation approach

`post/imggen.py` (không phụ thuộc web):

- `prompt(keyword)`; `create(config, keyword)` → sinh `search_id` bằng `imgsearch.new_search_id`, `purge_old` theo `candidate_ttl_hours`, ghi `state.json`; `execute(config, search_id, *, runner=None, cancel=None)`; `state(...)`; `latest(config)`; `recover(config)` (lượt `running` khi khởi động → `failed`, "máy chủ khởi động lại").
- `execute` chạy trong `tempfile.TemporaryDirectory`, gọi `cover_suggest.run_codex`, kiểm `image-1.png`…`image-5.png`, mỗi ảnh độc lập: không symlink, đúng tên, `images.validate`, tỉ lệ 1:1 ± 6 %; bỏ trùng sha256 với thư viện (`imgsearch.library_index`) và trong lô. Ảnh đạt: lưu `<id>.png` + `<id>.thumb.jpg` (`dhash.thumbnail`), `meta.json` dạng `SearchOutcome.to_dict()`, `skipped` là lý do, `sources: {"codex": n}`. ≥ 1 ảnh đạt → `done`; 0 ảnh → `failed` kèm lý do. Lưu `prompt.md`, `codex.log` và số token trong thư mục lượt (không phục vụ qua HTTP).

`web/post_image_gen.py`: service nhỏ giữ thread, `cancel` Event, seam `codex_runner`; lấy `EpisodeThumbs.codex_lock` không chờ.

Route (cookie CP8.3 W2):

- `POST /api/post-images/generate {keyword}` → 202 `{run}`; 422 từ khóa rỗng; 503 Codex không dùng được (lý do của `available`); 409 Codex bận.
- `GET /api/post-images/generate/latest` → `{run}` lượt mới nhất hoặc `{run: null}`. Với lượt `done` chỉ trả ứng viên chưa có trong thư viện; không còn ứng viên → `null`. Lượt mới nhất có `dismissed: true` → `null`, không lùi về lượt cũ hơn.
- `GET /api/post-images/generate/{search_id}` → `{run}`; id sai → 404.
- `POST /api/post-images/generate/{search_id}/cancel` → `{run}`; 404 khi id sai.
- `POST /api/post-images/generate/{search_id}/dismiss` → `{run}`; lưu `dismissed: true` trong `state.json`, không xóa file (purge theo TTL như cũ); 404 khi id sai; lượt `running` → 409 ("lượt đang chạy", dùng `cover_suggest.Busy`).
- `run` = `{search_id, keyword, status, error, tokens, candidates, skipped, notes, sources}` (`status`: `running` | `done` | `failed` | `cancelled`), `candidates` cùng khóa với `GET /api/post-images/find/{job}`.
- `GET /api/post-images` thêm `generate: {unavailable: <lý do | null>}`.

UI: nút "AI vẽ 5 ảnh" cạnh "Tìm theo từ khóa", cùng ô từ khóa; `unavailable` → nút tắt, `title` là lý do. Đang chạy: thông báo "Codex đang vẽ… có thể đóng hộp thoại, quay lại sau" + nút "Hủy". Mở hộp thoại: gọi `latest`; đang chạy thì poll tiếp (3 s, dừng khi đóng hộp thoại), `done` thì hiện lưới bằng `renderCandidates`.

## Phải giữ nguyên

- `/api/post-images/find`, `/search`, `/candidates/add`, `/files/post-image-candidates/…`, `imgsearch.run_search`: hành vi và response cũ (`GET /api/post-images` chỉ thêm khóa).
- `cover_suggest` không đổi; lượt gợi ý bìa vẫn chạy như cũ, chỉ loại trừ lẫn nhau với lượt vẽ ảnh qua `codex_lock`.
- Không ảnh nào vào thư viện khi chưa được chọn. Không sinh job trong runner, không ảnh hưởng hàng đợi.
- Không chạy Codex với `danger-full-access`; không log ra ngoài thư mục lượt.

## Code bị thay / xóa

Không có (chỉ thêm mới; `runKeywordFind` / `renderCandidates` dùng lại).

## Acceptance Criteria

1. Runner giả ghi 5 PNG vuông hợp lệ → `done`, 5 ứng viên, `origin` `codex`; file + thumb phục vụ qua route ứng viên P5c.
2. Chọn 2 ứng viên → `candidates/add` thêm đúng 2 ảnh theo số tiếp theo; `sources.tsv` có `codex-ai:<urlquote>`; 3 ảnh còn lại không vào thư viện.
3. Ảnh lỗi từng phần (không phải ảnh, không vuông, < 600 px, symlink, trùng thư viện, trùng lô) → bị loại kèm `skipped`, ảnh còn lại vẫn dùng được; 0 ảnh đạt → `failed` có lý do.
4. Prompt có từ khóa trong khối dữ liệu `ensure_ascii`, có quy tắc không vẽ người thật / không chữ, yêu cầu 1024×1024 và 5 phong cách; từ khóa chứa chỉ thị / dấu nháy / xuống dòng không thoát khỏi khối dữ liệu.
5. Từ khóa rỗng → 422; `available` báo lỗi → 503 và nút tắt có lý do; `codex_lock` đang giữ → 409; lock luôn được nhả sau `done` / `failed` / `cancelled` / lỗi lúc tạo lượt.
6. Hủy → `cancelled`, tiến trình Codex bị dừng; `CodexFailed` → `failed`, `codex.log` còn; khởi động lại khi `running` → `failed`.
7. `latest` trả lượt đang chạy; lượt `done` đã thêm hết → `null`; `search_id` sai dạng / path traversal → 404.
8. Không tạo job trong runner; test P5c, THUMB1 hiện có PASS không sửa.

## Required verification

- IMPLEMENTER: `PYTHONPATH=<worktree>/src python -m pytest -q -x --tb=short tests/test_imggen_img1.py`; `node --check src/auto_short/web/static/app.js`.
- ORCHESTRATOR (ngoài sandbox): `tests/test_web_imggen_img1.py tests/test_web_imgsearch_cp830.py tests/test_imgsearch_cp830.py tests/test_cover_suggest.py tests/test_web_episode_thumbs.py`; `python -m pytest -q -n auto`; `node scripts/framework-check.mjs`; chạy thật một lượt Codex trên thư mục ảnh tạm (không đụng thư viện thật).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model. Thêm route public API trong cùng cookie auth: manual test sau automated verification là điểm danh.

- [ ] Nhập "hoa sen", bấm "AI vẽ 5 ảnh", đóng rồi mở lại hộp thoại, thấy tiến độ / kết quả.
- [ ] Chọn ảnh → "Thêm vào thư viện" → ảnh có trong lưới thư viện.
- [ ] Nhập "Hòa thượng Tịnh Không" → ảnh không có mặt người.

## Handoff

Không dùng.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
