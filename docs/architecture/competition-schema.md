# Schema platform và ánh xạ dataset

Migration chính thức của platform là `packages/backend-common/migrations/0001_competition.sql` (PostgreSQL 16). Một database được chia schema theo domain. UUID là khóa nội bộ. Mã nguồn từ dataset (`CONV-001`, mã SKU) giữ nguyên dạng text. Không cần extension vector. Redis (working memory có TTL) và mọi index vector đều là dữ liệu dẫn xuất, không phải nguồn sự thật.

Schema `agent` của AI Agent **không** nằm trong migration này. Service tạo schema khi khởi động (`runtime/db.py`, các MCP server), và dữ liệu nghiệp vụ agent dùng khi chấm điểm lấy từ `apps/ai-agent-service/data/btc` ([kiến trúc](microservices-target-structure.md#quy-tắc-sở-hữu)).

## Ánh xạ dataset vào platform

| Đầu vào | Đích | Quy tắc |
|---|---|---|
| `catalog_skus.csv` | `commerce.products`, `skus`, `inventory` | Gom product theo `parent_id`; giữ `sku`, domain, màu, nguồn, cờ synthetic. `stock` → `quantity_on_hand` |
| `synthetic_sku_variants.csv` | `commerce.skus` | Bổ sung; khử trùng theo `sku_code` |
| `promotions.csv` | `commerce.promotions` | Giữ mô tả và channel. Văn bản tự do nhập với giá trị NULL; không suy ra mức giảm từ văn xuôi |
| `policies.csv` | `commerce.policies` | Giữ ID chính sách và ngày hiệu lực theo phiên bản |
| `customers.csv`, `conversations.jsonl`, `scenarios.json`, `judge_rubrics.json`, `voice_notes.jsonl` | không nạp vào runtime | Chỉ là dữ liệu đánh giá; không bao giờ đưa gold hay transcript tham chiếu cho agent. Không lưu CCCD |

Ngày trong dataset theo giờ Asia/Saigon. `end_date` (tính cả ngày đó) được đổi thành nửa đêm đầu ngày hôm sau, lưu kiểu `timestamptz`. Khuyến mãi chỉ áp dụng khi active **và** `starts_at <= now < ends_at` **và** khớp channel/SKU; `status=active` thôi là chưa đủ. Khi đánh giá, dùng ngày mô phỏng, không dùng đồng hồ máy.

## Bất biến nghiệp vụ

- **Định danh:** chuẩn hóa rồi băm HMAC có khóa; khóa nằm ngoài PostgreSQL. Số điện thoại dùng chung chỉ trả về danh sách ứng viên, không phải danh tính đã xác thực. Phải xác minh trước khi tiết lộ lịch sử. Consent và `verified_at` là bằng chứng, không thay cho phân quyền.
- **Fact hồ sơ:** thay trong một transaction: khóa khách, đóng `valid_to` của fact cũ, chèn fact mới có `supersedes_id` và nguồn. Không lưu giá hay tồn kho thành fact lâu dài.
- **Order:** khóa tồn kho theo thứ tự SKU cố định, kiểm tra còn hàng, làm mới giá và khuyến mãi, yêu cầu khách xác nhận và có thông tin giao hàng, reserve, tính tổng, ghi outbox, tất cả trong cùng transaction. Hủy order trả reserve đúng một lần.
- **Sở hữu:** service phải kiểm tra message, feedback, trace, episode và handoff thuộc đúng khách. Foreign key chỉ bảo đảm bản ghi tồn tại, không cô lập dữ liệu giữa các khách.
- **PII:** mã hóa địa chỉ và định danh; che input/output của tool trong log. Chính sách giữ và xóa dữ liệu áp dụng cho message, fact, episode, định danh, index ngoài và cả schema `agent`.
- **Quyền DB:** dùng role tối thiểu (`scripts/migration/provision_db_role.py`). Role runtime không đọc được schema `evaluation`. Tool gọi qua service, không chạy SQL tùy ý.
- **Tri thức:** chỉ người có quyền mới duyệt proposal. Outbox giao ít nhất một lần, consumer phải khử trùng theo event id.

## Áp dụng và kiểm tra

```powershell
Get-Content -Raw packages/backend-common/migrations/0001_competition.sql | docker compose exec -T postgres psql -U postgres -d app_db -v ON_ERROR_STOP=1
python scripts/migration/validate_dataset.py C:\path\to\sudo_code_2026_dataset
```

Chạy migration một lần trên database trống. Migration chạy trong transaction và cố ý báo lỗi nếu chạy lại. Thay đổi về sau phải thêm migration mới có số thứ tự; không reset database đang có dữ liệu. `validate_dataset.py` chỉ đọc: nó kiểm tra số lượng, ID trùng, giá, tồn kho và tham chiếu, chứ không chứng nhận tuân thủ đề thi hay đánh giá agent.
