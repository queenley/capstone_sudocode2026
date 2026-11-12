# Nhật ký cải tiến

Mỗi lần sửa case sai hoặc thêm tính năng, thêm một mục vào đây, mới nhất ở trên. Cách ghi: [skill `improvement-log`](../../.claude/skills/improvement-log/SKILL.md). Đề xuất trước khi code vẫn nằm ở [README](README.md) và [backlog](BACKLOG.md); file này ghi những gì đã làm và kết quả thật.

Trạng thái: `đang đo` (đã code, chưa có số trước/sau) · `xong` (có số đo) · `bỏ` (quay lui, ghi lý do).

## Mẫu

```markdown
### YYYY-MM-DD · Tên cải tiến

Loại: ... · Trạng thái: ... · Chỉ số: TSR / CCR / RQR / HR / latency / ...

- **Vấn đề:**
- **Bằng chứng:**
- **Sửa:**
- **Đã kiểm:**
- **Số đo:** trước ... / sau ..., cohort ..., hoặc `chưa đo`
- **Còn lại:**
```

## Các mục

Sáu mục đầu được ghi lại sau khi làm, từ đợt sửa ngày 05-06/11/2026. Chưa mục nào có số đo trên agent thật.

### 2026-11-12 · Số đo agent gốc trước và sau đợt sửa (commit `40fea307`)

Loại: sửa agent gốc · Trạng thái: xong · Chỉ số: TSR, HR, RQR, CCR, vi phạm, TTFT

- **Vấn đề:** các lỗi ở hai mục 12/11 bên dưới, cộng ba lỗi đọc từ trace lần chạy đầu: điều kiện chính sách không đạt bị coi là "chưa có thông tin" (`SCN-HARD-03`), nhắc lại con số của chính sách cũ (`SCN-HARD-05`), cuộc Zalo không có `channel_identity` bị coi là khách lạ (`SAMPLE-06`).
- **Sửa:** `rules.md` (luật 4, 6), `skills.yaml` (`product-advice`), `pipeline/eval/scenarios.connection`, nhãn `SCN-HARD-02`; vòng cải tiến publish câu trả lời Gap Loop sau R0; `gaps.record_from_run` chỉ ghi lượt agent nói không có thông tin.
- **Đã kiểm:** `tests/agent` trừ ASR: 1.453 qua.
- **Số đo:** advisor `gpt-5.6-luna`, mỗi bộ chạy 1 lần; "trước" là cây làm việc sáng 12/11, "sau" là commit `40fea307`.

  | Bộ | | TSR | HR (giá) | RQR | CCR | Vi phạm | TTFT p50 / p95 (ms) |
  |---|---|---|---|---|---|---|---|
  | `data/hard-cases` (5) | trước | 60,0 | 28,6 (20,0) | | | 1 | 1.349 / 4.320 |
  | | sau | 100,0 | 0 (0) | | | 0 | 1.136 / 3.679 |
  | Mẫu BTC (7) | trước | 71,4 | 19,4 (22,2) | 9,1 | 90,5 | 0 | 1.269 / 3.765 |
  | | sau | 85,7 | 21,2 (25,0) | 10,0 | 76,2 | 0 | 1.606 / 3.886 |
  | `data/gap-loop` frozen (13) | R0, `40fea307` | 23,1 | | | | 4 | 996 / 4.957 |
  | | R1, 5 mục đã học | 100,0 | | | | 0 | 942 / 3.739 |

  - R1 của Gap Loop đo ở `evaluation/runs/gap-20261112` (trước ba sửa prompt cuối), R0 đo ở `base-40fea307-gap-r0`: hai phía không cùng một commit.
  - Bộ chấm cảnh báo cần từ 100 lượt để p95 có ý nghĩa; các bộ này có 19 đến 52 lượt.
- **Còn lại:** `SAMPLE-01` vẫn trượt (tư vấn AirPure X thay vì Y, kéo theo 4 lần báo giá bị tính sai); CCR mẫu BTC tụt 90,5 → 76,2 chưa rõ nguyên nhân; `SAMPLE-07` vẫn kể thêm "30 ngày" và "30.000đ"; `SAMPLE-04` vẫn hỏi lại sản phẩm ở lượt mở đầu; TTFT p95 vẫn trên 3 giây. Hai cơ chế bớt vòng model và phép so sánh model chưa làm.

### 2026-11-12 · Agent gốc: giữ tài liệu đã đọc, đọc được mã đơn vừa tạo; mục Gap Loop có câu hỏi lập chỉ mục

Loại: sửa agent gốc + Knowledge Gap Loop · Trạng thái: đang đo · Chỉ số: TSR, vi phạm guardrail (chuyển máy thừa), TTFT

- **Vấn đề** (tìm bằng trace có sẵn, không gọi model):
  - `SCN-ADV-0069`: lượt 3 agent đọc "7–15 ngày làm việc" (BH-03); lượt 4 khách hỏi lại "gửi hàng thì mất bao lâu", lần tìm kiếm mới xếp BH-03 thứ 5, advisor chỉ đọc 3 đoạn đầu, nói "chưa có thông tin" và chuyển máy.
  - Khách mới vừa đặt đơn: câu có mã đơn bị guard chặn ("chưa xác minh danh tính nên không được đọc mã đơn") 33 lần trong 4 lần chạy nhỏ; mỗi lần thêm một vòng model và khách không nghe được mã đơn.
  - TTFT theo số vòng model của lượt (4 run, 119 lượt): 1 vòng p95 1,2–2,4 giây; 2 vòng p50 2,4–3,7 giây; 3 vòng p50 4,9–6,4 giây. Mọi lượt có tool đều từ 2 vòng.
  - Gap Loop, 5 mục đã học của `proof-4`: 8/10 câu frozen tìm thấy mục của mình trong 3 đoạn đầu; F05 (showroom) và F06 (tự đến lấy hàng) thì không.
- **Sửa:**
  - `pipeline/hot/nodes._passages_in_reach`, `agents/advisor.shown_passages`: tối đa 3 đoạn đã đọc ở lượt trước vẫn hiển thị; bước kiểm chuyển máy nhận riêng hai nhóm đoạn.
  - `guardrails/hard._tier`, `guard_input`: khách chưa xác minh được nghe mã của đơn tạo trong chính cuộc gọi; mã khác vẫn bị chặn.
  - `knowledge/expand.entry_questions`, `improvement/gaps.resolve`, `corpus.entry_chunk`: mục Gap Loop mang theo các câu khách có thể hỏi, viết lúc publish, lưu trong dòng của phiên bản và đi qua `kb_chunks`.
  - `data/hard-cases`: 5 kịch bản theo định dạng BTC cho các lỗi trên và hai lỗi của ngày 12/11 (chuyển máy sớm, quyền lợi có điều kiện).
- **Đã kiểm:** `tests/agent` trừ ASR: 1.451 qua, 3 bỏ qua. Truy xuất trên 60 câu có nhãn của BTC (`evaluation/runs/rag-20261112`): recall@3 89,8, recall@5 91,5, từ chối đúng câu ngoài tài liệu 75,0, từ chối nhầm 0. Thêm 5 mục Gap Loop không đẩy đoạn đúng nào khỏi top 3 (39/47 trước và sau) và không đổi quyết định từ chối.
- **Số đo:** chưa đo bằng lần chạy agent thật.
- **Còn lại:** chạy `data/hard-cases` và mẫu BTC; đo lại Gap Loop với câu hỏi do model viết; latency: mỗi vòng model khoảng 1,1–2 giây, muốn TTFT p95 dưới 3 giây phải bớt một vòng ở lượt hỏi sản phẩm (chưa làm, cần quyết định thiết kế). ASR không chạy được trên máy này (thiếu `soundfile`, `sherpa_onnx`).

### 2026-11-12 · Reflection học đủ ba cuộc warranty; sửa chuyển máy sớm của agent gốc

Loại: cải tiến (vòng tự cải tiến) + sửa agent gốc · Trạng thái: xong · Chỉ số: TSR frozen của `data/reflection/warranty`, vi phạm guardrail

- **Vấn đề:** vòng 11/11 chỉ sửa ổn định 1/3 cuộc cần học, và chạy lại thì bài học đổi. Agent gốc chuyển máy thừa ở cuộc đối chứng F06 trong khoảng một nửa số lần chạy.
- **Bằng chứng:** `evaluation/runs/reflect-warranty-{4,5,6,7}` (bảng ở [06-vong-cai-tien.md](../ai/06-vong-cai-tien.md) mục 6).
  - QaAgent đoán lỗi giữa 99 đoạn chính sách: 3 cuộc ra 3 chẩn đoán.
  - Dòng skill publish không ghi mã luật thì luật không đi kèm: 0/3 cuộc áp dụng; có ghi: 3/3.
  - F06: model gọi `handoff_transfer` cùng lượt với `catalog_search`, lý do "giá không có trong tài liệu".
- **Sửa:**
  - `agents/qa.py`, `qa_diagnose.md`: chẩn đoán đọc `relevant_policy_ids` của kịch bản; rubric giữ verdict dùng được (`settled`).
  - `skill_versions.apply`: mã luật được trích ghi vào cuối dòng khi publish.
  - `lessons.clusters`: gom theo tình huống và loại lỗi.
  - `reflection_patch.md`, `approval_decide.md`: nêu đủ điều luật cho gì và cả trường hợp không đủ điều kiện; cùng bài học diễn đạt hẹp hơn vẫn được chấp nhận.
  - `agents/policy.py`, `review.blocking`: kiểm thay đổi chờ 45 giây, hỏi lại một lần; không trả lời thì luôn chặn.
  - `guardrails/actions.early_transfer`, `agents/advisor.py`: giữ lại lần chuyển máy `ngoai_pham_vi_tai_lieu` gọi cùng lượt với tool tra cứu.
  - `policy_rules.md` (`over_promise`): mời quyền lợi có điều kiện khi bằng chứng cho thấy rõ điều kiện không đạt.
  - `config/models.yaml`: Reflection và ApprovalAgent sang `gpt-6.1-terra`. Cả sol và terra từ chối `temperature`.
  - Nhãn đối chứng warranty: cấm thêm câu gợi ý tư vấn gói.
- **Đã kiểm:** toàn bộ `tests/agent` trừ ASR: 1.444 qua, 3 bỏ qua.
- **Số đo:** `evaluation/runs/reflect-warranty-8/`, advisor `gpt-5.6-luna`, 6 cuộc frozen, mỗi phía 1 lần, duyệt bởi `approval-agent` (không phải người).

  | | R0 | R1 |
  |---|---|---|
  | TSR | 50 | 100 |
  | Cần học (F01–F03) | 0/3 | 3/3 |
  | Đối chứng (F04–F06) | 3/3 | 3/3 |
  | Vi phạm | 0 | 0 |

- **Còn lại:** một lần đo mỗi phía; ở vòng 7 đối chứng F05 hỏng (chào gói cho món 2.450.000đ). Luật `over_promise` mới chưa đo trên `data/dev` và mẫu BTC. Cần người duyệt cho vòng chính thức.

### 2026-11-11 · Reflection: bài học đúng lỗi QaAgent tìm ra, và luật được trích đi kèm

Loại: cải tiến (vòng tự cải tiến) · Trạng thái: xong · Chỉ số: TSR frozen của `data/reflection/warranty`

- **Vấn đề:** vòng `proof-warranty` (10/11) chỉ sửa được 1/3 cuộc frozen cần học; chạy lại hôm nay thì không học được gì.
- **Bằng chứng:**
  - Agent chỉ nhắc gói bảo hành mở rộng ở lượt mà đoạn BH-05 được truy xuất (L01). Luật cố định 3 chỉ cho nói chính sách có trong "Tài liệu liên quan", và advisor chỉ đọc 3 đoạn đầu.
  - `reflect-warranty-2`: ReflectionAgent không đọc chẩn đoán của QaAgent, 2/3 thẻ dạy điều khác; ApprovalAgent từ chối.
  - Bộ chấm so chuỗi: L01 nói "mua thêm gói bảo hành 12 tháng" vẫn trượt.
- **Sửa:**
  - `agents/reflection.py`, `reflection_lesson.md`, `pipeline/improve/cli.py`: thẻ bài học đọc câu chẩn đoán của QaAgent (`QA FOUND`).
  - `components/context/skills.py` (`learned_cites`), `components/knowledge/search.py` (`include`, `pinned`), `mcp/servers/knowledge.py`, `agents/advisor.py` (`shown_passages`), `pipeline/hot/nodes.py`: luật mà dòng skill đã publish trích dẫn đi kèm tài liệu của lượt.
  - `pipeline/improve/cli.py`: vòng học trước, chỉ đo frozen khi có thay đổi được duyệt; `compare` chỉ tính fixed/broken khi mọi lần chạy của mỗi phía đồng ý, còn lại là unstable.
  - Nhãn `data/reflection/warranty`: các cách nói một lời chào gói; đối chứng cấm thứ chỉ lời chào mới có.
- **Đã kiểm:** 144 test của vòng cải tiến, kho tri thức và skill qua (`test_approval_agent`, `test_reflection_changes_skills`, `test_reflection_dataset`, `test_improvement_loop`, `test_knowledge_in_force`, `test_skills_on_demand`). Toàn bộ `tests/agent`: 1.606 qua; 9 hỏng và 12 lỗi đều thuộc ASR, có từ trước (thiếu `soundfile`).
- **Số đo:** `evaluation/runs/reflect-warranty-3/`, advisor `gpt-5.6-luna`, 6 cuộc frozen, mỗi phía 2 lần, duyệt bởi `approval-agent` (không phải người).

  | | R0 | R1 |
  |---|---|---|
  | TSR | 50 / 50 | 83,3 / 66,7 |
  | Cần học (F01–F03) | 0/3, 0/3 | 2/3, 1/3 |
  | Đối chứng (F04–F06) | 3/3, 3/3 | 3/3, 3/3 |

- **Còn lại:** F03 trượt 2/2 và F02 đạt 1/2; chữ của bài học đổi giữa các vòng. F06 chuyển máy thừa ở agent gốc 1/2 lần. Chi tiết ở [06-vong-cai-tien.md](../ai/06-vong-cai-tien.md) mục 9.

### 2026-11-12 · Kịch bản nhiều máy lọc không khí một đơn (luật BTC 11/2026): SCN-ADV-0155..0160

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: TSR, HR

- **Vấn đề:** dev và test chỉ có cặp máy lọc lệch giá (Pro + AX40, Y + Mini). Vì vậy các luật mới của BTC chưa được đo: hai máy cùng mẫu, ba máy, AIR-2ND-50 đúng một máy, thu cũ đổi mới kết hợp AIR-2ND-50.
- **Bằng chứng:** chạy `pricing.quote_order` mới trên 29 cuộc đơn nhiều sản phẩm của dev/test: giá trùng nhãn cả 29. Không cuộc nào có hai máy lọc cùng mẫu hay `qty` ≥ 2.
- **Sửa:**
  - Loại cuộc `order_units`:
    - định nghĩa ở `call_kinds.py`, `policies.py`, `planner._label_order_units`;
    - oracle gọi `pricing.quote_order` rồi một `order.create` có `lines`, mỗi giá một dòng;
    - `args_match` là dòng giá thấp nhất của mẫu chính, có `total_match_vnd`;
    - cấm hai tổng sai: không giảm máy nào, và giảm 50% mọi máy sau máy đầu;
    - mẫu có hai giá không ghi `price_vnd:SKU`;
    - đơn trên 10 triệu: khách định trả COD rồi chuyển khoản, `must_say_any` có "10 triệu" / "chuyển khoản" (J11).
  - Persona `khach_mua_nhieu_may_loc` (6 biến thể) trong `personas_advanced.yaml` / `.py`.
  - `run_all` và `generate_scenarios` có thêm `--only-persona` và `--id-start`, để sinh ID mới mà không đánh số lại bộ cũ.
  - `pricing.quote_order` được đưa vào `OFFICIAL_TOOLS`.
  - `add_scenarios.py` cài kịch bản vào dataset và ghi `review/added.json` với trạng thái `pending`.
  - `build_dev_r4.install` giữ lại kịch bản thêm khi dựng lại.
  - Cài vào dev: ADV-0155..0159. Cài vào test: ADV-0160 (chỉ có ở test).
