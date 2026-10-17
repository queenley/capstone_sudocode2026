# Đánh giá AI agent

Thư mục này **chấm điểm AI tư vấn** (`apps/ai-agent-service`) bằng các kịch bản hội thoại có sẵn đáp án.

Mỗi kịch bản được chạy **hai lần**:

- **full**: AI được nhớ khách từ cuộc gọi trước;
- **baseline**: AI không có trí nhớ.

So hai kết quả cho biết trí nhớ giúp được bao nhiêu. Điểm được chấm bằng chính code chấm của BTC (`reference_eval.py`).

Logic của AI không bị sửa để chấm: thư mục `agent/` chỉ khởi động AI thật và nối nó với bộ chấm. Chạy được trên Windows và Linux.

---

## 1. Chuẩn bị (làm một lần)

1. **Bật database**: `docker compose up -d postgres` (từ thư mục gốc repo).
2. **Key AI**: file `.env` ở thư mục gốc có `OPENAI_API_KEY` (hoặc `GEMINI_API_KEY`).
3. **Cài thư viện** (Python 3.12) vào môi trường của AI agent:

   ```powershell
   py -3.12 -m venv apps/ai-agent-service/.venv          # bỏ qua nếu đã có
   apps/ai-agent-service/.venv/Scripts/python -m pip install -r scripts/evaluation/requirements.txt
   ```

   [`requirements.txt`](requirements.txt) gồm thư viện của AI agent và của bộ chấm. AI luôn chạy bằng Python trong `apps/ai-agent-service/.venv` (đổi bằng biến `AGENT_PYTHON`), kể cả khi bạn gõ lệnh bằng Python khác.

Mọi lệnh dưới đây chạy **từ thư mục gốc repo**. Cho gọn, đặt trước:

```powershell
$PY = "apps/ai-agent-service/.venv/Scripts/python"
```

---

## 2. Chạy đánh giá trong 3 bước

**Bước 1. Chuyển dữ liệu từ `scripts/create_data` sang dạng bộ chấm đọc được** (chỉ chạy một lần):

```powershell
& $PY scripts/evaluation/normalize_create_data.py
```

Kết quả: 101/150 kịch bản dùng được, lưu ở `datasets/create-data-diagnostic-v1/`. 49 kịch bản bị loại vì cần "lịch sử cuộc gọi cũ" (`seed_history`) mà AI chưa nạp được. Lý do từng kịch bản ghi trong `conversion-report.json`.

**Bước 2. Kiểm tra trước, không tốn tiền gọi AI:**

```powershell
& $PY scripts/evaluation/run_eval.py prepare --dataset-id create-data-diagnostic-v1 --level M2 --limit 5
```

Thấy `"allowed": true` là đầu vào hợp lệ.

**Bước 3. Chạy thật và chấm điểm:**

```powershell
& $PY scripts/evaluation/run_eval.py evaluate --dataset-id create-data-diagnostic-v1 --level M2 --limit 5
```

- `--level M2` hoặc `M1`: chỉ chạy một cấp độ. **Bỏ `--level`** thì chạy cả hai, mỗi cấp độ thành một lần chạy riêng (thư mục `<tên>-M1` và `<tên>-M2`), vì một lần chạy chỉ chứa được một cấp độ.
- `--limit 5`: chạy 5 kịch bản đầu (của mỗi cấp độ). **Nên bắt đầu nhỏ**, vì mỗi lượt chat gọi AI nhiều lần, nhân 2 cấu hình. Chạy toàn bộ 101 kịch bản là khoảng 1.700 lượt AI cộng 1.700 lượt chấm, mất nhiều giờ và tốn phí API đáng kể.
- `--only SCN-GEN-0003`: chạy đúng một kịch bản (lặp lại để chọn nhiều kịch bản).
- Trong lúc chạy, màn hình in tiến độ: bước đang làm (1/4 → 4/4), từng lượt chat (khách nói gì, AI trả lời gì, mất bao lâu, tốn bao nhiêu tiền, tổng tiền đến lúc đó) và thời gian ước tính. Mỗi kịch bản mất khoảng 1 phút để khởi động AI. Đặt `$env:EVAL_QUIET="1"` để tắt các dòng này.
- Bước chấm (extract) chạy **song song 6 lượt một lúc**, nhanh hơn khoảng 2 lần. Đổi bằng `$env:EVAL_EXTRACT_WORKERS="4"` (đặt `1` để chạy tuần tự). Không nên đặt quá cao vì OpenAI giới hạn số request mỗi phút.
- Bỏ `--dataset-id`: chạy 5 kịch bản mẫu có sẵn của nhóm.

