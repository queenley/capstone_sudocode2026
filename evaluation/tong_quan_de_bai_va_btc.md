# Tổng quan đề bài và gói BTC — bản đọc lại

> **TỔNG HỢP LỊCH SỬ 01/10/2026.** Inventory/yêu cầu BTC bên dưới không phải scope hay trạng thái mới nhất. Quyết định user, deferred, thứ tự đọc và nguồn bảo vệ ở [README](README.md); làm theo [P0–P10](evaluation-implementation-plan.md). Validator/audio BTC đầy đủ làm sau, không phải BTC bỏ yêu cầu.

Ngày kiểm tra: 01/10/2026. Đã đọc **46 file BTC thực nhận**, đề PDF **17 trang**, phần giải thích và **32 sơ đồ** của flow. Đây là tổng hợp yêu cầu/kiểm kê, không phải báo cáo Agent đã chạy đạt.

Đọc cùng [nhận xét và điểm flow](can_sua.md) và [BTC cung cấp gì — nhóm phải làm gì](phan_cong_btc_va_nhom.md).

## 1. Bài toán và cách đọc nguồn

Xây harness Agent call center tiếng Việt nhận diện khách, giữ thông tin qua nhiều cuộc gọi/kênh, tư vấn bằng tool/dữ liệu kiểm chứng, chuyển người thật có ngữ cảnh và cải tiến **không fine-tune**. Trọng tâm: chứng minh memory có ích bằng phép đo tái lập so với baseline không nạp memory phiên trước. Bốn tình huống nền: tiếp nối phiên, đa kênh, chuyển máy, QA cuộc gọi. [Đ tr.1–2, C.4–C.5]

M1: chat text + ghi âm offline/ASR local, memory, tool, evaluation, ít nhất 1 cơ chế cải tiến. M2: dữ liệu/tình huống lớn hơn, voice gần real-time, RAG/judge/simulator và kiểm chứng sâu hơn. Không lấy M2 bù thiếu M1. Điểm thưởng tối đa +5% chỉ xét khi M1 đã hoàn chỉnh. [Đ G tr.10] [Đ C.1–C.6; GD Team 10 Q2]

Đề PDF là nền; DC chỉ thay/bổ sung phần được nêu rõ. Gói mới **không bỏ yêu cầu dataset tự sinh**. Nếu tài liệu, nhãn và script khác nhau, lưu cả hai, giữ report BTC nguyên bản và báo kiểm tra bổ sung; không âm thầm đổi nhãn/công thức. Có schema/rubric/mock không có nghĩa đã tích hợp/chấm/chạy đạt.

Ngày thực tế kiểm tra01/10/2026 khác ngày quy ước dataset **15/10/2026**. Scenario dùng ngày call, không dùng ngày máy. [R dòng 3; SC dòng 23]

## Quy ước nguồn

- **Đ**: [Đề PDF](<temp-repo-for-agent/docs/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>), số trang tính từ trang đầu PDF (17 trang).
- **DC**: [DIEU-CHINH-DE.md](<BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md>), §1–12. **GD**: [GIAI-DAP-MENTOR.md](<BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md>), theo Team và câu hỏi.
- **R**: [README BTC](<BTC-Data-Vong1-TEAMS/README.md>), PUBLIC / Những gì BTC giữ lại / Quy trình chấm chéo.
- **SC**: [scenario_format.md](<BTC-Data-Vong1-TEAMS/schemas/scenario_format.md>). **TR**: [trace_log.schema.json](<BTC-Data-Vong1-TEAMS/schemas/trace_log.schema.json>).
- **HB**: [handoff_brief.schema.json](<BTC-Data-Vong1-TEAMS/schemas/handoff_brief.schema.json>). **CB**: [call_brief.schema.json](<BTC-Data-Vong1-TEAMS/schemas/call_brief.schema.json>). **T**: [tools.schema.json](<BTC-Data-Vong1-TEAMS/schemas/tools.schema.json>).
- **E**: [reference_eval.py](<BTC-Data-Vong1-TEAMS/eval/reference_eval.py>), dẫn theo tên hàm; vị trí: RQR dòng 61, CCR dòng 88, check_call dòng 123, TSR dòng 170, guardrail dòng 188, memory dòng 210, HR dòng 224, latency dòng 248, avg_turns dòng 258, Calls-to-Close dòng 262, ASR dòng 282, RAG dòng 329, CLI dòng 353.
- **MO**: [mock_tools.py](<BTC-Data-Vong1-TEAMS/eval/mock_tools.py>). **J**: [llm_judge_rubric.json](<BTC-Data-Vong1-TEAMS/eval/llm_judge_rubric.json>), criterion ID hoặc agreement_protocol.
- **L**: [huong-dan-do-latency.md](<BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md>). **SIM**: [customer_simulator_spec.md](<BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md>).
- **ASR**: [ground_truth.json](<BTC-Data-Vong1-TEAMS/asr/ground_truth.json>), normalization_rule/dialogues. **RAG**: [qa_labeled.json](<BTC-Data-Vong1-TEAMS/rag/qa_labeled.json>), qid.
- **Flow**: [evaluation-flow.md](evaluation-flow.md), dẫn theo số mục § và hình 1–32.

