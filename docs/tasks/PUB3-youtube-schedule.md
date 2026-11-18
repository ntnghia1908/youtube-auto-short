# Task: PUB3 — CLI lên lịch đăng video riêng tư chưa có lịch (YouTube Data API)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2 — mở rộng decision PUB2 G1 (thêm thao tác ghi `videos.update` trạng thái) và G4 (thêm scope OAuth)
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — review, full suite, đăng nhập lại 4 kênh, chạy thật
- Implementer: codex — lệnh mới trong package `publish` có sẵn, test không cần mạng / socket
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-11-18: "4 kênh cùng khung giờ và cố định tất cả các ngày" + "Đồng ý" quy tắc do ORCHESTRATOR đề xuất (khung giờ đo từ lịch hiện có, nối tiếp lịch cuối, bỏ bản trùng, thêm quyền sửa video, chạy thử 1 video trước)
- Parallel group: —
- Owned paths: `src/auto_short/publish/youtube.py`, `src/auto_short/publish/schedule.py` (mới), `src/auto_short/publish/__main__.py`, `tests/test_publish_schedule.py` (mới), `docs/decisions/PUB2-youtube-thumbnail-set.md` (sửa đổi G1 / G4), contract này
- Dependencies: none
- Base commit / branch: `1502331` / `feature/pub3-schedule`
- Human Lead approval: accepted 2026-11-18 ("Đồng ý")
- Implementation authorized: YES

## Goal

HUMAN LEAD upload video (Studio, để riêng tư / chưa lên lịch). `python -m auto_short.publish schedule --client … --token …` in kế hoạch: mỗi video riêng tư chưa có lịch của kênh → loại, tập, giờ đăng dự kiến (giờ VN). Thêm `--apply` thì đặt lịch (`status.publishAt`) cho đúng các video đó.

## Scope

- In scope: lệnh `schedule` (chạy thử mặc định, `--apply`, `--only id,…`, `--limit N`); đọc mọi video của kênh gồm riêng tư; phân loại; xếp giờ; `videos.update part=status`; nhật ký; thêm scope OAuth.
- Out of scope: upload video, đổi tiêu đề / mô tả / playlist / thumbnail (cron gắn ảnh có sẵn tự xử lý video đã lên lịch), route web, config `config.toml`, cron.

## Authority / key decisions

- **S1 khung giờ** (cố định, giờ `Asia/Ho_Chi_Minh`, mọi ngày, như nhau cho mọi kênh; đo 2026-11-18 từ 2.994 video 4 kênh): bản dọc `06:00`; khai thị `12:30`, `20:30`; Short `07:00`, `11:00`, `18:45`. Hằng số trong `schedule.py`.
- **S2 phân loại** (theo `fileDetails.fileName`, nếu không có thì `snippet.title`; NFC, strip):
  - Short: `^T(\d+)[ _]S(\d{1,3})(?!\d)` (không phân biệt hoa thường) → (tập, số clip).
  - Khai thị: `^T(\d+)[ _]KT(\d{1,3})(?!\d)` → (tập, số KT).
  - Bản dọc: tên chứa `HD Mobile` hoặc `HD Dọc` (không phân biệt hoa thường) và kết thúc bằng `Tập N` (bỏ đuôi `.mp4`) → (bộ, tập). Khóa bộ: phần trước `Tập N` sau khi NFC, casefold, thay ký tự không phải chữ / số bằng khoảng trắng, gộp khoảng trắng, bỏ tiền tố `hd mobile` / `hd dọc` (để tên file `[HD Mobile] X - PS. Y - Tập N.mp4` và tiêu đề tự sinh `HD Mobile X   PS  Y   Tập N` cùng khóa).
  - Không khớp → không lên lịch, in "bỏ qua: không nhận ra loại".
- **S3 ứng viên**: `status.privacyStatus == "private"`, không có `status.publishAt`, `status.uploadStatus == "processed"`. Video khác (công khai, unlisted, đã lên lịch) chỉ dùng để tính lịch cuối và bản trùng.
- **S4 bản trùng**: ứng viên có cùng khóa (loại + bộ + tập cho bản dọc; loại + tập + số cho Short / KT) với một video công khai, unlisted hoặc đã lên lịch trên cùng kênh → bỏ qua, in "đã có bản <id>". Hai ứng viên cùng khóa → chỉ xếp video upload sớm nhất, video kia bỏ qua cùng lý do.
- **S5 xếp giờ**, mỗi loại độc lập trên mỗi kênh:
  - Mốc = `publishAt` lớn nhất của các video đã lên lịch cùng loại. Không có → mốc = 23:59:59 hôm nay (giờ VN), tức bắt đầu từ ngày mai.
  - Ứng viên sắp theo (khóa bộ, tập, số clip / KT, thời điểm upload). Gán lần lượt vào các khung giờ của loại đó, khung đầu tiên lớn hơn mốc; không lấp khe trống trước mốc.
  - Khung giờ phải sau thời điểm chạy ít nhất 1 giờ; khung sớm hơn thì nhảy sang khung kế tiếp.
  - `--only` / `--limit` lọc ứng viên SAU khi xếp: video được chọn giữ đúng giờ như khi chạy toàn bộ (chạy thử 1 video rồi chạy tiếp không đổi lịch).
