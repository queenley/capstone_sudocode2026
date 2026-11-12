# Evaluation

Đo chất lượng AI agent theo cách BTC chấm. Có **một đường chạy duy nhất**: `run_eval.py` ở gốc repo, cũng là lệnh giám khảo sẽ gọi.

| Đường dẫn | Là gì |
|---|---|
| [`run_eval.py`](../run_eval.py) (gốc repo) | Lệnh duy nhất: chạy kịch bản qua agent thật, gắn nhãn câu hỏi/claim bằng extractor, rồi chấm bằng `reference_eval.py` của BTC |
| `apps/ai-agent-service/src/ai_agent_service/pipeline/eval/` | Mã của lệnh trên: `cli.py`, `runner.py`, `trace.py`, `scenarios.py`, `report.py`, `relabel.py`, `performance.py`, `tables.py`, `rag.py` |
| `apps/ai-agent-service/src/ai_agent_service/components/evaluation/scorers.py` | Extractor (nhãn `questions`, `claims`, `facts_used`) | --accept-suggestions
| [`config/prompts/evaluation/extractor.txt`](../config/prompts/evaluation/extractor.txt) | Prompt của extractor, nạp nguyên văn |
| `apps/ai-agent-service/data/btc/` | Gói dữ liệu của BTC, bản duy nhất trong repo; `tests/agent/test_btc_pack.py` ghim hash từng file. `eval/mock_tools.py`, `eval/reference_eval.py`, `schemas/tools.schema.json` là bản cập nhật 11/2026 (đơn nhiều máy lọc không khí, so cụm theo nguyên từ): xem [scoring-flow §3](../docs/evaluation/scoring-flow.md#3-công-cụ-nghiệp-vụ) |
| [`../data/dev/scenarios/`](../data/dev/README.md) | Kịch bản để chấm: 409 kịch bản theo định dạng BTC, khớp CRM hiện tại (SCN-ADV-0155..0159 thêm ngày 12/11/2026, chưa người duyệt ký: `review/added.json`). Nhãn là bản r4 (08–09/11/2026), dựng bằng `datasets/ground-truth-review/build_dev_r4.py` từ bản r3 ở commit `46b2f2ff`; người duyệt đã chấp nhận mọi nhóm (1–31), không còn thay đổi chờ duyệt; `golden_manifest.json` duyệt 801/801 nhãn (578 hội thoại), `official_gt_approved: true` (10/11/2026). Không so số với run cũ (chấm trên r3) mà không ghi rõ là đổi nhãn. Thay đổi từng trường ở `conversion-report.json`, lý do ở `DISPUTES.md`. Hội thoại mẫu và audio của các lượt khách đã đổi lời đã sinh lại (09–10/11/2026) |
| [`../data/test/scenarios/`](../data/test/README.md) | 99 kịch bản, nhãn bản r1 (`datasets/ground-truth-review/build_test_r1.py`, từ commit `cfb43fbb`) theo các nhóm sửa của dev. **Cùng mã và cùng khách với 99 kịch bản đầu của `data/dev`; lời khách viết lại, 51 cuộc đổi ngày, 2 cuộc đổi kết quả kỳ vọng**: không phải tập test độc lập |
| [`datasets/`](datasets/README.md) | Quy tắc duyệt nhãn, ID kịch bản đã dùng và holdout |
| [`data-generation/`](data-generation/README.md) | Sinh kịch bản theo định dạng BTC (có venv, test, prompt riêng) |
| [`rag_offline.py`](rag_offline.py) | Recall@k của kho tri thức, không cần model hay database (`make eval`) |
| `runs/` | Bằng chứng mỗi lần chạy, cache extractor và sổ ngân sách. **Không lên Git** (có thể chứa dữ liệu khách) |
| [`../docs/evaluation/`](../docs/evaluation/README.md) | Luồng vào bộ chấm, bản đồ hệ thống |

## Điều kiện trước khi chạy

| Cần | Vì sao | Cách |
|---|---|---|
| **Docker: chỉ PostgreSQL** | Bộ nhớ khách, trạng thái mock (đơn, lịch hẹn) và kho tri thức của các MCP server nằm trong database `<tên>_eval`, được tạo ở lần chạy đầu và xóa giữa các kịch bản | `docker compose up -d postgres` (cổng `127.0.0.1:5432` qua `docker-compose.override.yml`). Không cần các service khác: MCP server chạy thành tiến trình con qua stdio, không cần Redis, Qdrant, Kafka hay `ai-agent-service` |
| Python của agent | Lệnh và các MCP server chạy bằng cùng interpreter | `apps/ai-agent-service/.venv` (cài theo `apps/ai-agent-service/requirements.txt`) |
| `.env` ở gốc repo | `run_eval.py` tự nạp | `DATABASE_URL` (hoặc `AGENT_DATABASE_URL`) trỏ tới Postgres trên, ví dụ `postgresql://postgres:local-postgres-change-me@127.0.0.1:5432/app_db`; hoặc `EVAL_DATABASE_URL` với tên database kết thúc `_eval`. `OPENAI_API_KEY` cho advisor và extractor (`gpt-4.1-mini`). `TYPESAFE_API_KEY` cho kiểm chính sách (Jev): thiếu thì lượt đó chỉ qua hard guard, đếm ở `policy_skipped` |
| Windows | Bảng của `reference_eval.py` có tiếng Việt | Không cần làm gì: lệnh chạy bộ chấm với UTF-8. Lần gọi đầu tới mỗi MCP server khởi động nguội chậm; xem [chẩn đoán seed](../docs/evaluation/seed-timeout-windows.md) |

**Windows: dùng `127.0.0.1`, không dùng `localhost`** trong `DATABASE_URL`/`EVAL_DATABASE_URL`. `localhost` thử IPv6 `::1` trước, mà Docker chỉ mở cổng trên IPv4: mỗi kết nối mất ~15 giây, pool báo `PoolTimeout` sau 10 giây, các MCP server khởi động mất nhiều phút và bước nạp seed bị `TIMEOUT` (đo 04/11: kết nối 15 s → 0,02 s, khởi động MCP 457 s → 12,5 s).

Kiểm nhanh: `docker compose ps postgres` báo `healthy`, rồi chạy một kịch bản với `--only` trước khi chạy cả bộ.

## Chạy

Từ gốc repo:

```bash
# Chạy kịch bản qua agent (tốn phí model). Không --config: cả full và baseline_no_memory, rồi in bảng BTC
python run_eval.py --scenarios data/dev/scenarios --only SCN-GEN-0051 --out evaluation/runs/<tên>

# Kiểm đường ống mà không gọi extractor (agent vẫn gọi model; RQR và HR không đo)
python run_eval.py --scenarios <thư mục> --only <ID> --no-extract

# Gắn nhãn lại một run cũ bằng extractor hiện tại, KHÔNG chạy lại agent (chỉ tốn lượt gọi extractor)
python run_eval.py --relabel evaluation/runs/<ngày>-work/<run> --out evaluation/runs/<tên>-relabel

# Chỉ chấm một cấu hình (không có cột baseline). Cũng là cách duy nhất chấm một run bị dừng mà không ghi lý do,
# và chỉ khi trace của cấu hình đó đủ mọi lượt, không lượt hay after_call nào lỗi
python run_eval.py --relabel evaluation/runs/<run> --config full --out evaluation/runs/<tên>-full-relabel

# Bảng hiệu năng của run đã xong, miễn phí (không model, không database)
python run_eval.py --performance evaluation/runs/<tên>

# Chạy kèm bảng hiệu năng; --sessions thêm phép thử tải, TỐN PHÍ model (mỗi phiên tối đa 3 lượt)
python run_eval.py --scenarios data/dev/scenarios --performance --sessions 1,3,5 --out evaluation/runs/<tên>

# Ba bảng báo cáo từ các run đã xong, miễn phí; chọn all hoặc asr,agent,performance
python run_eval.py --report all --run router=evaluation/runs/<tên> --asr-run evaluation/runs/<asr>
python run_eval.py --report agent,performance --run router=evaluation/runs/<a> --run gaploop=evaluation/runs/<b>

# Chạy mới rồi in các bảng, run này là cột Router, TỐN PHÍ model
python run_eval.py --scenarios data/dev/scenarios --report all --out evaluation/runs/<tên>

# Router: đường chuẩn, dùng knowledge và skills đang active (TỐN PHÍ model)
python run_eval.py --scenarios data/dev/scenarios --profile router --out evaluation/runs/router-<tên>
# GapLoop: chạy trên một knowledge version đã duyệt, TỐN PHÍ model
python run_eval.py --scenarios data/dev/scenarios --profile gaploop --kb-version 1 --out evaluation/runs/gap-<tên>
# Reflection: chạy trên một skills version đã duyệt, TỐN PHÍ model
python run_eval.py --scenarios data/dev/scenarios --profile reflection --skills-version 1 --out evaluation/runs/reflection-<tên>

# Recall@k của kho tri thức, miễn phí
python evaluation/rag_offline.py

# ASR local: thử một clip của gói đã có, không provider/extractor
python run_eval.py --asr-package /absolute/path/package --asr-unit segments --only CLIP_ID --asr-transcribe --asr-model zipformer-30m --out evaluation/runs/asr-smoke-new
# Rubric judge BTC trên một run đã có (tốn phí judge, không chạy lại agent); hoặc thêm --judge khi chạy
python run_eval.py --judge-run evaluation/runs/<run> --out evaluation/runs/<run>-judge
# Bốc ≥20 cặp (cuộc gọi, tiêu chí) thành phiếu chấm tay, không gọi model; người chấm điền sheet.csv
python run_eval.py --judge-sample evaluation/runs/<run>-judge
# Độ đồng thuận người–judge: % và Cohen's kappa; kappa < 0,6 thì phân tích lỗi
python run_eval.py --judge-agreement evaluation/runs/<run>-judge/human-review
```

Giới hạn chi tiêu (tùy chọn): không đặt `EVAL_BUDGET_DB` thì lệnh chạy **không có trần chi tiêu** và in một dòng nhắc. Muốn đặt trần, tạo sổ một lần bằng `evaluation_budget.initialize(path, usd)` rồi đặt `EVAL_BUDGET_DB` trỏ tới nó; khi đã đặt, CLI chặn sổ thiếu/hỏng/hết cap trước DB/model. Không tạo lại sổ để chạy tiếp một ngân sách đã hết. SDK retry phải bằng 0 để không bỏ sót usage của request tính phí. Budget hiện hỗ trợ `openai:gpt-4.1-mini` (xem `llm/evaluation_budget.py`). ASR local/hypothesis replay không cần ledger. `EVAL_RUNS_DIR` đổi chỗ ghi `runs/`.

Mã thoát: `0` đủ nhãn và đã chấm · `1` có lượt lỗi hoặc chưa gắn nhãn (không in bảng, trace vẫn được giữ) · `2` đầu vào hoặc cấu hình sai.

### Bốn chỉ số của BTC

RQR, CCR, TSR, HR đều do `reference_eval.py` của BTC tính, chạy nguyên bản trên hai trace (`report.grade`); đội không tính lại công thức nào. Dữ liệu mỗi chỉ số cần (nhãn kịch bản và trường trace), độ phủ trên `data/dev` và các trường HR chưa kiểm được: [luồng vào bộ chấm, mục 5.1](../docs/evaluation/scoring-flow.md#51-dữ-liệu-từng-chỉ-số-cần-và-chỗ-còn-hở).

`ADVISOR_CONTEXT=full` nạp đủ luật và đủ brief; không đặt thì chạy chế độ tập trung. Biến này đọc cả từ `.env`, và biến của shell thắng `.env`. Lệnh in dòng `Advisor context`, manifest ghi `advisor_context`: đọc hai chỗ này trước khi so hai run.

### Nhiều phép đo

Mỗi profile là một run độc lập nhưng dùng cùng `--scenarios`, model, extractor và cấu hình database. `--profile` chỉ ghi rõ biến thể được đo; nó không thay công thức của `reference_eval.py` và không tự chạy vòng cải tiến. `gaploop` bắt buộc `--kb-version <N>`, còn `reflection` bắt buộc `--skills-version <N>`; version `0` của Reflection là `config/prompts/agent/advisor/skills.yaml`.

Vòng học và phê duyệt chạy riêng bằng `pipeline.improve`. Sau khi có version mới, chạy lại cùng cohort frozen rồi ghép bảng:

```bash
python -m ai_agent_service.pipeline.improve round --name learn-1 --learn data/gap-loop --frozen data/reflection --scripted
python run_eval.py --report all \
	--run router=evaluation/runs/router-<tên> \
	--run gaploop=evaluation/runs/gap-<tên> \
	--run reflection=evaluation/runs/reflection-<tên> \
	--out evaluation/runs/comparison.md
```

`--report` không gọi model. Cột phải được đặt tên đúng profile; manifest ghi profile, knowledge override và skills override để báo cáo cảnh báo khi gắn nhãn sai hoặc hai cột thực ra dùng cùng version. So sánh chỉ hợp lệ khi cohort, model, extractor và context giống nhau; xem thêm [scoring-flow](../docs/evaluation/scoring-flow.md).

### Bảng báo cáo

`--report` ghép ba bảng từ file của các run đã xong, cột nào chưa đo thì ghi `chưa đo`, không điền số. Cột Baseline lấy từ baseline của run `router`.

| Cột | Cần gì | Hiện trạng |
|---|---|---|
| Baseline, Router | Một run không `--config` | Đo được |
| GapLoop, Reflection | Run với `--kb-version N`, `v<N>.jsonl` có mục đã duyệt | `v0.jsonl` đang rỗng: run lúc này chỉ lặp lại Router, ghi chú sẽ báo |
| Subagent, A/B Testing | Agent phải có chế độ đó | Chưa có, cột ghi `chưa có` |
| ASR | Một run `--asr` | Đo được |

`--run` nhận `router`, `subagent`, `gaploop`, `reflection`, `ab`; thêm `--out <file>` để lưu bảng. `--report` đứng một mình bị từ chối để không vô tình chạy tốn phí. Run có `--config` không có `report.json`, nên cột Agent ghi `chưa đo`: chạy không `--config` để có cột đầy đủ. Bảng ASR đọc `main_scorer` của run `--asr`, mỗi tầng văn bản một cột. `subagent` và `ab` vẫn hiện `chưa có` vì chưa có profile thực thi.

Ghi chú dưới bảng báo khi hai cột khác bộ kịch bản, khác model, hoặc cùng knowledge.

### Hiệu năng

`--performance` in bảng "Chế độ vận hành & hiệu năng" và ghi `performance.json`, đọc từ trace và `usage.json` của cấu hình `full`:

| Dòng | Nguồn | Ghi chú |
|---|---|---|
| Chế độ vận hành | `input_mode` trong trace, model của manifest | |
| Call Brief, TTFT, Total | `reference_eval.latency` của BTC, p95 | Ngưỡng theo `huong-dan-do-latency.md`; cần ≥ 100 lượt mới có ý nghĩa |
| TTFA (voice) | `latency.ttfa_ms` | `run_eval.py` chạy chữ nên luôn "chưa đo"; số thật nằm ở màn Developer khi gọi voice |
| Số phiên đồng thời | `--sessions` | Mức cao nhất không lỗi và p95 trong ngưỡng chat, không ghi trace, không chấm |
| Thời gian theo bước | `timings` trong `diagnostics.jsonl` | Trung bình, p50, p95 của từng bước (`observability/stopwatch.py`); run cũ ghi "chưa đo" |
| Token mỗi lượt | `usage.json` | Trung bình theo lượt khách, tách và cộng `after_call` |
| Chi phí mỗi lượt | token nhân giá niêm yết (`performance.PRICES`) | Chỉ model đã chạy là số đo; model kia là ước tính cùng số token, chưa tính cache. Giá Gemini 3 Flash lấy từ trang theo dõi bên thứ ba, cần đối chiếu trang giá Google trước khi báo cáo |

`agent_text` trong trace là đúng lời khách nghe: số điện thoại chỉ đọc đủ trong câu xác nhận giao hàng (PB-08), các câu khác còn 3 số cuối (`*******876`).

Một run ghi: `full.jsonl`, `baseline.jsonl` (trace theo schema BTC), `diagnostics.jsonl` (từng lượt: lane, guard, và `extraction_items` kèm quote để kiểm tay), `report.json` + `table.txt` (BTC), `usage.json`, `manifest.json`, `errors.jsonl`, `rag/`.

Dùng `--out` mới hoặc thư mục rỗng; CLI không ghi đè bằng chứng đã có. Run lỗi không xuất bảng: xem `scenario-errors.jsonl`, `evaluation-error.log` hoặc `scoring-error.txt` tùy bước lỗi. Manifest chỉ `COMPLETE` sau khi hoàn tất output; chi tiết kiểm thử pipeline và Windows ở [chẩn đoán seed/đường chấm](../docs/evaluation/seed-timeout-windows.md).

Scenario được kiểm trước khi gọi model và snapshot từ nội dung đã nạp, cả `--config`. Database có advisory lock cho toàn bộ run, chặn hai runner reset lẫn nhau; output được giữ chỗ độc quyền. Trước extractor/scorer phải đủ đúng từng scenario/call/turn, đúng config và lời khách, không trùng hoặc trộn run. Trace được lưu sau mỗi scenario để giữ replies nếu bước sau lỗi. Relabel chỉ sửa lỗi extractor trên replies đầy đủ; lỗi seed, graph hoặc after-call vẫn chặn chấm.

Extractor hiện là `product-extractor-v13`. v13 (10/11/2026) sửa sẵn trước khi validate các lỗi mà luật đã định cách xử lý: `kind` lạ thành `other`, câu hỏi `open` có `value` thì đặt `value` null, claim/fact_usage bỏ `question_type`, thiếu `purpose` thì để rỗng; prompt nói rõ `source_field` không bao giờ là `previous_sessions`/`crm_history`; log thử lại in nguyên văn lỗi. v12: lượt nhắc lại một giá trị đã biết được tính là dùng dữ kiện đó. Từ v11: entity nạp từ `contracts/scenario/scenario-keys.yaml` (thêm slot `return_reason`, `tracking`; claim `callback_at`, `gift_sku`, `new_variant_sku`, `successor_sku`, `price_vnd:<SKU>`, `future_promo_disclosed`), mỗi lượt có thêm `today` và `crm_history`; số v11 so với v10 phải relabel cùng replies. v10 như v9, nhưng một mục model gắn `kind: other` (không phải câu hỏi, claim hay dữ kiện dùng lại) bị bỏ thay vì làm hỏng cả lượt; số của v10 so với v9 phải relabel cùng replies. v9 thêm 20 trường claim (trạng thái/mã đơn, mã vận đơn, ngày giao dự kiến, COD, bảo hành, đổi trả…) và slot `issue`, để HR kiểm được các `ground_truth_facts` của kịch bản nhóm mà v8 bỏ qua. Số HR của v9 không so trực tiếp với v8; muốn so phải relabel cùng replies. Cache JSON có thể mất hit khi nhiều process ghi snapshot, làm tăng số cache miss trong cap; không làm file cache bị ghi dở.

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
