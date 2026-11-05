# seed-dev: lỗi bộ test cần người tạo dữ liệu sửa

Dành cho người duy trì `evaluation/data-generation` và `data/seed-dev`. Tài liệu này chỉ nói về **bộ test**, không nói về agent. Mọi phát hiện được kiểm offline trên toàn bộ 400 kịch bản ngày 05/11/2026, không gọi model. Danh sách đầy đủ từng cuộc nằm ở phụ lục.

Quy tắc khi sửa: theo [`evaluation/datasets/ground-truth-review/SKILL.md`](../../evaluation/datasets/ground-truth-review/SKILL.md). Tạo revision mới (ví dụ `data/seed-dev-r2/`), **không ghi đè `data/seed-dev`** vì đã có run dùng nó; ghi từng trường đã đổi, nguồn và hash; nhãn chưa có người duyệt vẫn là diagnostic.

## 1. Phần đã đúng (không cần sửa)

| Phép kiểm | Kết quả |
|---|---|
| Giá trong `success_if.args_match` của `order.create`, tính lại bằng `mock_tools.pricing_get_quote` của BTC theo ngày gọi | 233/235 khớp; 2 lệch (`SCN-ADV-0024/call_2`, `SCN-ADV-0119/call_2`) là khuyến mãi một lần đã dùng ở cuộc trước, nên lệch là đúng |
| `ground_truth_facts.order_status`, `tracking` so với `crm_seed*.json` | 37/37, 20/20 |
| `must_carry_over`: slot có được cung cấp ở `seed_history` hoặc `facts_established` của cuộc trước | 2.251/2.251 |
| Cụm `must_say_any` có số: số có trong chính sách, catalog, khuyến mãi hoặc `ground_truth_facts` | 327/333; 6 cuộc còn lại là tổng giỏ tự tính (hợp lý) |
| Kênh, SKU, trạng thái đơn trong `seed_history` so với CRM | khớp (bộ v4 cũ lệch 31 tham chiếu; seed-dev không lệch) |

## 2. Lỗi cần sửa, theo mức độ

### 2.1 [Cao] 74 cuộc `order.create` bị cắt mất câu xác nhận cuối của khách

- `conversations/scenarios_<ID>/<call>.json` (hội thoại mẫu) có thêm 1–2 câu khách ở cuối, kiểu "Đúng rồi em, lên đơn giúp chị nhé", "Ừ đúng rồi em.". `customer_turns` (71 cuộc) hoặc `customer_turns_asr` (3 cuộc) trong `scenarios/<ID>.json` **không có** câu đó; phần còn lại giống hệt.
- Hệ quả: nhãn vẫn đòi `order.create`, nhưng khách không bao giờ nói đồng ý sau câu đọc lại. Agent làm đúng PB-09 (đọc lại rồi chờ) vẫn bị chấm trượt.
- Ví dụ `SCN-ADV-0014/call_1`: hội thoại mẫu có 5 câu khách, câu cuối "Đúng rồi em, chị xác nhận đặt hàng."; kịch bản chỉ có 4.
- Gợi ý nguyên nhân (chưa xác minh): `src/planning/call_kinds.py` (quanh dòng 187) yêu cầu hội thoại có câu xác nhận "đúng rồi em", nhưng bước xuất kịch bản không đồng bộ lại `customer_turns` từ hội thoại.
- **Sửa:** trong revision mới, nối câu thiếu vào `customer_turns` (và bản tương ứng vào `customer_turns_asr` nếu cuộc có ASR). Sửa bước xuất để không lặp lại.
- Cách tái hiện: so `[t["text"] for t in conv["turns"] if t["speaker"] == "customer"]` với `customer_turns`; lệch kiểu "kịch bản là tiền tố của hội thoại".

### 2.2 [Cao] 26 cuộc đòi `order.create` mà khách không hề đồng ý mua