- **Đã kiểm:**
  - data-generation 112/112 test qua.
  - Oracle dev và test tuyệt đối; validator dev 807/807, test 192/193 (GEN-0042/c3 cũ, người duyệt chọn không sửa).
  - `auto_verify`: nhãn của 6/7 cuộc mới qua mọi kiểm. ADV-0155 bị kiểm `consent` bắt: hai lượt cuối thiếu lời đồng ý.
- **Số đo:** chưa đo trên agent.
- **Còn lại:**
  - Người duyệt ký 7 cuộc mới trong `review_sheet.csv`, rồi chạy `approve_gold.py`.
  - Judge còn gắn cờ cách hành văn ở 6/7 hội thoại mẫu (J07, J08, J02).
  - Chưa có audio: chạy `synthesize_scenario_audio --only <id>` khi cần.
  - Mất 4 lần sinh lại vì nhãn sai: ngày nghỉ 26/10, câu gọi xác nhận của đơn COD trên 2 triệu, ngân sách của một máy, lý do hoãn mua trong cuộc chốt.
  - Bốn lỗi đó nay có test cố định trong `tests/test_label_sanity.py`. Planner được sửa theo:
    - mọi cuộc chốt đơn (`ORDERING_KINDS`) không còn nhận lý do hoãn mua;
    - ngân sách của `order_qty` tính trên cả đơn.
  - Rà toàn bộ dev/test bằng 5 kiểm (ngày nghỉ, câu gọi xác nhận, ngân sách, hoãn mua, số tiền khách tự nêu). Có 2 cuộc đã ký bị lỗi cùng gốc:
    - SCN-ADV-0057/call_1: khách nói "để anh bàn với gia đình" nhưng nhãn là chốt đơn; ngân sách 500.000đ là giá một lõi trong khi khách mua 3 lõi;
    - SCN-ADV-0118/call_1: khách nói "chờ cuối tháng nhận lương" nhưng nhãn là chốt đơn.
    - Sửa hai cuộc này cần một nhóm nhãn mới và người duyệt quyết.
  - 25 cuộc vượt ngân sách còn lại là cố ý (ca J11 của giỏ hàng, mua nhiều món, máy thứ hai).

### 2026-11-12 · Agent mẫu bịa chính sách và thông số sản phẩm (J02)

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: chất lượng hội thoại mẫu (judge J02)

- **Vấn đề:** bộ chấm gpt-5 gắn J02 cho 221 hội thoại mẫu ở dev/test. Agent mẫu nói "miễn phí vận chuyển toàn quốc cho đơn trên 500.000đ" với mọi ngành hàng, trong khi VC-02 chỉ áp cho mẹ & bé. Nó cũng tự nghĩ ra thời hạn bảo hành, chất liệu và tính năng.
- **Bằng chứng:** trong 221 bằng chứng J02, 70 nhắc giá, 61 bảo hành, 57 miễn phí vận chuyển, 40 đổi trả. Prompt có đưa văn bản chính sách, nhưng không đưa bản ghi catalog (`warranty_months`, `features`). BH-01 nói catalog là nguồn ưu tiên.
- **Sửa:**
  - `generate_dialogue.product_facts` đưa bản ghi catalog của các sản phẩm được nhắc trong cuộc vào CALL JSON.
  - Quy tắc 13 của `dialogue_full_call.jinja`:
    - phí giao, bảo hành, đổi trả, quà và thông số chỉ nói theo nguồn, kèm đúng điều kiện;
    - nêu rõ điều kiện của VC-02;
    - không có nguồn thì nói "chưa có thông tin";
    - không hứa giữ giá hay giữ khuyến mãi tới một ngày.
- **Đã kiểm:**
  - 112/112 test qua.
  - Lô 6 kịch bản mới (7 hội thoại): lần đầu, J02 gắn cờ cho "freeship đến 30/10" và "giữ ưu đãi đến 14/12". Ở lần sinh cuối vẫn còn 3/7 cuộc bị J02, ví dụ "miễn phí vận chuyển toàn quốc cho đơn trên 10 triệu" và "mỗi máy tặng kèm màng lọc". Prompt chưa chặn hết.
- **Số đo:** chưa đo trên 221 cuộc bị gắn cờ. Hội thoại mẫu cũ chưa sinh lại.
- **Còn lại:** sinh lại các cuộc J02 bằng `regenerate_conversations.py --only` (tốn phí), rồi chấm lại bằng judge để đo.

### 2026-11-10 · Combo, phụ kiện cùng tên sản phẩm; thử ngữ cảnh cuộc gọi (scenario-commerce-v14)

Loại: evaluation (bộ trích entity ASR) · Trạng thái: xong · Chỉ số: entity accuracy ASR, `sku`

- **Vấn đề:** trên lời gốc, bộ trích v13 vẫn sai 24/519 `sku` ở dev và 5/126 ở test. Có ba lỗi chung:
  - "combo Spectra S1" bị nhận là máy hút sữa Spectra S1; "combo AirPure Y" bị nhận là AirPure Y;
  - "giá máy AirPure Pro" khớp cả máy lẫn "Màng lọc thay thế AirPure Pro" nên bị bỏ trống;
  - "máy lọc không khí xiaomi smart bốn lai" bị bước khớp mờ nhận là màng lọc "Xiaomi Smart 4".
- **Bằng chứng:** `evaluation/runs/20261110-commerce-v13/{dev,test}-perfect`.
- **Sửa** (`components/intake/commerce.py`):
  - `_product_patterns`: thêm tên "Combo" + món đầu của combo. Tên dài hơn thắng ở chỗ hai tên chồng nhau.
  - `_part_without_its_kind`: phụ kiện trùng tên một sản phẩm khác cũng được nhắc, có nói loại hàng của sản phẩm đó, thì bị bỏ. Không bỏ khi sản phẩm kia không được nhắc: "cái AirPure Y" vẫn là AirPure Y, không bị combo che.
  - `_fuzzy_brand_product`: áp cùng quy tắc bỏ phụ kiện như khi khớp đúng tên.
  - `VERSION` lên `scenario-commerce-v14`.
- **Thử, không làm:** suy `sku` từ sản phẩm đã nhắc trước đó.
  - Trần lợi ích, chỉ dùng lời khách: dev 3 lượt (cùng cuộc gọi), test 0. Nếu tính cả cuộc gọi trước thì dev 10, test 4.
  - Nhãn theo lượt của BTC không gắn `sku` cho lượt chỉ ngầm nhắc sản phẩm. Trong mẫu: D01 "còn mẫu x thì bao nhiêu" để trống; D02 câu xác nhận "một máy e pia y" cũng để trống.
  - Định dạng ASR của BTC là từng cuộc gọi riêng, không nối sang cuộc trước.
  - Agent thật không dùng bộ trích này: LLM và `memory.extract` đã có cả hội thoại lẫn bộ nhớ.
- **Đã kiểm:**
  - `tests/agent/test_commerce_v14.py`: 7 ca.
  - Toàn bộ `tests/`: 1.641 qua, 18 bỏ qua. 3 ca hỏng nằm trong `tests/agent/test_extractor_v9.py`, file chưa theo dõi và đã hỏng từ trước.
- **Số đo:** `evaluation/runs/20261110-commerce-v14/`, chấm lại transcript đã lưu, cùng nhãn.

  | Tập | Văn bản | Entity v13 → v14 | `sku` v13 → v14 |
  |---|---|---|---|
  | dev | Lời gốc | 95,4% → 95,7% | 495 → 502/519 |
  | dev | Zipformer | 90,3% → 90,4% | 442 → 443/519 |
  | test | Lời gốc | 95,4% → 95,4% | 121 → 121/126 |
  | test | Zipformer | 91,0% → 91,0% | 110 → 110/126 |

  - Không mất lượt nào.
  - Test không có ca combo hay "giá máy AirPure Pro", nên không đổi.
  - Bốn lượt dev đổi từ Spectra S1 sang combo, ở chỗ nhãn để trống. Đây không phải đoán nhầm mới: trước đó bộ trích đã đoán Spectra S1 ở các lượt này.
- **Còn lại:**
  - 17 lượt dev và 5 lượt test sai trên lời gốc đã được phân loại, chờ người duyệt (bảng đề xuất nhãn chưa đưa lên main):
    - 14 lượt nhắc hai sản phẩm, nhãn ghi sản phẩm đầu (mẫu D01 của BTC để trống);
    - 4 lượt combo để trống nhãn;
    - 3 lượt câu chuẩn khác lời gốc.
  - 6 lỗi bộ trích còn lại chưa sửa.

### 2026-11-10 · Khớp tên sản phẩm nghe sai theo âm (scenario-commerce-v13)

Loại: evaluation (bộ trích entity ASR, dùng chung với bộ nhớ của agent) · Trạng thái: xong · Chỉ số: entity accuracy ASR, `sku`

- **Vấn đề:** trên dev, bộ trích lấy đúng 495/519 `sku` từ lời gốc nhưng chỉ 422/519 từ bản Zipformer. Zipformer viết một tên theo nhiều cách: riêng "Joie Pact" có khoảng 19 cách trên dev ("drapack", "rua pac", "drap back", "ra page"). Test lại có những cách chưa gặp ("grab parker", "drapuk"), nên thêm từng cách viết vào từ điển sẽ không bắt được test.
- **Bằng chứng:**
  - `sku` bị mất trên `evaluation/runs/20261110-hotwords/{dev,test}-greedy-rescored`.
  - Vòng đo nhanh trên transcript đã lưu, theo đúng cách bench xử lý văn bản; khớp số của bench.
- **Sửa:**
  - `components/intake/commerce.py`:
    - `_kinds`: dạng đọc cả tên trong từ điển ("drapark: Joie Pact", "aibia: AirPure Y") thành khoá âm của sản phẩm đó, như dạng đọc của hãng đã làm. Nhờ vậy các cách viết gần nó cũng được nhận.
    - `_kind_and_name`: chữ số nằm giữa loại hàng ("Xe đẩy 2 chiều") thuộc về loại hàng và được đọc thành chữ. Trước đây loại hàng của Combi Sugocal bị cắt còn "xe đẩy", và chữ "hai" chặn tên.
  - `config/models.yaml`, theo quy tắc v12 (nghe ít nhất hai lần, luôn cho cùng sản phẩm):
    - "hy pro", "hypro" → "hai Pro": 47 lần trên dev, đều là RunLite 2 Pro.
    - "run like" → RunLite.
    - "tiệc trùng" → "tiệt trùng".
  - `VERSION` lên `scenario-commerce-v13`; hai test ghim phiên bản được đổi theo.
- **Đã kiểm:**
  - `tests/agent/test_commerce_v13.py`: 11 ca, gồm 2 ca không được nhận ("hy vọng", "xe đẩy cho bé").
  - Toàn bộ `tests/`: 1.634 qua, 18 bỏ qua. 3 ca hỏng nằm trong `tests/agent/test_extractor_v9.py`, file chưa theo dõi và đã hỏng từ trước.
- **Số đo:** `evaluation/runs/20261110-commerce-v13/`, chấm lại transcript Zipformer greedy, không giải mã lại. Cùng nhãn.

  | Tập | Văn bản | Entity v12 | Entity v13 | `sku` v12 | `sku` v13 |
  |---|---|---|---|---|---|
  | dev | Zipformer | 89,4% | 90,3% | 422/519 | 442/519 |
  | test (không dùng để chỉnh luật) | Zipformer | 88,7% | 91,0% | 98/126 | 110/126 |
  | dev | Lời gốc | 95,4% | 95,4% | 495/519 | 495/519 |
  | test | Lời gốc | 95,4% | 95,4% | 121/126 | 121/126 |

  - Chỉ trường `sku` thay đổi.
  - Số lượt nhãn không có `sku` mà bộ trích vẫn đoán ra không đổi (dev 39, test 5). Số `sku` đoán sai sản phẩm cũng không đổi.
  - WER trên văn bản đưa vào agent: dev 5,4 → 5,2, test 5,5 → 5,4.
  - Trên dev có 4 lượt từng đúng nay bỏ trống:
    - 2 lượt "xe đẩy" + tên yếu ("watach", "ra tắt"): "xe đẩy" giờ là cách nói tắt của hai loại hàng, nên tên phải giống ít nhất 0,7 theo quy tắc v12.
    - 2 lượt câu có cả máy hút sữa và máy tiệt trùng: máy tiệt trùng nay được nhận, nên câu nhắc hai sản phẩm bị bỏ trống, trong khi nhãn ghi sản phẩm đầu.
    - Riêng "abia mini" mất vì "aibia" (AirPure Y) nay cũng là khoá âm.
- **Còn lại:**
  - Phần còn mất do ASR phần lớn không sửa được từ văn bản:
    - khách chỉ nói tên hãng ("máy lọc không khí epa");
    - câu nhắc hai sản phẩm;
    - "thay thế cho epi pro": chữ "cho" chặn tên. Không sửa, vì "thay thế cho máy lọc" có 6 lượt nhãn trống.
  - Chưa đo trên agent thật.

### 2026-11-10 · Trích entity từ lời ASR: tên sản phẩm nghe sai, size, COD, blocker (scenario-commerce-v12)

Loại: evaluation (bộ trích entity ASR, dùng chung với bộ nhớ của agent) · Trạng thái: xong · Chỉ số: entity accuracy ASR

- **Vấn đề:** chạy Zipformer 30M trên 3.616 clip lời khách của `data/dev` cho WER 5,6 nhưng entity accuracy chỉ 76,6%. Nếu chép đúng từng chữ thì bộ trích đạt 89,1%. Phần mất do ASR chủ yếu ở bốn trường:
  - `sku` mất 183 entity:
    - "run lai hy pro": tên hãng khớp riêng, làm khuất cả model;
    - loại hàng nói tắt ("giày", "xe đẩy");
    - tên nghe sai: "aibia", "drapark", "slicker up classige".
  - `size_new`: "sai/tay/cy bốn mươi hai", "syse el", "size em".
  - `payment`: "ko d", "kod", "coop", "cây o d", "thẻ ngân hàng".

  Phần mất do bộ trích:
  - `blocker` hụt 142: giá chỗ khác, "hỏi thêm rồi gọi lại", "chờ cuối tháng mới có tiền";
  - `has_children` hụt 30: "bé nhà anh được mười hai tháng".
- **Bằng chứng:** `evaluation/runs/20261110-093836-dev-asr/` gồm:
  - `full-dev`: Zipformer;
  - `perfect-text`: thay bản ASR bằng chính lời gốc;
  - `replay-*`: dùng lại các transcript trên, không giải mã lại.
- **Sửa:**
  - `components/intake/commerce.py`:
    - `_heard_product`: khi tên hãng khớp phần đầu, model nghe sau đó vẫn được nhận nếu giống ≥ 0,7 và các từ thêm vào có thể là tên model.
    - `_kind_groups`: loại hàng nói tắt nhiều từ ("xe đẩy"), và "giày" một từ, gom mọi sản phẩm cùng loại. Từ một chữ khác bị loại vì mất dấu sẽ trùng từ thường ("nồi"/"nói", "bộ"/"bỏ"). Nói tắt thì tên phải khớp ≥ 0,7.
    - `_size_cues`, `spoken.size_letters`: thêm dạng nghe sai của "size" và cỡ chữ. Không coi là size khi theo sau là tiền hay số lần.
    - Màu đứng sau size; "navi", "bè".
    - `_payment`: dạng COD nghe sai, chỉ nhận khi đi sau "thanh toán" hoặc "trả"; các cách nói chuyển khoản ngân hàng. `_negated` không coi "đúng không" là phủ định.
    - `BLOCKERS`: thêm nhiều cách nói. `WEAK_HESITATION` ("hỏi thêm rồi gọi lại", "chưa quyết định") thua lý do cụ thể nói trong cùng mệnh đề.
    - `_children`: tuổi của bé nói bằng chữ.
  - `config/models.yaml` (`voice.lexicon.corrections`): 12 dạng ASR ghi sai, mỗi dạng nghe ≥ 2 lần trên clip dev và luôn ứng với cùng một sản phẩm.
- **Đã kiểm:**
  - `tests/agent/test_commerce_v12.py`: 53 ca câu tổng hợp, gồm cả ca không được nhận ("nói hôm trước", "phân vân giữa vài mẫu", "hoàn chênh lệch", "sai 40 nghìn").
  - Hai test cũ ghim chuỗi phiên bản được đổi sang v12.
  - Một ca trong `test_asr_entities.py` được đổi theo cách gán nhãn của `data/dev`: "bên khác có giá 8 triệu" nay có thêm `blocker: so sanh gia`.
  - Toàn bộ `tests/`: 1.612 qua (trừ `tests/agent/test_extractor_v9.py`, file chưa theo dõi, đã hỏng từ trước).
