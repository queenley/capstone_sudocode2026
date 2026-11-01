# Tài liệu evaluation

| File | Nội dung |
|---|---|
| [scoring-flow.md](scoring-flow.md) | Một con số RQR, CCR, TSR, HR đến từ đâu: luồng từ kịch bản tới bảng BTC, extractor, bảng "chỉ số nào đọc trường nào" |
| [system-map.md](system-map.md) | Bản đồ hệ thống để làm tiếp: đường chạy sản phẩm, lệnh đã kiểm, giới hạn phải nhớ |
| [rqr-btc-interpretation.md](rqr-btc-interpretation.md) | Đối chiếu đề, điều chỉnh/giải đáp BTC và thuật toán main; công thức RQR, mẫu số, ngoại lệ và điểm chưa rõ |
| [question-classification-contract.md](question-classification-contract.md) | Phân loại open/confirm theo ý nghĩa; 34 slot, giới hạn ngữ cảnh và các ca diagnostic |
| [extractor-implementation.json](extractor-implementation.json) | Version/hash schema, prompt, helper và kết quả kiểm tra triển khai extractor |
| [RUN-LEDGER.md](RUN-LEDGER.md) | Cohort cố định, phép relabel cùng replies, bằng chứng, kết quả và ngân sách từng attempt |
| [asr-local.md](asr-local.md) | Kiến trúc ASR, Zipformer greedy mặc định, WER/CER, entity và phép đo âm thanh |
| [neural-denoiser-comparison.md](neural-denoiser-comparison.md) | RNNoise tùy chọn, so bật/tắt Zipformer trên 148 clip và hai montage; WER/CER/entity diagnostic/latency |
| [memory-erasure-verification.md](memory-erasure-verification.md) | Smoke `xoa_du_lieu` trước/sau sửa, dữ liệu Memory thực tế, checkpoint/replay và giới hạn của điểm TSR |

Cửa vào của cả phần evaluation (lệnh chạy, quy tắc, bố cục thư mục): [`evaluation/README.md`](../../evaluation/README.md). Chương đánh giá của tài liệu AI: [`docs/ai/05-danh-gia.md`](../ai/05-danh-gia.md).
