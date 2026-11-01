# RQR: yêu cầu BTC và cách main đang tính

Rà soát ngày 01/11/2026. Policy máy đọc: [rqr-policy.json](rqr-policy.json), `status=ready` nghĩa là đã đối chiếu xong các nguồn hiện có; các câu hỏi chưa được BTC quy định vẫn được giữ ở `unresolved_issues`.

Phạm vi chỉ là diễn giải và bằng chứng. Không sửa scorer, pack BTC, extractor, prompt, test, scenario hay nhãn. Mốc thực thi được giữ là main `41eda490bc47577018541c7778c0e8443ed8e6c8`; SHA-256 của `apps/ai-agent-service/data/btc/eval/reference_eval.py` là `18f1fa0881a345b8dd01c4160ec8fc31aea5ff8385c09a3eb3db96a88372843e`.

## Nguồn và thứ tự ưu tiên

| ID trong JSON | Nguồn đã đọc | Phần liên quan |
|---|---|---|
| `sudo_assignment` | `/Users/vqd/Downloads/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf` (17 trang) | C.2 trang 5; C.4 trang 6–7; A.1 trang 11; A.6/B trang 13–14; định nghĩa phiên trang 15 |
| `btc_amendment` | `/Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md` | dòng 15–19: trace/scorer; 29–31: xác nhận lại |
| `btc_mentor` | `/Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md` | dòng 37–38: Team 5 câu 11; 42–46: chấm chéo; 56–57: đa lượt/đa phiên |
| `btc_readme` | `/Users/vqd/Downloads/BTC-Data-Vong1-TEAMS/README.md` | dòng 32–37: chấm chéo và kiểm tay 20 lượt |
| `btc_scenario_schema` | [scenario_format.md](../../apps/ai-agent-service/data/btc/schemas/scenario_format.md) | dòng 13–15: `facts_established`, `must_carry_over`, `must_not_ask` |
| `btc_trace_schema` | [trace_log.schema.json](../../apps/ai-agent-service/data/btc/schemas/trace_log.schema.json) | dòng 51–75: một câu hỏi gán về slot; `type` chỉ có `open`, `confirm` |
| `btc_playbook` | [playbook-telesale.md](../../apps/ai-agent-service/data/btc/policy/playbook-telesale.md) | PB-01 dòng 5–6; PB-09/10 dòng 29–33 |
| `main_reference` | [reference_eval.py](../../apps/ai-agent-service/data/btc/eval/reference_eval.py) **tại mốc main trên** | dòng 29–43, 75–100, 179–181, 391–400 |
| `user_ontology` | file đính kèm `Văn bản đã dán.txt` | bỏ dòng chỉ có whitespace: 30 core + 4 slot ngành; không phải một quy tắc đếm RQR |
| `main_extractor_prompt`, `main_extractor_code` | [extractor.txt](../../config/prompts/evaluation/extractor.txt), [scorers.py](../../apps/ai-agent-service/src/ai_agent_service/components/evaluation/scorers.py) **tại mốc main trên** | quy ước của dụng cụ đo v4, không phải giải đáp BTC |

Các file schema và playbook ở repo khớp byte với bản Downloads. Ba file hướng dẫn cấp gốc của gói BTC không có bản tương ứng trong thư mục pack của repo; JSON lưu đường dẫn ngoài repo, hash, trích dẫn và dòng để có thể kiểm lại. `/Users/vqd/Downloads/SUDO.pdf` là bản ghi chú thiết kế 32 trang, mở đầu bằng “pipeline”; đã đọc để lấy bối cảnh, không dùng để ghi đè đề BTC.

Ưu tiên giải đáp/điều chỉnh bổ sung của BTC khi xung đột với đề gốc. Cụ thể, A.1 đề gốc miễn câu xác nhận; điều chỉnh mục 5 và giải đáp Team 5 câu 11 bổ sung ngoại lệ: xác nhận cùng slot lần thứ hai trở đi trong cùng phiên là thừa. Hai nguồn bổ sung thống nhất ở điểm này; không có ngày phát hành trong nội dung để tự xếp chúng theo thời gian.

