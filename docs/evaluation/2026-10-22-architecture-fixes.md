# Revision kiến trúc sau yêu cầu sửa toàn diện — 22/10/2026

Base main `1e738ba1`, working tree chưa commit. Đây là revision sau [các sửa từ log ban đầu](2026-10-22-log-fixes.md). Không có model run mới, không đổi GT/BTC scorer, không sửa/re-score run đã đóng. Holdout đã dùng để debug, nên cần cohort độc lập mới cho lần đo sau.

## 1. Sự kiện nghiệp vụ trước, slot phẳng sau

Log thực xác nhận dữ liệu đã bị ghép khác sản phẩm: R0 full 0034/call_1 lưu SKU-AP-Y với giá/KM của SKU-XM-4P; R1 full 0083/call_2 lưu SKU-AP-FLT-P với giá SKU-AP-PRO. Các lượt full 0006, 0033, 0040, 0046 ở holdout cũng có ghép sai SKU/biến thể/giá. Đây là một nguyên nhân chung, không phải mỗi cảnh báo là một bug riêng.

Trước đây `from_tools` chọn product riêng rồi lấy giá/biến thể/KM cuối cùng của cả call. Nay chọn một frame sản phẩm nhất quán rồi mới chiếu sang các slot BTC. Nếu có order, dùng sản phẩm của order cuối; nếu có exchange mới hơn, dùng frame exchange; không có giao dịch thì giữ sản phẩm được quote đầu tiên. Giá lấy từ quote đúng SKU/variant và không lấy quote xuất hiện sau order để sửa giá của order đã tạo. Quy tắc này không đọc GT.

- Thêm `quoted_sku` để ràng buộc giá lịch sử với sản phẩm. Dữ liệu cũ chưa có liên kết không được khẳng định là giá cũ của món đang nói; cảnh báo và tra giá hiện tại. Không tự suy hoặc sửa giá cũ từ catalog hôm nay.
- Quote không còn KM thì invalidate các slot KM cũ, giữ lịch sử. Đổi sản phẩm không giữ variant của món cũ.
- Thêm `order_ids` để giữ toàn bộ đơn của giỏ và hợp nhất qua nhiều call. Slot scalar `order_id` vẫn giữ tương thích. Recall lấy các ID đã ghi ngay cả khi CRM seed không liệt kê đơn mới; refresh chỉ các ID có nguồn của khách, không gom đơn của cả hộ gia đình.
- Hợp nhất danh sách đơn lại trong transaction dưới customer lock, tránh hai writer ghi đè nhau. Dùng JSONB hiện có, không đổi schema DB.

Audit offline trên tool log R0/R1/holdout kiểm **78 snapshot**, đánh dấu **8 lần ghi cũ có cặp product/price không khớp quote**. Tám lần này gồm cả R0/R1 của cùng case, không phải tám bug hoặc tám scenario mới. Chiếu lại bằng code mới cho ra snapshot có quote đúng sản phẩm. Đây là kiểm phép biến đổi dữ liệu, không phải model rerun hay điểm metrics mới. Evidence local: `architecture-offline-audit.json`.

## 2. Identity và quyền ghi memory

Các lỗi sau được xác nhận bằng fixture/code hiện tại; log cũ không đủ chứng minh đã có lộ dữ liệu thật:

- Chỉ identity `confirmed` từ ledger được dùng làm match; `provisional` không tự thành VERIFIED ở lần gọi sau.
- Giữ provenance key → customer. Một key từ lời nói không được hưởng độ tin cậy của một connection key khác chưa match; khi hang-up chỉ xác nhận các key đã match đúng customer.
- SĐT nhắc thêm sau khi đã xác minh không tự gắn vào người đang nói. Khách mới ưu tiên connection key, không gắn mọi số trong call vào cùng hồ sơ.
- Bỏ việc cho MemoryAgent tự nâng identity ở cuối cuộc. Chưa xác nhận trong identity flow thì không ghi vào hồ sơ đó. Đã xóa model/prompt `same_person` khỏi đường này.
- Hỗ trợ họ tên nhiều từ trong câu tự giới thiệu, giữ ranh giới từ; nhắc tên người khác hoặc nói gọi hộ không được coi là tự nhận danh tính. Từ chối identity thì xóa phone/quote cũ khỏi khả năng write.
- Candidate phải qua quality/type/range trước khi chọn giá trị thắng. Candidate muộn nhưng confidence thấp không xóa candidate tốt; preference của khách thắng gợi ý của agent; business record từ tool thắng suy diễn. Model observation phải chỉ đúng turn/speaker, kể cả lời nhân viên trong copilot.

