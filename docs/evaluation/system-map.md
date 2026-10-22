# Bản đồ hệ thống để tiếp tục evaluation

Đối chiếu main `1e738ba1` ngày 22/10/2026. Xem `2026-10-22-worklog.md` cho bằng chứng và kết quả lần làm việc này.

## Đường chạy sản phẩm

Web → API gateway → AI conversation routes → `runtime/harness` → hot graph:
perceive → load_context → route → advisor → guard → respond → persist.
Sales/identity/commerce quản lý cuộc trò chuyện, xác thực và nghiệp vụ nền tảng.
Agent dùng MCP catalog, CRM, order, memory và knowledge; business tools bọc mock BTC.
Không suy rằng unit test API với ScriptedAgent đã kiểm chất lượng model thật.

- Intake chuẩn hóa text/teencode/số nói, tokenize PII vào vault.
- Identity phân biệt UNKNOWN/PROBABLE/AMBIGUOUS/VERIFIED; một số điện thoại có thể là của nhiều người.
- Memory được ghi ở after_call; call sau retrieve → refresh qua tool → dựng CallBrief. Baseline tắt đọc memory trước đó, không tắt ghi after_call.
- Knowledge tìm mỗi lượt bằng BM25 + multilingual-e5-small ONNX, RRF và ngưỡng abstain. Model thiếu có thể fallback keyword-only; phải ghi đúng mode khi báo điểm.
- Advisor dùng ReAct với tools theo lane. Action guard kiểm trước tool, hard guard kiểm lời trả lời; Jev kiểm mềm khi có key và quyền gọi.
- Streaming kiểm từng câu trước khi gửi. Handoff chuyển sang copilot; write tools không tự retry.
- `models.yaml` giữ routing/generation/pricing; secret trong `.env`, không đưa vào báo cáo.

## Hai runner, hai loại bằng chứng

| Runner | Business tools | Đầu ra |
|---|---|---|
| Root `run_eval.py` | MCP của sản phẩm | full/baseline JSONL, diagnostics, usage, manifest, report và RAG |
| `scripts/evaluation/run_eval.py` | Mock/audit do harness quản lý; memory/knowledge vẫn MCP | prepare → raw → evidence → scored; kiểm provenance, coverage và nhãn bổ sung |

Không gộp delta giữa hai runner. Root runner dùng database có tên kết thúc `_eval`; harness dùng schema kết thúc `_eval`. Chỉ chạy từng runner một trên cùng môi trường evaluation vì reset làm sạch trạng thái.

## Lệnh offline đã xác minh

Từ gốc repo, Python 3.12 trong `apps/ai-agent-service/.venv`:

```sh
apps/ai-agent-service/.venv/bin/python -m pytest -q
(cd scripts/evaluation && ../../apps/ai-agent-service/.venv/bin/python -X utf8 -m unittest discover -s tests -p 'test_*.py')
PYTHONPATH=apps/ai-agent-service/src:packages/backend-common apps/ai-agent-service/.venv/bin/python -m scripts.evaluation.evaluate
apps/ai-agent-service/.venv/bin/python scripts/evaluation/run_eval.py data-check --set create-data-diagnostic-v1
```

`data-check` có thể không có schema issue nhưng vẫn exit 2 vì dataset diagnostic chưa được người duyệt. `prepare` cho diagnostic là gate đầu vào, không chứng nhận GT chính thức hay chất lượng agent.

## Giới hạn phải nhớ

