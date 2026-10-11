# Kế hoạch sở hữu dữ liệu

Các service đã có entry point HTTP riêng nhưng chưa độc lập về database. **Đừng trỏ một service sang database trống chỉ bằng cách đổi biến môi trường.** Schema hiện tại có foreign key chéo domain, và luồng order và xóa dữ liệu dựa vào transaction dùng chung.

## Ai sở hữu bảng nào

| Owner | Bảng |
|---|---|
| Identity | `identity.customers`, `customer_identities`, `customer_access`, `challenges`, `staff_users`, `audit_logs` |
| Sales | `conversation.conversations`, `messages`, `handoffs`, `improvement.feedback`, `improvement.proposals` |
| Commerce | `commerce.products`, `skus`, `inventory`, `promotions`, `policies`, `orders`, `order_items` |
| AI Agent | schema `agent`: `calls`, `turns`, `pii_vault`, checkpoint LangGraph, `mock_state`, ledger, `kb_chunks` (tạo khi service khởi động) |
| Di sản agent cũ | `memory.profile_facts`, `memory.episodes`, `conversation.turn_traces`, `tool_executions`: agent hiện tại không ghi vào các bảng này nữa, chỉ còn worker `conversation.ended` và trang staff đọc |
| Event relay | `improvement.outbox`, `processed_events` (hạ tầng dùng chung tạm thời) |

Schema `agent` đã tách về logic. Agent chỉ tham chiếu `conversation_id` dưới dạng giá trị, không có foreign key sang bảng platform. Vì vậy dữ liệu của agent có thể chuyển sang database riêng ngay bây giờ: đặt `AGENT_DATABASE_URL` cho schema `agent`, còn `DATABASE_URL` vẫn trỏ vào database platform để phục vụ bốn điểm chạm trong [kiến trúc](microservices-target-structure.md#hiện-trạng). Muốn agent hoàn toàn không cần `DATABASE_URL`, Sales phải cung cấp API cho bốn điểm chạm đó.

## Phụ thuộc chéo cần gỡ

- Conversation của Sales tham chiếu customer của Identity.
- Order của Commerce tham chiếu customer và conversation. Khi đặt order, hệ thống kiểm tra khách, quote, tồn kho và xác nhận trong cùng một transaction.
- Challenge của Identity tham chiếu conversation, và bước xác minh gắn khách vào conversation trong cùng transaction.
- AI Agent ghi `messages` và `handoffs` trực tiếp, qua `runtime/platform.py`.
- Lệnh xóa dữ liệu khách (`DELETE /api/customer/data`, chạy ở Identity) che conversation, memory, feedback và địa chỉ giao hàng của Commerce trong một transaction. Lệnh này **chưa** xóa `agent.pii_vault` và fact ledger; phải bổ sung trước khi xử lý khách thật.

Các quan hệ này phải chuyển thành API hoặc projection theo event (idempotent) trước khi di chuyển bảng. Đặt order và xóa dữ liệu cần điều phối kiểu saga. Chỉ bỏ foreign key mà không thay thế sẽ sinh dữ liệu lệch nhau.

## Trình tự an toàn

1. Thêm API nội bộ cho xác minh/tra cứu khách, trạng thái conversation, lệnh order, và phần ghi transcript/handoff mà agent đang dùng. Dùng xác thực giữa các service; không tin `customer_id` do trình duyệt gửi.
2. Đưa việc đặt order ra sau API lệnh của Commerce (Sales gọi). Giữ reserve tồn kho và idempotency trong một transaction của Commerce.
3. Cho mỗi service outbox và relay offset riêng. Topic theo domain đã có trong `contracts/kafka/topics.md`; giữ legacy mirror cho đến khi consumer chuyển hết.
4. Tạo database riêng, chạy migration theo owner, backfill một snapshot nhất quán. Chạy shadow read, so ID và số lượng, rồi mới chuyển từng owner.
5. Chuyển ghi sang owner, theo dõi độ trễ event và đối soát. Chỉ xóa bảng cũ và mirror sau khi hết thời hạn rollback.

Cho đến khi xong các bước trên, `DATABASE_URL` vẫn là database chuyển tiếp dùng chung.