Các ký hiệu trong bảng bên dưới trỏ tới đúng file ở danh sách này; tên hàm, mục, JSON key hoặc qid xác định phần cần đối chiếu. Tài sản BTC được kiểm tra tại `BTC-Data-Vong1-TEAMS` ngày 01/10/2026; không suy ra đây là phiên bản mới nhất ngoài những file thực nhận.


## 2. Phần ngoài Evaluation — checklist toàn dự án

Không trừ điểm flow Evaluation chỉ vì không vẽ toàn bộ runtime/UI. Các định mức dưới vẫn là trách nhiệm dự án.

### 2.1. Dataset tự sinh

| Yêu cầu | M1 | M2 | Nguồn |
|---|---|---|---|
| Transcript | ≥ 120 | ≥ 250 | Đ C.1 tr.3 |
| Audio phát triển | ≥ 40 cuộc và ≥ 1 giờ | ≥ 100 cuộc và ≥ 3 giờ | Đ C.1 tr.3 |
| Khách đa phiên | ≥ 30 khách, ≥ 2 cuộc/khách | ≥ 60 khách, có nhóm≥ 3 cuộc | Đ C.1 tr.3 |
| Khách có cả gọi/chat | ≥ 10 | ≥ 30 | Đ C.1; GD Team 5 Q2 |
| Ngành/vùng | 1 ngành/2 vùng | 3 ngành/3 vùng | Đ C.1 |
| Nhiễu | Không có tỷ lệ tối thiểu; mô tả phân bố | ≥ 20%audio | Đ C.1 |
| Catalog | ≥ 30 SKU | ≥ 100 SKU | Đ C.1; DC §2 |
| Persona | Do dự, so giá, hậu mãi | Thêm hỏi không mua, hết kiên nhẫn lần 3 | Đ C.1 |

Nhóm sinh dữ liệu bằng LLM đóng vai/TTS nhưng giá/chính sách phải dựa BTC. Public 7 case không thay 120 transcript; CRM 50 khách không tự thành 30 khách có hội thoại của nhóm. Audio phát triển và ≥ 20 file ASR eval là hai định mức khác nhau; nếu giao nhau phải khai báo split/vai trò. [DC §2; GD Team 5 Q1]

Catalog thực có 40 parent+96 variant; CSV là bản bảng, không phải40sản phẩm bổ sung. Cách đếm đạt 100 SKU M2 chưa được giải thích rõ khi dùng gói chung: cần hỏi BTC, không tự nhân bản/thay catalog. [R dòng 9; products.json/CSV]

### 2.2. Hệ thống, an toàn, kiến trúc

| Hạng mục | M1 | M2 bổ sung | Nguồn |
|---|---|---|---|
| Tiếng Việt | ASR local; ITN tiền/SĐT/ngày-hẹn; teencode/không dấu/code-switch | Diarization, sửa ASR bằng từ điển sản phẩm, xử lý nhiễu/streaming | Đ C.1 tr.3–4; DC §8 |
| Trích xuất | Intent, sản phẩm/size/màu, giá, hẹn, người quyết định, outcome | Sentiment, objection, promises | Đ C.1 tr.4 |
| PII | Mask dữ liệu nhạy cảm trong log/gửi dịch vụ ngoài | Tokenization, xóa dữ liệu | Đ C.1; DC §11 |
| Memory | Working/episodic/profile, cập nhật thông tin đổi | TTL, provenance, chống memory poisoning | Đ C.1–C.2 tr.4–5 |
| Continuity | Nhận diện khách/kênh, Call Brief | Nhiều thay đổi, lịch sử dài | Đ C.2; SC |
| Harness/tool | Tool giá/tồn kho/đơn/hẹn/chuyển máy, fallback timeout/ASR kém/LLM sai | Barge-in, nén context | Đ C.2 tr.5; DC §3 |
| MCP hoặc A2A | Chọn≥ 1hướng, giải thích | Phân quyền, policy/QA | Đ C.3 tr.6 |

Nền đề yêu cầu≥ 3 tool; DC/T chuẩn hóa7 tool M1: crm.get_customer, catalog.search, inventory.check, order.create, order.update, schedule.callback, handoff.transfer. M2 bổ sung pricing.get_quote, order.status. Không lấy “≥ 3” để bỏ hợp đồng tool mà testcase mới sử dụng. Mock cần nhóm bọc/tích hợp, không phải hệ thống nối sẵn.

