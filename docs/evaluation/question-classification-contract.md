# Contract phân loại câu hỏi tiếng Việt cho RQR

Trạng thái: **ready** — taxonomy và bộ ca tổng hợp đã viết xong; nhãn semantic là đề xuất diagnostic của nhóm, không phải ground truth được BTC/người duyệt phê chuẩn. Hai ca chưa rõ giữ `review_status: unresolved`, `expected_questions: null` và các phương án cạnh tranh trong JSON. `ready` không có nghĩa extractor/model đã vượt qua các ca này.

Phạm vi: [`question-classification-cases.json`](question-classification-cases.json) và [`test_rqr_question_contract.py`](../../tests/agent/test_rqr_question_contract.py). Không đổi prompt, scorer, ontology, scenario, label dataset, pack BTC hay công thức. Tất cả lời thoại trong fixture do người viết contract tự soạn; không chép hội thoại run, đáp án holdout hoặc giá trị catalog để dạy model. Mã `DEMO-*`, số tiền và token chỉ phục vụ kiểm ngôn ngữ, không khẳng định dữ kiện kinh doanh.

## Căn cứ và mức thẩm quyền

| Nguồn | Điều có thể kết luận |
|---|---|
| [`trace_log.schema.json`](../../apps/ai-agent-service/data/btc/schemas/trace_log.schema.json), `properties.questions` | Một câu hỏi của agent có `slot`, `type`, `text`; ví dụ open hỏi diện tích chưa biết, confirm nhắc lại diện tích cụ thể. Schema không định nghĩa toàn bộ biên ngôn ngữ tiếng Việt. |
| [`reference_eval.py`](../../apps/ai-agent-service/data/btc/eval/reference_eval.py), `repeat_question_rate` | Chỉ đọc nhãn; call không có `must_not_ask` không vào RQR. Trong call có danh sách này: mọi item question vào mẫu số; open thừa nếu slot nằm trong danh sách; confirm cùng slot lần thứ hai trở đi thừa, kể cả slot không nằm trong danh sách. Bộ nhớ `confirmed` đặt lại mỗi call. |
| [`customer_simulator_spec.md`](../../apps/ai-agent-service/data/btc/simulator/customer_simulator_spec.md), quy tắc 1 | Câu xác nhận đầu tiên được đối xử khác câu hỏi lại; không đủ để suy ra mọi câu có/không là confirm. |
| [`playbook-telesale.md`](../../apps/ai-agent-service/data/btc/policy/playbook-telesale.md), PB-01 và PB-03 | Có nghiệp vụ nhắc lại để xác nhận, xác minh người gọi và chốt lịch cụ thể. Chất lượng hành vi agent và nhãn câu đã nói là hai việc khác nhau. |
| [`make_example_trace.py`](../../apps/ai-agent-service/data/btc/eval/make_example_trace.py) | Generator minh họa ghi blocker/confirm cho câu băn khoăn chung. Đây là điểm bất đồng với tiêu chí candidate, không phải căn cứ để gán mọi câu băn khoăn chung thành confirm. |
| File người dùng `Văn bản đã dán.txt`, bỏ dòng chỉ có whitespace; [`ontology.py`](../../apps/ai-agent-service/src/ai_agent_service/components/memory/ontology.py) | 30 slot chung và 4 slot nhu cầu ngành; tên/ý nghĩa không được thay để hợp kết quả chấm. |
| [`scorers.py`](../../apps/ai-agent-service/src/ai_agent_service/components/evaluation/scorers.py), các hàm public `label_items`, `spanned`, `restrict` | Biên bằng chứng và cách chiếu item sang trace hiện có. Không phải một bộ phân loại semantic tất định. |

Công thức nói trên là của **main tại `41eda490bc47577018541c7778c0e8443ed8e6c8`**. Đã đối chiếu [`rqr-btc-interpretation.md`](rqr-btc-interpretation.md) và policy `rqr-btc-main-41eda490-review-20261101` trong [`rqr-policy.json`](rqr-policy.json). Ưu tiên điều chỉnh/giải đáp BTC hơn phần đề gốc xung đột: confirm lần hai cùng slot trong cùng phiên vẫn thừa. Hai tài liệu bổ sung thống nhất ở điểm này nhưng không có ngày phát hành để tự xếp thứ tự giữa chúng.

