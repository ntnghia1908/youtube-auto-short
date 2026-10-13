# SR1 — Sutra Reader Contract (trang Đọc Kinh)

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | HUMAN LEAD 2026-10-12: APPROVE SR1 (R1–R6, gồm `pypdf==6.20.0`), SR1.1–SR1.3 làm lần lượt, một PR. Hướng đã duyệt: chỉ HUMAN LEAD dùng sau đăng nhập; thêm kinh bằng `.docx` / `.txt` và (đổi ý cùng ngày) **PDF**; v1 = cỡ chữ, mục lục, nhớ chỗ đọc, giao diện đọc, màn hình luôn sáng, đếm biến tụng; nghi thức giữ trong từng bộ; mục "Đọc Kinh" ở thanh trên cùng, không ở thanh tab của trang video |
| Checkpoint | SR1 (S2) |
| Task contract | `docs/tasks/SR1.1-sutra-reader.md`, `docs/tasks/SR1.2-sutra-import.md`, `docs/tasks/SR1.3-sutra-pdf-import.md` |
| Builds on | `docs/decisions/CL1-chinese-learning-contract.md` C1 (quy ước host / application, G11); `docs/decisions/CP8.3-web-contract.md` W2 (auth), W4 (API); CP1 §10 (dependency: thêm `pypdf`, gate R5) |

Khi ACCEPTED, file này là **canonical owner** của: ứng dụng Đọc Kinh (namespace `work/_sutras/`, định dạng văn bản kinh S2, cấu trúc đọc S3, lưu trữ + đếm biến S4, import S5 + PDF S5a, route / API S6, phía client S7, giữ màn hình sáng S8). Nơi khác chỉ trỏ tới đây. Auto Short và Chinese Learning không đổi behavior.

## S1. Boundary (theo CL1 C1 G11)

- Ứng dụng thứ ba trong host. Package `src/auto_short/sutra/`: `markup.py` (S2, S3), `store.py` (S4), `importer.py` (S5), `pdf.py` (S5a), `web.py` (FastAPI `APIRouter`, S6). `markup` / `store` / `importer` **không** import Auto Short, learning hay `web/`; `web.py` chỉ import `fastapi` + package `sutra`.
- Host (`web/app.py` `create_app`) chỉ: `app.include_router(...)` + thêm mục "Đọc Kinh" vào topnav mọi trang tĩnh. Auth middleware hiện có bảo vệ mọi route `/sutras*`, `/api/sutras*` (không thêm `PUBLIC_PATHS`).
- Trang tĩnh trong `web/static/` với tiền tố `sutra` (`sutras.html`, `sutra.html`, `sutra-edit.html`, `sutra.js`, `sutra.css`, `sutra-awake.mp4`); không sửa `app.js`. Dùng chung `style.css` (topbar, nút) — chỉ thêm, không đổi rule cũ.
- Không CLI, không job, không config section mới (giới hạn là hằng trong code).
- Nội dung kinh là bản dịch có bản quyền → chỉ nằm trong `work/_sutras/` (gitignored), không commit; test dùng fixture tự soạn.

## S2. Định dạng văn bản (`sutra.txt`, schema `v1`)

UTF-8, chuẩn hóa NFC khi lưu, xuống dòng `\n`. Mỗi dòng xét theo thứ tự:

| Dòng | Nghĩa |
|---|---|
| `= <tên>` | Tên bộ kinh. Bắt buộc, đúng một lần, là dòng không trống đầu tiên. |
| `~ <text>` | Dòng giới thiệu (dịch giả, nguồn…), chỉ giữa `=` và `@` / `#` đầu tiên. |
| `@ <tên nhóm>` | Nhóm mục lục (vd "Nghi thức đầu", "Chính kinh", "Hồi hướng"). Tùy chọn; mục trước `@` đầu tiên thuộc nhóm không tên. |
| `# <tên mục>` | Mục (chương / phẩm / Nguyện hương…). Mọi nội dung phải nằm trong một mục. |
| `[^<n>]: <text>` | Chú thích `n` (`n` = 1–3 chữ số) của mục hiện tại. |
| dòng trống | Tách đoạn. |
| `\<text>` | Dòng nội dung thường, bỏ `\` (escape các ký tự đầu dòng trên). |
| còn lại | Dòng nội dung. |

- Mỗi dòng nội dung là **một dòng hiển thị** (dài thì tự xuống dòng): kệ giữ ngắt dòng, văn xuôi viết một dòng / đoạn. Không reflow.
- Dòng nội dung bắt đầu `* ` → dòng nhấn mạnh (`strong`, chữ đậm; bỏ tiền tố), vd câu Hán Việt in đậm trước bản kệ dịch (sửa đổi ORCHESTRATOR 2026-10-12 trong lúc SR1.1, theo bản in Thái Thượng). - Dòng nội dung bọc trọn trong `( … )` → chỉ dẫn nghi lễ (`inst`, chữ nghiêng, mờ). Dòng có ≥ 50 % ký tự chữ là chữ Hán (CJK Unified Ideographs) → `han` (font Hán).
- `[^n]` trong dòng nội dung = tham chiếu chú thích; phải có định nghĩa cùng mục, định nghĩa không được dùng → lỗi.
- Lỗi parse (thiếu `=`, nội dung ngoài mục, mục rỗng, chú thích thiếu / thừa / trùng, dòng > 5 000 ký tự, > 2 000 mục) trả **mọi** lỗi kèm số dòng; không lưu văn bản lỗi.
- Giới hạn: văn bản ≤ 2 MB UTF-8.

## S3. Cấu trúc đọc (JSON, kết quả parse — không lưu)

```json
{"schema_version": 1, "title": "…", "intro": ["…"],
 "groups": [{"title": "Chính kinh" | null,
             "sections": [{"id": "s1", "title": "…",
                           "paragraphs": [[{"text": "…", "kind": "text" | "inst" | "han" | "strong"}]],
                           "notes": {"1": "…"}}]}]}
```

`id` = `s<số thứ tự mục từ 1>`, ổn định khi chỉ sửa chữ trong mục. Client dựng DOM bằng `textContent` (không HTML từ dữ liệu).

## S4. Lưu trữ và đếm biến

- `work/_sutras/<slug>/`: `sutra.txt` (S2), `meta.json` (`schema_version` 1, `slug`, `title`, `sha256` của `sutra.txt`, `created_at`, `updated_at`), `recitations.json` (`schema_version` 1, `entries`: `[{"at": "<UTC ISO-8601>"}]`, tăng dần). Ghi bằng `workspace.atomic_write_*`; mỗi slug một khóa (`threading.Lock`) cho read-modify-write.
- `slug`: từ tên bộ khi tạo — bỏ dấu (NFD + bỏ dấu, `đ` → `d`), chữ thường, `[a-z0-9]` nối bằng `-`, ≤ 60 ký tự; trùng → `-2`, `-3`…; slug dành riêng `new` (trùng route trang `/sutras/new`) → bắt đầu từ `new-2` (SR1.2); regex hợp lệ `^[a-z0-9][a-z0-9-]{0,59}$`. Đổi tên bộ không đổi slug.
- Xóa bộ: xóa `work/_sutras/<slug>/` (phải là con trực tiếp của `work/_sutras/`, không symlink) — mất cả lịch sử đếm biến; UI hỏi xác nhận.
- Đếm biến: `+1` thêm `{"at": now}`; hoàn tác xóa entry cuối. Ngày hiển thị theo giờ trình duyệt.
- `work/_sutras/` có tiền tố `_` → danh sách tập, tab Bộ nhớ, `iter_manifests` tự bỏ qua (CL1 C0).

## S5. Import (thêm / sửa bộ kinh)

- Tải lên `.txt` (UTF-8, có / không BOM), `.docx` hoặc `.pdf` (S5a) → server trả văn bản S2 để **xem trước và sửa** trong ô soạn; chỉ lưu khi người dùng bấm Lưu (gửi văn bản S2).
- Body thô (như upload ảnh CP8.15 P5a), tên gốc ở `?name=`; `.txt` / `.docx` ≤ 5 MB, `.pdf` ≤ 30 MB. `.docx`: kiểm zip trước khi mở — tổng kích thước giải nén ≤ 50 MB, ≤ 2 000 member; đọc bằng `python-docx` (extra `[web]`, đã duyệt CP8.31) chỉ đoạn văn thân bài theo thứ tự (bỏ ảnh, bảng chỉ lấy chữ từng ô theo dòng, bỏ header / footer); chú thích Word → `[^n]` + định nghĩa cuối mục.
- Chuyển sang S2: văn bản đã có dòng `=` → giữ nguyên. Còn lại theo heuristic: dòng đầu không trống → `=`; đoạn style Heading (docx) hoặc dòng ngắn (≤ 80 ký tự) toàn chữ in hoa / bắt đầu `CHƯƠNG`, `PHẨM`, `Phẩm`, `Chương` (+ số / chữ) → `#`; dòng trống liên tiếp gộp một; mỗi đoạn docx = một dòng (dòng ngắt mềm trong đoạn giữ thành nhiều dòng). Heuristic chỉ là gợi ý — người dùng sửa trước khi lưu.

