# 003. Mỗi lượt một bước nghiệp vụ, một vòng model

| | |
|---|---|
| Trạng thái | đã duyệt (24/11/2026) |
| Người phụ trách | |
| Ngày tạo | 2026-11-24 |
| Loại | tool / action guard / hard guard / playbook (skills) |
| Chỉ số mục tiêu | latency (TTFT p95 ≤ 3 s, Total p95 ≤ 8 s), TSR giữ nguyên |

Plan 002 lo **cơ chế** để một lượt có tool ghi chỉ cần một vòng model. Plan này lo phần **nghiệp vụ**: một cuộc gọi là nhiều lượt, mỗi lượt khách nói ứng với đúng một bước nghiệp vụ. Bảng ở mục 3.2 ghi, cho từng bước: harness phải có sẵn dữ liệu gì trước vòng model, model làm gì, tool ghi nào chạy, ai nói kết quả, và TTFT tính ở đâu.

## 1. Vấn đề

Một lượt đang tốn 2–4 vòng model, vì harness và tool của ta dồn vào một lượt những việc thuộc nhiều lượt, hoặc trả việc về cho model:

- **Tool ghi bị trả về vì luật riêng của ta, không phải của BTC.** Ví dụ `order_create` đòi phải có địa chỉ và phải có `quote_order` ngay trong lượt.
- **Biến thể chưa được tra** khi khách đã nói size và màu, nên model gọi `order_update`, bị trả về, đi tra, rồi gọi lại.
- **Guard chặn câu đúng.** Câu viết trước lời gọi tool bị phán trước khi tool chạy. Kết quả tool của lượt trước không được tính. Số tiền chỉ được so với đoạn tài liệu vừa truy xuất.
- **Câu dẫn bị tính là TTFT.** Model nói "dạ em kiểm tra" trước khi tra, và câu đó bị đếm như câu trả lời.

## 2. Bằng chứng

Run `evaluation/runs/fix-check-20261116` và `fix-check-20261116-2` (`gpt-5.6-luna`, bật các công tắc `ADVISOR_*`), 175 lượt. Hai run này chạy trước commit 39a22b81 (18/11), nên lỗi đòi địa chỉ trong bảng dưới đã được sửa; các lỗi còn lại vẫn còn trong code hiện tại (mục 3.3):

| Số vòng model | Số lượt | TTFT p95 | Lượt TTFT > 3 s |
|---|---|---|---|
| 1 | 121 | 2,13 s | 0 |
| 2 | 44 | 3,91 s | 7 |
| 3–4 | 10 | 3,6–4,8 s (Total tới 9 s) | 5 |

| Lượt | Số vòng | Vì sao |
|---|---|---|
| SCN-ADV-0125 call_2 t3, khách xin tách đơn COD | 4 | `order_create` bị trả về: "Còn thiếu địa chỉ giao… hỏi khách rồi mới gọi `order_create`". Sau đó guard chặn câu "em sẽ tách thành 2 đơn", phải sinh lại |
| SCN-ADV-0125 call_2 t4, khách cho địa chỉ | 2 | Vòng 1 model tự gọi `quote_order` và `delivery.estimate`; vòng 2 mới gọi `order_create` |
| SCN-GEN-0108 call_2 t3, "đổi sang size 42 màu đen" | 3 | `order_update` bị trả về vì mã biến thể chưa xuất hiện trong kết quả tool. Vòng 2 đi tra, vòng 3 gọi lại |
| 10 lần guard chặn rồi sinh lại câu | +1 mỗi lần | 8/10 chặn sai do cơ chế (mục 3.4); 2/10 đúng: nhắc "11/11" (KM-02), và khẳng định "còn hạn trả hàng" khi chưa có dữ liệu đơn |

**BTC làm thế nào.** Trace mẫu `data/btc/eval/runs/full.jsonl`:
- Tạo đơn ngay ở câu chốt: SAMPLE-01, 02, 04, 05, 06, đều không có địa chỉ.
- `order.update` ở lượt khách nói "làm thủ tục đổi cho anh nhé" (SAMPLE-03), tức là sau lượt khách hỏi đổi.
- `mock_tools.order_create`: địa chỉ không bắt buộc, `payment` mặc định là COD.

## 3. Giải pháp

### 3.1 Quyết định (24/11/2026)