Đây vẫn là chính sách nhận diện bằng connection key/xác nhận hội thoại của repo, không phải cơ chế OTP mới. Không sửa hàng loạt các liên kết identity đã lưu; dữ liệu có sẵn cần audit riêng khi có evidence.

## 3. Tool boundary và dữ liệu riêng

- Bổ sung guard cho `order_status`/CRM: VERIFIED mới được đọc dữ liệu riêng; mã đơn phải nằm trong scope đã xác minh. Số dùng chung không được enumerate toàn bộ đơn. CRM chỉ đưa profile đã xác minh vào model, không đưa cả danh sách người chung SĐT.
- Context thiếu thì guarded tool bị chặn. Copilot vẫn không tự write; write không tự retry khi kết quả chưa rõ.
- Tool handler nhận input thô cần cho nghiệp vụ; kết quả và args trả vào model/checkpoint được tokenize bằng vault của call. Địa chỉ từ kết quả tool phải được dùng qua token rõ ràng, không tự thay default khách đã cung cấp trong context.
- Brief từ CRM/memory cũng được mask trước checkpoint. JSON tokenize/detokenize đi qua từng value, giữ đúng dấu nháy/Unicode; cập nhật cả runtime, root runner và adapter harness. Raw values chỉ được phục hồi ở boundary output vốn được phép, giữ contract trace cũ.
- Yêu cầu xóa dữ liệu đã xác nhận đi thẳng vào deletion, không phụ thuộc việc extraction model có trả lời được hay không.

Không có tuyên bố đã làm sạch checkpoint/log cũ. Các artifact có PII vẫn ở local và bị gitignore. Khôi phục địa chỉ thuộc vault của call cũ chưa được chứng minh end-to-end; không coi một token trùng tên ở call hiện tại là bằng chứng đã khôi phục đúng địa chỉ cũ.

## 4. Streaming, context và bằng chứng dùng memory

Test xuyên suốt cold memory → recall → hot graph thật → guard → native/runtime trace phát hiện citation `[B…]` đến sau câu đã phát bị chấm như câu rỗng, bật safe line. Nay citation riêng được gắn như metadata vào câu đã phát. Citation của câu bị bỏ vì vượt giới hạn không được cộng credit. Đây là lỗi tái hiện offline, chưa chứng minh nó giải thích toàn bộ CCR thấp trong run cũ.

Native runner và runtime export dùng chung phép phân giải citation → fact ID → slot. Runtime lưu các slot đã dùng theo từng turn, tránh brief cập nhật cuối call làm đổi provenance của lượt trước. Bỏ credit do trùng substring như `size=42` xuất hiện trong `1.420.000đ`. Tool bị chặn/không có result không được xuất như đã executed. Đây là thay đổi đo/export; không lấy nó để sửa hoặc làm đẹp điểm run cũ.

Repair context không còn cắt JSON tool ở ký tự 800, làm mất SKU/variant cuối payload. Brief, lane, kết quả tool đã chạy và lý do bị chặn là context bắt buộc; budget 3.000 token ước tính là mục tiêu mềm cho phần tùy chọn. Prompt có thể dài hơn; API budget cap vẫn giữ nguyên. Chưa đo latency/cost thực của revision này.

## 5. Kiểm chứng và trạng thái

- **184 backend tests + 24 harness tests PASS**, gồm fixture an toàn và test chạy graph/ReAct thật với model/tool giả; không API model.
- PostgreSQL thật `app_db_eval`: PASS cho union order khi ghi đồng thời, replay idempotent, customer isolation, invalidation KM. Chỉ tạo schema ngẫu nhiên riêng và đã drop sau test; không reset schema/bảng hiện hữu. Evidence: `postgres-integrity-check.json`.
- Audit từ log: 78 snapshot như trên; source lock và kiểm bất biến lưu trong `architecture-fix-verification.json`.
- Budget ledger không đổi; không chạy lại 10 case lịch sử, không có thêm lượt model hoặc holdout.

**Metrics sau sửa: INCOMPLETE.** Chưa chứng minh TSR/CCR/HR tăng với model thật. Nhãn vẫn diagnostic, QA judge của repo còn stub, không đánh giá audio/UI/Windows ở revision này. Cần review diff và đo trên cohort development/holdout mới với instrument được khóa và ngân sách hợp lệ. Không tiếp tục dùng holdout vừa debug như tập kiểm độc lập.

Triển khai cần kết thúc các call đang chạy trước khi đổi phiên bản: idempotency key, metadata identity/vault và provenance của call cũ không nên trộn với revision mới. Chưa deploy hoặc sửa dữ liệu production.
