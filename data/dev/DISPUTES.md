# Nhãn còn tranh chấp của `data/dev`

Chưa có người duyệt: mọi thay đổi trong [`conversion-report.json`](conversion-report.json) đều `decision: pending`, `official_gt_approved: false`. Nhãn của bộ này vẫn là chẩn đoán.

## Cần người quyết định

| Cuộc | Vấn đề | Đề xuất |
|---|---|---|
| SCN-ADV-0028/call_1 | Nhãn đòi `order.create`, câu khách cuối: "Chị cần suy nghĩ thêm một chút trước khi chốt đơn." Giữ nguyên, agent làm đúng sẽ trượt | Đổi sang `hen_goi_lai`, `tool_called: null` |
| SCN-ADV-0023/call_1 | Nhãn đòi `order.create`, câu khách cuối: "Chị chờ cuối tháng này nhận lương rồi thanh toán qua ngân hàng nhé." Chưa rõ đặt trước hay chưa quyết | Người duyệt đọc lại ý đồ kịch bản |
| 34 cuộc `J02_no_fabrication` | Hội thoại mẫu nói điều không có nguồn, `must_say_any` rút từ đó có thể sai. Chưa rà cuộc nào (danh sách ở `review/needs_manual_review.csv`) | Duyệt trước các nhãn khác |
| SCN-GEN-0133/call_2 | Hội thoại mẫu không gọi `order.create` khớp `args_match` | Đọc lại nhãn |
| SCN-GEN-0092/call_3, 0126/call_3, 0192/call_3, 0210/call_3 | Hội thoại mẫu hỏi quá `max_agent_questions` (có từ `seed-dev`) | Sửa hội thoại mẫu hoặc nới giới hạn, có lý do |

## Đề xuất đã áp dụng, chờ duyệt

- **Câu xác nhận thêm tay.** 42 cuộc đòi `order.create` nhưng khách không xác nhận sau câu đọc lại được thêm "Đúng rồi em, lên đơn giúp … nhé." ở cuối, hoặc trước câu chào/cảm ơn cuối. Người duyệt có thể thấy một số cuộc nên đổi nhãn thay vì thêm lời.
- **SCN-GEN-0224/call_2** dời từ Chủ nhật 29/11 sang thứ Hai 30/11 vì LN-01 không xử lý đổi trả Chủ nhật.
- **SCN-ADV-0151..0154** là bốn ca hẹn gọi lại mới: 01/01, Chủ nhật ngoài giờ, ngoài giờ ngày thường, 11/11. Ca 0152, 0153: `args_match` là khung đề xuất gần nhất (`clock.nearest_working_time`), giả định khách đồng ý.

## Biết nhưng để nguyên

- **`say_at_most`** (SCN-ADV-0031, 0060, 0126, call_1): `reference_eval.py` không đọc khoá này, nên chỉ `validate_rules` của đội kiểm. `forbidden_claims` cùng cuộc đã phủ phần lớn ý.
- **Mock BTC và 11/11:** `mock_tools.schedule_callback` không biết giờ mở 07:00–23:00, sẽ dời 22:00 về 08:00. MCP server của agent giữ nguyên giờ trong trường hợp này (`crm.schedule_callback`); pack BTC không sửa. Ca SCN-ADV-0154 chỉ đúng với agent đi qua wrapper đó.
- **Luật Chủ nhật** chưa có guard: mock và agent đều không chặn đổi trả Chủ nhật; r3 chỉ tránh ca đó trong dữ liệu.
- **`must_say_any` chỉ có số** (143 cuộc): không sai, agent đọc số bằng chữ sẽ trượt.
- **`asr_test/`** chép nguyên từ `seed-dev-r2`. Các cuộc r2 chưa từng có audio vẫn không có.
- **`judgments/`, `review/`, `reports/simulation_replays.jsonl`** vẫn của r2, chưa chạy lại vì cần model. Bốn ca mới chưa có hội thoại mẫu.
