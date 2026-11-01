# Luồng đi vào bộ chấm

Một trang để biết một con số RQR, CCR, TSR hay HR đến từ đâu. Có **một đường duy nhất**: `run_eval.py` ở gốc repo, cũng là lệnh giám khảo sẽ gọi (`run_eval.py --scenarios <thư mục> --config full|baseline_no_memory --out <file>`). Mã nằm ở `apps/ai-agent-service/src/ai_agent_service/pipeline/eval/` và `components/evaluation/scorers.py`.

## 1. Ba điều cần nhớ

1. **Con số chính thức là `reference_eval.py` của BTC**, chạy nguyên bản như một tiến trình riêng trên hai file trace. Đội không tính lại công thức nào. Gói BTC là bản duy nhất trong repo (`apps/ai-agent-service/data/btc`), và `tests/agent/test_btc_pack.py` ghim hash từng file để nó không đổi lặng lẽ.
2. **Script đó chỉ đọc trace**, không đọc hội thoại. Mọi thứ nó cần phải có sẵn trong mỗi dòng: `questions[]`, `claims[]`, `facts_used[]`, `tool_calls[]`, `latency`, `memory_writes`. BTC không phát extractor: việc trích `questions` và `claims` là của đội, và BTC chấm tay ngẫu nhiên 20 lượt để bắt extractor bỏ sót hoặc bịa.
3. **Đổi extractor là đổi dụng cụ đo.** Chỉ so các số do cùng một `extractor_version` ra (hiện `product-extractor-v5`: từ v5, câu đọc lại đơn trước khi tạo là **một** câu xác nhận `order_summary`, không còn một câu cho mỗi chi tiết; số của v4 so với v5 bằng `run_eval.py --relabel`).

## 2. Luồng một lần chạy

```
run_eval.py --scenarios <thư mục> [--config ...] [--only ID] [--no-extract] --out <thư mục>
 │
 ├─ scenarios.py   đọc từng *.json, lập kế hoạch từng cuộc: ngày (15/10/2026 + days_later hoặc call_date),
 │                 khóa nhận diện kênh, lượt khách (customer_turns_asr nếu có), seed_history
 │
 ├─ runner.py      với mỗi cấu hình (full rồi baseline_no_memory), mỗi kịch bản:
 │                   • xóa trạng thái trong database <tên>_eval, nạp seed_history
 │                   • mỗi cuộc: nhận diện → dựng Call Brief → từng lượt chạy qua đồ thị agent → after_call
 │                   • 3 lượt khởi động không ghi (--warmup)
 │                 full đọc bộ nhớ; baseline_no_memory chỉ tắt ĐỌC (after_call vẫn ghi)
 │
 ├─ trace.py       một dòng trace BTC mỗi lượt agent: customer_text, agent_text (đã trả PII), tool_calls (tên, tham số
 │                 thực chạy, kết quả), latency (ttft_ms, total_ms), call_brief_latency_ms (lượt 1 của call_2/3),
 │                 memory_writes (dòng cuối mỗi cuộc), facts_used từ trích dẫn [Bn]; questions/claims để trống
 │
 ├─ cli._label     SAU khi chạy xong mọi kịch bản của một cấu hình (không chen vào lượt đo thời gian):
 │                 extractor gắn questions, claims, facts_used cho từng dòng (mục 4)
 │
 ├─ kiểm tra       mỗi dòng đối chiếu schemas/trace_log.schema.json; đếm lượt lỗi, lượt chưa gắn nhãn, after_call lỗi.
 │                 Có lỗi chặn (report.BLOCKING) thì KHÔNG in bảng, thoát mã 1, trace vẫn được giữ
 │
 └─ report.grade   python reference_eval.py --scenarios ... --trace full.jsonl --baseline baseline.jsonl
                   → report.json, table.txt  ← SỐ CHÍNH THỨC; thêm bảng Recall@k của RAG (rag.py)
                   → team_checks.json        ← kiểm tra của nhóm (say_at_most), chẩn đoán, in dưới bảng
```

Có `--config` thì chỉ chạy và ghi một file trace, không chấm (BTC sẽ ghép hai file rồi tự chạy `reference_eval.py`).

## 3. Công cụ nghiệp vụ

Chín công cụ của BTC (`crm.get_customer`, `catalog.search`, `inventory.check`, `pricing.get_quote`, `order.create`, `order.status`, `order.update`, `schedule.callback`, `handoff.transfer`) do máy chủ MCP của sản phẩm trả lời (`mcp/servers/{catalog,crm,order}.py`). Chúng **bọc đúng `eval/mock_tools.py` của BTC**, không viết lại logic: giá sau khuyến mãi, tồn kho theo ngày, giới hạn COD, ngày nghỉ, SĐT dùng chung đều là hàm của BTC. Khách tổng hợp của đội (`catalog/crm_seed_synthetic.json`) được thêm vào CRM của mock trong bộ nhớ khi nạp; id và số điện thoại trùng khách BTC thì bị bỏ. Trạng thái (đơn, lịch hẹn, phiếu) lưu trong một dòng `mock_state` của Postgres, và được xóa giữa các kịch bản.

Sản phẩm thêm vài thứ ngoài mock: khóa idempotency cho lệnh ghi, `delivery.estimate`, tìm sản phẩm dễ tính hơn. Chúng nằm trong lớp bọc, không đổi kết quả của hàm BTC.

## 4. Extractor

`scorers.Extractor`, một lần gọi mô hình mỗi lượt (`gpt-4.1-mini`, temperature 0, cấu hình `agents.extractor` trong `models.yaml`), prompt [`extractor.txt`](../../config/prompts/evaluation/extractor.txt) nạp nguyên văn.