- **Số đo** (cùng nhãn và cùng transcript):

  | Tập | Văn bản | v11 | v12 |
  |---|---|---|---|
  | dev | Zipformer | 76,6% | 89,4% |
  | dev | Lời gốc | 89,1% | 95,4% |
  | test (holdout, không dùng để chỉnh luật) | Zipformer | 77,9% | 88,7% |
  | test | Lời gốc | 91,0% | 95,4% |

  - Trên dev, so với v11 chỉ có 1 entity đúng thành sai (GEN-0130/c2-t1).
  - Có thêm 24 blocker và 18 `has_children` ở các lượt nhãn bỏ trống. Ví dụ: "để anh hỏi thêm rồi gọi lại", "bé nhà chị được N tháng".
  - Test không độc lập hẳn: cùng sản phẩm và giọng TTS với dev, chỉ khác lời.
  - 100 cuộc ghép hai giọng từ clip dev (`20261110-093836-dev-turns-*`, cùng các lượt đã tách):
    - entity accuracy theo lượt: 63,7% → 72,2% (259 entity, 64 cuộc tách được lượt);
    - entity accuracy theo cuộc: 79,0% → 86,4%.
  - So sánh ASR trên 3.616 clip dev (`viegem-full`, VieGem chạy qua asr-service trên MPS):

    | Chỉ số | Zipformer 30M | VieGem |
    |---|---|---|
    | WER | 5,6 | 6,8 |
    | CER | 2,9 | 4,2 |
    | Entity accuracy, trích bằng v11 (chưa chỉnh theo bản ASR nào) | 76,6% | 65,7% |
    | Entity accuracy, trích bằng v12 | 89,4% | 74,5% |
    | Thời gian giải mã p50 / clip | 0,05 s (CPU) | 0,24 s (MPS) |

    VieGem mất hẳn tên "e pia" (viết thành "f"), COD (viết "co", "tiêu") và số đếm ("mười lăm" thành "m"), nên giữ Zipformer làm mặc định.
- **Còn lại:**
  - Nhãn nên để người duyệt xem lại:
    - số tài khoản nhận hoàn tiền gắn `payment: bank` (6 lượt);
    - "ví momo", "zalo pay" gắn `bank`;
    - "đen" có dấu ở GEN-0186;
    - "so sánh thêm" lúc là `so sanh gia`, lúc là `can suy nghi them`;
    - "người nhà mua cái khác rồi" gắn `can hoi nguoi nha`.
  - `entity_accuracy_per_turn` thấp chủ yếu vì `diarize.py` bỏ 36/100 cuộc ghép.

### 2026-11-10 · Reflection học được bài mới: ApprovalAgent duyệt theo đáp án chấp nhận

Loại: tính năng (vòng cải tiến) · Trạng thái: xong · Chỉ số: TSR frozen

- **Vấn đề:** Reflection chưa bao giờ publish được một thay đổi. Vòng `warranty-1` không học gì vì lỗi `TSR.must_say` bị phân vào `review` nên không tới Reflection; `warranty-3` có 4 thẻ cùng dạy BH-05 nhưng gắn vào 3 skill khác nhau nên không nhóm nào đủ 3 khách; các đề xuất sau đó viết "nếu phù hợp" thay cho điều kiện của luật và dạy agent "tra tool để báo giá gói", việc không tool nào làm.
- **Bằng chứng:** `evaluation/runs/warranty-1`, `warranty-3`, `warranty-4` (file `improvement/review/*.md`, `rounds/*/cards.jsonl`).
- **Sửa:** `agents/approval.py` + `approval_decide.md`: một lần gọi cho mỗi đề xuất, chấp nhận nếu cùng ý với `accept` trong `data/reflection/<bộ>/expected.yaml`, từ chối nếu khác. Lỗi `review` của bộ có đáp án đi tới Reflection (`cli._admitted`). Gom thẻ theo tình huống, ghi vào skill nhiều thẻ chọn nhất (`lessons.clusters`). Reflection đọc danh sách tool (`lessons.advisor_tools`) và phải ghi nguyên điều kiện của luật (`reflection_patch.md`); đề xuất có thể thêm tình huống vào mô tả skill (`when`). Reflection và ApprovalAgent dùng `gpt-6.1-sol`. Bộ dữ liệu mới `data/reflection/warranty` và `budget`; bộ cũ chuyển vào `data/reflection/conduct`. Trang mô tả: `docs/ai/06-vong-cai-tien.md`.
- **Đã kiểm:** `tests/agent/test_approval_agent.py`, `test_reflection_changes_skills.py`, `test_reflection_dataset.py` (không gọi model). Toàn bộ `tests/agent`: 1.512 passed, còn 9 failed và 12 errors đều là ASR, có từ trước.
- **Số đo:** `proof-warranty`, tập frozen warranty 6 cuộc, `product-extractor-v11`: R0 50 / 50, R1 66,7 / 66,7. SCN-WTY-F01 trượt 2/2 trước, đạt 2/2 sau; 3 đối chứng vẫn đạt. `proof-budget`: không có đề xuất (agent gốc đã nói "vượt ngân sách" ở 3/4 cuộc học).
- **Còn lại:** SCN-WTY-F02, F03 chưa áp dụng bài học; phần `when` thêm vào mô tả skill để sửa việc này chưa đo. Chưa có bộ nhãn để hiệu chỉnh ApprovalAgent. Đáp án `accept` do nhóm viết bộ dữ liệu; báo cáo phải ghi người duyệt là `approval-agent`.

### 2026-11-10 · Viết lại prompt của advisor theo tầng, bỏ `rule_packs.yaml`

Loại: prompt · Trạng thái: đang đo · Chỉ số: TSR, RQR

- **Vấn đề:** `rule_packs.yaml` (khoảng 1.900 token) đã không còn được đưa vào prompt của advisor nhưng vẫn là "luật cố định" mà QaAgent, Reflection và PolicyAgent đọc, và mâu thuẫn với skill (COD mặc định, múi giờ của `callback_at`). Luật trong `rules.md` đánh số nhảy (7, 15, 21) và có ý viết hai nơi.
- **Bằng chứng:** đọc code: `prompt_parts` không gọi `_packs_block`; `lessons.fixed_rules` đọc `rule_packs.yaml`.
- **Sửa:** `rules.md` đánh số 1–17 theo năm nhóm; `skills.yaml` mỗi quy trình viết một chỗ, mỗi dòng một ý, có tiêu đề kèm mô tả; xóa `rule_packs.yaml` và phần chọn gói luật trong `focus.py`. Luật 4 khôi phục "Chỉ khi … thật sự" sau khi bản viết lại làm agent chuyển máy khi khách hỏi giá; luật 9 và ghi chú `NO_ANSWER` trong `nodes.py` thêm: khách chỉ bày tỏ lo lắng thì không chuyển máy.
- **Đã kiểm:** `test_prompt_focus.py` (luật đánh số liền, không quy trình nào lặp giữa luật và skill), `test_advisor_action_rules.py`.
- **Số đo:** tập frozen `data/reflection/conduct`, R0: trước (proof-3 đến 6) 66,7–77,8, sau (`proof-conduct`) 77,8 / 88,9, RQR 0. Cùng ngày còn nhiều thay đổi khác nên chưa tách được phần của prompt. Bản sửa luật 9 và `NO_ANSWER` chưa đo (SCN-WTY-F06 chuyển máy 1/2 lần ở R0, 2/2 lần ở R1 của `proof-warranty`).
- **Còn lại:** chạy bộ chính thức để kiểm không hồi quy ở các tình huống khác.

### 2026-11-10 · Guard chặn đơn trùng cho món đã nằm trong đơn nhiều dòng

Loại: hard guard · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** khách chốt hai món, agent tạo một đơn hai dòng; lượt sau khách nói "Đúng rồi, đặt đi em" và agent tạo thêm một đơn riêng cho món thứ hai, nên tổng đơn bị cộng trùng.
- **Bằng chứng:** `evaluation/runs/proof-budget/learn-budget` SCN-BGT-L02 call_1 turn 4 (tổng 13.180.000đ thay vì 9.190.000đ); `r1-budget` SCN-BGT-F05 turn 4.
- **Sửa:** `components/guardrails/actions.py` `_order_create`: so món của đơn mới với `skus` của mọi đơn đã tạo trong cuộc, không chỉ `sku`. Cùng lúc `components/evaluation/judge.py` tính tổng đơn từ `lines`, để J11 áp được cho đơn nhiều dòng.
- **Đã kiểm:** `tests/agent/test_order_lines.py::test_a_product_of_an_order_of_lines_already_placed_is_not_ordered_again_on_a_confirmation`.
- **Số đo:** chưa đo.
- **Còn lại:** chạy lại `data/reflection/budget` (hai kịch bản frozen chứa món hết hàng đã được thay).

### 2026-11-08 · Màn hình giám sát: gộp phiên theo khách, Call Brief lên đầu, chuông báo đỏ qua Kafka

Loại: tính năng · Trạng thái: xong · Chỉ số: không có (giao diện nhân viên); e2e

- **Vấn đề:** hàng chờ của `/calls` và `/ban-hang` có một dòng cho mỗi phiên, nên một khách nhắn web, rồi Zalo, rồi gọi hotline chiếm ba dòng rời nhau. Call Brief nằm cuối cột "Bằng chứng" bên phải, dưới phần ngữ cảnh. Khi trợ lý chuyển máy, nhân viên chỉ thấy ở lần tải lại kế tiếp (5 giây ở `/calls`, 10 giây ở `/ban-hang`). Hook báo động `useHandoffAlerts` có sẵn nhưng không trang nào gắn vào.
- **Bằng chứng:** đọc code. `handoff.requested` đã được ghi vào outbox (`runtime/platform.py`) và worker đẩy lên topic `telesales.sales.events`, nhưng không ai nghe topic đó để báo cho nhân viên. Chỉ cuộc web chat (có `conversation_id`) ghi outbox; hotline và Zalo đặt `handoff_status = 'pending'` thẳng vào bảng `calls`.
- **Sửa:**
  - **Backend.** Thêm `runtime/alerts.py`: một hub đánh thức các luồng đọc khi có handoff. Hub được gọi từ `calls.request_handoff`, `accept_handoff`, `hang_up` và từ harness khi trợ lý chuyển máy. Một consumer Kafka chạy trong thread riêng, mỗi process một consumer group (`auto.offset.reset=latest`), nên mọi instance đều nghe được và không lấy mất message của worker outbox. Danh sách khách chờ luôn đọc từ bảng `calls`: Kafka chỉ báo lúc cần đọc lại, nhờ vậy hotline và Zalo vẫn hiện dù không đi qua outbox.
  - **Endpoint.** `GET /api/agent/handoffs/stream` (SSE) gửi `handoffs` mỗi khi danh sách đổi, gửi keepalive mỗi 15 giây, và tự đóng sau 100 giây để vừa giới hạn 120 giây của proxy. Không có `KAFKA_BROKERS` thì vẫn đọc lại mỗi 5 giây. `_call` trả thêm `handoff_requested_at`.
  - **Chuông.** `HandoffBell` đọc stream bằng fetch, vì EventSource không gửi được token nhân viên. Stream không mở được hai lần thì chuyển sang polling 5 giây và thử lại. Chuông đỏ, có số đếm và rung khi có người chờ; kêu chuông và thông báo trình duyệt như hook cũ. Danh sách mở ra ghi thời gian chờ, lý do và nguồn tín hiệu (Kafka, máy chủ đọc lại, hay trang tự tải). Toast được render qua portal, vì `.sl-topbar` giữ phần tử `fixed` ở đầu trang. Chuông được gắn vào header `/calls` và topbar `/ban-hang`; bấm vào thì mở cuộc gọi đó trong tab hội thoại.
  - **Hàng chờ.** `features/call-groups.ts` gộp các phiên theo `customer_id`. Phiên không có `customer_id` (khách lạ, số dùng chung) vẫn đứng riêng, vì không có căn cứ để gộp. Thứ tự: nhóm có người chờ trước, rồi nhóm đang mở, rồi mới nhất. Phía trên brief có dải "Các phiên của khách này" để chuyển giữa các phiên.
  - **Call Brief.** Component riêng ở đầu khung hội thoại, gập được: bàn giao từ trợ lý cạnh brief và cảnh báo, khung đỏ khi khách đang chờ. Cột phải chỉ còn ngữ cảnh, các lượt của trợ lý và after-call.
- **Đã kiểm:**
  - `tests/agent/test_handoff_alerts.py` (7 test): hub đánh thức mọi luồng đọc, kể cả khi bị gọi từ thread Kafka; chỉ sự kiện làm đổi danh sách chờ mới kêu; không có Kafka thì đọc lại theo nhịp; stream gửi lại khi danh sách đổi; một lần đánh thức đến trước nhịp đọc lại.
  - `e2e/call-console.spec.ts`: thêm 4 test (gộp 3 phiên của một khách thành một dòng và chuyển phiên; chuông đỏ từ stream rồi mở cuộc gọi; polling khi stream trả 502; chuông ở `/ban-hang` mở tab hội thoại). Cả 6 test pass trên dev server.
  - Test demo trong `redesign-snapshots` đọc brief ở vị trí mới; 3 test console và sales pass. `tsc` sạch. Toàn bộ `tests/` trên venv của `ai-agent-service` (Python 3.12): 1.391 passed, 35 failed, 14 errors. Tất cả fail và error nằm ở ASR và voice (`test_asr_*`, `test_voice_transport`), cộng thêm `test_settlement_does_not_recreate_a_missing_ledger` (Windows khóa file SQLite). Test này cũng fail trên HEAD khi chưa có thay đổi.
- **Số đo:** không có chỉ số agent. e2e console: 6/6.
- **Còn lại:**
  - Handoff của hotline và Zalo chưa ghi outbox, nên instance khác chỉ thấy sau tối đa 5 giây. Muốn tức thì thì cần ghi `handoff.requested` cho cả cuộc không có `conversation_id`; `aggregate_id` của outbox phải là UUID.
  - Hàng chờ chỉ gộp các phiên trong 50 cuộc gần nhất.
  - Chưa thử với Kafka thật (profile `async` của docker-compose).

### 2026-11-08 · Redesign frontend theo taste-skill

Loại: tính năng · Trạng thái: xong · Chỉ số: bố cục (`check.mjs`), copy-lint, e2e

- **Vấn đề:** cửa hàng và trang nhân viên dùng font Inter và chữ 700/800, nhãn viết hoa giãn chữ, gradient, chữ 8–11px. Trang chủ là một chuỗi khối không theo hệ lưới.
- **Bằng chứng:** chạy kit của skill `Leonxlnx/taste-skill` (plugin không cài được trong môi trường này, nên clone repo và theo `SKILL.md`). Lần đo bố cục đầu tiên: khung chat lệch 28px, trang cuộn ngang ở 390px, hero ở 390px cao hơn một màn hình. `consistency.mjs` lần đầu: 78 FAIL ở 5 cỡ màn hình.
- **Sửa:** bốc thăm theo skill, không chọn tay: palette white-navy-tab, hero product, nav-split, footer-columns, close-type, brand-band, nút pill, moment photo-chapters. Font Work Sans, vì ba cặp font bốc được (Besley, Outfit, Red Hat) không có dấu tiếng Việt. Kit chép vào `apps/web/public/assets`; bảng màu và CSS riêng của trang ở `public/assets/site.css`. `theme.css` lấy token mới cho toàn frontend; độ đậm chữ tối đa 500; trang nhân viên bỏ nhãn viết hoa, gradient và chữ dưới 13px. Header, Footer và trang chủ viết lại theo markup của kit. Các trang ứng dụng được bọc `.s-app`, nên luật "mỗi section một màn hình" chỉ áp cho trang chủ. Cửa hàng luôn nền sáng; trang nhân viên vẫn đổi được sáng/tối. Thêm trang credit ảnh `/anh` và thẻ og. `KitMotion` gọi lại `motion.js` và mount moment sau mỗi lần chuyển route.
- **Đã kiểm:** `check.mjs` ở 1440/1024/820/768/390: không còn lỗi nào ngoài `hero-lines`, đã ghi waiver. copy-lint: 0 FAIL, 0 WARN. Gate round 2: 1 FAIL (`section-gaps` ở 390px), kèm 5 waiver ghi trong `.taste-skill/waivers.json`. Round 3: `GATE: ERROR`, vì `consistency.mjs` chạy quá 9,5 phút trên Edge chạy bằng CPU. e2e trên bản production: xem "Số đo".
- **Số đo:** e2e trên bản production (`next build` + `next start`, build trước khi có merge): 55 pass, 4 fail, 7 skip. Cả 4 fail nằm trong `e2e/redesign-snapshots.spec.ts`, file đến từ một nhánh khác đang merge dở (bộ lọc theo diện tích phòng, thông số trên card, call console). Đó là tính năng của nhánh kia, bản này chưa có. Trước redesign, trên dev server, 5 test fail do route biên dịch chậm và Fast Refresh; bản production không bị. Test `expired responses...` đã chập chờn từ trước: bản cũ trong docker fail 3/3, bản mới pass 2/3.
- **Còn lại:** chưa redesign bố cục các trang ứng dụng (danh mục, sản phẩm, giỏ hàng, thanh toán) và trang nhân viên; mới đổi token. 5 waiver: nút chat nổi (skill cấm, nhưng đó là sản phẩm), hotline thật, bảng chính sách và FAQ không ảnh, lưới tile đồng dạng, `hero-lines`. Ảnh trang chủ là stand-in (Wikimedia, Flickr), cần thay bằng ảnh thật của shop. Bài học về công cụ: profile Chrome của kit nằm trong `apps/web` làm Tailwind quét treo dev server; Tailwind sinh `.grid` và `.start-7` trùng tên với class kit; Next dev chặn hydrate khi mở bằng `127.0.0.1`.