Quyết định của người dùng và `evaluation/README.md:49` giữ nguyên scorer trên main. Vì vậy cần phân biệt **yêu cầu văn bản BTC**, **hành vi main**, và **quy ước extractor của đội**. Không sửa công thức để giải quyết một điểm chưa rõ. Toàn file scorer main khác bản Downloads (SHA-256 bản ngoài: `818fc4900a18f9b92c1abb3adebcca997774dfc3da23083c9030bad2f7229ddc`), nhưng thân hàm `repeat_question_rate` của hai bản giống nhau khi đối chiếu AST. Kết luận này chỉ áp dụng cho RQR, không đồng nhất toàn bộ hai bộ chấm.

## Yêu cầu BTC đã có bằng chứng

Theo A.1, `RQR = số câu hỏi thừa / tổng câu hỏi agent × 100%`. Đơn vị là câu hỏi gắn slot, không phải lượt thoại. `must_not_ask` là danh sách slot không được hỏi **mở**. Đề nói thông tin thực sự mới và thông tin hết hạn theo TTL không bị coi là hỏi thừa; những điều này phải được thể hiện đúng trong nhãn scenario, không phải do extractor tự bỏ câu hỏi.

Xác nhận đầu tiên không thừa; xác nhận lại cùng slot trong cùng phiên từ lần hai trở đi là thừa theo phần bổ sung. BTC còn phạt đọc vẹt hồ sơ ở tiêu chí trải nghiệm và rubric judge; đây không phải một nhánh tính RQR mới. PB-01 khuyên chỉ nhắc tối đa hai thông tin liên quan ở lời mở đầu, còn PB-09 yêu cầu đọc lại đơn một lần trước `order.create`; không nguồn nào cấp một ngoại lệ RQR riêng cho bước đọc đơn.

BTC giao đội trích `questions[]`/`claims[]` và mô tả phương pháp trong báo cáo, kiểm tay ngẫu nhiên 20 lượt để phát hiện bỏ sót. Giảm RQR ≥40% là **giảm tương đối**: `(RQR_baseline - RQR_full) / RQR_baseline × 100%`, không phải giảm 40 điểm phần trăm. Hai cấu hình dùng cùng test/model/tham số, chỉ khác nạp bộ nhớ.

## Thuật toán main, giữ nguyên

Đặt `E` là các cặp `(scenario_id, call)` có `set(must_not_ask)` **khác rỗng**. `D` là tổng số phần tử `questions[]` của mọi dòng trace thuộc `E`. `N` là số phần tử trong `D` thỏa một trong hai điều kiện:

1. `type == "open"` và `slot` nằm trong `must_not_ask` của call đó.
2. `type == "confirm"` và đã gặp một phần tử `confirm` cùng tên slot trước đó trong call đó.

Main trả `round(100 × N / D, 1)` nếu `D > 0`, ngược lại `None` (JSON `null`). Đây là gộp tử/mẫu trên mọi call đủ điều kiện, không lấy trung bình các tỷ lệ mỗi call. Bộ `confirmed` khởi tạo lại cho **mỗi `(scenario_id, call)`**; `total`/`redundant` cộng dồn toàn lần chấm một cấu hình.

| Tình huống | Main đếm vào `D` | Main đếm vào `N` |
|---|---:|---:|
| Call thiếu `must_not_ask` hoặc có `[]` | 0 | 0, kể cả nhiều xác nhận lặp |
| `open`, slot trong `must_not_ask` | 1 mỗi phần tử | 1 mỗi phần tử, kể cả câu đầu tiên của call |
| `open`, slot ngoài `must_not_ask`, dù hỏi nhiều lần | 1 mỗi phần tử | 0 |
| `confirm` đầu tiên của một slot | 1 | 0, kể cả slot trong `must_not_ask` |
| `confirm` lần 2+ cùng slot | 1 mỗi phần tử | 1 mỗi phần tử, **kể cả slot ngoài `must_not_ask`** |
| `slot="other", type="open"` | 1 | 0 khi `other` không có trong `must_not_ask` |

Các dòng của một call được `load_trace` sắp theo `turn`; các phần tử `questions[]` giữ thứ tự mảng. Xác nhận lặp trong **cùng lượt** vẫn bị đếm. Một `open` không thêm slot vào `confirmed`; chuỗi `open → confirm → confirm` chỉ có câu confirm cuối là xác nhận lặp. Không cần khách trả lời “đúng” để main đánh dấu đã xác nhận: chỉ cần đã có nhãn `confirm`.

