# Bản đồ hệ thống để làm tiếp evaluation

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

## Một lệnh đánh giá

`run_eval.py` ở gốc repo dùng MCP của sản phẩm cho công cụ nghiệp vụ, database có tên kết thúc `_eval` (tạo ở lần chạy đầu, xóa trạng thái giữa các kịch bản). Luồng từng bước và bảng "chỉ số nào đọc trường nào": [scoring-flow.md](scoring-flow.md). Cửa vào, lệnh và quy tắc: [`evaluation/README.md`](../../evaluation/README.md).

## Lệnh offline đã kiểm

Từ gốc repo, Python 3.12 trong `apps/ai-agent-service/.venv`:

```sh
apps/ai-agent-service/.venv/bin/python -m pytest -q                      # toàn bộ test, không model
apps/ai-agent-service/.venv/bin/python evaluation/rag_offline.py         # Recall@3/@5, không model, không database
(cd evaluation/data-generation && ../../apps/ai-agent-service/.venv/bin/python -m pytest -q)
```

## Giới hạn phải nhớ

- Scorer BTC và gói dữ liệu BTC là bất biến (`tests/agent/test_btc_pack.py`).
- Lỗi extractor làm mất cả lượt khỏi trace chấm: lượt đó "unlabelled" và bảng không được in. Đọc `diagnostics.jsonl` (`extraction_items`) trước khi kết luận agent bỏ sót.
- `must_say_any` chỉ khớp chuỗi; thiếu GT hay usage không được điền 0 hoặc PASS.
- Evaluation bằng text không thay thế kiểm UI, auth, ASR, TTS; nó không chứng minh voice hoạt động.
- Cùng sản phẩm/giá/số lượng/thanh toán/địa chỉ trong cùng cuộc dùng chung khóa idempotency của lệnh tạo đơn; số lượng khác hoặc cuộc khác là thao tác khác.
- `EVAL_BUDGET_DB` (tùy chọn) giữ một sổ SQLite dùng chung giữa các tiến trình: giữ mức dự phòng tối đa trước mỗi request, chỉ hoàn phần chênh khi có usage. Không tạo lại sổ để chạy tiếp một ngân sách đã hết.
- Chỉ chạy một lần đánh giá mỗi lúc trên cùng một database `_eval`, vì mỗi kịch bản xóa trạng thái.
