# Task: SCH1 — Trang "Lịch YouTube" (mỗi kênh đã lên lịch tới đâu + cảnh báo nháp)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1 — file tóm tắt mới + trang đọc riêng; không thêm thao tác ghi YouTube, không đổi schema cũ
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, test web / full suite, cron ops, chạy thật 8080
- Implementer: codex — hàm thuần + route đọc + trang tĩnh theo mẫu có sẵn
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-19 "Trên web nên có thêm mục hiển thị video và bài đăng đã lên lịch của mỗi kênh trên youtube đã đến tập mấy ngày nào" → đề xuất (mục trang chủ, cảnh báo < 7 ngày, `check` tự chạy 15:30 giờ VN mỗi ngày) → "Đồng ý"
- Parallel group: —
- Owned paths: `src/auto_short/publish/check.py`, `src/auto_short/publish/overview.py` (mới), `src/auto_short/publish/__main__.py`, `src/auto_short/web/routes/status.py` (route đọc mới), `src/auto_short/web/routes/pages.py` (route trang), `src/auto_short/web/static/schedule.html` + `schedule.js` (mới), link "Lịch YouTube" trong `topnav` của các trang tĩnh (`src/auto_short/web/static/*.html`, chỉ thêm một thẻ `<a>`), `tests/test_publish_overview.py` + `tests/test_web_schedule_overview.py` (mới), contract này; **Amendment A**: `src/auto_short/publish/youtube.py` (chỉ ghi / giữ `authorized_at`, helper liệt kê token, hàm auth chia bước bắt đầu / thăm dò), `src/auto_short/web/routes/youtube_auth.py` (mới) + đăng ký router trong `src/auto_short/web/app.py`, `tests/test_publish_youtube_auth.py` + `tests/test_web_youtube_auth.py` (mới)
- Dependencies: PUB3.1 (#219, lệnh `check` + bộ nhớ id), PST1 (`work/_publish/post_times.json`, `slot_at`). Bắt đầu implement sau khi cả hai merge; rebase lên `main` lúc đó.
- Base commit / branch: `1502331` (contract) / `feature/sch1-schedule-overview`
- Human Lead approval: accepted 2026-11-19 ("Đồng ý")
- Amendment A (HUMAN LEAD 2026-11-19 "ok duyệt"): O6 thông báo chưa có số liệu / hạn mức, O7 hạn token, O8 nút lấy lại token (device flow) — xem Authority + AC6–8; Owned paths thêm ở dòng dưới.
- Amendment B (HUMAN LEAD 2026-11-19 "chỉ check giúp tôi từ 1/11/2026 vì có vài cái lỗi tôi đã biết"): O1b lọc cảnh báo theo mốc — xem Authority + AC9; không thêm Owned paths.
- Implementation authorized: YES (bắt đầu trên nền `test/pst1-pub31` 2026-11-19 theo yêu cầu HUMAN LEAD; rebase lên `main` sau khi #221 + #220 merge)

## Goal

Trang riêng **"Lịch YouTube"** (`/schedule`, link ở thanh menu trên cùng; HUMAN LEAD 2026-11-19 "Trang này để riêng một trang nhé"): mỗi kênh một dòng, các cột Bản dọc / Khai thị / Short / Bài post ghi **mục cuối đã lên lịch + ngày giờ đăng (giờ VN)** và **số ngày còn lịch**; ô < 7 ngày tô cảnh báo; dòng nhỏ "công khai gần nhất". Số liệu làm mới mỗi ngày tự động, web không gọi YouTube.

## Scope

- In scope: `check` ghi bản tóm tắt kênh; hàm tóm tắt thuần; route đọc + trang riêng; cron ops chạy `check` 4 kênh 15:30 giờ VN.
- Out of scope: đặt lịch / ghi YouTube từ web; sửa trang chủ; thay đổi `schedule` / `check` ngoài việc ghi tóm tắt.

## Authority / key decisions

- **O1 tóm tắt kênh**: mỗi lần `check` đọc xong (không lỗi), ghi `work/_publish/channels/<channel_id>.json` (atomic, `schema_version` 1): `channel_id`, `channel_title`, `playlist_id` (playlist website từ `--playlist`), `updated_at`, và cho mỗi loại `vertical` / `kt` / `short`: `last_scheduled` {`key`, `publish_at`}, `scheduled_count` (số video riêng tư có lịch trong tương lai), `last_public` {`key`, `published_at`}. Dùng `schedule.classify`; video không nhận ra loại bị bỏ qua. Không lưu token / tiêu đề video.
- **O1a cảnh báo nháp (HUMAN LEAD 2026-11-19: "thêm cảnh báo đăng nháp thiếu bài nào để tôi biết đăng bổ sung")**: tóm tắt O1 lưu thêm kết quả `check.compare` của lần chạy đó: `missing` (mã thiếu trong lỗ hổng, theo loại), `duplicates` (mã + id các bản, bản giữ / bản nên xóa), `unrecognized_count`, `pending` (khoảng "chưa đăng T…–T…" mỗi loại). Trên trang, dưới dòng mỗi kênh: "⚠ Thiếu: T114 (dọc), T9_KT06, T14_KT04 — upload bổ sung"; "⚠ Trùng: T17_S09 — xóa bản b8Ep79QKIk4" (link Studio `https://studio.youtube.com/video/<id>/edit`); không có cảnh báo → không hiện dòng. Danh sách dài > 10 mã → hiện 10 + "và N mã khác" (bấm mở hết).
- **O1b mốc cảnh báo (Amendment B)**: hằng số `ISSUES_SINCE = 2026-11-01T00:00+07:00` trong `publish/overview.py`. Tóm tắt O1a lưu thêm mốc ngày cho mỗi cảnh báo: trùng → `uploaded_at` mới nhất trong các bản; lạ (không nhận ra loại) → lưu danh sách `unrecognized` [{`youtube_id`, `uploaded_at`}] (thay chỉ đếm; giữ `unrecognized_count`); thiếu → `since` = `uploaded_at` của video cùng loại có mã liền trước gần nhất trên kênh (vd thiếu T30_KT06 → ngày upload của T30_KT05; không có mã trước → không có `since`). API / trang chỉ hiện cảnh báo có mốc ≥ `ISSUES_SINCE`; cảnh báo không có mốc thì ẩn. Lọc lúc đọc (API), nên đổi mốc không cần chạy lại `check`; tóm tắt cũ chưa có trường mốc → hiện như cũ. Trang ghi nhỏ "Chỉ cảnh báo từ 01/11/2026".
- **O2 bài post**: cột Bài post lấy từ `post_times.json` (PST1): bài đã tick có `slot_at` thuộc các tập của playlist website đó → `slot_at` lớn nhất + mã bài; "công khai gần nhất" = `slot_at` lớn nhất ≤ now.
- **O3 số ngày còn lịch**: `ceil((last_scheduled.publish_at − now) / 1 ngày)`, ≤ 0 → "hết lịch"; < 7 → cảnh báo. Tóm tắt cũ hơn 36 giờ → ghi "số liệu cũ (cập nhật dd/mm HH:MM)".
- **O4 trang riêng**: route `GET /api/schedule-overview` đọc mọi file O1 + O2 (chỉ đọc file local), trả theo thứ tự tên kênh. Trang `/schedule` (card, kèm dòng cảnh báo O1a, mobile-first: bảng cuộn ngang hoặc mỗi kênh một khối) một card mỗi kênh.
- **O6 thông báo trạng thái (Amendment A)**: trang hiện khối thông báo rõ ràng thay vì trống: không có file tóm tắt nào → "Chưa có số liệu. Số liệu cập nhật tự động lúc 15:30 giờ VN mỗi ngày (sau khi hạn mức YouTube mở lại lúc 15:00)."; nút "Đọc lại" chỉ đọc lại file trên máy chủ — ghi rõ dưới nút "Chỉ đọc lại số liệu đã lưu, không gọi YouTube". `check` lỗi (hạn mức / 429 / đăng nhập) → ghi `work/_publish/channels/<token_stem>.error.json` {`at`, `message`} (không token, không tiêu đề video); lần `check` thành công xóa file lỗi đó. Trang hiện lỗi gần nhất của kênh: "Lần đọc dd/mm HH:MM lỗi: hết hạn mức YouTube — tự thử lại 15:30".
- **O7 hạn token (Amendment A)**: tóm tắt O1 lưu thêm `token` = tên file token (stem, vd `cam-ung-thien`; NDCL token mặc định → `default`), không lưu nội dung token. `auth` ghi thêm `authorized_at` (epoch) vào token; refresh giữ nguyên trường này. Ứng dụng OAuth đang ở chế độ Testing → refresh token hết hạn 7 ngày sau `authorized_at`. API trả mỗi token: `authorized_at`, `expires_at = authorized_at + 7 ngày`, `days_left`; thiếu `authorized_at` → "không rõ hạn" (token cũ; các token hiện tại auth 2026-11-18 — ORCHESTRATOR điền tay `authorized_at` một lần). Trang: dòng "Token còn N ngày (hết dd/mm)", ≤ 2 ngày tô cảnh báo, hết hạn → đỏ "Token hết hạn — lấy lại token".
- **O8 nút lấy lại token (Amendment A)**: trên mỗi kênh nút "Lấy lại token". `POST /api/youtube-tokens/{stem}/auth` (stem phải là file có sẵn trong thư mục token hoặc `default`; không nhận đường dẫn) bắt đầu device flow bằng `client_path` ghi trong token đó, trả `verification_url` + `user_code` + `expires_in`; một luồng nền thăm dò (dùng lại logic `auth`, chia bước bắt đầu / thăm dò) và khi xong ghi token nguyên tử (giữ `client_path`, ghi `authorized_at`). `GET /api/youtube-tokens/{stem}/auth` trả trạng thái `waiting` / `done` / `error` (+ thông báo). Mỗi token tối đa một phiên đang chờ (bấm lại trả phiên đang chờ). Trang hiện mã to + link mở `https://www.google.com/device`, tự hỏi trạng thái mỗi 5 giây, xong → "Đã lấy token mới". Không bao giờ trả access / refresh token hay client secret qua API; route sau đăng nhập web như các route khác.
- **O5 cron (ops, ORCHESTRATOR, không trong repo)**: `~/.local/bin/auto-short-youtube-check` chạy `python -m auto_short.publish --token <token> check --playlist <PID>` cho 4 kênh (ánh xạ PUB3.1 C5), crontab 08:30 UTC = 15:30 giờ VN, log `~/.local/share/auto-short/youtube-check.log`. Mỗi kênh ~1 lượt search.

## Implementation approach

- `publish/overview.py`: `summarize(videos, now) -> dict` thuần (O1), `write(config, doc)`; `check` gọi sau khi đọc video.
- `web/routes/status.py`: route O4; `post_times.json` đọc qua helper của PST1.
- `schedule.html` / `schedule.js`: trang mới theo mẫu trang tĩnh hiện có (vd `storage.html`), dùng `style.css`.

## Phải giữ nguyên

- Đầu ra / hành vi `check` và `schedule` (chỉ thêm ghi file tóm tắt); các trang hiện có (ngoài một link menu); test cũ PASS không sửa.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. O1: `summarize` đúng mục cuối đã lên lịch / công khai gần nhất / số đếm cho mỗi loại; `check` ghi file sau khi đọc thành công, không ghi khi lỗi.
2. O1a: tóm tắt lưu thiếu / trùng / lạ / chưa đăng đúng như `check`; trang hiện cảnh báo thiếu (theo loại) và trùng (id nên xóa + link Studio), rút gọn > 10 mã; không cảnh báo → không hiện.
3. O2 / O3: cột bài post đúng từ `slot_at`; số ngày, "hết lịch", cảnh báo < 7 ngày, "số liệu cũ" > 36 giờ đúng.
4. O4: API đọc file local (không gọi mạng), trang `/schedule` hiện 4 kênh, link menu có trên các trang; thiếu file → kênh không hiện / thông báo "chưa có số liệu".
5. Test cũ PASS không sửa.
6. O6: không có tóm tắt → thông báo "Chưa có số liệu … 15:30"; nút Đọc lại có chú thích; `check` lỗi ghi / thành công xóa file lỗi, trang hiện lỗi gần nhất.
7. O7: `auth` ghi `authorized_at`, refresh giữ; API trả hạn token đúng (còn N ngày / ≤ 2 cảnh báo / hết hạn / không rõ); không lộ secret.
9. O1b: trùng / lạ / thiếu chỉ hiện khi mốc ≥ 01/11/2026 (giờ VN), ranh giới đúng; thiếu không có mã trước → ẩn; tóm tắt cũ không có mốc → hiện như cũ; số đếm trên trang khớp danh sách sau lọc.
8. O8: route auth từ chối stem lạ / đường dẫn; bắt đầu trả mã + URL; thăm dò `authorization_pending` / `slow_down` / thành công ghi token giữ `client_path` + `authorized_at` / lỗi; một phiên mỗi token; transport giả trong test, không mạng.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_publish_overview.py tests/test_publish_check.py` — AC1–2 (IMPLEMENTER).
- `PYTHONPATH=src python -m pytest -q tests/test_web_schedule_overview.py` + test trang tĩnh / auth hiện có — AC3–4 (ORCHESTRATOR).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR).
- Chạy thật: cron chạy 1 lần tay cho 4 kênh; trang `/schedule` 8080 hiện số khớp Studio (CƯT khai thị tới T23_KT05 · 02/12).

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract.

- [ ] HUMAN LEAD mở trang "Lịch YouTube" trên điện thoại, đối chiếu 1–2 kênh với Studio.

## Result

- Main changes:
  - Thêm `publish/overview.py`: `summarize` (thuần, phân loại bằng `schedule.classify`, đếm id riêng biệt), `issues` (chiếu nguyên quyết định `check.compare`, bỏ title), `write` / `read` snapshot atomic và helper `summarize_posts`, `coverage`, `stale`.
  - Lệnh `check` ghi `work/_publish/channels/<channel_id>.json` schema 1 sau khi đọc / kiểm tra thành công; lỗi giữ snapshot trước. Không đổi stdout hay đường chạy `schedule`; không thêm lượt mạng. Tên kênh lấy từ `channelTitle` của snippet video / playlist đã đọc, dự phòng channel id khi kênh rỗng không có snippet tên.
  - API `GET /api/schedule-overview` chỉ đọc snapshot và local playlist / bài post / `post_times.json`; chỉ tính `slot_at` của bài đã tick, gồm Short và khai thị, bỏ bài ngoài playlist. Tính lại số ngày và stale mỗi lần đọc; lỗi giờ post được báo riêng, vẫn giữ dữ liệu video.
  - Trang riêng `/schedule`: một card/kênh, bảng cuộn ngang, giờ VN, cảnh báo < 7 ngày / > 36 giờ, thiếu / trùng với link Studio và mở rộng sau 10 mã; hiện pending / số video không nhận ra. Thêm đúng một link topnav cho mỗi trang hiện có topnav.
- AC → test:
  - AC1: `tests/test_publish_overview.py` — đủ ba loại, cuối theo thời gian, id riêng biệt, public / private / unlisted, ngày lỗi, snapshot thành công và giữ nguyên / không tạo khi API lỗi.
  - AC2: `tests/test_publish_overview.py` — thiếu / trùng / lạ / pending khớp `check.compare`, không lưu title; `tests/test_web_schedule_overview.py` — cảnh báo, link Studio, rút gọn 10 mã, không có cảnh báo thì ẩn dòng.
  - AC3: `tests/test_publish_overview.py` — slot bài đã tick, hết lịch, ceil, ranh giới 7 ngày / 36 giờ; `tests/test_web_schedule_overview.py` — tách playlist, giờ VN, bài legacy không slot, bài đã bỏ render.
  - AC4: `tests/test_web_schedule_overview.py` — auth, API local không ghi / không gọi YouTube, bốn kênh theo tên, trang / menu, dữ liệu thiếu / lỗi, DOM an toàn và bảng cuộn.
  - AC5: `tests/test_publish_check.py` cũ không sửa, PASS trong lần chạy bên dưới; các regression khác chờ ORCHESTRATOR.
- Verification IMPLEMENTER: `conda run -n auto-short env PYTHONPATH=src python -m pytest -q tests/test_publish_overview.py tests/test_publish_check.py` → **39 passed in 0.65s**. Python env mặc định thiếu pytest nên dùng env `auto-short` theo chỉ dẫn. `git diff --check` sạch.
- Chưa chạy: `tests/test_web_schedule_overview.py` (đã viết, gồm HTTP/auth và DOM Node), test trang tĩnh / auth hiện có và full suite — ORCHESTRATOR chạy vì sandbox IMPLEMENTER không có loopback và phạm vi lệnh test được giới hạn.
- O5 cron / chạy thật bốn kênh / đối chiếu Studio / checklist điện thoại: chưa thực hiện, thuộc ORCHESTRATOR / HUMAN LEAD. Không gọi mạng thật; không commit / push / PR; không giao agent khác.
- ORCHESTRATOR 2026-11-19: `check._keep_order` xếp hạng công khai / không công khai > đã lên lịch > còn lại (trước đây bản lên lịch upload sớm hơn thắng bản công khai — CƯT T17_S09); test `test_compare_public_copy_wins_over_earlier_scheduled_copy`. Targeted `tests/test_publish_overview.py tests/test_web_schedule_overview.py tests/test_publish_check.py`: 46 passed.

### Amendment A — READY IMPLEMENTER, chờ review / verification ORCHESTRATOR

- Base thực tế: `feature/sch1-schedule-overview` HEAD `ac69b71`, working tree sạch trước khi sửa. Chỉ làm O6–8 trong owned paths; không sửa / xóa test cũ, chỉ nối thêm ca vào hai file overview và tạo hai file auth mới.
- O6: thông báo chưa có số liệu + lịch 15:30 / hạn mức mở lại 15:00, chú thích nút Đọc lại; `check` ghi lỗi đã lọc nội dung theo token stem (quota / 429 / OAuth / lỗi file), giữ snapshot cũ; thành công xóa lỗi. `overview.read(..., include_errors=True)` trả thêm lỗi, mặc định vẫn giữ giao diện đọc snapshot cũ. API trả `errors`; trang ghép lỗi theo token, vẫn hiện lỗi / nút auth khi chưa có snapshot.
- O7: auth mới ghi `authorized_at`, refresh giữ nguyên (token legacy vẫn không rõ hạn); API `tokens[stem]` chỉ trả `authorized_at`, `expires_at` (7 ngày Testing), `days_left`, `warning`, `expired`. Trang cảnh báo ≤ 2 ngày, hết hạn màu đỏ. Snapshot gắn `token` cho file trong allowlist hoặc token mặc định (`default`); đường dẫn CLI tùy ý ngoài allowlist giữ snapshot tương thích cũ và không được gắn đích auth web. Không điền tay ngày cho token thật trong task này.
- O8: tách `auth` thành `start_device` / `poll_device`, giữ CLI và fallback scope cả ở bước bắt đầu lẫn thăm dò. Router mới dùng mẫu `build(ctx)` và middleware đăng nhập hiện có; chỉ nhận stem allowlist (không symlink / đường dẫn), POST trả lại phiên đang chờ, thread nền ghi token atomic mode 0600, GET trả waiting / done / error. Response chỉ chiếu trường công khai, thông báo lỗi không chép exception chứa secret. Trang có mã lớn, link cố định `https://www.google.com/device`, poll 5 giây, báo đã lấy token mới.
- Helper mới và tái dùng: đã tìm bằng `rg -n '^def (auth|_form|_credentials|_token_doc|_save_token|atomic_write_json|default_token|token_paths|token_status|check_error)|^    def _clients' src/auto_short/publish src/auto_short/workspace.py src/auto_short/web/post_links.py` và đọc source liên quan. `start_device` / `poll_device` tách logic auth đang có, dùng lại `_form`, `_credentials`, `_token_doc`, `_save_token`; không giữ bản auth cũ song song. `default_tokens_dir` là alias tương thích `default_token_dir`; `token_paths` / `token_stem` liệt kê và ánh xạ allowlist (logic `_clients` hiện có gọi YouTube nên không phù hợp route local). `overview.check_error`, `token_status`, `tokens` bổ sung lưu lỗi / tính hạn thuần / đọc metadata chưa có helper tương đương; ghi file dùng `atomic_write_json`. Router có helper nội bộ chọn file / chiếu response / chạy nền; JS thêm `tokenControl` và `checkError` dùng lại `AutoShort.el`, `api`, hàm giờ VN hiện có.

| AC | Test / bằng chứng |
|---|---|
| AC6 | `test_check_error_saved_sanitized_then_cleared_and_snapshot_links_registered_token` (parametrize default / named và quota / 429 / 401); `test_amendment_api_local_errors_and_testing_token_metadata_without_secrets` (HTTP chưa chạy); `test_amendment_page_empty_errors_token_expiry_and_device_flow_dom` (PASS). |
| AC7 | `test_refresh_preserves_authorized_at_or_unknown_legacy_token`; `test_testing_token_lifetime_boundaries_and_secret_projection` + `test_legacy_or_invalid_token_authorization_date_is_unknown`; ca device flow kiểm auth mới ghi ngày và giữ client binding. DOM kiểm không rõ hạn / còn 2 ngày / hết hạn; HTTP metadata chưa chạy. |
| AC8 | `tests/test_publish_youtube_auth.py`: bước bắt đầu không poll, CLI / helper fallback scope, pending / slow_down / thành công / hết hạn / từ chối / lỗi mạng / JSON và field lỗi, allowlist / symlink, ghi 0600 và không lộ secret (PASS). `tests/test_web_youtube_auth.py`: auth web, stem / đường dẫn / symlink, một phiên mỗi token, GET trạng thái và thay phiên terminal, bảo toàn token khi lỗi (đã viết, chưa chạy). DOM POST → GET sau 5000 ms → thông báo thành công (PASS). |

- Ngân sách hàm test: AC7 / AC8 hơn 3 hàm vì tách lifetime thuần, refresh, device transport và HTTP middleware / concurrency; các nhánh cùng hành vi gom bằng parametrize, tái dùng `Wire`, `Clock`, fixture OAuth, service và DOM harness có sẵn.
- Verification IMPLEMENTER: `conda run -n auto-short env PYTHONPATH=src python -m pytest -q tests/test_publish_overview.py tests/test_publish_check.py tests/test_publish_youtube_auth.py` → **75 passed in 3.05s**. Không có `tests/test_publish_youtube.py` nên bỏ khỏi lệnh theo chỉ dẫn.
- DOM / static không socket: `conda run -n auto-short env PYTHONPATH=src python -m pytest -q tests/test_web_schedule_overview.py -k 'page_renders or amendment_page or topnav'` → **3 passed, 8 deselected in 1.13s** (một warning deprecation TestClient từ import, không khởi tạo TestClient). `node --check src/auto_short/web/static/schedule.js`, `python -m py_compile` cho source / test thay đổi và `git diff --check` đều PASS.
- Chưa chạy: toàn bộ ca TestClient trong `tests/test_web_schedule_overview.py` và `tests/test_web_youtube_auth.py`, test trang tĩnh / auth khác và full suite — thuộc ORCHESTRATOR theo phân công. Không tuyên bố PASS cho HTTP / full suite / chạy thật.
- Dòng thêm / xóa (diff Amendment A so với `ac69b71`, gồm file mới chưa track): ứng dụng **+289 / −36**; test **+351 / −0**. Đếm từ `git diff --numstat` cộng số dòng file mới trong `git ls-files --others --exclude-standard`; không stage file để đếm.
- Không commit / push / PR, không gọi agent khác, không gọi mạng thật. Chưa chạy cron, auth thật, sửa token thật hay triển khai 8080.

### Amendment B — READY IMPLEMENTER, chờ review / verification ORCHESTRATOR

- Base thực tế: `feature/sch1-schedule-overview` HEAD `1a95a2b` (commit docs Amendment B), working tree sạch trước khi sửa. Chỉ thực hiện O1b / AC9 trong owned paths.
- `overview.issues(checked, videos=None)` giữ nguyên đầu ra legacy khi không truyền `videos`; CLI truyền danh sách video để lưu mã thiếu dạng `{key, since}`, mốc `uploaded_at` mới nhất của nhóm trùng, danh sách `unrecognized` `{youtube_id, uploaded_at}` và số đếm gốc. Mã trước gần nhất lấy trên toàn bộ video cùng loại qua `schedule.classify`, kể cả mã website không có; sắp theo số tập / clip, dùng ngày upload mới nhất nếu mã trước có nhiều bản. Mã trước không có ngày hợp lệ → `since: null`, không nhảy qua video đó lấy mốc xa hơn.
- Hằng số `ISSUES_SINCE = "2026-11-01T00:00+07:00"`; hàm thuần `visible_issues(doc, since)` lọc khi API đọc, không sửa file snapshot. Snapshot mới được nhận diện bởi danh sách `unrecognized` (kể cả rỗng); snapshot cũ chưa có trường này giữ nguyên cảnh báo. Mốc thiếu / lỗi bị ẩn, ranh giới lấy bao gồm đúng thời điểm mốc, tính lại `unrecognized_count` sau lọc; pending giữ nguyên. API truyền hằng số mỗi lần đọc để thay mốc không cần chạy lại `check`.
- Trang dùng danh sách API đã lọc, hỗ trợ mã thiếu legacy dạng chuỗi lẫn dạng mới, hiện dòng nhỏ “Chỉ cảnh báo từ 01/11/2026”. Không đổi quyết định / stdout của `check`, không sửa `schedule` / `check.py`.

| AC | Test / bằng chứng |
|---|---|
| AC9 | `test_amendment_b_dates_numeric_predecessors_all_kinds_and_newest_duplicate`: ba loại, thứ tự số T9/T10 và clip 09/10, mã trước ngoài inventory, ngày thiếu/lỗi, trùng lấy mốc mới nhất, không lưu title / không mutate, legacy. `test_amendment_b_visible_boundaries_counts_no_mutation_and_changed_cutoff` (parametrize): trước / đúng / sau 00:00 giờ VN, UTC tương đương, mốc thiếu/lỗi/không timezone, số đếm khớp danh sách, đổi mốc trên snapshot cũ đã lưu. `test_amendment_b_api_filters_on_read_and_page_uses_visible_lists`: API local giữ nguyên file, legacy, đổi mốc lúc đọc; DOM chỉ hiện mã / số đếm còn lại và dòng chú thích, hết cảnh báo thì ẩn khối (đã viết, ORCHESTRATOR chạy). |

- Chỉ thêm ba hàm test AC9 vào hai file được phép; sửa đúng một assertion test CLI cũ để truyền `sources` vào `issues` theo chữ ký mới tùy chọn. Không sửa test cũ khác.
- Tái dùng / helper mới: tìm bằng `rg -n '^def (issues|visible_issues|classify|_timestamp|_code)' src/auto_short/publish/{overview,schedule,check}.py`; dùng lại `issues`, `schedule.classify`, `schedule._timestamp`, `check._code`, `_iso`. Helper mới `visible_issues` phục vụ lọc thuần lúc đọc theo O1b, chưa có helper tương đương; predicate `visible` nội bộ chỉ so mốc ngày.
- Verification IMPLEMENTER: `conda run -n auto-short env PYTHONPATH=src python -m pytest -q tests/test_publish_overview.py tests/test_publish_check.py tests/test_publish_youtube_auth.py` → **83 passed in 0.78s**. `node --check src/auto_short/web/static/schedule.js`, `python -m py_compile` (conda `auto-short`) cho ba source Python và hai file test thay đổi, `git diff --check` PASS.
- Chưa chạy test web (bao gồm test API/DOM AC9 mới), các test web khác / full suite / kiểm tra thật: ORCHESTRATOR phụ trách. READY ở phạm vi IMPLEMENTER; không tuyên bố PASS cho phần chưa chạy.
- Dòng thêm / xóa Amendment B (`git diff --numstat` so với `1a95a2b`, không tính contract): ứng dụng **+63 / −7**; test **+94 / −1**.
- Không commit / push / PR, không gọi agent khác, không gọi mạng thật; không sửa token thật / cron / triển khai.
