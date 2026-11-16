# Phân tích các cuộc fail TSR, lần chạy `router` trên `data/dev` (16/11/2026)

Nguồn: `docs/evaluation/conversations.csv`, cấu hình `router` (kiến trúc cũ, trước plan 002), 409 kịch bản, 807 cuộc, **178 cuộc fail TSR**. CSV chỉ có lời thoại, không có `tool_calls`, nên nguyên nhân được suy từ `success_if`, lời thoại, mock BTC (`eval/mock_tools.py`) và chạy offline các hàm của agent; không gọi model. Bảng từng cuộc: [`tsr-fail-causes-20261116.csv`](tsr-fail-causes-20261116.csv).

## Tổng hợp

| Loại | Số cuộc | Xử lý |
|---|---:|---|
| Agent sai, đã sửa (A1–A11) | 86 | sửa code/prompt; code có test |
| Agent sai, chưa sửa (A12) | 5 | cần trace hoặc cần duyệt, bên dưới |
| Hỏng dây chuyền từ cuộc trước (C1) | 11 | tự hết khi cuộc trước đúng |
| Dataset sai (D1–D7) | 71 | chỉ báo cáo |
| Extractor sai (E1) | 5 | chỉ báo cáo |
| ASR sai | 0 | không có: lượt khách là văn bản dựng sẵn; lỗi gõ không dấu thuộc ITN (A4) |

## Agent sai, đã sửa

| Mã | Lỗi | Cuộc | Sửa |
|---|---|---:|---|
| A1 | Hai người chung SĐT: khách nói "chị Dung đây, hôm trước…" mà `pick_by_name` chỉ nhận câu chỉ có tên; câu "ừ đúng rồi" sau khi agent hỏi "mình là chị Dung ạ?" cũng không được nhận. Tier kẹt AMBIGUOUS, không lên được đơn | 18 | `resolver._here`: nhận câu tự giới thiệu ở bất kỳ đâu (có dấu: "đây"/"nè", không nhầm "đấy"; không sau "không phải"). `nodes._bind_named`: khi còn AMBIGUOUS, lượt sau vẫn nhận tên, hoặc nhận "đúng rồi" nếu câu trước của agent nêu đúng một ứng viên. Đo offline trên 42 cuộc chung SĐT: 30/30 lượt có nói tên nhận đúng người, 0 nhầm |
| A2 | Tra giá/tồn kho/đặt đơn bằng SKU cha (`SKU-SN-RUN2`) khi khách đã nói size và màu: báo "còn hàng" khi biến thể hết, báo giá có RUN-10 cho size 43 vốn bị loại trừ, đơn ghi mã cha | 16 | Guard: `order_create`/`order_update` từ chối mã cha có biến thể. Tra trước (`named_lookups`, kiến trúc mới) tra đúng biến thể khi lời khách đủ size và màu, không tra mã cha. Đo offline: 92 lượt tra biến thể trên dev, 0 lệch nhãn |
| A3 | Khách nói "chốt" trước khi nói cách thanh toán: agent tạo đơn với COD mặc định, rồi nói "đã cập nhật sang chuyển khoản" (không có tool nào đổi thanh toán) | 7 | Guard: `order_create` thiếu `payment` hoặc `address` thì bắt hỏi khách (khu vực là đủ địa chỉ); skill `place-order` bỏ "chưa chọn thì để COD" và "bỏ trống địa chỉ, xin sau khi tạo đơn" (trái PB-09); mô tả tham số `payment`, `address` sửa theo |
| A4 | ITN: "5 triệu bảy trăm" thành `5 1.700.000đ`; "tối thứ Bảy này tầm 10 giờ" thành 10:00 hôm nay; "(19/10)", "ngày 11/11" trong câu bị bỏ qua; câu không dấu "toi thu hai 19 10 tam 7 gio" không được đọc | 6 | `itn.py`: chữ số trước đơn vị tiền; từ đệm "tầm/khoảng/lúc", "này" sau thứ; ngày ghi rõ và buổi trong cùng câu; mẫu không dấu |
| A5 | Chuyển máy khi khách hỏi chuyện ngoài lề (phở, bài văn) hay đòi thông tin người khác; viết hộ bài văn; chuyển máy với câu hỏi bảo hành | 12 | `rules.md` luật 4, 9 và `policy_rules.md` (handoff): việc ngoài mua bán và đòi thông tin người khác thì nói không có thông tin / không thể cung cấp, không chuyển |
| A6 | Nhắc lại "11/11" khi từ chối nói về đợt sale chưa bắt đầu (`trace_must_not_match`) | 4 | skill: không lặp lại ngày/tên đợt sale khách nêu |
| A7 | Handoff Brief để trống `product_advised`, `price_quoted_vnd` khi Call Brief không có sản phẩm tư vấn | 2 | `nodes._handoff_product`: lấy sản phẩm đã báo giá trong cuộc, rồi đơn gần nhất của khách (Call Brief nay mang `price_vnd` của đơn) |
| A8 | Tự chọn mẫu khi khách chưa chọn, hoặc đổi sang mẫu thay thế khách không nói chọn | 4 | skill `place-order`: đặt đúng mẫu khách gọi tên; lời khách khớp nhiều mẫu thì hỏi |
| A9 | Đơn tách COD (QT-01): giá máy thứ hai lấy từ báo giá lẻ thay vì báo giá có `basket_skus`, guard từ chối; câu đọc lại cộng "tổng cả giỏ" theo giá lẻ (14.180.000đ thay vì 10.935.000đ) | 3 | `advisor._basket_quotes_in`: đơn có `basket_skus` dùng báo giá cùng giỏ; tổng giỏ chỉ đọc khi có `pricing_quote_order` của cả giỏ |
| A10 | Hỏi quá `max_agent_questions`: đọc lại đơn ở mỗi lượt khách bổ sung thông tin | 11 | Một phần nhờ A3 (không tạo đơn trước khi có thanh toán). Ca `max_agent_questions: 1` mà khách đưa địa chỉ ở lượt 3 thì gần như không đạt được (xem D7) |