1. **Một lượt khách, một bước nghiệp vụ.**
   - Khách **hỏi** ("đổi được không", "giá bao nhiêu"): agent trả lời và, khi cần, hỏi khách chốt. Không ghi gì.
   - Khách **chốt hoặc ra lệnh** ("lên đơn đi", "làm thủ tục đổi cho anh", "đúng rồi em"): agent làm đúng một việc ghi.
2. **Một vòng model mỗi lượt. Model quyết, tool tự điền, harness không đoán.**
   - Model chọn tool và soạn sẵn câu trả lời có chỗ trống (plan 002 cho tool ghi; plan này mở rộng sang tool tra cứu có kết quả dạng cố định).
   - Tool chạy, **tự điền và tự nối** những gì nó cần. Ví dụ: `order_create` tự báo giá đơn; `catalog_search` tự nối giá và tồn kho của mẫu khớp. Nối dựa trên kết quả tool, không dựa trên lời khách.
   - Harness điền số vào câu, đưa qua guard, rồi nói. Vòng hai chỉ là đường lui khi câu không dùng được (kết quả mở, nhãn lạ); mỗi lần dùng đều được đếm.
3. **Bỏ prefetch theo chữ khách.** Bỏ `named_lookups`, `need_search`, nhánh đoán nhu cầu, `ADVISOR_PREFETCH`, và tra trước đơn đang chốt (thừa khi `order_create` tự điền).
   - Module nhận diện thực thể (`components/intake/commerce.py`) rời khỏi luồng chạy của agent.
   - Module này chỉ còn dùng cho evaluation: Entity Accuracy của ASR, bộ trích CCR.
   - Phần trích `seed_history` không còn khớp chữ; sản phẩm nằm trong summary, Call Brief hiện ra.
4. **Tool không trả việc về cho model khi tự làm được.** Chỉ trả lỗi khi cần khách quyết, ví dụ hết hàng hay vượt hạn mức COD.
5. **Giữ phần dựa trên trạng thái.** Call Brief làm mới giá và tồn kho của sản phẩm đã tư vấn lúc nối máy (rule 5 của hướng dẫn latency).
6. **TTFT.**
   - Lượt có câu soạn sẵn: TTFT là lúc harness nói câu đó (sau khi tool xong).
   - Lượt không gọi tool: token đầu của model.
   - Câu dẫn ("dạ em kiểm tra") không tính vào TTFT, chỉ tính cho TTFA.

### 3.1b Trường `say` và mẫu câu theo kết quả (chốt 24/11/2026)

- **Mọi tool có trường `say`**, là thuộc tính đầu tiên, `null` khi không cần. Model điền lời của nó vào đó:
  - **bắt buộc** khi trong lượt khách hỏi thêm điều khác ngoài việc của tool: trả lời bằng dữ kiện đã có trong cuộc hoặc tài liệu;
  - một câu xin lỗi ngắn khi khách đang bực;
  - không nói kết quả của chính tool đó.
- **Harness nói `say` trước, rồi câu mẫu theo kết quả tool.** Câu mẫu cố định theo từng nhãn kết quả (lấy từ `mock_tools.py`), điền số từ kết quả tool, xưng hô và tên từ Call Brief.
- **Câu mẫu không qua guard**, vì số lấy thẳng từ kết quả tool. **`say` qua guard** như mọi câu model viết.
- **Kết quả mở được đóng lại bằng tool của ta**:
  - tư vấn theo nhu cầu: `product_advise` xếp hạng theo diện tích, khóa trẻ em, ngân sách (`mcp/tools.py`, `_fit`); câu mẫu nói mẫu số 1 kèm lý do khớp;
  - nhiều đơn, biến thể hết hàng: câu mẫu liệt kê tối đa 3 rồi hỏi khách chọn; khách chọn ở lượt sau.
- **Vòng 2 có đếm** chỉ còn cho so sánh nhiều mẫu theo đặc điểm, khi khách hỏi so sánh.

**Bench 24/11** (`workbench/latency/bench_say_field.py`, local, không commit; log `say-field.log`, `say-field-2.log`):
- Model `gpt-5.6-luna`, `reasoning_effort` none, mock BTC.
- Prompt cache đã ấm (một lần gọi khởi động mỗi ca và biến thể), 2 lần đo mỗi ô.
- Tool chạy trên mock, gần 0 ms; trên MCP thật cộng 10–400 ms.
- Chưa tính guard của `say`.