### 2026-11-07 · Ảnh cho 13 sản phẩm còn thiếu

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không có (giao diện)

- **Vấn đề:** 13 sản phẩm hiện hình vẽ thay cho ảnh.
- **Bằng chứng:** `data/seed/catalog/README.md` liệt kê 13 mã không có ảnh phù hợp trên Openverse ngày 2026-10-25.
- **Sửa:** `scripts/seed/product_images.py --candidates` với từ khóa rộng hơn, xem từng bảng ứng viên, chọn bằng `--use`. Ảnh lưu ở `apps/web/public/products`, credit ở `product_images.json`.
- **Đã kiểm:** xem bảng tổng hợp 13 ảnh mới; thay ảnh `XM-4P` vì ảnh đầu tiên không thấy máy.
- **Số đo:** 40/40 sản phẩm có ảnh.
- **Còn lại:** vài ảnh chỉ gần đúng loại hàng (máy lọc nước nóng lạnh cho RO, bình sữa cho máy hâm và máy tiệt trùng). Cần chạy lại seed để ảnh vào database: `docker compose run --rm seed`.

### 2026-11-12 · Gói BTC cập nhật 11/2026: đơn nhiều máy lọc không khí, so cụm theo nguyên từ

Loại: evaluation, dữ liệu · Trạng thái: xong · Chỉ số: TSR, CCR (chấm chính thức)

- **Vấn đề:** BTC thay `eval/mock_tools.py`, `eval/reference_eval.py` và `schemas/tools.schema.json`.
  - Mock: AIR-2ND-50 chỉ một máy mỗi đơn (máy rẻ nhất, bằng giá thì máy sau). Thêm `pricing.quote_order(lines)` và `order.create(lines)`.
  - Chấm: so cụm theo nguyên từ; `trace_must_not_match` bỏ tham số tool; không tính đơn có lỗi; so ngày giờ tới phút.
  - Agent chỉ đặt được mỗi lệnh một mã, một giá. Vì vậy hai AirPure Pro hay `qty` 2 sẽ bị mock trả `price_mismatch`: mock chờ 7.690.000đ và 3.995.000đ.
- **Bằng chứng:**
  - Chạy `--selftest` của mock mới.
  - Chạy oracle và validator của dev/test với `BTC_DATA_DIR` trỏ bản mới: không đổi kết quả. Bộ dữ liệu chỉ có cặp máy lệch giá, không có ca nhiều máy cùng mẫu.
  - Bộ test của agent: chỉ hỏng test ghim hash.
- **Sửa:**
  - Ba file của gói và phần agent (`pricing_quote_order`, `order_create(lines)`, guard `_order_of_lines`, `purchase.priced_lines`, `test_order_lines.py`) đã có trên nhánh chính ở commit `91e8d113` (10/11/2026). Khi rebase, bản agent làm song song (`actions.priced_lines`, `test_air_purifier_orders.py`) bị bỏ, giữ bản của nhánh chính.
  - Mục này thêm phần đánh giá và dữ liệu: ghi chú bản cập nhật trong `tests/agent/btc_pack.sha256.json`, `scenario-keys.yaml`, scoring-flow §3, `tools_audit` và `auto_verify` dev/test chạy lại.
  - Test privacy của bộ sinh: tra SĐT người khác qua tool không còn là lộ thông tin theo BTC; guard của agent vẫn chặn việc đó.
- **Đã kiểm:**
  - Bộ sinh dữ liệu: 112/112 test qua.
  - Oracle dev và test hoàn hảo; 0 lỗi khoá. `auto_verify`: nhãn dev 799/801, test 191/192.
- **Số đo:** chưa chạy agent thật. Ca cần thử: hai máy cùng mẫu, ba máy, khách có máy cũ (TRADE-IN-AP và AIR-2ND-50).

### 2026-11-10 · Extractor v13: tự sửa lỗi luật trước khi thử lại; tắt Langfuse khi hết hạn mức

Loại: evaluation · Trạng thái: xong · Chỉ số: RQR, CCR, HR (công cụ đo đổi: `product-extractor-v13`)

- **Vấn đề:**
  - Log của `run_eval` có `Items attempt 1 invalid (InvalidOutput); asking again`.
  - Có thêm `Failed to export spans batch code: 403`.
- **Bằng chứng:**
  - Cache extractor có 4.507 lượt. 30 lượt (0,7%) phải thử lại, và cả 30 đều đúng ở lần thứ hai.

    | Lỗi | Lượt |
    |---|---|
    | `source_field` là `previous_sessions` | 17 |
    | `kind` lạ (`alt_suggested`), câu hỏi `open` có `value`, thiếu `purpose` | 13 |

    JSON của các lỗi này đúng cú pháp, nên `json_repair` (đã chạy trước khi thử lại) không sửa được.
  - Langfuse trả `403 Ingestion suspended: Usage threshold exceeded`. Key vẫn hợp lệ (`auth_check` ok, vùng jp).
- **Sửa:**
  - `Item.settle` (`mode="before"`) sửa sẵn những gì luật đã định cách xử lý:
    - `kind` lạ thành `other`;
    - câu hỏi `open` có `value` thì đặt `value = null`;
    - claim và fact_usage bỏ `question_type`;
    - thiếu `purpose` thì để rỗng.

    Lỗi trích dẫn từ lịch sử vẫn để model sửa lại.
  - Prompt `extractor.txt`, quy tắc 1: `source_field` không bao giờ là `previous_sessions` hay `crm_history`.
  - Log thử lại in nguyên văn lỗi.
  - `VERSION` lên v13.
  - `LANGFUSE_TRACING_ENABLED=false` trong `.env`. `tracing.is_configured` đọc cờ này. Thêm cờ vào `.env.example`.
- **Đã kiểm:** 176 test liên quan qua (chạy với `PYTHONUTF8=1`; không có cờ này, console cp1252 làm vỡ một số test ASR).
- **Số đo:** chưa chạy. Không so điểm v13 với run v12 trừ khi dùng `run_eval.py --relabel`.

### 2026-11-10 · Bộ chấm hội thoại mẫu: gpt-5, tài liệu shop, hướng dẫn chấm, J11 theo ngân sách

Loại: dữ liệu · Trạng thái: xong (chưa đo đồng thuận với người) · Chỉ số: J01–J12 trên hội thoại mẫu

- **Vấn đề:** bộ chấm cũ (gpt-4o-mini) chấm sai theo cả hai chiều.
  - Báo J02 (bịa) khi agent nói đúng giá hoặc khuyến mãi đang chạy (ADV-0044, ADV-0031). Lấy lời của khách làm bằng chứng J03.
  - Bỏ sót lỗi thật: sai món của mã đơn (GEN-0169, GEN-0235), sai thời gian giao (GEN-0020/c3).
  - J02 cho đối chiếu với "tài liệu", nhưng bộ chấm không nhận được tài liệu nào.
  - J11 không áp dụng cho đơn vượt ngân sách khách nêu (13 cuộc dev, 3 cuộc test).
- **Sửa:**
  - Model chấm `gpt-5`. Client tự xử lý model suy luận: không gửi `temperature`, dùng `max_completion_tokens`, có khoá luồng.
  - Thêm phần mở đầu cố định: chính sách cho khách, catalog, khuyến mãi. Phần này được tính giá cache, khoảng 84% prompt.
  - Thêm `active_promotions` cho từng cuộc.
  - Thêm `config/prompts/data-generation/judge_guidance.md`, nối sau prompt của BTC. Prompt và tiêu chí của BTC giữ nguyên.
  - J11 áp dụng khi tổng tiền vượt ngân sách. Thêm `--workers` và `--only`.
- **Đã kiểm:**
  - Trên 23 ca bộ chấm cũ FAIL: 16 ca thành PASS. 4 trong 7 ca còn FAIL đối chiếu lại thấy là lỗi thật; 1 ca bị chấm sai (GEN-0123, "đổi trả 7 ngày" đúng chính sách).
  - Chấm lại toàn bộ: dev 801 cuộc, test 192 cuộc. Tỷ lệ FAIL theo tiêu chí ở dev:

    | Tiêu chí | FAIL |
    |---|---|
    | J02 | 184/801 |
    | J08 | 95/801 |
    | J07 | 32/232 |
    | J01 | 38/377 |
    | J05 | 18/20 |
    | J10 | 10/12 |
    | J11 | 16/36 |

  - J02 nhóm theo nội dung câu bị FAIL (dev và test):

    | Loại | Số câu | Ghi chú |
    |---|---|---|
    | Miễn phí ship | 69 | Agent nói "đơn từ 500.000đ freeship toàn quốc" với hàng không phải Mẹ & bé; chính sách: chỉ Mẹ & bé, ngành khác miễn phí từ 2.000.000đ |
    | Bảo hành | 55 | Agent nói "bảo hành 12 tháng" với AirPure Pro (24 tháng theo catalog), hoặc với giày và áo (không bảo hành) |
    | Thông số | 48 | |
    | Giá | 24 | |
    | Đơn hàng | 23 | |

    Đó là lỗi thật của bộ viết hội thoại (gpt-4.1), không phải lỗi của nhãn.
  - Chi phí chấm khoảng 34 USD.
- **Số đo:** hội thoại qua mọi kiểm tự động: dev 381/801, test 88/192 (trước, với bộ chấm cũ: 576 và 148). Chưa đo kappa với người (BTC yêu cầu ≥ 20 mẫu).

### 2026-11-10 · Sinh lại hội thoại mẫu và audio theo nhãn mới (dev r4, test r1)

Loại: dữ liệu · Trạng thái: xong (bộ vàng chờ người duyệt ký lại) · Chỉ số: TSR, CCR, WER

- **Vấn đề:**
  - Sau các nhóm sửa nhãn, nhiều hội thoại mẫu không còn khớp kịch bản, cụ thể ở các loại sau.

    | Loại | dev | test |
    |---|---|---|
    | Lời khách đã đổi | 188 | 43 |
    | Trượt validator | 31 | 6 |
    | Agent mẫu bịa (J02) | 33 | 2 |
    | Thiếu file | 4 | — |

  - `approve_gold.py` chặn lần ký vì GEN-0184/c2 và GEN-0197/c2 trượt validator.
  - 236 clip dev còn đọc lời khách cũ.
- **Bằng chứng:** `review/auto_verified.json`, `reports/validation.json`, `synthesize_scenario_audio --changed-only --dry-run`. Dev có 266 lượt cần đọc, test 58.
- **Sửa:**
  - `regenerate_conversations.py` mới:
    - chọn các cuộc;
    - chuyển file cũ sang `data/.build/regen-backup/`;
    - chạy `generate_dialogue --resume`, `validate_rules`, `llm_judge --resume` và `export_manual_review` (không `--ingest`);
    - ghi `review/regenerated.json`;
    - xoá `approve_conversation` cũ của các cuộc đó;
    - chạy `mark_conversations.py` và `auto_verify.py`.
  - `DATAGEN_REFRESH_CACHE=1` trong `openai_client.py`. Nếu không có cờ này, kịch bản không đổi sẽ nhận lại bản nháp cũ từ cache.
  - `mark_conversations.py` không đánh dấu lại các cuộc đã sinh lại. Ca J02 vẫn lấy theo lần chấm mới.
  - `write_ground_truth` lấy entity từ `asr_reference/<call>.json`, là file mà nhóm 11 đã sửa. Kiểm lại: 0 khác biệt trên 3.369 clip dev không đổi lời.
  - `install` của builder giữ các `asr_reference` vừa đọc lại và dựng lại `ground_truth.json` từ clip.
  - Đã chạy hai vòng. Vòng hai sinh lại 27 cuộc dev và 6 cuộc test còn J02 hoặc trượt validator.
- **Đã kiểm:**
  - Oracle hoàn hảo; `trace_log` không đổi.
  - Validator: dev 801/801 (trước là 770), test 191/192 (trước là 186). Ca còn trượt là GEN-0042/c3, hỏi 3 câu trong khi tối đa là 2.
  - Hội thoại qua mọi kiểm: dev 576/801 (trước là 415), test 148/192 (trước là 112). Phần còn lại phần lớn do bộ chấm bằng model gắn cờ cần người đọc.
  - J02 còn lại: dev 13, test 2.
  - `ground_truth.json` ASR không còn clip đọc lời cũ. Ở test, 114 nhãn chuyển sang `entities_not_stated`, khớp với dev (nhóm 32, người duyệt chấp nhận 10/11/2026).
  - Chi phí model (ước theo bảng giá trong `settings.yaml`): dev khoảng 6,25 USD, test khoảng 1,41 USD. ElevenLabs: 27.756 ký tự.
- **Còn lại:** người duyệt ký lại bằng `approve_gold.py` cho dev và test.
- **Số đo:** chưa đo trên agent thật.

### 2026-11-09 · Duyệt nhóm 19–24 và 31: không còn nhãn chờ duyệt

Loại: dữ liệu · Trạng thái: xong (bộ vàng chờ người duyệt ký lại) · Chỉ số: TSR, RQR, CCR

- **Vấn đề:** 25 thay đổi Claude đề xuất (dev 23 ở nhóm 19–24, 31; test 2 ở nhóm 21, 22) vẫn là `decision: pending`, nên các cuộc đó nằm ngoài bộ vàng.
- **Bằng chứng:** người duyệt (dngan0365) đọc bảng các thay đổi từng nhóm và đồng ý tất cả.
- **Sửa:**
  - Đặt `ACTION_PROPOSALS_REVIEWED = "2026-11-09"` trong `build_dev_r4.py`. Builder của test đọc cùng cờ này.
  - Dựng lại cả hai bộ: 25 thay đổi thành `decision: revise` với `reviewer` và `reviewed_on`. Lời khách và nhãn không đổi.
  - DISPUTES và README ghi 0 thay đổi chờ duyệt.
- **Đã kiểm:**
  - Oracle hoàn hảo, 0 file lỗi schema.
  - Validator: dev 770/797, test 186/192.
  - `auto_verify` (nhãn qua mọi kiểm): dev 799/801, test 191/192. Chỉ còn ADV-0024/0119 c2 là N; luật RUN-10 dùng một lần, nhãn đúng.
  - `review_sheet.csv` giữ nguyên các ô duyệt của người duyệt; chỉ cột gợi ý thay đổi.
- **Còn lại:** người duyệt đặt Y cho ADV-0024/0119 c2, rồi chạy `approve_gold.py` cho dev và test để ký lại bộ vàng.
- **Số đo:** chưa đo trên agent thật.

### 2026-11-09 · Lần kiểm thứ hai: thanh toán, diện tích, kịch bản chung SĐT (nhóm 27–31)

Loại: dữ liệu · Trạng thái: xong (nhóm 19–24, 31 chờ duyệt) · Chỉ số: TSR, RQR, CCR

