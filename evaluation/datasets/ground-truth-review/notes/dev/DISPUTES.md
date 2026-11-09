# Nhãn đã duyệt, đã rà và chưa làm của `data/dev`

`official_gt_approved: false`. Từng thay đổi nằm trong [`conversion-report.json`](conversion-report.json):

- `decision: revise`, `proposed_by: null`: người duyệt chấp nhận đề xuất của bản tổng hợp 08/11/2026.
- `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-08`: Claude đề xuất sau khi đọc từng câu; người duyệt (dngan0365) chấp nhận cả bảng dưới ngày 08/11/2026.
- `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-09`: nhóm 11b, 14, 16, 17, 18, Claude đề xuất sau lần kiểm mâu thuẫn nhãn với lời khách; người duyệt chấp nhận cả bảng ngày 09/11/2026 (cờ `NEW_PROPOSALS_REVIEWED` trong `build_dev_r4.py`).
- `decision: pending`, `proposed_by: claude`: nhóm 19, 20, 21, 22, 23, 24, 31, Claude đề xuất ngày 09/11/2026 sau lần kiểm hành động kỳ vọng của agent (tool, tham số, kết quả) với lời khách và mock BTC, chưa ai duyệt (cờ `ACTION_PROPOSALS_REVIEWED` trong `build_dev_r4.py`).
- `decision: revise`, `proposed_by: null`, bằng chứng bắt đầu "Người duyệt nêu": nhóm 11c, 25–30, người duyệt tự nêu hoặc quyết (27–30 từ lần kiểm thứ hai của người kiểm khác) và yêu cầu sửa ngày 09/11/2026.

Còn **23 thay đổi** ở trạng thái `pending` (nhóm 19–24, 31). Đặt `ACTION_PROPOSALS_REVIEWED` trong `build_dev_r4.py` khi người duyệt chấp nhận.

