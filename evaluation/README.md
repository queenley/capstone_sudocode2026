# Evaluation

Đo chất lượng AI agent theo cách BTC chấm. Có **một đường chạy duy nhất**: `run_eval.py` ở gốc repo, cũng là lệnh giám khảo sẽ gọi.

| Đường dẫn | Là gì |
|---|---|
| [`run_eval.py`](../run_eval.py) (gốc repo) | Lệnh duy nhất: chạy kịch bản qua agent thật, gắn nhãn câu hỏi/claim bằng extractor, rồi chấm bằng `reference_eval.py` của BTC |
| `apps/ai-agent-service/src/ai_agent_service/pipeline/eval/` | Mã của lệnh trên: `cli.py`, `runner.py`, `trace.py`, `scenarios.py`, `report.py`, `relabel.py`, `rag.py` |
| `apps/ai-agent-service/src/ai_agent_service/components/evaluation/scorers.py` | Extractor (nhãn `questions`, `claims`, `facts_used`) |
| [`config/prompts/evaluation/extractor.txt`](../config/prompts/evaluation/extractor.txt) | Prompt của extractor, nạp nguyên văn |
| `apps/ai-agent-service/data/btc/` | Gói dữ liệu của BTC, bản duy nhất trong repo; `tests/agent/test_btc_pack.py` ghim hash từng file |
| [`datasets/`](datasets/README.md) | Kịch bản đã gán nhãn (v4, 150 kịch bản) và quy tắc duyệt nhãn |
| [`data-generation/`](data-generation/README.md) | Sinh kịch bản theo định dạng BTC (có venv, test, prompt riêng); ghi vào `data/seed-<tên>/` ở gốc repo |
| [`../contracts/scenario/scenario-keys.yaml`](../contracts/scenario/scenario-keys.yaml) | Mọi khóa được phép của một kịch bản (kiểu, nguồn BTC/nhóm, ý nghĩa); bộ sinh từ chối khóa lạ |
| [`rag_offline.py`](rag_offline.py) | Recall@k của kho tri thức, không cần model hay database (`make eval`) |
| `runs/` | Bằng chứng mỗi lần chạy, cache extractor và sổ ngân sách. **Không lên Git** (có thể chứa dữ liệu khách) |
| [`../docs/evaluation/`](../docs/evaluation/README.md) | Luồng vào bộ chấm, bản đồ hệ thống |

## Chạy

Từ gốc repo, với Python của agent (`apps/ai-agent-service/.venv`) và `docker compose up -d postgres`:

```bash
# Chạy kịch bản qua agent (tốn phí model). Không --config: cả full và baseline_no_memory, rồi in bảng BTC
python run_eval.py --scenarios evaluation/datasets/create-data-diagnostic-v4/scenarios --only SCN-GEN-0051 --out evaluation/runs/<tên>

# Kiểm đường ống mà không gọi extractor (agent vẫn gọi model; RQR và HR không đo)
python run_eval.py --scenarios <thư mục> --only <ID> --no-extract

# Gắn nhãn lại một run cũ bằng extractor hiện tại, KHÔNG chạy lại agent (chỉ tốn lượt gọi extractor)
python run_eval.py --relabel evaluation/runs/<ngày>-work/<run> --out evaluation/runs/<tên>-relabel

# Recall@k của kho tri thức, miễn phí
python evaluation/rag_offline.py
```

Giới hạn chi tiêu: `EVAL_BUDGET_DB=<đường dẫn sổ SQLite>` đặt trần USD cho mọi request có phí (xem `llm/evaluation_budget.py`). Sổ hiện dùng nằm ở `evaluation/runs/20261024-work/budget.sqlite`. Không tạo lại sổ để chạy tiếp một ngân sách đã hết. `EVAL_RUNS_DIR` đổi chỗ ghi `runs/`.

Mã thoát: `0` đủ nhãn và đã chấm · `1` có lượt lỗi hoặc chưa gắn nhãn (không in bảng, trace vẫn được giữ) · `2` đầu vào hoặc cấu hình sai.

Một run ghi: `full.jsonl`, `baseline.jsonl` (trace theo schema BTC), `diagnostics.jsonl` (từng lượt: lane, guard, và `extraction_items` kèm quote để kiểm tay), `report.json` + `table.txt` (BTC), `team_checks.json` (kiểm tra riêng của nhóm, `success_if.say_at_most`: số lượt agent khớp một mẫu không quá mức cho phép, ví dụ AIR-2ND-50 nói một lần; in dưới bảng BTC, là số chẩn đoán, không phải số chính thức), `rqr_a1.json` (RQR theo đúng lời văn A.1 của đề: câu xác nhận không bao giờ tính là thừa, kể cả lần thứ hai; `reference_eval` thì tính câu xác nhận lần 2+ là thừa theo giải đáp câu 11 của BTC, nên số chính thức là của nó; file ghi cả số câu xác nhận lặp và mức giảm so với baseline của hai cách tính), `usage.json`, `manifest.json`, `errors.jsonl`, `rag/` (Recall@k của 60 câu BTC, và `rag/scenario_recall.json`: chunk agent thật sự truy hồi trong mỗi cuộc so với `relevant_policy_ids` của cuộc đó; `recall` = cuộc có ≥1 mục đúng, `full_recall` = đủ mọi mục, `coverage` = tỉ lệ mục đúng trung bình; số chẩn đoán, chỉ có với kịch bản mang khóa này như `data/seed-dev`, bộ v4 thì không).

## Quy tắc

1. **Số chính thức chỉ là `reference_eval.py` của BTC**, chạy nguyên bản. Không viết lại công thức. Không sửa gói BTC; `test_btc_pack.py` sẽ báo nếu một byte đổi.
2. **Đo công bằng.** `full` và `baseline_no_memory` cùng kịch bản, model, prompt, công cụ, tri thức; chỉ khác bộ nhớ.
3. **Đổi extractor là đổi dụng cụ đo.** Số do extractor khác nhau không so trực tiếp được; ghi `extractor_version` khi so. Hiện là `product-extractor-v5` (câu đọc lại đơn là một câu xác nhận `order_summary`); số của v4 so bằng `--relabel`.
4. **Không dùng đáp án của tập kiểm hay holdout để viết FAQ, playbook hay ví dụ.** Ví dụ trong prompt extractor là dữ liệu bịa.
5. **Nhãn chưa có người duyệt là diagnostic.** Đổi nhãn thì tạo revision mới (xem [`datasets/ground-truth-review`](datasets/ground-truth-review/SKILL.md)), không ghi đè revision đã dùng, và báo thay đổi nhãn tách khỏi thay đổi của agent.
6. **Thiếu bằng chứng không được điền 0 hay PASS.** Dữ liệu thiếu thì báo thiếu.
7. **Không commit** hội thoại thô, key, dữ liệu khách, hay nội dung `runs/`.
8. **Không dùng `evaluate` để thử cấu hình.** Mỗi lần chạy có gọi model là tốn phí; thử trên một kịch bản trước, và gắn nhãn lại bằng `--relabel` khi chỉ đổi extractor.