---

## 3. Đọc kết quả

Mỗi lần chạy tạo một thư mục `scripts/evaluation/runs/<ngày-giờ>/`. Bảng điểm in ra cuối lệnh và lưu ở `scored/scorer.stdout.txt`:

```
Chỉ số                                Baseline      Hệ thống
Repeat-Question Rate (%)                  None           0.0
Context Carryover Rate (%)                 0.0           0.0
Task Success Rate (%)                      0.0         100.0
...
```

| Chỉ số | Nghĩa | Tốt khi |
|---|---|---|
| **TSR**, Task Success Rate | Tỉ lệ kịch bản AI làm đúng việc (gọi đúng tool, nói đúng ý) | cao |
| **CCR**, Context Carryover Rate | AI có dùng lại thông tin khách đã nói ở cuộc trước không | cao |
| **RQR**, Repeat-Question Rate | AI có hỏi lại điều khách đã nói không | thấp |
| **HR**, Hallucination Rate | AI có bịa giá, khuyến mãi, tồn kho không | thấp |
| Latency | Thời gian AI trả lời (p50, p95) | thấp |

Các file khác trong thư mục run:

| File | Xem để làm gì |
|---|---|
| `case-trace.json` | Đọc lại từng hội thoại: khách nói gì, AI trả lời gì, gọi tool nào |
| `execution-report.json` | Tóm tắt các giai đoạn, lỗi nếu có |
| `scored/official-report.json` | Điểm chi tiết theo code chấm của BTC |
| `evidence/validation.json` | Những gì còn thiếu bằng chứng |

**Mã thoát của lệnh `evaluate`:** `0` = đạt hết · `1` = chạy xong nhưng AI trượt một số kiểm tra (kết quả bình thường) · `2` = thiếu bằng chứng để kết luận · `3` = lỗi khi chạy.

Thư mục `runs/` có thể chứa dữ liệu khách nên **không đưa lên Git**.

---

## 4. Theo dõi chi phí trên MLflow

Mỗi lần `evaluate` chạy xong, số token và **số tiền (USD)** được tự động ghi lên MLflow, kèm điểm TSR/CCR/RQR/HR. Chỉ ghi con số, không ghi nội dung hội thoại hay dữ liệu khách.

1. Bật MLflow (một lần): `docker compose --profile tracking up -d mlflow`
2. Mở **http://localhost:5500**, chọn experiment **telesales-evaluation**.

Mỗi lần chạy là một dòng, với các cột chính:

| Metric | Nghĩa |
|---|---|
| `total_cost_usd` | Tổng tiền của lần chạy (AI + chấm) |
| `full_cost_usd`, `baseline_cost_usd` | Tiền của AI ở từng cấu hình |
| `extractor_cost_usd` | Tiền của model chấm (đọc câu trả lời) |
| `cost_per_turn_usd` | Tiền trung bình mỗi lượt chat |
| `*_input_tokens`, `*_output_tokens` | Số token |
| `full_tsr`, `baseline_tsr`, ... | Điểm, để so chi phí với chất lượng |

File `spend_by_scenario.json` (tab Artifacts) chia chi phí theo từng kịch bản.