- **Đầu vào mỗi lượt:** lời agent, tên và tham số các tool đã gọi (không có kết quả), và từ call_2 trở đi `previous_sessions` (lời khách và lời agent của các cuộc trước, cùng kịch bản, cùng cấu hình; baseline chỉ thấy lời của baseline). Không bao giờ có nhãn, kỳ vọng, bộ nhớ hay đáp án.
- **Đầu ra:** các `Item` {kind, slot_or_field, value, question_type, speaker, source_field, quote, start, end, purpose}. Ánh xạ sang trace BTC: `question` → `questions[{slot, type, text=quote}]`, `claim` → `claims[{field, value, text=quote}]`, `fact_usage` → `facts_used[slot]`.
- **Hai lượt kiểm tất định sau khi mô hình trả lời:** `spanned()` chỉ giữ item mà `quote` tìm thấy đúng trong lời agent hoặc tham số tool (tính lại offset; quote lấy từ `previous_sessions` hay từ chỗ khác bị bỏ và đếm); `restrict()` ép về từ vựng cố định (35 slot = 34 của ontology + `channel`; 18 trường claim + `promo_<CODE>_active`), ép giá trị về đúng kiểu (`5200000` chứ không phải `"5.200.000đ"`), áp quy tắc grounding và khử trùng.
- **`facts_used`** = slot extractor thấy được dùng lại từ cuộc trước, rồi slot của các dòng brief agent đã trích dẫn `[Bn]`, mỗi slot một lần.
- **Lỗi một lượt là lỗi của cả run:** extractor thử hai lần; vẫn lỗi thì lượt đó "unlabelled" và bảng không được in. Quote sai, slot lạ, giá trị không ép được chỉ làm item bị bỏ hoặc chỉnh, và được đếm (`extraction_dropped_items`, `extraction_changed_items`).
- **Cache** `evaluation/runs/cache/extractor.json`, khóa theo prompt + model + toàn bộ đầu vào (kể cả lịch sử). Đổi prompt hay lịch sử thì tự mất hiệu lực.
- **Gắn nhãn lại không chạy lại agent:** `run_eval.py --relabel <run> --out <thư mục>` lấy lời agent đã có trong một run cũ, xóa nhãn cũ, gắn lại bằng extractor hiện tại và chấm bằng `reference_eval.py`. Đo extractor, không đo agent hiện tại; `facts_used` chỉ gồm phần extractor thấy (cận dưới của CCR).

## 5. Con số nào đến từ đâu

| Chỉ số | Hàm trong `reference_eval.py` | Trường trace nó đọc | Ai sinh trường đó |
|---|---|---|---|
| RQR | `repeat_question_rate` | `questions[].slot`, `.type`; `must_not_ask` | extractor |
| CCR | `context_carryover_rate` | `facts_used[]` và tên khóa trong `tool_calls[].args`; `must_carry_over` | extractor + trích dẫn `[Bn]` |
| TSR | `task_success_rate` → `check_call` | `tool_calls`, `agent_text`, `claims` (cho `forbidden_claims`), `questions` (cho `max_agent_questions`), `memory_writes` | agent (tool), extractor |
| HR | `hallucination_rate` | `claims[].field`, `.value` so với `ground_truth_facts`; HR giá&KM là các trường bắt đầu `price`, `promo`, `list_price` | extractor |
| Guardrail | `guardrail_violations` | `agent_text`, `memory_writes`, `tool_calls[].args`, claim `is_human` | agent, extractor |
| Latency | `latency` | `latency.ttft_ms`, `total_ms`, `ttfa_ms`, `call_brief_latency_ms` | mốc thời gian quanh đồ thị agent |
| Số lượt TB, Calls-to-Close | `avg_turns`, `calls_to_close` | số dòng trace; `order.create` trong `tool_calls` | agent |

Điều cần nhớ khi viết hay sửa prompt extractor (đã kiểm trên `reference_eval.py`):
- RQR: câu `open` về slot trong `must_not_ask` là thừa; câu `confirm` lần thứ hai trở đi về cùng slot trong một cuộc cũng thừa; `confirm` lần đầu không thừa. Mọi câu hỏi, kể cả `other`, đều vào mẫu số.
- HR: chỉ claim có trường nằm trong `ground_truth_facts` của cuộc đó mới được tính, và so bằng `!=` chính xác, nên kiểu giá trị (số nguyên, bool, chuỗi) phải đúng.
- CCR: không kiểm nguồn của `facts_used`; định nghĩa của BTC là "slot từ phiên trước được dùng có ý nghĩa".
- Latency: BTC lấy mọi dòng, nhưng hướng dẫn đo của họ bảo bỏ 3 lượt khởi động và cần ≥ 100 lượt để p95 có ý nghĩa; lệnh chạy bỏ 3 lượt khởi động bằng `--warmup`.

## 6. Điểm dễ nhầm

- **Không có bộ mô phỏng khách.** Khách nói đúng `customer_turns` viết sẵn của kịch bản, đúng như BTC chấm. Agent hỏi thừa thì khách vẫn nói câu kế tiếp.
- **Tắt extractor** (`--no-extract`): `questions` và `claims` rỗng, nên RQR và HR không đo (`None`), nhưng TSR của các cuộc chỉ cần tool vẫn có số. Agent vẫn gọi model, nên vẫn tốn phí.
- **Chạy trên bộ ẩn của BTC:** BTC thay `--scenarios` và tự gọi hai lần với `--config`; kết quả chính thức là bảng họ chạy `reference_eval.py` trên hai file trace đó, kèm cách trích `questions`/`claims` ghi trong báo cáo của đội.
- **Dữ liệu và bằng chứng:** `evaluation/datasets/` (kịch bản v4), `evaluation/runs/` (không lên Git). Xem [`evaluation/README.md`](../../evaluation/README.md).
