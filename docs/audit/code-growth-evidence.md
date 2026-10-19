# Code growth — bằng chứng đầu vào cho AUDIT-code-growth

| Metadata | Value |
|---|---|
| Status | EVIDENCE — NOT AUTHORITY |
| Đo ngày | 2026-10-19, kỳ 2026-09-26 → 2026-10-19, `origin/main` |

Đầu vào cho `docs/tasks/AUDIT-code-growth.md`. Repository public: file này chỉ có số tổng hợp, không chép prompt / transcript.

## 1. Kích thước hiện tại (`git ls-files`)

- Python ứng dụng (ngoài `tests/`): ≈ 34,1k dòng; test Python: ≈ 31,5k dòng; JS / HTML / CSS: ≈ 6,5k dòng.

## 2. Theo PR merge (`code-growth-prs.tsv`)

Mỗi dòng = một merge commit first-parent trên `main`, `git diff --numstat <merge>^1 <merge>`. Nhóm: `app` = `*.py` ngoài `tests/` (gồm `src/`, `scripts/`, `tools/` — audit cần tách script bench khỏi `src/`); `test` = `tests/`; `web` = `*.js|*.html|*.css`; `doc` = còn lại. Cột `task / type / implementer` nối với contract qua dòng `- PR:` trong Result hoặc prefix tên nhánh; 58/103 PR khớp (PR lớn chưa khớp: SR1 #82, CP13.1 #57, TC-WEB1 #96, CL1 #12, CP11 #41).

- 103 PR: app +34,6k / −2,4k (xóa 6,8 %); test +34,1k / −1,9k.
- Theo Type (58 PR khớp):

| Type | PR | app + / − | tỉ lệ xóa | test + | web + |
|---|---|---|---|---|---|
| FEATURE | 30 | 22.359 / 566 | 3 % | 22.711 | 4.522 |
| CHANGE | 21 | 4.700 / 1.601 | 34 % | 5.157 | 1.246 |
| BUG | 6 | 530 / 59 | 11 % | 900 | 32 |

- Test ≈ 1 : 1 với code ứng dụng; BUG ≈ 1,7 dòng test / dòng code.
- Theo IMPLEMENTER (field contract): subagent Claude 34 PR app +12,6k / −0,6k; Codex 4 PR app +0,3k / −1,2k (mẫu nhỏ, chủ yếu CHANGE); 18 PR không ghi IMPLEMENTER.

## 3. Prompt giao việc cho subagent `implementer` (transcript local, 73 phiên)

Chỉ đếm cờ trong prompt đầu tiên và số dòng của tool `Edit` / `Write`; không lưu nội dung.

- Prompt nhắc tái dùng hàm / helper có sẵn: 15/73; nhắc xóa / gỡ code bị thay: 21/73; "tối thiểu / không mở rộng": 10/73; "giữ nguyên": 3/73; giới hạn phạm vi test: 0/73.
- Độ dài prompt: median ≈ 3,3k ký tự, p90 ≈ 4,9k.
- Dòng viết bởi `Edit` / `Write`: 34,4k; dòng bị thay (old_string): 1,3k → 26,5 dòng viết / dòng thay.
- Prompt có nhắc tái dùng hoặc xóa: 17,9 dòng viết / dòng thay (29 phiên); không nhắc: 522,8 (44 phiên). Chỉ là tương quan: phiên tạo module mới thường không có chỉ dẫn xóa.
- Lớn nhất theo dòng viết: CP8.15 (5,1k), CP8.9 (3,2k), CP8.5 (2,3k), CP13.1b (2,2k), CP9 (1,9k), CP7 (1,8k).

## 4. Giới hạn

- Transcript và Codex session chỉ có trên VM; phiên cloud dùng số ở mục 3 thay vì đo lại.
- `git diff` gồm cả file sinh / fixture; một dòng có thể là dữ liệu test lớn.
- Không đo trùng lặp, code chết hay độ phủ — là việc của audit.