| Ca | Không có `say`: TTFT | Có `say`: TTFT | Khách nghe (biến thể có `say`) |
|---|---|---|---|
| Khách đồng ý sau khi đọc lại đơn | 1,87 s | 1,40 s | Câu mẫu tạo đơn: mã, tổng, ngày giao, nhân viên gọi xác nhận |
| Đồng ý và hỏi "có quà không" | 1,63 s (câu hỏi bị bỏ qua) | 1,32 s (`say` xong), câu mẫu ở 1,57 s | "Dạ em kiểm tra, đơn này không có quà tặng kèm ạ." rồi câu mẫu. Đúng: GIFT-FILTER hết hạn 22/10 |
| Khách bực vì giao chậm | 1,33 s | 1,23 s | Câu xin lỗi rồi trạng thái đơn và mã vận đơn |
| Hỏi "đơn của chị" khi có 2 đơn | 1,18 s | 1,14 s | Liệt kê 2 đơn rồi hỏi khách hỏi đơn nào |
| Nhu cầu: 25 m², bé 2 tuổi, tầm 5,5 triệu | 1,47 s | 1,23 s | AirPure Y, phòng tới 30 m², có khóa trẻ em, 5.200.000đ |
| Cùng ca nhu cầu nhưng đi vòng 2 | | 2,91–3,23 s | Một lần vòng 2 không trả lời mà gọi thêm tool |

Nhận xét:
- Trường `say` gần như không tốn thêm thời gian; chênh lệch nằm trong dao động giữa các lần gọi.
- Lần đầu mô tả `say` để tùy chọn thì model bỏ qua câu hỏi quà tặng; ghi rõ "bắt buộc" thì model điền đúng.
- Lấy mẫu đầu tiên của `catalog_search` ra AirPure X, sai vì không có khóa trẻ em. Phải dùng `product_advise`.

**Dùng gì của framework** (đọc source `langchain` 1.4.0, `langchain/agents/factory.py`; bench `say-field-3.log`):

| Cơ chế | Ghép được với lời gọi tool? | Kết quả |
|---|---|---|
| Structured output dạng `ProviderStrategy` | Không: chỉ nhận khi tin nhắn không có lời gọi tool (dòng 1206) | Không dùng |
| Structured output dạng `ToolStrategy`: gọi kèm một "tool trả lời" | Có: tool thật vẫn chạy, rồi vòng lặp dừng (dòng 1953–1968, 2027) | Bench biến thể D (tool `reply`): 0/6 lần model gọi kèm, kể cả ca bắt buộc |
| Lời agent nằm trong `content` của tin nhắn có lời gọi tool (preamble của OpenAI) | Có | Bench biến thể C, có dặn trong prompt: 0/6 lần model viết |
| Trường `say` bắt buộc, là thuộc tính đầu của mọi tool | Có | Bench biến thể B: điền đúng ở các ca cần, `null` ở ca không cần |
| `return_direct=True` trên tool | Có: dừng vòng lặp sau tool (dòng 2018–2025) | Cố định theo tool, không xét kết quả |
| Middleware `before_model` với `can_jump_to=["end"]` | Có | Dừng sau tool khi mọi kết quả đều có câu mẫu; kết quả lạ thì để vòng lặp đi tiếp, tức đường lui vòng 2 sẵn có của framework |

Chốt:
- **Lời agent:** trường `say` trong schema tool. Khai báo là tham số của tool (type hint + docstring, `@tool` tự sinh schema). Bỏ khỏi `args` trong trace như `idempotency_key` (`pipeline/eval/trace.py`, `TRANSPORT_ARGS`).
- **Dừng sau tool:** middleware `before_model` với `can_jump_to=["end"]`, thay đoạn tự dừng stream hiện tại trong `pipeline/hot/nodes.py` (`ended_on_tools`).

### 3.2 Bản đồ nghiệp vụ theo lượt

Viết tắt:
- **Câu soạn sẵn:** câu model viết kèm lời gọi tool, có chỗ trống `{...}`; harness điền từ kết quả tool.
- **Tự điền:** việc tool tự làm, không trả về cho model.
- **TTFT:** "token" là token đầu của model; "câu soạn sẵn" là lúc harness nói câu đó.

