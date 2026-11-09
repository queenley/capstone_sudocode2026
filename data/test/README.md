# Bộ `data/test`

99 kịch bản (50 `SCN-ADV`, 49 `SCN-GEN`), 192 cuộc, theo định dạng BTC, kèm audio, hội thoại mẫu và báo cáo của bộ sinh dữ liệu.

**Không phải tập test độc lập.** `data/test` là bản sinh lại của 50 `SCN-ADV` và 49 `SCN-GEN` đầu tiên của `data/dev`: cùng mã kịch bản, cùng khách, cùng persona và kế hoạch cuộc gọi; chỉ lời khách được viết lại. Điểm trên bộ này đo khả năng chịu được cách diễn đạt khác, không đo khả năng tổng quát. Đừng chạy hai bộ vào cùng một thư mục run. Muốn có tập test thật thì sinh bộ mới với mã (vd. `SCN-TST-*`) và khách riêng.

## Nhãn đã sửa (bản r1, 08–09/11/2026)

Các thư mục nhãn (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`), `conversion-report.json` và `DISPUTES.md` do [`build_test_r1.py`](../../evaluation/datasets/ground-truth-review/build_test_r1.py) ghi, dựng từ nhãn ở commit `cfb43fbb`, áp các nhóm sửa của `data/dev` (bản r4). Nhãn vẫn là chẩn đoán (`official_gt_approved: false`). Từng trường đổi ở `conversion-report.json` (mỗi mục có `rule_from`), lý do ở [`DISPUTES.md`](DISPUTES.md).

| Nhóm | Sửa | Phạm vi |
|---|---|---|
| 5, 9, 11 (định dạng), 12 | Quy tắc đã duyệt ở dev, tái tạo đúng danh sách dev | 5 cuộc, 31 cuộc, 6 nhãn, 99 kịch bản |
| 1, 2, 3, 4, 7, 8, 10, 11 (nghĩa) | Đọc câu của tập test, áp như ở dev | 83 thay đổi |
| 14 | Khách nói đúng các fact nhãn ghi mà trước đó không nói ở đâu | 27 cuộc |
| 15 | Thêm lời đồng ý cho cuộc tạo đơn mà khách chưa đồng ý | 8 cuộc |
| 17, 18 | Khách ẩn danh (ADV-0050/c2), `owned_sku` của ADV-0045/c1 | 2 cuộc |
| 21, 22 | Người chung SĐT mua đúng món của nhãn (GEN-0015/c2); gọi lại vào ngày nghỉ (GEN-0022/c1) (**chờ duyệt**) | 2 cuộc |

Kiểm, không gọi model: 99/99 kịch bản nạp được bằng loader của `run_eval`; 0 lỗi khóa; oracle qua `reference_eval.py` của BTC: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema.

Dựng lại từ gốc repo: `python evaluation/datasets/ground-truth-review/build_test_r1.py`, rồi từ `evaluation/data-generation`: `python -m src.pipeline.build_ground_truth --root ../../data/test`.

**Hội thoại mẫu (`conversations/`) không phải ví dụ mẫu:** các ca J02 có câu bịa, ca agent mẫu không tạo đơn hoặc hỏi quá giới hạn, và mọi cuộc đã đổi lời khách được đánh dấu `approve: N` trong `review/needs_manual_review.csv` (`evaluation/datasets/ground-truth-review/mark_conversations.py`). Không dùng chúng làm few-shot hay dữ liệu vòng cải tiến. Bộ này chưa phải bộ vàng: `official_gt_approved: false`, chưa có `review/golden_manifest.json`. Kiểm tự động và đề xuất từng cuộc ở `review/auto_verified.json`, `review/review_sheet.csv` (`auto_verify.py`); người duyệt ký bằng `evaluation/datasets/ground-truth-review/approve_gold.py`.

**Audio chưa theo kịp nhãn:** các nhóm 1, 3, 10, 14, 15, 21 đổi lời khách, nhưng audio, `asr_reference/` của những lượt đó và hội thoại mẫu vẫn là lời cũ.