Câu đọc lại đơn với mã biến thể nói "1 sản phẩm đã chọn": nay đọc tên, size, màu từ catalogue (`commerce.product_name`).

| A11 | Nói "vẫn trả được nếu còn trong 7 ngày" trước khi xem ngày đơn; tạo yêu cầu trả hàng sau khi chính agent nói đã quá hạn (mock BTC không tự kiểm hạn); xin "địa chỉ cụ thể" khi khách đã nói khu vực | 3 | skill `change-order`: xem ngày đơn trước, quá hạn DT-01 thì không gọi `order_update`; skill `place-order`: khu vực là đủ địa chỉ |

## Agent sai, chưa sửa (A12, 5 cuộc)

| Cuộc | Lỗi | Vướng gì |
|---|---|---|
| ADV-0071 call_2 | Khách nói người nhà đã mua cái khác rồi hỏi "mình có thể trả hàng không?"; agent hỏi xác nhận, khách không trả lời thẳng, không có `order_update` | Cần duyệt: hạ ngưỡng ý định "change" của PolicyAgent để câu hỏi "có trả được không" kèm lý do được coi là yêu cầu trả. Rủi ro tạo yêu cầu trả khi khách chỉ hỏi |
| ADV-0008 call_1 | Không nói thời gian xử lý bảo hành 7–15 ngày; các lượt sau không có câu trả lời trong CSV | Cần trace (có thể đã chuyển máy) |
| ADV-0090 call_2 | Cuộc 1 khách nói giỏ có "Medela", cuộc 2 agent nhớ thành "Spectra S1" | Cần trace: lỗi ghi bộ nhớ hay agent cuộc 1 đã tư vấn Spectra |
| GEN-0067 call_2 | Khách đổi ngân sách giữa đơn 4 món, agent tạo đơn chỉ có màng lọc | Cần trace tool_calls |
| ADV-0060 call_2 | Tạo đơn máy X ngay khi khách nói "chốt một cái", máy Mini thêm sau không vào cùng đơn | Có thể đã đỡ nhờ A3 (chưa có thanh toán thì chưa tạo đơn); cần đo |

Đề xuất cần duyệt thêm: một hard guard chặn `order_update` đổi/trả khi ngày đơn quá hạn DT-01. Mock không kiểm, quy trình QT nói "chỉ hợp lệ trong thời hạn DT-01", nhưng hạn tính từ ngày ký nhận mà trace chỉ có ngày tạo đơn, và lỗi nhà sản xuất có hạn 30 ngày; hiện chỉ sửa bằng prompt.

## Hỏng dây chuyền (C1, 11 cuộc)

Call 2/3 đổi size hay hỏi tình trạng đơn mà call 1 đã tạo sai sản phẩm hoặc không tạo đơn. Hết khi call 1 đúng.

## Danh sách mã theo nhóm

Mỗi cuộc fail đúng một nhóm; bảng đầy đủ kèm lý do của bộ chấm ở [`tsr-fail-causes-20261116.csv`](tsr-fail-causes-20261116.csv).

