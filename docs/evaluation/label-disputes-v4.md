# Nhãn v4 cần người duyệt (24/10/2026)

Tìm ra khi đọc từng cuộc trượt TSR của lần chạy `development-r2-v4` (12 case M2). Chưa sửa nhãn nào: theo `datasets/ground-truth-review/SKILL.md`, đổi nhãn phải tạo revision mới (v5) có người duyệt. Cột "bằng chứng" là file hoặc trace để đối chiếu.

| Cuộc | Vấn đề | Bằng chứng | Đề xuất (chờ duyệt) |
|---|---|---|---|
| SCN-GEN-0126 call_3, SCN-GEN-0060 call_1 và call_3 | Khách chỉ nói "giày chạy bộ size 41 màu đen"; nhãn đòi RunLite 2 (`SKU-SN-RUN2-41-DEN`, 1.690.000) nhưng cả RunLite 1 và 2 khớp. Agent hỏi "RunLite 1 hay RunLite 2 Pro?" ở lượt 1, kịch bản không trả lời, agent chọn RunLite 1. Giá 1.161.000 bị tính là sai vì nhãn mong 1.521.000. | `case-trace.json`, trace R2 | Thêm lượt khách nói rõ "RunLite 2 Pro", hoặc nới `args_match.sku` nhận cả hai SKU kèm giá tương ứng |
| SCN-GEN-0060 call_1 | `must_say_any` đòi "24/10" hoặc "ngày 24", trong khi `promotions.json` ghi RUN-10 kết thúc `2026-10-25` và `facts_established.promo_expiry` là `2026-10-25` | `evaluation-contracts/sources/btc/catalog/promotions.json` | Xác định quy ước (ngày cuối hay ngày hết), rồi sửa cụm cho khớp |
| Cùng kiểu | 12 call có `must_say_any` là một ngày lệch với `promo_expiry` của chính kịch bản (ví dụ 0010 call_2: 21/10 so với 30/10; 0026 call_2: 24/10 so với 25/10). Chưa xác định đó là lỗi hay một mốc khác. | quét tự động các `success_if.must_say_any` của v4 | Người duyệt xác định ý nghĩa của mốc ngày |
| SCN-GEN-0148 call_1 | Khách chỉ hỏi về mẫu cũ đã ngừng bán và ngân sách, không bao giờ nói đồng ý mua mẫu mới, nhưng nhãn đòi `order.create` 4.890.000 COD | `case-trace.json`, 5 lượt khách | Thêm lượt khách đồng ý mẫu thay thế, hoặc đổi kỳ vọng thành tư vấn |
| SCN-GEN-0148 call_2 | Hệ quả của dòng trên: nhãn kỳ vọng đơn `OD600001` do call_1 tạo, nhưng call_1 chưa tạo đơn | trace | Tự khỏi khi call_1 được sửa |

Không claim nào trong 8 claim bị đánh dấu sai về giá hoặc trạng thái là con số bịa: 2 claim là cách nói khác của đúng trạng thái đơn, 4 claim là giá hoặc mã đơn mà một tool của chính cuộc đó trả về (ví dụ Joie Pact 3.490.000 trong câu liệt kê hai xe đẩy; mã đơn cũ OD188213), 2 claim còn lại ("đã giao") là hệ quả dây chuyền ở SCN-GEN-0148. Xem `claim-adjudication.json` (nhóm `EQUIVALENT`, `TOOL_BACKED`, `NEEDS_REVIEW`).
