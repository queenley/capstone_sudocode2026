# Phân công: BTC đã cung cấp gì và nhóm còn phải làm gì?

> **PHÂN CÔNG LỊCH SỬ 01/10/2026.** Bảng mô tả trách nhiệm toàn dự án, không phải work order hiện tại cho evaluator. Theo [README](README.md), validator và audio/segments BTC đầy đủ deferred; runtime/memory/tools sản phẩm là dependency, không implement trong evaluator. Thứ tự hiện hành: [P0–P10](evaluation-implementation-plan.md).

Ngày kiểm tra: 01/10/2026. Căn cứ 46 file BTC thực nhận, đề PDF và flow hiện tại. Đây là **phân công theo vai trò/hạng mục**, chưa gán tên thành viên vì chưa có danh sách nhóm.

- [Tổng quan đề, inventory và các điểm cần hỏi BTC](tong_quan_de_bai_va_btc.md).
- [Những điểm cần hoàn thiện flow, ma trận M1/M2](can_sua.md).

Nguyên tắc: **tận dụng tài sản BTC, không xây lại nguồn sự thật; vẫn phải xây phần tích hợp và tạo bằng chứng chạy của nhóm**. Mock tool không phải backend đã nối; schema không phải validator đã chạy; rubric không phải judge đã chấm; public sample không phải dataset hoàn chỉnh.

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


## 1. Có sẵn để dùng — không cần tự tạo lại

| Hạng mục | BTC cung cấp gì | Thực nhận | Nhóm phải làm gì | Đầu ra cần có | Cách kiểm chứng / nguồn |
|---|---|---|---|---|---|
| Catalog chuẩn | Sản phẩm/biến thể/thuộc tính/successor/combo | 40 parent, 96 variant; CSV40 hàng | Dùng đúng snapshot; xây adapter tra cứu, không tự bịa giá/SKU | Catalog version và adapter | Đối chiếu products.json; CSV không đếm thêmSKU. R PUBLIC |
| Khuyến mãi | Điều kiện/thời hạn/stackable |13 record, README ghi14 | Dùng dữ liệu thực, xác nhận chênh lệch; không tự thêm chương trình | Promo manifest và test điều kiện | promotions.json; KM-04; MO.pricing_get_quote |
| Tồn kho theo ngày | Inventory timeline | Có JSON đầy đủ trong gói | Tích hợp ngày scenario/on và kiểm tra lúc chốt | Inventory adapter/contract tests | MO.inventory_check; SC dòng 23 |
| CRM seed |50 khách, định danh đa kênh, lịch sử | Có50 record, 49SĐT phân biệt | Nạp seed đúng; shared phone không tự gộp người | Seed script/id-resolution tests | crm_seed; DC §11 |
| Policy corpus |14 tài liệu/99 chunk | Có đủ 14/99 | Giữ nguyên raw/version/chunkID; phân quyền nội bộ | Corpus manifest + access policy | CL/DT/KM/NB/PB và DC §9 |
| RAG QA |60 câu đã gán chunk/expected_answer | Đủ60/6 loại | Không cần tự gán lại corpus chuẩn; vẫn chạy retriever và xử lý nhãn tranh chấp | Mapping chunk và dispute list | RAG Q20/Q57; E.rag_eval |
| Persona chuẩn |12 persona/prompt/patience | Đủ12 | Tái sử dụng prompt đúng spec; không cần sáng tác lại để chấm M2 | Persona config có version | simulator/personas.json; SIM |
| Rubric chuẩn |12 criterion/prompt/protocol | Có JSON | Nạp nguyên văn; không cần nghĩ bộJ01–J12 mới | Rubric version trong manifest | J; DC §12 |
| Public sample | Format/case minh họa |7 case/13 calls/39 turn | Dùng làm smoke test/adapter; không viết lại raw | Public compatibility report | SAMPLE01–07; SC |
| Scorer tham chiếu | Logic metric/CLI | Có 397 dòng Python | Giữ nguyên bản cho official report; đọc giới hạn, bổ sung riêng | Scorer hash/version + report BTC | E; DC §2 |