## S5a. Import PDF

PDF chỉ có lớp chữ mới import được (PDF scan → 422 "PDF không có lớp chữ"). Chữ trích ra luôn cần người soát: thuật toán là gợi ý, ô soạn S5 là nơi sửa.

- **An toàn:** parse trong **process con** (`python -I -m auto_short.sutra.pdf <file>`; route web chạy `python -I -c` nạp đúng thư mục `src/` chứa package đang phục vụ request, vì `-I` bỏ `PYTHONPATH`; file tạm trong `work/_sutras/.tmp/`, giới hạn bộ nhớ `RLIMIT_AS` 3 GiB trong process con), timeout 120 s (quá → 504, kill process), ≤ 1 000 trang; process con chỉ trả JSON văn bản S2 + cảnh báo. Lý do: pypdf từng có lỗi vòng lặp / bộ nhớ với file hỏng; không để chặn process web.
- **Trích dòng:** lấy từng đoạn chữ kèm vị trí (x, y) và cỡ chữ qua text visitor của pypdf; chuẩn hóa NFC (bản Google Docs tách rời dấu từng ký tự); gộp đoạn cùng `y` (± 2.5 pt) thành dòng; trang ngang có chữ ở hai nửa → **2 cột** (sách in 2 trang / tờ), đọc cột trái rồi cột phải; trong một dòng, khoảng trống lớn (> 40 pt) giữa chữ Việt và chữ Hán → hai ô riêng (cột chữ Hán song song).
- **Bỏ header / footer:** chuỗi (bỏ số) lặp trên ≥ 15 % số trang (≥ 3 trang) → xóa, kể cả khi dính vào đầu / cuối dòng khác. Xét ở 20 % trên / dưới trang; dòng có chứa số (số trang) xét **ở mọi vị trí** (bản Google Docs đặt footer ngay sau chữ cuối trang, y thay đổi). Không xóa câu lặp không có số ở giữa trang (vd "Xá Lợi Phất! …" lặp trong A Di Đà). Dòng chỉ có số ở vùng trên / dưới (số trang) → xóa, **sau** bước chú thích (số chú thích cỡ nhỏ ở cuối trang không phải số trang).
- **Tiêu đề mục (`#`):** dòng toàn chữ in hoa (≥ 3 chữ cái, ≤ 80 ký tự, không chữ Hán) thụt / căn giữa so với lề, hoặc cỡ chữ lớn hơn thân bài; các dòng tiêu đề liền nhau gộp một.
- **Ghép dòng logic:** lề trái = x phổ biến nhất của thân bài theo (cột, trang chẵn / lẻ) trên **cả tài liệu**; dòng thụt (> 8 pt) mở dòng mới; dòng sát lề là dòng nối nếu mục có dòng thụt, hoặc dòng trước dài gần hết cột (≥ 80 % độ dài P90 của cột); dòng bắt đầu chữ thường luôn là dòng nối. Khoảng cách dọc > 1.5 × bước dòng → dòng trống (tách khổ / đoạn). Mục văn xuôi (dòng logic trung bình > 70 ký tự) → mỗi đoạn cách nhau một dòng trống.
- **Sửa chữ:** "h ữu" → "hữu": Word tách dấu thành đoạn chữ riêng bắt đầu bằng dấu cách (`' ữ'`) đặt chồng lên chữ trước → quyết định dấu cách theo khoảng cách x giữa các đoạn, không theo dấu cách trong đoạn; dự phòng: ghép X + Y khi Y (bắt đầu bằng nguyên âm) không phải âm tiết tiếng Việt đứng riêng còn X + Y là âm tiết hợp lệ.
- **Chữ đậm:** cả dòng logic dùng font đậm (tên font chứa `Bold`), không phải tiêu đề → tiền tố `* `; bỏ qua khi phần lớn (≥ 50 %) dòng thân bài là chữ đậm (sách in toàn chữ đậm).
- **Giãn dòng:** khoảng cách tới dòng trước > 1.15 × bước dòng trung vị cả tài liệu → dòng logic mới (kệ in giãn dòng hơn văn xuôi, không thụt lề); dòng đầu trang dùng bước dòng của trang.
- **Header theo chương:** dòng ở 12 % trên / dưới trang gồm chữ in hoa + số trang (vd "PHÁP TẠNG NHÂN ĐỊA ĐỆ TỨ 35") → bỏ, dù không lặp đủ 15 % số trang.
- **Chữ nhỏ đánh số kiểu danh sách** (`1. Quốc vô ác đạo nguyện.` cuối trang) là thân bài, không phải chú thích.
- **Font VNI cũ (SR1.5, sửa đổi 2026-10-12):** đoạn chữ dùng font tên chứa `VNI-` (trừ font ký hiệu) → đổi bảng mã VNI-Windows sang Unicode trước khi ghép dòng (gộp các đoạn VNI liền nhau rồi mới đổi, vì một chữ có thể bị tách hai đoạn). **Ký hiệu pháp khí / nhịp** (sách nghi thức: chuông, mõ, khánh) → bỏ: đoạn chữ thuộc font ký hiệu (`VNI-Helve`, `SegoeUISymbol`, …) hoặc chỉ gồm ký tự ký hiệu (`O ● • ▬ ◎ ° Þ þ Ⴃ ー …`); dòng chỉ còn ký hiệu → bỏ. Bài in dạng bản nhạc (chữ rải theo nốt) không dựng lại được → cảnh báo, người dùng tự gõ.
- **Danh sách đánh số:** dòng bắt đầu `\d+\. ` luôn mở dòng logic mới.
- **Chú thích:** cỡ chữ so với trung vị **của trang** (có trang in cỡ nhỏ hơn toàn sách — A Di Đà trang phụ lục — không được coi cả trang là chú thích); số nhỏ (cỡ < 85 % thân bài) ngay sau một chữ → `[^n]`; dòng cỡ nhỏ ở 20 % cuối trang bắt đầu bằng số → định nghĩa `[^n]:` đặt cuối mục chứa tham chiếu; không ghép được → cảnh báo.
- **Cảnh báo** trả về (`warnings`): trang không có chữ, chú thích không ghép được, mục quá dài / quá ngắn bất thường.
- Thuật toán thử trên 3 PDF đầu (ORCHESTRATOR, 2026-10-12, prototype ngoài repo): chính văn A Di Đà, Thái Thượng tách đúng mục và đoạn; còn lỗi nhỏ ở vài mục kệ / chú; Vô Lượng Thọ còn header "KINH VÔ LƯỢNG THỌ - ÂM HÁN VIỆT n" lẫn vào tiêu đề phẩm (đã sửa bằng quy tắc header có số trang). Bản Vô Lượng Thọ đầy đủ HUMAN LEAD gửi sau (AMTBVN, 182 trang, sách chữ lớn): nhận đủ 48 phẩm + 48 nhãn nguyện sau các quy tắc giãn dòng / header theo chương / chữ nhỏ đánh số. Số đo chính thức do SR1.3 ghi.

