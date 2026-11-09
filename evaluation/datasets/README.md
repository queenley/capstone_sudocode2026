# Datasets của evaluation

Kịch bản nằm ở [`data/dev/scenarios`](../../data/dev/README.md) (404 kịch bản: 250 persona BTC `SCN-GEN-*`, 154 persona của nhóm `SCN-ADV-*`). Định dạng của BTC (`apps/ai-agent-service/data/btc/schemas/scenario_format.md`), chạy bằng lệnh đánh giá duy nhất của repo. Thư mục này giữ quy tắc duyệt nhãn và danh sách ID đã dùng.

| Thư mục | Là gì |
|---|---|
| `ground-truth-review/` | Quy tắc duyệt và sửa nhãn (`SKILL.md`): đọc trước khi thêm hoặc sửa kịch bản |

Trạng thái: **diagnostic** (`official_gt_approved: false`). Nhãn do bộ sinh gán; người duyệt đã chấp nhận từng nhóm sửa (`DISPUTES.md` của `data/dev` và `data/test`), và `review/golden_manifest.json` đã ký từng cuộc (dev 786/801 nhãn, test 189/192); bộ vàng chính thức khi mọi cuộc được duyệt. Mọi điểm đo trên bộ này là điểm chẩn đoán, không phải điểm chính thức.

## Chạy thử

```bash
# lập kế hoạch + chạy 1 kịch bản (tốn phí model; extractor tắt)
apps/ai-agent-service/.venv/bin/python run_eval.py --scenarios data/dev/scenarios --only SCN-GEN-0051 --no-extract --out evaluation/runs/<tên-lần-chạy>
```

Chọn tập con: chép kịch bản sang một thư mục trong `evaluation/runs/subsets/` rồi trỏ `--scenarios` vào đó (xem `data/dev/README.md`, mục 3).

Khách tổng hợp `SYN-C...` dùng `apps/ai-agent-service/data/btc/catalog/crm_seed_synthetic.json`.

## Kịch bản đã dùng (ID có tiền tố `SCN-GEN-`)

**Đây là ID của bộ v4 cũ (đã xoá); chưa xác nhận ID trùng nội dung với `data/dev`** (SCN-GEN-0051 thì cùng khách và cùng đơn). Lấy từ các run trong `evaluation/runs/` và sổ chạy đã xóa; ghi lại đây để không chạy trùng hay dùng nhầm holdout. Mọi nhãn vẫn là diagnostic.

| Nhóm | ID |
|---|---|
| Run 17/10 (chỉ đọc, 10 case bị loại khỏi mọi run mới) | 0010, 0011, 0012, 0013, 0014, 0017, 0018, 0020, 0021, 0026 |
| Run 22/10: development (10) | 0007, 0008, 0023, 0027, 0029, 0030, 0034, 0036, 0037, 0083 |
| Run 22/10: holdout (10), **đã dùng để gỡ lỗi nên không còn độc lập** | 0006, 0024, 0033, 0038, 0039, 0040, 0043, 0046, 0050, 0053 |
| Run 24/10: development M2 (12) | 0003, 0028, 0032, 0060, 0062, 0066, 0069, 0118, 0126, 0146, 0148, 0150 |
| Run 24/10: development M1 (4) | 0072, 0075, 0088, 0089 |
| Run 24/10: 5 case mới | 0051, 0070, 0086, 0129, 0142 |
| **Holdout 24/10, chưa chạy lần nào** (M2: 0145, 0105, 0002, 0071, 0035, 0121, 0019; M1: 0091, 0138, 0052) | giữ nguyên, chỉ chạy một lần sau khi chốt sửa, không dùng để sửa sản phẩm |

## Các bản cũ

v1 (101 kịch bản), v2 (122), v3 (150, nhãn `chuyen_khoan`), v4 (`create-data-diagnostic-v4`, 150, lệch SKU đơn so với CRM synthetic), `output1-btc-diagnostic-v2` và bộ ASR `asr-team-v2` đã bị xóa khỏi cây thư mục; v1 đến v3 còn trong lịch sử git trước commit dọn dẹp. Bằng chứng các run cũ trong `evaluation/runs/` còn nguyên, nhưng không tái lập được từ bộ đã xoá.
