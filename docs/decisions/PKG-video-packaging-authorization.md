# PKG — Implementation Authorization Boundary: đóng gói video ghép chủ đề (thumbnail, hình, nhạc)

| Metadata | Value |
|---|---|
| Status | ACCEPTED — HUMAN LEAD 2026-10-24 (G1–G6, §4) |
| Authority | HUMAN LEAD yêu cầu 2026-10-24 (đề xuất P1–P4); P1 Publishing Queue (PUB1, PUB1.1) và nhật ký thử nghiệm (PKG1.1) bị HUMAN LEAD bỏ cùng ngày |
| Governance | Framework v4.4 — boundary-authorized, dual-agent (Codex IMPLEMENTER, Codex reviewer thứ hai) |
| Scope | PKG1 thumbnail + tiêu đề → VIS1 hình ambient → AUD1 nhạc nền, đều sau kết quả TC3 |
| Integration | Push / PR / merge / restart 8080 vẫn cần HUMAN LEAD duyệt riêng |

Task nằm hoàn toàn trong boundary này ghi `Authorization mode: boundary`, `Authorization source: docs/decisions/PKG-video-packaging-authorization.md` và `Implementation authorized: YES` khi có base commit; không cần APPROVE TASK riêng.

## 1. Mục tiêu

Giúp video Khai thị ghép chủ đề 30–40 phút (TC3) dễ được chọn xem và dễ nghe hơn mà **không đổi lời giảng**. Thay đổi lượt xem / CTR là kết quả thử nghiệm, không phải cam kết.

## 2. Rule chung (canonical owner cho PKG1 / VIS1 / AUD1)

- **R1 Đầu vào**: chỉ kết quả TC3 đã hợp lệ (`web/theme_plan.py` `ThemePlans.output(verify=True)`: plan approved, fingerprint khớp, sha256 khớp). Không sửa `theme_render/`, `theme_plan/`, `theme_index/` hay file TC3 (`theme/<plan>-r<rev>.mp4|json`).
- **R2 Lời giảng nguyên vẹn**: không tổng hợp giọng, không thay / cắt / đảo lời, không dựng cảnh người giảng nói. Mode A (Original = file TC3) luôn còn và là mặc định.
- **R3 Output riêng**: mọi file mới nằm ở `output/_compilations/<playlist_id>/theme/pkg/<plan_id>-r<rev>/`. Tên file chứa cache key = sha256 rút gọn của (sha256 TC3, cấu hình, sha asset, version renderer). Ghi qua thư mục tạm cùng ổ + `os.replace`; lỗi giữa chừng thì xóa file tạm, không đụng file TC3.
- **R4 Stale**: plan revision / fingerprint hoặc sha256 TC3 đổi → hồ sơ đóng gói và variant cũ hiện "cũ — dựng lại", không bị tự xóa, không còn được tải như bản hợp lệ.
- **R5 Kho asset có nguồn gốc**: ảnh / loop / nhạc chỉ được dùng khi có trong `library.json` với `source`, `license`, `approved: true`. Hệ thống **không tự tải** media bên thứ ba. Hình nền tạo bằng ffmpeg (gradient, ánh sáng mềm) là asset nội bộ, license-free, dùng làm mặc định và cho test.
- **R6 Duyệt tay**: thumbnail, tiêu đề, chuỗi cảnh và mức nhạc chỉ được đánh dấu dùng khi HUMAN LEAD bấm duyệt; chỉ bản đã duyệt có nút tải "bản đăng".
- **R7 Không dependency mới**: ffmpeg + stdlib + font OFL đóng gói (`render/text.py` để đo / ngắt dòng). Không Pillow, không AI sinh ảnh / video.
- **R8 Job**: dựng media qua job runner hiện có, làn render, một job mỗi `(playlist, plan, variant)`; khóa trùng như `theme_render`.
- **R9 Mặc định không đổi**: không bật mode nào, hành vi Short / khai thị / CP8.33 / TC1–TC3 giữ nguyên khi người dùng không chọn.

## 3. Task graph

```text
TC3 (có) ──► PKG1 thumbnail + tiêu đề
         └─► VIS1 ambient (variant: hình) ──► AUD1 nhạc nền (variant: + nhạc)
Để sau: VIS1.1 cảnh theo chapter; AUD1.1 nhạc né giọng (ducking); PKG cho khai thị 4–7 phút và CP8.33
```

Tuần tự, một writer: PKG1 → VIS1 → AUD1. PKG1 và VIS1 không chung owned path nhưng cùng sửa trang kế hoạch chủ đề (`theme_plan.js`) và đăng ký route, nên không chạy song song.

## 4. Gate — HUMAN LEAD đã quyết 2026-10-24

