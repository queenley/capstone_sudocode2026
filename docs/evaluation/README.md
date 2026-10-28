Revision kiến trúc hiện tại: [bằng chứng, sửa đổi và kiểm chứng](2026-10-22-architecture-fixes.md).

Sửa từ log sau khi đóng run: [revision offline](2026-10-22-log-fixes.md).

Kết quả ngày 22/10/2026: [báo cáo và giới hạn](2026-10-22-results.md).

# Đánh giá

Lịch sử chọn case và run mới: [RUN-LEDGER.md](RUN-LEDGER.md). Trước khi chạy thêm, kiểm danh sách đã chạy và holdout để tránh trùng.

Main hiện có runner BTC ở gốc repo (`run_eval.py`) và harness phân tích tại `evaluation/agent-evaluation/run_eval.py`. Xem [bản đồ hiện tại](system-map.md) và [đợt kiểm ngày 22/10/2026](2026-10-22-worklog.md). Các bảng số liệu và ghi chú runner stub bên dưới là tài liệu lịch sử, không phải readiness mới nhất.

Mọi con số dùng trong báo cáo đều được tính bằng code chấm của BTC: `apps/ai-agent-service/data/btc/eval/reference_eval.py`. Repo có ba tầng đánh giá, xếp từ rẻ đến đầy đủ:

| Tầng | Lệnh | Cần gì | Đo gì |
|---|---|---|---|
| 1. Test | `python -m pytest -q` | không gì | lane, hard guard, PII, ITN; contract của route agent; workflow nền tảng |
| 2. Retrieval của agent | `python evaluation/agent-evaluation/run_eval.py rag-offline` | không gì | Recall@3/@5, multi-hop, tỉ lệ từ chối (abstain), `rag_eval` của BTC |
| 3. End-to-end Chương A | `evaluation/data-generation` + `reference_eval.py` | stack đang chạy + key model | CCR, RQR, TSR (+ hard case), HR (+ giá/khuyến mãi), guardrails, latency, ASR |

CI chạy tầng 1 và 2 ở mỗi push. Tầng 2 ghi `reports/generated/evaluation.json`, CI upload file này thành artifact.

## Tầng 1: test

- `tests/agent/`: logic agent không cần model hay database. Gồm bảng lane (7 luật, luật khớp đầu tiên thắng); hard guard (giá phải có trong kết quả tool, mã đơn chỉ đọc cho khách đã xác minh, không nhận là người, không lộ PII hay giá nhập, phải trả lời tiếng Việt); mã hóa số điện thoại ở mọi cách viết, không nhầm với số tiền; ITN số tiền nói.
- `tests/test_agent_turns.py`: route `/turns`, `/stream` với một agent giả lập (`ScriptedAgent` trong `tests/conftest.py`). Kiểm tra định dạng TurnResult, replay theo `turn_id`, SSE, transcript đã che PII, handoff sang platform, và mã 404/409.
- `tests/test_workflows.py`, `test_transfer.py`, `test_auth_mcp.py`, …: định danh, order, khuyến mãi, duyệt tri thức, chuyển nhân viên, RBAC, đủ 9 tool của BTC trên các MCP server.

## Tầng 2: retrieval của agent

`evaluation/agent-evaluation/run_eval.py rag-offline` cho chính retriever của agent (`kb_search`: BM25 trên `data/btc/policy`, mỗi mục `## [XX-nn]` là một chunk) trả lời 60 câu trong `data/btc/rag/qa_labeled.json`. Agent được tính là "từ chối" khi không có kết quả nào, hoặc kết quả đầu là tài liệu nội bộ.

| Chỉ số | Retriever của agent | Baseline `create_data` |
|---|---:|---:|
| Recall@3 / @5 | 81.4 / 88.1 | 84.7 / 93.2 |
| Multi-hop full recall@5 | 58.3 | 66.7 |
| Từ chối khi không có câu trả lời | **0.0** | 87.5 |
| Từ chối khi hỏi thông tin nội bộ | 20.0 | 80.0 |
| Từ chối nhầm | 4.3 | 6.4 |