- **Vấn đề:** một người kiểm khác đọc từng cuộc của dev và test, báo khoảng 40 nhãn sai.
  - `args_match.payment` ghi cách thanh toán khách không nói (4 cuộc dev).
  - `room_area_m2` không có trong lời khách: khách quay lại đã chuyển nhà, lịch sử CRM 20 m² đã quá hạn (9 cuộc dev, 2 test).
  - Ở kịch bản hai người chung SĐT, call_2 gán fact của người kia (dev 18, test 4), kèm vài câu lẫn vai.
  - README của test mô tả sai ("chỉ lời khách được viết lại").
  - DISPUTES ghi "chưa có golden_manifest".
- **Bằng chứng:** đọc lại từng cuộc trong danh sách của người kiểm; mọi mục đều đúng. So test với dev: 51 cuộc đổi ngày, GEN-0033/c2 và GEN-0049/c2 đổi `hen_goi_lai` sang `chot_don`. `auto_verify.py` (và danh sách nhóm 14) đã coi lịch sử CRM là "khách đã nói", và chỉ cần có một số đi kèm m², không đối chiếu giá trị.
- **Sửa:**
  - Nhóm 27: khách nói cách thanh toán.
  - Nhóm 28: khách nói diện tích phòng mới.
  - Nhóm 29: bỏ fact người gọi call_2 không nói.
  - Nhóm 30: câu đúng vai; cô Loan xưng "cô" như CRM.
  - Nhóm 27–30 ghi là người duyệt yêu cầu.
  - `grounded` của `auto_verify.py` giờ khớp giá trị, không tính lịch sử CRM, và ở kịch bản chung SĐT chỉ tính lời trong chính cuộc đó. Bộ đọc số đọc được "4.500.000đ" và "7 triệu bảy trăm".
  - Bộ kiểm chặt hơn lộ thêm 2 nhãn `has_children` không có căn cứ (GEN-0066/c1, GEN-0181/c1): thành nhóm 31, chờ duyệt.
  - Xoá quyết định cũ trong `review_sheet.csv` ở 36 cuộc dev và 7 cuộc test có nhãn đổi sau lần ký, để ký lại.
  - Sửa README và DISPUTES.
- **Đã kiểm:** 0 lỗi khóa; oracle CCR 100 · RQR 0 · TSR 100 · HR 0; validator dev 770/797, test 186/192. `auto_verify`: dev 785/801 cuộc nhãn qua, test 189/192; các nhãn còn N chỉ là các nhóm chờ duyệt và ADV-0024/0119 c2 (RUN-10 dùng một lần, nhãn đúng). Pending khớp DISPUTES: dev 23, test 2.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** người duyệt duyệt nhóm 19–24, 31 rồi ký lại. Audio và hội thoại mẫu chưa sinh lại (người duyệt chờ tập khách ổn định).

### 2026-11-09 · Tự động hoá phần kiểm trước bộ vàng; người duyệt ký bằng một lệnh

Loại: evaluation · Trạng thái: xong (chờ người duyệt ký) · Chỉ số: không đổi

- **Vấn đề:** người duyệt muốn hoàn tất bộ vàng tự động. Theo `SKILL.md`, nhãn chỉ thành vàng khi có người duyệt độc lập; Claude không tự duyệt nhãn mình sửa.
- **Sửa:**
  - Chạy lại `validate_rules` trên nhãn mới: dev 773/797 hội thoại mẫu qua, test 186/192.
  - `auto_verify.py` kiểm mọi cuộc, không gọi model: khóa, pending, fact có căn cứ trong lời khách, lời đồng ý, outcome, dữ kiện so với mock BTC, gọi lại, validator, judge, đánh dấu N. Kết quả ghi vào `review/auto_verified.json` (`not_golden: true`) và `review/review_sheet.csv`, có đề xuất Y/N tách riêng cho nhãn (quyết định `official_gt_approved`) và cho hội thoại mẫu (quyết định `golden_manifest.json`); cột duyệt để trống.
  - `approve_gold.py` cho người duyệt ký. `--accept-suggestions` nhận đề xuất nhưng manifest ghi `method` trung thực. Script không cho Y khi validator trượt.
- **Đã kiểm:** dev có 785/801 cuộc nhãn qua, 411 hội thoại dùng được; test có 188/192 và 111. Chạy `approve_gold.py` trên bản sao tạm: không cờ thì từ chối; có cờ thì ghi manifest, `official_gt_approved` vẫn false vì còn nhãn N. Dữ liệu thật chưa ký.
- **Bổ sung:** nhóm 26 do người duyệt quyết. ADV-0031/c1 (dev, test) và ADV-0126/c1 (dev) nói "Nhà anh có một phòng ngủ của con", nên đổi `has_children` false thành true; lời khách giữ nguyên. Regex `grounded` của `auto_verify.py` nhận thêm "của con". Sau khi dựng lại: dev 787/801 cuộc nhãn qua, test 189/192. Các cuộc còn N là nhóm 19–24 đang chờ duyệt và ADV-0024/0119 c2 (giá RUN-10 dùng một lần: nhãn đúng, bộ kiểm chặt).
- **Còn lại:** người duyệt ký. Judge của 245 hội thoại cần chạy lại (gọi model) nếu muốn dùng chúng.

### 2026-11-09 · Rà lại sau khi gộp: trạng thái pending, hội thoại mẫu lỗi, blocker chỉ nói ngân sách, GEN-0099

Loại: dữ liệu · Trạng thái: xong (nhóm 19–24 vẫn chờ duyệt) · Chỉ số: entity_accuracy (ASR); hội thoại mẫu không vào chấm điểm

- **Vấn đề:** người duyệt chỉ ra bốn điểm.
  - `DISPUTES.md` ghi "không còn thay đổi nào ở trạng thái pending", trong khi `conversion-report.json` còn 21 (dev) và 2 (test). Câu này do Claude chèn sai khi thêm nhóm 19–24.
  - Hội thoại mẫu lỗi (33 ca J02 có câu bịa, GEN-0133/c2, 4 ca hỏi quá `max_agent_questions`) chưa được đánh dấu là không dùng.
  - Còn nhãn `vuot ngan sach` ở câu chỉ nói ngân sách.
  - GEN-0099/c1 nói "có một bé lớn" mà `has_children: false`.
- **Bằng chứng:**
  - Đếm `decision` trong `conversion-report.json`.
  - Đọc 29 nhãn `vuot ngan sach` của dev: 15 câu chỉ nói ngân sách, giữ ADV-0110 c2 t4 ("ngân sách eo hẹp quá nên cần trả góp"). Test không có câu loại này. Con số "khoảng 60" là trước khi nhóm 11 bỏ bớt.
  - Quét `has_children: false` có nhắc tới con: chỉ GEN-0099 mơ hồ (GEN-0131 nói rõ "không có bé nhỏ").
- **Sửa:**
  - DISPUTES ghi đúng số đang chờ.
  - Nhóm 11c (bỏ 15 nhãn) và 25 (GEN-0099 nói rõ "nhà không có trẻ nhỏ", nhãn giữ), ghi là người duyệt nêu.
  - `mark_conversations.py` mới ghi `approve: N` kèm lý do vào `review/needs_manual_review.csv`, đúng cơ chế stage 8 của data-generation: người duyệt điền N thì hội thoại luôn bị loại. Đánh dấu dev 217 hội thoại (33 J02, 5 ca trên, 179 cuộc đã đổi lời khách), test 44. Script không ghi `Y` và không chạy `--ingest`, nên không tạo `golden_manifest.json`.
- **Đã kiểm:** số `pending` khớp giữa report và DISPUTES (21, 2). 0 lỗi khóa; oracle CCR 100 · RQR 0 · TSR 100 · HR 0.
- **Còn lại:** bộ vàng cần người duyệt độc lập (`official_gt_approved` vẫn false); nhóm 19–24 chờ duyệt; hội thoại mẫu và audio của các cuộc đổi lời cần sinh lại.

### 2026-11-09 · Một thư mục cho mỗi bộ: nhãn r4 vào thẳng data/dev, r1 vào data/test; ADV-0154 theo LN-02

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không đổi (cùng nhãn)

- **Vấn đề:** hai bản (`data/dev` và `data/dev-r4`, `data/test` và `data/test-r1`) dễ chạy nhầm bản cũ. Người duyệt chọn giữ một thư mục cho mỗi bộ. Ở SCN-ADV-0154/call_1, đáp án ghi kết quả `schedule.callback` là 08:00 (mock BTC thô dời 22:00), trong khi nhãn và `must_say_any` là 22:00.
- **Bằng chứng:** tool `schedule_callback` của agent (`mcp/servers/crm.py`, `clock.SPECIAL_HOURS`) giữ 22:00 ngày 11/11 theo LN-02 (tổng đài 07:00–23:00). Chỉ `mock_tools.schedule_callback` của BTC chưa có ngoại lệ này.
- **Sửa:**
  - `build_dev_r4.py` và `build_test_r1.py` đọc nhãn gốc từ git (`SOURCE_REF` là `46b2f2ff` và `cfb43fbb`), dựng trong `data/.build/` (gitignored). Sau đó chỉ thay các thư mục nhãn, `conversion-report.json` và `DISPUTES.md` của `data/dev` và `data/test`; audio và hội thoại mẫu không đụng tới.
  - README của bản sửa gộp vào `data/dev/README.md` và `data/test/README.md` (mới). Notes chuyển sang `notes/dev`, `notes/test`; `SKILL.md` ghi quy ước mới.
  - `ground_truth.json` ghi lại với thụt lề 2 như bộ sinh, nên diff chỉ còn các dòng đổi.
  - Nhóm 24 (chờ duyệt): kết quả trong `tools/` của ADV-0154 là 22:00, `moved_from: null`.
- **Đã kiểm:** so từng byte, `data/dev` giống bản dev-r4 ngoại trừ đúng `tools/` của ADV-0154, `data/test` giống hệt test-r1. Mọi file kịch bản git báo đổi đều có mục trong `conversion-report.json`. 0 lỗi khóa; loader `run_eval` nạp 404/404 và 99/99; oracle qua `reference_eval.py` CCR 100 · RQR 0 · TSR 100 · HR 0. `tests/agent/test_extractor_vocabulary.py`, `test_btc_pack.py`: 30 pass; test của `evaluation/data-generation`: 112 pass.
- **Số đo:** không có (nhãn không đổi so với bản đã kiểm).
- **Còn lại:** nhóm 19–24 chờ duyệt. Các run cũ trong `evaluation/runs/` chấm trên nhãn r3: không so số trực tiếp với run mới.

### 2026-11-09 · Hành động kỳ vọng của agent: dev-r4 và test-r1, nhóm 19–23

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: TSR, HR

- **Vấn đề:** một số `success_if`, tham số và `tools/` của đáp án chuẩn không khớp lời khách hoặc chính sách. Khách hẹn giờ gọi lại mà nhãn không đòi `schedule.callback`. Khách hoãn mà nhãn vẫn đòi tạo đơn. Lời khách mua một món, nhãn ghi món khác. Lịch gọi lại rơi vào ngày nghỉ thì `args_match` chỉ chấp nhận một trong hai cách làm đúng.
- **Bằng chứng:** bộ kiểm hành động không gọi model. Nó đối chiếu `schedule.callback` (ngày, giờ, kết quả `mock_tools.schedule_callback`), `order.create` (sản phẩm được nhắc, số lượng, câu cuối có hoãn không), `order.update` (action và size so với lời khách), `order.status`, `handoff.transfer` (khách đòi người hoặc hỏi y tế). Khoảng 60 mục bị báo, đọc từng câu: phần lớn là báo động giả (câu hỏi y tế chuyển máy đúng luật, khách nhắc nhân viên cũ, "Thứ Hai tuần sau"…). Còn lại 5 lỗi thật, và 1 chỗ chính sách mâu thuẫn với mock BTC.
- **Sửa (chờ duyệt, cờ `ACTION_PROPOSALS_REVIEWED`):**
  - Nhóm 19: GEN-0184/c2 đòi `schedule.callback` 19:00 ngày hôm sau.
  - Nhóm 20: ADV-0123/c1 đổi thành `hen_goi_lai`, không tạo đơn.
  - Nhóm 21: GEN-0197/c2 (dev) và GEN-0015/c2 (test), lời khách đổi sang mua AirPure Mini đúng nhãn.
  - Nhóm 22: 7 cuộc dev và 1 cuộc test, bỏ `args_match.callback_at` khi giờ hẹn rơi vào ngày nghỉ LN-02; giữ giờ đã dời ở `ground_truth_facts` và `must_say_any`.
  - Nhóm 23: ADV-0117/c1, khách tự xưng nhất quán là "anh".
  - Cũng sửa lỗi của chính nhóm 14 (đã duyệt): câu thêm vào dùng cách người gọi tự xưng, không theo `honorific` của kịch bản. Ở các kịch bản hai người chung SĐT, chị Dung từng bị ghi "Phòng cô…".
- **Đã kiểm:** dựng lại hai revision; 0 lỗi khoá; loader `run_eval` nạp 404/404 và 99/99; oracle qua `reference_eval.py` cho CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** chờ duyệt. Ở SCN-ADV-0154/call_1, LN-02 cho gọi 22:00 ngày 11/11 nhưng mock BTC dời về 08:00; cần người duyệt chọn theo chính sách hay theo mock.

### 2026-11-09 · Nhãn có căn cứ trong lời khách: dev-r4 và test-r1, nhóm 14–16

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR

- **Vấn đề:** `facts_established` ghi diện tích, trẻ nhỏ, tuổi bé, ngân sách mà khách không nói ở cuộc nào, seed_history cũng không có. Cuộc sau lại cấm hỏi (RQR) hoặc bắt nhớ (CCR) chính các slot đó: agent hỏi lại vì chưa biết thì bị trừ điểm, còn agent bịa ra số thì được cộng. Ở tập test, 8 cuộc đòi `order.create` mà khách không nói lời đồng ý nào. Ở dev, 2 cuộc ghi `freeship: true` khi không biết nơi giao.
- **Bằng chứng:** bộ kiểm mâu thuẫn không gọi model, chạy trên dev, dev-r4, test, test-r1. Nó đối chiếu nhãn với lời khách, `ground_truth_facts` với `mock_tools.py` của BTC theo ngày cuộc gọi (giá, tồn kho, khuyến mãi), danh tính với CRM, `expected_outcome` với tool, ngày giữa các cuộc.
  - Giá, tồn kho, khuyến mãi, outcome, ngày, thanh toán: không có mâu thuẫn. ADV-0024/0119 trông như sai giá nhưng là RUN-10 `once_per_customer`; các khách không có trong CRM đều là persona ẩn danh hoặc số mới.
  - Facts không nói ở đâu, trên dev-r4: room 29, has_children 29, child_age 41, budget khoảng 105; trên test-r1: 6, 11, 4, 21. Đa số bị cuộc sau dùng tới.
- **Sửa:** nhóm 14 thêm câu khách nói đúng giá trị đã gán, nối vào lượt đầu nên số lượt không đổi. Đây là cách đã duyệt ở nhóm 1 và 3, giữ được phép thử trí nhớ. dev-r4 có 144 cuộc / 196 nhãn, test-r1 có 27 cuộc / 37 nhãn; danh sách đọc lại từng cuộc. Nhóm 15 (test-r1) thêm lượt đồng ý cho 8 cuộc tạo đơn. Nhóm 16 (dev-r4) bỏ `freeship` ở 2 cuộc. Người duyệt chấp nhận các nhóm 11b, 14–18 ngày 09/11/2026 (cờ `NEW_PROPOSALS_REVIEWED` trong `build_dev_r4.py`; dựng lại, 2.582 và 612 file nhãn không đổi byte nào).
- **Đã kiểm:** dựng lại cả hai revision; 0 lỗi khoá. Oracle qua `reference_eval.py`: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema. Kiểm lại thì không còn fact nào khách không nói (8 mục còn lại đều đã đọc, khách nói bằng chữ như "một tháng", "một triệu"); 0 cuộc tạo đơn thiếu lời đồng ý.
- **Số đo:** chưa đo trên agent thật.
- **Bổ sung cùng ngày:**
  - Nhóm 11b (dev-r4): đọc 432 nhãn `blocker` của ASR, gồm những câu có từ gợi ý. Bỏ 8 nhãn (câu không nêu lý do, xin chuyển máy, lý do đã xong như "đã hỏi vợ và quyết định mua rồi"). Đổi 4 nhãn chê giá mà không so với nơi khác sang `vuot ngan sach`.
  - Nhóm 17: theo quy tắc người duyệt đưa ra, khách ẩn danh không đọc SĐT thì cuộc sau không nối được với cuộc đầu, nên chỉ giữ slot khách nói lại. Áp cho ADV-0050/0093/0145 call_2; nếu khách đọc số thì phải lưu và giữ ngữ cảnh.
  - Nhóm 18: bỏ `owned_sku` khỏi `must_carry_over` ở ADV-0045/c1, vì `seed_history` chỉ là thông tin tham khảo.
  - Size và `return_days` của ASR test-r1: đọc 35 nhãn, đều đúng.
  - Dựng lại: 0 lỗi khoá, oracle CCR 100 · RQR 0 · TSR 100 · HR 0.
