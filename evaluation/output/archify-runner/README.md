# Evaluation Harness — Archify

Mở `evaluation-harness.html` bằng trình duyệt. Đây là kiến trúc quanh Evaluation Runner, không phải pipeline cải tiến FAQ/phát hành.

Mở `assertion-judge.html` để xem nhánh chấm chi tiết: input → validator → mode router → supplemental assertion hoặc criterion selector/LLM-judge → combiner → report. Chấm BTC đi nhánh độc lập trong mọi mode áp dụng. File nguồn là `assertion-judge.architecture.json`, receipt là `assertion-judge.finalize-summary.json`. Validate/deliver/check PASS; browser check lỗi khởi động Chrome, chưa review trực quan.

Ba nhánh: hội thoại ON/OFF ở giữa; ASR bên trái; M2 bên phải. Ground truth chỉ đi tới bộ chấm, không đưa đáp án vào Agent. Mọi kết quả hội tụ ở report aggregator, bảng A.6 và kiểm ngưỡng. Nhánh không dùng judge đi trực tiếp tới aggregator; judge/supplemental giữ riêng điểm BTC.

Nguồn JSON: `evaluation-harness.architecture.json`. Nội dung căn cứ `../../evaluation-runner-flow.md`, `../../evaluation-flow.md`, file Evaluation_QD (1).md và folder BTC.

## Kiểm chứng

- Archify showcase validate: PASS.
- Delivery và strict artifact check: PASS.
- Browser check: FAIL do Chrome DevTools pipe kết thúc trước khi đo; không tuyên bố trình duyệt hoặc review bằng mắt đã đạt.
- Receipt cuối: `review-2/evaluation-harness.finalize-summary.json`; HTML hash được ghi trong receipt.

File SVG là bản trích thử từ HTML, chưa nghiệm thu export; không dùng thay bản HTML. Không sửa data BTC hay flow Excalidraw gốc.