| Nhóm | Mã kịch bản, cuộc (`SCN-` bỏ đầu, `c2` = `call_2`) |
|---|---|
| A1 nhận diện SĐT chung | GEN-0004 c2, GEN-0005 c2, GEN-0015 c2, GEN-0031 c2, GEN-0055 c2, GEN-0065 c2, GEN-0081 c2, GEN-0115 c2, GEN-0131 c2, GEN-0147 c2, GEN-0155 c2, GEN-0165 c2, GEN-0181 c2, GEN-0197 c2, GEN-0205 c2, GEN-0215 c2, GEN-0231 c2, GEN-0247 c2 |
| A10 hỏi quá số câu (đọc lại đơn nhiều lần, hỏi thừa) | ADV-0007 c1, ADV-0039 c1, ADV-0068 c1, ADV-0088 c1, ADV-0102 c1, ADV-0134 c1, GEN-0003 c3, GEN-0042 c3, GEN-0160 c3, GEN-0176 c3, GEN-0210 c3 |
| A11 đổi trả không xem ngày đơn; xin địa chỉ chi tiết (sửa prompt) | ADV-0043 c1, ADV-0138 c1, GEN-0105 c2 |
| A12 agent sai, chưa sửa (cần trace hoặc cần duyệt) | ADV-0008 c1, ADV-0060 c2, ADV-0071 c2, ADV-0090 c2, GEN-0067 c2 |
| A2 SKU cha thay vì biến thể (giá/tồn kho/đơn) | ADV-0032 c2, ADV-0112 c3, ADV-0131 c2, GEN-0014 c3, GEN-0022 c2, GEN-0026 c2, GEN-0060 c1, GEN-0060 c3, GEN-0092 c3, GEN-0096 c3, GEN-0108 c1, GEN-0114 c3, GEN-0123 c1, GEN-0193 c2, GEN-0196 c3, GEN-0202 c2 |
| A3 tạo đơn sớm với COD tự chọn, rồi báo "đã đổi thanh toán" | ADV-0017 c3, ADV-0078 c3, ADV-0099 c2, ADV-0105 c1, GEN-0034 c2, GEN-0061 c2, GEN-0234 c2 |
| A4 ITN đọc sai tiền/giờ | ADV-0036 c1, ADV-0099 c1, ADV-0153 c1, ADV-0154 c1, GEN-0136 c2, GEN-0170 c2 |
| A5 chuyển máy thừa / làm việc ngoài phạm vi | ADV-0002 c1, ADV-0034 c1, ADV-0051 c2, ADV-0052 c1, ADV-0080 c1, ADV-0084 c1, ADV-0094 c2, ADV-0097 c1, ADV-0103 c1, ADV-0114 c1, ADV-0129 c1, ADV-0146 c2 |
| A6 nhắc lại ngày sale chưa công bố | ADV-0022 c1, ADV-0054 c1, ADV-0117 c1, ADV-0149 c1 |
| A7 Handoff Brief thiếu sản phẩm/giá | ADV-0017 c2, ADV-0144 c1 |
| A8 tự chọn/đổi mẫu khách chưa chọn | GEN-0016 c1, GEN-0177 c2, GEN-0182 c1, GEN-0216 c1 |
| A9 đơn tách (QT-01) sai giá máy thứ hai | ADV-0030 c2, ADV-0059 c2, ADV-0125 c2 |
| C1 hỏng dây chuyền từ cuộc trước | GEN-0008 c2, GEN-0024 c2, GEN-0086 c3, GEN-0090 c2, GEN-0108 c2, GEN-0136 c3, GEN-0158 c2, GEN-0174 c2, GEN-0208 c2, GEN-0216 c2, GEN-0240 c2 |
| D1 order_id trong nhãn khác mã khách nói | GEN-0035 c1, GEN-0035 c2, GEN-0069 c1, GEN-0069 c2, GEN-0101 c1, GEN-0101 c2, GEN-0135 c1, GEN-0135 c2, GEN-0169 c1, GEN-0169 c2, GEN-0201 c1, GEN-0201 c2, GEN-0235 c1, GEN-0235 c2 |
| D2 channel_identity không có trong CRM | ADV-0003 c2, ADV-0009 c1, ADV-0035 c2, ADV-0041 c1, ADV-0048 c1, ADV-0049 c1, ADV-0064 c2, ADV-0070 c1, ADV-0077 c1, ADV-0098 c2, ADV-0104 c1, ADV-0130 c2, ADV-0136 c1, ADV-0143 c1 |
| D3 khách không nói mẫu, nhãn tự chọn một mẫu | GEN-0008 c1, GEN-0024 c1, GEN-0030 c3, GEN-0086 c2, GEN-0126 c3, GEN-0146 c3, GEN-0158 c1, GEN-0174 c1, GEN-0192 c3, GEN-0240 c1 |
| D4 nhãn trái tài liệu/mock BTC | ADV-0013 c1, ADV-0031 c1, ADV-0045 c1, ADV-0108 c1, ADV-0140 c1, GEN-0213 c2 |
| D5 must_say quá hẹp (agent nói đúng ý, khác chữ) | ADV-0014 c2, ADV-0016 c1, ADV-0049 c2, ADV-0055 c1, ADV-0111 c1, ADV-0120 c1, ADV-0126 c1, ADV-0144 c2, ADV-0147 c1, GEN-0019 c1, GEN-0051 c1, GEN-0085 c1, GEN-0151 c1, GEN-0185 c1, GEN-0219 c1 |
| D6 khách đổi ý giữa chừng, nhãn giữ đơn cũ | ADV-0012 c2, ADV-0073 c2, ADV-0079 c2, GEN-0036 c2, GEN-0167 c2 |
| D7 lượt khách không đủ để đạt success_if | ADV-0068 c2, ADV-0093 c1, ADV-0145 c1, ADV-0145 c2, GEN-0037 c2, GEN-0121 c2, GEN-0237 c2 |
| E1 extractor tính câu phủ định/điều kiện là claim | ADV-0033 c1, ADV-0083 c1, ADV-0150 c1, GEN-0029 c2, GEN-0063 c2 |

## Ca nghi ngờ (phân loại chưa chắc)