“Không cần tạo lại” không có nghĩa không cần đọc/kiểm thử. Ví dụ cần test chọn policy cũ cho đơn cũ, không được xóa bản cũ khỏi corpus để đơn giản hóa RAG. Các xung đột B01–B15 trong tổng quan phải được ghi nhận trước khi dùng làm ground truth chắc chắn.

## 2. Có mẫu/schema/logic tham chiếu — nhóm vẫn phải tích hợp hoặc chạy

| Hạng mục | BTC cung cấp gì | Thực nhận | Nhóm phải làm gì | Đầu ra cần có | Cách kiểm chứng / nguồn |
|---|---|---|---|---|---|
| Tool nghiệp vụ | Tên/required và mock Python | T + MO, 9hàm nghiệp vụ | Bọc thành MCP hoặc adapter, quản lý state/ngày, tool permission; đối chiếu policy/code | Tool adapter + contract tests | Cùng input phải đối chiếu output mock; báo tranh chấp, không âm thầm sửa. DC §3,10 |
| Scenario input | Mô tả format, 7 mẫu | Có SC, không phải bộ đầy đủ của nhóm | Parser/validator; calls động; channel/ASR/seed_history/date | Scenario loader và validation report | SAMPLE07 có 1 call vẫn chạy; ASR lỗi không thay bằng bản sạch. SC |
| Trace | JSON Schema | Có TR | Instrument Agent/tool thật; serialise đúng types/IDs; validate/cross-check coverage | full.jsonl, baseline.jsonl | Trace thực, đủ expected turns, không trộn run/config. TR |
| Call Brief | Schema | Có CB | Xây nội dung từ state, freshness tại thời điểm nhận diện, timestamp/precompute | Brief và latency logs | Required fields, precomputed_parts, nạp trong5sM1/3sM2. DC §6; L |
| Handoff Brief | Schema + tool | Có HB/T/MO | Tạo brief ngay khi chuyển, validate cả schema; ghi consultant riêng | Handoff trace/ticket/brief | Required đầy đủ; không chỉ subset scorer; không cần routing thật. DC §4; GD |
| Scorer/report | reference_eval.py, report mẫu | Có | Chạy trên trace nhóm; wrapper sinh A.6/delta và supplement | report_btc.json + table + coverage | Chạy lại từ artifacts được cùng số; không sửa official metric. Đ A.6; E |
| Extractor | Schema questions/claims/facts_used | Không có extractor Agent hoàn chỉnh | Trích từ lời Agent/tool thật, kiểm precision/recall bằng mẫu người | Extractor code/config và audit set | BTC có thể chấm tay20 turn; không lấy GT điền prediction. R dòng 36 |
| Judge | Rubric và prompt | Không có engine judge/verdict của nhóm | Selector, prompt, model call, output validation, human agreement | quality_report và ≥ 20 nhãn người | Applies_to/pass_if đúng; kappa/agreement; lỗi không PASS. J |
| Simulator | Spec8 rules +12 persona | Không có simulator engine | State machine/LLM customer, termination, log, 3 seed | Per-seed logs + stability report | SIM §1–5, mean/std/range, không lộ đáp án cho Agent |
| ASR |4 GT mẫu và rule chuẩn hóa | Không có audio/hypotheses | Chạy local ASR khi có audio; ITN, entity extraction, output mapping | hypotheses + WER/CER/entity report | Đủ IDs; báo riêng tiền/SĐT; không tính thiếu thành 0 lỗi. ASR |
| RAG | Corpus, QA, scorer retrieval | Không có index/retriever/results nhóm | Chunk/mapID, build retrieval, truy vấn60 câu; answer/version judge riêng | rag_results + retrieval/answer report | --rag không tự chạy retriever; coverage60; E.rag_eval |
| Memory check | Trường memory_expectation + heuristic | Có mô tả/code | Kiểm state thật: supersede/TTL/identity/delete; khai báo snapshot | Supplemental state report | Không suy từ chuỗi memory_writes rằng database đúng. SC; E.memory_checks |
| Guardrail | Regex/rubric/policy | Có rule tham chiếu | Mask đúng nơi, chống lộ nội bộ, AI honesty; audit toolargs/memory/external logs | Safety tests + redacted traces | Official0vi phạm không chứng minh toàn diện. DC §11; E/J |
| Latency | Định nghĩa/ngưỡng/cách đo | Có L và E.latency | Timestamp backend, warm-up view, hardware manifest, freshness/cold path | Latency report tái lập | ≥ 100 lượt, loại3 warm-up khỏi latency nhưng giữ quality trace. L |
| Trace ví dụ | Generator +2 trace/report | Có; mỗi trace33/39agent_text rỗng | Chỉ học format/check scorer, không nộp làm kết quả nhóm | Smoke test format | Không gọi latency ngẫu nhiên là số đo thật. make_example_trace.py |

Lưu ý tool: DC nói “mọi tool nhận on”, nhưng một số hàm mock không có tham số đó. Adapter phải theo chữ ký đã nhận và truyền ngày tới các hàm có xử lý thời gian; ghi câu hỏi gửi BTC, không blindly thêm on rồi làm hỏng lời gọi.

## 3. Nhóm phải tự xây, tự sinh, tự đo

| Hạng mục | BTC đã cho nền gì | Thực nhận | Nhóm phải làm gì | Đầu ra cần có | Cách kiểm chứng / nguồn |
|---|---|---|---|---|---|
| Dataset C.1 M1 | Catalog/policy/CRM/persona | Không có 120 transcript/40 audio của nhóm | Sinh≥ 120 transcript, ≥ 40 call audio/≥ 1h, ≥ 30 khách đa phiên, ≥ 10đa kênh; 1 ngành/2 vùng | Dataset + distribution/PII/readme | Đếm file/duration/customer/session/channel thật; Đ C.1 |
| Dataset C.1 M2 |3 ngành/biến thể/case gợi ý | Không có 250 transcript/100 audio của nhóm | ≥ 250 transcript, ≥ 100 audio/≥ 3h, ≥ 60đa phiên, ≥ 30đa kênh, 3 vùng, ≥ 20%nhiễu | Dataset extension/version | Chốt SKUcount với BTC; đếm coverage độc lập |
| Team Frozen | Public mẫu và định mức đề | Không có Frozen hoàn chỉnh do BTC phát cho nhóm | Gán GT/expectation, ≥ 20multi+ ≥ 5 hardM1, ≥ 40M2, freeze/version | Golden/Frozen manifest và data | Không dùng7public thay bộ riêng; Đ C.4 |
| Growth | Format tham chiếu | Không có tập Growth của nhóm | Từ gap/lỗi hợp lệ → dedup/PII → scenario → GT độc lập → review | Growth dataset/version | errors log không tự là test; không tự nhập Frozen |
| Agent/harness | Tool/schema/reference | Không có hệ thống nhóm tích hợp sẵn | Xây runtime/model/prompt/tool loop/fallback; chọnMCP/A2A | Hệ thống chạy được | Đ C.2–C.3; đủ shared state/chuyển việc thật |
| Memory | CRM/schema | Không có implementation nhóm | Working/episodic/profile; identity/freshness; M2TTL/provenance/delete | Store/MemoryAgent và tests | Cases đa phiên/đa kênh/shared phone |
| Official runner | CLI contract | Không có runner nhóm | Chạy fixed turns, full/baseline, resetstate, seed_history, artifact | run_eval CLI + traces | R dòng 34–36; không fine-tune/dùng GT cho Agent |
| Report orchestrator | Scorer | Chưa có lệnh toàn bộ pipeline nhóm | Một lệnh run→validate→score→table; suite applicability | Entry point + manifest/report | Đ C.4; không chép tay số vào slide |
| Metric bổ sung | Định nghĩa/logic tham chiếu | Cost/Tool-Call Accuracy chưa có trongE | Công bố công thức/mẫu số/missing; cost có modelprice/version | Supplemental metrics | Không gắn nhãn “official BTC” cho metric tự định nghĩa |
| Cải tiến M1 | Yêu cầu≥ 2feedback/≥ 1 cơ chế | Không có lifecycle của nhóm | Outcome+QA, Gap Loop hoặcExemplar, human review | Candidate/test/review records | Đ C.5; trước/sau có đo |
| Cải tiến M2 | Reflection/A-B gợi ý | Chưa có record/vòng đo nhóm | ≥ 2cơ chế; Reflection record/no-change nếu chọn; anti-bad-win/rollback | R0/R1/R2 + harm analysis | Cùng Frozen; ≥ 3 vòng; không chọn riêng run tốt |
| Review/release | Rubric/policy | Không có UI quyền duyệt/active version | Tách candidate/approved/tested/active; hash, rollback | Approval/version/release records | Chỉ active đúng bản đã đo; gate nội bộ ghi là đề xuất |
| Phân tích lỗi | Trace/report format | Chưa có≥ 10 lỗi Agent nhóm | Chọn và phân tích≥ 10 case sai, expected/actual/rootcause/retest | Error casebook | Đ F; không dùng lỗi generator giả làm lỗi Agent |
| Demo/UI/tài liệu | Đề yêu cầu | Gói BTC không cung cấp | UI, README, video, slides, architecture | Bộ nộp đầy đủ | Đ C.6/F; xem tổng quan§2.3 |

Bộ ASR eval ≥ 20 file nhóm là nghĩa vụ đo riêng, ngoài việc đạt số lượng audio phát triển. Có thể tái sử dụng tài sản nếu hợp đồng cho phép và khai báo rõ split; không được double-count để che thiếu coverage.

## 4. BTC giữ lại hoặc chưa nhận — cần chờ/xác nhận

| Hạng mục | BTC nói cung cấp/giữ gì | Thực nhận | Nhóm phải làm gì | Đầu ra cần có | Cách kiểm chứng / nguồn |
|---|---|---|---|---|---|
| Hidden test |41 scenario, 19 hard; phát/chạy lúc chấm | Không có file | Chuẩn bị runner tương thích public; không đoán/lấy đáp án hidden | CLI đã kiểm public + contract tests | R §Giữ lại; DC §11 |
|8 GT ASR còn lại |BTC giữ; team nhận D01–D04 |4 GT/34 turn | Giữ manifest sample/full, không báo 12 GT đã nhận | Asset status | R dòng 30; ASR description |
| Audio BTC |Bộ đầy đủ 12 hội thoại,~12 phút | Không có audio trong 46 file | Xin audio mẫu/đợt phát chính thức; vẫn chuẩn bị ASR bằng audio nhóm | Audio receipt manifest | Đếm file/duration thật, không dựa README |
| Diarization segments |audio/id.segments.json | Không có | Xin định dạng/file, chuẩn bị adapter/cách đo | Segment manifest + schema check | DC §8; E.wer_cer |
| validate_scenarios.py |README nhắc BTC dùng kiểm catalog/scenario | Không có file | Xin script/quy tắc; tạm làm contract checks riêng, không giả danh scriptBTC | Open issue + report tự kiểm | R dòng 22 |
| make_audio.py/script sinh data |README nói BTC giữ script sinh | Không có | Không phải tự viết lại đúng scriptBTC; tự tạo data nhóm theo yêu cầu | Data generation pipeline của nhóm | R dòng 20,30; DC §2 |
| Nhãn/policy/mock tranh chấp |Q20/Q57/SAMPLE01–03 và các biên | Có cả nguồn mâu thuẫn | Gửi B01–B15; không sửa raw bằng phỏng đoán | Dispute registry + phản hồi BTC | Tổng quan§8 |
| Cách đếm SKU/20+5/độ lệchseed |Định mức có, cách diễn giải chưa đủ | Chưa có xác nhận riêng | Hỏi BTC; báo các số thành phần/mean/std/range | Quyết định được dẫn nguồn | Đ C.1/C.4; SIM §5 |

Không để việc chưa có hidden/audio đầy đủ chặn mọi tiến độ: vẫn làm runner, dataset nhóm, extractor, local ASR và report trên phần hợp lệ đã có. Nhưng không đánh dấu suite BTC đầy đủ là PASS.

## 5. Thứ tự việc nhóm theo phụ thuộc

### 5.1. Làm nền M1 trước

| Thứ tự / vai trò gợi ý | Phụ thuộc | Việc cần làm | Đầu ra và điểm kiểm tra | Liên hệ audit |
|---|---|---|---|---|
|0 · Data lead + trưởng nhóm |Không | Chốt snapshot 46 file, inventory/hash, tranh chấp B01–B15; chọn M1/M2 phạm vi | Source manifest; ghi yêu cầu BTC/đề xuất riêng |F05/F15 |
|1 · Data + domain reviewer |0 | Sinh data/GT đúng policy/ngày; chọn Frozen; tag hard family; có ASR eval≥ 20 file | Data validation + count/coverage; chưa đủ audio BTC ghi thiếu |F13 |
|2 · Backend/tool + memory |0 | Tích hợp tools/seed/history/date; state vàbrief/handoff | Contract tests; sharedphone/oldpolicy/stock/TTL tùy mức |F03/F04 |
|3 · Harness/evaluation |1,2 | Runner fixed-turn full/baseline; isolated state; waitmemory; trace/extractor | Trace schema + completeness pass; extractor audit20 turn |F01/F02 |
|4 · ASR + perf |1,2, 3 | Local ASR/ITN/entity; timestamp/brief refresh; cost và ASR time | Audio coverage, raw/normalized, ≥ 100 lượt latency theo L |F07/F08 |
|5 · Evaluation/report |3,4 | ScorerBTC + supplemental; A.6/delta/turns-scenario | Một lệnh xuất report và errors; chốt R0 |F09 |
|6 · Improvement + QA |5 | Outcome+QA → Gap Loop/Exemplar; candidate+Growth; người duyệt | Candidate có nguồn/expected test độc lập; eval lạiR1 |F11/F17 |
|7 · Evaluation + cả nhóm |6 | Phân tích≥ 10 lỗi; soR0/R1/baseline; viết hạn chế/demo | Báo cáo có số thật, ≥ 10 case; repo/video/UI/slides |F12 |

M1 chưa có rubric judge vẫn có thể chấm phần assert được; nếu có tiêu chí lời thoại không assert được thì theoĐ A.3 khai báo judge và rubric trước. Không gán nhãn “M1 thì cấm judge” hay “M2 thì bỏ assertion”.

### 5.2. Bổ sung M2 sau nền M1

| Thứ tự / vai trò | Phụ thuộc | Việc bổ sung | Nghiệm thu | Audit |
|---|---|---|---|---|
|8 · Data |1 | Mở rộng C.1 và ≥ 40 scenario, thêm hard family M2 | Đếm đúng transcript/audio/người/kênh/nhiễu/SKU đã xác nhận |F13 |
|9 · Retrieval + evaluation |0,3, 5 | RAG60 QA/99 chunk; retrieval3/5, fullmulti, abstain, answer/version | Coverage60, qid/chunkmapping, report và tranh chấp nhãn |F06 |
|10 · Voice/ASR |4 | Diarization, voice TTFA, ≥ 2 phiên đồng thời | Segments đủ, protocol đúng; TTFA p95 ≤ 2,5s/Brief ≤ 3s |F07/F08 |
|11 · QA/judge |3,5 | Selector/rubricJ01–J12, validate/retry; người chấm≥ 20 cặp | Agreement/kappa, phân tích lỗi; không đảo hardFAIL |F14 |
|12 · Simulator |3,5, 8 | State/patience/8 rules/12 turn/log; 3 seed | Requiredlogs vàmean/std/range; không trộn fixed-turn |F10 |
|13 · Evalmetrics |3,5 | Tool-Call Accuracy/cost/p50p95; CTC tùy chọn | Formula/support/expected/observed, phân biệt tool attempt/tool success |F09 |
|14 · Improvement + QA |6,8–13 phù hợp suite | Thêm cơ chế thứ 2, chạy R2, harmanalysis/rollback | ≥ 3 vòng, cùng Frozen; ảnh hưởnghại có evidence; hashđúng version |F11/F17 |

Các vai trò có thể do cùng người kiêm nhiệm. Không bắt buộc thêm framework/microservice chỉ để khớp tên vai trò; nhóm chọn kiến trúc đáp ứng MCP hoặcA2A của đề.

## 6. Định nghĩa “xong” cho phần Evaluation

Một phiên bản chỉ có thể được mô tả là đã đánh giá đầy đủ khi:

1. Input/GT/source version và suite áp dụng được chốt; số file/case/turn biết rõ.
2. Runner đã sinh trace thật, schema/completeness hợp lệ, extractor được đối chiếu người.
3. Baseline/full cùng điều kiện ngoài memory; state tách đúng; không rò GT vào Agent.
4. Official report tái lập bằng scorerBTC; supplementary reports ghi rõ công thức và không ghi đè sốofficial.
5. ASR/RAG/judge/sim/latency theo mức được báo đầy đủ hoặc **chưa hoàn tất** với lý do; missing không bị ẩn.
6. Có bảng A.6/delta và before-after R0/R1; M2 có R2; phân tích≥ 10 lỗi thật.
7. Candidate được duyệt/đo trước active; report gắn đúng hash; rollback có thể truy lại.
8. Các tranh chấp BTC còn mở được công khai, không kết luận đạt phần chưa đủ bằng chứng.

Mục1–6 là diễn giải yêu cầu đề/DC thành hợp đồng nghiệm thu; quy trìnhhash/candidate/gate cụ thể ở mục 7 là thiết kế quản trị nhóm để thực hiện an toàn, không phải mọi field đượcBTC bắt buộc.

## 7. Những việc không cần làm lại hoặc không nên làm

- Không tự tạo lại catalog/policy chuẩn để né ca khó; giữ bản cũ, nội bộ và nhiễu trong corpus đánh giá đúng phạm vi.
- Không sinh lại public/hidden để gọi là bộ BTC; hiddenBTC giữ, public chỉ là mẫu.
- Không viết scorer mới thay official rồi so số giữa nhóm; metric mới để nhánh supplemental.
- Không lấy generatortrace/report_example làm thành tíchAgent hoặc latency thật.
- Không xây lại12 criterion khi đã có rubric; công việc còn thiếu là chọn đúng, gọi judge, validate và đối chiếu người.
- Không cần tổng đài thật/routing nhân viên cụ thể để đạt handoff trong đề mô phỏng.
- Không coi Source Gate là cổng “xétcase vàoFrozen”, hoặc catalog là luật xét nguồn học.
- Không tự sửa nhãnBTC để pipelinePASS; tạoissue với bằng chứng và chờ xác nhận.

## 8. Kết quả của đợt audit này

Chỉ tạo ba tài liệu Markdown: can_sua.md, tong_quan_de_bai_va_btc.md, phan_cong_btc_va_nhom.md. Chưa sửa flow/ảnh/repo/data, chưa triển khai runner, chưa sửa scorer và chưa chạy benchmark Agent. Điểm6,97/10M1 và6,02/10M2 trong can_sua.md là **điểm thiết kế tạm tính**, không phải chất lượngAgent đã đo.