**Số đo SR1.3** (2026-10-12; `scripts/sutra_pdf_measure.py`, qua đúng đường `importer.import_pdf` + `markup.parse`; 4 PDF thật, không commit nội dung):

| PDF | Trang | Mục nhận / mục thật | `markup.parse` | Header còn sót (dòng / dính trong dòng) | Dòng ngắt dở (< 45 ký tự, không dấu câu cuối, trong mục văn xuôi) | Cảnh báo | Thời gian |
|---|---|---|---|---|---|---|---|
| A Di Đà (2 trang / tờ) | 25 | 24 / 24 (danh sách tiêu đề trùng bản hand-clean) | OK | 0 / 0 | 6 | 4 | 1.3 s |
| Thái Thượng Cảm Ứng Thiên | 34 | 12 / 11 (thừa 1 tiêu đề ở trang bìa) | OK | 0 / 0 | 0 | 2 | 1.4 s |
| Vô Lượng Thọ Google Docs (cắt ở phẩm 31) | 78 | 39 / 39 (31 phẩm + 7 mục nghi thức + "Mở đầu") | OK | 0 / 0 | 42 | 2 | 4.1 s |
| Vô Lượng Thọ đầy đủ (AMTBVN) | 182 | 67; **48 / 48 phẩm "… ĐỆ …"**, **nhãn nguyện 1–48: 48 / 48** | OK | 0 / 0 | 16 | 3 | 5.0 s |