- **Giá** lấy từ `apps/ai-agent-service/config/models.yaml` (`input_token_price_per_million`, `output_token_price_per_million` của từng provider). Hiện đã đặt giá OpenAI `gpt-4.1-mini`; Gemini chưa có giá nên chỉ ghi token (`agent_priced = 0`). Đổi model thì cập nhật giá ở đó.
- **Ghi lại lần chạy cũ** (hoặc khi MLflow chưa bật lúc chạy): `& $PY scripts/evaluation/run_eval.py mlflow-log --run scripts/evaluation/runs/<tên>`. Mỗi lần chạy chỉ được ghi một lần; thêm `--force` để ghi lại.
- Địa chỉ MLflow lấy từ `MLFLOW_TRACKING_URI` trong `.env`; `http://mlflow:5000` (tên trong Docker) được tự đổi thành `http://127.0.0.1:5500` khi chạy từ máy bạn.

---

## 5. Các lệnh khác

| Lệnh | Làm gì | Gọi AI? |
|---|---|---|
| `run_eval.py history` | Liệt kê mọi lần chạy cũ và điểm của chúng | Không |
| `run_eval.py data-check --set create-data-diagnostic-v1` | Kiểm tra bộ dữ liệu có hợp lệ không | Không |
| `run_eval.py rag-recall --out scripts/evaluation/runs/rag-1` | Đo khả năng tìm đúng đoạn chính sách (Recall@3/@5 trên 60 câu BTC) | Không |
| `python -m scripts.evaluation.evaluate` | Bản đo Recall nhanh, cũ hơn, không cần database | Không |

Đổi model:

- `--advisor openai:gpt-4.1-mini`: model AI tư vấn (mặc định lấy theo `apps/ai-agent-service/config/models.yaml`).
- `--extractor openai:gpt-4.1-mini`: model đọc câu trả lời để chấm (mặc định OpenAI khi có key).

---

## 6. Gặp lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `Postgres is not reachable` hoặc treo rất lâu lúc khởi động | Bật `docker compose up -d postgres`. Dùng `127.0.0.1`, không dùng `localhost`, trong URL database (trên Windows `localhost` làm mỗi server chậm vài phút) |
| `No API key for provider ...` | Thêm key vào `.env` ở thư mục gốc |
| Gemini báo 402 `RESOURCE_EXHAUSTED` | Hết tiền tài khoản Google; dùng `--advisor openai:gpt-4.1-mini` |
| `The selection mixes levels` | Thêm `--level M1` hoặc `--level M2` |
| `Choose a new run directory` | `--out` đã tồn tại; chọn tên khác |
| Nhiều lượt chấm báo `OpenAIConnectionError` | Đã xử lý tự động trên Windows (dùng bộ chứng chỉ `certifi`). Nếu vẫn gặp, giảm `EVAL_EXTRACT_WORKERS` |
| `MLflow not reachable` | Bật `docker compose --profile tracking up -d mlflow`, rồi ghi lại bằng `run_eval.py mlflow-log --run ...` |
| `The agent's code changed after preparation` | Đã sửa code AI sau bước `prepare`; chạy lại `evaluate` từ đầu |

---

## 7. Cấu trúc thư mục

```text
run_eval.py               Điểm vào của mọi lệnh
product.py                Chuẩn bị đầu vào, chạy, thu bằng chứng, chấm
product_adapter.py        Cầu nối giữa bộ chấm và AI (chạy AI ở tiến trình riêng)
agent/                    Khởi động AI thật của repo cho bộ chấm
  launch.py               Đọc .env, chọn database, chọn key
  bridge.py               Nhận từng lượt chat từ bộ chấm, đưa vào AI
  runner.py               Lắp ráp AI giống như khi chạy thật
  extract_command.py      Gọi model để trích câu hỏi/khẳng định trong câu trả lời
  spend.py                Tính tiền từ số token và giá trong models.yaml
  mlflow_log.py           Ghi chi phí và điểm của một lần chạy lên MLflow
normalize_create_data.py  Chuyển dữ liệu create_data thành bộ dữ liệu chấm
datasets/                 Các bộ kịch bản (registry.json là danh sách)
eval_harness/             Code chấm
evaluation-contracts/     Định dạng và dữ liệu gốc của BTC (không sửa)
tests/                    Test không gọi AI
docs/                     Quy tắc gán nhãn, lỗi đã gặp, các luồng cải tiến
runs/                     Kết quả các lần chạy (không lên Git)
```

