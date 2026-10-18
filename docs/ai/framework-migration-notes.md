# Framework Migration Notes

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Scope | Canonical owner của chính sách validate task legacy (v4.2) và giới hạn migration v4.4 |

## Legacy task validation

- `framework.config.json` → `legacyTasks` liệt kê 83 task contract có tại base commit `6f796c068aaad03852aacc2fb962062fc5e23d79` (trừ `_template.md` và `AS-FW-UPGRADE-01.md`). Danh sách này đóng băng.
- Các file đó được validate bằng rule task của v4.2 (field và section như trước); bỏ qua `Authorization mode`, `Authorization source`, `Implementer`. Chúng không bị viết lại.
- Task mới (mọi file ngoài danh sách) chịu đầy đủ rule v4.4.
- Thêm file vào `legacyTasks` cần quyết định của HUMAN LEAD.

## Sửa mâu thuẫn của kit checker v4.4

Dưới `governance.taskAuthorization=boundary`, kit từ chối mọi task có mode khác `boundary`, dù comment của kit nói mode `task` tường minh vẫn được phép. Checker của project: task không legacy phải khai `- Authorization mode:` tường minh là `task` hoặc `boundary` (thiếu → FAIL); `boundary` vẫn cần Authorization source thật. Không nới check v4.4 nào khác.

## Concurrency

`maxParallelImplementers=3` chỉ là trần cấu hình. Số writer thực tế là 1 cho tới khi có pilot worktree-isolation được duyệt riêng.