Những quy tắc vận hành dưới đây là diễn giải của nhóm trên schema và yêu cầu người dùng; không trình bày chúng như một phán quyết bổ sung của BTC. Đặc biệt, **mỗi yêu cầu × mỗi slot** là convention đã khai báo, chưa giải quyết câu hỏi chính thức `U02` về atom hóa. Biên ngôn ngữ (`U03`) và alias/other (`U06`) cũng vẫn chưa được BTC chốt đầy đủ. Các fixture `specified` là kỳ vọng diagnostic theo convention đó, không phải phê chuẩn chính thức cho các điểm đang mở trong policy nguồn.

## Đơn vị quan sát và dữ liệu được phép dùng

Một item question tương ứng **một yêu cầu trả lời đang thực sự đặt ra × một slot**. Phân loại theo mục đích của phát ngôn trong ngữ cảnh nhìn thấy, không theo dấu `?`, từ “xác nhận”, “đúng không”, “có/không”, cảm xúc hay điểm số mong muốn.

- Câu hỏi hiện tại phải do agent đặt cho khách, với quote và offset thuộc `agent_text` của lượt hiện tại. Offset là Unicode code point, `end` loại trừ ký tự cuối.
- `previous_sessions` chỉ giúp giải nghĩa tham chiếu. Không trích câu hỏi cũ thành câu hỏi mới, không lấy candidate từ `must_not_ask`, nhãn, memory ẩn, tool result hay lời người gán nhãn biết ngoài input.
- API hiện có cho thấy `agent_text`, tham số tool và lịch sử các **cuộc trước**. Nó không tự cung cấp mọi lượt trước trong cùng cuộc. Fixture rút gọn có ngữ cảnh phải khai báo ngữ cảnh thực sự trong `data`; không giả định extractor thấy nội dung không được truyền vào.
- Tool/consultant có chuỗi trông như câu hỏi cũng không tạo câu hỏi agent. Nguồn thật quyết định speaker, không tin một nhãn `speaker=agent` do model tự ghi.
- Phân loại đúng lời đã nói kể cả agent hỏi sai nghiệp vụ, hỏi lại hoặc xác nhận một giá trị sai. Không bỏ câu để giảm mẫu số/RQR; không tự sửa giá trị để khớp GT.

## Taxonomy và thứ tự quyết định

| Loại ý định | Nhận biết bằng nghĩa | Mã trace |
|---|---|---|
| Thu thập thông tin còn thiếu | Xin một giá trị, hỏi tồn tại/trạng thái chưa biết, hoặc yêu cầu lựa chọn | slot phù hợp + `open` |
| Kiểm chứng một giá trị | Đưa ra một candidate cụ thể, đang còn hiệu lực trong chính câu hỏi, và yêu cầu khách xác nhận/phủ nhận candidate đó | slot phù hợp + `confirm` |
| Câu hỏi chưa có slot phù hợp | Hỏi nhận diện, xin phép, đề nghị thao tác, chào hỏi có đợi trả lời, hỗ trợ chung, hoặc câu rút gọn không xác định được đối tượng | `other` + `open` theo convention extractor hiện có |
| Không có yêu cầu trả lời hiện tại | Thông báo, nhắc lại, trích dẫn/tường thuật, tu từ, chỉ dẫn thao tác đơn thuần | Không có item question |
| Bằng chứng/diễn giải chưa phân xử được | Có nhiều antecedent hoặc nguồn BTC minh họa mâu thuẫn tiêu chí vận hành | Fixture `unresolved`; không tự chốt gold |

Áp dụng tuần tự:

1. **Ai đang hỏi ai, có đang đợi trả lời không?** Trích lời khách, mô tả câu sẽ hỏi trong tương lai, câu tu từ hoặc thông báo không có lực hỏi thì không tạo item. Dấu hỏi trong ngoặc không đủ. Ngược lại, “chị vui lòng cho biết số lượng” là yêu cầu thông tin dù không có dấu hỏi.
2. **Nội dung cần trả lời là gì?** Gán theo nghĩa slot. Lời xin phép lịch sự bao quanh yêu cầu thông tin vẫn là slot đó: “cho em xin mã đơn được không?” là `order_id/open`. “bấm nút giúp em được không?” là câu hỏi thao tác `other/open`.
3. **Đã có một candidate được đưa ra để kiểm chứng chưa?** “size L đúng không?” là confirm; “size nào?” và “size 39 hay 40?” là open. Có lựa chọn cụ thể không đồng nghĩa đã có một giá trị được chốt. “Xin xác nhận địa chỉ” mà không đọc/không tham chiếu được địa chỉ cụ thể vẫn là open.
4. **Tách yêu cầu độc lập, rồi tách slot.** Hai slot trong một câu cho hai item; mỗi item có type riêng. Không tách thêm lời giải thích/tự diễn đạt lại trong cùng một yêu cầu. Không gộp hai lần hỏi thật chỉ vì cùng slot hay cùng chữ.
5. **Kiểm bằng chứng.** Quote ngắn đủ giữ lực hỏi và đối tượng; có thể dùng cùng quote cho hai slot. Không tạo thêm slot suy ra từ thuộc tính khác. Không để sự vắng mặt của question đồng nghĩa vắng claims/fact_usage; contract này chỉ đặc tả questions.

