# Báo cáo tiến độ dự án — 01/11/2026

## Những việc đã làm

1. **Hoàn thiện backend:** bổ sung kiểm tra quyền truy cập, chống tạo đơn trùng, xử lý lỗi API và các tình huống thao tác đồng thời. Gia cố quản lý phiên gọi, bàn giao nhân viên và xóa dữ liệu khách hàng.
2. **Cải thiện website:** hoàn thiện giỏ hàng, thanh toán, chat và giao diện nhân viên; xử lý phản hồi đến trễ khi đăng xuất hoặc đổi tài khoản; bổ sung trạng thái tải, lỗi và hỗ trợ mobile/bàn phím.
3. **Tích hợp ASR:** dùng Zipformer 30M greedy làm mặc định; giữ kiến trúc nhận dạng giọng nói cho web và công cụ đánh giá WER/CER, entity và chỉ số âm thanh. Audio, nhãn và kết quả hard-test đã được xóa theo yêu cầu; giữ model weights và dữ liệu agent.
4. **Chuẩn hóa đánh giá:** giữ nguyên bộ test/harness/scorer của main; đối chiếu cách tính RQR với đề và giải đáp BTC. Chuẩn hóa extractor v7 bằng prompt tiếng Việt, schema Pydantic và 34 slot; bổ sung sửa JSON, kiểm tra bằng chứng và xử lý output lỗi.
5. **Kiểm thử xóa Memory:** chạy kịch bản SCN-GEN-0037 trước/sau sửa. Sau sửa, cả full và baseline đều xóa 9 facts, 1 episode và 1 identity về 0. Sửa lỗi mất xác nhận xóa, báo thành công khi tool chưa thành công và dữ liệu bị ghi lại bởi tác vụ đến trễ.
6. **Popup khách quay lại:** chào theo tên và nhắc blocker còn hiệu lực từ Memory đúng tài khoản; không hiện lại dữ liệu cũ sau logout, đổi tài khoản hoặc yêu cầu xóa. Kiểm tra giao diện desktop/mobile và nội dung dài.

## Kết quả kiểm tra

- Suite backend tổng hợp: **629 passed, 15 skipped**; các test bị bỏ qua cần hạ tầng riêng, không tính là đã đạt.
- Kiểm tra PostgreSQL riêng: **14 test pass**.
- Frontend: typecheck và production build đạt; **15 unit test pass**, **15 ca Chrome trên bản cuối pass**.
- Đã khóa cohort 7 scenario, 78 lời đáp lịch sử để so extractor. RQR full 13,3%, baseline 17,6%, giảm tương đối 24,4%, **chưa đạt mục tiêu 40%**. Đây là gắn nhãn lại lời đáp cũ, chưa chứng minh agent hiện tại cải thiện.
- Không dùng riêng điểm TSR để kết luận xóa thành công: đã kiểm tra thêm trạng thái dữ liệu thực tế.

## Việc còn cần xác minh

- Chạy cohort agent hiện tại lớn hơn và duyệt nhãn semantic bằng người.
- Kiểm tra giọng nói/micro thật, tải nhiều phiên và độ trễ thực tế.
- Xác minh SLA xóa 72 giờ, worker/outbox, backup và deployment production.
- Popup kiểm tra lại thay đổi từ thiết bị khác tối đa mỗi 30 giây; chưa có push realtime.

Chi tiết và lệnh tái lập: [nghiệm thu](verification.md), [xóa Memory](evaluation/memory-erasure-verification.md), [popup](frontend/returning-customer-popup.md), [sổ chạy đánh giá](evaluation/RUN-LEDGER.md).