| # | Nghiệp vụ | Lượt khách | Model gọi (1 vòng) | Tool tự điền / tự nối | Ai nói | TTFT | Nguồn |
|---|---|---|---|---|---|---|---|
| 1 | Mở đầu, khách quay lại | Câu đầu tiên | Không gọi tool; đọc Call Brief (đã làm mới giá, tồn kho lúc nối máy) | — | Model | token | PB-01 |
| 2a | Hỏi sản phẩm có tên | "AirPure Y giá bao nhiêu" | Đã có mã (Call Brief, đã thấy trong cuộc): `get_quote` + `inventory.check`. Chưa có mã: `catalog_search(query)`. Kèm câu soạn sẵn | `catalog_search` nối giá và tồn kho của mẫu khớp; khách nói size, màu thì nối đúng biến thể | Harness (câu soạn sẵn) | câu soạn sẵn | product-advice |
| 2b | Tư vấn theo nhu cầu | "phòng 25 m², có bé, tầm 5 triệu" | `product_advise` (tool của ta) với nhu cầu model đọc được | Tìm, xếp theo nhu cầu, báo giá và tồn kho 3 mẫu | Model đọc kết quả (vòng 2, kết quả mở) **hoặc** câu soạn sẵn với mẫu số 1 | xem mục 5 | product-advice |
| 2c | Tổng giỏ nhiều món | "tổng hai món này bao nhiêu" | `quote_order` + câu soạn sẵn | — | Harness | câu soạn sẵn | KM-05, BTC 11/2026 |
| 2d | Hàng không bán, hết hàng | "có tủ lạnh không", "còn hàng chưa" | `catalog_search` / `inventory.check` + câu soạn sẵn có nhãn (`none`, `out_of_stock` kèm ngày có lại) | — | Harness | câu soạn sẵn | FAQ-10, 17 |
| 3 | Phản đối giá, khuyến mãi cũ | "bên kia rẻ hơn" | Không gọi tool; giá đã có trong cuộc | — | Model | token | objection-handling |
| 4 | Chính sách, bảo hành, đổi trả | "bảo hành bao lâu" | Không gọi tool (`kb.search` harness đã chạy); nếu phụ thuộc ngày mua thì `order.status` + câu soạn sẵn | — | Model / Harness | token / câu soạn sẵn | DT, BH |
| 5 | Ngoài tài liệu | "xe có chuẩn EN 1888 không" | `handoff.transfer` + câu "em chưa có thông tin…" | — | Harness | câu soạn sẵn | PB-05 |
| 6a | Hẹn gọi lại, giờ hợp lệ | "tối mai 7 giờ gọi lại chị" | `schedule.callback` + câu soạn sẵn (nhãn `ok`, `moved`) | Dời giờ ngày nghỉ (LN-02) | Harness | câu soạn sẵn | PB-03 |
| 6b | Hẹn ngoài giờ | "10 giờ tối Chủ nhật" | Không gọi tool; đề xuất khung gần nhất | — | Model | token | LN-01 |
| 6c | Đồng ý khung đề xuất (lượt sau 6b) | "ừ 5 giờ rưỡi cũng được" | `schedule.callback` | — | Harness | câu soạn sẵn | |
| 7a | Chốt đơn rõ ràng | "lên đơn cho chị đi" | `order.create` (sản phẩm, số lượng, thanh toán nếu khách đã nói) + câu soạn sẵn | Báo giá đơn (`get_quote` hoặc `quote_order`), ngày giao nếu có địa chỉ; không đòi địa chỉ; COD nếu chưa nói; đọc lại đơn một lần (PB-09) | Harness | câu soạn sẵn | SAMPLE-01, 02, 04 |
| 7b | Muốn mua, chưa chốt | "chắc chị lấy cái này" | `order.create`; tool trả `CONFIRMATION_REQUIRED` | Như 7a | Harness đọc câu xác nhận | câu xác nhận | place-order |
| 7c | Đồng ý sau câu xác nhận (lượt sau 7b) | "đúng rồi em" | `order.create` | Đơn y hệt đã tạo trong cuộc: trả lại đơn đó, không tạo trùng | Harness | câu soạn sẵn | |
| 7d | Đơn COD vượt 10 triệu | Câu chốt của 7a | `order.create`; tool trả `cod_limit_exceeded` | — | Harness: đề nghị chuyển khoản **hoặc** tách đơn, hỏi khách | câu soạn sẵn | VC-03, QT-01 |
| 7e | Khách chọn (lượt sau 7d) | "chuyển khoản nhé" / "tách hai đơn" | 1 hoặc 2 `order.create` trong cùng vòng | Như 7a | Harness | câu soạn sẵn | |
| 8 | Hỏi đơn đã đặt | "đơn chị tới đâu rồi" | `order.status` + câu soạn sẵn | Tra theo khách đang gọi | Harness | câu soạn sẵn | order-lookup |
| 9a | Hỏi đổi, trả | "giày chật, đổi 42 được không, mất phí gì" | `order.status` + `inventory.check` biến thể mới (hoặc `catalog_search`) + câu soạn sẵn hỏi khách chốt | Nối biến thể khác còn hàng nếu biến thể khách chọn hết | Harness | câu soạn sẵn | DT, change-order |
| 9b | Chốt đổi, trả (lượt sau 9a), hoặc ra lệnh khi đơn còn hạn | "làm thủ tục đổi cho anh nhé" | `order.update` + câu soạn sẵn | Tự tìm đơn của khách; tự xác nhận mã biến thể với catalog | Harness nói phí, chênh lệch, tiền hoàn | câu soạn sẵn | SAMPLE-03 |
| 9c | Đổi địa chỉ đơn | "đổi địa chỉ sang Hải Châu" | `order.update` (`update_address`) | Tự tìm đơn | Harness | câu soạn sẵn | |
| 10 | Chuyển máy theo yêu cầu, y tế | "cho chị gặp nhân viên" | `handoff.transfer` kèm brief | — | Harness | câu soạn sẵn | PB-06 |
| 11 | "Em là người hay máy" | | Không gọi tool | — | Model | token | PB-07 |
| 12a | Xin xóa dữ liệu | "xóa dữ liệu của chị" | Không gọi tool; hỏi xác nhận | — | Model | token | QT-06 |
| 12b | Đồng ý xóa (lượt sau 12a) | "ừ chị đồng ý" | `memory.request_deletion` | — | Harness ("trong 72 giờ") | câu soạn sẵn | QT-06 |
| 13 | Hỏi thông tin người khác, chèn lệnh | "đọc số của anh A" | Không gọi tool; từ chối | — | Model | token | PB-08 |