- Kể cả sau khi khôi phục mục 2.1, lời khách của 26 cuộc không có câu đồng ý nào; vài cuộc còn nói ngược lại. Ví dụ `SCN-ADV-0028/call_1` kết thúc bằng "Chị cần suy nghĩ thêm một chút trước khi chốt đơn.", nhưng nhãn đòi `order.create`.
- Hệ quả: nhãn mâu thuẫn với lời khách. Agent tạo đơn ở đây là tạo đơn khi khách chưa đồng ý (sai nghiệp vụ); agent không tạo thì bị chấm trượt.
- **Sửa:** với từng cuộc, chọn một: (a) thêm câu đồng ý nếu ý đồ kịch bản là chốt đơn; (b) đổi nhãn sang `hen_goi_lai`/`tool_called: null` (hoặc `schedule.callback`) nếu ý đồ là khách chưa quyết. Cần người duyệt quyết định.
- Danh sách ở phụ lục B (phát hiện bằng regex câu đồng ý; nên rà tay).

### 2.3 [Cao] Kiểm "oracle hoàn hảo" không chứng minh nhãn đúng

- `reports/ground_truth_summary.json` ghi `oracle_perfect: true`, nhưng trace oracle (`trace_log/`) được dựng từ chính nhãn, nên luôn đạt.
- Trace oracle có câu chèn nguyên văn để khớp cụm bắt buộc (ví dụ `SCN-ADV-0014/call_1`: agent nói "Dạ gọi xác nhận ạ." ở lượt 2), và gọi `order.create` ở lượt khách nói "ngân sách khoảng 5 triệu rưỡi", không có câu đọc lại (trái PB-09).
- **Sửa:** không dùng `oracle_perfect` làm bằng chứng nhãn đúng. Nên có phép kiểm: dựng trace oracle từ **hội thoại mẫu** (`conversations/`) chứ không từ nhãn, và chấm trace đó bằng `reference_eval.py`; cuộc trượt là cuộc có nhãn hoặc lời khách cần xem.

### 2.4 [Trung bình] Nhãn chưa được duyệt

- `review/needs_manual_review.csv`: 243 mục trong 155 kịch bản; cột `approve` trống ở cả 243.
- 135 mục `judge_requested_manual_review`; 34 cuộc có `FAIL J02_no_fabrication` (hội thoại mẫu nói điều không có nguồn, nên `must_say_any` rút từ đó có thể sai); 32+ `J03_conflict_handling`.
- **Sửa:** duyệt ít nhất 34 cuộc J02 trước (phụ lục C), vì đây là chỗ nhãn có thể chứa thông tin bịa.

### 2.5 [Trung bình] Khoá `say_at_most` không được bộ chấm BTC hỗ trợ

- 3 cuộc dùng `success_if.say_at_most` (phụ lục D). `reference_eval.py` (`check_call`) không đọc khoá này nên bỏ qua im lặng: tiêu chí đó không bao giờ được chấm.
- **Sửa:** đổi sang khoá BTC hỗ trợ (`forbidden_claims` dạng chuỗi, `max_agent_questions`…), hoặc ghi rõ là diagnostic ngoài BTC.

### 2.6 [Trung bình] Ngày phiên cũ sau ngày cuộc gọi

- `SCN-GEN-0080`, `SCN-GEN-0146`: `call_1` ngày 2026-10-05 nhưng `seed_history` có phiên/đơn ngày 2026-10-10 (0080) và 2026-10-08 (0146). Runner từ chối hai kịch bản này.
- Cùng persona `khach_da_kenh_mau_thuan`, biến thể `ba_kenh_lech_gia`; nên rà các kịch bản cùng loại.

### 2.7 [Thấp] Kênh phiên cũ dùng tên CRM `fb`

- 60 kịch bản có `seed_history[].channel = "fb"`, không thuộc tên kênh của `scenario_format.md` (`hotline`, `zalo_oa`, `chat_fanpage`, `web_chat`). Runner của đội đã thêm ánh xạ `fb → facebook`; bộ chấm hoặc runner khác có thể từ chối.
- **Sửa (khuyến nghị):** dùng tên kênh của `scenario_format.md` trong kịch bản.

### 2.8 [Thấp, để biết] Cụm bắt buộc chỉ có dạng số