| Mã | Đang xếp | Vì sao nghi |
|---|---|---|
| ADV-0007, 0039, 0068, 0088, 0102, 0134 c1 | A10 (agent hỏi thừa) | `max_agent_questions: 1` mà khách chỉ đưa địa chỉ ở lượt 3, nên agent gần như phải hỏi ít nhất một câu địa chỉ cộng câu đọc lại đơn. Có thể là nhãn quá chặt (dataset) |
| GEN-0036 c2, ADV-0079 c2 | D6 (khách đổi ý) | Agent cuộc 2 nhắc "xe đẩy Joie Pact" trong khi nhãn cuộc 1 là SKU-MB-STR2. Có thể agent cuộc 1 đã tư vấn Joie Pact (hợp lệ, nhãn giả định một mẫu), hoặc bộ nhớ ghi sai. Cần trace cuộc 1 |
| ADV-0055, 0120 c1; ADV-0126 c1; ADV-0014 c2 | D5 (chữ quá hẹp) | Agent đúng ý nhưng không nêu lý do ("freeship chỉ cho miền Nam", "máy thứ hai", "8%"). Nhãn hẹp, nhưng câu trả lời có lý do sẽ tốt hơn cho khách |
| GEN-0213 c2 | D4 (nhãn trái catalogue) | Nhãn đòi "không có thông tin" cho "bản giới hạn màu hồng"; agent trả lời theo catalogue (chỉ có đen, trắng, xám). Có thể người viết nhãn muốn agent không khẳng định "không có bản giới hạn" |
| ADV-0049 c1 | D2 (`fb.syn-c003` không có trong CRM) | Khách đọc số ở lượt cuối, sau khi đã chuyển máy; brief thiếu SĐT. Một phần là agent chuyển máy trước khi có số |
| C1 (11 cuộc) | Hỏng dây chuyền | Chỉ đúng nếu cuộc trước được sửa; GEN-0216 c2 còn do agent đọc đơn cũ OD188213 thay vì đơn vừa tạo |

## Vấn đề dataset (chỉ báo cáo, không sửa)

- **D1, 7 kịch bản, 14 cuộc:** GEN-0035, 0069, 0101, 0135, 0169, 0201, 0235. `args_match.order_id` là đơn `OD9xxx03` (đã giao, sản phẩm khác) trong khi khách đọc và hỏi đơn `OD9xxx02`. Sửa: đổi nhãn sang `…02`, hoặc đổi lời khách.
- **D2, 14 cuộc:** `channel_identity` không có trong `crm_seed_synthetic.json`: `fb.c003`, `fb.c009`, `fb.c023`, `fb.c029`, `fb.syn-c003`, `zalo_syn-c002/c004/c006/c008/c010`. Sửa: thêm các id này vào CRM của khách tương ứng, hoặc cho khách đọc SĐT.
- **D3, 10 cuộc:** khách chỉ nói "giày chạy bộ size N màu X" ở mọi cuộc; catalogue có hai dòng (RunLite 1, RunLite 2 Pro) cùng size màu; nhãn chọn RunLite 2 Pro. Sửa: cho khách nói tên mẫu, hoặc nhãn chấp nhận cả hai.
- **D4, 6 cuộc:** ADV-0013, 0045, 0108, 0140: "6–12 tháng" cho màng lọc AirPure X/Pro, trong khi bảng SP-AIR ghi X: 8–12 tháng, Pro: 12 tháng (6–12 là HEPA nói chung, BH-02). ADV-0031: cấm `price_vnd=2445000` dù mock trả đúng giá đó cho AirPure X đi cùng Y (AIR-2ND-50). GEN-0213: xem phần nghi ngờ.
- **D5, 15 cuộc:** `must_say_any` thiếu cách nói tương đương: "đang trên đường giao" (cần "đang giao"), "chưa áp dụng freeship cho khu vực" (cần "miền Nam"), "giảm 50% máy rẻ hơn" (cần "máy thứ hai"), "391.200đ" (cần "8%"), "chưa có chương trình giảm 50%" (cần "không thể").
- **D6, 5 cuộc:** khách đổi ngân sách hay đổi ý giữa cuộc, nhãn vẫn đòi đơn ban đầu (ADV-0012, 0073: vẫn đòi Y + Mini sau khi khách hạ ngân sách còn 5 triệu; GEN-0167: vẫn đòi 4 món sau khi hạ còn 8,5 triệu).
- **D7, 7 cuộc:** lượt khách không đủ để đạt `success_if`: khách không bao giờ đồng ý xóa rõ ràng (GEN-0121, GEN-0237), khách từ chối nói với AI rồi mới xin xóa (GEN-0037), chat ẩn danh hẹn gọi lại mà không cho SĐT (ADV-0093, ADV-0145 c1, c2 hỏng theo), call 2 khách nhắc đơn khác với call 1 (ADV-0068).

## Extractor (chỉ báo cáo)

`config/prompts/evaluation/extractor.txt` luật 9 đã cấm ghi "con số chỉ nhắc để bác bỏ hoặc mô tả chính sách cũ", nhưng extractor vẫn ghi `return_days=14` (GEN-0029, 0063), `exchange_fee_vnd=20000` (GEN-0063), `freeship=True` cho câu có điều kiện (ADV-0150), và gán `product_available=True` của câu về HikePro/nồi chiên cho iPhone (ADV-0033, 0083). Lỗi do model extractor không theo luật. Theo quy ước không sửa phần evaluation; cần người phụ trách evaluation xem.

## Rà prompt agent (16/11)

Đã đọc toàn bộ `rules.md`, `skills.yaml`, `notes.yaml`, `policy_rules.md`. Mâu thuẫn tìm thấy và đã sửa:

| Chỗ | Mâu thuẫn | Sửa |
|---|---|---|
| `skills.yaml` `place-order` | Một dòng bảo "khách giục đặt mà chưa có địa chỉ thì bỏ trống address, xin sau khi tạo đơn; chưa chọn thanh toán thì để COD", trái PB-09 (đọc lại địa chỉ và thanh toán trước `order.create`) | Gộp thành một dòng: cần đủ sản phẩm, thanh toán, địa chỉ (khu vực là đủ); thiếu thì hỏi gộp một câu. Guard chặn `order_create` thiếu `payment` hoặc `address`; mô tả tham số `address` trong `crm.py` sửa theo |
| `place-order` | "Khách đã nói đặt và đã biết sản phẩm: gọi order_create ngay" ngược với dòng trên | "…và đơn đã đủ ba thứ trên" |
| `rules.md` luật 3 | Hạn đổi trả "tính từ ngày mua", DT-01 tính từ ngày nhận | Đổi trả từ ngày nhận, bảo hành từ ngày mua; dùng ngày đơn trong Call Brief/order_status nếu có |
| `change-order` | "Đã nói rõ muốn trả thì gọi order_update ngay" ngược với "quá hạn thì không gọi" | Dòng kiểm hạn đứng trước; "gọi ngay" chỉ khi đơn còn hạn |
| `notes.yaml` `preamble` | "Cả lượt tối đa ba câu" trong khi chế độ thoại cho tối đa hai câu | "Vẫn trong giới hạn số câu ở trên" |
| `rules.md` luật 9 | Sau lần chèn ngày 16/11, câu "Các trường hợp này" không còn rõ chỉ trường hợp nào | Viết lại: khi nào chuyển, khi nào không chuyển, và trường hợp thông tin người khác tách riêng |
| `product-advice`, `place-order` | Không nói rõ phải tra bằng mã biến thể | Thêm: sản phẩm có size, màu thì mọi lần tra và đặt dùng variant_sku |

Chỗ dài nhưng giữ nguyên: `rules.md` luật 4 và 13, `notes.yaml` `CONTINUITY` và `spoken`. Mỗi câu ứng với một lỗi đã gặp; cắt thì mất quy tắc. Đề xuất (chưa làm): bỏ skill `conversation` khi chưa có bài học nào được duyệt (thân chỉ có một câu mô tả).

Chỗ còn có thể xung đột, cần người quyết định:
- `policy_rules.md` `change`: "Đơn còn thiếu địa chỉ mà khách cho địa chỉ tức là muốn cập nhật địa chỉ". Nay agent không tạo đơn thiếu địa chỉ nữa; dòng này chỉ còn dùng cho đơn web hoặc đơn cũ. Giữ.
- `rules.md` luật 4 (chuyển máy khi tài liệu không trả lời được, theo quyết định 01/11) và PB-05 ("ghi nhận, hẹn phản hồi"): giữ theo quyết định cũ.

## Kiến trúc mới (plan 002) có còn sai không

Các lỗi trên nằm ở nhận diện, ITN, guard, prompt và cách tính giá, dùng chung cho cả hai kiến trúc, nên kiến trúc mới cũng sai y như vậy trước khi sửa. Riêng A2 kiến trúc mới còn tệ hơn: tra trước (`ADVISOR_PREFETCH`) đưa sẵn giá và tồn kho của mã cha vào cho model; đã sửa. Câu soạn sẵn (`reply`) của tool ghi không thay đổi các kết quả trên.

## Chạy thử evaluation trên ca nghi ngờ (16/11)

Run `evaluation/runs/fix-check-20261116` (log `evaluation/runs/fix-check-20261116.log`). Cấu hình giống bench `on4` của kiến trúc mới: advisor như lần chạy dev (`AGENT_PROFILE` trống), bật `ADVISOR_PREFETCH`, `REPLY_PLAN`, `EARLY_INTENTS`, `SHORT_BRIEF`, `PREAMBLE`, `PRODUCT_ADVISE`, `FIRST_CLAUSE`, `SERVICE_TIER=priority`; chỉ `full`, extractor `product-extractor-v13`. Mỗi kịch bản đại diện một nhóm lỗi đã sửa, cộng ADV-0071 (chưa sửa). Một lần chạy mỗi kịch bản, nên mỗi ô có thể là dao động.

| Kịch bản, cuộc | Nhóm | `router` cũ | Lần chạy này | Ghi chú |
|---|---|:-:|:-:|---|
| SCN-ADV-0017 c2 | A7 brief | 0 | 1 | Handoff Brief đủ trường |
| SCN-ADV-0017 c3 | A3 thanh toán | 0 | 1 | Đơn tạo với chuyển khoản khách chọn |
| SCN-ADV-0154 c1 | A4 giờ hẹn | 0 | 1 | "tối thứ Tư, ngày 11/11, tầm 10 giờ" đặt đúng 22:00 |
| SCN-GEN-0026 c2 | A2 biến thể | 0 | 1 | Không còn báo "còn hàng" cho size đã hết |
| SCN-GEN-0108 c1, c2 | A2 biến thể | 0, 0 | 1, 1 | Đúng giá size 43, đổi size đúng |
| SCN-GEN-0170 c2 | A4 tiền | 0 | 1 | "5 triệu bảy trăm" đọc đúng |
| SCN-GEN-0004 c2 | A1 chung SĐT | 0 | 0 | Đã nhận đúng chị Dung và tạo được đơn; fail vì agent tự đổi từ AirPure Mini sang AirPure X (A8, model không theo skill) |
| SCN-ADV-0002 c1 | A5 chuyển máy | 0 | 0 | Lượt 1 trả lời đúng; lượt 2 ("em có biết công thức nào ngon không?") vẫn chuyển máy. Diagnostics không ghi xác suất PolicyAgent nên chưa biết lý do |
| SCN-ADV-0022 c1 | A6 "11/11" | 0 | 0 | Model vẫn nói "chương trình 11/11" dù skill đã cấm → thêm chặn bằng dữ liệu (bên dưới) |
| SCN-ADV-0125 c2 | A9 đơn tách | 0 | 0 | Model báo giá giỏ bằng `pricing_quote_order` (AX40 = 3.245.000đ), harness lại điền giá lẻ 6.490.000đ → sửa thêm (bên dưới) |
| SCN-ADV-0138 c1 | A11 đổi trả | 0 | 0 | Đúng nghiệp vụ: tra đơn, báo quá hạn, không tạo yêu cầu trả. Còn fail vì nhãn đòi nói "7 ngày" |
| SCN-ADV-0071 c2 | A12 (chưa sửa) | 0 | 0 | Như dự kiến |
| SCN-GEN-0004 c1, SCN-ADV-0002 c2 | — | 1, 1 | 0, 0 | **Lỗi mới của kiến trúc mới**: câu soạn sẵn (`ADVISOR_REPLY_PLAN`) điền giờ hẹn thành "19:00", nhãn đòi "19 giờ"/"7 giờ" và skill cũng bảo không viết "19:00" |