Muốn bỏ một đề xuất thì sửa bảng tương ứng trong `evaluation/datasets/ground-truth-review/build_dev_r4.py` (hoặc đặt `CLAUDE_PROPOSALS_REVIEWED = None` để đưa cả nhóm về `pending`), rồi chạy lại script từ gốc repo. Script dựng từ nhãn ở commit `46b2f2ff` và ghi đè các thư mục nhãn của `data/dev` (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`), `conversion-report.json` và file này; audio và hội thoại mẫu không đổi. Bản gốc của file này ở `evaluation/datasets/ground-truth-review/notes/dev/`.

## Đề xuất của Claude, đã duyệt 08/11/2026

124 thay đổi trong `conversion-report.json`: nhóm 4 có 5, nhóm 7 có 7, nhóm 11 có 111, nhóm 12 có 1.

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 4 | SCN-ADV-0023/call_1 | `hen_goi_lai`, `tool_called: null`, `must_not_call_tools: [order.create]`, bỏ `order_id`, bỏ `order.create` khỏi `tools/` của oracle | Câu cuối "Chị chờ cuối tháng này nhận lương rồi thanh toán qua ngân hàng nhé": khách chưa đặt hôm nay, khớp với `blocker` "chờ cuối tháng nhận lương" của chính nhãn |
| 7 | 7 cuộc hotline: ADV-0146/c2, GEN-0037/c2, 0158/c2, 0171/c2, 0187/c2, 0221/c2, 0237/c2 | Bỏ `phone_provided` khỏi `facts_established` và `memory_expectation` của cuộc đó | Khách không đọc số của mình (đọc CCCD, số tài khoản, hoặc hỏi số người khác). `must_not_ask` của cuộc sau giữ nguyên, vì hệ thống đã biết số gọi tới |
| 11 | 61 nhãn `blocker` | Bỏ 57 nhãn, đổi loại 4 nhãn | Đã đọc 92 câu mà không có từ nào khớp với loại rào cản được gán. Các nhãn bỏ thuộc câu hẹn giờ, câu nói ngân sách, đổi trả, trả góp, nghi ngờ chính sách, xin chuyển máy gặp bác sĩ, "sếp cho phép". 31 câu còn lại giữ vì vẫn là lý do chưa mua |
| 11 | 22 nhãn `promo_expiry` | Bỏ | **Khác đề xuất gốc** (sửa năm). Các câu này nói ngày hẹn gọi lại ("tối thứ hai mười chín tháng mười… em gọi lại"), ngày có hàng, hoặc ngày sale 11/11 bắt đầu; không câu nào nói hạn khuyến mãi. Sửa năm sẽ tạo ra một hạn khuyến mãi không có thật |
| 11 | 6 nhãn `phone` | Bỏ | Là số CCCD hoặc số tài khoản. **Khác đề xuất gốc** (đổi tên trường): `entity_schema` không có `id_number` hay `bank_account` |
| 11 | 21 nhãn tiền | 17 đổi sang `price_vnd`, 4 bỏ | Câu khách nhắc lại giá shop ("giá em báo…", "giá là… đúng không") bị gán `competitor_price_vnd` hoặc `budget_vnd`. Bỏ khi là tổng đơn, giá đã mua, hoặc trùng với nhãn `price_vnd` sẵn có |
| 11 | SCN-GEN-0049-call_2-t8 `restock_date` | Bỏ | "Thế em hẹn cho chị gọi lại vào ngày hai mươi mốt nhé": lịch gọi lại, không phải ngày có hàng |
| 12 | `metadata/*.json` | Thêm tag `source:btc` (khách có trong `crm_seed.json` của BTC) hoặc `source:team` | Để báo cáo tách phần dựa trên dữ liệu BTC khỏi phần đội tự thêm. Dùng tag vì schema `Scenario` của bộ sinh dữ liệu không nhận khóa mới |

## Đề xuất của Claude, đã duyệt 09/11/2026

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 14 | 144 cuộc, 196 nhãn (`G14` trong `build_dev_r4.py`) | Nối vào lượt đầu một câu khách nói đúng giá trị đã gán, ví dụ "Phòng chị khoảng 20 mét vuông, nhà chị có trẻ nhỏ, ngân sách của chị tầm 6 triệu." | `facts_established` có `room_area_m2` / `has_children` / `child_age_months` / `budget_vnd` mà khách không nói ở cuộc nào, seed_history cũng không có. Cuộc sau cấm hỏi (RQR) hoặc bắt nhớ (CCR) chính các slot đó, nên agent hỏi lại vì chưa biết bị trừ điểm. Danh sách từ bộ kiểm, đọc lại từng cuộc. Bỏ ADV-0110/c1 `child_age_months` ("bé được một tháng": khách có nói). Thêm lời khách thay vì bỏ nhãn, như nhóm 1 và 3, để giữ phép thử trí nhớ. |
| 16 | ADV-0065/c2, GEN-0111/c2 | Bỏ `ground_truth_facts.freeship` | Quạt dưới 2.000.000đ chỉ được miễn phí ship nhờ NAM-SHIP0 (miền Nam), nhưng khách không nói nơi giao và CRM không có địa chỉ; không biết được freeship hay không |
| 11b | 12 nhãn `blocker` của ASR (`BLOCKER_CUE` trong `build_dev_r4.py`) | Bỏ 8, đổi 4 sang `vuot ngan sach` | Đọc 432 nhãn: 41 câu không có từ gợi ý chặt của loại được gán, và mọi câu có dấu hiệu "đã xong". Bỏ khi câu không nêu lý do ("hôm nay anh sẽ không quyết định mua"), xin chuyển máy, đổi sang sản phẩm khác, hoặc lý do đã xong ("đã hỏi vợ và quyết định mua rồi"). Đổi khi câu chê giá mà không so với nơi khác (schema chỉ có 7 loại, gần nhất là `vuot ngan sach`) |
| 17 | ADV-0050/c2, ADV-0093/c2, ADV-0145/c2 | Ở call_2 chỉ giữ slot khách tự nói lại trong cuộc đó: ADV-0050 giữ size, màu, sản phẩm (khách nói lại "áo phao lông vũ màu be size L"), bỏ `blocker`, `price_quoted_vnd`; ADV-0093 bỏ hết (khách chỉ nói "máy lọc không khí"); ADV-0145 giữ `blocker` ("đã bàn với gia đình"), bỏ sản phẩm, giá, ngân sách, nhu cầu | call_1 là chat ẩn danh (`fb.anon`), khách không đọc SĐT, nên cuộc hotline sau (số không có trong CRM) không nối được với call_1. Quy tắc của người duyệt: nếu khách có đọc SĐT thì agent phải lưu khách và giữ ngữ cảnh cho lần mua hoặc gọi sau |
| 18 | ADV-0045/c1 | Bỏ `owned_sku` khỏi `must_carry_over` | `seed_history` chỉ là thông tin tham khảo. Cuộc này mua màng lọc cho AirPure Pro khách nêu, còn lịch sử CRM là nồi chiên Lock&Lock 4L; giữ `owned_sku` sẽ bắt agent dùng món không liên quan |

Sửa ngày 09/11/2026 trong nhóm 14 (đã duyệt): câu thêm vào dùng cách người gọi tự xưng trong chính cuộc đó, không lấy `honorific` của kịch bản. Ở các kịch bản hai người chung SĐT, người gọi call_2 (chị Dung) đã bị ghi "Phòng cô…" theo cô Loan của kịch bản.

## Đã sửa, chờ duyệt (hành động của agent, 09/11/2026)

| Nhóm | Phạm vi | Đề xuất | Lý do |
|---|---|---|---|
| 19 | GEN-0184/c2 | `tool_called: schedule.callback`, `callback_at` 19:00 ngày hôm sau; thêm vào `tools/` và `ground_truth_facts.callback_at` | Khách nói "Tối mai 7 giờ em gọi lại cho anh nhé" nhưng nhãn không đòi tool nào. Playbook: xác nhận thời điểm gọi lại và ghi lịch bằng `schedule.callback`. Tool lỗi giả lập chỉ ở call_1 |
| 20 | ADV-0123/c1 | `hen_goi_lai`, `tool_called: null`, `must_not_call_tools: [order.create]`, bỏ `order_id`, bỏ `order.create` khỏi `tools/`, bỏ `must_say_any` về gọi xác nhận đơn | Câu cuối "Để chị bàn với gia đình rồi chốt đơn cho em." là hoãn, như ADV-0028 ở nhóm 4 |
| 21 | GEN-0197/c2 | Lời chị Dung đổi thành mua "máy lọc không khí AirPure Mini", "hôm qua cô Loan có gọi hỏi máy lọc nước", "lên đơn giúp chị" | Hai người chung SĐT: nhãn và `tools/` là AirPure Mini, nhưng lời thoại là mua "máy lọc nước RO Karofi 9 lõi" mà cô Loan đã hỏi |
| 22 | ADV-0151/c1, GEN-0022/c1, GEN-0056/c1, GEN-0102/c1, GEN-0138/c1, GEN-0172/c1, GEN-0206/c1 | Bỏ `args_match.callback_at`; giữ `tool_called: schedule.callback`, `ground_truth_facts.callback_at` (giờ đã dời) và `must_say_any` (27/10, 02/01) | Giờ khách hẹn rơi vào ngày nghỉ (LN-02: 26/10, 01/01). `args_match` ghim giờ khách xin, nên agent tự đề xuất khung gần nhất theo LN-01 thì trượt TSR, dù kết quả giống hệt agent để tool tự dời |
| 23 | ADV-0117/c1 | "chị đợi" thành "anh đợi" ở hai lượt | Nhãn và CRM là "anh", các lượt khác khách tự xưng "anh"; bộ sinh lỡ hai chỗ (như nhóm 10) |
| 24 | ADV-0154/c1 | Kết quả `schedule.callback` trong `tools/` của đáp án: 22:00, `moved_from: null` (trước là 08:00 do mock thô dời) | LN-02: ngày 11/11 tổng đài mở 07:00–23:00. Tool `schedule_callback` của agent (`mcp/servers/crm.py`, `clock.SPECIAL_HOURS`) giữ 22:00; chỉ `mock_tools.schedule_callback` thô của BTC chưa có ngoại lệ này. Kết quả trong đáp án lấy theo tool agent thật dùng, khớp `ground_truth_facts.callback_at` và `must_say_any` |
| 31 | GEN-0066/c1, GEN-0181/c1 | Khách nói "nhà anh có trẻ nhỏ" / "nhà chị không có trẻ nhỏ" ở lượt đầu | `has_children` có trong nhãn nhưng khách không nói; lộ ra khi `auto_verify.py` khớp giá trị thay vì bất kỳ từ nào |

## Người duyệt nêu, đã sửa (09/11/2026)

| Nhóm | Phạm vi | Sửa | Lý do |
|---|---|---|---|
| 11c | 15 nhãn `blocker` ASR (`BLOCKER_BUDGET_ONLY`) | Bỏ `vuot ngan sach` | Câu chỉ nói ngân sách ("chị có ngân sách khoảng bốn triệu thôi"), không nói giá vượt ngân sách; schema: `null` khi câu không nêu lý do. Đếm trên nhãn hiện tại còn 15 câu loại này (các câu khác đã bỏ ở nhóm 11). Giữ ADV-0110 c2 t4 ("ngân sách eo hẹp quá nên cần trả góp") |
| 25 | GEN-0099/c1 | "Chị có một bé lớn" thành "Nhà chị không có trẻ nhỏ, bé nhà chị lớn rồi" | `has_children: false` (nhà không có trẻ nhỏ) đúng ý, nhưng câu cũ dễ đọc thành có trẻ. Nhãn giữ nguyên |
| 26 | ADV-0031/c1, ADV-0126/c1 | `has_children` false thành true (`facts_established`, `memory_expectation`) | Khách nói "Nhà anh có một phòng ngủ của con": người duyệt chọn đổi nhãn (khách có con) thay vì sửa lời |
| 27 | ADV-0053/c2, GEN-0001/c1, GEN-0216/c1, GEN-0248/c1 | Khách nói cách thanh toán của `args_match.payment` ở lượt trước lượt cuối | Nhãn ghi bank/COD nhưng khách không nói (ADV-0053 hỏi "thanh toán bằng cách nào thì được?" rồi không chọn). Agent hỏi lại thì lời cố định không có câu trả lời (TSR); call_2 còn đòi nhớ và cấm hỏi `payment` |
| 28 | GEN-0016, 0048, 0082, 0148, 0182, 0216, 0248, ADV-0023, ADV-0118 call_1 | Khách nói "Phòng mới của chị khoảng … mét vuông" bằng đúng giá trị nhãn | Khách quay lại đã chuyển nhà; diện tích 20 m² trong lịch sử CRM đã quá hạn, khách không nói diện tích mới, mà call_2 cấm hỏi (RQR). `auto_verify.py` và danh sách nhóm 14 đã coi lịch sử là "đã nói": nay chỉ tính lời khách và phải khớp giá trị |
| 29 | 18 cuộc call_2 hai người chung SĐT (`G29` trong `build_dev_r4.py`) | Bỏ khỏi `facts_established`/`memory_expectation` các fact người gọi call_2 không nói | Người gọi call_2 là người còn lại; ngân sách, "gia đình 4 người", `has_children` là của người kia hoặc không ai nói |
| 30 | GEN-0081, 0131, 0097 call_2; cô Loan tự xưng "chị" ở GEN-0005, 0055, 0081, 0131, 0181 call_2 | Câu mở đầu đúng vai ("hôm trước cô có hỏi em về máy lọc nước RO"); cô Loan xưng "cô" (CRM C034) | Lẫn vai giữa hai người chung SĐT |

## Đã rà, đề xuất giữ nguyên

| Phạm vi | Kết luận |
|---|---|
| 33 cuộc `J02_no_fabrication` (`review/needs_manual_review.csv`) | Nhãn khớp `ground_truth_facts`: "7 giờ"/"19h" khớp `callback_at` 19:00, "219.000" khớp `refund_vnd`, "đã giao" khớp `order_status: delivered`, "19/10" khớp `restock_date`, "6.295.000" khớp `total_vnd`, "máy thứ hai" khớp AIR-2ND-50. Phần bịa nằm ở hội thoại mẫu (`conversations/`), không nằm ở nhãn. Chưa sinh lại hội thoại mẫu vì việc đó cần gọi model. Đã đánh dấu `approve: N` (kèm lý do) trong `review/needs_manual_review.csv` bằng `evaluation/datasets/ground-truth-review/mark_conversations.py`, để không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến. |
| SCN-GEN-0133/call_2 | Nhãn khớp lời khách (chuyển khoản, 4 món). Chỉ có hội thoại mẫu không gọi `order.create`. Đã đánh dấu `approve: N` (kèm lý do) trong `review/needs_manual_review.csv` bằng `evaluation/datasets/ground-truth-review/mark_conversations.py`, để không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến. |
| SCN-GEN-0092, 0126, 0192, 0210 call_3 (`max_agent_questions: 2`) | Khách tự đưa sản phẩm, thanh toán, địa chỉ rồi chốt; agent chỉ cần hỏi câu đọc lại đơn. Giữ giới hạn; cần sửa hội thoại mẫu. Đã đánh dấu `approve: N` (kèm lý do) trong `review/needs_manual_review.csv` bằng `evaluation/datasets/ground-truth-review/mark_conversations.py`, để không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến. |
| `args_match.order_group` (3 cuộc) | Giữ: `order_group` là tham số của đội đã khai trong `contracts/scenario/scenario-keys.yaml` (`team_tool_args`), và chính là hành vi tách đơn (QT-01) cần kiểm |
| `call_date` trong `ground_truth_facts` | Giữ: đã nằm trong `NON_CLAIM_FACTS` (`evaluation/data-generation/src/ground_truth/traces.py`) và `scorers.NOT_CLAIMS`, nên extractor không sinh claim cho nó và HR không đổi |
| Persona, `expected_outcome`, `hard_case`, các khóa ngoài định dạng BTC (nhóm 12) | Giữ; khi báo cáo ghi rõ đây là phần của đội |

## Chưa làm

| Phạm vi | Lý do |
|---|---|
| Bộ vàng | `official_gt_approved: false`. `review/golden_manifest.json` đã có (dngan0365, 09/11/2026, `method: accepted_suggestions`: 785/801 nhãn, 411 hội thoại), nhưng được ký **trước** lần kiểm thứ hai: các nhóm 26–31 đổi nhãn sau đó, nên cần chạy lại `auto_verify.py` rồi ký lại bằng `approve_gold.py`. `official_gt_approved` chỉ thành true khi nhãn của mọi cuộc là Y; hiện còn N: các cuộc của nhóm 19–24, 31 (chờ duyệt) và ADV-0024/0119 c2 (giá RUN-10 dùng một lần: nhãn đúng, bộ kiểm chặt) |
| Hội thoại mẫu của các cuộc đã đổi lời khách | Không còn khớp kịch bản. Đã đánh dấu `approve: N` (kèm lý do) trong `review/needs_manual_review.csv` bằng `evaluation/datasets/ground-truth-review/mark_conversations.py`, để không dùng làm ví dụ mẫu hay dữ liệu vòng cải tiến. Cần sinh lại (gọi model) khi nhãn ổn |
| Clip khách đọc SĐT 10 số | Cần sinh audio mới |
| Audio của các lượt khách đã đổi | Nhóm 1, 3, 10, 14 đổi hoặc thêm lời khách trong `scenarios/`, nhưng `audio/` và `asr_reference/` vẫn là lời cũ. Cần chạy `synthesize_scenario_audio --changed-only` |
| Nhóm 13 | Đã chọn quy ước: `budget_vnd` bằng đúng số khách nói (khác SAMPLE-01); `promo_active` là có giảm giá hoặc quà tặng (theo SAMPLE-01, khác SAMPLE-02) |