- **Còn lại:** audio của các lượt có lời mới chưa sinh lại (người duyệt sẽ sinh khi dữ liệu ổn).

### 2026-11-08 · data/test-r1: sửa nhãn tập test theo các nhóm của dev-r4

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR, entity_accuracy (ASR)

- **Vấn đề:** `data/test` mang lại các lỗi nhãn đã sửa ở dev-r4, vì nó được sinh lại từ 99 kịch bản đầu của `data/dev` (cùng mã, khách, persona và kế hoạch cuộc gọi; chỉ lời khách khác). Đây cũng là lý do tập này không độc lập với dev.
- **Bằng chứng:**
  - Chạy kiểm không gọi model trên dev, dev-r4 và test: khoá theo `scenario-keys.yaml`, loader `run_eval`, oracle qua `reference_eval.py` của BTC, schema, độ khớp giữa các thư mục.
  - So mã: 99/99 mã của test có trong dev, cùng số điện thoại, 0 kịch bản trùng nội dung.
  - Đo từng nhóm của dev-r4 thành quy tắc trên dev: nhóm 5 khớp 22/22, nhóm 9 khớp 130/130. Các nhóm còn lại không tái tạo được danh sách đã duyệt (G1 độ chính xác 0,68, G3 0,79, G7 và G8 không dùng được), nên phải đọc câu.
  - Cũng trong lần kiểm này, phát hiện nhóm 7 của dev-r4 để lại `facts_established: {}` ở 5 cuộc. Đã sửa trong `build_dev_r4.py`, dựng lại; đúng 5 file đổi, oracle không đổi.
- **Sửa:** revision mới `data/test-r1`, dựng bằng `evaluation/datasets/ground-truth-review/build_test_r1.py` (dùng lại các hàm của `build_dev_r4.py`); `data/test` không đổi.
  - 43 thay đổi theo quy tắc đã duyệt: nhóm 5 có 5, nhóm 9 có 31, phần định dạng của 11 có 6, nhóm 12 có 1.
  - 83 thay đổi Claude đề xuất sau khi đọc câu: nhóm 1, 2, 3, 4, 7, 8, 10 và phần nghĩa của 11. Người duyệt chấp nhận cả bảng cùng ngày (`proposed_by: claude`, `reviewed_on: 2026-11-08`; cờ `CLAUDE_PROPOSALS_REVIEWED` trong script). Chi tiết ở `DISPUTES.md`.
  - `data/test-r*/` thêm vào `.gitignore` như `data/dev-r*/`. README và DISPUTES của cả hai revision chuyển vào `evaluation/datasets/ground-truth-review/notes/`; script chép nguyên byte khi dựng.
  - 21 cuộc có `budget_vnd` mà khách không nói ngân sách: để lại cho người duyệt.
- **Đã kiểm:** 99/99 kịch bản nạp được bằng loader của `run_eval`; 0 lỗi khoá. Oracle trên test-r1: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 vi phạm, 0 lỗi schema.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** 21 cuộc `budget_vnd` khách không nói chờ người duyệt chọn cách sửa; audio của các lượt khách đã đổi chưa sinh lại; `size_old`/`return_days` của ASR ở test chưa đọc. Muốn có tập test độc lập thì phải sinh tập mới với mã và khách riêng.

### 2026-11-08 · data/dev-r4: sửa nhãn theo bản tổng hợp 08/11/2026

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR, entity_accuracy (ASR)

- **Vấn đề:** nhãn của `data/dev` mâu thuẫn với lời khách, với dữ liệu BTC hoặc với chính bộ dữ liệu, nên agent làm đúng vẫn bị chấm trượt. Ví dụ: cuộc chat không nối được với cuộc sau; đòi nhớ `owned_sku` của món không liên quan; đơn vượt hạn mức COD mà khách chưa đồng ý chuyển khoản; `promo_active: true` khi chỉ có freeship.
- **Bằng chứng:** bản tổng hợp nhãn của người làm tập dev (08/11/2026). Mình tính lại từng nhóm trên `data/dev` và pack BTC (`promotions.json`, `crm_seed.json`, `inventory_timeline.json`), vì các file bằng chứng mà bản tổng hợp dẫn tới không có trên máy. Khi đọc lại nhãn ASR, mình thấy 22 nhãn `promo_expiry` thật ra là ngày hẹn gọi lại.
- **Sửa:** revision mới `data/dev-r4`, dựng bằng `evaluation/datasets/ground-truth-review/build_dev_r4.py`; `data/dev` không đổi. 515 dòng thay đổi (tính cả bản ASR của lời khách) được người duyệt chấp nhận (nhóm 1, 2, 3, 4 cho ADV-0028, 5, 8, 9, 10, phần định dạng của 11). 124 thay đổi do Claude đề xuất (ADV-0023, hotline nhóm 7, `blocker`/tiền/`promo_expiry`/`phone`/`restock_date` của ASR, tag nguồn), người duyệt chấp nhận cả bảng cùng ngày. Trong `conversion-report.json`, các mục này có `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-08`; cờ `CLAUDE_PROPOSALS_REVIEWED` trong script đưa chúng về `pending` nếu cần. Phần giữ nguyên và chưa làm ghi trong `DISPUTES.md`.
- **Đã kiểm:** 404/404 kịch bản nạp được; độ dài `customer_turns_asr` khớp. Oracle trên r4: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 vi phạm, 0 lỗi schema. Khi chuyển 124 đề xuất sang đã duyệt: dựng lại bằng `--force`, 2.582 file nhãn giống hệt từng byte, và 640 thay đổi trong report giữ nguyên nội dung, chỉ đổi trạng thái.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** audio của các lượt khách đã đổi (nhóm 1, 3, 10) chưa được sinh lại; hội thoại mẫu J02 và max_agent_questions chưa sinh lại (cần model); nhãn `blocker` có từ gợi ý chưa đọc; `official_gt_approved` vẫn false.

### 2026-11-08 · Chỉ đọc lại đơn khi đủ thông tin, và "đồng ý" kèm từ đệm vẫn tạo được đơn

Loại: hard guard, prompt · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** 23 cuộc trong `eval2` trượt TSR vì không có `order.create` nào (`success_if` chờ `order.create` khớp `args_match`). Khi trả lời câu agent đọc lại đơn, khách thường đưa thông tin còn thiếu chứ không nói "đồng ý", nên câu đọc lại bị phí. Còn khi khách đã đồng ý thì đơn vẫn không được tạo.
- **Bằng chứng:** `evaluation/runs/eval2-full-relabel-3`. Trong 23 cuộc, 19 có `pricing.get_quote` lỗi `BAD_ENVELOPE` vì tham số `payment` (đã sửa ở mục "Tham số thừa…", sau khi chạy run này); 13 cuộc đọc lại đơn ở lượt cuối nên không còn lượt để khách xác nhận. Trên toàn run có 153 câu trả lời ngay sau câu đọc lại đơn: 116 không phải lời đồng ý (phần lớn là địa chỉ hoặc cách thanh toán, ví dụ SCN-ADV-0018 call_2 lượt 3 "Giao hàng cho chị ở Thủ Đức"); 35 được `purchase.answer()` (qua `agrees()`) nhận là đồng ý nhưng không có đơn, trong khi `purchase.matches()` đòi `YES.fullmatch`; chỉ 2 tạo được đơn. `agrees()` còn từ chối "Ừ, vậy em lên đơn cho anh luôn đi." (SCN-GEN-0232) và "Chị đồng ý lên đơn rồi, em làm cho chị nhé." (SCN-GEN-0240). Mẫu BTC: cả 5 cuộc chấm `order.create` đều để khách nói "lên đơn" ở lượt cuối.
- **Sửa:** (1) `ActionGuardMiddleware` trả `ORDER_INCOMPLETE`, kèm phần còn thiếu và không phát hành bản nháp, khi đơn thiếu thanh toán do model truyền, thiếu địa chỉ (lấy từ lời khách hoặc bộ nhớ qua `order_arguments`) hoặc thiếu ngày giao từ `delivery.estimate` (`purchase.missing`, `purchase.estimated_delivery`). Câu đọc lại có thêm "giao dự kiến ngày …" (PB-09). Rule 12 trong `rule_packs.yaml` bỏ "thiếu địa chỉ hay thanh toán không phải lý do chờ / tự đặt COD": giờ chỉ hỏi phần còn thiếu, và gọi `order_create` ngay khi khách vừa đưa thông tin cuối cùng, để câu "chốt đơn" kế tiếp là lời xác nhận. (2) `purchase.matches()` dùng `agrees()`, cùng quy tắc với `answer()`; các điều kiện khác giữ nguyên: đúng câu đọc lại ở lượt trước, cùng nội dung đơn, còn trong 300 giây, có biên nhận HMAC. (3) `COURTESY` thêm "vậy", "làm"; câu có "nhưng", "đổi", "thêm", "chuyển khoản" vẫn không được tính là đồng ý.
- **Đã kiểm:** thêm 12 test trong `tests/agent/test_ec03_confirmation_isolation.py` (đơn thiếu từng trường; câu đọc lại có ngày giao; 4 câu đồng ý kèm từ đệm tạo được đơn; 4 câu có ý đổi đơn bị từ chối). Fixture được cập nhật cho đơn đủ thông tin. Kế hoạch mua sai trên kênh khác giờ dừng ở `ORDER_INCOMPLETE`, không còn tạo bản nháp. `tests/agent`: 1.285 passed; 11 failed và 14 errors đều nằm ở ASR và voice (`test_asr_*`, `test_voice_transport`), các file không bị đổi trong mục này.
- **Số đo:** chưa đo.
- **Quay lui một phần (merge `origin/main`, commit `1fac83c9`):** bỏ phần (1) `ORDER_INCOMPLETE`, vì skill đặt hàng của `main` cố ý cho tạo đơn khi chưa có địa chỉ (hỏi sau) và mặc định COD. Giữ lại ngày giao dự kiến trong câu đọc lại, phần (2) và phần (3). Đã bỏ các test đơn thiếu từng trường; giữ 3 test về ngày giao và câu đồng ý.
- **Còn lại:** khi lần đầu khách nói muốn mua lại rơi vào lượt cuối (như SAMPLE-02, SAMPLE-04, SAMPLE-05 của BTC), vẫn không còn lượt để xác nhận: đây là đánh đổi đã chọn (xác nhận trước khi tạo đơn). Số lượng mặc định là 1 khi khách không nói, và được đọc lại để khách sửa. Cần chạy lại các cuộc `order.create` của `eval2`, trước hết một kịch bản (SCN-ADV-0018).

### 2026-11-07 · Extractor v11: entity nạp từ contract, thêm today và crm_history

Loại: evaluation · Trạng thái: đang đo · Chỉ số: RQR, HR, CCR (đổi dụng cụ đo)

- **Vấn đề:** từ vựng của extractor được viết tay, lệch khỏi `contracts/scenario/scenario-keys.yaml`. Slot `return_reason` và `tracking` có trong contract nhưng extractor không có, nên câu hỏi về hai slot này bị gán `other` và RQR không thấy. `callback_at`, `gift_sku`, `new_variant_sku`, `successor_sku`, `price_vnd:<SKU>` và `future_promo_disclosed` có trong `ground_truth_facts` nhưng không bao giờ được trích, nên HR không kiểm các trường này. Fact lấy từ hồ sơ CRM (`seed_history`) không được tính là `facts_used`. Relabel `eval2` 3.592 lượt chạy nhiều giờ.
- **Bằng chứng:** so `scorers.vocabulary()`/`CLAIM_FIELDS` với contract: thiếu `return_reason`, `tracking`. Các trường claim mới xuất hiện trong kịch bản của `evaluation/runs/eval2-full-relabel-3/scenarios` (ví dụ `gift_sku` 51 lần, `callback_at` dạng `2026-10-19T19:00`). Về tốc độ: giới hạn OpenAI trong `models.yaml` là 200k token đầu vào/phút (giữ lại 10%). Mỗi lượt khoảng 6,6k token prompt cộng lịch sử, nên chỉ chạy được khoảng 20 lượt/phút. Ngoài ra cache 5,9 MB được ghi lại toàn bộ sau mỗi lượt, ngay trên event loop.
- **Sửa:** `scorers.contract()` đọc contract. `EXTRA_SLOTS` là các slot contract có mà ontology không có. `CLAIM_FIELDS` là khóa `ground_truth_facts` trừ `NOT_CLAIMS`, cộng `shipping_fee_vnd` và `cod_limit_vnd`. Thêm kiểu `datetime` (chuẩn hóa về `YYYY-MM-DDTHH:MM`) và `sku` (phải có đúng mã trong quote); `price_vnd:<SKU>` cũng phải có mã trong quote. `turn_input` nhận `today` và `crm_history`, do `cli.call_context` lấy từ plan của kịch bản, ở cả run thường lẫn relabel. Fact usage được giữ khi có `previous_sessions` hoặc `crm_history`. Prompt cập nhật theo bản người dùng đưa; vẫn giữ slot `issue` và quy tắc `estimated_delivery` của v10. Cache ghi theo lô (50 nhãn hoặc 30 giây, và một lần khi gắn nhãn xong) trong thread riêng, JSON không thụt lề. `VERSION` lên `product-extractor-v11`.
- **Đã kiểm:** chạy 11 file test extractor/relabel/eval trong `apps/ai-agent-service/.venv`: 126 passed. Ba test mới nằm trong `test_extractor_vocabulary.py` (entity theo contract; `callback_at`/SKU/`price_vnd:<SKU>`; `crm_history` làm bằng chứng). Python hệ thống thiếu `pytest-asyncio`, nên test async phải chạy bằng venv này.
- **Số đo:** chưa đo.
- **Còn lại:** hash và version đổi nên cache cũ không dùng được; relabel lại sẽ gọi model cho mọi lượt. Muốn nhanh hơn rõ rệt phải nâng `input_tokens_per_minute` của OpenAI theo tier thật của key, hoặc gắn nhãn cả một cuộc trong một lần gọi; cách sau lại đổi dụng cụ đo, cần duyệt trước. Các lỗi TSR "không có tool call order.create khớp args_match" là lỗi của agent, không phải của extractor, nên extractor không sửa được.

### 2026-11-07 · Extractor v10: một lượt không gán được nhãn không làm hỏng cả run

Loại: evaluation · Trạng thái: đang đo · Chỉ số: RQR, HR, CCR (đổi dụng cụ đo)

- **Vấn đề:** relabel `full` của `eval2` dừng ở lượt 521/3.747. Một lượt hỏng cả hai lần thử, và `_label` dừng mọi lượt còn lại.
- **Bằng chứng:** `evaluation/runs/eval2-full-relabel-2`, SCN-ADV-0061 call_2 lượt 4, câu "em chưa tra được giá chính xác lúc này": cả hai lần model trả `kind: "other"`, schema chỉ nhận `question`, `claim`, `fact_usage`. Prompt dùng `other` làm nhãn dự phòng của slot; ở nhiệt độ 0 chạy lại vẫn ra như vậy.
- **Sửa:** `scorers.Item` nhận `kind: other`, `label_items` bỏ mục đó và tính vào `changed`; `VERSION` lên `product-extractor-v10`. `cli._label` gán nhãn tiếp các lượt khác khi một lượt hỏng, trừ khi có `EVAL_BUDGET_DB`; bảng vẫn bị giữ khi còn lượt chưa gán nhãn.
- **Đã kiểm:** hai test mới trong `tests/agent/test_relabel_one_config.py`; `test_eval_guardrails` cập nhật theo hành vi mới; toàn bộ `tests/agent` chỉ còn lỗi ASR của môi trường.
- **Số đo:** chưa đo.
- **Còn lại:** đổi `scorers.py` đổi `prompt_sha256`, nên cache cũ không dùng được. Lần sửa trước (thử lại khi ghi cache) cũng đã đổi hash mà không nâng version: run `thu-1` có hash `bc5653…`, relabel lần 2 có `29c4d1…`. Không so số giữa các hash khác nhau.

