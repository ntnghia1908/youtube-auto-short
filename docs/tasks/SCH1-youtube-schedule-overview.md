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
- Owned paths: `src/auto_short/publish/check.py`, `src/auto_short/publish/overview.py` (mới), `src/auto_short/publish/__main__.py`, `src/auto_short/web/routes/status.py` (route đọc mới), `src/auto_short/web/routes/pages.py` (route trang), `src/auto_short/web/static/schedule.html` + `schedule.js` (mới), link "Lịch YouTube" trong `topnav` của các trang tĩnh (`src/auto_short/web/static/*.html`, chỉ thêm một thẻ `<a>`), `tests/test_publish_overview.py` + `tests/test_web_schedule_overview.py` (mới), contract này
- Dependencies: PUB3.1 (#219, lệnh `check` + bộ nhớ id), PST1 (`work/_publish/post_times.json`, `slot_at`). Bắt đầu implement sau khi cả hai merge; rebase lên `main` lúc đó.
- Base commit / branch: `1502331` (contract) / `feature/sch1-schedule-overview`
- Human Lead approval: accepted 2026-11-19 ("Đồng ý")
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