- **S6 ghi**: `PUT videos?part=status` thân `{"id", "status": {...}}`. Sao giữ mọi trường ghi được trong `status` hiện tại (`embeddable`, `license`, `publicStatsViewable`, `selfDeclaredMadeForKids`, `containsSyntheticMedia` nếu có), đặt `privacyStatus = "private"`, `publishAt` = RFC 3339 UTC (`…Z`). Content-Type `application/json`. Mỗi video thành công → ghi nhật ký `work/_publish/schedule.json` (atomic, `schema_version` 1: youtube_id, kind, key, publish_at, set_at). Lỗi `quotaExceeded` / 403 / 401 sau refresh → dừng, exit ≠ 0, video đã đặt vẫn trong nhật ký. Thiếu quyền (`insufficientPermissions` / scope) → báo "token chưa có quyền sửa video; chạy lại auth".
- **S7 đọc video**: uploads (`videos()` có sẵn) + `search?forMine=true&type=video` phân trang để lấy video riêng tư uploads không trả về, rồi `videos.list part=fileDetails,snippet,status` cho id còn thiếu (theo lô 50). Đã kiểm tay 2026-11-18 (ops `attach.py`).
- **S8 OAuth**: thêm `https://www.googleapis.com/auth/youtube.force-ssl` vào `SCOPES` (G4 sửa đổi). Token cũ vẫn dùng được cho lệnh thumbs / web đọc; `schedule --apply` cần token mới. Không log token / secret.
- Không thêm dependency (G5).

## Implementation approach

- `youtube.py`: `SCOPES` thêm force-ssl; `_request` nhận Content-Type tùy chọn (giữ `image/jpeg` cho thumbnail); thêm `all_videos()` (S7) và `update_status(youtube_id, status)`.
- `schedule.py`: hàm thuần `classify(video)`, `plan(videos, now) -> rows` (S2–S5), `apply(config, rows, client)` + nhật ký (S6). `now` truyền vào để test.
- `__main__.py`: subcommand `schedule` với `--client`, `--token`, `--config`, `--apply`, `--only`, `--limit`, theo mẫu các lệnh có sẵn. Bảng in: id, loại, khóa, giờ VN dự kiến, trạng thái / lý do; dòng tổng mỗi loại.
- Tái dùng: `config.load`, `workspace.atomic_write_json` / `read_json_dict`, `render.text.nfc`, transport giả trong test như `tests/test_publish_thumbs.py`.

## Phải giữ nguyên

- Hành vi các lệnh `auth`, `thumbs`, `kt-thumbs`, `short-thumbs` và web đọc token (LNK1); test cũ PASS không sửa. Không tự lên lịch khi gọi lệnh khác.

## Code bị thay / xóa

- Không có.

## Acceptance Criteria

1. Phân loại đúng Short / KT / bản dọc theo tên file, rơi về tiêu đề khi thiếu tên file; tên file và tiêu đề tự sinh của cùng tập bản dọc cho cùng khóa; tên lạ → bỏ qua.
2. Chỉ ứng viên S3 được xếp; công khai / unlisted / đã lên lịch / chưa xử lý xong không bị đụng.
3. Bản trùng S4 bị bỏ qua có lý do; hai ứng viên cùng khóa chỉ xếp bản sớm nhất.
4. Xếp giờ S5: nối tiếp sau lịch cuối cùng loại đúng khung giờ VN, nhiều ngày; loại chưa có lịch bắt đầu ngày mai; khung < now + 1 h bị bỏ; thứ tự theo bộ / tập / số.
5. `--only` / `--limit` cho cùng giờ như kế hoạch đầy đủ.
6. Chạy thử không gọi API ghi nào. `--apply` gửi `PUT videos?part=status` với `publishAt` UTC đúng và giữ các trường status ghi được; ghi nhật ký từng video; lỗi quota dừng giữa chừng, nhật ký giữ phần đã đặt.
7. `SCOPES` gồm force-ssl; thiếu quyền cho thông báo chạy lại auth.
8. Lệnh / test cũ không đổi hành vi.

## Required verification

- `PYTHONPATH=src python -m pytest -q tests/test_publish_schedule.py tests/test_publish_thumbs.py tests/test_publish_kt.py tests/test_publish_shorts.py` — AC1–8 (IMPLEMENTER chạy được trong sandbox).
- `PYTHONPATH=src python -m pytest -q -n auto` — full suite (ORCHESTRATOR, ngoài sandbox).
- Chạy thật (ORCHESTRATOR): đăng nhập lại 4 kênh; chạy thử từng kênh, đối chiếu bảng với số liệu 2026-11-18 (Tín Nguyện ~100 bản dọc + 2, CƯT ~59 + 32 + 16, VLT 14 và Người Dân Cực Lạc 2 bị bỏ vì trùng).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm security model (scope OAuth mới, thao tác ghi trạng thái video) → manual test là gate trước khi chạy hàng loạt.

- [ ] Chạy thử 4 kênh, HUMAN LEAD xem bảng giờ.
- [ ] `--apply --only <1 id>` trên 1 video; HUMAN LEAD thấy lịch đúng trong Studio.
- [ ] HUMAN LEAD OK → `--apply` cả kênh.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