So với bản ORCHESTRATOR hand-clean (cùng nguồn): A Di Đà lệch 121 / 432 dòng, Thái Thượng lệch 75 / 968 dòng (chủ yếu dòng `@` nhóm và `~` giới thiệu không có trong PDF, khổ kệ bị nối do dòng đủ dài, đánh số lại `[^n]` theo mục). Chữ sai dấu còn sót: 0 trong Thái Thượng (tách dấu Word), 0 "ĐỆTỨ"-kiểu dính chữ trong bản đầy đủ.

Làm rõ khi triển khai (không đổi hướng S5a): (1) cụm lặp **không có số** chỉ bị xóa khi cả dòng khớp và lặp ở cùng độ cao (±4 pt) — giữ lại câu điệp trong bài tụng; dính đầu / cuối dòng chỉ xét với dòng có số; (2) một dòng có đoạn cỡ chữ lệch > 1.4 lần (footer cỡ nhỏ dính tiêu đề cỡ lớn cùng y trong bản Google Docs) tách thành hai ô; (3) header theo chương nhận số ở đầu, cuối hoặc **giữa** hai tên chương; cũng áp cho dòng cỡ ≤ 60 % thân bài ở bất kỳ vị trí; "PHẨM 12" cuối dòng vẫn là tiêu đề; (4) số trang trơn ở 8 % trên / dưới xóa bất kể cỡ chữ; (5) tiêu đề: dòng toàn hoa thụt > 6 pt hoặc cỡ > 1.03 × thân bài; (6) dấu chú thích `[^n]` gắn ngay lúc trích dòng (số nhỏ ngay sau chữ cùng dòng), định nghĩa tra theo (trang, số), đánh số lại theo mục; (7) dấu cách đầu đoạn chữ "` ữ`" chỉ bỏ khi chữ có dấu (không phải ASCII) và x tới đoạn kế cho độ rộng hợp lý; (8) mục không có nội dung bị bỏ (cảnh báo); dòng logic > 4 000 ký tự được chia ở dấu câu (giới hạn 5 000 của S2); tên bộ lấy tạm từ tên file (cảnh báo).

Giới hạn còn lại: khổ kệ có dòng gần bằng dòng văn xuôi bị nối thành một dòng (A Di Đà 2 trang / tờ: nhiều khổ); chữ Hán song song chỉ tách khi cách chữ Việt > 40 pt; trang bìa / mục lục cho tiêu đề rời rạc; PDF xoay `/Rotate` chưa xử lý; PDF scan → 422 (OCR ngoài scope).

**Số đo SR1.5** (2026-10-12; cùng script và cách đo như SR1.3; 5 PDF thật, không commit nội dung):

| PDF | Mục | `markup.parse` | Header sót | Dòng ngắt dở | Cảnh báo | So với SR1.3 |
|---|---|---|---|---|---|---|
| A Di Đà (2 trang / tờ) | 24 | OK | 0 / 0 | 6 | 4 | văn bản giống hệt từng dòng |
| Thái Thượng Cảm Ứng Thiên | 12 | OK | 0 / 0 | 0 | 2 | giống hệt |
| Vô Lượng Thọ Google Docs | 39 | OK | 0 / 0 | 42 | 2 | giống hệt |
| Vô Lượng Thọ đầy đủ (182 trang) | 67; 48 / 48 phẩm; nhãn nguyện 48 / 48 | OK | 0 / 0 | 16 | 3 | giống hệt |
| A Di Đà Hán Việt (font VNI, sách nghi thức; mới) | 25 (trước: 61, nhiều tiêu đề giả từ ký hiệu / chữ lỗi mã) | OK | 0 / 0 | 52 | 39 (4 là "đoạn dạng bản nhạc") | trước SR1.5: `PHAÄT`, `Ñ`, `ö` khắp nơi; sau: 0 chuỗi mã VNI sót |