Đổi giá trị, đổi SKU, đổi người dùng chung SĐT, khách sửa thông tin, TTL, tool vừa trả dữ liệu mới hoặc đoạn hội thoại được handoff **không tự reset** `confirmed` trong cùng call. Main chỉ so tên slot; không đọc giá trị/quote/ý định để miễn trừ. Sang call khác, scenario khác, hoặc lần gọi hàm chấm khác thì reset. Call 1 vẫn được tính nếu nó có `must_not_ask` khác rỗng; không có điều kiện cứng `call_2+`.

`must_not_ask` ở đây là **nhãn scenario đầu vào scorer**, không phải trường cùng tên trong Call Brief của agent. Hàm không suy lại nó từ memory, `facts_established`, TTL, `facts_used`, `agent_text` hay lịch sử. Slot khớp chuỗi chính xác, không chuẩn hóa alias. Thiếu call/thiếu câu hỏi không sinh một lỗi RQR giả định; mẫu số thiếu không chứng minh hội thoại tốt.

Loader chỉ nhóm theo `(scenario_id, call)`, không nhóm theo `config`/`run_id`/SĐT. Main đọc và chấm file full/baseline riêng; không ghép nhiều cấu hình hoặc nhiều run vào cùng một file rồi mong scorer tự tách. `examples` chỉ giữ 20 câu thừa đầu, còn tử/mẫu vẫn tính toàn bộ.

## `other`, nhiều slot và quy ước hiện có của đội

**`other` là giá trị của `slot`, không phải giá trị của `type`.** Schema BTC chỉ cho `type=open|confirm`; `slot` là chuỗi không có enum. Không có danh sách 34 slot bắt buộc trong schema BTC. Main cũng không giới hạn tên slot: `other` chỉ là một chuỗi, nên nếu scenario có `must_not_ask=["other"]`, câu `other/open` vẫn bị phạt; nếu đưa `other/confirm` vào scorer thì lần hai cũng bị phạt. Dụng cụ đo v4 của đội hiện ép `other` về `open` (`scorers.py:368–371`); đó là quy ước local.

File người dùng gửi có đúng **30 core + 4 slot ngành** sau khi bỏ dòng chỉ có whitespace; JSON liệt kê đủ 34 tên. Main v4 có thêm `channel` ở tầng extractor, và `other` là sentinel ngoài ontology; chúng không làm ontology người dùng thành 35 hoặc 36 slot. Giữ `channel` hay thay quy ước này là quyết định extractor có version riêng, không phải một điều chỉnh RQR đã được BTC ban hành.

Trong `extractor.txt` v4, đội đã chọn các quy ước sau (ghi nhận hiện trạng, **không nâng thành luật BTC**):

- Một câu hỏi về hai slot sinh hai item; đọc lại đơn rồi xin xác nhận sinh một item mỗi slot; nhiều câu trong một lượt không gộp thành một câu.
- `confirm` khi agent nêu một giá trị cụ thể và xin xác nhận; hỏi giá trị hoặc chọn giữa phương án là `open`. Không có yêu cầu câu confirm phải bắt nguồn từ phiên trước để scorer đếm nó.
- Đề nghị hỗ trợ, xin phép, câu chốt hoặc xã giao mà thực sự chờ câu trả lời được ghi `other/open`; lời chào/khẳng định thuần túy không phải câu hỏi.
- Chống trích trùng cùng một quan sát bằng identity gồm kind, slot, value, type, source và span; đây không phải bỏ mọi câu hỏi lặp cùng slot. Hai lần hỏi thật ở hai span/lượt khác nhau vẫn phải giữ.

Main không tự tách câu, không tách slot và không khử trùng `questions[]`. Nếu extractor xuất hai item, main cộng hai vào mẫu số; nếu xuất một, main cộng một. BTC chưa nói rõ quy tắc atom hóa câu nhiều slot, cũng chưa giải quyết alias như `variant_sku` so với `size`/`color`. Vì vậy phải khai báo quy ước, kiểm tay và giữ nhất quán; không chọn cách tách/gộp dựa trên cách nào có điểm đẹp hơn.

`success_if.max_agent_questions` là kiểm tra TSR riêng: main cộng `len(questions)` của toàn call, không dùng cổng `must_not_ask`. Thay đơn vị trích câu hỏi có thể đổi cả TSR, kể cả các call không được tính RQR.

## Điểm chưa được BTC chốt và cách xử lý trong phạm vi này