MCP M1 ≥ 2 server, bắt buộc memory; M2 thêm order/knowledge và phân quyền tool. A2A M1 Router+Context/Memory+Sales; M2 Policy/Compliance+QA. Phải chia sẻ state/chuyển việc thật và giải thích ít nhất1tình huống tách thành phần có lợi. [Đ C.3]

### 2.3. UI, demo, sản phẩm nộp

| Yêu cầu | Nội dung | Nguồn |
|---|---|---|
| UI M1 | Chat, Call Brief, timeline memory | Đ C.6 tr.8; GD Team 5 Q9 |
| M2 | Copilot/cảnh báo/dashboard; voice≥ 2 phiên đồng thời | Đ C.6; DC §1 |
| Demo | 2 cuộc tiếp nối; M2 thêm phiên hậu mãi; chạy script đánh giá trực tiếp để so baseline | Đ C.6 |
| Repo |README cài/chạy, seed script, mã nguồn | Đ F tr.9 |
| Dataset |Cách sinh, phân bố, hạn chế, xử lý PII | Đ F |
| Kiến trúc |Sơ đồ, memory, tool, quyết định/lý do | Đ F |
| Evaluation |Baseline, trước/sau, ≥ 10 trường hợp sai | Đ F |
| Trình bày |Video5–8 phút, website, slide≤ 15 | Đ F |
| Ràng buộc |Không fine-tune, AI honesty, dữ liệu hợp lệ, bảo mật | Đ D; C.5 |
| Model |Được chọn model/tier; nêu cấu hình và chi phí | GD Team 5 Q10 |

Không cần tổng đài thật hay routing tới đúng nhân viên; handoff đúng lúc và brief đầy đủ là trọng tâm. [GD Team 5 Q3,5]

Trọng số dự án:12/22/15/15/13/13/5/5 cho dữ liệu/kiến trúc-harness/MCP-A2A/evaluation/cải tiến/trải nghiệm-demo/khả năng mở rộng-chi phí/trình bày. Điểm audit flow trong can_sua.md **không phải điểm chính thức này**. [Đ G tr.9–10]

## 3. Bộ dữ liệu nào dùng làm gì?

| Tập | Ai làm | Mục đích | Không phải |
|---|---|---|---|
| Dataset C.1 | Nhóm sinh trên catalog/policy BTC | Phát triển ASR/memory/Agent | Public/hidden |
| Public sample | BTC7 case | Tích hợp format/smoke test | Dataset đầy đủ của nhóm |
| Team Frozen/Golden | Nhóm chọn/gán nhãn/version trước đo | Baseline/full và R0/R1/R2 trên bộ giữ nguyên | Hidden BTC |
| Growth | Nhóm kiểm chứng case mới từ gap/lỗi được phép dùng | Chống tái phạm, báo riêng | errors.jsonl hay nơi nhập Frozen tự động |
| Hidden | BTC giữ 41 case/19 hard | Chấm chéo | File nhóm đã nhận |
| ASR eval | BTC audio+GT khi phát và ≥ 20 file nhóm | WER/CER/entity, M2 diarization | Golden text bắt buộc ánh xạ1–1 |
| RAG | BTC60 QA/99 chunk | Retrieval/abstain/answer/version | Transcript khách/memory |
| Simulator | BTCspec/persona, nhóm hiện thực | Hội thoại phản ứng, 3 seed | Fixed-turn chấm chéo |

Nguồn: Đ C.1/C.4/C.5; DC §2,7–12; R §Giữ lại; GD Team 8 Q2/Team 10 Q1.

Frozen/Golden, Growth, Source Gate và candidate/release là thuật ngữ tổ chức của nhóm, không phải tất cả có sẵn trong schema BTC. “Frozen” nghĩa giữ nguyên bộ đo, không đồng nghĩa chưa ai nhìn. Đề cho dùng feedback đánh giá để cải tiến và đo lại; sau khi sửa theo lỗi Frozen phải gọi đúng là regression/cải tiến trên bộ đã xem, không phải bằng chứng test độc lập. Source Gate chặn học tự động từ test là lựa chọn an toàn, không phải BTC cấm mọi phân tích lỗi Frozen. [Đ C.5; Flow §3]

## 4. Hợp đồng Evaluation

### 4.1. Runner và bộ test

M1 ≥ 20 scenario đa phiên2–3 calls + ≥ 5 hard; M2 ≥ 40. Cách hiểu “+5” nên hỏi BTC: có thể chọn kế hoạch thận trọng20 thường+5 hard, nhưng không tuyên bố25là quy định đã chốt. Public SAMPLE-07 chỉ 1 call vẫn phải chạy đúng. [Đ C.4 tr.6; SAMPLE-07]

