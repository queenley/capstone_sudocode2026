# Tối ưu ASR ngày 03/10/2026

## Bổ sung M1 v4 — chưa benchmark PhoWhisper

- Lưu việc FPT Voice Maker chuyển hướng về AI Factory và chưa xác minh quota tại [PENDING_TTS.md](PENDING_TTS.md); không phát sinh request TTS có phí.
- Chuẩn bị catalog-v3 bằng chế độ scripts-only: 4 dev, 20 eval, 12 khách giả lập, không trùng khách giữa split; 4/20 eval được thiết kế có nhiễu. Đây là **phân bố script**, chưa phải 20 audio đã sinh.
- ITN v3 tách số tiền chữ số chính xác khỏi quy ước nói tắt, thêm callback date có ngữ cảnh ngày gọi. Ngày là supplemental metric; BTC scorer/schema nguồn giữ nguyên.
- Preflight siết entity scalar, ngày metadata, supplemental GT, audio thừa và số lượng dialogue khai báo. Human-review complete chỉ true khi cả dataset và từng dialogue đều được đánh dấu human_verified; chưa có bước nhập phiếu duyệt tự động.
- Timing báo raw/effective/warm-up count; mặc định bỏ 3 mẫu đầu khỏi timing, không bỏ khỏi quality. Giới hạn: thời gian elapsed gồm nhận dạng và post-processing trong vòng call, không phải phép đo streaming hay TTFA.
- 13 kiểm thử local đạt; contract checker đạt 5 schema, 48 valid/14 invalid, 15 semantic mutations, 86 BTC compatibility records và 46 source hashes. ResourceWarning đến từ cách BTC mở file; giữ nguyên nguồn BTC.
- Chấm lại transcript cũ: dev WER 6,3%, CER 5,0%; eval WER 6,1%, CER 4,6%. Replay không đo ASR speed, không dùng chọn PhoWhisper và không có bằng chứng cải thiện model.

Chưa hoàn tất: tạo/nghe audio catalog-v3, xác minh giọng vùng miền, chạy PhoWhisper-small/medium trên dev rồi eval khóa cấu hình. M2 và tích hợp Agent ngoài phạm vi vòng này. Các mục bên dưới ghi lịch sử trước thay đổi code/normalizer; lock lịch sử không còn áp dụng code hiện tại.

## Quyết định trên dev

Mọi thử nghiệm nhận dạng chỉ dùng 4 audio dev. Dữ liệu vẫn mang `pending_human_listening`; chưa sửa audio/GT dựa theo đáp án của model.

| Cấu hình | WER (%) | CER (%) | SĐT đúng / 4 | Quyết định |
|---|---:|---:|---:|---|
| Baseline whole-audio | 6,3 | 5,0 | 0 | Giữ mặc định |
| VAD, nhận từng đoạn riêng | 16,4 | 12,0 | 0 | Không chọn; file nhiễu phát sinh lời thừa |
| VAD + prompt tiếng Việt chung | 14,1 | 10,5 | 0 | Không chọn |
| Whole-audio + nhận lại đoạn SĐT | 6,3 | 5,0 | 0 | Không chọn; tăng thời gian, không tăng accuracy |

Các báo cáo cuối: [baseline](runs/dev-v3-locked/report.json), [VAD chấm lại cùng extractor](runs/dev-v3-vad-regraded/report.json), [VAD + prompt chấm lại](runs/dev-v3-vad-prompt-regraded/report.json), [phone retry](runs/dev-v3-phone-refine/report.json). File replay chỉ chấm lại transcript từ run nhận dạng; không được dùng timing replay như thời gian ASR. Các run thử ban đầu và run `*-replay` cũ được giữ làm lịch sử; không dùng chúng làm bản bàn giao.

Baseline được chọn trước khi chạy `eval-v3-locked`. `config.lock.json` ghim hash model/scorer/code, phiên bản runtime và các tham số; runner từ chối cấu hình lệch lock. Source code của các thử nghiệm đầu có hash khác bản cuối; baseline cuối đã được chạy lại bằng code khóa.

## Những lỗi đã sửa

