# Backlog cải tiến

## Đợt gia cố backend/frontend

Nguồn chuẩn theo người dùng: giữ toàn bộ main `41eda49`, gồm test/harness/scorer; bỏ bước khôi phục ZIP BTC. Không sửa dataset/ASR/ITN/lexicon. Việc cần model thật nằm trong [WAITING-FOR-USER.md](WAITING-FOR-USER.md).

Đã triển khai, cần giữ regression test khi thay đổi tiếp:

- Proxy PATCH/HEAD/OPTIONS, giới hạn request/frame, timeout, request ID, streaming cleanup và rate limit Redis có TTL nguyên tử.
- Kiểm tra payload idempotency, COD khi thiếu phương thức, phục hồi đơn bằng key trong phạm vi khách, transaction và tranh chấp tồn kho.
- Guard không lấy lệnh đọc đơn làm bằng chứng tạo đơn; đối chiếu mã đơn/trạng thái, không để mệnh đề lịch sử bỏ qua cam kết mới.
- Cách ly fact chưa xác nhận; không tự nâng toàn bộ fact chỉ vì xác nhận liên hệ trước. Chặn ghi vào khách đã xóa.
- Outbox xóa dữ liệu có chữ ký nội bộ, receipt theo dõi sau thu hồi tài khoản, cleanup call/vault/checkpoint và chặn checkpoint/ghi muộn.
- Một cuộc mở cho mỗi conversation khi kết nối đồng thời; đóng cuộc chờ lượt đang chạy; nhận handoff idempotent, chặn force vượt bảo vệ dữ liệu.
- Frontend chống response cũ, xác nhận lại giá/đơn, retry cùng lượt chat, SSE CRLF/Unicode, polling đúng cuộc và giải phóng tài nguyên voice.
- Gap Loop có người duyệt/nguồn công khai, KB version atomic/serialized, đề xuất regression chưa duyệt; rubric judge tùy chọn có trạng thái INCOMPLETE.

Kiểm tra local và cách tái lập được ghi trong `docs/verification.md`. Các kết quả chất lượng model và ngưỡng hiệu năng còn chờ, không đánh dấu đạt từ test giả.

## Backlog nghiên cứu trước đợt gia cố

Một dòng mỗi cải tiến. Khi bắt đầu làm, tạo file `NNN-ten-ngan.md` từ [mẫu](_TEMPLATE.md) và điền cột "File".

Các mục dưới đây lấy từ lỗi và giới hạn **đã ghi nhận** trong [docs/ai/05-danh-gia.md](../ai/05-danh-gia.md#9-còn-thiếu). Ưu tiên chỉ là gợi ý ban đầu, nhóm tự sắp lại.

| # | Cải tiến | Vấn đề / bằng chứng | Loại | Chỉ số | Ưu tiên | Trạng thái | File |
|---|---|---|---|---|---|---|---|
| 1 | Không hỏi mở mã đơn khi đã tra được | 5/5 câu hỏi thừa ở run 5 case mới là hỏi `order_id` (0051, 0070, 0086) | prompt + tool flow | RQR | cao | ý tưởng | |
| 2 | Luôn gọi `order.create` / `order.status` khi kịch bản cần | 0070, 0086 call_2/3 thiếu tool khớp | prompt / lane | TSR | cao | ý tưởng | |
| 3 | Nói đúng `return_days` theo chính sách hiện hành | 0129 call_2 nói 14 và 30 ngày thay vì 7 | hard guard / tri thức | HR, TSR | cao | ý tưởng | |
| 4 | Giới hạn số câu hỏi mỗi cuộc | 0142 call_3 hỏi 5 câu, giới hạn 2 | prompt / hard guard | TSR, RQR | trung bình | ý tưởng | |
| 5 | Không hỏi lại mã sản phẩm khách đã chọn | thấy trong log 24/10 | prompt | RQR | trung bình | ý tưởng | |
| 6 | Giảm TTFT p95 dưới 3 s | p95 3779 ms (42 lượt) | config / prompt ngắn hơn | latency | trung bình | ý tưởng | |
| 7 | Vòng tự cải tiến: feedback → playbook → duyệt → đo → quay lui | `components/improvement/*` còn là stub | playbook | tất cả | cao | ý tưởng | |
| 8 | QaAgent chấm rubric J01–J12 sau mỗi cuộc | `agents/qa.py` chưa gọi model | tool nội bộ | chất lượng | trung bình | ý tưởng | |
| 9 | Trang đọc tín hiệu 👍/👎 của nhân viên | tín hiệu đã ghi, chưa có nơi xem | UI | | thấp | ý tưởng | |
| 10 | Thêm entity `sku`, `order_id`, số điện thoại cho ASR | entity accuracy chưa đo các loại này | ITN / lexicon | ASR | thấp | ý tưởng | |
