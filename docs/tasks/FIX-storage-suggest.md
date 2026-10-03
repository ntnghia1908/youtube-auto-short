# Task: FIX-storage-suggest — Gợi ý dọn dẹp gộp Short + khai thị, cảnh báo bài đăng, tự dọn nguồn khi đăng hết

## Status / Approval

- Status: APPROVED
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
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