Pipeline: validate input/GT → tính ngày, chuẩn bị state → chạy customer_turns (ưu tiên customer_turns_asr nếu có) → chờ memory trước call sau → xuất trace đúng schema → scorer BTC → các suite bổ sung → bảng tự sinh baseline/system/delta và lỗi. Cấu hình full/baseline chỉ khác nạp memory phiên trước; giữ working memory trong call; tách state giữa run/config/scenario. Không lộ success_if/GT cho Agent, không dùng GT điền prediction extractor. [SC; TR; R dòng 34–36; Đ A.6]

### 4.2. Metric và giới hạn scorer

| Metric | Ý nghĩa theo đề | Hành vi E cần công bố |
|---|---|---|
| RQR | Hỏi thừa/tổng câu hỏi; confirm lần 2 cùng slot là thừa | Chỉ xét call có must_not_ask không rỗng |
| CCR | Fact dùng đúng/fact cần dùng | Kiểm tên slot trong facts_used/key toolargs, không đủ chứng minh giá trị/ngữ cảnh |
| TSR | Kịch bản đạt/tổng kịch bản theo điều kiện định trước | Bỏ call thiếu success_if; tổng eligible khác mọi scenario; hard denominator lấy mọi hard flag |
| HR | Claim sai/claim kiểm chứng, riêng giá/KM | Bỏ field không có ground_truth_facts; thiếu extract/GT làm điểm đẹp giả |
| WER/CER | Edit distance sau chuẩn hóa | Lower/NFC/punctuation/space, không tự thay pipelineITN |
| Entity | Exact-match sauITN; tiền/SĐT riêng | E tổng hợp dialogue; cần breakdown/coverage bổ sung |
| Guardrail/memory | An toàn và trạng thái đúng | Regex/chuỗi sàng lọc, không phải kiểm chứng database/policy đầy đủ |
| Tool-Call Accuracy M2 | Đúng tool/args theo hợp đồng | E chưa có metric riêng |
| Calls-to-Close | Số cuộc đến khi chốt, chỉ khách đã chốt | E thấy order.create, không xác nhận result thành công |
| Mean turns | A.6 là trung bình/kịch bản | E in trung bình/cuộc |
| Latency/cost | Thời gian/chi phí | E không tự bỏ 3 warm-up, chưa tính cost |

Nguồn: Đ A tr.11–13; DC §5,11; E các hàm tương ứng. Calls-to-Close được đề gốc liệt kê M2 nhưng GD Team 8 Q3 nói không bắt buộc: giữ nếu thuận tiện, không trừ điểm tuân thủ vì thiếu khi theo giải đáp.

Ngưỡng: RQR giảm tương đối≥ 40%, TSR ≥ 70%, HR giá/KM ≤ 5%. Giảm tương đối=(baseline−full)/baseline; baselineRQR =0 thì không xác định, không tự PASS. Không có claim đủ điều kiện cũng không phải HR0% có ý nghĩa. [Đ C.4; E main/pct]

### 4.3. Judge và các suite riêng

- Judge: J01continuity/J02không bịa/J03mâu thuẫn/J04danh tính/J05handoff/J06tone/J07closing/J08confirm/J09PII/J10AI/J11budget-COD/J12hết hàng. Giữ đúng applies_to/pass_if. Assertion FAIL không chuyển judge để cứu. M2 chấm tay≥ 20 cặp(call, criterion), agreement/kappa; kappa<0,6phải phân tích. JSON/verdict lỗi không là PASS. HybridAND/retry 1 lần là lựa chọn nhóm, không đổi TSR BTC. [J; DC §12; Đ A.3]
- ASR: đầy đủ là 12 hội thoại BTC + ≥ 20 file nhóm; hiện chỉ 4 GT, không có audio. Reference/hypothesis cùng dạng số; entity ITN riêng. M2 diarization dùng segments. E đối chiếu speaker theo midpoint đoạn GT, không phải DER tiêu chuẩn. [DC §8; ASR; E wer_cer]
- RAG:25single+12multi_hop+6version_conflict+8unanswerable+5restricted+4numeric=60. Giữ mapping chunk_id BTC. “Recall@k” trong E thực chất là query-hit≥ 1relevant; full-recall multi-hop kiểm đủ tất cả. Version accuracy/answer cần người/judge riêng. [RAG; E rag_eval]
- Latency: M1 TTFT p95 ≤ 3s, Total p95 ≤ 8s, Brief ≤ 5s; M2 TTFA p95 ≤ 2,5s, Brief ≤ 3s, ≥ 2 phiên. ≥ 100 lượt, bỏ 3 warm-up, đo backend; nêu hardware/model/API. Refresh KM/tồn kho/kênh mới phải tính vào nạp Brief. ASR offline báo riêng time/phút audio. [DC §1,6; L]
- Simulator: goal/facts/patience/asked_slots/irritation/committed; 8 rules theo thứ tự; ≤ 12 lượt khách/call; log persona/seed/patience_trace/outcome/n_turns/ended_by; 3 seed, độ lệch TSR ≤ 10 điểm. Giới hạn12không áp vào fixed-turn hidden có thể16 lượt. [SIM; DC §11–12]

