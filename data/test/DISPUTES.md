# Nhãn đã duyệt, đã rà và chưa làm của `data/test`

`official_gt_approved: false`. Từng thay đổi nằm trong [`conversion-report.json`](conversion-report.json), mỗi mục có `rule_from` là nhóm tương ứng của dev-r4:

- `decision: revise`, `proposed_by: null`: quy tắc đã duyệt ở dev-r4, áp theo yêu cầu của người duyệt (nhóm 5, 9, phần định dạng của 11, nhóm 12).
- `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-08`: Claude đề xuất sau khi đọc từng câu của tập test; người duyệt (dngan0365) chấp nhận cả bảng dưới ngày 08/11/2026.
- `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-09`: nhóm 14, 15, 17, 18, Claude đề xuất sau lần kiểm mâu thuẫn nhãn với lời khách; người duyệt chấp nhận cả bảng ngày 09/11/2026 (cờ `NEW_PROPOSALS_REVIEWED` trong `build_dev_r4.py`).
- `decision: pending`, `proposed_by: claude`: nhóm 21, 22, Claude đề xuất ngày 09/11/2026 sau lần kiểm hành động kỳ vọng của agent (tool, tham số, kết quả) với lời khách và mock BTC, chưa ai duyệt (cờ `ACTION_PROPOSALS_REVIEWED` trong `build_dev_r4.py`).

Còn **2 thay đổi** ở trạng thái `pending` (nhóm 21, 22). Đặt `ACTION_PROPOSALS_REVIEWED` trong `build_dev_r4.py` khi người duyệt chấp nhận.

