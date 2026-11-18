# Báo cáo vòng Reflection `reflection-2` (17–18/11/2026)

## Tóm tắt

- Vòng Reflection học lại từ lỗi của agent trên 44 kịch bản và đề xuất 3 dòng skill mới cho skill `conversation`. Các dòng này được publish thành **skills v1**.
- Kết luận: **v1 không làm agent tốt hơn v0, nên không áp vào agent.**
  - Trên 7 kịch bản frozen, TSR giữ nguyên 80%, còn CCR và độ bịa giá đều xấu đi.
  - Trên các kịch bản trùng với run v0 cùng ngày, TSR giảm 4–7 điểm.
- Agent hiện vẫn ở v0. Skill đã học chỉ được cất ở `evaluation/runs/reflection-2/learned/`.

## Cách chạy

| Bước | Nội dung |
|---|---|
| Tập kịch bản | `data/.build/rounds/reflection-2`: 40 kịch bản học và 20 frozen lấy từ `data/dev`, seed 1, 50% kịch bản khó (adv-share 0.5) |
| Học (learn) | Chạy agent v0 trên 40 kịch bản dev và 4 kịch bản budget, rồi gom lỗi |
| Chẩn đoán | QaAgent chấm từng lỗi, ReflectionAgent viết thẻ bài học, gom cụm theo khách (mỗi cụm cần ít nhất 3 khách) |
| Duyệt | PolicyAgent và ApprovalAgent. Vòng này được duyệt tự động bằng `--approved --scripted`, **chưa có người duyệt** |
| Đo R0/R1 | So v0 và v1 trên 7 kịch bản frozen, mỗi bên 1 lần (chạy ít để tiết kiệm) |
| Full | Chạy v1 trên toàn bộ `data/dev` (409 kịch bản), cấu hình `full`. **Dừng ở 190/409** để tiết kiệm |

- Agent: `openai/gpt-5.6-luna`.
- Extractor: `product-extractor-v13`.
- Chấm điểm: `reference_eval.py` của BTC.

## Kết quả bước học

- Có 169 lỗi: 151 lỗi sản phẩm, 16 lỗi hành vi, 2 lỗi review.
- Phân loại chẩn đoán:
  - agent không theo skill đã có: 51
  - loại trừ: 14
  - thiếu skill: 12
  - không phải lỗi do skill: 5
  - chưa kết luận được: 3
- Từ đó ra 66 thẻ bài học, gom thành **3 đề xuất**, cả 3 đều vào skill `conversation`:

| # | Dòng skill đề xuất | Số khách |
|---|---|---|
| 1 | Khi khách chốt mua và đã chọn biến thể hoặc cách thanh toán, dùng lựa chọn đã biết, chỉ hỏi thông tin còn thiếu, và đưa lựa chọn đó vào lần đọc lại đơn trước khi tạo | 18 |
| 2 | Khi khách muốn mua nhưng chưa nói rõ món, dùng thông tin đã tư vấn làm ngữ cảnh rồi hỏi khách muốn mua món nào, không tự coi món đã tư vấn là món khách chọn | 3 |
| 3 | Khi khách đã tự xưng bằng danh xưng cụ thể, không gọi chung là "anh/chị" ở các lượt sau | 3 |

## Đo R0/R1 trên 7 kịch bản frozen

- Các kịch bản: SCN-ADV-0073, SCN-ADV-0087, SCN-GEN-0115, SCN-GEN-0156, SCN-ADV-0041 (đối chứng), SCN-BGT-F01, SCN-BGT-F02.
- Mỗi bên chạy 1 lần.

| Chỉ số | v0 (R0) | v1 (R1) |
|---|---|---|
| TSR | 80.0 | 80.0 |
| RQR | 0.0 | 0.0 |
| CCR | 52.4 | 42.9 |
| HR giá | 10.5 | 14.3 |

- **Sửa được 1 lỗi:** SCN-ADV-0073 call_2, sai thông tin khuyến mãi.
- **Làm hỏng 4 lỗi:**
  - SCN-ADV-0073 call_1 và call_2: sai tổng tiền.
  - SCN-GEN-0115 call_1: quên người quyết định và khu vực giao hàng.

## Chạy full `data/dev` với v1 (dừng ở 190/409)

| Bộ so sánh | v0 TSR | v1 TSR |
|---|---|---|
| 190 kịch bản đã chạy | — | **71.1** (135/190); kịch bản khó 66.7 |
| 15 kịch bản trùng với run v0 `20261117-judge/dev` | 73.3 | 66.7 |
| 24 kịch bản trùng với tập học | 70.8 | 66.7 |

- v0 là run cùng ngày, cùng code.
- Tập 24 kịch bản là các kịch bản agent đã học từ chính chúng, nên v1 lẽ ra phải có lợi thế ở đây.

Các lượt đổi kết quả:
- **Bị làm hỏng:**
  - SCN-ADV-0009 call_1: thiếu câu báo hết hạn bảo hành.
  - SCN-ADV-0010 call_2: không gọi đúng `order.update`.
  - SCN-ADV-0053 call_1: không gọi đúng `schedule.callback`.
  - SCN-ADV-0053 call_2: không gọi đúng `order.create`.
- **Được sửa:** SCN-ADV-0131 call_2: gọi đúng `order.create`.

Lỗi bị làm hỏng phần lớn ở bước tạo hoặc sửa đơn. Đây đúng là chỗ đề xuất 1 ("dùng lựa chọn đã biết khi chốt đơn") tác động.

## Giới hạn

- Mẫu nhỏ, mỗi bên chỉ chạy 1 lần, nên số liệu còn nhiễu. Tuy vậy, cả ba phép so sánh đều cho thấy v1 không tốt hơn v0.
- Run full bị dừng trước bước trích nhãn, nên **v1 chỉ có TSR**; RQR, CCR và HR không dùng được. Muốn có đủ thì phải chạy `run_eval.py --relabel` trên trace, bước này tốn thêm tiền gọi extractor.
- Việc duyệt skill là tự động (`scripted-eval`), chưa có người xem.
- Không có run v0 trên toàn bộ 409 kịch bản `data/dev` cùng code, nên không so được trên cả tập.

## File liên quan

- `evaluation/runs/reflection-2/measure.log`: log của bước học, duyệt và R0/R1.
- `evaluation/runs/reflection-2/learned/`: skills v1 đã học.
- `evaluation/runs/reflection-2/full-dev/report.partial-190.json`: báo cáo BTC trên 190 kịch bản.
- `docs/plan/IMPROVEMENT-LOG.md`: mục ngày 2026-11-18.