## 5. Improvement nối Evaluation thế nào?

M1 ≥ 2nguồn feedback, ≥ 1 cơ chế cải tiến, đoR0/R1 trên cùng Frozen. M2 ≥ 2cơ chế, ≥ 3 vòng và phân tích cải tiến gây hại. Nếu chọn Reflection, đề mô tả record sau mỗi call; record có thể “không có bài học mới”, không buộc publish thành FAQ. Human review trước áp dụng; tránh học cách hứa sai để chốt; rollback khi tụt. [Đ C.5 tr.7]

Flow đang chọn FAQ6a→6b→6c(candidate), hoặc QA10→Source Gate→11pool→12threshold→13draft; cả hai qua14review→15eval→16active. Ô10 chấm cuộc gọi; ô 15 đo phiên bản. Source Gate xét nguồn/quyền học, không checkgiá và không quyết định nhập Frozen. errors.jsonl là evidence lỗi; Growth cần scenario/GT/acceptance đã duyệt. QA không chỉ là LLM-judge. [Flow §2–15,23]

## 6. Chính sách theo thời gian và ca khó

| Tình huống | Xử lý | Nguồn |
|---|---|---|
| Ngày giữa calls | call_date ưu tiên; thiếu thì cộng dồn days_later | SC dòng 23 |
| KM/tồn kho thay đổi | on theo call; không dùng quote/memory cũ làm sự thật hiện tại | promotions/inventory_timeline; MO |
| Đơn trước 01/10/2026 | Vẫn dùng đổi trả2026-06; mới không luôn thắng | changelog CL-01; SAMPLE-07 |
| Bảo hành đơn cũ | Karofi/Kangaroo trước/từ01/08/2026 khác thời hạn | CL-04 |
| Ngừng bán | successor_sku; không đặt SKU cũ theo memory | products; CL-05 |
| Chung SĐT | Không gộp memory mù; xác nhận khi brief lệch | crm_seed C034/C035; J04 |
| Nội bộ | Không lộ giá nhập/nhà cung cấp/floor; ngày về hàng chỉ dùng phần được phép | policy nội bộ; J12; MO |
| Lịch nghỉ | Tính cả ngày nghỉ riêng, không chỉ weekend | policy lịch nghỉ; DC §11 |
| COD/budget | Tính tổng, nói vượt ngân sách; biên10 tr cần xác nhận | QT-01; VC-03; J11 |
| Đa kênh | Giữ nguồn/thời điểm quote, giải thích mâu thuẫn | SAMPLE-04; DC §11 |
| PII/AI/xóa | Không nhận là người; mask và xử lý xóa theo mức yêu cầu | J09/J10; DC §11 |

## 7. Tài sản thực nhận

| Tài sản | Đếm thực tế | Ghi chú |
|---|---|---|
| Toàn gói |46 file, loại metadata hệ điều hành | Sổ đầy đủ bên dưới |
| Policy |14 file/99 chunk_id duy nhất | Khớp README |
| Catalog |40 parent/96 variant/40 hàngCSV | Có2 ngừng bán/2 combo theo dữ liệu |
| Promotion |13 record | README ghi14 |
| CRM |50 khách/49SĐT phân biệt | Có chung SĐT |
| Public |7 scenario/13 calls/39customerturns |4 thường+3 hard, README ghi5+2 |
| ASR |4 GT D01–D04/34 turn/1 noisy | Không có audio/segments |
| RAG |60 QA/6 loại | Một số answer tranh chấp |
| Simulator/judge |12 persona/spec; 12 criterion/prompt | Chưa có engine/verdict nhóm |
| Trace mẫu |39 turn/config; 33agent_text rỗng/config | Generator nhân tạo |
| validate_scenarios.py |Không có | README nhắc nhưng chưa nhận |
| make_audio.py/script sinh |Không có | BTC giữ script sinh |
| Hidden/8 GT còn lại |Chỉ được mô tả, chưa nhận | BTC giữ 41 case/19 hard và8 GT |
| hypotheses/rag_results nhóm |Không có | Đầu ra nhóm phải tạo, không phải BTC thiếu |

R dòng 20 mô tả bộ ASR đầy đủ 12 GT/86 turn/~12 phút/4 noisy, nhưng dòng 30 nói team nhận 4 mẫu. Không báo đã có 12 audio chỉ vì đọc dòng 20.

### Sổ đọc đủ 46 file

Mỗi file dưới đã đọc/parse đầy đủ. Số dòng thuộc snapshot này; source code được đọc, không mặc định chạy generator.