| ID | Điểm chưa rõ trong nguồn BTC | Hành vi main/đội cần báo rõ |
|---|---|---|
| `U01` | Bổ sung “trong cùng phiên” có áp dụng cả call không có `must_not_ask`? | Main bỏ toàn call nếu danh sách rỗng. Giữ nguyên cổng; không báo là main đo mọi phiên. |
| `U02` | Một câu ghép nhiều slot đếm theo câu ngữ pháp hay từng yêu cầu thông tin? | Main đếm item; v4 chọn mỗi câu hỏi × mỗi slot. Đây là quy ước đo, chưa có câu trả lời BTC riêng. |
| `U03` | Biên giữa hỏi thông tin, hỏi có/không, đề nghị, xin phép, xã giao và câu hỏi tu từ; có/không dấu `?` | Schema chỉ cho ví dụ open/confirm; v4 có quy tắc chi tiết hơn. Cần kiểm tay ca biên, không đồng nhất mọi câu có `?` với câu hỏi hay mọi yes/no với confirm. |
| `U04` | “Đã được xác nhận” có cần khách thực sự đồng ý không? | Main dùng lần agent hỏi `confirm`, không chờ phản hồi. Không tự miễn câu lặp vì khách chưa trả lời. |
| `U05` | Xác nhận lại do khách sửa, chuyển sản phẩm, thông tin stale, xác minh danh tính hoặc đọc đơn có được miễn không? | Không có ngoại lệ trong hàm; cùng slot lần 2+ vẫn bị phạt ở call đủ điều kiện. Tách đánh giá phù hợp nghiệp vụ khỏi số main. |
| `U06` | Ranh giới alias/slot: product–variant–size–color, callback_at–callback_time, blocker–decision_maker; câu hỏi ngoài ontology | BTC không phát ontology hoàn chỉnh hoặc luật alias; 34 slot là ontology người dùng, `channel`/`other` là quy ước đo đã có. Không đọc `must_not_ask` để đoán nhãn đúng. |
| `U07` | Tự xác định TTL/hợp lệ trước call thế nào khi scenario và bộ nhớ thật bất đồng? | Main tin `must_not_ask` cố định. Tranh chấp nhãn phải đi qua ground-truth review; không sửa nhãn hay tự giảm tử số ở extractor. |

Không cần giải quyết các câu hỏi này bằng một luật mới để dùng scorer hiện tại. Phân loại cần dựa trên lời agent và bằng chứng trích dẫn, không dựa trên tác động lên điểm. Nếu thay quy ước extractor, ghi `extractor_version` mới; so bằng `run_eval.py --relabel` trên cùng replies khi được giao chạy, cùng ledger đã chỉ định. Không diễn giải `None` hoặc thiếu trace thành 0%/PASS. Main dùng RQR đã làm tròn một chữ số để tính mức giảm; baseline bằng 0 hoặc `None` cho mức giảm `None` và cờ đạt ngưỡng `false`.

## Ví dụ số học để kiểm tra cách đọc hàm

Các nhãn dưới đây được dựng mới để minh họa thuật toán, không lấy từ hội thoại hay đáp án test.

Trong một call có `must_not_ask=["size"]`, lần lượt xuất `size/open`, `size/confirm`, `size/confirm`, `payment/open`, `other/open`, `payment/confirm`, `payment/confirm`: `D=7`, `N=3`, RQR=`42.9%`. Ba câu thừa là open về size và hai confirm lặp. `payment` không nằm trong `must_not_ask` vẫn có thể bị phạt confirm lặp. Một call khác không có `must_not_ask`, dù xuất nhiều câu hỏi, cộng `0/0` vào tổng này. Sang call đủ điều kiện kế tiếp, confirm đầu về size lại không thừa.

Nếu một lượt trong call đủ điều kiện có hai phần tử `size/confirm` và `color/confirm` chưa từng gặp, phần lượt đó cộng `0/2`; nếu lặp cả hai sau đó, cộng `2/2`. Đây là kết quả với **hai item đã cho**, không phải bằng chứng BTC bắt buộc phải trích câu ghép theo cách đó.

Rà soát này chỉ đọc nguồn, đối chiếu hash/AST và kiểm cấu trúc hai tài liệu; không chạy đánh giá, không gọi model/API trả phí và không tạo lại ledger.
