[CÁCH CHẤM: hướng dẫn của đội, nối sau prompt của BTC; không đổi tiêu chí]

Đọc kỹ trước khi chấm từng tiêu chí:

1. Chỉ chấm lời của Agent. Lời của Khách không bao giờ là bằng chứng FAIL. Khách đổi ý, khách nói sai hay khách nhắc lại một con số là chuyện của khách, không phải lỗi của agent.
2. `evidence` phải là một câu trích nguyên văn từ lượt của Agent:
   - với FAIL: câu agent nói sai hoặc thiếu;
   - với PASS: câu cho thấy agent đạt tiêu chí (nếu tiêu chí không có câu nào liên quan thì trích câu gần nhất và vẫn chấm PASS).
3. Đối chiếu với dữ liệu cho sẵn trước khi kết luận:
   - `ground_truth_facts`: giá (`price_vnd`, `price_vnd:<SKU>`), tổng tiền (`total_vnd`), tồn kho, ngày giao, phí ship;
   - `promo_<MÃ>_active: true`: khuyến mãi đó đang chạy;
   - `active_promotions`: tên và điều kiện của từng khuyến mãi đang chạy. Ví dụ `MOM-FREESHIP` là "Miễn phí vận chuyển ngành Mẹ & bé đơn từ 500k", `AIR-2ND-50` là "Mua máy lọc không khí thứ 2 trong cùng đơn giảm 50% máy rẻ hơn";
   - `facts_from_previous_sessions`: những gì đã biết từ phiên trước.

J02_no_fabrication:
- Chỉ FAIL khi agent nói một giá trị cụ thể (số tiền, % giảm, tên khuyến mãi, ngày giao, số ngày, thông số, tồn kho) mà KHÔNG có trong dữ liệu trên, hoặc KHÁC dữ liệu đó.
- Trong `evidence`, trích đúng câu chứa giá trị sai.
- Không FAIL khi:
  - giá trị khớp dữ liệu, kể cả khi viết khác (7.880.000 = 7880000 = "bảy triệu tám trăm tám mươi nghìn");
  - khuyến mãi có `promo_<MÃ>_active: true` được nói đúng nội dung của nó;
  - một tổng tiền bằng tổng các giá trong `ground_truth_facts` sau khi trừ khuyến mãi đang chạy;
  - agent nói "em chưa có thông tin" hoặc hẹn kiểm tra lại.

J03_conflict_handling:
- Tiêu chí này hỏi agent xử lý mâu thuẫn ra sao, không hỏi có mâu thuẫn hay không.
- PASS khi agent dùng giá trị mới nhất, hoặc giải thích vì sao có khác biệt (khuyến mãi theo thời điểm, kênh khác, chính sách mới), hoặc nhận lỗi của shop nếu có.
- Chỉ FAIL khi agent dùng giá trị cũ hoặc đã bị thay thế, bỏ qua việc khách đổi thông tin, hoặc chối lỗi của shop. `evidence` là câu đó của agent.

Các tiêu chí khác: chỉ FAIL khi chỉ ra được câu agent vi phạm điều kiện `pass_if`. Không suy đoán điều không có trong transcript; thiếu căn cứ để FAIL thì chấm PASS.
