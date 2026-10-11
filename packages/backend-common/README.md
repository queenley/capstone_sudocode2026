# `backend-common`: gói dùng chung giai đoạn chuyển tiếp

Phần code mà Commerce, Identity và Sales vẫn dùng chung, cùng một ít mà AI Agent mượn. Gói này **không** chứa AI agent; agent nằm hoàn toàn trong `apps/ai-agent-service`.

| Thư mục | Nội dung | Ai dùng |
|---|---|---|
| `src/db/`, `migrations/` | ORM SQLAlchemy, session, migration `0001` | mọi service, seed, worker |
| `src/core/` | `Settings`, `configure_service`, readiness | mọi service |
| `src/security/` | token, JWT staff, `Security.conversation()`, `mask()` | mọi service; AI Agent dùng để xác thực conversation token |
| `src/api/` | Handler HTTP mà các service đăng ký lại; `tests/conftest.py` gộp chúng thành app test | Commerce, Identity, Sales |
| `src/commerce/`, `src/identity/` | Logic domain còn dùng chung | Commerce, Identity, Sales |
| `src/memory/` | `profile_facts`/`episodes` của agent cũ (trang staff và worker còn đọc) | Sales, worker |
| `src/messaging/` | Outbox relay và Kafka worker (`EVENT_OWNERS`) | các event worker |
| `src/evaluation/` | Hàm tính metric dùng trong test | tests |

## Vì sao gói này còn tồn tại

Các service vẫn dùng chung PostgreSQL, có foreign key chéo domain và transaction xuyên domain. Bỏ gói này, hoặc tách database, khi chưa thay các phụ thuộc đó sẽ làm hỏng luồng đang chạy. Xem [kế hoạch sở hữu dữ liệu](../../docs/architecture/data-ownership-migration.md).

**Không thêm tính năng mới vào đây.** Code chỉ nên ở lại cho đến khi một API/event contract hoặc service sở hữu thay thế được nó. Lâu dài, gói này nên thu nhỏ thành thư viện tiện ích, hoặc bị gỡ bỏ.