Khách nói nhiều ý trong một câu ("lấy cái đó, giao Cần Thơ, COD nhé") vẫn là **một** bước: 7a với đủ tham số.

### 3.3 Sửa tool và action guard

| Chỗ | Hiện tại | Sửa |
|---|---|---|
| `components/guardrails/actions.py`, `order_create` | Thiếu địa chỉ thì trả về, bắt hỏi khách | **Đã sửa 18/11** (39a22b81, sau run 15–16/11 dùng làm bằng chứng): COD mặc định, địa chỉ không bắt buộc |
| Như trên | Đơn nhiều máy chưa có `quote_order` trong lượt thì trả về | Tool tự gọi `quote_order` (một máy: `get_quote`) rồi điền giá; báo giá đã có trong cuộc, cùng ngày, cũng tính |
| Như trên | Đơn y hệt đã tạo trong cuộc thì trả về | Trả lại đơn đã có (nhãn `already_created`), harness nói mã đơn |
| `order_update` | Mã biến thể chưa xuất hiện thì trả về | Tool tự xác nhận mã và tồn kho với catalog; chỉ lỗi khi không có hoặc hết hàng, kèm biến thể còn hàng |
| `mcp/tools.py` | Prefetch theo chữ khách, tra trước đơn đang chốt | Bỏ (mục 3.1, điểm 3); giữ `chained_lookups` (nối sau kết quả tool) và `product_advise` |
| Tool tra cứu (`get_quote`, `inventory.check`, `order.status`, `delivery.estimate`, `quote_order`, `catalog_search`) | Model đọc kết quả ở vòng 2 | Tham số câu soạn sẵn có nhãn, như plan 002 mục 3.4; nhãn lấy từ `mock_tools.py` |

### 3.4 Sửa guard