| ID | Câu hỏi | Đề xuất |
|---|---|---|
| G1 | Duyệt boundary PKG1 + VIS1 + AUD1 (VIS1.1 / AUD1.1 chưa duyệt) | Duyệt |
| G2 | Ảnh người giảng trong thư viện bài đăng (`post-images/`, nguồn hwadzan.com, `sources.tsv`) được dùng trên thumbnail và làm nền video? | HUMAN LEAD xác nhận quyền dùng; nếu không, PKG1 chỉ dùng ảnh do HUMAN LEAD nạp vào kho |
| G3 | Nguồn ảnh cảnh / loop / nhạc có license | HUMAN LEAD tự cung cấp file + ghi nguồn; MVP chạy được với nền ffmpeg tự tạo |
| G4 | Thêm font `BeVietnamPro-ExtraBold.ttf` (OFL, cùng họ font đang dùng) vào `render/fonts/` cho chữ thumbnail | Đồng ý (asset, không phải thư viện) |
| G5 | Public API + config mới: route dưới `/api/playlists/{pid}/theme-plans/{plan_id}/package…`, `/files/playlists/{pid}/theme-pkg/{plan_rev}/{name}`, job kind `theme_package`, mục `[packaging]` (`asset_dir`, mặc định `~/.local/share/auto-short/packaging/`) | Đồng ý; chi tiết schema trong từng task contract |
| G6 | Dung lượng: mỗi variant 40 phút ~0,4–1,5 GB, ổ còn ~35 GB (93 %). Variant không tự archive; xóa tay trên trang đóng gói | Đồng ý |

Quyết định HUMAN LEAD (2026-10-24, trả lời từng câu):

- **G1**: duyệt cả PKG1 + VIS1 + AUD1 (tuần tự). VIS1.1 / AUD1.1 chưa duyệt.
- **G2**: ảnh người giảng trong `post-images/` được dùng cho thumbnail **và** nền video; import ghi `license` theo xác nhận của HUMAN LEAD.
- **G3**: ORCHESTRATOR tìm nguồn hình cảnh / loop / nhạc **CC0 hoặc public domain** (ghi URL, license, tác giả), HUMAN LEAD duyệt từng nguồn trước khi nạp kho. Code không tải media tự động (R5 giữ nguyên); nạp kho bằng CLI sau khi duyệt. Chưa có asset duyệt → nền ffmpeg tự tạo. Nhóm nguồn được phép (HUMAN LEAD 2026-10-24): **hình** — bảo tàng Open Access CC0 (The Met, Smithsonian, Cleveland, Art Institute of Chicago), Wikimedia Commons chỉ file Public Domain / CC0, Pexels / Pixabay (license riêng, không CC0); **nhạc** — YouTube Audio Library (ghi công vào mô tả khi bài yêu cầu), CC0 / public domain (FreePD, OpenGameArt CC0, Musopen), Pixabay Music. Mỗi asset ghi `source` (URL trang) + `license` đúng tên; CC BY-SA / NC / ND không được nạp. Rủi ro biết trước: nhạc CC0 / Pixabay vẫn có thể bị Content ID nhận nhầm — HUMAN LEAD xử lý khiếu nại trên Studio.
- **G4**: thêm `BeVietnamPro-ExtraBold.ttf` (OFL).
- **G5**: đồng ý route / config `[packaging]` (kho mặc định `~/.local/share/auto-short/packaging/`) / job `theme_package` như trên.
- **G6**: variant xóa tay trên trang Đóng gói (hiện dung lượng từng bản); không tự archive.

- **G7** (HUMAN LEAD 2026-10-24, sau G1–G6): thêm **PKG2 — thumbnail cho tập** (bản ngang HD 16:9 + bản dọc 9:16 và 16:9) cho cả bộ kinh, **làm trước VIS1**. Chữ chỉ "tên bộ kinh — Tập N" + người giảng (deterministic từ header, không AI). Output đặt cạnh tập `output/<episode_id>/thumbs/` (ngoại lệ R3 vì đầu vào là tập, không phải TC3). Duyệt = HUMAN LEAD xem lưới + tải zip (R6 thu gọn). Thứ tự mới: PKG1 → PKG2 → VIS1 → AUD1.
- **G8** (HUMAN LEAD 2026-10-24, sau G7): thumbnail tập chỉ ghép ảnh kho + chữ, không phụ thuộc video → mọi tập của bộ kinh (header hợp lệ) đều được dựng **cả 16:9 và 9:16**, kể cả tập đã xóa video trên VM (bản lưu nằm ở máy khác) hoặc chưa có bản HD / bản dọc. Thay điều kiện "tập đủ điều kiện" của PKG2. Task: PKG2.2.

## 5. Ngoài scope

Tự đăng / upload YouTube; YouTube Analytics API; nhật ký thử nghiệm (PKG1.1, bỏ); hàng đăng bài cộng đồng (PUB1, bỏ); AI sinh ảnh / video / giọng; tải media tự động; đổi TC1–TC3, CP8.33 hoặc layout Short.