Mục "PHẬT THUYẾT A DI ĐÀ KINH" ra chữ Unicode đúng. Còn lại: các bài tán / hồi hướng in dạng bản nhạc (mục "Mở đầu", "TÁN PHẬT KỆ", "PHẦN PHỤ LỤC:", "NGUYỆN") vẫn rời rạc, kèm vài tiêu đề giả (`Y Y Y`, `TIẾP` / `DẪN` / `NGUYỆN`) do nốt nhạc; người dùng tự gõ lại.

Làm rõ khi triển khai (SR1.5): (1) bộ đổi VNI nằm ở `sutra/vni.py` (bảng ghép nguyên âm + dấu, chữ hoa / thường, bộ ký tự `ô ö ñ æ ó ò î`); (2) đoạn thuộc font ký hiệu / chỉ có ký hiệu được thay bằng một dấu cách (không dính hai chữ hai bên); đoạn chỉ gồm `O` được giữ khi nằm sát chữ liền kề (< 0.6 × cỡ chữ), dấu `•` đầu dòng ở font thường được giữ (gạch đầu dòng của văn bản thường, có trong Vô Lượng Thọ); (3) cảnh báo "bản nhạc": mục ≥ 30 từ có ≥ 30 % từ chỉ một chữ cái (ngưỡng "1–2 chữ cái" làm chú Đại Bi báo nhầm vì âm tiết hai chữ); (4) font TCVN3 / VISCII (`.Vn…`, `TCVN`, `VISCII`) chỉ cảnh báo, không đổi; (5) văn bản `.txt` / `.docx` không có dòng `#` / `@` nhưng có nội dung → chèn `# <tên bộ>` sau dòng `=` (và các dòng `~`) kèm cảnh báo.

## S6. Route / API

Trang (HTML tĩnh, `Cache-Control: no-cache`): `GET /sutras` (thư viện), `GET /sutras/new`, `GET /sutras/{slug}` (đọc), `GET /sutras/{slug}/edit`. Slug không hợp lệ / không có → 404.

| API | Body / kết quả |
|---|---|
| `GET /api/sutras` | `[{slug, title, sections, recitations: {total, last_at}, updated_at}]`, theo `title` |
| `GET /api/sutras/{slug}` | S3 + `slug`, `sha256`, `recitations: {total, entries}` (≤ 400 entry cuối) |
| `GET /api/sutras/{slug}/text` | `{text, sha256}` (để sửa) |
| `POST /api/sutras` | `{text}` → 201 `{slug}`; 400 `{errors: [{line, message}]}`; `?dry_run=1` → 200 S3, không ghi (xem trước) |
| `PUT /api/sutras/{slug}` | `{text, sha256}` → 200; `sha256` khác bản đang lưu → 409 (bị sửa nơi khác) |
| `DELETE /api/sutras/{slug}` | 200 |
| `POST /api/sutras/import?name=` | body thô → `{text, warnings}`; 413 quá lớn; 415 không phải `.txt` / `.docx` / `.pdf`; 422 file hỏng / PDF không có lớp chữ; 504 PDF quá thời gian |
| `POST /api/sutras/{slug}/recitations` | → `{total, entry}` |
| `DELETE /api/sutras/{slug}/recitations/last` | → `{total}`; 409 khi chưa có entry |

JSON body ≤ 3 MB (413). Lỗi trả `{"detail": "<tiếng Việt>"}` như CP8.3.

## S7. Phía client