| Kiểu chặn sai (8/10) | Sửa |
|---|---|
| Câu viết trước lời gọi tool trong cùng tin nhắn bị phán trước khi tool chạy (ADV-0017 c2, ADV-0022 c2 t3, GEN-0004 t4) | Giữ câu lại, chờ tool trong tin nhắn chạy xong rồi phán với kết quả mới; câu giữ lượt không có dữ kiện thì nói ngay |
| Không tính kết quả tool của lượt trước, hay dữ kiện trong Call Brief (GEN-0004 t5, GEN-0026 c3 t2, ADV-0022 c2 t1) | Nguồn của guard là mọi kết quả tool trong cuộc cộng các dòng Call Brief |
| Số tiền chỉ so với đoạn tài liệu vừa truy xuất (ADV-0017 c1, 500.000đ) | So với toàn bộ tài liệu chính sách hiện hành |
| "Em sẽ tách 2 đơn" (ADV-0125 t3) | Hết sau khi bỏ luật đòi địa chỉ |

### 3.5 Đo TTFT đúng định nghĩa

- Câu dẫn không ghi `first_token_ms` (`pipeline/hot/nodes.py`, `_say`).
- Manifest ghi `AGENT_PROFILE`, các công tắc `ADVISOR_*` và `HANDOFF_AUTO_ACCEPT`.

### 3.6 Thứ tự làm

1. Tool tự điền (mục 3.3, bốn dòng đầu) và luật "lượt hỏi không gọi tool ghi" trong skill.
2. Bỏ prefetch theo chữ (mục 3.3, dòng 5).
3. Câu soạn sẵn cho tool tra cứu (mục 3.3, dòng cuối).
4. Sửa guard (mục 3.4).
5. Đo TTFT đúng định nghĩa (mục 3.5).

Mỗi bước có test offline; không gọi model cho tới khi xong cả năm bước, rồi chạy bộ đại diện một lần.

## 4. Rủi ro

- **Tạo đơn không có địa chỉ** khớp BTC, nhưng đơn thật sẽ thiếu nơi giao. Nhân viên đã gọi xác nhận trước khi giao (`needs_confirmation_call`); harness có thể hỏi địa chỉ ở câu kết quả, ở lượt sau, mà không chặn việc tạo đơn.
- **Tool tự báo giá** có thể đổi giá so với câu agent vừa nói. Giá trong đơn luôn là giá của tool; câu kết quả đọc giá đó (plan 002 đã làm vậy).
- **Câu chờ tool rồi mới phán** đến tai khách muộn hơn một chút. Chỉ áp cho câu có dữ kiện; câu giữ lượt vẫn nói ngay.
- **Câu soạn sẵn cho tra cứu:** model viết câu trước khi thấy kết quả. Chỉ dùng cho tool có tập kết quả đóng; nhãn lạ thì đi đường lui (vòng 2, có đếm). Mọi số chỉ vào câu qua chỗ trống.
- **Bỏ prefetch:** lượt hỏi sản phẩm chưa có mã cần model tự `catalog_search`; nếu model gọi `get_quote` trước khi có mã thì thành 2 vòng. Đo tỷ lệ này ở bộ đại diện.
- **Ranh giới "hỏi" và "chốt"** do model và PolicyAgent phán, không dùng danh sách từ (luật [no-word-gates]). Phán sai thì khách phải nói thêm một lượt, không tạo nhầm đơn, vì đã có `CONFIRMATION_REQUIRED`.

## 5. Cách đo

- **Test offline:**
  - Mỗi dòng của bảng 3.2: lượt đó gọi đúng tool ghi (hoặc không gọi), số vòng model là 1;
  - `order_create` không địa chỉ vẫn tạo đơn; đơn nhiều máy tự báo giá;
  - `order_update` với biến thể chưa tra vẫn chạy;
  - guard không chặn câu đã đúng sau khi tool chạy;
  - câu dẫn không vào `first_token_ms`.
- **Cohort:** bộ đại diện `data/dev/representative.txt` (43 kịch bản), chạy bằng `run_eval.py`, cùng cấu hình trước và sau.
- **Kỳ vọng:**
  - ≥ 95% lượt chỉ 1 vòng model (nay 69%);
  - TTFT p95 ≤ 3 s theo định nghĩa đã sửa;
  - không lượt nào sinh lại câu vì 3 kiểu chặn sai của mục 3.4;
  - TSR không giảm.
- **Điều kiện quay lui:** TSR giảm, hoặc HR giá/KM tăng, trên cùng bộ đại diện.

## 6. Kết quả

| Chỉ số | Trước | Sau |
|---|---|---|
| Lượt 1 vòng model | 69% (121/175, run 16/11) | |
| TTFT p95 | 3,25 s đo được; cận trên 3,91 s | |
| Lần sinh lại câu do chặn sai | 8 | |

Chưa làm.