- Đọc JSON từ chối key trùng và NaN/Infinity; preflight từ chối dataset rỗng, ID trùng/không an toàn, reference rỗng và entity dictionary sai kiểu.
- Kiểm WAV PCM16 mono 16 kHz, thời lượng dương và đủ payload. Audio thiếu/hỏng được ghi theo ID.
- Hypothesis validate bằng `$defs/AsrHypotheses` của bộ contract; malformed/text rỗng được loại khỏi scoring view và ghi thiếu coverage. Bản replay gốc giữ trong `submitted_hypotheses.json`.
- Unknown ID không lẫn vào scorer; coverage có `COMPLETE/INCOMPLETE`. Accuracy bổ sung dùng toàn bộ entity GT, hypothesis thiếu vẫn nằm trong mẫu số.
- ITN tiền hỗ trợ số bằng chữ, số có dấu ngăn cách, ngân sách và nhiều lượt báo giá; phát ngôn “đây là giá minh họa” không xóa giá đã nhận. Khoảng giá không bị đoán thành một mức giá.
- Dãy SĐT thiếu/thừa không được cắt hoặc thêm số. Chẩn đoán tách lỗi input/schema, extractor không hỗ trợ và lỗi ASR/GT cần nghe xác nhận.
- Generator không ghi đè GT đã duyệt hoặc tái sử dụng audio cũ khi script thay đổi.
- Scorer BTC nguyên bản và 46 file nguồn qua kiểm hash; import không sinh cache trong snapshot.

## Bằng chứng và phần còn lại

### Kết quả cuối trên 20 audio eval hiện có

Report: [eval-v3-locked](runs/eval-v3-locked/report.json). Đủ 20/20, WER 6,1%, CER 4,6%, tiền 100%, SĐT 5%; tương đương điểm bản cũ. ASR đo được 12,11 giây/phút audio ở lượt này; biến động thời gian máy không được coi là bằng chứng thuật toán nhanh hơn. [Bảng trước–sau](runs/comparison-v3/comparison.md) kiểm cùng hash audio và GT. Lock dev/eval trùng nội dung; scorer BTC cùng hash bản gốc.

Một lỗi cụ thể đã sửa: TEAM-EVAL-19 có ASR text `09000001009` (11 chữ số). Extractor cũ cắt thành `0900000100` và trả như một SĐT hợp lệ. Bản mới giữ nguyên transcript, bỏ entity đó và lưu `INVALID_PHONE_LENGTH`. Đây là sửa tính đúng của pipeline; không biến kết quả thành một số khớp đáp án.

Kiểm thử: 8 ca tự động gồm tiền/phone, key trùng/NaN, audio thiếu/cắt cụt, schema/ID/coverage và CLI chứng minh WER=0 vẫn phải INCOMPLETE nếu không có audio. Bộ contract kiểm 46 source hash vẫn đạt. Trang nghe kiểm đủ 24 audio và cú pháp JavaScript; trạng thái nghe duyệt vẫn pending.

Trang [nghe duyệt](datasets/synthetic-v1/listen.html) phát toàn bộ audio và riêng đoạn SĐT, kèm transcript script và phiếu JSON xác nhận/hash. Timing nhãn TTS chỉ dùng cho UI nghe; nhận dạng, VAD và phone retry không đọc nhãn này.

Cấu hình mới chưa giải quyết dãy số điện thoại nhiều số 0. Các retry trên dev cho ra 11 chữ số nên bị từ chối, giữ bản ASR ban đầu. Không tự thêm hai số 0 để khớp đáp án. Cần người nghe xác nhận audio thật sự chứa 10 chữ số; nếu TTS đọc thiếu thì tạo phiên bản dataset mới, nếu audio đúng thì tiếp tục nghiên cứu model trên dev.

Bộ eval TTS này đã được xem lỗi ở vòng trước, nên chỉ là regression set cho hiện tại; không tuyên bố test mù độc lập. 12 audio BTC chưa nhận vẫn chưa có số đo. Entity date/SKU/area, số tiền thập phân và số quốc tế là phần chưa triển khai trong extractor hiện tại.

VAD sử dụng API sẵn có của [faster-whisper](https://github.com/SYSTRAN/faster-whisper); thông số cụ thể được lưu trong manifest, không lấy từ nhãn TTS.
