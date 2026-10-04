# Flow Evaluation theo vai trò — bản nháp Archify

Mở `evaluation-draft.html` bằng trình duyệt; file chứa nội dung để xem offline. Giao diện Archify dùng tiếng Anh, nội dung sơ đồ dùng tiếng Việt.

Nguồn thiết kế: `../../evaluation-flow.md`, `../../source/flow_bach.excalidraw`, `../../exemplar-bank-design.md`, `../../reflection-ab-design.md`. Công cụ: https://github.com/tt-a1i/archify.

## Cách đọc

- Consultant: 6a trả lời → Source Gate → 6b FAQ nháp → 6c candidate và test; không lưu live ngay.
- After-call: 8 thu evidence → 9 MemoryAgent → ledger riêng của khách; đồng thời chuyển trace sang QaAgent.
- QaAgent: 10 chấm và ghi lesson/no-change → Source Gate → 11 pool → 12 đủ bằng chứng → 13 tổng hợp thành playbook nháp. Chưa đủ thì chờ hoặc review.
- Exemplar: lấy ví dụ chốt đơn đã xác minh từ pool, bỏ PII và gắn tình huống, tạo candidate.
- Mọi candidate → 14 người duyệt → 15 runner và scoring → Evaluation Gate → 16 active. Chưa duyệt, FAIL hoặc thiếu bằng chứng thì giữ candidate.
- M2 A/B: duyệt protocol, chạy offline hai biến thể với state riêng, đề xuất winner quay về 14; không đưa kết quả thử nghiệm thẳng lên active.

## Trạng thái kiểm tra

Đã render ở mức `standard`. Kiểm tra bố cục `showcase` chưa đạt vì một số đường nối chồng hoặc giao nhau; chưa có kiểm chứng trình duyệt và chưa kiểm tra hình bằng mắt. Đây là bản nháp, không phải bản đã nghiệm thu; không thay sơ đồ chính hoặc bản Excalidraw gốc.

Nguồn JSON giữ profile `showcase` để tiếp tục sửa và kiểm tra, không hạ tiêu chuẩn nghiệm thu. Có thể tái tạo nháp bằng `archify render workflow evaluation.workflow.json evaluation-draft.html --quality standard`.