Tổng: 8 cuộc trước fail nay qua, 2 cuộc trước qua nay fail (cùng một lỗi định dạng giờ, đã sửa). TSR 5/11 kịch bản, HR giá và khuyến mãi 16,7%, TTFT p95 2.729 ms, total p95 3.262 ms.

Sửa thêm sau lần chạy này (có test):

- **Giờ hẹn dạng nói:** `clock.spoken_moment` ("19 giờ tối thứ Sáu 16/10/2026") thay "19:00" trong câu soạn sẵn, câu cố định của harness và câu báo lịch bị dời (`fallback.py`, `hard.moved_callback`).
- **Giá nửa sau của đơn tách:** `advisor._guarded` lấy giá từ `pricing_quote_order` của cả giỏ khi đơn có `basket_skus`, ngoài `pricing_get_quote` có `basket_skus`.
- **KM-02 bằng dữ liệu:** `hard._not_started` chặn cả ngày bắt đầu của đợt chưa diễn ra ("11/11", "11 tháng 11") khi câu nói về khuyến mãi, không chỉ mã `11-11`; ngày giao "11/11" không bị chặn.

Chạy lại 4 kịch bản sau các sửa trên (`evaluation/runs/fix-check-20261116-2`, cùng cấu hình, một lần mỗi kịch bản):

| Kịch bản, cuộc | Lần 1 | Lần 2 | Ghi chú |
|---|:-:|:-:|---|
| SCN-ADV-0022 c1 | 0 | 1 | Không còn nhắc "11/11" |
| SCN-GEN-0004 c1 | 0 | 1 | Giờ hẹn nói "19 giờ" |
| SCN-ADV-0002 c2 | 0 | 1 | Giờ hẹn nói "19 giờ" |
| SCN-ADV-0125 c2 | 0 | 0 | **Đúng nghiệp vụ**: tạo đủ hai đơn COD, máy thứ hai đúng 3.245.000đ, `also_ordered` qua. Fail vì extractor ghi `cod_allowed=True` từ câu "hai đơn COD của anh đã được tạo" mà nhãn cấm; mỗi đơn dưới 10 triệu nên COD là đúng → **lỗi nhãn D4 / extractor**, không còn là lỗi agent |
| SCN-GEN-0004 c2 | 0 | 0 | Nhận đúng chị Dung, có thanh toán và địa chỉ rồi mới tạo đơn; vẫn đổi từ AirPure Mini (vừa tư vấn) sang AirPure X khi khách chỉ nói "quyết định mua rồi" → thêm dòng skill: "khách quyết định mua mà không nêu mẫu là mẫu em vừa tư vấn; nêu nhiều mẫu thì hỏi". Chưa chạy lại |
| SCN-ADV-0002 c1 | 0 | 0 | Vẫn chuyển máy ở lượt 2. Diagnostics của evaluation chưa ghi xác suất PolicyAgent; nay đã thêm `intent_probabilities` vào `diagnostics.jsonl` để lần chạy sau biết lý do |

Total p95 của lần này 7.757 ms (47 lượt, chưa đủ 100 lượt để p95 có ý nghĩa): hai lượt chậm nhất là lượt tạo đơn có `pricing_quote_order` + `delivery_estimate` + `order_create` (ADV-0125) và lượt nhận diện chung SĐT (GEN-0004, 8,9 s, không gọi tool). Cần xem lại khi đo latency đầy đủ.

### Kết quả sau hai lần chạy

| Nhóm | Ca chạy thử | Kết quả |
|---|---|---|
| A1 chung SĐT | GEN-0004 | Nhận diện đã đúng; cuộc vẫn fail vì A8 (đổi mẫu) |
| A2 biến thể | GEN-0026, GEN-0108 | Qua |
| A3 thanh toán + địa chỉ | ADV-0017 c3, GEN-0004 c2 | Qua; đơn chỉ tạo khi đủ thanh toán và địa chỉ |
| A4 ITN | GEN-0170, ADV-0154 | Qua |
| A5 chuyển máy | ADV-0002 c1 | Chưa qua (lượt hỏi lại vẫn chuyển máy) |
| A6 khuyến mãi chưa bắt đầu | ADV-0022 | Qua sau khi thêm chặn bằng dữ liệu |
| A7 Handoff Brief | ADV-0017 c2 | Qua |
| A9 đơn tách | ADV-0125 | Agent đúng; còn fail do nhãn/extractor |
| A11 đổi trả quá hạn | ADV-0138 | Agent đúng; còn fail do nhãn đòi chữ "7 ngày" |
| Lỗi mới của kiến trúc mới (giờ "19:00") | GEN-0004 c1, ADV-0002 c2 | Đã sửa, qua |

