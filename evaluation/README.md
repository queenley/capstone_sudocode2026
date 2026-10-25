# Evaluation

Đánh giá chất lượng AI agent, tách khỏi `scripts/` (vận hành platform). Hai project độc lập, mỗi cái có README, requirements và test riêng:

| Thư mục | Việc | Lệnh chính |
|---|---|---|
| [`harness/`](harness/README.md) | Harness chấm điểm agent end-to-end (full vs baseline, scorer BTC), dataset đã duyệt, RAG Recall, ASR, lịch sử run (`runs/`, không commit) | `apps/ai-agent-service/.venv/Scripts/python evaluation/harness/run_eval.py evaluate --advisor openai:gpt-4.1-mini` |
| [`data-generation/`](data-generation/README.md) | Sinh kịch bản test theo format BTC, ground truth, audio, bộ ASR; có venv riêng | xem README |

Luồng dữ liệu: `data-generation/output/` → `harness/normalize_create_data.py` → `harness/datasets/<revision>/` → `harness/run_eval.py`.

Recall@k nhanh của kho tri thức, không cần model: `python evaluation/harness/evaluate.py` (hoặc `make eval`).

Lệnh dạng BTC (`--scenarios`, `--config`, `--out`) là `run_eval.py` ở root repo, không nằm ở đây. Báo cáo, ledger các run và kết quả: [`docs/evaluation/`](../docs/evaluation/README.md).

Trước đây hai thư mục này là `scripts/evaluation/` và `scripts/create_data/`; bằng chứng run, dataset và tài liệu có ngày cũ vẫn ghi đường dẫn cũ.