### 2026-11-07 · Chấm riêng một cấu hình và extractor không còn treo

Loại: evaluation · Trạng thái: đang đo · Chỉ số: TSR, CCR, RQR, HR của `full`

- **Vấn đề:** `eval2` chạy xong `full` (404 kịch bản, 3.747 lượt) thì extractor đứng yên hơn 20 phút ở lượt 143 rồi tiến trình dừng. Manifest còn `INCOMPLETE`, không có baseline, nên relabel từ chối và không chấm được gì. Lúc gán nhãn cũng không in tiến độ, nên không phân biệt được treo hay đang chạy.
- **Bằng chứng:** `evaluation/runs/eval2`: cache extractor ghi lần cuối 16:43 với 143 mục; CPU của tiến trình không đổi; 5 kết nối HTTPS ở trạng thái `CLOSE_WAIT`.
- **Sửa:** `relabel` nhận `--config`: chỉ chấm cấu hình đó, không cần cấu hình kia. Một run dừng mà không ghi lý do chỉ được nhận khi chọn `--config` và trace của cấu hình đó đủ mọi lượt (`report.trace_errors`), không lượt hay `after_call` nào lỗi; lỗi đã ghi trong manifest vẫn chặn. `cli._label` giới hạn 300 s mỗi lượt: quá thì dừng với lỗi, phần đã gán nhãn giữ trong cache. In tiến độ sau mỗi 200 lượt. Lần relabel đầu dừng ở lượt 256 vì Windows từ chối ghi đè `extractor.json` (`PermissionError`, repo nằm trong OneDrive); `scorers._replace` thử lại 5 lần, vẫn bị giữ thì cảnh báo và gán nhãn tiếp.
- **Đã kiểm:** `tests/agent/test_relabel_one_config.py`, hai test mới trong `test_extractor_cache_integrity.py`. Kiểm `eval2` qua đúng các bước kiểm của relabel, không gọi model: đủ 3.747 lượt, không lỗi.
- **Số đo:** chưa đo.
- **Còn lại:** số của `eval2` là của code trước các bản sửa guard, chỉ dùng làm mốc. Relabel xoá `facts_used` cũ, nên CCR là cận dưới. Chưa tìm được vì sao lời gọi extractor treo dù đã đặt timeout 60 s; giới hạn 300 s chỉ chặn hậu quả.

### 2026-11-07 · Đo thời gian từng bước của một lượt

Loại: evaluation · Trạng thái: đang đo · Chỉ số: TTFT, Total Latency

- **Vấn đề:** trace chỉ có `ttft_ms` và `total_ms`, nên không biết giây nào đi vào model, tool, guard hay PolicyAgent, và không quyết được có nên thêm Redis. Langfuse chỉ thấy model và tool của advisor; PolicyAgent, hard guard, tra knowledge và nạp brief không có span, `stage_timings` gửi lên luôn rỗng.
- **Bằng chứng:** `evaluation/runs/eval2`, 3.419 lượt: TTFT p50 3,2 s, p95 9,3 s; Call Brief p50 84 ms, p95 267 ms; lượt có tool p50 3,9 s so với 1,6 s; lượt viết lại p50 6,3 s. Trung bình 2,03 lần gọi advisor và 0,91 lần gọi PolicyAgent mỗi lượt.
- **Sửa:** `observability/stopwatch.py` mở một đồng hồ mỗi lượt qua contextvar, đo thời gian thực của từng bước: `context`, `knowledge`, `compact`, `advisor` (thời gian chờ chữ tiếp theo, kể cả tool), `guard`, `policy`, `respond`, `persist`, `other`; thêm `model` và `tools` đo bên trong advisor. Hai tool chạy song song chỉ tính một lần. Ghi vào `diagnostics.jsonl` (`timings`), không vào trace BTC; `--performance` in bảng theo bước; API đưa vào `latency.stages_ms`, nên màn Developer và Langfuse (`stage_timings`) có số.
- **Đã kiểm:** `tests/agent/test_turn_stopwatch.py`, gồm một lượt qua graph thật với model giả. Toàn bộ `tests/agent` không thêm lỗi mới.
- **Số đo:** chưa đo; `eval2` chạy trước khi có đồng hồ.
- **Còn lại:** chạy lại một kịch bản để có bảng đầu tiên. PolicyAgent vẫn chưa có span riêng trên Langfuse. Khi stream, model chạy trước trong lúc câu đang được kiểm, nên `model` có thể dài hơn `chờ advisor`.

### 2026-11-07 · Guard nhận đúng nguồn của số tiền

Loại: hard guard, soft guard, tool · Trạng thái: đang đo · Chỉ số: TSR, HR, số lần fallback

- **Vấn đề:** phần lớn lần chặn số tiền là chặn oan, nên khách nhận câu an toàn thay cho câu trả lời đúng. `schedule.callback` lỗi `INTERNAL` khi chưa có số của khách.
- **Bằng chứng:** `evaluation/runs/eval2`, phân loại toàn bộ, không lấy mẫu: giá của lượt trước trong cùng cuộc; `1.400 W` bị đọc là tiền; ngân sách gõ không dấu hoặc kiểu "5 triệu rưỡi"; tổng các báo giá; phí bằng 8% giá theo BH-05; giá của Call Brief ở lượt mở đầu; `order.status` trả rỗng; PolicyAgent chặn số viết bằng chữ và số đã có trong tool. SCN-ADV-0093, SCN-ADV-0145: `schedule.callback` thiếu `customer_phone`.
- **Sửa:** `call_numbers` giữ số của giá, catalog và giao hàng trong cả cuộc; `allowed_amounts` nhận tổng các báo giá và tỷ lệ trong tài liệu nhân với giá; `itn` đọc "rưỡi" và bỏ số có đơn vị đo; `customer_amounts` đọc tiền không dấu; `PRICE_HISTORY` nhận cách nhắc giá cũ ở lượt mở đầu; `_order_state` chấp nhận tra rỗng và câu hỏi xác nhận; `open_amounts` để PolicyAgent chỉ xét số không có nguồn; thiếu số khách thì `actions` yêu cầu hỏi số, `crm` báo lỗi rõ thay vì `INTERNAL`.
- **Đã kiểm:** `tests/agent/test_money_sources.py`. Phát lại 140 bản nháp bị chặn qua guard mới, không gọi model: 92 qua, 48 còn bị chặn. Trong 48 ca có tổng tính sai thật (11.380.000 so với 10.935.000), và khoảng 15 ca lượt mở đầu mà bản phát lại không có giá của Call Brief.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** chạy lại `eval2` sau khi sửa. Theo dõi HR vì guard nới ra ở một số nguồn. Model viết lại nguyên câu ở 14 lần fallback, nên chưa dùng được lý do bị chặn để sửa câu.

### 2026-11-07 · Tham số thừa làm hỏng báo giá và chuyển máy

Loại: hard guard, tool · Trạng thái: đang đo · Chỉ số: TSR, HR

- **Vấn đề:** model truyền tham số tool không khai báo, server từ chối cả lần gọi và model chỉ nhận `BAD_ENVELOPE`. PolicyAgent chặn cả số có trong tài liệu đã đọc. Guard coi câu "em chưa chuyển được máy" là lời hứa chuyển máy.
- **Bằng chứng:** `evaluation/runs/eval2` (150 kịch bản, đang chạy): 141 trên 660 `pricing.get_quote` lỗi, cả 141 có `payment`, không lần thành công nào có; 3 `handoff.transfer` lỗi đều có `escalation_reason` thừa; 118 trên 1.290 lượt dính lỗi. SCN-ADV-0104 call_1 turn 4: chuyển máy lỗi, cả 3 bản nháp bị chặn, khách nhận câu an toàn. Lỗi tham số chỉ nằm ở 3 trên 36 lần fallback.
- **Sửa:** `advisor.declared_arguments` bỏ tham số không khai báo trước mọi tool; câu hỏi `unquoted_price` tính cả tài liệu đã đọc; `hard.TRANSFER_REFUSED` cho câu từ chối đi qua.
- **Đã kiểm:** `tests/agent/test_tool_arguments.py`. Chưa chạy lại `eval2`.
- **Số đo:** chưa đo.
- **Còn lại:** xem mục "Guard nhận đúng nguồn của số tiền".

### 2026-11-07 · Admin duyệt Knowledge Gap Loop

Loại: tính năng, hard guard · Trạng thái: đang đo · Chỉ số: HR

- **Vấn đề:** màn hình duyệt gap chỉ có ở trang developer; `gaps.resolve` không gọi `gap.gate` nên câu trả lời có số tiền, mã khuyến mãi hoặc tồn kho vẫn được xuất bản; không có cách loại câu không cần trả lời; nguồn trích có thể là chính sách hết hiệu lực.
- **Bằng chứng:** `gate` không có nơi gọi nào trong `gaps.py`; `KnowledgeGaps` chỉ được gắn trong `agent-console.tsx`.
- **Sửa:** gắn `KnowledgeGaps` vào `/admin`; `gaps.resolve` gọi `gate` và từ chối nguồn hết hiệu lực; thêm `gaps.dismiss` và `POST /api/developer/knowledge-gaps/{id}/dismiss`; câu đang mở hiện trước.
- **Đã kiểm:** `tests/agent/test_gap_review_and_judge.py`, `tests/agent/test_faq_admin.py`, `apps/web/e2e/gap-admin.spec.ts` với backend giả.
- **Số đo:** chưa đo; chưa có câu hỏi thật.
- **Sửa thêm:** `POST /api/developer/knowledge-gaps/{id}/faq` và nút "Chuyển thành FAQ nháp": tạo mục nháp `FAQ-GAP-<id>`, việc duyệt bật vẫn ở phần FAQ, không đổi phiên bản kiến thức.
- **Còn lại:** gom câu trùng nghĩa, chuyển kho gap sang DB, gợi ý câu trả lời, xóa bản sao trong FAQ khi khách yêu cầu xóa dữ liệu.

### 2026-11-07 · Trang quản lý FAQ và bộ FAQ nháp

Loại: tính năng · Trạng thái: đang đo · Chỉ số: token mỗi lượt, TSR

- **Vấn đề:** chưa có FAQ thật cho các đợt, và admin không có giao diện để thêm, sửa, xóa FAQ.
- **Bằng chứng:** `data/kb/v0.jsonl` trống; `kb_upsert` chỉ gọi được qua MCP.
- **Sửa:** thêm `data/kb/drafts.jsonl` (10 mục nháp lấy từ KM, LN, DT, VC), `components/knowledge/faq.py`, API `/api/developer/faq` chỉ cho admin, cột `status` trong `kb_chunks`, màn hình `faq-admin.tsx` ở `/admin`. Mục nháp không được agent đọc; bật cần người xác nhận và qua `gap.gate`.
- **Đã kiểm:** `tests/agent/test_faq_admin.py`; cả vòng đời trên database tạm của Postgres (nạp nháp, duyệt, tìm theo sản phẩm, hết hạn, tắt, xóa, khởi động lại không nạp lại mục đã xóa); `apps/web/e2e/faq-admin.spec.ts` trên Chromium với backend giả; `tsc --noEmit`. Chưa chạy trên service thật.
- **Số đo:** chưa đo; chưa có mục nào được bật.
- **Còn lại:** người duyệt đọc từng mục, gồm cả ngày mở đợt Giáng sinh và Tết do tôi tự chọn. Chưa phát hiện xu hướng từ cuộc gọi thật.

### 2026-11-07 · FAQ theo sản phẩm và theo đợt

Loại: knowledge, tính năng · Trạng thái: đang đo · Chỉ số: RAG, TSR, token mỗi lượt

- **Vấn đề:** mục FAQ của nhóm không gắn được với sản phẩm hay đợt khuyến mãi; `kb_upsert` không nhận ngày hiệu lực; đổi ngày trong bản phát hành không được ghi xuống `kb_chunks`.
- **Bằng chứng:** `sync_release` chỉ cập nhật khi title hoặc text đổi; `data/kb/v0.jsonl` trống; model chỉ đọc 3 đoạn mỗi lượt.
- **Sửa:** thêm `campaign`, `applies_to` trong `corpus.py`, lưu qua `provenance` nên không cần migration; `with_campaigns` lấy ngày và sản phẩm từ `promotions.json`, từ chối đợt không có ngày kết thúc; `search(about=...)` ưu tiên mục khớp sản phẩm và bỏ mục của sản phẩm khác; `shown_passages` đọc thêm tối đa 1 mục theo đợt khớp sản phẩm; `kb_upsert` nhận ngày, đợt, sản phẩm; `sync_release` so cả ngày và `provenance`.
- **Đã kiểm:** `tests/agent/test_knowledge_campaigns.py`; câu lệnh `sync_release` chạy trên database tạm của Postgres 16: dữ liệu giống thì không ghi, đổi `valid_to` thì cập nhật. `kb_upsert` chưa được gọi thật qua MCP.
- **Số đo:** RAG 60 câu không đổi (Recall@3 91,5, Recall@5 93,2), vì `v0` chưa có mục nào. Tác dụng thật chưa đo.
- **Còn lại:** thêm mục FAQ thật cho một đợt rồi đo. Bước phát hiện xu hướng từ cuộc gọi thật chưa làm. Mục do nhóm thêm vẫn cần người đối chiếu với chính sách.

### 2026-11-07 · Đo prompt cache và đặt `prompt_cache_key`

Loại: tính năng, evaluation · Trạng thái: đang đo · Chỉ số: token mỗi lượt, chi phí

- **Vấn đề:** agent dựa vào cache tự động của nhà cung cấp nhưng không ghi số token đọc từ cache, nên không biết tiết kiệm bao nhiêu.
- **Bằng chứng:** `token_ledger` chỉ có `calls`, `input`, `output`; `performance.py` ghi rõ chưa tính cache.
- **Sửa:** `token_ledger` thêm `cached`, đọc từ `input_token_details.cache_read`; `usage.json`, `performance.py` và `--report performance` có tỷ lệ cache, run cũ hiện "chưa đo"; `factory.cache_options` đặt `prompt_cache_key` theo từng agent cho OpenAI. Chi phí vẫn chưa trừ phần cache vì repo chưa có giá token cache.
- **Đã kiểm:** `tests/agent/test_knowledge_campaigns.py`, gồm kiểm khóa nằm trong payload của `ChatOpenAI`. Chưa gọi API thật.
- **Số đo:** chưa đo. Lần chạy `cache-thu-1` dừng vì `eval2` đang giữ database.
- **Còn lại:** chạy SCN-GEN-0050 khi `eval2` xong, đọc dòng cache trong `--report performance`, rồi quyết định có ổn định thêm phần prompt phía sau không.

### 2026-11-07 · Lọc chính sách không còn hiệu lực trước khi lấy top k

Loại: knowledge, prompt · Trạng thái: đang đo · Chỉ số: RAG, version accuracy, TSR

- **Vấn đề:** đoạn hết hiệu lực vẫn vào top 5 và text của nó vẫn tới model, chỉ kèm câu dặn đừng nhắc lại. Ngày đặt khách tự nói không được dùng. Khách có đơn ở hai bản chính sách bị lấy đơn mới nhất mà không hỏi. `NQ-*` ghi không dùng để tư vấn khách vẫn đọc được. Mục changelog được tính nhưng chưa tới model.
- **Bằng chứng:** `rag/qa_labeled.json`, 9 trên 60 câu trả về đoạn không áp dụng; Q43 không dùng ngày đơn. 20 trên 22 khách có đơn nằm ở cả hai phía 01/10/2026.
- **Sửa:** `KnowledgeBase.search` lọc theo `in_force` trước khi lấy top k, bỏ `superseded`, `validity`, `counterpart`; `stated_order_day` đọc ngày đặt từ lời khách, dùng cho cả hot path và `rag.py`; `version_differs` thêm ghi chú để agent hỏi đơn nào; `_passages` gửi kèm mục changelog của đoạn bị lọc, ngoài hạn mức 3 đoạn model đọc (`shown_passages`); tiêu đề tài liệu quyết định `restricted` và ngày hết hiệu lực; sửa luật 3 trong `rules.md`.
- **Đã kiểm:** `tests/agent/test_knowledge_in_force.py`; bộ `tests/agent` không có lỗi mới so với trước.
- **Số đo:** RAG 60 câu, hybrid, trước và sau như nhau: Recall@3 91,5, Recall@5 93,2, abstain không trả lời được 75, abstain restricted 60, false abstain 0. Keyword cũng không đổi. Câu có đoạn không áp dụng: 9 xuống 0, Q43 là câu duy nhất lấy bản cũ và đúng. Tác động lên TSR, RQR chưa đo vì chưa chạy agent.
- **Còn lại:** chạy nhóm kịch bản đổi trả để xem câu hỏi "đơn nào" có làm tăng RQR không. Với đơn cũ, DT-06 và DT-07 không có bản cũ tương ứng nên không còn được đọc. Khách hỏi về ghi âm cuộc gọi giờ nhận câu thông tin nội bộ vì NQ-03 bị chặn. Mục FAQ do nhóm thêm chưa được đối chiếu tự động với chính sách.