---

## 8. Cách hoạt động (cho người muốn hiểu sâu)

1. `prepare` sao chép và "khóa" (hash) mọi đầu vào: kịch bản, nhãn, code AI. Code AI bị sửa giữa chừng thì lần chạy bị từ chối, để kết quả luôn ứng với đúng một phiên bản code.
2. `evaluate` mở AI trong một tiến trình riêng cho từng kịch bản và từng cấu hình. Các tool nghiệp vụ (giá, tồn kho, đơn hàng) **không** chạy trong AI mà được trả lời bởi bản mock của BTC nằm trong bộ chấm, để biết chính xác AI đã gọi gì và làm thay đổi gì.
3. Trí nhớ và chính sách vẫn chạy qua server MCP của AI, trên schema database riêng `agent_eval`, được xóa trước mỗi kịch bản. Dữ liệu thật trong schema `agent` không bị đụng tới.
4. Sau khi chạy, một model "extractor" đọc từng câu trả lời để tách câu hỏi, khẳng định (giá, tồn kho, ...) và thông tin được dùng lại; code chấm của BTC tính điểm từ đó.
5. Không thử lại khi lỗi: mọi lần gọi AI hay tool thất bại đều được ghi nhận như nó xảy ra.

Biến môi trường có thể đổi: `EVAL_DB_SCHEMA` (mặc định `agent_eval`, phải kết thúc bằng `_eval`), `EVAL_DATABASE_URL`, `AGENT_PYTHON` (Python dùng để chạy AI).

---

## 9. Quy tắc khi sửa dữ liệu hoặc code chấm

- **Trước khi sửa code** trong thư mục này: đọc [lỗi đã gặp và guardrail](docs/CODING-INCIDENTS-AND-GUARDRAILS.md).
- **Trước khi thêm hoặc sửa kịch bản, đáp án, nhãn:** đọc [hướng dẫn duyệt ground truth](datasets/ground-truth-review/SKILL.md). Tóm tắt:
  - không sửa dữ liệu gốc, luôn tạo bản (revision) mới;
  - nhãn do máy sinh chỉ là `diagnostic`; muốn `approved` phải có người duyệt từng cuộc gọi;
  - không đổi điều kiện chấm sau khi đã xem điểm.
- Các bộ dữ liệu hiện có:
  - `output1-diagnostic-v2`: 5 kịch bản mẫu, mặc định ([quyết định duyệt](datasets/output1-btc-diagnostic-v2/review-decisions.md));
  - `create-data-diagnostic-v1`: 101 kịch bản từ `create_data`, nhãn chờ duyệt.

Chạy test của bộ chấm:

```powershell
Set-Location scripts/evaluation
& ../../apps/ai-agent-service/.venv/Scripts/python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

---

## 10. Tính năng nâng cao

Đã có trong bộ chấm nhưng chưa nối hết vào AI:

- **Knowledge Gap:** mỗi lần chấm tạo `scored/knowledge-gap-candidates.json`, danh sách các lượt AI phải chuyển người hoặc nói "chưa có thông tin". Người duyệt chọn câu nào nên thành FAQ (`gap-publish`), rồi kiểm tra lại (`gap-check`). Hiện AI **chưa** tự dùng FAQ mới. Chi tiết: [luồng Knowledge Gap](docs/flows/KNOWLEDGE-GAP-LOOP.md).
- **Reflection / playbook:** từ đánh giá cuộc gọi rút ra bài học cho AI. Xem [luồng Reflection](docs/flows/REFLECTION-FLOW.md).
- **Exemplar bank:** đang tạm hoãn, xem [thiết kế](docs/flows/EXEMPLAR-BANK-FLOW.md).
- Báo cáo phụ trong mỗi run: `scored/claim-adjudication.json` (khẳng định khác đáp án nhưng có thể tương đương) và `scored/tool-business-error-review.json` (tool lỗi và AI có tự sửa không). Hai file này không thay đổi điểm chính thức.

Đề bài gốc: [requirements/project-brief.pdf](requirements/project-brief.pdf).
