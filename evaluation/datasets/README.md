# Datasets của evaluation

Một bộ kịch bản đã gán nhãn, định dạng của BTC (`apps/ai-agent-service/data/btc/schemas/scenario_format.md`), đủ để chạy bằng lệnh đánh giá duy nhất của repo.

| Thư mục | Là gì |
|---|---|
| `create-data-diagnostic-v4/` | 150 kịch bản đã sinh bằng `evaluation/data-generation`, đã sửa nhãn thanh toán (`chuyen_khoan` → `bank`). `scenarios/` (1 file mỗi kịch bản), `tool-labels.json` (tool kỳ vọng từng cuộc), `conversion-report.json` (nguồn, hash, trường đã đổi), `DISPUTES.md` (nhãn cần người duyệt) |
| `ground-truth-review/` | Quy tắc duyệt và sửa nhãn (`SKILL.md`): đọc trước khi thêm hoặc sửa kịch bản |

Trạng thái: **diagnostic**. `conversion-report.json` ghi `official_gt_approved: false`, tức nhãn do bộ sinh gán và chưa có người duyệt độc lập. Mọi điểm đo trên bộ này là điểm chẩn đoán, không phải điểm chính thức.

## Chạy thử

```bash
# lập kế hoạch + chạy 1 kịch bản (tốn phí model; extractor tắt)
apps/ai-agent-service/.venv/bin/python run_eval.py --scenarios evaluation/datasets/create-data-diagnostic-v4/scenarios --only SCN-GEN-0051 --no-extract --out evaluation/runs/<tên-lần-chạy>
```

Các kịch bản hiếm chuyên biệt (`hard_case`) và khách tổng hợp `SYN-C...` dùng `apps/ai-agent-service/data/btc/catalog/crm_seed_synthetic.json`.

## Các bản cũ

v1 (101 kịch bản), v2 (122), v3 (150, nhãn `chuyen_khoan`), `output1-btc-diagnostic-v2` và bộ ASR `asr-team-v2` đã bị xóa khỏi cây thư mục; còn trong lịch sử git trước commit dọn dẹp. Không dùng được nữa để tái lập các run cũ trong `evaluation/runs/`, nhưng bằng chứng của các run đó vẫn còn nguyên ở đó.