Việc cần làm tiếp: đưa luật từ chối của baseline (`evaluation/data-generation/src/rag/retriever.py`, `should_abstain`) vào `kb_search`. Khi agent không biết từ chối, câu hỏi ngoài tài liệu sẽ dẫn tới bịa câu trả lời, làm tăng HR.

## Tầng 3: chỉ số bắt buộc Chương A

[`evaluation/data-generation`](../../evaluation/data-generation/README.md) sinh kịch bản đúng format `test_set/public_sample`, phủ đủ 15 loại hard case. Nhãn được tính bằng cách **chạy** `mock_tools.py` của BTC, còn LLM chỉ viết lời thoại. Pipeline cũng sinh ground truth `trace_log`, CallBrief/HandoffBrief mong đợi, audio khách và bộ ASR của nhóm. Oracle (một agent lý tưởng) đạt điểm tuyệt đối trên 120 kịch bản / 260 cuộc gọi, nghĩa là mọi nhãn đều khả thi.

| Chỉ số | Nhãn trong kịch bản | Trường trace được đọc |
|---|---|---|
| RQR ↓ | `must_not_ask` | `questions[{slot,type}]` |
| CCR ↑ | `must_carry_over` | `facts_used`, `tool_calls[].args` |
| TSR ↑ (+ hard case) | `success_if`, `expected_outcome`, `hard_case` | `tool_calls`, `agent_text`, `claims` |
| HR ↓ (+ giá/khuyến mãi) | `ground_truth_facts` | `claims[{field,value}]` |
| Guardrails / over-escalation | `trace_must_not_match`, `expected_outcome` | `agent_text`, `memory_writes`, `tool_calls` |

Quy trình:

```powershell
cd evaluation/data-generation
python -m src.pipeline.run_all --plan-only               # kịch bản + nhãn + kiểm tra oracle, không tốn API
# chạy agent trên các kịch bản (chế độ đầy đủ và memory_enabled=false), xuất trace JSONL
python ../../apps/ai-agent-service/data/btc/eval/reference_eval.py `
  --scenarios output/scenarios --trace runs/full.jsonl --baseline runs/no_memory.jsonl --out report.json
```

Phần `comparison` trong `report.json` cho biết đã đạt ngưỡng của BTC chưa: RQR giảm ≥ 40% so với baseline, TSR ≥ 70%, HR về giá/khuyến mãi ≤ 5%.

Hai lần chạy so sánh phải dùng cùng dataset, model, temperature, tool và prompt; chỉ khác bộ nhớ giữa các phiên.

**Xuất trace:** `GET /api/developer/calls/{call_id}/trace?scenario_id=…&call=call_2&config=full&format=jsonl` chuyển một cuộc gọi đã lưu thành dòng `trace_log` (`runtime/trace_export.py`):

- `customer_text` và `agent_text` đã giải token;
- `tool_calls` dùng tên có dấu chấm, kèm args/result;
- có `latency`, và `call_brief_latency_ms` ở lượt 1 của call 2/3;
- `facts_used` lấy từ các dòng brief mà câu trả lời trích, cộng các giá trị brief được nhắc lại;
- `memory_writes` của after_call được gắn vào dòng cuối;
- `customer_input_mode` lấy từ lượt của khách.

`questions` và `claims` được trích bằng luật, như schema giao cho đội và báo cáo phải mô tả. Bảng luật nằm trong docstring của module. Test `tests/agent/test_btc_contract.py` chấm một trace xuất ra bằng chính các hàm của `reference_eval.py` (TSR 100, HR 0, RQR 0).

**Còn thiếu:** runner tự đưa từng kịch bản qua agent (`pipeline/eval/runner.py` vẫn là stub). Runner chỉ cần, với mỗi call: tạo conversation, gửi `customer_turns` (hoặc `customer_turns_asr`) qua `/turns`, kết thúc cuộc gọi, rồi nối JSONL của endpoint trên.

## Latency

`GET /api/developer/latency` tính p50/p95 của TTFT, total, TTFA và `call_brief` theo đúng công thức p95 của `reference_eval.py`, loại các lượt khởi động (warm-up), và so với ngưỡng BTC (3s / 8s / 2,5s / 3s). BTC yêu cầu ít nhất 100 lượt thì p95 mới có ý nghĩa.
