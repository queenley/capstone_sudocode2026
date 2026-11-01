# Xóa dữ liệu ASR hard-test — 01/11/2026

Phạm vi do người dùng chọn: “Xóa audio/nhãn/kết quả ASR hard-test; giữ weights Zipformer và dữ liệu agent”.

- `/Users/vqd/Downloads/SUDO_CODE_DONE/capstone_sudocode2026/data/seed/catalog/asr_hard_vi`: deleted, 166 file, 36105735 byte.
- `/Users/vqd/Downloads/SUDO_CODE_DONE/capstone_sudocode2026/evaluation/runs/20261101-asr-hard`: deleted, 903 file, 291301090 byte.
- `/Users/vqd/Downloads/asr_hard_vi`: deleted, 166 file, 36105735 byte.

Đã giữ code/harness/schema/kiến trúc ASR, model weights, pack BTC, agent datasets và ngân sách hiện có. Không xóa ledger hoặc reset cap; snapshot extractor trước sửa nằm trong namespace RQR riêng. Không còn giữ audio, nhãn hoặc báo cáo kết quả của hard-test đã xóa trong ba thư mục trên.

Đã xóa thêm 31 log/script tạm do luồng ASR hard-test này tạo trong `/private/tmp` (878367 byte), gồm logs kết quả và script chứa vocabulary/đề xuất nhãn. Chỉ dùng danh sách tên chính xác đã tạo, không quét/xóa log ASR của công việc khác.