| # | File | Dòng | Dấu vết kiểm tra/vai trò |
|---|---|---:|---|
| 1 | [DIEU-CHINH-DE.md](<BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md>) | 59 | Đọc đủ 12 điều chỉnh; nguồn thay thế/bổ sung đề. |
| 2 | [GIAI-DAP-MENTOR.md](<BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md>) | 60 | Đọc đủ giải đáp; làm rõ CLI, baseline, simulator, Calls-to-Close. |
| 3 | [README.md](<BTC-Data-Vong1-TEAMS/README.md>) | 37 | Đối chiếu PUBLIC/giữ lại/chấm chéo; phát hiện số promotion và loại sample lệch. |
| 4 | [asr/ground_truth.json](<BTC-Data-Vong1-TEAMS/asr/ground_truth.json>) | 362 | Parse4 dialogue/34 turn; đọc normalization và entity; không có audio đi kèm trong gói. |
| 5 | [catalog/crm_seed.json](<BTC-Data-Vong1-TEAMS/catalog/crm_seed.json>) | 551 | Parse50 khách/49SĐT phân biệt; seed_history, đơn và shared identity. |
| 6 | [catalog/inventory_timeline.json](<BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json>) | 72 | Đọc các mốc tồn kho; dùng call_date/on, không dùng đồng hồ hiện tại. |
| 7 | [catalog/products.csv](<BTC-Data-Vong1-TEAMS/catalog/products.csv>) | 41 | Đọc 40 hàng dữ liệu; bản bảng, không phải40sản phẩm bổ sung. |
| 8 | [catalog/products.json](<BTC-Data-Vong1-TEAMS/catalog/products.json>) | 1198 | Đọc 40 parent +96 variant, attributes, discontinued/successor/combo. |
| 9 | [catalog/promotions.json](<BTC-Data-Vong1-TEAMS/catalog/promotions.json>) | 190 | Đọc 13chương trình; điều kiện/stackable/thời hạn; README ghi14. |
| 10 | [eval/huong-dan-do-latency.md](<BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md>) | 20 | Đọc đủ 7quy tắc; đối chiếu warm-up với scorer. |
| 11 | [eval/llm_judge_rubric.json](<BTC-Data-Vong1-TEAMS/eval/llm_judge_rubric.json>) | 19 | Đọc 12 criterion, prompt và protocol đối chiếu người. |
| 12 | [eval/make_example_trace.py](<BTC-Data-Vong1-TEAMS/eval/make_example_trace.py>) | 47 | Đọc generator; trace nhân tạo lấy trực tiếp nhãn và random latency; không phải runner Agent. |
| 13 | [eval/mock_tools.py](<BTC-Data-Vong1-TEAMS/eval/mock_tools.py>) | 222 | Đọc toàn bộ9 tool và helper/mask; kiểm tra quote trong bộ nhớ, không ghi trạng thái ra file. |
| 14 | [eval/reference_eval.py](<BTC-Data-Vong1-TEAMS/eval/reference_eval.py>) | 397 | Đọc toàn bộ metric/CLI; gọi hàm evaluate với trace mẫu, không chạy Agent. |
| 15 | [eval/runs/baseline.jsonl](<BTC-Data-Vong1-TEAMS/eval/runs/baseline.jsonl>) | 39 | Parse/đọc 39 turn; 33agent_text rỗng; chỉ ví dụ định dạng. |
| 16 | [eval/runs/full.jsonl](<BTC-Data-Vong1-TEAMS/eval/runs/full.jsonl>) | 39 | Parse/đọc 39 turn; 33agent_text rỗng; chỉ ví dụ định dạng. |
| 17 | [eval/runs/report_example.json](<BTC-Data-Vong1-TEAMS/eval/runs/report_example.json>) | 319 | Đọc và đối chiếu lại evaluate; system/baseline khớp trace mẫu. |
| 18 | [policy/changelog.md](<BTC-Data-Vong1-TEAMS/policy/changelog.md>) | 16 | CL-01..05: ngày hiệu lực, grandfathering đơn cũ, successor. |
| 19 | [policy/chinh-sach-bao-hanh.md](<BTC-Data-Vong1-TEAMS/policy/chinh-sach-bao-hanh.md>) | 16 | BH-01..05: thời hạn, ưu tiên catalog; Q20 cần xác nhận. |
| 20 | [policy/chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md](<BTC-Data-Vong1-TEAMS/policy/chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md>) | 18 | Bản cũ; không xóa khỏi corpus vì còn áp dụng đơn trước 01/10. |
| 21 | [policy/chinh-sach-doi-tra.md](<BTC-Data-Vong1-TEAMS/policy/chinh-sach-doi-tra.md>) | 24 | DT-01..07: điều kiện bản mới, 7 ngày/30 ngày, đổi size/hoàn tiền. |
| 22 | [policy/chinh-sach-van-chuyen-thanh-toan.md](<BTC-Data-Vong1-TEAMS/policy/chinh-sach-van-chuyen-thanh-toan.md>) | 28 | VC-01..07: giao hàng/phí/COD; biên đúng 10 triệu mâu thuẫn wording. |
| 23 | [policy/dieu-khoan-khuyen-mai.md](<BTC-Data-Vong1-TEAMS/policy/dieu-khoan-khuyen-mai.md>) | 30 | KM-01..09: hiệu lực/điều kiện/chọn KM/giỏ hàng; Q57 cần xác nhận. |
| 24 | [policy/faq.md](<BTC-Data-Vong1-TEAMS/policy/faq.md>) | 60 | FAQ có 19 chunk; cần lấy nguồn gốc policy khi sinh đáp án/test. |
| 25 | [policy/ghi-chu-nhap-hang-NOI-BO.md](<BTC-Data-Vong1-TEAMS/policy/ghi-chu-nhap-hang-NOI-BO.md>) | 23 | Nội bộ: tách thông tin có thể dùng với giá nhập/nhà cung cấp cấm tiết lộ. |
| 26 | [policy/noi-quy-nhan-vien.md](<BTC-Data-Vong1-TEAMS/policy/noi-quy-nhan-vien.md>) | 16 | Tài liệu nhiễu; giữ trong corpus chuẩn để kiểm tra retrieval. |
| 27 | [policy/playbook-telesale.md](<BTC-Data-Vong1-TEAMS/policy/playbook-telesale.md>) | 36 | PB-01..11: chào/confirm/chuyển máy/tổng kết; PB-01 khác giới hạn J01. |
| 28 | [policy/quy-trinh-cod-hoan-hang.md](<BTC-Data-Vong1-TEAMS/policy/quy-trinh-cod-hoan-hang.md>) | 19 | QT-01..06: COD/xác nhận/hoàn hàng; đối chiếu mock. |
| 29 | [policy/spec-gia-dung.md](<BTC-Data-Vong1-TEAMS/policy/spec-gia-dung.md>) | 36 | Spec bảng; đọc thông số làm GT và retrieval numeric/multi-hop. |
| 30 | [policy/spec-thoi-trang-me-be.md](<BTC-Data-Vong1-TEAMS/policy/spec-thoi-trang-me-be.md>) | 33 | Spec/size/màu/mẹ & bé; variant và tư vấn theo điều kiện. |
| 31 | [policy/thong-bao-lich-nghi.md](<BTC-Data-Vong1-TEAMS/policy/thong-bao-lich-nghi.md>) | 13 | Ngày nghỉ ảnh hưởng lịch hẹn/ETA, không chỉ weekend. |
| 32 | [rag/qa_labeled.json](<BTC-Data-Vong1-TEAMS/rag/qa_labeled.json>) | 585 | Đọc 60 QA/6 loại, toàn bộ relevant_chunk_ids/expected_answer; Q20/Q57 tranh chấp. |
| 33 | [schemas/call_brief.schema.json](<BTC-Data-Vong1-TEAMS/schemas/call_brief.schema.json>) | 33 | Đọc required, context/precomputed_parts; adapter phải validate. |
| 34 | [schemas/handoff_brief.schema.json](<BTC-Data-Vong1-TEAMS/schemas/handoff_brief.schema.json>) | 25 | Đọc required; scorer subset check không thay schema. |
| 35 | [schemas/scenario_format.md](<BTC-Data-Vong1-TEAMS/schemas/scenario_format.md>) | 23 | Đọc calls/input_mode/asr/seed_history/memory_expectation/success_if. |
| 36 | [schemas/tools.schema.json](<BTC-Data-Vong1-TEAMS/schemas/tools.schema.json>) | 166 | Đọc tên/required các tool; không mặc định mọi hàm Python nhận on. |
| 37 | [schemas/trace_log.schema.json](<BTC-Data-Vong1-TEAMS/schemas/trace_log.schema.json>) | 169 | Đọc required/types/questions/claims/tool_calls/latency/memory; không giả định null latency hợp lệ. |
| 38 | [simulator/customer_simulator_spec.md](<BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md>) | 33 | Đọc state/8 rules/12 turn/log/3 seed/≤ 10 điểm, không lộ GT. |
| 39 | [simulator/personas.json](<BTC-Data-Vong1-TEAMS/simulator/personas.json>) | 29 | Đọc 12 persona, prompt và patience theo call. |
| 40 | [test_set/public_sample/SAMPLE-01.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-01.json>) | 65 | Tiếp nối do dự/hỏi người nhà; budget lời thoại5 tr khác facts5,7 tr. |
| 41 | [test_set/public_sample/SAMPLE-02.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-02.json>) | 61 | Giá đối thủ/điện thoại; promo_active call 2 cần đối chiếu thời hạn. |
| 42 | [test_set/public_sample/SAMPLE-03.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-03.json>) | 64 | Đổi màu sau mua; order_id kỳ vọng không có sẵn trong seed/mock. |
| 43 | [test_set/public_sample/SAMPLE-04.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-04.json>) | 62 | Fanpage→hotline; giữ nguồn báo giá và định danh kênh. |
| 44 | [test_set/public_sample/SAMPLE-05.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-05.json>) | 56 | Ca khó KM hết hạn; không giữ giá cũ vô điều kiện. |
| 45 | [test_set/public_sample/SAMPLE-06.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-06.json>) | 79 | Ca khó ASR/teencode; ưu tiên customer_turns_asr. |
| 46 | [test_set/public_sample/SAMPLE-07.json](<BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-07.json>) | 43 | Ca khó policy cũ; chỉ 1 call, không ép mọi public sample phải 2–3 call. |