Muốn bỏ một đề xuất thì sửa bảng tương ứng trong `evaluation/datasets/ground-truth-review/build_test_r1.py` (hoặc đặt `CLAUDE_PROPOSALS_REVIEWED = None` để đưa cả nhóm về `pending`), rồi chạy lại script từ gốc repo. Script dựng từ nhãn ở commit `cfb43fbb` và ghi đè các thư mục nhãn của `data/test` (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`), `conversion-report.json` và file này; audio và hội thoại mẫu không đổi. Bản gốc của file này ở `evaluation/datasets/ground-truth-review/notes/test/`.

## Đề xuất của Claude, đã duyệt 08/11/2026

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 1 | 7 cuộc chat: ADV-0049/c1, GEN-0011/c1, 0027/c1, 0030/c1, 0030/c2, 0043/c1, 0046/c2 | Thêm "Số {anh/chị} là …" ở lượt cuối, `phone_provided: true` | Mã kênh không có trong CRM, khách không đọc số, cuộc sau cần biết khách. Đúng 7 mã đã duyệt ở dev. GEN-0011, 0027, 0043 còn ghi sẵn `phone_provided: true` dù khách chưa đọc số |
| 2 | ADV-0016/c1, ADV-0048/c1, GEN-0019/c1, 0019/c2, 0035/c1, 0035/c2 | Bỏ `owned_sku` khỏi `must_carry_over` | Cuộc tra hoặc đổi một đơn khác món khách đã mua. Năm mã đầu đã duyệt ở dev; GEN-0035/c2 cùng đơn giày, ở test có thêm nhãn này |
| 3 | GEN-0017/c2, GEN-0033/c2 | Thêm "Vậy anh chuyển khoản nhé." sau câu đòi COD | Đơn vượt hạn mức COD, nhãn chuyển khoản, khách chỉ đòi COD. Không sửa GEN-0049/c2 (khách đã đồng ý chuyển khoản) và ADV-0030/c2 (khách chọn tách đơn để được COD) |
| 4 | ADV-0023/c1, ADV-0028/c1 | `hen_goi_lai`, `tool_called: null`, `must_not_call_tools: [order.create]`, bỏ `order_id`, bỏ `order.create` khỏi `tools/` | Câu cuối giống bản dev đã duyệt: chờ lương; "sẽ suy nghĩ thêm rồi chốt đơn" |
| 7 | GEN-0021/c2, GEN-0037/c2 | Bỏ `phone_provided` | Khách đọc số CCCD, không đọc SĐT của mình |
| 8 | ADV-0046/c1, GEN-0010/c1, GEN-0049/c1, GEN-0049/c2 (8,5 → 8 triệu); GEN-0036/c2 (8,1 → 8,5 triệu) | `budget_vnd` bằng số khách nói | Khách nói "8 triệu"; "8 triệu rưỡi" |
| 10 | SCN-ADV-0021 | Lời khách tự xưng "anh"; `blocker` "cần hỏi người nhà" | Nhãn và CRM là "anh" (Tuấn), khách tự xưng "cô/cháu" |
| 11 | 4 `promo_expiry` | Bỏ | Câu nói ngày sale 11/11 bắt đầu, lịch gọi lại hoặc ngày có hàng |
| 11 | 1 `phone` (GEN-0037/c2 t3) | Bỏ | Số CCCD |
| 11 | 10 nhãn tiền | 8 đổi sang `price_vnd`, bỏ 2 | Khách nhắc lại giá của shop ("giá là … đúng không", giá trên Zalo/web của shop). Bỏ khi là giá đã mua hoặc trùng `price_vnd`. Giữ 6 nhãn giá đối thủ thật |
| 11 | 15 nhãn `blocker` | Bỏ 14, đổi loại 1 | Câu nói ngân sách, hỏi trả góp, xin đổi size, xin trả hàng, đồng ý chuyển máy, hẹn giờ, hết hàng, hoặc không nêu lý do. GEN-0007 c1 t4: "giá cao hơn chỗ khác" là so sánh giá, không phải vượt ngân sách |

## Đề xuất của Claude, đã duyệt 09/11/2026

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 14 | 27 cuộc, 37 nhãn (`G14` trong `build_test_r1.py`) | Nối vào lượt đầu một câu khách nói đúng giá trị đã gán, ví dụ "Phòng anh khoảng 15 mét vuông, nhà anh có trẻ nhỏ." | `facts_established` có `room_area_m2` / `has_children` / `child_age_months` / `budget_vnd` mà khách không nói ở cuộc nào, seed_history cũng không có. Cuộc sau cấm hỏi (RQR) hoặc bắt nhớ (CCR) chính các slot đó, nên agent hỏi lại vì chưa biết bị trừ điểm. Danh sách từ bộ kiểm, đọc lại từng cuộc. Bỏ ADV-0021/c1 `has_children` ("có em nhỏ ở nhà": khách có nói). Thêm lời khách thay vì bỏ nhãn, như nhóm 1 và 3, để giữ phép thử trí nhớ |
| 15 | ADV-0006/c2, ADV-0013/c1, ADV-0038/c2, ADV-0045/c1, GEN-0015/c2, GEN-0027/c2, GEN-0033/c2, GEN-0042/c3 | Thêm lượt cuối "Đúng rồi em, lên đơn giúp {anh/chị} nhé." | `success_if` đòi `order.create` nhưng hai lượt cuối không có lời đồng ý (PB-09: đọc lại đơn rồi chờ khách xác nhận). `data/dev` đã được thêm câu đồng ý từ trước r3, tập test thì chưa |
| 17 | ADV-0050/c2 | Ở call_2 chỉ giữ slot khách tự nói lại trong cuộc đó: giữ size, màu, sản phẩm (khách nói lại "áo phao lông vũ size L màu be"), bỏ `blocker`, `price_quoted_vnd` | call_1 là chat ẩn danh (`fb.anon`), khách không đọc SĐT, nên cuộc hotline sau (số không có trong CRM) không nối được với call_1. Quy tắc của người duyệt: nếu khách có đọc SĐT thì agent phải lưu khách và giữ ngữ cảnh cho lần mua hoặc gọi sau |
| 18 | ADV-0045/c1 | Bỏ `owned_sku` khỏi `must_carry_over` | `seed_history` chỉ là thông tin tham khảo. Cuộc này mua màng lọc cho AirPure Pro khách nêu, còn lịch sử CRM là nồi chiên Lock&Lock 4L; giữ `owned_sku` sẽ bắt agent dùng món không liên quan |

Sửa ngày 09/11/2026 trong nhóm 14 (đã duyệt): câu thêm vào dùng cách người gọi tự xưng trong chính cuộc đó, không lấy `honorific` của kịch bản. Ở các kịch bản hai người chung SĐT, người gọi call_2 (chị Dung) đã bị ghi "Phòng cô…" theo cô Loan của kịch bản.

## Đã sửa, chờ duyệt (hành động của agent, 09/11/2026)

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 21 | GEN-0015/c2 | Lời chị Dung đổi thành mua "máy lọc không khí AirPure Mini cho phòng của chị", "lên đơn giúp chị" | Hai người chung SĐT: nhãn và `tools/` là AirPure Mini, nhưng lời thoại là mua "máy lọc nước RO Karofi 9 lõi mà cô Loan đã hỏi" (bản dev của kịch bản này đúng) |
| 22 | GEN-0022/c1 | Bỏ `args_match.callback_at`; giữ `schedule.callback`, `ground_truth_facts.callback_at` và `must_say_any` (27/10) | Giờ khách hẹn (Thứ Hai 26/10) là ngày nghỉ LN-02; như dev-r4 |

## Đã rà, giữ nguyên

| Phạm vi | Kết luận |
|---|---|
| 35 nhãn `size_old` / `size_new` / `return_days` / `exchange_fee_vnd` của ASR | Đọc từng câu: `size_old` chỉ ở size khách đang có hoặc muốn đổi đi ("size 43 chật quá"), `size_new` ở size muốn mua, "đổi trả trong 14 ngày" là `return_days`. Không cần sửa |

## Người duyệt quyết (09/11/2026)

| Nhóm | Phạm vi | Sửa | Lý do |
|---|---|---|---|
| 26 | ADV-0031/c1 | `has_children` false thành true (`facts_established`, `memory_expectation`) | Khách nói "Nhà anh có một phòng ngủ của con": người duyệt chọn đổi nhãn (khách có con) thay vì sửa lời |
| 28 | GEN-0048/c1, ADV-0023/c1 | Khách nói "Phòng mới của chị khoảng … mét vuông" | Như nhóm 28 của dev: diện tích không có trong lời khách, lịch sử CRM đã quá hạn |
| 29 | GEN-0004, 0005, 0031, 0047 call_2 | Bỏ các fact người gọi call_2 không nói | Hai người chung SĐT, như nhóm 29 của dev |

## Chưa làm

| Phạm vi | Lý do |
|---|---|
| Bộ vàng | `official_gt_approved: false`. `review/golden_manifest.json` đã có (dngan0365, 09/11/2026, `accepted_suggestions`: 188/192 nhãn, 111 hội thoại), ký trước khi nhóm 26, 28, 29 đổi nhãn: chạy lại `auto_verify.py` rồi ký lại. Còn N: GEN-0015/c2, GEN-0022/c1 (nhóm 21–22 chờ duyệt) và ADV-0024/c2 (giá RUN-10 dùng một lần) |
| Hội thoại mẫu: 2 ca J02 và các cuộc đã đổi lời khách | Đã đánh dấu `approve: N` (kèm lý do) trong `review/needs_manual_review.csv` bằng `evaluation/datasets/ground-truth-review/mark_conversations.py`, để không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến. Cần sinh lại khi nhãn ổn |
| Trùng mã và trùng khách với `data/dev` | Không sửa được bằng nhãn. Muốn có tập test độc lập thì cần sinh tập mới với mã riêng (vd. `SCN-TST-*`) và khách riêng |
| Audio của các lượt khách đã đổi | Nhóm 1, 3, 10, 14, 15 đổi lời khách, nhưng audio và `asr_reference` vẫn là lời cũ |