- Mobile-first, vanilla JS. Trang đọc: thanh công cụ ẩn khi cuộn xuống, hiện khi cuộn lên / chạm giữa màn hình; mục lục dạng sheet theo nhóm `@`, đánh dấu mục đang đọc; cài đặt: cỡ chữ 14–32 px (bước 2), giãn dòng 1.4 / 1.7 / 2.0, chữ có chân / không chân, nền Sáng / Giấy / Tối.
- **Sửa đổi HUMAN LEAD 2026-10-12 (SR1.4):** cài đặt thêm **Độ đậm chữ** Thường / Đậm (áp cho toàn bộ chữ; bỏ "Đậm vừa" 2026-10-13 vì font hệ thống không có bậc 500, nhìn như Thường — HUMAN LEAD; dòng `strong` luôn đậm hơn chữ thường một bậc) và **Kiểu đọc**: Cuộn dọc (mặc định, như trên) / Lật trang ngang như sách (mỗi trang vừa một màn hình, vuốt trái / phải hoặc chạm mép trái / phải để sang trang, có số trang `x / y` của bộ kinh; đổi cỡ chữ / kiểu đọc giữ đúng chỗ đang đọc). Vị trí đọc vẫn lưu theo `{section, offset}` cho cả hai kiểu.
- Lưu trong `localStorage` (mọi truy cập bọc `try/catch`, trang chạy được khi không có): cài đặt chung `sutra:settings`; vị trí đọc `sutra:pos:<slug>` = `{section, offset (0–1 trong mục), sha256, at}` — lưu khi cuộn (debounce) và khi rời trang; mở lại → về đúng vị trí; thư viện có "Đọc tiếp". `sha256` đổi → về đầu mục cùng `id` nếu còn.
- Cuối kinh: nút "Tụng xong (+1 biến)"; đầu trang: "Đã tụng N biến · hôm nay M", mở lịch sử theo ngày (30 ngày gần nhất) + "Hoàn tác biến vừa ghi".
- Thư viện: danh sách bộ, số biến, lần tụng cuối, "Đọc tiếp" / "Đọc từ đầu", "Thêm bộ kinh"; sửa / xóa trong trang đọc (menu).

## S8. Giữ màn hình sáng

- Nút "Giữ màn hình sáng" (mặc định bật khi đang đọc, nhớ trong `sutra:settings`). Thử `navigator.wakeLock.request("screen")` (chỉ có trên HTTPS / localhost; xin lại khi `visibilitychange` về `visible`).
- Không có Wake Lock (web 8080 là HTTP trong LAN) → dự phòng: `<video muted playsinline loop>` phát `sutra-awake.mp4` (video đen rất nhỏ, có track âm thanh im lặng, vài KB, sinh bằng `ffmpeg`, lệnh ghi trong task) bắt đầu trong một thao tác chạm của người dùng; tạm dừng khi trang ẩn.
- Không đảm bảo trên mọi trình duyệt — kiểm thật trên điện thoại HUMAN LEAD (manual test). Không đạt → hướng tiếp theo (HTTPS trong LAN) là decision riêng.

## Ngoài scope SR1

OCR PDF scan (không có lớp chữ); tự cuộn; đánh dấu trang, tìm kiếm; chế độ ẩn / hiện lớp Hán / Hán Việt / Việt; đồng bộ vị trí đọc giữa thiết bị; offline (service worker); người đọc khác / công khai; TTS / audio tụng.

## Decision gates (HUMAN LEAD)

| Gate | Đề xuất |
|---|---|
| R1 boundary | Ứng dụng `sutra` theo S1, chung process / auth web |
| R2 định dạng | S2 (markup dòng) làm nguồn duy nhất, sửa tay được |
| R3 lưu trữ | S4 (`work/_sutras/`, không commit nội dung) |
| R4 security | Chỉ sau đăng nhập; upload theo giới hạn S5 / S6; không HTML từ dữ liệu |
| R5 dependency | Thêm `pypdf==6.20.0` (thuần Python, BSD-3, không kéo dependency khác trên Python 3.12) vào extra `[web]`, chỉ dùng trong `sutra/pdf.py`; python-docx đã có. Đã cân nhắc, không chọn: PyMuPDF (AGPL, binary), pdfminer.six / pdfplumber (nặng hơn, không cần) |
| R6 giữ màn hình sáng | S8 (Wake Lock + video dự phòng, chấp nhận rủi ro trình duyệt) |
