# Bảng chỉ số: 5 case M2 mới (24/10/2026)

Run `final-5new2` (thư mục `scripts/evaluation/runs/20261024-work/`, không commit). Dataset `create-data-diagnostic-v4` (nhãn **diagnostic, chưa người duyệt**), 5 kịch bản chưa dùng trước đó và không thuộc holdout: SCN-GEN-0051, 0070, 0142, 0129, 0086; 45 lượt mỗi cấu hình. Agent: prompt mới, chặn đơn trùng, `facts_used` do agent báo, hard guard hứa chuyển máy, Jev bật. Extractor `product-extractor-v3` (khớp đường chấm chính thức). Mẫu rất nhỏ: chỉ để xem hướng, không kết luận.

| Chỉ số | Baseline | Hệ thống | Mục tiêu BTC | Đạt |
|---|---|---|---|---|
| Task Success Rate | 20,0% (1/5) | **0,0%** (0/5) | ≥ 70% | không |
| TSR riêng ca khó | 25,0% (1/4) | 0,0% (0/4) | | |
| Context Carryover Rate | 2,0% (1/50) | **18,0%** (9/50) | | tăng 9 lần |
| Repeat-Question Rate | 5,1% (2/39) | **11,6%** (5/43) | giảm ≥ 40% so với baseline | không (tăng) |
| Hallucination Rate giá & KM | 7,7% (1/13) | **4,5%** (1/22) | ≤ 5% | hệ thống đạt |
| HR toàn bộ claim kiểm chứng được | 25,0% (5/20) | 16,1% (5/31) | | |
| Số lượt TB / cuộc | 3,46 | 3,46 | | |
| Vi phạm guardrail | 0 | 0 | | |
| TTFT p50 / p95 (bỏ 3 lượt warm-up, 42 lượt) | 2074 / 4055 ms | 2115 / **3779** ms | p95 ≤ 3000 ms | không |
| Total p50 / p95 (bỏ 3 lượt warm-up) | 2156 / 4087 ms | 2221 / 3892 ms | p95 ≤ 8000 ms | có |
| Calls-to-Close (BTC / đã xác minh) | 3 / 3,0 (1/5 kịch bản) | 3 / 3,0 (1/5 kịch bản) | | |

Ngưỡng p95 cần ≥ 100 lượt; ở đây chỉ 42, nên là chỉ báo.

## Vì sao TSR hệ thống là 0/5 (7 cuộc trượt)
- 0051 call_1: thiếu cụm `must_say_any` ("đang giao…"), cụm từ giòn.
- 0070 call_2 và 0086 call_2: không có `order.create` khớp; 0070 call_3 và 0086 call_3: không có `order.status` khớp.
- 0142 call_3: hỏi 5 câu, vượt giới hạn 2.
- 0129 call_2: nói `return_days` 14 (và 30) trong khi chính sách hiện hành là 7 ngày (claim cấm).

## RQR hệ thống cao hơn baseline: câu thừa thuộc về mã đơn
5 câu thừa của hệ thống đều là hỏi mở mã đơn (`order_id`) ở các kịch bản hỏi trạng thái đơn (0051, 0070, 0086), thông tin mà kịch bản coi là đã có. Baseline chỉ hỏi 2 lần vì ít cuộc cần đến.

## HR hệ thống
5 claim sai: `promo_active` và `freeship` ở 0086, `return_days` 30 và 14 so với 7 ở 0129 (chính sách cũ), `policy_version` ghi "2026-10-01" so với "2026-10" (cách ghi).
