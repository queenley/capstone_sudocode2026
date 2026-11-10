# Bộ `data/test`

99 kịch bản (50 `SCN-ADV`, 49 `SCN-GEN`), 192 cuộc, theo định dạng BTC, kèm audio, hội thoại mẫu và báo cáo của bộ sinh dữ liệu.

**Không phải tập test độc lập.** `data/test` là bản sinh lại của 50 `SCN-ADV` và 49 `SCN-GEN` đầu tiên của `data/dev`: cùng mã kịch bản, cùng khách và persona. Lời khách được viết lại; 51 cuộc được dời sang ngày khác (kéo theo giá và khuyến mãi khác, nhãn tính theo ngày mới), và SCN-GEN-0033/call_2, SCN-GEN-0049/call_2 đổi từ `hen_goi_lai` sang `chot_don`. Điểm trên bộ này đo khả năng chịu được cách diễn đạt khác, không đo khả năng tổng quát. Đừng chạy hai bộ vào cùng một thư mục run. Muốn có tập test thật thì sinh bộ mới với mã (vd. `SCN-TST-*`) và khách riêng.

## Nhãn đã sửa (bản r1, 08–09/11/2026)

Các thư mục nhãn (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`), `conversion-report.json` và `DISPUTES.md` do [`build_test_r1.py`](../../evaluation/datasets/ground-truth-review/build_test_r1.py) ghi, dựng từ nhãn ở commit `cfb43fbb`, áp các nhóm sửa của `data/dev` (bản r4). Người duyệt (dngan0365) đã ký nhãn từng cuộc ngày 10/11/2026: 192/192 (`official_gt_approved: true`, `review/golden_manifest.json`; 46/384 ô lấy theo gợi ý của `auto_verify.py`). Từng trường đổi ở `conversion-report.json` (mỗi mục có `rule_from`), lý do ở [`DISPUTES.md`](DISPUTES.md).

| Nhóm | Sửa | Phạm vi |
|---|---|---|
| 5, 9, 11 (định dạng), 12 | Quy tắc đã duyệt ở dev, tái tạo đúng danh sách dev | 5 cuộc, 31 cuộc, 6 nhãn, 99 kịch bản |
| 1, 2, 3, 4, 7, 8, 10, 11 (nghĩa) | Đọc câu của tập test, áp như ở dev | 83 thay đổi |
| 14 | Khách nói đúng các fact nhãn ghi mà trước đó không nói ở đâu | 27 cuộc |
| 15 | Thêm lời đồng ý cho cuộc tạo đơn mà khách chưa đồng ý | 8 cuộc |
| 17, 18 | Khách ẩn danh (ADV-0050/c2), `owned_sku` của ADV-0045/c1 | 2 cuộc |
| 21, 22 | Người chung SĐT mua đúng món của nhãn (GEN-0015/c2); gọi lại vào ngày nghỉ (GEN-0022/c1) | 2 cuộc |
| 26, 28, 29 | `has_children` theo lời khách (ADV-0031/c1); khách nói diện tích phòng mới (GEN-0048/c1, ADV-0023/c1); bỏ fact của người kia ở kịch bản chung SĐT (GEN-0004, 0005, 0031, 0047 call_2) (người duyệt yêu cầu, sau lần kiểm thứ hai) | 7 cuộc |

Mọi nhóm đã được người duyệt chấp nhận; không còn thay đổi `pending`.

Kiểm, không gọi model: 99/99 kịch bản nạp được bằng loader của `run_eval`; 0 lỗi khóa; oracle qua `reference_eval.py` của BTC: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema.

Dựng lại từ gốc repo: `python evaluation/datasets/ground-truth-review/build_test_r1.py`, rồi từ `evaluation/data-generation`: `python -m src.pipeline.build_ground_truth --root ../../data/test`.

**Hội thoại mẫu (`conversations/`) đã sinh lại theo nhãn r1** (09–10/11/2026, [`regenerate_conversations.py`](../../evaluation/datasets/ground-truth-review/regenerate_conversations.py)): 46 cuộc có lời khách đã đổi, trượt validator, agent mẫu bịa (J02) hoặc thiếu file được viết lại (danh sách ở `review/regenerated.json`). Validator: 191/192. Người duyệt đã ký lại ngày 10/11/2026: 149/192 hội thoại vào `review/golden_manifest.json` (nhãn và hội thoại cùng Y), theo kết quả của bộ chấm cũ (gpt-4o-mini). Sau đó bộ chấm hội thoại được chấm lại bằng gpt-5, có tài liệu shop và hướng dẫn chấm (`config/prompts/data-generation/judge_guidance.md`): 88/192 hội thoại qua mọi kiểm tự động, và 64 trong 149 hội thoại đã ký nay bị gắn cờ (nhiều nhất là J02, agent mẫu nói sai chính sách miễn phí vận chuyển hoặc thời hạn bảo hành; sau đó J08, xác nhận lặp lại). Người duyệt xem lại các cuộc đó trong `review/review_sheet.csv` trước khi dùng chúng làm few-shot hay dữ liệu vòng cải tiến. Kiểm tự động và đề xuất từng cuộc ở `review/auto_verified.json`, `review/review_sheet.csv` (`auto_verify.py`); người duyệt ký bằng `evaluation/datasets/ground-truth-review/approve_gold.py`.

**Audio đã theo kịp nhãn** (09–10/11/2026): mọi lượt khách đổi lời được đọc lại bằng `synthesize_scenario_audio --changed-only` (58 lượt, 4.793 ký tự ElevenLabs); `asr_reference/ground_truth.json` dựng lại từ clip trên đĩa, không còn clip đọc lời cũ. Nhãn entity lấy từ `asr_reference/<call>.json` (đã sửa ở nhóm 11), không lấy bản chép cạnh clip. Ở 114 clip mà khách không nói tên món ("xe này có khuyến mãi gì không em?"), `sku` (110) và `has_children` (4) chuyển sang `entities_not_stated`, như dev đã làm (nhóm 32, người duyệt chấp nhận 10/11/2026; xem [DISPUTES.md](DISPUTES.md)).