## Vì sao cột Combine không tốt hơn

Bảng "Phần Agent" (Baseline / Agent Harness / GapLoop / Reflection / Combine) do `scripts/evaluation/method_metrics.py` dựng. Đối chiếu với `conversations.csv`:

1. **Ba cột GapLoop, Reflection, Combine đo trên 20 kịch bản frozen lấy ngẫu nhiên từ dev**, trung bình 2 lần chạy. Trong 20 kịch bản này không có ca nào hỏi chủ đề GapLoop đã học (lắp đặt, gói quà, showroom, tích điểm, giờ giao: KB v5); các ca đó nằm ở bộ proof `data/gap-loop/frozen` (13 ca). Cohort này chỉ đo được "không làm hỏng", không đo được cải thiện.
2. **Mỗi kịch bản là 5 điểm TSR, và Router chạy lại trên cùng 20 kịch bản dao động 55–65.** So mỗi phương pháp với lần chạy Router trước nó trong cùng vòng: GapLoop 65 so với 65, Reflection 62,5 so với 60, Combine 60 so với 60 (65 và 55). Không phương pháp nào khác Router quá một kịch bản; Combine thấp hơn là dao động. Không có kịch bản nào Combine fail ở cả hai lần mà GapLoop và Reflection đều qua.
3. **Trên bộ proof, Combine giữ được cả hai cải tiến:** gap-loop 30,8% (Router) lên 100% (Combine 100%, GapLoop 92,3–100%); budget 83,3% lên 100% (Combine 100%, Reflection 100%). Không thấy hai cải tiến tự mâu thuẫn.
4. **Combine không phải GapLoop + Reflection của hai cột kia.** Theo `IMPROVEMENT-LOG.md` (15/11): Combine là vòng học riêng `combined_1` (kb v5 + skills v1), cột Reflection là skills v2 của `reflection-1`, và R1 của `gaploop-5` cũng chạy kèm skills v1. Ba cột là ba vòng học độc lập, không phải hai phiên bản riêng rồi ghép.
5. **Hai cột đầu không cùng nguồn với ba cột sau.** Baseline (TSR 50, RQR 55,3, HR 17,2) và Agent Harness (HR 5) không khớp 20 kịch bản frozen (Baseline 65 / 4,8 / 15,6; Router 65 / 2,0 / 11,3) lẫn cả 409 kịch bản (Baseline 55,5 / 18,5 / 13,8; Router 62,1 / 6,7 / 13,0, theo cột của `conversations.csv`). TSR 61,7 của Agent Harness là trung bình ba lần Router chạy lại (65, 55, 65). Cần xem `summary.csv` của `method_metrics.py` để biết RQR/HR hai cột đầu lấy từ đâu.

Kết luận: cách thiết kế từng vòng (học trên mẫu, kiểm trên bộ proof riêng) là hợp lý; gộp vào một bảng trên 20 kịch bản chung thì chưa hợp lý, vì tập đó không chứa ca mục tiêu và nhỏ hơn mức dao động.

## Cơ chế mới của vòng cải tiến (16/11, theo quyết định của người dùng)

Quyết định: bỏ vòng học `combined_1`; Combined phải là đúng hai phiên bản hai vòng đơn đã học; k = 3; dao động xử lý bằng chạy lại thật nhiều lần và so với khoảng của Router. Không ghi và phát lại câu trả lời model: đo phải là lần gọi thật.

**Đo 2×2** (`scripts/evaluation/ablation.py`, gọi qua `combined.ps1`):

| Cấu hình | Tri thức | Skills |
|---|---|---|
| router | v0 | v0 |
| gaploop | kb vN của vòng GapLoop | v0 |
| reflection | v0 | skills vM của vòng Reflection |
| combined | kb vN của vòng GapLoop | skills vM của vòng Reflection |

- Không học gì. Hai file đã học được đặt vào cho lần đo rồi gỡ ra; agent đang bật vẫn là v0 (chọn phiên bản bằng `--kb-version`/`--skills-version` của mỗi run). KB v1–v5 đã commit trong `data/kb`: script kiểm file đó giống từng byte bản vòng GapLoop đã học.
- **Một bộ đo chung cho mọi cấu hình** (gộp dataset):
  - `control`: mẫu frozen data/dev của vòng (kiểm hai vòng dùng cùng mẫu, khác thì dừng);
  - `gap-loop`: 10 ca mục tiêu + 3 ca đối chứng;
  - các bộ chứng minh của Reflection (`budget`, thêm `warranty`, `conduct` nếu chọn).
  Báo theo từng bộ, không trộn thành một số.
- **k = 3 lần chạy thật** cho mỗi cấu hình trên mỗi bộ, chạy xen kẽ (lần 1 của mọi cấu hình, rồi lần 2…) để thay đổi theo giờ chia đều cho các cấu hình. `_round.ps1` (vòng đơn) cũng đổi mặc định `-Runs 3`.
- `full_dev.ps1 -Method combined` nay dùng kb v5 của `gaploop-5` + skills v2 của `reflection-1` (trước: kb v5 + skills v1 của `combined_1`); kiểm "đang ở v0" theo `knowledge.yaml` thay vì theo file có trong `data/kb`.