### 2026-11-07 · `run_all --output`

Loại: tính năng · Trạng thái: xong · Chỉ số: không áp dụng

- **Vấn đề:** chạy thử `run_all --fresh` không chỉ định thư mục sẽ xóa dữ liệu sinh ra trong `data/dev`, bộ dữ liệu duy nhất; chỉ đổi được thư mục đích qua `--seed` hoặc biến môi trường.
- **Bằng chứng:** `Dataset.clear` xóa các thư mục dữ liệu trong thư mục output, mặc định là `data/dev`.
- **Sửa:** `run_all.py` thêm `--output`, tính đường dẫn từ nơi gõ lệnh và truyền cho mọi bước qua `DATAGEN_OUTPUT`. Lệnh mẫu trong README có `--fresh` đều kèm `--output`.
- **Đã kiểm:** `tests/test_run_all_output.py`; chạy thật `--plan-only --output`, `data/dev` không đổi.
- **Số đo:** không áp dụng.
- **Còn lại:** `--fresh` không kèm thư mục vẫn xóa `data/dev`; chưa thêm chặn.

### 2026-11-07 · Chỉ giữ một bộ dữ liệu: `data/dev`

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không đổi cách chấm

- **Vấn đề:** ba bản `seed-dev`, `seed-dev-r2`, `seed-dev-r3` nằm cạnh nhau, tài liệu và đồng đội không chắc phải chạy bản nào.
- **Bằng chứng:** r3 chỉ có ở máy cục bộ, `seed-dev` trong git là bản chưa sửa nhãn.
- **Sửa:** đổi tên r3 thành `data/dev`, chép `asr_test/` từ r2 sang, xóa `seed-dev` và r2. Bộ sinh dữ liệu ghi vào `data/<tên>`, mặc định `data/dev`. Xóa `revise_seed_dev_r3.py` vì nguồn của nó không còn. `--report` so bộ kịch bản theo hash file, nên đổi tên thư mục không làm run cũ thành bộ khác. Báo cáo có ngày giữ nguyên.
- **Đã kiểm:** hash `scenarios/` trước và sau khi đổi tên trùng nhau; 404 kịch bản, 73 file `asr_test/`.
- **Số đo:** không áp dụng, nội dung kịch bản và nhãn không đổi.
- **Còn lại:** `seed-dev-r2` không còn bản nào vì chưa từng vào git; `seed-dev` còn trong lịch sử git.

### 2026-11-06 · Skill viết tài liệu kèm sơ đồ

Loại: tính năng · Trạng thái: xong · Chỉ số: không áp dụng

- **Vấn đề:** chưa có quy tắc chung để viết tài liệu đủ chi tiết và biết khi nào cần vẽ sơ đồ.
- **Bằng chứng:** yêu cầu của người dùng ngày 06/11.
- **Sửa:** thêm `.claude/skills/write-docs/SKILL.md`: đọc code trước khi viết, độ chi tiết của một trang, chọn loại Mermaid theo nội dung như `docs/ai/`, và các bước kiểm.
- **Đã kiểm:** đọc lại quy ước tài liệu và sơ đồ đang có trong repo. Skill chưa được dùng thử trên một trang thật.
- **Số đo:** không áp dụng.
- **Còn lại:** không.

### 2026-11-06 · Hợp nhất commit `06a5ecad` với thay đổi bộ nhớ và dữ liệu

Loại: evaluation, dữ liệu · Trạng thái: xong · Chỉ số: không đổi cách chấm

- **Vấn đề:** rebase `408e2769` lên `06a5ecad` xung đột ở 7 file: upstream chọn `data/seed-dev`, commit chọn `data/seed-dev-r3`; cả hai cùng sửa lỗi kênh `fb`; commit xóa `evaluation/datasets/README.md` mà upstream vừa cập nhật.
- **Bằng chứng:** `seed-dev` và r2 chỉ khác 2 file kịch bản; r3 sửa nhãn trên r2 (168 file khác, 404 kịch bản) và không nằm trong git.
- **Sửa:** r3 là đường chạy hiện tại; giữ `evaluation/datasets/README.md` vì đó là nơi duy nhất ghi ID đã dùng và holdout; `scenarios.py` chỉ còn `CRM_SESSION_CHANNELS`; `_TEMPLATE.md` trỏ đúng danh sách ID.
- **Đã kiểm:** không còn dấu xung đột; test evaluation, prompt, bộ nhớ, BTC pack và budget: 100 qua, 1 lỗi khóa file trên Windows có từ trước.
- **Số đo:** không áp dụng, code chấm và nhãn không đổi.
- **Còn lại:** không; r3 đã trở thành `data/dev` (xem mục 07/11).

### 2026-11-06 · Cho model biết hôm nay là ngày nào

Loại: prompt · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** model không biết ngày hiện tại nên "tối mai" không đổi được thành ngày đúng; agent tự đoán năm, bị guard chặn rồi nói với khách là giờ đó ngoài giờ làm việc.
- **Bằng chứng:** `evaluation/runs/mem-truoc-2`, `mem-sau`, `mem-sau-2`, SCN-GEN-0050 call_1 turn 5: `schedule.callback` với `callback_at` năm 2024, bị chặn "đã qua".
- **Sửa:** `advisor.system_prompt` thêm dòng "Bây giờ là ..." vào phần lane; `run_eval` in và ghi `advisor_context`; thông báo riêng khi thư mục chỉ có `run.lock` rỗng.
- **Đã kiểm:** `test_prompt_focus.py`, `tests/agent`; chạy thật SCN-GEN-0050 ở cả hai chế độ.
- **Số đo:** SCN-GEN-0050, TSR 0 lên 100 ở cả hai chế độ (`date-full`, `date-focused`). Chỉ một kịch bản.
- **Còn lại:** đo trên nhóm kịch bản hẹn gọi lại. Ở `date-focused`, call_2 agent đặt thêm một lịch 27/10 không có trong nhãn.

### 2026-11-06 · Luật lõi, episode và tra lịch sử

Loại: prompt, slot bộ nhớ, tool · Trạng thái: đang đo · Chỉ số: token mỗi lượt, CCR, RQR

- **Vấn đề:** luật lõi còn 1.389 token; episode không có mục tiêu và việc còn dở; agent không tra được lời đã nói ở cuộc trước.
- **Bằng chứng:** đo `tokens(HARD_RULES)`; bảng `episodes` chỉ có `summary`, `outcome`, `commitments`.
- **Sửa:** chuyển luật 11, 14, 18, 19, 21 sang `rule_packs.yaml`; `episodes` thêm cột `goal`, `open_items`, `MemoryAgent.goal_of` lấy mục tiêu bằng code; brief có dòng việc còn dở; thêm tool `memory_search_calls` cho lane CONTINUITY, che token PII và bỏ qua cuộc hiện tại.
- **Đã kiểm:** `tests/agent` 1.117 test qua; 4 fail và 14 error thuộc nhóm ASR, voice và khóa file. Trên PostgreSQL thật (database tạm): migrate bảng cũ giữ nguyên dữ liệu, chạy lại an toàn; câu truy vấn đúng khách, bỏ cuộc hiện tại, che token. Luật lõi 1.045 token, toàn bộ 2.547 token.
- **Số đo:** `chưa đo`.
- **Còn lại:** chạy thật một kịch bản; `run_eval` không có bảng `turns` nên tool chỉ tìm được trong episode khi đánh giá.

### 2026-11-06 · Prompt đủ bằng chứng, nạp theo tình huống, có trạng thái cuộc

Loại: prompt, slot bộ nhớ, tool · Trạng thái: đang đo · Chỉ số: TSR, CCR, RQR, HR, token mỗi lượt

- **Vấn đề:** agent trả lời lệch yêu cầu, prompt dài và có thể mất đúng phần nó phải dựa vào.
- **Bằng chứng:** ngân sách 3.000 token, luật cứng chiếm 2.663. Trên ngữ cảnh mẫu, `knowledge` và `summary` bị cắt; `products` và `orders` cũng thuộc diện bị cắt. Danh sách phần bị cắt bị bỏ đi. Có hai luật 12.
- **Sửa:** `budget.py` chỉ còn playbook là tùy chọn, ngân sách 4.000; `focus.py` chọn luật và dòng brief theo lượt, công tắc `ADVISOR_CONTEXT=full`; `rule_packs.yaml` tách 8 luật và gộp luật 12; `call_state.py` giữ điều khách đã nói, sản phẩm vừa báo giá, câu hỏi đang mở; "Yêu cầu hiện tại" đặt cuối prompt; brief đánh dấu blocker đã xong; thêm `memory_get_episodes` cho lane CONTINUITY; diagnostics có `context`.
- **Đã kiểm:** test mới `test_prompt_focus.py` và bộ `tests/agent` (kết quả ở báo cáo của lượt này). Luật lõi và kích thước cuối xem mục "Luật lõi, episode và tra lịch sử".
- **Số đo:** `chưa đo`. So trước/sau bằng `ADVISOR_CONTEXT=full` trên cùng cohort.
- **Còn lại:** nhận chủ đề bằng từ khóa có thể sót, sai sót chỉ làm thiếu luật chứ không mất tool; cần xem `context.packs` trên trace thật.

### 2026-11-06 · Bảng báo cáo `--report`

Loại: evaluation · Trạng thái: đang đo · Chỉ số: tất cả

- **Vấn đề:** chưa có lệnh ghép bảng ASR, Agent và hiệu năng theo cấu hình cho báo cáo.
- **Bằng chứng:** `run_eval.py` chỉ in bảng Baseline/Hệ thống; WER, CER và hiệu năng nằm ở các lệnh riêng.
- **Sửa:** thêm `pipeline/eval/tables.py`, các tham số `--report`, `--run`, `--asr-run`, `--kb-version`; biến môi trường `KNOWLEDGE_VERSION` trong `config_manager.py`.
- **Đã kiểm:** 18 test liên quan qua; `--report all --run router=evaluation/runs/test` in đúng ba bảng.
- **Số đo:** không áp dụng.
- **Còn lại:** chưa chạy `--report` kèm một run mới, `--kb-version` và bảng ASR trên run thật. GapLoop, Reflection cần knowledge version có mục đã duyệt (`v0.jsonl` đang rỗng). Subagent và A/B Testing chưa có trong agent.

### 2026-11-06 · Tạo audio chỉ cho lượt đã đổi

Loại: dữ liệu · Trạng thái: xong · Chỉ số: chi phí tạo dữ liệu

- **Vấn đề:** đổi một câu làm phải tạo lại dạng đọc của cả cuộc; câu chèn vào làm lệch số lượt nên clip cũ không dùng lại được.
- **Bằng chứng:** r3 có 42 cuộc thêm câu đồng ý và 73 cuộc khôi phục câu cuối; r3 chưa có clip nào.
- **Sửa:** thêm `carry_audio.py`; `reference.load_or_build` chỉ gọi model cho dòng mới; `synthesize_scenario_audio` có `--changed-only`, `--only`, `--dry-run`, và giữ giọng của cuộc.
- **Đã kiểm:** 105 test `data-generation` qua; sau khi chạy, `--dry-run` báo 0 lượt còn thiếu.
- **Số đo:** dùng lại 3.612 clip, tạo mới 135 lượt, gửi 2.766 ký tự (31 lượt lấy từ cache). Chưa tính chi phí model viết dạng đọc.
- **Còn lại:** `asr_test/` vẫn ở `seed-dev-r2`.

### 2026-11-06 · Giữ `blocker` khi model bộ nhớ bỏ sót, đọc được ASR không dấu

Loại: slot bộ nhớ · Trạng thái: đang đo · Chỉ số: CCR

- **Vấn đề:** ý "cần bàn với gia đình" không vào bộ nhớ, nên cuộc sau không nhắc lại được.
- **Bằng chứng:** `evaluation/runs/test`, SCN-GEN-0050 call_1: model bộ nhớ đã chạy, ghi `callback_time` nhưng không có `blocker`. Regex chỉ chạy khi model lỗi và chỉ khớp chữ có dấu.
- **Sửa:** `agents/memory.py`: lớp `Words` đọc câu không dấu; `BACKSTOP` giữ `blocker`, `decision_maker` từ luật khi model bỏ sót, trừ khi cuộc đã có đơn. Thêm `fold`, `unmarked` vào `intake/text.py`; thêm hướng dẫn vào `memory_extractor.md`.
- **Đã kiểm:** 66 test bộ nhớ qua, gồm `test_memory_unmarked.py`.
- **Số đo:** `chưa đo`.
- **Còn lại:** chạy lại SCN-GEN-0050 để xác nhận CCR. Đổi prompt nên extractor của bộ nhớ có version mới.

### 2026-11-05 · Nhận lời đồng ý mua có từ xưng hô

Loại: action guard · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** khách nói đồng ý kèm từ xưng hô thì đơn không được tạo.
- **Bằng chứng:** `YES.fullmatch` từ chối 72 trong 73 câu xác nhận được khôi phục ở r3.
- **Sửa:** `guardrails/purchase.py`: thêm `CONSENT`, `COURTESY`, `agrees`. Câu chỉ gồm lời đồng ý và từ lịch sự mới tính; câu có thêm yêu cầu khác thì không.
- **Đã kiểm:** test agent liên quan qua.
- **Số đo:** `chưa đo`.
- **Còn lại:** số TSR r3 không so trực tiếp với r2 vì nhãn đã đổi.

### 2026-11-05 · Hẹn gọi lại đúng giờ, gồm ngày nghỉ và 11/11

Loại: action guard · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** giờ hẹn có múi giờ không khớp `args_match` của BTC; guard chặn giờ khách xin vào ngày nghỉ; agent hứa gọi lại mà chưa gọi tool.
- **Bằng chứng:** báo cáo lỗi bộ `seed-dev` mục thời gian; SCN-GEN-0050 hứa gọi lại.
- **Sửa:** `clock.tool_time` bỏ múi giờ; `SPECIAL_HOURS` cho 11/11; `actions._schedule_callback` cho phép ngày nghỉ để mock dời giờ; `hard.moved_callback` buộc báo giờ mới; guard chặn câu hứa khi chưa gọi tool; `crm.py` giữ giờ hợp lệ của 11/11.
- **Đã kiểm:** `test_callback_time.py` qua.
- **Số đo:** `chưa đo`.
- **Còn lại:** mock của BTC không biết giờ 11/11, nên SCN-ADV-0154 chỉ đúng qua wrapper của agent.

### 2026-11-05 · Bộ dữ liệu `seed-dev-r3`

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: TSR, CCR

- **Vấn đề:** kịch bản bị cắt câu xác nhận cuối, thiếu câu đồng ý, sai kênh `fb`, thiếu ca hẹn ngoài giờ và ngày nghỉ.
- **Bằng chứng:** báo cáo lỗi bộ `seed-dev`; chi tiết từng trường ở `data/seed-dev-r3/conversion-report.json`.
- **Sửa:** `revise_seed_dev_r3.py`, thêm stage `sync_customer_turns`, `check_labels`. Thêm SCN-ADV-0151..0154, dời SCN-GEN-0224 call_2.
- **Đã kiểm:** 404/404 kịch bản nạp được; oracle CCR 100, RQR 0, TSR 100, HR 0; hội thoại mẫu TSR 98,8.
- **Số đo:** `chưa đo` trên agent thật.
- **Còn lại:** nhãn chưa có người duyệt; xem `data/seed-dev-r3/DISPUTES.md`, gồm SCN-ADV-0023, SCN-ADV-0028 và 34 cuộc J02.