### Kiểm tra read-only

Đã parse/đếm dữ liệu, đọc source, xem 32 ảnh. Gọi E.evaluate trên trace mẫu trong bộ nhớ: full TSR85,7%, hard66,7%, RQR 0%, CCR 100%; baseline TSR85,7%, RQR 100%, CCR 4,8%; khớp report_example phần system/baseline. Đây chỉ là consistency check artifact mẫu: generator lấy nhãn trực tiếp, latency ngẫu nhiên, 39 lượt<100; **không chứng minh Agent đạt**. Gọi MO.pricing_get_quote để kiểm Q57 trong bộ nhớ; không chạy Agent/benchmark, không sửa scorer/data. [E; eval/make_example_trace.py; eval/runs; MO]

## 8. Mâu thuẫn/câu hỏi cần BTC xác nhận

| ID | Nguồn chưa khớp | Tác động và cách xử lý |
|---|---|---|
| B01 | README14promotion/5+2sample; thực tế13/4+3 | Dùng số thực nhận, xin changelog |
| B02 | SAMPLE-01 call 1 nói 5 tr, facts budget5,7 tr | Đánh dấu disputed, không sửa raw |
| B03 | SAMPLE-02 call 2 ngày 18/10 promo_active=false; GIFT-FILTER tới 22/10/tool vẫn áp dụng | Chốt ý nghĩa promo_active trước chấm HR |
| B04 | SAMPLE-03 kỳ vọng OD682761; seed/mock không có, order mới đầu tiên OD600001 | Xin hợp đồng seed order; argsmatch không chứng minh order tồn tại |
| B05 | Q20 đáp 12 tháng; BH-01 nói 12nhưng ưu tiên catalog; catalog Xiaomi24 | Answer judge cần nhãn được xác nhận |
| B06 | Q57 đáp 10.435.000; mock Pro7.690.000+X2.445.000=10.135.000 | Chốt exclusivity cấp giỏ hay cấp SKU |
| B07 | VC-03 COD dưới 10 tr; QT-01/J11/mock chặn trên 10 tr | Chốt đúng biên10 tr |
| B08 | PB-01 tối đa2 fact cũ; J01 tối đa3 | Runtime≤ 2 có thể thỏa cả hai, không đổi rubric |
| B09 | L bỏ 3 warm-up; E không tự bỏ | Giữ raw và latency view; xin protocol chính thức |
| B10 | Đ A.6 turns/scenario; E turns/call; CTC trong Đ nhưng GD nói tùy chọn | Báo cả 2 đơn vị; CTC không tính bắt buộc |
| B11 | M2 ≥ 100 SKU; 40 parent+96 variant | Hỏi cách đếm được chấp nhận |
| B12 | SIM “độ lệch≤ 10 điểm” chưa rõ range/std; “20+5” chưa rõ cách đếm | Báo range/std và thường/hard/tổng riêng |
| B13 | DCmọi tool nhận on; vài hàm mock không có on | Adapter theo signature, xin hợp đồng thống nhất |
| B14 | validate_scenarios.py/audio/segments chưa nhận | Xin tài sản cần phát; không tuyên bố suite đã chạy |
| B15 | order_update mock không phân nhánh phí policy cũ; schedule_callback chưa xử lý giờ mở cửa đặc biệt ngày 11/11 (07:00–23:00) | Contract tests, giữ log khác biệt tài liệu/code, chờ BTC chốt |

Nguồn: từng file/ID đã nêu trong bảng; B15 xem MO.order_update/schedule_callback và policy đổi trả cũ/lịch nghỉ. Đây là các điểm cần xác nhận của snapshot, không phải lý do dừng mọi việc.

## 9. Khi quay lại làm tiếp

Theo thứ tự: kiểm kê/version và contract tests → data/GT → runner/state/trace/extractor → baseline/full M1 → Gap Loop và R0/R1 → suite M2 và R2 → báo cáo/demo. Xem [phân công chi tiết](phan_cong_btc_va_nhom.md). Không tự sửa flow/data trong đợt audit này.