- 143 cuộc có `must_say_any` mà mọi lựa chọn đều là chữ số ("4.890.000", "19 giờ"). Không sai, nhưng agent đọc số bằng chữ ("bốn triệu…") sẽ trượt. Nên thêm cách viết khác nếu muốn nhãn bền hơn.
- `callback_at` trong nhãn không có múi giờ (87/87). Giữ nguyên; phía hệ thống sẽ chuẩn hoá cho khớp.

## 3. Đề nghị thứ tự

1. 2.1 và 2.2 (chặn trực tiếp `order.create`, 235 cuộc trong bộ test).
2. 2.4 (34 cuộc J02).
3. 2.5, 2.6, 2.7.
4. Thêm phép kiểm 2.3 vào pipeline sinh dữ liệu để các lỗi trên tự lộ ra lần sau.

Khi xong, xuất `data/seed-dev-r2/` kèm `conversion-report.json` và `DISPUTES.md`; đội agent sẽ chạy lại trên r2 và báo riêng phần điểm đổi do bộ test.

## Phụ lục

### A. 74 cuộc bị cắt câu xác nhận

| Cuộc | Trường | Câu bị thiếu |
|---|---|---|
| SCN-ADV-0005/call_2 | `customer_turns` | Đúng rồi em, lên đơn cho chị nhé. |
| SCN-ADV-0013/call_1 | `customer_turns` | Đúng rồi em, lên đơn giúp anh nhé. |
| SCN-ADV-0014/call_1 | `customer_turns` | Đúng rồi em, chị xác nhận đặt hàng. |
| SCN-ADV-0024/call_1 | `customer_turns` | Vâng đúng rồi em. |
| SCN-ADV-0024/call_2 | `customer_turns` | Ừ đúng rồi em. |
| SCN-ADV-0026/call_2 | `customer_turns` | Ừ, đúng rồi. |
| SCN-ADV-0027/call_2 | `customer_turns` | Dạ đúng rồi em, cảm ơn em. |
| SCN-ADV-0037/call_2 | `customer_turns` | Anh xác nhận đúng rồi em nhé. |
| SCN-ADV-0038/call_2 | `customer_turns` | Vâng, chị xác nhận nhé. |
| SCN-ADV-0039/call_1 | `customer_turns` | Đúng rồi, lên đơn cho chị luôn nhé. |
| SCN-ADV-0050/call_2 | `customer_turns` | Vâng, đúng rồi em. |
| SCN-ADV-0056/call_2 | `customer_turns` | Ừ đúng rồi em. |
| SCN-ADV-0074/call_1 | `customer_turns` | Đúng rồi em, lên đơn giúp anh nhé. |
| SCN-ADV-0075/call_1 | `customer_turns` | Chị xác nhận đủ thông tin rồi em nhé. |
| SCN-ADV-0079/call_2 | `customer_turns` | Chị đồng ý. |
| SCN-ADV-0098/call_2 | `customer_turns_asr` | dung roi em |
| SCN-ADV-0100/call_2 | `customer_turns` | Vâng, đúng rồi em. |
| SCN-ADV-0109/call_1 | `customer_turns` | Đúng rồi em. |
| SCN-ADV-0116/call_2 | `customer_turns_asr` | u dung roi chau len don cho co nhe |
| SCN-ADV-0119/call_1 | `customer_turns` | Đúng rồi em. |
| SCN-ADV-0119/call_2 | `customer_turns` | Ừ, đúng rồi em. |
| SCN-ADV-0122/call_2 | `customer_turns` | Đúng rồi em, lên đơn cho chị nhé. |
| SCN-ADV-0132/call_2 | `customer_turns` | Đúng rồi em, lên đơn giúp anh nhé. |
| SCN-ADV-0133/call_2 | `customer_turns` | Đúng rồi em, lên đơn giúp anh nhé. |
| SCN-ADV-0134/call_1 | `customer_turns` | Ừ đúng rồi, em lên đơn luôn nhé. |
| SCN-ADV-0140/call_1 | `customer_turns` | Vâng, đúng rồi em. |
| SCN-ADV-0145/call_2 | `customer_turns` | Vâng, đúng rồi em. |
| SCN-ADV-0148/call_2 | `customer_turns_asr` | dong y |
| SCN-GEN-0001/call_1 | `customer_turns` | Đúng rồi em, chị chốt đơn nha. |
| SCN-GEN-0003/call_3 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0004/call_2 | `customer_turns` | Ừ đúng rồi em. |
| SCN-GEN-0005/call_2 | `customer_turns` | Đúng rồi em, em đặt đơn giúp chị nhé. |
| SCN-GEN-0022/call_2 | `customer_turns` | Đúng rồi em, đặt giúp anh nhé. |
| SCN-GEN-0036/call_2 | `customer_turns` | Ừ đúng rồi em. |
| SCN-GEN-0039/call_2 | `customer_turns` | Ừ đúng rồi em. |
| SCN-GEN-0047/call_2 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0048/call_1 | `customer_turns` | Ừ đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0061/call_2 | `customer_turns` | Ừ, đúng rồi em. |
| SCN-GEN-0067/call_2 | `customer_turns` | Chị đồng ý nhé. |
| SCN-GEN-0081/call_2 | `customer_turns` | Ừ, đúng rồi em. |
| SCN-GEN-0082/call_1 | `customer_turns` | Đúng rồi em, cảm ơn nhé. |
| SCN-GEN-0083/call_2 | `customer_turns` | Ừ, lên đơn giúp chị luôn nhé. |
| SCN-GEN-0090/call_1 | `customer_turns` | Đúng rồi em, lên đơn cho chị nhé. |
| SCN-GEN-0099/call_2 | `customer_turns` | Vâng, đúng rồi em. |
| SCN-GEN-0102/call_2 | `customer_turns` | Đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0114/call_3 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0116/call_1 | `customer_turns` | Đúng rồi em, lên đơn cho chị nhé. |
| SCN-GEN-0117/call_2 | `customer_turns` | Anh xác nhận nhé. |
| SCN-GEN-0122/call_2 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0130/call_3 | `customer_turns` | Vâng, đúng rồi. |
| SCN-GEN-0132/call_1 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0143/call_2 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0146/call_3 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0155/call_2 | `customer_turns` | Đúng rồi em. / Cảm ơn em nhé. |
| SCN-GEN-0156/call_2 | `customer_turns` | Ừ, đúng rồi em. |
| SCN-GEN-0164/call_3 | `customer_turns` | Đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0165/call_2 | `customer_turns` | Đúng rồi, em lên đơn giúp chị nhé. |
| SCN-GEN-0167/call_2 | `customer_turns` | Đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0177/call_2 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0182/call_1 | `customer_turns` | Đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0183/call_2 | `customer_turns` | Vâng, đúng rồi em nhé. |
| SCN-GEN-0192/call_3 | `customer_turns` | Đúng rồi, em lên đơn đi. |
| SCN-GEN-0196/call_3 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0205/call_2 | `customer_turns` | Ừ, đúng rồi em. |
| SCN-GEN-0208/call_1 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0214/call_3 | `customer_turns` | Đúng rồi, thông tin như vậy là chính xác. |
| SCN-GEN-0216/call_1 | `customer_turns` | Dạ, đúng rồi em. |
| SCN-GEN-0227/call_2 | `customer_turns` | Anh xác nhận đúng rồi em. |
| SCN-GEN-0230/call_3 | `customer_turns` | Anh xác nhận, lên đơn giúp anh nhé. |
| SCN-GEN-0233/call_2 | `customer_turns` | Đúng rồi em, lên đơn giúp chị nhé. |
| SCN-GEN-0238/call_2 | `customer_turns` | Đúng rồi em. |
| SCN-GEN-0247/call_2 | `customer_turns` | Dạ đúng rồi em. / Cảm ơn em nha. |
| SCN-GEN-0248/call_1 | `customer_turns` | Ừ, em đặt luôn giúp chị nhé. |
| SCN-GEN-0249/call_2 | `customer_turns` | Đúng rồi em, em lên đơn nhé. |

