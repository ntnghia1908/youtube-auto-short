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
- Implementation authorized: YES (bắt đầu trên nền `test/pst1-pub31` 2026-11-19 theo yêu cầu HUMAN LEAD; rebase lên `main` sau khi #221 + #220 merge)

## Goal

Trang riêng **"Lịch YouTube"** (`/schedule`, link ở thanh menu trên cùng; HUMAN LEAD 2026-11-19 "Trang này để riêng một trang nhé"): mỗi kênh một dòng, các cột Bản dọc / Khai thị / Short / Bài post ghi **mục cuối đã lên lịch + ngày giờ đăng (giờ VN)** và **số ngày còn lịch**; ô < 7 ngày tô cảnh báo; dòng nhỏ "công khai gần nhất". Số liệu làm mới mỗi ngày tự động, web không gọi YouTube.

## Scope

- In scope: `check` ghi bản tóm tắt kênh; hàm tóm tắt thuần; route đọc + trang riêng; cron ops chạy `check` 4 kênh 15:30 giờ VN.
- Out of scope: đặt lịch / ghi YouTube từ web; sửa trang chủ; thay đổi `schedule` / `check` ngoài việc ghi tóm tắt.

## Authority / key decisions

- **O1 tóm tắt kênh**: mỗi lần `check` đọc xong (không lỗi), ghi `work/_publish/channels/<channel_id>.json` (atomic, `schema_version` 1): `channel_id`, `channel_title`, `playlist_id` (playlist website từ `--playlist`), `updated_at`, và cho mỗi loại `vertical` / `kt` / `short`: `last_scheduled` {`key`, `publish_at`}, `scheduled_count` (số video riêng tư có lịch trong tương lai), `last_public` {`key`, `published_at`}. Dùng `schedule.classify`; video không nhận ra loại bị bỏ qua. Không lưu token / tiêu đề video.
- **O1a cảnh báo nháp (HUMAN LEAD 2026-11-19: "thêm cảnh báo đăng nháp thiếu bài nào để tôi biết đăng bổ sung")**: tóm tắt O1 lưu thêm kết quả `check.compare` của lần chạy đó: `missing` (mã thiếu trong lỗ hổng, theo loại), `duplicates` (mã + id các bản, bản giữ / bản nên xóa), `unrecognized_count`, `pending` (khoảng "chưa đăng T…–T…" mỗi loại). Trên trang, dưới dòng mỗi kênh: "⚠ Thiếu: T114 (dọc), T9_KT06, T14_KT04 — upload bổ sung"; "⚠ Trùng: T17_S09 — xóa bản b8Ep79QKIk4" (link Studio `https://studio.youtube.com/video/<id>/edit`); không có cảnh báo → không hiện dòng. Danh sách dài > 10 mã → hiện 10 + "và N mã khác" (bấm mở hết).
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