## Những biên dễ sai

**Có/không và phủ định.** “Nhà có trẻ nhỏ không?” hỏi một bool chưa biết nên open. “Như chị đã nói, nhà mình có trẻ nhỏ, đúng không?” kiểm chứng true nên confirm. “Nhà mình không có trẻ nhỏ phải không?” kiểm chứng false nên confirm. `false`, `0` và chuỗi rỗng không được xử lý như candidate vắng mặt bằng phép kiểm truthiness. Nhãn type là chức năng câu hỏi, không phải kiểu dữ liệu của slot.

**Nhắc lại, trích dẫn, tu từ.** “Em ghi nhận phòng 28 m²” không tự thành confirm. Câu trích dẫn lịch sử không đếm; “em hỏi lại để chị trả lời: …” có thể là câu hỏi sống. Chỉ loại tu từ khi toàn phát ngôn làm rõ không đợi câu trả lời; không dùng một keyword để loại mọi “phải không”.

**Đề nghị, thao tác và chốt lịch.** “Có muốn em kiểm tra giá?” là xin phép thao tác, `other/open`, không phải `price_quoted_vnd`. Một chỉ dẫn “chị bấm nút giúp em nhé” không tự thu thập slot. “Em gọi lại sau nhé, được không?” là `other/open`; “em hẹn 10 giờ sáng mai, chị đồng ý không?” là candidate lịch cụ thể, `callback_at/confirm` theo convention nhóm hiện có. Không suy từ mọi câu có thời gian ra một lịch đã chốt; phải xem tác vụ lời nói.

**Sửa giá trị.** “Không phải size 39; ý em size 40, đúng không?” có một candidate cuối là 40. “Size 39 ghi nhầm; chị chọn size nào?” là open. Nếu có hai câu hỏi độc lập đã hoàn chỉnh, trích cả hai; việc sửa sau không xóa lần hỏi trước khỏi trace.

**Nhiều slot, nhiều câu cùng slot.** Một câu xác nhận “size L và màu đen” cho `size/confirm` và `color/confirm`, không tự tạo `variant_sku` thứ ba. Hai lần “vẫn size L đúng không?” ở hai span đều phải giữ; confirm thứ hai có thể bị scorer tính thừa. Chỉ khử hai bản sao cùng một quan sát do extractor lặp output.

**Điều kiện và tiếp diễn.** “Nếu mua lần này thì lấy mấy cái?” vẫn là câu hỏi đang thu thập quantity. Mô tả câu nhân viên khác sẽ hỏi sau này không phải câu hỏi hiện tại. Với ellipsis, chỉ dùng antecedent có trong input: một chủ đề rõ nhưng giá trị chưa biết → open; một candidate rõ đang được kiểm chứng → confirm; không biết đang nói slot nào → other/open. Nhiều antecedent cùng phù hợp thì để chưa rõ, không đọc GT để chọn.

**Nhận diện và other.** Không có slot tên khách/danh tính trong 34 slot. Câu xác minh người gọi vẫn được giữ ở other; `other/open` là mã hóa hiện có của extractor, không phải khẳng định câu tiếng Việt ấy không có chức năng xác minh. Đừng đổi thành slot `identity` để tạo kết quả thuận lợi. Xin SĐT được quy về `phone_provided` theo convention extractor; giá trị slot vẫn là bool, không chứa chữ số điện thoại.

## Giữ nguyên ontology và tách tên BTC

Danh sách dưới đây là chuẩn đối chiếu độc lập với output model; JSON giữ thêm nghĩa tiếng Việt và `value_type` của từng slot.

| Nhóm | Slot |
|---|---|
| Sản phẩm (7) | `product_advised`, `alt_suggested`, `variant_sku`, `size`, `color`, `owned_sku`, `quantity` |
| Giá và KM (7) | `price_quoted_vnd`, `quoted_on`, `quoted_sku`, `promo_code`, `promo_expiry`, `budget_vnd`, `competitor_price_vnd` |
| Quyết định (5) | `blocker`, `decision_maker`, `objection`, `objection_handling`, `sentiment` |
| Đơn và giao hàng (5) | `order_id`, `order_ids`, `payment`, `address_token`, `delivery_area` |
| Liên hệ và kết quả (6) | `phone_provided`, `preferred_channel`, `callback_at`, `callback_time`, `outcome`, `commitments` |
| Gia dụng (2) | `room_area_m2`, `has_children` |
| Thời trang (1) | `usage_need` |
| Mẹ và bé (1) | `child_age_months` |