### B. 26 cuộc đòi `order.create` mà lời khách không có câu đồng ý

| Cuộc | Câu khách cuối |
|---|---|
| SCN-ADV-0023/call_1 | Chị chờ cuối tháng này nhận lương rồi thanh toán qua ngân hàng nhé. |
| SCN-ADV-0028/call_1 | Chị cần suy nghĩ thêm một chút trước khi chốt đơn. |
| SCN-ADV-0036/call_2 | Địa chỉ giao hàng là Lê Chân, Hải Phòng. |
| SCN-ADV-0045/call_1 | Khu vực giao hàng là Cầu Giấy, Hà Nội, em có thể giao được không? |
| SCN-ADV-0059/call_2 | Cảm ơn em, anh sẽ đợi hàng. |
| SCN-ADV-0064/call_2 | mong la quat nay se giao nhanh cho anh |
| SCN-ADV-0082/call_2 | co cam on chau mong nhan hang som |
| SCN-ADV-0115/call_2 | Em làm đơn cho chị luôn đi. |
| SCN-ADV-0131/call_2 | Khu vực giao hàng là Lê Chân, Hải Phòng. |
| SCN-GEN-0017/call_2 | Anh muốn trả bằng tiền mặt khi giao hàng. |
| SCN-GEN-0034/call_2 | khu vuc giao hang la cau giay ha noi |
| SCN-GEN-0055/call_2 | Em làm đơn giúp cô nhé. |
| SCN-GEN-0077/call_2 | Mong là sẽ nhận được hàng sớm! |
| SCN-GEN-0086/call_2 | Em ghi đơn cho chị nhé. |
| SCN-GEN-0092/call_3 | Mong sớm nhận được hàng. |
| SCN-GEN-0093/call_2 | Mong là hàng sẽ đến nhanh chóng. |
| SCN-GEN-0117/call_2 | Anh xác nhận nhé. |
| SCN-GEN-0136/call_2 | Mong là hàng sẽ giao nhanh cho anh. |
| SCN-GEN-0148/call_1 | Xác nhận lại địa chỉ giao hàng giúp chị với nhé. |
| SCN-GEN-0181/call_2 | Khu vực giao hàng là Cần Thơ, cho cô biết khi nào được giao nhé. |
| SCN-GEN-0197/call_2 | Làm ơn giúp chị làm đơn hàng này đi. |
| SCN-GEN-0202/call_2 | Làm đơn cho chị luôn đi em. |
| SCN-GEN-0211/call_2 | Mong là giao hàng nhanh nhé! |
| SCN-GEN-0217/call_2 | Giao hàng cho chị ở Cầu Giấy, Hà Nội nhé. |
| SCN-GEN-0236/call_2 | Ngân sách giờ là 2.900.000đ em ạ. |
| SCN-GEN-0242/call_3 | Nhớ ghi rõ là chị đã gọi xác nhận rồi. |

