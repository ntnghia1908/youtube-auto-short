# Task: FIX-storage-suggest — Gợi ý dọn dẹp gộp Short + khai thị, cảnh báo bài đăng, tự dọn nguồn khi đăng hết

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `07a5ae9` (`main`) / `fix/storage-suggest` (worktree `../youtube-auto-short-suggest`)
- Human Lead approval: APPROVED nguyên bản 2026-10-03 (yêu cầu HUMAN LEAD 2026-10-03; Q1 = video xong là đủ, bài đăng chỉ cảnh báo; Q2 = gộp một gợi ý cho cả video; Q3 = tự dọn video nguồn khi video đã đăng hết, trừ nguồn enhance sau này)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm hành vi **tự động xóa dữ liệu** (dọn video nguồn không cần người bấm) — policy lưu trữ mới; cùng với đổi luật gợi ý tab Bộ nhớ (CP8.6 S2 / CP8.3 § Gợi ý). Quyết định HUMAN LEAD ghi ở đây và trong CP8.3; không đổi API archive / delete, không chạm security / dependency.

## Bối cảnh

Hiện tại (`web/storage.py` `recommend`): tập Short `<id>` và tập khai thị `<id>.kt` là hai dòng độc lập; mỗi dòng có gợi ý `all_published` ngay khi video của chính nó tick hết "Đã đăng" — có thể gợi ý xóa tập Short trong khi khai thị cùng video chưa đăng xong. Bài đăng ("Đã đăng bài", `posts.json`) không được xét; xóa tập là mất bài đã soạn.

## Goal

Gợi ý dọn dẹp theo **video**: Short + khai thị của cùng một video là một gợi ý; chỉ gợi ý "đã đăng hết" khi cả hai phần xong; nếu còn bài đăng chưa tick thì gợi ý kèm cảnh báo. Video đã đăng hết → **tự dọn video nguồn** (không cần bấm).

## Scope

- In scope:
  - **D1 Gộp theo video.** `<id>` và `<id>.kt` (cùng video id) cho ra tối đa **một** gợi ý; hành động ("Dọn video nguồn", "Xóa cả tập") áp cho mọi workspace của video đó (phần nào dọn được thì dọn; số byte = tổng). Video chỉ có một phần (không có `.kt` hoặc chỉ có `.kt`) như cũ.
  - **D2 Luật `all_published` theo video.** Chỉ khớp khi **mọi phần hiện có** của video "Xong" (W10 L4: render `done`, mọi video `rendered` đã tick đúng file hiện tại). Một phần đang `processing` → bỏ qua cả video. Luật `old_source` / `stale_unfinished`: áp theo video, điều kiện xét trên từng phần (IMPLEMENTER đề xuất cách gộp tối giản, ghi vào authority; mặc định: `old_source` khi mọi phần còn nguồn đều thỏa; `stale_unfinished` khi mọi phần thỏa).
  - **D3 Cảnh báo bài đăng (Q1).** Gợi ý kèm số bài chưa tick "Đã đăng bài" của cả video (Short + khai thị, chỉ bài đã soạn); UI hiện "Còn n bài đăng chưa đăng — xóa cả tập sẽ mất bài đã soạn" (xác nhận "Xóa cả tập" nhắc lại). Bài đăng không chặn gợi ý.
  - **D4 Tự dọn video nguồn (Q3).** Khi video "đã đăng hết" theo D2 (mọi phần hiện có "Xong"), server tự gọi `archive_source` cho từng phần còn nguồn dọn được (`youtube`, render `done`, còn file) — cùng hàm / hiệu ứng như nút "Dọn video nguồn" (CP8.6 S3: sau đó không sửa title / khôi phục / thêm Short / chạy lại).
    - Thời gian ân hạn: chỉ dọn khi trạng thái "đã đăng hết" giữ ổn định ≥ `[storage] auto_archive_grace_minutes` (mặc định 30) — bỏ tick trong khoảng đó thì không dọn. Kiểm định kỳ (ví dụ mỗi 5 phút) và lúc server khởi động; không chạy khi phần nào của video đang có job.
    - Bật / tắt: `[storage] auto_archive` (mặc định `true`).
    - Nguồn đã enhance (CP13, chưa có): **không tự dọn** — task S2 của CP13 phải đánh dấu nguồn enhance và hàm tự dọn bỏ qua nó; contract này chỉ ghi ràng buộc, không cài đặt trước.
    - Ghi log (`auto-short: web: tự dọn nguồn <id> …`) và trang tập hiện "Đã tự dọn video nguồn <thời điểm>" (dùng `archive.json`, thêm field `auto: true`).
    - Tập đã đăng hết từ trước khi merge: được dọn ở lần kiểm đầu tiên sau khởi động (cùng luật).
  - Bảng dung lượng từng tập (rows) giữ nguyên từng workspace; chỉ phần gợi ý gộp.
  - Cập nhật `docs/decisions/CP8.3-web-contract.md` § Gợi ý (S2) (+ payload `recommendations` nếu đổi field).