- Scorer BTC, policy/catalog nguồn và revision/run đã dùng là bất biến.
- Lỗi extractor có thể làm mất cả lượt khỏi trace chấm: đọc raw tool audit trước khi kết luận agent không gọi tool.
- `must_say_any` chỉ khớp chuỗi; thiếu GT/usage không được điền 0 hoặc PASS.
- Root runner không thay thế kiểm UI/auth/ASR/TTS; evaluation text không chứng minh voice hoạt động.
- Cùng sản phẩm/giá/số lượng/thanh toán/địa chỉ trong cùng call dùng chung order idempotency key; số lượng khác hoặc call khác là thao tác khác.
- Opt-in `EVAL_BUDGET_DB` giữ sổ SQLite dùng chung giữa tiến trình: giữ mức dự phòng tối đa trước request, chỉ hoàn phần chênh khi có usage. Không tạo lại sổ để chạy tiếp một ngân sách đã hết.

## Chạy tiếp có kiểm soát

1. Đọc RUN-LEDGER.md, chọn cohort mới không có ID lịch sử/development/holdout đã dùng, lưu snapshot/hash và gate prepare theo từng level.
2. Kiểm database evaluation, embedding và key (chỉ kiểm presence, không in giá trị). Python và các dependency đã ở venv; Docker postgres đang chạy.
3. Đối soát sổ chi phí hiện tại trước. Snapshot còn 1,4165 USD sau tổng usage + dự phòng. Burst extraction đã có thể chặn tạm request do reservation đồng thời; revision sau chạy tuần tự khi bật cap. Không tạo lại ledger để lách trần hoặc giải phóng usage thiếu evidence. Lượt sửa từ log chỉ chạy offline.
4. Khi ngân sách hợp lệ, chạy root runner với thư mục output chưa tồn tại, đường dẫn cohort mới đã qua gate và ledger đã được khởi tạo đúng ngân sách được phép:

```sh
AI_GATEWAY_API_KEY='' EVAL_BUDGET_DB=/absolute/path/to/authorized-budget.sqlite \
  apps/ai-agent-service/.venv/bin/python -u run_eval.py \
  --scenarios /absolute/path/to/new-locked-cohort \
  --provider openai --model gpt-4.1-mini \
  --out /absolute/path/to/new-run-directory
```

Không dùng lại ví dụ cohort hôm nay như case mới. Sau mỗi lần bắt đầu/kết thúc, cập nhật ledger kể cả execution xong nhưng scoring lỗi. Cùng cohort ở vòng retest phải giữ nguyên runner/nhãn/instrument; đổi instrument thì báo riêng.

Revision sau log 22/10: ORDER_SERVICE có thể được chọn cho khách VERIFIED đang tra tình trạng đơn dù memory chưa có mã; CRM lookup dùng identity của caller đã xác minh. Model call cuối dành trả lời không tools. Lỗi model giữ partial tool results ở cả streaming/copilot và không tự retry write. Native extractor retry truncation đúng một lần, ghi lại lỗi đã phục hồi; harness command giữ contract một attempt nhưng xuất known error usage.


## Revision kiến trúc sau log ngày 22/10

- Business memory chiếu từ frame cùng sản phẩm sang slot BTC; `quoted_sku` ràng buộc giá lịch sử, `order_ids` giữ giỏ nhiều đơn. Không có DB migration; list hợp nhất dưới transaction/customer lock.
- Key lookup có provenance customer_ids, chỉ dùng ledger identity confirmed. Extraction model không cấp quyền ghi vào identity chưa xác nhận; key được nhắc không tự liên kết.
- Model/checkpoint nhận token từ tool và brief, không chỉ từ lời khách; runtime và hai runner phục hồi JSON ở output bằng helper chung. Private order/CRM reads bị giới hạn theo identity và scope đơn.
- Citation trễ được giữ như metadata, không thành câu rỗng. Citation → slot dùng chung; runtime freeze provenance theo turn, không suy credit từ substring.
- Context bắt buộc không bị cắt bởi target mềm 3.000 token; tool JSON không bị cắt giữa payload khi regenerate. Chưa đo chi phí/latency mới.
- Xem [bằng chứng và giới hạn](2026-10-22-architecture-fixes.md). Trạng thái metrics sau sửa vẫn INCOMPLETE; không có model run trả phí mới.