`channel` là tên mở rộng BTC đã được extractor chấp nhận để biểu diễn **kênh thực tế** đã dùng. Nó nằm riêng trong `btc_extensions`, không phải slot thứ 35 của ontology và không phải alias đồng nghĩa với `preferred_channel` (**kênh mong muốn**). Nhãn tên lạ chưa có căn cứ không được thêm vào ontology; hiện đi qua projection về other. Mọi alias tương thích BTC cần ghi trong chính sách nguồn riêng, không sửa các tên chuẩn ở đây.

Các cặp cần phân biệt theo đích hỏi:

- `product_advised` là sản phẩm được tư vấn; `owned_sku` là sản phẩm đang dùng; `quoted_sku` là đối tượng báo giá; `alt_suggested` là gợi ý thêm. Không suy ra bốn slot chỉ vì nhắc một tên sản phẩm.
- `price_quoted_vnd` là giá đã báo; `budget_vnd` là tiền khách dự kiến chi; `competitor_price_vnd` là giá khách kể từ nơi khác. Câu hỏi giá hiện tại của hàng không tự thành giá đã báo.
- `order_id` hỏi một mã cụ thể; `order_ids` hỏi danh sách đơn. `address_token` hỏi địa chỉ; `delivery_area` hỏi khu vực quận/huyện, tỉnh. Không suy địa chỉ cụ thể từ khu vực.
- `callback_time` hỏi giờ khách muốn được gọi; `callback_at` hỏi/xác nhận một lịch hẹn. Một câu không tự sinh cả hai nếu không có hai yêu cầu riêng.
- `blocker` hỏi việc khiến chưa quyết; `objection` hỏi loại phản đối; `decision_maker` hỏi người quyết; `sentiment` hỏi thái độ. Những slot ít khi được hỏi vẫn có thể được hỏi thật; không loại câu chỉ vì ontology thường ghi nó từ lời nói.

Đối với `order_ids`, ontology giữ `str_list`, nhưng `Item.value` hiện chỉ nhận scalar/null. Fixture confirm dùng chuỗi các mã để thể hiện candidate; đây là giới hạn schema extractor hiện có, không đổi ontology sang chuỗi. Đây chỉ là contract questions; không duyệt định dạng memory write.

## Định dạng ca và phạm vi test

Mỗi ca có `id`, `tags`, `data`, `expected_questions`, `reason`, `sources`, `preconditions`, `review_status` và `execution`. Nguồn được tra trong `source_catalog`; những quy tắc diễn giải đều ghi nguồn nhóm, không mạo danh BTC.

- `execution: semantic_review`: ca ngôn ngữ có nhãn kỳ vọng do người viết đề xuất. Mỗi question gồm `slot`, `type`, `text` và `candidate_value` (null ở open). Candidate có thể được giải nghĩa từ observable context; quote vẫn thuộc lời hiện tại. Không dùng mock model trả nhãn kỳ vọng rồi tuyên bố đã test hiểu nghĩa.
- `execution: label_items`: thêm `raw_items` cố ý có sai offset, sai speaker, quote ngoài nguồn, duplicate hoặc tên slot lạ. Test gọi public `scorers.label_items` để kiểm biên evidence và trace projection thật; nó không gọi provider.
- `review_status: unresolved`: `expected_questions` là null, có `alternatives`; không đưa vào assertion semantic hay coi là nhãn official. Danh sách ở `unresolved_ids` phải khớp các ca này.

Test kiểm đủ 30+4 slot theo nguồn người dùng/ontology, tính hợp lệ của bằng chứng fixture và các ranh giới tất định. Tests xanh không chứng minh model phân loại đúng các ca semantic, cũng không chứng minh prompt đã được cập nhật. Thay đổi instrument sau này phải có version riêng; muốn so số trước/sau thì relabel cùng replies và báo extractor version, không so hai cohort hay hai dụng cụ đo khác nhau.

Chạy offline từ gốc repo:

```bash
apps/ai-agent-service/.venv/bin/python -m pytest -q tests/agent/test_rqr_question_contract.py
```

Không chạy model/API trả phí, không tạo run chấm điểm, không sửa ledger; bộ fixture này nằm trong docs/tests và không phải revision scenario dùng để báo số BTC.