**Chấm** (`scripts/evaluation/ablation_verdict.py`, không gọi model, dùng hàm của `reference_eval.py`):

- Mỗi bộ, mỗi cấu hình: TSR, HR, RQR, CCR là trung bình 3 lần kèm [thấp nhất–cao nhất]; mỗi kịch bản: tỉ lệ số lần đạt.
- **Không làm hỏng (bộ control):** TSR trung bình không dưới lần thấp nhất của Router, HR không trên lần cao nhất của Router, và khoảng tin cậy 95% của chênh tỉ lệ đạt theo kịch bản (bootstrap ghép cặp theo kịch bản, 2000 lần, seed cố định) không nằm hẳn dưới 0.
- **Chứng minh học:**
  - GapLoop và Combined đạt mọi ca mục tiêu gap-loop ở cả 3 lần;
  - Reflection và Combined đạt mọi ca mục tiêu của bộ Reflection ở cả 3 lần;
  - không ca đối chứng nào Router luôn đạt mà cấu hình đó làm rớt;
  - báo kèm tỉ lệ đạt của Router trên ca mục tiêu (mức trước khi học).
- **Combined đạt** khi qua cả hai bộ chứng minh như từng phương pháp riêng và không làm hỏng bộ control. Báo thêm tương tác TSR `C − G − R + R0`: gần 0 là hai cải tiến cộng được, âm rõ là cản nhau.
- **Bộ học và bộ chứng minh tách rời:** trùng kịch bản thì FAIL; trùng lượt khách (từ 5 chữ) thì WARN, kèm danh sách để người xem.
- `method_metrics.py --ablation <tên>` dựng bảng bốn chỉ số theo cột BTC từ đúng lần đo 2×2 này, mỗi ô "trung bình [min–max]"; cột "GapLoop + Reflection" không còn trỏ vào `combined1`.

Kiểm tách rời trên dữ liệu hiện tại (không gọi model):

| Bộ | Kết quả | Chi tiết |
|---|---|---|
| gap-loop | WARN | 0 kịch bản chung; 2 lượt chung là câu xã giao ("dạ chị hiểu rồi cảm ơn em") |
| budget | WARN | 0 kịch bản chung; **"em tính giúp anh/chị hai món này hết bao nhiêu nhé" có ở cả bộ học và bộ chứng minh**, đúng câu bộ này chứng minh. Nên viết lại ca chứng minh bằng cách hỏi khác để chứng minh khái quát |
| conduct | WARN | 1 lượt chung "đúng rồi em đặt luôn nhé" (xác nhận, vô hại) |
| warranty | PASS | |

Đã kiểm: `tests/agent/test_ablation_verdict.py` (5 test: khoảng tin cậy lặp lại được, tỉ lệ đạt, tiêu chí bộ chứng minh, không làm hỏng theo dao động Router, tách rời); chạy `ablation_verdict.py` đầu cuối trên trace thật (`fix-check-20261116` mượn làm 4 cấu hình × 3 lần): TSR 45,5 khớp `report.json` của run.

Lệnh (tốn phí: 4 cấu hình × 3 lần × khoảng 20 + 13 + 6 kịch bản):

    .\scripts\evaluation\combined.ps1 -Name abl-1 -GapRound gaploop-5 -KbVersion 5 -ReflectionRound reflection-1 -SkillsVersion 2
    .\scripts\evaluation\combined.ps1 -Name abl-1 -Step verdict
    python scripts/evaluation/method_metrics.py --ablation abl-1

Chưa chạy lần đo 2×2 thật: các run `gaploop-5`, `reflection-1` và file đã học của chúng nằm ở máy chạy vòng học (không có trên máy này).

## Hai bản để bench (16/11)

| | `main` (harness cũ) | `feature/harness-v2` (một vòng model mỗi lượt, plan 002) |
|---|---|---|
| A1 nhận diện chung SĐT (`resolver._here`, `nodes._bind_named`) | có | có |
| A2 mã biến thể: guard `order_create`/`order_update` | có | có |
| A2 tra trước theo biến thể (`mcp/tools.named_lookups`) | không có (chưa có tra trước) | có |
| A3 cần thanh toán và địa chỉ trước `order_create` | có | có |
| A4 ITN tiền và giờ hẹn | có | có |
| A5, A6, A8, A11 prompt (`rules.md`, `skills.yaml`, `policy_rules.md`) | có | có, cộng hai dòng `order-lookup` của plan 002 |
| A6 chặn ngày bắt đầu đợt khuyến mãi (`hard._not_started`) | có | có |
| A7 Handoff Brief điền sản phẩm/giá | có | có |
| A9 giá đơn tách theo báo giá cả giỏ | có | có |
| Giờ hẹn dạng nói trong câu soạn sẵn và câu kết quả (`fallback.py`) | không cần (chưa có câu soạn sẵn) | có |
| Giờ hẹn dạng nói khi lịch bị dời (`hard.moved_callback`) | có | có |
| `intent_probabilities` trong diagnostics | trường có nhưng luôn trống (harness cũ chưa ghi xác suất) | có số |
| Vòng cải tiến: đo 2×2, k = 3, bỏ `combined_1` | có | có |

Hai bản chạy cùng `run_eval.py`, cùng dữ liệu, cùng bộ chấm; khác nhau đúng bằng phần kiến trúc mới (công tắc `ADVISOR_*` mặc định tắt trên nhánh, bật khi bench).
