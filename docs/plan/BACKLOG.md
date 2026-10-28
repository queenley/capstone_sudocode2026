# Backlog cải tiến

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
