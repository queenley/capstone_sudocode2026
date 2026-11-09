# Đánh giá agent trên bộ `data/dev`

> **Nhãn hiện tại là bản r4 (08–09/11/2026): xem [Nhãn đã sửa](#nhãn-đã-sửa-bản-r4-0809112026).** Đoạn dưới mô tả bản r3.
>
> **Bộ dev duy nhất, trước đây tên `seed-dev-r3`, revision của `seed-dev-r2` (05/11/2026).** Nhãn vẫn là chẩn đoán, chưa có người duyệt. Dựng offline; từng trường đổi và hash nguồn ở [`conversion-report.json`](conversion-report.json), phần chưa quyết ở [`DISPUTES.md`](DISPUTES.md).
>
> - 73 cuộc được trả lại câu xác nhận cuối bị cắt khỏi kịch bản; 42 cuộc `order.create` được thêm câu đồng ý sau câu đọc lại (chờ duyệt).
> - 60 kịch bản đổi kênh `fb` thành `chat_fanpage` theo `scenario_format.md`.
> - SCN-GEN-0224/call_2 dời khỏi Chủ nhật (LN-01).
> - Thêm SCN-ADV-0151..0154: hẹn gọi lại 01/01, Chủ nhật ngoài giờ, ngoài giờ ngày thường, 11/11. Tổng 404 kịch bản, 801 cuộc.
> - `audio/` và `asr_reference/` gồm clip của r2 cho lượt không đổi, cộng các lượt mới do `synthesize_scenario_audio --changed-only` đọc. `asr_test/` chép nguyên từ `seed-dev-r2`.
>
> Kiểm offline: 404/404 kịch bản nạp được; oracle CCR 100 · RQR 0 · TSR 100 · HR 0; hội thoại mẫu TSR 98,8. Oracle dựng từ nhãn nên không chứng minh nhãn đúng: xem `reports/label_check.json` (stage `check_labels`).

Bộ dữ liệu do [`evaluation/data-generation`](../../evaluation/data-generation/README.md) sinh, theo định dạng kịch bản của BTC. README này chỉ cách dùng nó để chấm agent. Con số chính thức luôn là `reference_eval.py` của BTC, chạy qua `run_eval.py` ở gốc repo (quy tắc trong [`evaluation/README.md`](../../evaluation/README.md)).

## Nhãn đã sửa (bản r4, 08–09/11/2026)

Các thư mục nhãn (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`), `conversion-report.json` và `DISPUTES.md` do [`build_dev_r4.py`](../../evaluation/datasets/ground-truth-review/build_dev_r4.py) ghi, dựng từ nhãn ở commit `46b2f2ff` (bản r3 ở trên), theo [quy trình duyệt nhãn](../../evaluation/datasets/ground-truth-review/SKILL.md). Bản r3 vẫn lấy lại được từ commit đó. Các run cũ trong `evaluation/runs/` chấm trên r3: không so số trực tiếp với run mới, mà ghi rõ là đổi nhãn. Nhãn vẫn là chẩn đoán (`official_gt_approved: false`). Từng trường đổi ở `conversion-report.json`, lý do và phần chưa làm ở [`DISPUTES.md`](DISPUTES.md).

| Nhóm | Sửa | Phạm vi |
|---|---|---|
| 1 | Cuộc chat mang mã kênh không có trong CRM: khách đọc SĐT ở lượt cuối (SAMPLE-04) | 29 cuộc |
| 2 | Bỏ `owned_sku` khỏi `must_carry_over` khi cuộc gọi nói về món khác | 115 cuộc |
| 3 | Đơn vượt hạn mức COD: thêm lượt khách đồng ý chuyển khoản | 11 cuộc |
| 4 | ADV-0028, ADV-0023 call_1: khách hoãn, `hen_goi_lai`, không tạo đơn | 2 cuộc |
| 5 | Bỏ `room_area_m2`/`blocker` khỏi `must_carry_over` của cuộc tra hoặc đổi đơn | 22 cuộc |
| 7 | Bỏ `phone_provided` ở cuộc hotline khách không đọc số của mình | 7 cuộc |
| 8 | `budget_vnd` bằng đúng số khách nói | 10 cuộc |
| 9 | `promo_active: false` khi chỉ có freeship hoặc COD-0 | 130 cuộc |
| 10 | Lời khách tự xưng khớp nhãn và CRM | 4 kịch bản |
| 11 | Nhãn entity ASR: định dạng (màu, mã đơn, size, năm), theo nghĩa (`blocker`, `promo_expiry`, `phone`, nhãn tiền, `restock_date`), và `blocker` có từ gợi ý (11b), `blocker` ở câu chỉ nói ngân sách (11c, người duyệt nêu) | 218 nhãn |
| 12 | Tag `source:btc` / `source:team` trong `metadata/` | 404 kịch bản |
| 14 | Khách nói đúng các fact mà nhãn ghi nhưng trước đó không nói ở đâu (diện tích, trẻ nhỏ, tuổi bé, ngân sách) | 144 cuộc |
| 16 | Bỏ `freeship` khi không biết nơi giao | 2 cuộc |
| 17 | Khách ẩn danh không đọc SĐT: cuộc sau chỉ giữ slot khách nói lại | 3 cuộc |
| 18 | ADV-0045/c1: bỏ `owned_sku` (lịch sử CRM chỉ để tham khảo) | 1 cuộc |
| 26–30 | `has_children` theo lời khách; khách nói cách thanh toán và diện tích phòng mới mà nhãn ghi; bỏ fact của người kia ở kịch bản chung SĐT; câu lẫn vai (người duyệt yêu cầu, sau lần kiểm thứ hai) | 39 cuộc |
| 25 | GEN-0099/c1: câu "có một bé lớn" nói rõ "nhà không có trẻ nhỏ" (người duyệt nêu) | 1 cuộc |
| 19–24 | Hành động kỳ vọng của agent: gọi lại khách hẹn, hoãn thì không tạo đơn, người chung SĐT, lịch gọi lại vào ngày nghỉ, xưng hô, kết quả gọi lại 22:00 ngày 11/11 (**chờ duyệt**) | 15 cuộc |

Kiểm, không gọi model: 404/404 kịch bản nạp được bằng loader của `run_eval`; 0 lỗi theo `contracts/scenario/scenario-keys.yaml`; oracle qua `reference_eval.py` của BTC: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema.

Dựng lại từ gốc repo: `python evaluation/datasets/ground-truth-review/build_dev_r4.py`, rồi từ `evaluation/data-generation`: `python -m src.pipeline.build_ground_truth --root ../../data/dev` (viết lại `trace_log/` và báo cáo oracle trong `reports/`).

**Hội thoại mẫu (`conversations/`) không phải ví dụ mẫu:** các ca J02 có câu bịa, ca agent mẫu không tạo đơn hoặc hỏi quá giới hạn, và mọi cuộc đã đổi lời khách được đánh dấu `approve: N` trong `review/needs_manual_review.csv` (`evaluation/datasets/ground-truth-review/mark_conversations.py`). Không dùng chúng làm few-shot hay dữ liệu vòng cải tiến. Bộ này chưa phải bộ vàng: `official_gt_approved: false`, chưa có `review/golden_manifest.json`. Kiểm tự động và đề xuất từng cuộc ở `review/auto_verified.json`, `review/review_sheet.csv` (`auto_verify.py`); người duyệt ký bằng `evaluation/datasets/ground-truth-review/approve_gold.py`.

**Audio chưa theo kịp nhãn:** các nhóm 1, 3, 10, 14, 21, 23, 25 đổi hoặc thêm lời khách trong `scenarios/`, nhưng `audio/`, `asr_reference/` của những lượt đó và hội thoại mẫu (`conversations/`) vẫn là lời cũ. Sinh lại bằng `synthesize_scenario_audio --changed-only` khi người duyệt thấy nhãn đã ổn.

## Trong thư mục có gì

| Thư mục | Nội dung | Dùng để |
|---|---|---|
| `scenarios/` | 404 kịch bản (250 persona BTC `SCN-GEN-*`, 154 của nhóm `SCN-ADV-*`), 801 cuộc gọi | **đầu vào của `run_eval.py`** |
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
python -m src.pipeline.build_ground_truth      # -> data/dev/reports/a6_oracle.txt, oracle_report.json
python -m src.pipeline.validate_rules          # -> data/dev/reports/validation.json (hội thoại mẫu)
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
python run_eval.py --scenarios data/dev/scenarios --only SCN-GEN-0001 --out evaluation/runs/dev-smoke
```

Không có `--config`: chạy cả `full` (có bộ nhớ) và `baseline_no_memory`, rồi in bảng BTC. Thêm `--only` nhiều lần để chạy vài kịch bản. `--no-extract` bỏ extractor (rẻ hơn, nhưng RQR và HR không đo được), chỉ để kiểm đường ống.

## 3. Chạy một tập con

`run_eval.py` nhận một thư mục, nên chép kịch bản cần chạy sang một thư mục riêng trong `evaluation/runs/` (không lên Git). Ví dụ lấy theo persona, theo tag hoặc theo mốc ngày:

```bash
python - <<'EOF'
import json, shutil
from pathlib import Path
seed, out = Path("data/dev"), Path("evaluation/runs/subsets/hard-cases/scenarios")
out.mkdir(parents=True, exist_ok=True)
for meta in sorted((seed / "metadata").glob("*.json")):
    m = json.loads(meta.read_text(encoding="utf-8"))
    if "hard_case" in m["tags"]:                 # hoặc: m["region"] == "nam", m["category"].startswith("me-be"), "date:sunday" in m["tags"]
        shutil.copy(seed / "scenarios" / meta.name, out / meta.name)
print(len(list(out.glob("*.json"))), "scenarios ->", out)
EOF
python run_eval.py --scenarios evaluation/runs/subsets/hard-cases/scenarios --out evaluation/runs/dev-hard-cases
```

Kịch bản sinh sau khi có mốc ngày mới có tag `date:<mốc>`: `promo_last_day`, `after_promo_end`, `before_promo_start`, `sale_day`, `out_of_stock`, `delivery_over_holiday`, `sunday`, `ordinary`.

## 4. Chạy cả bộ

```bash
python run_eval.py --scenarios data/dev/scenarios --out evaluation/runs/dev-full
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
python run_eval.py --relabel evaluation/runs/dev-full --out evaluation/runs/dev-full-relabel
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
python apps/ai-agent-service/data/btc/eval/reference_eval.py --scenarios data/dev/scenarios \
    --trace evaluation/runs/dev-full/full.jsonl --asr data/dev/asr_test --out evaluation/runs/dev-asr.json
```

Repo **chưa có** script chạy `asr-service` hàng loạt để sinh `hypotheses.json`; cần viết trước khi chấm ASR.

## Lưu ý

- Bộ này sinh trước một số lần sửa bộ sinh dữ liệu: kịch bản đơn nhiều món sinh sớm có thể còn lời khách lệch số lượng, kịch bản cũ chưa có tag `date:`. Xem `reports/validation.json` và sinh lại khi cần.
- `evaluation/runs/` không lên Git: có hội thoại của agent và có thể có dữ liệu khách.
- Bộ chấm và gói BTC (`apps/ai-agent-service/data/btc`) không được sửa; `tests/agent/test_btc_pack.py` ghim hash từng file.
