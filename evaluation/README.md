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
| [`data-generation/`](data-generation/README.md) | Sinh kịch bản theo định dạng BTC (có venv, test, prompt riêng) |
| [`rag_offline.py`](rag_offline.py) | Recall@k của kho tri thức, không cần model hay database (`make eval`) |
| `runs/` | Bằng chứng mỗi lần chạy, cache extractor và sổ ngân sách. **Không lên Git** (có thể chứa dữ liệu khách) |
| [`../docs/evaluation/`](../docs/evaluation/README.md) | Luồng vào bộ chấm, bản đồ hệ thống |

## Chạy

Từ gốc repo, với Python của agent (`apps/ai-agent-service/.venv`) và `docker compose up -d postgres`:

```bash
# Bắt buộc cho agent/extractor: dùng ledger hiện có, không tạo lại để vượt cap
export EVAL_BUDGET_DB=evaluation/runs/20261024-work/budget.sqlite

# Chạy kịch bản qua agent (tốn phí model). Không --config: cả full và baseline_no_memory, rồi in bảng BTC
python run_eval.py --scenarios evaluation/datasets/create-data-diagnostic-v4/scenarios --only SCN-GEN-0051 --out evaluation/runs/<tên>

# Kiểm đường ống mà không gọi extractor (agent vẫn gọi model; RQR và HR không đo)
python run_eval.py --scenarios <thư mục> --only <ID> --no-extract

# Gắn nhãn lại một run cũ bằng extractor hiện tại, KHÔNG chạy lại agent (chỉ tốn lượt gọi extractor)
python run_eval.py --relabel evaluation/runs/<ngày>-work/<run> --out evaluation/runs/<tên>-relabel

# Recall@k của kho tri thức, miễn phí
python evaluation/rag_offline.py

# ASR local: thử một clip của gói đã có, không provider/extractor
python run_eval.py --asr-package /absolute/path/package --asr-unit segments --only CLIP_ID --asr-transcribe --asr-model zipformer-30m --out evaluation/runs/asr-smoke-new
```

Giới hạn chi tiêu: `EVAL_BUDGET_DB=<đường dẫn sổ SQLite>` là bắt buộc cho agent/extractor, kể cả `--no-extract` và `--relabel`; CLI chặn ledger thiếu/hỏng/hết cap trước DB/model. Sổ hiện dùng nằm ở `evaluation/runs/20261024-work/budget.sqlite`. Không tạo lại sổ để chạy tiếp một ngân sách đã hết. SDK retry phải bằng 0 để không bỏ sót usage của request tính phí. Budget hiện hỗ trợ `openai:gpt-4.1-mini` (xem `llm/evaluation_budget.py`). ASR local/hypothesis replay không cần ledger. `EVAL_RUNS_DIR` đổi chỗ ghi `runs/`.

Mã thoát: `0` đủ nhãn và đã chấm · `1` có lượt lỗi hoặc chưa gắn nhãn (không in bảng, trace vẫn được giữ) · `2` đầu vào hoặc cấu hình sai.

Một run ghi: `full.jsonl`, `baseline.jsonl` (trace theo schema BTC), `diagnostics.jsonl` (từng lượt: lane, guard, và `extraction_items` kèm quote để kiểm tay), `report.json` + `table.txt` (BTC), `usage.json`, `manifest.json`, `errors.jsonl`, `rag/`.

Dùng `--out` mới hoặc thư mục rỗng; CLI không ghi đè bằng chứng đã có. Run lỗi không xuất bảng: xem `scenario-errors.jsonl`, `evaluation-error.log` hoặc `scoring-error.txt` tùy bước lỗi. Manifest chỉ `COMPLETE` sau khi hoàn tất output; chi tiết kiểm thử pipeline và Windows ở [chẩn đoán seed/đường chấm](../docs/evaluation/seed-timeout-windows.md).

Scenario được kiểm trước khi gọi model và snapshot từ nội dung đã nạp, cả `--config`. Database có advisory lock cho toàn bộ run, chặn hai runner reset lẫn nhau; output được giữ chỗ độc quyền. Trước extractor/scorer phải đủ đúng từng scenario/call/turn, đúng config và lời khách, không trùng hoặc trộn run. Trace được lưu sau mỗi scenario để giữ replies nếu bước sau lỗi. Relabel chỉ sửa lỗi extractor trên replies đầy đủ; lỗi seed, graph hoặc after-call vẫn chặn chấm.

Extractor hiện là `product-extractor-v8`: thêm kiểm tra schema cache và ghi file tạm riêng khi chạy đồng thời. Prompt/phép chiếu nhãn giữ nguyên từ v7 nhưng instrument hash đổi; muốn so với v7 phải relabel cùng replies. Cache JSON có thể mất hit khi nhiều process ghi snapshot, làm tăng số cache miss trong cap; không làm file cache bị ghi dở.

## Quy tắc

ASR dùng `--asr` cho ground_truth/hypotheses BTC-compatible hoặc `--asr-package` cho manifest audio/reference. `--asr-unit montage` chia WAV theo waveform, `segments` dùng ranh giới được cung cấp và phải báo oracle segmentation. `--asr-entity-review` nhận nhãn canonical có provenance; nhãn chưa duyệt luôn diagnostic. Chi tiết phép đo, version và nguồn VoiceGo: [ASR local](../docs/evaluation/asr-local.md). Không chạy script scorer khác trong gói người dùng thay cho lệnh gốc.

1. **Theo quyết định hiện tại: dùng toàn bộ test/harness/scorer trên main**, mốc đồng bộ `41eda490bc47577018541c7778c0e8443ed8e6c8`. Giữ `reference_eval.py` tại mốc này, không khôi phục ZIP BTC và không sửa tiếp công thức. Pack được `test_btc_pack.py` ghim hash; manifest mỗi run ghi `reference_eval_sha256`. Khi báo số phải nêu đây là bộ chấm của main, không mặc định đồng nhất với ZIP BTC gốc.
2. **Đo công bằng.** `full` và `baseline_no_memory` cùng kịch bản, model, prompt, công cụ, tri thức; chỉ khác bộ nhớ.
3. **Đổi extractor là đổi dụng cụ đo.** Số do extractor khác nhau không so trực tiếp được; ghi `extractor_version` khi so.
4. **Không dùng đáp án của tập kiểm hay holdout để viết FAQ, playbook hay ví dụ.** Ví dụ trong prompt extractor là dữ liệu bịa.
5. **Nhãn chưa có người duyệt là diagnostic.** Đổi nhãn thì tạo revision mới (xem [`datasets/ground-truth-review`](datasets/ground-truth-review/SKILL.md)), không ghi đè revision đã dùng, và báo thay đổi nhãn tách khỏi thay đổi của agent.
6. **Thiếu bằng chứng không được điền 0 hay PASS.** Dữ liệu thiếu thì báo thiếu.
7. **Không commit** hội thoại thô, key, dữ liệu khách, hay nội dung `runs/`.
8. **Không dùng `evaluate` để thử cấu hình.** Mỗi lần chạy có gọi model là tốn phí; thử trên một kịch bản trước, và gắn nhãn lại bằng `--relabel` khi chỉ đổi extractor.
