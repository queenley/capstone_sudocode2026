# Đánh giá agent trên bộ `seed-dev`

Bộ dữ liệu do [`evaluation/data-generation`](../../evaluation/data-generation/README.md) sinh, theo định dạng kịch bản của BTC. README này chỉ cách dùng nó để chấm agent. Con số chính thức luôn là `reference_eval.py` của BTC, chạy qua `run_eval.py` ở gốc repo (quy tắc trong [`evaluation/README.md`](../../evaluation/README.md)).

## Trong thư mục có gì

| Thư mục | Nội dung | Dùng để |
|---|---|---|
| `scenarios/` | 400 kịch bản (250 persona BTC `SCN-GEN-*`, 150 persona của nhóm `SCN-ADV-*`), 797 cuộc gọi | **đầu vào của `run_eval.py`** |
| `metadata/` | vùng, ngành, độ khó, tag (`date:<mốc ngày>`, `variant:…`, `hard_case`) của từng kịch bản; persona nằm trong file `scenarios/` | chọn tập con để chạy |
| `conversations/`, `trace_log/` | hội thoại mẫu của agent lý tưởng, trace của oracle (lời gọi tool thật trên mock BTC) | so sánh, kiểm nhãn; agent **không** đọc chúng |
| `call_brief/`, `handoff_brief/` | Call Brief và brief chuyển máy kỳ vọng | so với brief của agent |
| `rag/scenario_qa.json` | câu hỏi lấy từ lời khách, kèm mục chính sách liên quan (`relevant_policy_ids`) | Recall@k trên kịch bản |
| `audio/`, `asr_test/` | audio lượt khách (3 giờ, có `ground_truth.json`) và 24 hội thoại hai người | chấm ASR |
| `reports/` | kiểm tra nhãn, oracle, audio, chi phí sinh dữ liệu | đọc trước khi chạy |
| `review/needs_manual_review.csv` | các ca cần người duyệt | duyệt tay |

**Nhãn là chẩn đoán.** Chưa có `review/golden_manifest.json` (chưa ai duyệt tay), nên số đo trên bộ này là chẩn đoán, chưa phải bộ vàng (quy tắc 5).

## 0. Kiểm nhãn trước (miễn phí, không gọi model)

Agent lý tưởng (oracle) phải đạt CCR 100 · RQR 0 · TSR 100 · HR 0 và 0 vi phạm guardrail. Nếu không đạt thì nhãn sai, chạy agent cũng vô nghĩa.

```bash
cd evaluation/data-generation
python -m src.pipeline.build_ground_truth      # -> data/seed-dev/reports/a6_oracle.txt, oracle_report.json
python -m src.pipeline.validate_rules          # -> data/seed-dev/reports/validation.json (hội thoại mẫu)
cd ../..
```

`a6_oracle.txt` là bảng A.6 của BTC chấm trên oracle. Trong `validation.json`, những hội thoại `validator_pass: false` là các ca nhãn hoặc hội thoại mẫu còn lỗi; muốn sinh lại thì chạy `python -m src.pipeline.run_all --only-failed` trong `evaluation/data-generation`.

## 1. Chuẩn bị

Từ gốc repo, với Python của agent:

```bash
docker compose up -d postgres                          # run_eval dùng một database đánh giá riêng
apps/ai-agent-service/.venv/Scripts/python --version   # Windows; Linux/macOS: apps/ai-agent-service/.venv/bin/python
```

- Key của model agent và extractor nằm trong `.env` của agent (`config/models.yaml` chọn model).
- **Mọi lần chạy có gọi model đều tốn tiền.** Đặt sổ ngân sách trước khi chạy, và không xoá hay tạo lại sổ để vượt trần:

```bash
export EVAL_BUDGET_DB=evaluation/runs/20261024-work/budget.sqlite         # bash
$env:EVAL_BUDGET_DB = "evaluation/runs/20261024-work/budget.sqlite"       # PowerShell
```

(Máy chưa có `evaluation/runs/` thì lần chạy đầu sẽ tạo sổ mới ở đó.)

## 2. Chạy thử một kịch bản

```bash
python run_eval.py --scenarios data/seed-dev/scenarios --only SCN-GEN-0001 --out evaluation/runs/seed-dev-smoke
```

Không có `--config`: chạy cả `full` (có bộ nhớ) và `baseline_no_memory`, rồi in bảng BTC. Thêm `--only` nhiều lần để chạy vài kịch bản. `--no-extract` bỏ extractor (rẻ hơn, nhưng RQR và HR không đo được), chỉ để kiểm đường ống.

## 3. Chạy một tập con

`run_eval.py` nhận một thư mục, nên chép kịch bản cần chạy sang một thư mục riêng trong `evaluation/runs/` (không lên Git). Ví dụ lấy theo persona, theo tag hoặc theo mốc ngày:

```bash
python - <<'EOF'
import json, shutil
from pathlib import Path
seed, out = Path("data/seed-dev"), Path("evaluation/runs/subsets/hard-cases/scenarios")
out.mkdir(parents=True, exist_ok=True)
for meta in sorted((seed / "metadata").glob("*.json")):
    m = json.loads(meta.read_text(encoding="utf-8"))
    if "hard_case" in m["tags"]:                 # hoặc: m["region"] == "nam", m["category"].startswith("me-be"), "date:sunday" in m["tags"]
        shutil.copy(seed / "scenarios" / meta.name, out / meta.name)
print(len(list(out.glob("*.json"))), "scenarios ->", out)
EOF
python run_eval.py --scenarios evaluation/runs/subsets/hard-cases/scenarios --out evaluation/runs/seed-dev-hard-cases
```

Kịch bản sinh sau khi có mốc ngày mới có tag `date:<mốc>`: `promo_last_day`, `after_promo_end`, `before_promo_start`, `sale_day`, `out_of_stock`, `delivery_over_holiday`, `sunday`, `ordinary`.

## 4. Chạy cả bộ

```bash
python run_eval.py --scenarios data/seed-dev/scenarios --out evaluation/runs/seed-dev-full
```

400 kịch bản × 2 cấu hình, mỗi lượt agent một lần gọi model, cộng extractor cho từng lượt: chi phí lớn. Chạy một kịch bản (bước 2) và một tập con (bước 3) trước, xem `usage.json` để ước lượng.

## 5. Đọc kết quả

Thư mục `--out` của một lần chạy:

| File | Nội dung |
|---|---|
| `table.txt`, `report.json` | **số chính thức** của `reference_eval.py`: RQR, CCR, TSR (và TSR ca khó), HR (và HR giá/khuyến mãi), guardrail, độ trễ, `calls_to_close`; Baseline cạnh Hệ thống |
| `team_checks.json` | kiểm tra riêng của nhóm (`success_if.say_at_most`, ví dụ AIR-2ND-50 nói một lần); in dưới bảng BTC, là chẩn đoán |
| `errors.jsonl` | mọi cuộc trượt TSR, kèm lý do và các lượt cần đọc |
| `diagnostics.jsonl` | từng lượt: lane, guard, nhãn extractor kèm câu trích (`quote`) để kiểm tay |
| `full.jsonl`, `baseline.jsonl` | trace theo schema BTC |
| `usage.json`, `manifest.json` | token, chi phí, model, prompt, phiên bản extractor |

Cách tính từng chỉ số: [`docs/evaluation/scoring-flow.md`](../../docs/evaluation/scoring-flow.md).

**Chỉ so số giữa các lần chạy cùng `extractor_version`** (ghi trong `manifest.json`, hiện `product-extractor-v5`). Đổi extractor thì chấm lại lần chạy cũ thay vì chạy lại agent:

```bash
python run_eval.py --relabel evaluation/runs/seed-dev-full --out evaluation/runs/seed-dev-full-relabel
```

## 6. Retrieval (RAG), miễn phí

```bash
python evaluation/rag_offline.py                                     # 60 câu rag/qa_labeled.json của BTC
cd evaluation/data-generation && python -m src.pipeline.eval_rag     # thêm câu hỏi từ kịch bản (rag/scenario_qa.json)
```

`scenario_qa.json` lấy lời khách của từng cuộc gọi làm câu hỏi, đáp án là `relevant_policy_ids` của cuộc đó; kết quả ở `rag/scenario_rag_report.json`. Retriever của agent đánh giá trên cùng bộ câu bằng `eval_rag --results <rag_results.json của agent>`.

## 7. ASR

Hai bộ có đáp án: `asr_test/ground_truth.json` (24 hội thoại hai người, 8 có nhiễu băng thông điện thoại, kèm `audio/<id>.segments.json` để chấm diarization) và `audio/` (lượt khách, đáp án trong JSON cạnh mỗi WAV).

Chấm theo đúng cách của BTC cần `hypotheses.json` của ASR, đặt cạnh `ground_truth.json`, theo định dạng ghi trong trường `hypotheses_format` của file đó:

```json
{"<id>": {"text": "<transcript cả hội thoại>", "entities": {"price_vnd": 4890000}, "turns": [{"speaker": "A", "start": 0.0, "end": 3.2, "text": "..."}]}}
```

```bash
python apps/ai-agent-service/data/btc/eval/reference_eval.py --scenarios data/seed-dev/scenarios \
    --trace evaluation/runs/seed-dev-full/full.jsonl --asr data/seed-dev/asr_test --out evaluation/runs/seed-dev-asr.json
```

Repo **chưa có** script chạy `asr-service` hàng loạt để sinh `hypotheses.json`; cần viết trước khi chấm ASR.

## Lưu ý

- Bộ này sinh trước một số lần sửa bộ sinh dữ liệu: kịch bản đơn nhiều món sinh sớm có thể còn lời khách lệch số lượng, kịch bản cũ chưa có tag `date:`. Xem `reports/validation.json` và sinh lại khi cần.
- `evaluation/runs/` không lên Git: có hội thoại của agent và có thể có dữ liệu khách.
- Bộ chấm và gói BTC (`apps/ai-agent-service/data/btc`) không được sửa; `tests/agent/test_btc_pack.py` ghim hash từng file.