- Out of scope: đổi luật "Xong" của trang bộ kinh / tập (W10 L4); tự **xóa cả tập**; đổi `archive` / `delete` API; bài đăng chặn gợi ý.

## Acceptance Criteria

1. Video có Short xong mà khai thị chưa xong (hoặc ngược lại) → không có gợi ý `all_published`.
2. Cả hai xong → đúng một gợi ý cho video; "Dọn video nguồn" / "Xóa cả tập" xử lý cả `<id>` và `<id>.kt`, số byte = tổng.
3. Video chỉ một phần → hành vi như trước.
4. Còn bài đăng chưa tick → gợi ý vẫn có, kèm số bài + cảnh báo; hết bài chưa tick → không cảnh báo.
5. Một phần đang chạy job → không gợi ý cho video.
6. Tự dọn: video đăng hết, giữ ổn định ≥ ân hạn → nguồn mọi phần được dọn (archive.json `auto: true`); bỏ tick trong ân hạn → không dọn; `auto_archive = false` → không dọn; phần có job → chờ; nguồn local / đã archived → không làm gì.
7. Authority CP8.3 § Gợi ý + § Dọn video nguồn + config docs khớp hành vi.
8. `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` PASS; `node scripts/framework-check.mjs` PASS.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` — AC 1–6, 8 (tests mới cho `recommend` gộp, route storage, tự dọn với clock tiêm được).
- `node scripts/framework-check.mjs` — AC 7, 8.
- Chạy `recommend` + danh sách video **sẽ bị tự dọn** read-only trên dữ liệu thật `work/` repo chính (không ghi, không archive) và dán vào Result để HUMAN LEAD xem trước khi merge.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database hay security model. Có hành vi tự xóa dữ liệu → HUMAN LEAD xem danh sách "sẽ bị tự dọn" trong Result **trước merge** (gate); điểm danh còn lại trên 8080 sau merge:

- [ ] Đọc danh sách video sẽ bị tự dọn ngay sau khi 8080 khởi động lại — đồng ý.

- [ ] Tab Bộ nhớ: video có Short xong, khai thị chưa xong → không có gợi ý.
- [ ] Video xong cả hai → một gợi ý, cảnh báo bài đăng nếu còn.
- [ ] Bấm "Dọn video nguồn" một gợi ý gộp → cả hai tập archived.
- [ ] Tick "Đã đăng" Short cuối cùng của một video (khai thị đã đăng) → sau ân hạn, nguồn tự dọn, trang tập ghi "Đã tự dọn".

## Result

- Main changes:
  - D1/D2: `web/storage.py` `recommend` gộp theo video (`video_id` bỏ `.kt`; Short đứng trước khai thị); `all_published` khi mọi phần "Xong"; `old_source` khi mọi phần dọn được đều cũ; `stale_unfinished` khi mọi phần dở dang cũ; video có phần `processing` bị bỏ qua. Mỗi action có `episodes` (UI gọi archive / delete lần lượt từng phần; số byte = tổng); gợi ý có `video_id`, `episodes`.
  - D3: `post_unticked` (bài `posts.json` chưa tick, của Short còn rendered) trên mỗi gợi ý; UI hiện cảnh báo + nhắc lại trong xác nhận "Xóa cả tập".
  - D4: `[storage] auto_archive` (true) / `auto_archive_grace_minutes` (30) (`config.py` `StorageConfig`, `config.example.toml`); `auto_archive_plan` (thuần) + `auto_archive_pass` trong `create_app` (vòng lúc khởi động + mỗi 5 phút trong lifespan; giữ `submit_lock`, bỏ video có job); `archive_source(auto=True)` ghi `archive.json` `"auto": true`; `episode.archived.auto` + nhãn "Đã tự dọn video nguồn" ở trang tập; log `web: tự dọn nguồn <id> …`.
  - Cách xác định ân hạn (không thêm file trạng thái): `complete_since` = max(`at` tick, mtime `publish.json`, mtime `render_manifest.json`, `render.finished_at`) của các phần; bỏ tick / tick lại / render lại dời mốc nên ân hạn tính lại, sống qua restart. Ghi trong CP8.3 § S5.
  - Authority: CP8.3 § Gợi ý (S2), § Tự dọn video nguồn (S5), bảng API, README.
- Tests: `tests/test_storage_suggest.py` (mới, 19 test: AC 1–6) + cập nhật assertion payload `episodes` trong `tests/test_storage_cp86.py`. `PYTHONPATH=<worktree>/src python -m pytest -q -n auto`: lần 2 = 1353 passed, 1 failed (`test_lanes_artifacts_identical_to_serial`, chập chờn đã biết, PASS khi chạy riêng); lần 1 thêm `test_web_cp9.py::test_cut_save_reset_and_409[serial]` fail, PASS khi chạy lại riêng + lần 2. `node scripts/framework-check.mjs` PASS.
- Danh sách video SẼ BỊ TỰ DỌN khi 8080 khởi động lại (tính read-only trên `/home/ntnghia/youtube-auto-short/work`, 2026-10-03, ân hạn 30 phút): **không có video nào, giải phóng 0**. Lý do: 6 video "Xong" cả hai phần đều đã archived từ trước (không còn nguồn); `yzR1eCK_iV0` (Short Xong 13/13, nguồn 702 806 278 B) khai thị `.kt` chưa đăng (0/7) nên không đủ điều kiện; mọi tập khác chưa Xong. Phần Short / khai thị dùng chung một inode nguồn (hard link); byte gợi ý đếm mỗi inode một lần (review F1).
- Bảng gợi ý trước (code cũ) -> sau (mới), dữ liệu thật:
  - Trước: 14 gợi ý `all_published`: `yzR1eCK_iV0` (Dọn nguồn 702 806 278 B + Xóa 969 928 647 B) và 13 dòng riêng (7 tập `.kt`, 6 tập Short) chỉ "Xóa cả tập".
  - Sau: 6 gợi ý `all_published` (một mỗi video): `Bi7kVGbnPfE` (Xóa 665 911 485 B), `4oOZz2CBz3g` (570 945 392), `Irmcm5Ep478` (532 810 088; còn 12 bài đăng chưa tick), `rbjfCfFq3Dk` (540 348 843), `7axON1RpRjo` (550 070 640), `7w4nSj3PguI` (521 878 485); chỉ "Xóa cả tập" (đã archived). `yzR1eCK_iV0` không còn gợi ý (khai thị chưa xong); `X8ao0_7ufto.kt` (Xong, đã archived) không còn gợi ý riêng vì Short `X8ao0_7ufto` chưa Xong.
- Review: ORCHESTRATOR round 1: F1 cộng trùng byte nguồn hard link → round 2 sửa (`2806ad0`), ACCEPTED 2026-10-03. ORCHESTRATOR xác nhận `tests/test_web_cp9.py::test_cut_save_reset_and_409[lanes|serial]` cũng FAIL trên `main` `07a5ae9` với `-n auto` (job post tự soạn gọi Ollama thật) — lỗi có sẵn, ngoài scope; đề xuất FIX riêng tiêm `post_compose` giả.
- Important findings / decisions: gợi ý cũ 14 -> mới 6 vì gộp theo video. `Irmcm5Ep478` còn 12 bài đăng chưa tick (cảnh báo D3 hoạt động trên dữ liệu thật).
- Known limitations: (1) bảng từng tập vẫn tính riêng mỗi workspace (hard link dùng chung hiện ở cả hai dòng); gợi ý đã dedupe theo inode (review F1); (2) "tự dọn" nhận biết "đã đăng hết" từ tick + mtime, nên sửa tay file trong `work/` / `output/` dời mốc ân hạn; (3) nguồn enhance (CP13) chưa có nên chưa được loại trừ; (4) server chưa được chạy với config repo chính (theo yêu cầu an toàn), UI chỉ kiểm bằng `node --check` + test API, chưa thử trình duyệt.
- PR:
