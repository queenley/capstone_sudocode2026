# Cần sửa — audit thiết kế Evaluation theo đề và gói BTC

> **AUDIT LỊCH SỬ 01/10/2026, không phải chuẩn implementation hiện hành.** Điểm số/thiếu sót mô tả flow tại thời điểm audit. Trước code đọc [README](README.md) → [plan](evaluation-implementation-plan.md) → flow/contracts; không khôi phục hành vi cũ hoặc mở lại validator/audio BTC deferred từ nội dung bên dưới. Giữ audit để truy vết.

Ngày: 01/10/2026. Đối tượng: [evaluation-flow.md](evaluation-flow.md), toàn bộ nội dung và 32 sơ đồ; đối chiếu 46 file BTC thực nhận và 17 trang đề PDF. **Chỉ đánh giá thiết kế**, không chứng nhận implementation hay Agent đã đạt benchmark. Lần này giữ nguyên flow, hình, repo và BTC.

## 1. Kết luận nhanh

Flow **chưa đáp ứng hết**. Đã làm tốt: baseline/full, memory đa phiên, phân biệt QA cuộc gọi với evaluation phiên bản; assertion/judge/hybrid; human review trước active; version/rollback; Frozen/Growth và Source Gate có ranh giới.

Thiếu lớn: nhánh RAG đầy đủ, diarization M2, Tool-Call Accuracy/cost, R2 cho M2, yêu cầu báo cáo ≥ 10 lỗi, và hợp đồng kiểm chứng bổ sung cho các heuristic của scorer. ASR/latency/simulator có khung nhưng chưa đủ chi tiết để tránh đo sai.

| Mức | Phạm vi tính | Điểm đạt/tổng yêu cầu | Điểm thiết kế |
|---|---|---:|---:|
| M1 |33 yêu cầu lõi trong ma trận C |23/33 | **6,97/10** |
| M2 |33 lõi +16 bổ sung M2 |29,5/49 | **6,02/10** |

Đây là điểm **tạm tính về độ đầy đủ thiết kế Evaluation**, không phải điểm dự án theo trọng số BTC. Các câu hỏi chưa chốt với BTC được báo riêng ở §7. Không lấy thiếu audio/hidden làm bằng chứng Agent kém, cũng không coi tài liệu là bằng chứng đã triển khai.

Lỗi/rủi ro nghiêm trọng không được điểm trung bình che:

1. Scorer có thể cho điểm đẹp khi trace/GT/claim thiếu hoặc chỉ có tên slot; flow chưa đủ gate bổ sung để phát hiện.
2. Handoff cần validate schema thật, không chỉ check subset trường scorer.
3. RAG và diarization chưa có pipeline nên chưa thể tuyên bố đủ M2.
4. Hai vòng R0/R1 chưa đủ M2 ≥ 3 vòng.
5. Đáp án/scorer/mock của BTC có chỗ khác tài liệu; không được âm thầm chọn nguồn để “làm cho PASS”.

Xem [tổng quan và sổ 46 file](tong_quan_de_bai_va_btc.md) cùng [phân công](phan_cong_btc_va_nhom.md).

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


## 2. Cách chấm và giới hạn

- Đơn vị là một nghĩa vụ kiểm chứng độc lập, không đếm lại cùng nghĩa vụ chỉ vì xuất hiện ở cả PDF/DC/GD.
- Đáp ứng=1; một phần=0,5; thiếu/sai=0. Điểm=10×tổng điểm/số yêu cầu áp dụng.
- M1=23/33×10=6,9697; M2=(23+6,5)/(33+16)×10=6,0204. Phần M2 bổ sung riêng=6,5/16, không phải điểm M2 tổng.
- “Đáp ứng” chỉ nghĩa flow có đường đi/giải thích đáp ứng yêu cầu; không nghĩa đã có mã hoặc đã chạy.
- Đề xuất riêng như Source Gate, support 3 calls, retry 1 lần, HybridAND, naming artifact, release không-regression không tạo thêm yêu cầu BTC để trừ điểm.
- Calls-to-Close không vào mẫu số bắt buộc vì GD Team 8 Q3 nói M2 không bắt buộc, dù đề gốc liệt kê; khuyến khích báo riêng.
- Dataset phát triển C.1, UI và kiến trúc ngoài Evaluation được kiểm kê tại tổng_quan; không trừ flow vì thiếu sơ đồ runtime ngoài phạm vi.
- Câu hỏi biên/asset chưa nhận không được gán 0 cho “hệ thống không đạt”. Ma trận chấm phần nghĩa vụ thiết kế đã xác định; điểm vẫn tạm tính chờ BTC làm rõ các hợp đồng ảnh hưởng.

## 3. Ma trận yêu cầu → flow

### 3.1. Lõi áp dụng M1 và M2

| ID | Yêu cầu kiểm chứng độc lập | Nguồn | Vị trí flow hiện tại | Trạng thái | Điểm | Nhận xét |
|---|---|---|---|---|---:|---|
| C01 | Tách bộ nhóm/public/hidden; không dùng public thay bộ riêng | Đ C.4 tr.6; DC §2; R §PUBLIC | §16 | Đáp ứng | 1 | Đã tách đúng vai trò. |
| C02 | M1 ≥ 20 kịch bản đa phiên + ≥ 5 ca khó, kỳ vọng khai báo trước | Đ C.4 tr.6; Đ B tr.13 | §16,18 | Đáp ứng | 1 | Có định mức; cần giải thích cách đếm dấu “+”. |
| C03 | Bao phủ tình huống temporal, đa kênh, hard cases BTC | DC §9–11; SC | §16–18,24 | Một phần | 0,5 | Có ví dụ và trường input, chưa có coverage matrix từng họ lỗi. |
| C04 | Scenario/GT gắn nguồn catalog, policy; kiểm tra trước chạy | DC §2,10; SC | §6,12,15–17 | Đáp ứng | 1 | Đã có xác minh GT và version. |
| C05 | Runner CLI nhận thư mục scenario/config, xuất trace | R §Quy trình chấm chéo; Đ C.4 | §17 | Đáp ứng | 1 | Hợp đồng runner đã nêu. |
| C06 | Đa phiên đúng thứ tự, chờ memory; state tách giữa run | SC; Đ A.6 | §7,17 | Đáp ứng | 1 | Có ranh giới working memory và memory phiên trước. |
| C07 | Input ASR lỗi, channel, seed_history, ngày cộng dồn/on | SC dòng 8–23 | §17 | Đáp ứng | 1 | Đã nêu các đầu vào quan trọng; adapter cần xử lý chữ ký tool. |
| C08 | Baseline chỉ khác nạp memory; cùng test/model/tham số | Đ A.6 tr.13; GD Team 5 Q7,10 | §17,23 | Đáp ứng | 1 | Đúng thiết kế paired comparison. |
| C09 | Trace đúng schema, memory evidence khi được kiểm tra | DC §2,11; TR; SC memory_expectation | §7,17,21 | Một phần | 0,5 | Chưa biến memory_writes/state validation thành điều kiện bắt buộc theo case. |
| C10 | Extractor questions/claims có cách trích và kiểm tra người | DC §2; R dòng 36 | §21 | Đáp ứng | 1 | Có audit ngẫu nhiên 20 lượt; không lấy nhãn GT làm prediction. |
| C11 | Handoff đúng ca, brief đủ required schema | DC §4; HB; E check_call | §4,18 | Một phần | 0,5 | Nêu brief/TSR nhưng chưa có nhánh validate toàn bộ schema ngoài scorer. |
| C12 | RQR và quy tắc xác nhận lần hai | Đ A.1; DC §5; E repeat_question_rate | §21 | Một phần | 0,5 | Chưa thể hiện scorer bỏ cả call khi must_not_ask rỗng. |
| C13 | CCR: fact thực sự được dùng đúng, không chỉ xuất hiện slot | Đ A.2; E context_carryover_rate | §21 | Một phần | 0,5 | Nêu ý nghĩa đúng, thiếu bước kiểm chứng giá trị/ngữ cảnh ngoài heuristic. |
| C14 | TSR assertion khai báo trước; mẫu số/hard case/thiếu dữ liệu | Đ A.3; DC §11; E check_call/task_success_rate | §18–20 | Đáp ứng | 1 | Đã tách official và supplemental, hard FAIL không bị judge đảo. |
| C15 | HR theo claim; riêng giá/KM; coverage GT và claim | Đ A.4; E hallucination_rate | §21,23 | Một phần | 0,5 | Chưa có nhánh xử lý claim không có field GT/không extract được. |
| C16 | Guardrail PII, nhận là người, nội bộ, chuyển máy thừa | DC §11; E guardrail_violations | §18,21 | Một phần | 0,5 | Có chỉ số nhưng chưa đủ kiểm tra bổ sung ngoài regex/scorer. |
| C17 | Memory expectation: supersede, đúng hồ sơ, trạng thái thực | SC dòng 18; DC §11; E memory_checks | §7,17,21 | Một phần | 0,5 | Chưa tách kiểm tra trạng thái thật với kiểm tra chuỗi sàng lọc. |
| C18 | Bảng A.6 tự sinh gồm baseline/system/delta | Đ C.4; Đ A.6; E main | §21,23 | Một phần | 0,5 | Có artifact table nhưng chưa chốt adapter thêm delta mà CLI BTC thiếu. |
| C19 | Số lượt trung bình/kịch bản trong A.6 | Đ A.6 tr.13; E avg_turns | §21 | Thiếu | 0 | Thiếu; scorer hiện là trung bình/cuộc gọi, khác đơn vị. |
| C20 | Ngưỡng RQR ≥ 40% giảm tương đối, TSR ≥ 70%, HR giá/KM ≤ 5% | Đ C.4 tr.7; E main | §23 | Đáp ứng | 1 | Có cả trường hợp baseline RQR =0 không tự PASS. |
| C21 | ASR local, audio → hypothesis → WER/CER | Đ C.1; DC §8 | §22 / hình 28–29 | Đáp ứng | 1 | Đã có nhánh ASR riêng. |
| C22 | ASR BTC + ≥ 20 file nhóm; kiểm kê coverage thực nhận | DC §8; R §Giữ lại | §16,22,26 | Một phần | 0,5 | Có guard thiếu tài sản nhưng thông tin BTC hiện không có đã lỗi thời. |
| C23 | Chuẩn hóa số/ITN; entity exact-match tiền và SĐT riêng | Đ A.5; ASR normalization_rule; E wer_cer | §22 | Một phần | 0,5 | Chỉ ghi normalization chung, chưa tách raw/normalized/ITN và hai loại entity. |
| C24 | Mốc/giới hạn latency, brief freshness + precompute | DC §1,6; L | §17,22 | Một phần | 0,5 | Có ngưỡng và precompute; thiếu freshness bắt buộc trong mốc nạp brief. |
| C25 | ≥ 100 lượt, bỏ 3 warm-up; cùng hardware; p50/p95 tái lập | L §Quy tắc; E latency | §22 / hình 31 | Một phần | 0,5 | Đúng ý tưởng nhưng chưa chốt latency view hợp schema, khác raw scorer. |
| C26 | Đo riêng thời gian ASR/phút audio, không nhập TTFT | L quy tắc 6 | §22 | Một phần | 0,5 | Có loại ASR khỏi TTFT, chưa nêu đầu ra ASR time/phút. |
| C27 | Ước tính chi phí/cuộc gọi, nêu model/tier | GD Team 5 Q10; Đ tiêu chí 7 | §7,21 | Thiếu | 0 | Có tokens nhưng chưa có phép tính/báo cáo cost. |
| C28 | Ít nhất 2 nguồn feedback hợp lệ | Đ C.5 tr.7 | §8–11 | Đáp ứng | 1 | Outcome và điểm QA/evaluation đều có; nên ghi tên rõ. |
| C29 | M1 ≥ 1 cơ chế cải tiến và test chống tái phạm | Đ C.5 tr.7 | §5–6,12–15 | Đáp ứng | 1 | Gap Loop có FAQ candidate và Growth test. |
| C30 | R0 → cải tiến → R1 trên cùng bộ giữ nguyên | Đ C.5 tr.7 | §23 | Đáp ứng | 1 | Phân biệt trong-vòng và giữa-vòng đúng. |
| C31 | Báo cáo phân tích ≥ 10 trường hợp sai | Đ F tr.9 | §21,25 | Thiếu | 0 | Có errors artifact nhưng chưa yêu cầu chọn/phân tích ít nhất 10 lỗi. |
| C32 | Xác định thay đổi cần người duyệt trước áp dụng | Đ C.5 tr.7 | §6,12–14 | Đáp ứng | 1 | Hai nhánh hội tụ review/eval trước active. |
| C33 | Không fine-tune; cải tiến dữ liệu/memory/prompt/điều phối | Đ C.5 tr.7 | §5–14,23 | Đáp ứng | 1 | Các đường cập nhật mô tả đều ở tầng hệ thống, không train trọng số. |

### 3.2. Phần bổ sung M2

| ID | Yêu cầu kiểm chứng độc lập | Nguồn | Vị trí flow hiện tại | Trạng thái | Điểm | Nhận xét |
|---|---|---|---|---|---:|---|
| M01 | Bộ test M2 ≥ 40 kịch bản | Đ C.4 tr.6 | §16 | Đáp ứng | 1 | Đã có định mức. |
| M02 | Judge rubric J01–J12 đúng applicability/pass_if | DC §12; J | §19–20,27 | Một phần | 0,5 | Pipeline tốt nhưng J01 diễn giải rộng thành mọi fact; phải giữ sản phẩm/rào cản. |
| M03 | Judge đối chiếu người ≥ 20 mẫu, agreement/kappa | Đ C.4; DC §12; J agreement_protocol | §20 | Đáp ứng | 1 | Có protocol, version và xử lý judge lỗi. |
| M04 | RAG Recall@3/@5 trên 60 câu và 99 chunk BTC | DC §7,9; RAG; E rag_eval | §21 chỉ nhắc --rag | Thiếu | 0 | Chưa có nhánh retrieval/input/output. |
| M05 | RAG full-recall multi-hop, abstain/false-abstain | DC §9; E rag_eval | Không có | Thiếu | 0 | Cần coverage và mẫu số riêng. |
| M06 | Version accuracy/chất lượng answer RAG | R PUBLIC dòng 14; E rag_eval note | Không có | Thiếu | 0 | Scorer không tự chấm; cần người/judge riêng. |
| M07 | Diarization từ audio segments chuẩn | DC §8; E wer_cer | §22 chưa có | Thiếu | 0 | Thiếu nhánh segments → speaker mapping → báo cáo. |
| M08 | Simulator 8 quy tắc, state/patience/≤ 12 lượt | SIM §1–3 | §22 / hình 28,30 | Một phần | 0,5 | Có 3 seed/8 quy tắc nhưng chưa rõ state và dừng. |
| M09 | Simulator log bắt buộc theo persona/call/seed | SIM §4 | §22 / hình 30 | Một phần | 0,5 | Có trace/outcome, thiếu patience_trace, n_turns, ended_by. |
| M10 | Simulator 3 seed, độ lệch TSR ≤ 10 điểm, không lộ GT | SIM §5; GD Team 8 Q2 | §19,22 | Một phần | 0,5 | Có mean/std và tách fixed-turn; thiếu ngưỡng và phép đo “độ lệch” cụ thể. |
| M11 | Voice TTFA p95 ≤ 2,5s; brief ≤ 3s | DC §1; L | §22 / hình 31 | Đáp ứng | 1 | Có ngưỡng voice. |
| M12 | Kiểm chứng M2 ≥ 2 phiên đồng thời | DC §1 | Không có | Thiếu | 0 | Thiếu nhánh kiểm tra tải demo trong hiệu năng. |
| M13 | ≥ 2 cơ chế cải tiến; Reflection có cấu trúc nếu chọn | Đ C.5 tr.7 | §8,11 | Một phần | 0,5 | Có Gap + Reflection nhưng bỏ lesson các call thường; cần record no-change nếu chọn Reflection mỗi call. |
| M14 | Ít nhất 3 vòng đo cải tiến R0/R1/R2 | Đ C.5 tr.7 | §23 | Thiếu | 0 | Mới thể hiện R0/R1. |
| M15 | Phân tích cải tiến gây hại, không học hứa sai, rollback | Đ C.5 tr.7 | §11,14,23–25 | Đáp ứng | 1 | Đã có bad-win filter, regression và rollback. |
| M16 | Tool-Call Accuracy với expected calls/args | Đ C.4 tr.7 | §18,21 | Thiếu | 0 | TSR không thay Tool-Call Accuracy; chưa định nghĩa metric riêng. |

### 3.3. Chưa đủ bằng chứng hoặc ngoài mẫu số

| Nội dung | Kết luận | Vì sao không gán điểm tuân thủ |
|---|---|---|
| Runner/extractor đã implement/chạy thật | Chưa xác minh | Đợt này audit thiết kế, không benchmark Agent |
| Hệ thống đạt 5 metric/ngưỡng | Chưa xác minh | report_example là synthetic, không trace Agent nhóm |
| Audio/segments BTC đầy đủ | Chưa nhận |46 file không có audio; 4 GT mẫu khác 12 đầy đủ |
| Hidden 41/19 | BTC giữ | Không phải file nhóm có quyền đọc hôm nay |
| Cách đếm 100 SKU M2 | Cần BTC xác nhận | Parent/variant chưa có quy tắc rõ |
| Hard 5 nằm trong 20 hay cộng riêng | Cần BTC xác nhận | Flow đã nêu nguyên định mức; không tự biến thành luật 25 |
| “Độ lệch TSR ≤ 10 điểm” range hay std | Cần BTC xác nhận | Yêu cầu 3 seed vẫn rõ; báo cả range/std |
| Calls-to-Close bắt buộc? | Không tính bắt buộc theo GD | Giữ cả sự khác biệt với PDF |
| Release gate không-regression mọi chỉ số | Đề xuất nhóm | Không phạt tuân thủ BTC vì không dùng đúng gate đề xuất |

## 4. Những điểm cần sửa

P0: có thể làm kết luận đánh giá sai. P1: thiếu yêu cầu hoặc đầu ra bắt buộc. P2: làm rõ tài liệu và quyết định thiết kế. Không cần bỏ cấu trúc 6a–16; trọng tâm là mở rộng ô 15.

| Fix | Ưu tiên, vị trí | Vấn đề và tác động | Sửa luồng thế nào | Điều kiện nghiệm thu / nguồn |
|---|---|---|---|---|
| F01 | P0 · §17–18,21; hình 15/17/18/27 | Trace thiếu hoặc trộn cấu hình có thể vẫn được scorer nhận, làm sai mẫu số. | Manifest các ID/call/turn dự kiến → schema validation → completeness → scorer BTC và kiểm tra bổ sung. | Phát hiện missing, duplicate, unknown ID, config trộn; không âm thầm bỏ case. Giữ raw report. TR; E.load_trace/check_call/TSR. |
| F02 | P0 · §18,21; hình 18/27 | CCR/HR trong lời giải thích mạnh hơn điều script thực kiểm. Tên slot đúng chưa chứng minh giá trị đúng. | Trace thật → extractor audit → kiểm fact/value/provenance; claim thiếu GT đưa vào danh sách chưa chấm được. | Có test slot đúng nhưng value sai, claim bị bỏ sót, field thiếu GT; báo coverage riêng. Đ A.2/A.4; E.CCR/HR. |
| F03 | P0 · §4,18; hình 3/18 | Handoff brief đúng vài trường chưa đủ schema; tool args đúng chưa chứng minh tool thành công. | Handoff → validate HB → kiểm tool result/state → official và supplemental outcome. | Thiếu required field phải bị phát hiện; tool error không được diễn giải là đã tạo đơn thành công. DC §4; HB; E.check_call. |
| F04 | P0 · §7,17,21 | Memory check chỉ là sàng lọc chuỗi, có thể bỏ sót TTL, supersede, nhầm hồ sơ, PII. | Case có memory_expectation → bắt buộc memory_writes và bằng chứng state → kiểm state/provenance/PII. | Kiểm old value bị vô hiệu, không ghi hồ sơ khác, TTL/deletion khi áp dụng. Không suy PASS từ việc thiếu log. SC; TR; E.memory_checks/guardrail. |
| F05 | P0 · §12,16–18 | Nhãn, mock và policy BTC có mâu thuẫn; chọn âm thầm một phía sẽ làm lệch GT. | Kiểm tính nhất quán trước freeze → sổ tranh chấp → xin BTC xác nhận; giữ nguyên raw version. | Q20/Q57/SAMPLE01–03 có bằng chứng hai phía; không lấy đáp án Agent sinh để sửa GT. Tổng quan §8. |
| F06 | P1 · §15,21–22; hình 15/27/28 | RAG mới có chữ --rag, chưa có pipeline M2. | Policy +60 QA → retrieve/map chunk ID → coverage → Recall@3/@5/full multi-hop/abstain → chấm answer/version riêng. | Đủ 60 qid, không trùng hoặc bỏ query khó; có retrieval config, mẫu số và báo cáo answer/version. DC §7,9; E.rag_eval. |
| F07 | P1 · §22; hình 28–29 | ASR chưa tách rõ raw/normalization/ITN/loại entity; thiếu diarization M2. | Manifest audio → ASR local → raw hypothesis → WER/CER chuẩn hóa và entity sau ITN; M2 thêm segments/speaker scoring. | Báo coverage BTC mẫu/đầy đủ/nhóm, tiền và SĐT riêng; thiếu hypothesis không được lặng bỏ. Diarization dùng đúng phép đo E. DC §8; ASR. |
| F08 | P1 · §22; hình 31 | Thiếu ASR time/phút, refresh trong Call Brief, kiểm tra đồng thời M2; warm-up chưa chốt cách xuất hợp schema. | Giữ raw trace → đánh dấu 3 warm-up → latency view riêng; timestamp gồm refresh; đo voice ≥ 2 phiên, báo ASR time. | ≥ 100 lượt theo L, công bố raw/effective N; không xóa trace chất lượng hoặc gán null trái schema. Đo đúng TTFT/Total/TTFA/Brief. L; DC §1,6. |
| F09 | P1 · §21,23; hình 27/32 | Chưa rõ delta và turns/scenario của A.6; chưa có cost/Tool-Call Accuracy. | Report BTC → adapter thêm delta và mean turns/scenario; metric cost/tool riêng có công thức. | Một lệnh sinh bảng; giữ turns/call của E; nêu expected/observed, token usage và chi phí. Đ A.6/C.4; GD Team 5 Q10. |
| F10 | P1 · §22; hình 30 | Simulator thiếu chi tiết state, log, termination và tiêu chuẩn ổn định. | State → 8 quy tắc theo thứ tự → dừng vì patience/timeout 12 lượt → log bắt buộc → thống kê 3 seed. | Có test 8 quy tắc; đủ patience_trace/ended_by/n_turns; báo mean/std/range, chờ BTC chốt “độ lệch”. Không cap fixed-turn ở 12. SIM. |
| F11 | P1 · §8,11,23; hình 7/10/32 | M2 mới có hai vòng; Reflection có thể bỏ record ở call thường. | QA mỗi call; nếu chọn Reflection, có record lesson/no-change; chỉ candidate mới qua pool. Thêm R0→R1→R2. | Định danh ≥ 2 cơ chế, ≥3 report cùng Frozen; có phân tích hại/rollback. Không buộc no-change thành lesson. Đ C.5. |
| F12 | P1 · §21,25; hình 27 | File errors chưa đủ yêu cầu phân tích ≥ 10 trường hợp sai. | Errors đầy đủ → chọn ≥ 10 case → root cause/fix/retest/trade-off. | Mỗi case có expected/actual, call/turn, nguyên nhân, hành động; không lấy 10 dòng trùng một lỗi. Đ F tr.9. |
| F13 | P1 · §16–18 | Chưa có coverage matrix từng họ ca khó BTC. | Registry scenario → tag mức/hard family/date/channel/privacy → coverage check trước freeze. | Có case ID cho các họ lỗi DC §11: ASR, shared phone, old policy, tồn kho, COD, deletion, holiday… Không tuyên bố đã có hidden. |
| F14 | P1 · §19,27; hình 20–22 | J01 diễn giải thành “ít nhất một thông tin” rộng hơn rubric “sản phẩm hoặc rào cản”. | Nạp rubric nguyên văn; sửa bản tóm tắt J01; selector theo hợp đồng và evidence, không né lỗi do thiếu hành động. | Call 2 chỉ nhắc diện tích không tự PASS J01. Giữ J07 theo applies_to official; hành động bị bỏ do assertion kiểm. J. |
| F15 | P2 · §1,16,26 | Ghi BTC không có trong môi trường đã lỗi thời; có định mức đề bị gắn nhãn REPO. | Cập nhật nguồn/version/inventory; gắn PDF/DC cho yêu cầu bắt buộc. | Ghi đúng 46 file, 4 GT, 0 audio; không nói đã nhận 12 audio. R; Đ C.4. |
| F16 | P2 · §3,8, 12,23 | Dễ hiểu Source Gate, Reflection mỗi call, dùng chung runner là các vi phạm BTC tuyệt đối. | Nêu Gate là chính sách nhóm; được phân tích lỗi Frozen nhưng công bố bộ đã xem; chung code runner không sai. | Không chặn memory trong scenario; không đổi vai trò Frozen/Growth; không nói BTC bắt buộc support 3 calls. Đ C.5; GD Team 8 Q2. |
| F17 | P2 · §13–14,23; hình 12/13/32 | Chưa rõ đường R0 khi chưa có active/candidate; release gate chứa nhiều lựa chọn nội bộ. | Thêm đường benchmark initial version; release dùng suite applicability và version hash. | R0 thất bại vẫn lưu làm mốc; M1 không bị chặn bởi suite M2 không áp dụng; candidate sửa phải đo lại. Flow §23; thiết kế nhóm. |

F01–F17 là **đề xuất cho lần sửa sau**, chưa áp dụng vào flow hoặc code.

## 5. Kiểm toán công thức và edge case

### 5.1. Không diễn giải scorer mạnh hơn thứ nó kiểm

| Điểm | Tài liệu / hành vi thực | Cách trình bày và bổ sung |
|---|---|---|
| RQR | E dòng 61–86 bỏ call có must_not_ask rỗng; repeated-confirm chỉ chạy ở các call còn lại. | Giữ RQR official; audit confirmation trên mọi call bằng metric riêng. |
| CCR | E dòng 88–102 dùng tên slot trong facts_used hoặc key tool args. | Kiểm thêm giá trị/mục đích; không nói scorer đã chứng minh dùng fact đúng ngữ cảnh. |
| TSR | E dòng 123–186 bỏ falsy success_if; scenario đạt khi mọi call được chấm đều đạt; hard denominator lấy mọi hard flag. | Báo scheduled/eligible/scored/missing và call không có assertion; không tự sửa mẫu số official. |
| Null và negative-only | args_match bỏ expected value None; trace rỗng có thể qua một số điều kiện chỉ cấm hành động. | Thiếu turn là INCOMPLETE. tool_called:null không tự có nghĩa cấm mọi tool; phải đọc must_not_call_tools. |
| Handoff | Scorer kiểm brief_must_contain, không validate toàn bộ HB. | Thêm schema validator và kiểm tool result/state. |
| HR | E dòng 224–246 chỉ xét field có GT. | Báo tổng claim/extracted/checkable/unresolved; không có claim không có nghĩa an toàn tuyệt đối. |
| Guardrail | E dòng 188–208 bỏ số10chữ số bắt đầu0 trong regex PII; kiểm tra tổng quát chưa bao phủ mọi tool args. | Vẫn thực hiện log/external masking theo đề; 0 vi phạm official không chứng minh không có PII. |
| Memory | E dòng 210–222 bỏ một số key: superseded, must_not_write_to, address_ttl_check, profile_state. | State assertion hoặc review tay bổ sung; memory_checks=[] không phải memory đạt. |
| ASR thiếu dữ liệu | E dòng 282–327 trả None nếu thiếu asset; bỏ dialogue không có hypothesis. | Kiểm đủ manifest ID trước kết luận; báo coverage sample/full/team riêng. |
| Entity | E dùng dictionary entity ở mức dialogue. | Bổ sung breakdown ITN/phone/money; phân biệt entity và số lần xuất hiện. |
| Diarization | E dò speaker hypothesis ở midpoint đoạn GT, nhãn A/C. | Nêu đúng tên phép đo; không gọi là DER. |
| RAG thiếu kết quả | E dòng 329–350 bỏ query thiếu result khỏi overall recall; abstain có mẫu số khác. | Kiểm coverage60/60 trước so; báo by-type/support; không tăng điểm bằng bỏ query. |
| RAG metric | Recall@k là query hit ≥ 1 relevant; full multi-hop kiểm đủ relevant. | Không diễn giải thành trung bình số chunk được tìm thấy; answer/version phải chấm riêng. |
| Latency | E dòng 248–256 dùng mọi giá trị, L yêu cầu bỏ 3 warm-up. | Giữ raw report BTC và báo derived latency theo L; không null field integer hoặc xóa turn chất lượng. |
| Calls-to-Close | E dòng 262–269 thấy order.create mà không xác nhận result thành công. | Metric tùy chọn; phân biệt attempted close và successful close trong phần bổ sung. |
| CLI/bảng | CLI không có --catalog dù comment đầu file gợi ý; bảng chỉ baseline/system và turns/call. | Dùng argparse thực tế; adapter thêm delta/turns-scenario, không sửa scorer. |

Nguồn: E theo dòng/hàm; TR required/types; L; Đ A.1–A.6.

### 5.2. Ca kiểm chứng trước khi tin báo cáo

| Ca thử | Kết quả mong đợi |
|---|---|
| Thiếu scenario/call/turn, duplicate turn, trộn config | Coverage/validation FAIL, không silent-drop. |
| Scenario hard không có success_if | Báo khác biệt hard/eligible; không diễn giải là tự động PASS. |
| Confirm cùng slot lần2 ở call có must_not_ask=[] | Nêu giới hạn RQR official; supplemental phát hiện. |
| facts_used đúng tên slot nhưng sai value/ngữ cảnh | Giữ official, semantic check FAIL. |
| order.create args đúng nhưng result.error | Không diễn giải thành đã tạo đơn thành công. |
| Brief thiếu một required field | Schema FAIL dù subset scorer PASS. |
| Không claim/không GT/extractor bỏ sót | N/A hoặc unresolved kèm coverage; không cố gán HR =0. |
| Baseline RQR =0 và full RQR =0 | Relative reduction N/A, không “đạt giảm40%”. |
| Hard FAIL nhưng judge PASS | Hard/hybrid FAIL; judge không cứu điểm. |
| Judge JSON sai/thiếu ID/evidence | Retry theo chính sách; còn lỗi thì INCOMPLETE, không xóa khỏi báo cáo. |
| RAG chỉ trả qid dễ hoặc ASR thiếu hypothesis | Incomplete, không tuyên bố đủ suite. |
| Ba lượt warm-up có lỗi chất lượng | Chỉ loại khỏi latency, vẫn chấm chất lượng. |
| Copy/viết lại lỗi Frozen thành Growth | Giữ provenance bộ đã xem; không biến thành test độc lập. |
| Candidate thay đổi sau PASS | Vô hiệu report hash cũ, đo lại trước active. |

Đây là **ca nghiệm thu đề xuất**, chưa chạy trên runner Agent. Audit chỉ gọi scorer với trace mẫu và quote mock trong bộ nhớ.

## 6. Sổ kiểm tra 32 sơ đồ

Đã xem trực tiếp tất cả PNG, không chỉ tên link. Ảnh nằm trong output/evaluation-assets; số hình khớp Flow. Bảng này không tạo thêm điểm trùng ma trận.

| Hình | Nội dung | Nhận xét / hành động |
|---:|---|---|
|1 | Tổng cảnh 6a–16 | Giữ hai nhánh qua14–15; mở rộng ô 15 theo F06–F11. |
|2 | Source Gate | Giữ; ghi rõ chính sách nhóm, không chặn memory scenario. F16. |
|3 | Consultant/handoff | Thêm HB/state validation. F03. |
|4 | FAQ draft có nguồn | Giữ; bổ sung xử lý nguồn tranh chấp. F05. |
|5 | Candidate + Growth draft | Giữ, chưa live. |
|6 | After-call memory/QA | Giữ chờ memory; bổ sung evidence bắt buộc. F04. |
|7 | QA rồi lọc lesson | M2 thêm Reflection record/no-change. F11. |
|8 | Evidence pool/dedup | Giữ provenance và phân nhóm tình huống. |
|9 | Threshold/urgent case | Giữ, ngưỡng support là đề xuất nhóm. |
|10 | Consolidate won/lost | Giữ không học từ chốt đơn nhờ hứa sai; nối record Reflection. |
|11 | Policy/human review | Thêm sổ GT tranh chấp. F05. |
|12 | Verify candidate Frozen/Growth | Thêm applicability và initial R0. F17. |
|13 | Active version/rollback | Giữ hash đúng phiên bản. |
|14 | Errors → Growth | Giữ review/schema, không “rửa nguồn” test. |
|15 | Tổng pipeline ô 15 | Thiếu RAG/diarization. F06–F08. |
|16 | Dataset/manifest | Cập nhật inventory/coverage. F13/F15. |
|17 | Runner full/baseline | Số call theo scenario; validation. F01. |
|18 | Assertion/official TSR | Thêm HB/state/tool result supplemental. F03/F04. |
|19 | Chọn assertion/judge/hybrid | Giữ; không đổi sang judge chỉ vì assertion FAIL. |
|20 | Criterion selector nhóm1 | J01 đúng nguyên văn rubric. F14. |
|21 | Criterion selector nhóm2 | Giữ applicability; không né lỗi thiếu hành động. |
|22 | Criterion selector nhóm3 | Giữ date/stock/budget; nguồn tranh chấp theo F05. |
|23 | Judge prompt/evidence | GT chỉ cho bộ chấm, không Agent. |
|24 | Judge/JSON/retry | Giữ; đồng bộ validation verdict ở hình 25. |
|25 | Verdict/evidence → Quality | Giữ INCOMPLETE không thành PASS. |
|26 | Hybrid, hard FAIL ưu tiên | Giữ báo cáo bổ sung riêng. |
|27 | Scorer + quality report | Thêm RAG/cost/Tool-Call Accuracy/delta/≥ 10 lỗi. |
|28 | ASR và simulator overview | Bổ sung đường RAG/diarization. |
|29 | ASR chi tiết | ITN breakdown và diarization. F07. |
|30 | Simulator 3 seed | State/log/stability chi tiết. F10. |
|31 | Latency/warm-up | Freshness/concurrency/ASR time. F08. |
|32 | So sánh/release | Thêm M2 R2 và initial R0. F11/F17. |

## 7. Danh sách cần xác nhận với BTC, không tự chọn bên thắng

Đã ghi chi tiết **B01–B15** tại [tổng quan §8](tong_quan_de_bai_va_btc.md): sốpromotion/publichard; SAMPLE01budget; SAMPLE02promo; SAMPLE03orderseed; Q20warranty; Q57basketpricing; CODđúng 10 tr; PB01/J01; warm-up; turns/call-vs-scenario vàCTCoptional; SKUcount; 20+5vàsimrange/std; on/signature; assetthiếu; mockvsoldpolicy/holiday.

Đặc biệt:

- README nói 4ASRsample được phát, 8 GTcòn lạiBTC giữ: không gọi đó là “8 file bị mất”.
- Audio/segments và validate_scenarios.py không có trong gói thực nhận: chỉ đánh dấu chưa nhận/xin BTC, không bịa file.
- Giữ baseline/full và officialmetric cho contract BTC; báo supplemental phát hiện khác biệt, không sửa groundtruth/scorer đểlàmđẹpđiểm.

## 8. Thứ tự hoàn thiện flow ở lần sau

1. P0 F01–F05: validity/completeness, extractor/GT, handoff/state và nguồn tranh chấp.
2. P1 M1: A.6/cost, ASR/latency, ≥ 10 lỗi và hardcoverage.
3. P1 M2: RAG, diarization, Tool-Call Accuracy, simulator, Reflection/R2.
4. P2: sourceinventory, nhãnBTC/đề xuất, initialR0 vàthuậtngữ.

**Không cần bỏ cấu trúc6a–16.** Cần mở rộng ô 15 thành suite rõràng, tăng kiểm chứng evidence và hoàn thiện M2; giữ cácđiểm tốt đang có. Chưa sửa fileflow trong đợt này.