### C. 34 cuộc có `FAIL J02_no_fabrication`

SCN-ADV-0046/call_1, SCN-ADV-0060/call_1, SCN-ADV-0065/call_1, SCN-ADV-0107/call_1, SCN-GEN-0008/call_1, SCN-GEN-0030/call_2, SCN-GEN-0035/call_2, SCN-GEN-0068/call_1, SCN-GEN-0080/call_2, SCN-GEN-0101/call_2, SCN-GEN-0108/call_2, SCN-GEN-0111/call_1, SCN-GEN-0118/call_1, SCN-GEN-0123/call_1, SCN-GEN-0135/call_2, SCN-GEN-0140/call_1, SCN-GEN-0158/call_2, SCN-GEN-0169/call_1, SCN-GEN-0169/call_2, SCN-GEN-0174/call_1, SCN-GEN-0174/call_2, SCN-GEN-0180/call_2, SCN-GEN-0184/call_1, SCN-GEN-0184/call_2, SCN-GEN-0197/call_2, SCN-GEN-0201/call_1, SCN-GEN-0201/call_2, SCN-GEN-0208/call_2, SCN-GEN-0229/call_1, SCN-GEN-0234/call_1, SCN-GEN-0235/call_1, SCN-GEN-0235/call_2, SCN-GEN-0245/call_1, SCN-GEN-0250/call_1

### D. 3 cuộc dùng `say_at_most`

SCN-ADV-0031/call_1, SCN-ADV-0060/call_1, SCN-ADV-0126/call_1
