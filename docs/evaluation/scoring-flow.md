# Luồng đi vào bộ chấm

Một trang để biết một con số RQR, CCR, TSR hay HR đến từ đâu. Cập nhật 27/10/2026, sau khi đối chiếu code và gói dữ liệu BTC (`BTC-Data-Vong1-TEAMS`).

## 1. Ba điều cần nhớ

1. **Con số chính thức luôn là `reference_eval.py` của BTC**, chạy nguyên bản trên một file trace. Bốn bản (gói BTC, `evaluation/agent-evaluation/contracts/sources/btc/eval/`, `apps/ai-agent-service/data/btc/eval/`, `evaluation/data-generation/data/eval/`) giống hệt nhau từng byte (SHA-256 `818fc490…`). Harness từ chối chạy nếu bản được ghim trong run khác bản chuẩn.
2. **Script đó chỉ đọc trace**, không đọc hội thoại. Mọi thứ nó cần phải có sẵn trong mỗi dòng trace: `questions[]`, `claims[]`, `facts_used[]`, `tool_calls[]`, `latency`, `memory_writes`. BTC không phát extractor: việc trích `questions` và `claims` từ lời agent là của đội, và BTC chấm tay ngẫu nhiên 20 lượt để bắt extractor bỏ sót.
3. **Có hai đường sinh ra trace**, không được trộn số của hai đường (xem [system-map](system-map.md), mục "Hai runner").

| | Đường A: lệnh của giám khảo | Đường B: harness phân tích |
|---|---|---|
| Lệnh | `run_eval.py --scenarios <dir> --config full\|baseline_no_memory --out <file>` ở gốc repo | `evaluation/agent-evaluation/run_eval.py evaluate` |
| Mã | `apps/ai-agent-service/src/ai_agent_service/pipeline/eval/cli.py` | `evaluation/agent-evaluation/src/` |
| Công cụ nghiệp vụ | MCP của sản phẩm | mock BTC do harness quản lý (memory, knowledge vẫn qua MCP) |
| Extractor | `scorers.Extractor`, prompt `config/prompts/agent/turn_labeller.md` | `src/services/agent/extract_command.py`, prompt `config/prompts/evaluation/extractor.txt` |
| `facts_used` | tất định: các trích dẫn `[Bn]` agent đã dùng (`pipeline/eval/trace.py`) | extractor (`fact_usage`) cộng `facts_used` agent tự báo |
| Dùng cho | số trên bộ ẩn của BTC | phân tích, kiểm nguồn gốc bằng chứng, nhãn bổ sung |

**Hệ quả:** prompt extractor của đường B (`extractor.txt`, v4) không ảnh hưởng đường A. Muốn đường A nhận 35 slot (có `channel`) thì phải sửa `turn_labeller.md` và `components/evaluation/scorers.py` trong `apps/`, phần thuộc sở hữu của product.

## 2. Đường B từng bước

```
run_eval.py evaluate --dataset-id <id> --level M1|M2
 │
 ├─ prepare   (steps/prepare)      ghim đầu vào, mã agent, prompt extractor; cổng execution_gate
 │            → <run>/inputs/          scenarios, grading, nhãn tool, extractor-prompt.txt, extractor.json
 │
 ├─ run       (steps/run)          mỗi kịch bản × {full, baseline_no_memory}: một tiến trình agent
 │            khách nói đúng customer_turns viết sẵn của kịch bản, ở cả M1 và M2
 │            (khách do mô hình đóng vai chỉ có ở lệnh simulate, mục 5)
 │            tool nghiệp vụ do mock BTC trả lời
 │            → <run>/raw/{full,baseline_no_memory}/   raw-execution.jsonl, tools.jsonl, timing
 │
 ├─ collect   (steps/collect)      mỗi lượt agent một "document": lời khách, lời agent, tool, thời gian
 │     ├─ ModelExtractor              gọi services/agent/extract_command.py một lần mỗi lượt
 │     │     đầu vào: agent_text, tool_texts, consultant_texts, và từ call_2 trở đi previous_sessions
 │     │     (không có nhãn, kỳ vọng, bộ nhớ hay kết quả tool)
 │     ├─ slots.restrict              ép về từ vựng cố định: 35 slot, 19 trường claim, kiểu giá trị đúng
 │     └─ dựng dòng trace BTC         questions, claims, facts_used, tool_calls, latency
 │            → <run>/evidence/{full,baseline}.jsonl, transcripts/, extraction.jsonl, coverage
 │
 └─ score     (steps/score)        chỉ đưa các dòng hợp lệ cho BTC
       ├─ python reference_eval.py --scenarios --trace full.jsonl --baseline baseline.jsonl   (subprocess, steps/score/official.py)
       │     → <run>/scored/official-report.json        ← SỐ CHÍNH THỨC
       ├─ kiểm bổ sung của đội (assertion-details.json, tool-call accuracy, fact/claim grounding)
       └─ supplement.py + side_reports.py                ← CHỈ ĐỂ BÊN CẠNH, không thay số chính thức
```

`evaluate` chạy trọn bốn bước; `prepare`, `run`, `collect`, `score` cũng chạy riêng được. Một bộ trộn M1 và M2 được tách thành hai run `<out>-M1`, `<out>-M2`.

Mỗi run là một thư mục bất biến sau khi đóng (`artifacts.lock.json` ghi hash từng file). Không sửa tay file trong đó rồi chấm lại như run thật.

## 3. Con số nào đến từ đâu

| Chỉ số | Hàm trong `reference_eval.py` | Trường trace nó đọc | Ai sinh trường đó |
|---|---|---|---|
| RQR | `repeat_question_rate` | `questions[].slot`, `.type`; `must_not_ask` của kịch bản | extractor |
| CCR | `context_carryover_rate` | `facts_used[]` và tên khóa trong `tool_calls[].args`; `must_carry_over` | A: trích dẫn `[Bn]`. B: extractor + agent tự báo |
| TSR | `task_success_rate` → `check_call` | `tool_calls`, `agent_text`, `claims` (cho `forbidden_claims`), `questions` (cho `max_agent_questions`), `memory_writes` | agent (tool), extractor (claim, question) |
| HR | `hallucination_rate` | `claims[].field`, `.value` so với `ground_truth_facts`; HR giá&KM là các trường bắt đầu bằng `price`, `promo`, `list_price` | extractor |
| Guardrail | `guardrail_violations` | `agent_text`, `memory_writes`, `tool_calls[].args`, claim `is_human` | agent, extractor |
| Latency | `latency` | `latency.ttft_ms`, `total_ms`, `ttfa_ms`, `call_brief_latency_ms` | mốc thời gian của adapter |
| Số lượt TB, Calls-to-Close | `avg_turns`, `calls_to_close` | số dòng trace; `order.create` trong `tool_calls` | agent |
| WER, CER, Entity Accuracy, diarization | `wer_cer` | không đọc trace; đọc `asr/ground_truth.json` và `hypotheses.json` | lệnh `asr` riêng |

Quy tắc chấm cần nhớ khi viết hay sửa prompt extractor (đã kiểm trên `reference_eval.py`):
- RQR: câu `open` về slot trong `must_not_ask` là thừa; câu `confirm` lần thứ hai trở đi về cùng slot trong một cuộc cũng thừa; `confirm` lần đầu không thừa. Mọi câu hỏi, kể cả `other`, đều vào mẫu số.
- HR: chỉ claim có trường nằm trong `ground_truth_facts` của cuộc đó mới được tính, và so bằng `!=` chính xác, nên kiểu giá trị (số nguyên, bool, chuỗi) phải đúng.
- CCR: không kiểm nguồn của `facts_used`; định nghĩa của BTC là "slot từ phiên trước được dùng có ý nghĩa".

## 4. Phần của BTC và phần đội tự thêm

| Thuộc BTC (nguyên bản) | Đội thêm, chỉ để bên cạnh |
|---|---|
| `reference_eval.py`, `mock_tools.py`, schema trace, bộ kịch bản | `src/criteria/` (`carryover.py`, `claims.py`, `tool_state.py`…): kiểm giá trị `fact_usage` đúng ground truth (chặt hơn CCR), grounding claim, kiểm tool thành công |
| `official-report.json` | `steps/score/supplement.py`: p50/p95 bỏ 3 lượt warm-up (BTC lấy mọi dòng), Calls-to-Close chỉ tính đơn có trong trạng thái mock |
| bảng A.6 in từ script | `steps/score/side_reports.py`: diễn giải lại claim, chỉ chẩn đoán (`official_score_changed: false`) |

Không có chỗ nào đội tính lại RQR, CCR, TSR hay HR bằng công thức riêng để thay cho số BTC.

## 5. `simulate` không đi qua collector

`run_eval.py simulate` chạy khách do mô hình đóng vai (kernel 8 quy tắc BTC), mỗi seed một thư mục `raw-seed{N}/`. Nó **không** gọi collector, extractor hay `score`. TSR lấy từ `check_call` của BTC chạy ngay trong tiến trình, trên hàng do bộ quan sát (một lần gọi mô hình mỗi lượt agent) dựng, nên không có RQR, CCR, HR hay latency. Điểm BTC chấm cho simulator là thiết kế và độ lặp lại (TSR lệch ≤ 10 điểm giữa 3 seed), còn TSR chính thức vẫn dùng `customer_turns` viết sẵn của `evaluate`.

## 6. Hai extractor của hai đường

| | `extractor.txt` (đường B) | `turn_labeller.md` (đường A) |
|---|---|---|
| Từ vựng | 35 slot (34 của ontology + `channel`); 18 trường claim và `promo_<CODE>_active` | 34 slot; 18 trường claim và `promo_<CODE>_active` (`scorers.SLOTS`, `CLAIM_FIELDS`) |
| Đầu vào | lượt này, cộng các cuộc trước | lượt này |
| Đầu ra | `Item` có `quote` và offset, collector kiểm quote bằng lát cắt | `TurnLabels` (`questions`, `claims`) |
| `facts_used` | có `fact_usage` | không: lấy từ `[Bn]` |
| Cache | chỉ ghi vào `evidence/cache/` theo đầu vào đầy đủ, không đọc lại: mỗi lần `collect` gọi mô hình lại | `runs/cache/extractor.json`, đọc lại, khóa theo `PROMPT_SHA` |

Từ vựng của B lấy từ chính `scorers` của A (`src/services/agent/slots.py`) để hai đường dán nhãn cùng bộ tên; `channel` là phần B thêm.

## 7. Điểm dễ nhầm

- **Thư mục run lồng nhau.** Mỗi ngày làm việc là một thư mục (`20261024-work/`) chứa nhiều run cùng sổ ngân sách và script. `run_eval.py history` nay liệt kê các run bên trong.
- **Một đầu vào xuất hiện nhiều lần.** `inputs/` được chép sang `raw/inputs`, `evidence/raw/inputs` và `scored/evidence/raw/inputs` để mỗi tầng tự kiểm hash. Đọc tầng cuối cùng bạn cần, không cần đọc cả bốn.
- **Số v3 và v4 không so được.** Đổi prompt hay đầu vào extractor là đổi dụng cụ đo. `benchmark` và `compare-rounds` từ chối so hai run khác `extractor_version`.
- **Script `run-*.sh` trong `runs/20261024-work/`** là bản ghi lệnh đã dùng, còn gọi `scripts/evaluation/run_eval.py` (đường dẫn cũ). Giữ nguyên làm bằng chứng; lệnh hiện hành là `evaluation/agent-evaluation/run_eval.py`.
- **Docstring của `reference_eval.py` nhắc `--catalog`**, nhưng script không có cờ đó. Đó là file của BTC, không sửa.

## 8. Lệnh

```sh
# Offline, không gọi mô hình
apps/ai-agent-service/.venv/bin/python evaluation/agent-evaluation/run_eval.py data-check --set create-data-diagnostic-v4
apps/ai-agent-service/.venv/bin/python evaluation/agent-evaluation/run_eval.py prepare --dataset-id create-data-diagnostic-v4 --level M2 --only SCN-GEN-0051
apps/ai-agent-service/.venv/bin/python evaluation/agent-evaluation/run_eval.py history

# Gọi mô hình, tốn phí (ghi RUN-LEDGER.md trước và sau)
apps/ai-agent-service/.venv/bin/python evaluation/agent-evaluation/run_eval.py evaluate --dataset-id create-data-diagnostic-v4 --level M2 --only SCN-GEN-0051

# Chấm lại bằng chứng đã đóng với extractor hiện tại, chỉ tốn lượt gọi extractor
apps/ai-agent-service/.venv/bin/python docs/evaluation/rescore_with_scoped_extractor.py evaluation/agent-evaluation/runs/<ngày>-work/<run>
```

Tham chiếu: [README của agent-evaluation](../../evaluation/agent-evaluation/README.md), [system-map](system-map.md), [RUN-LEDGER](RUN-LEDGER.md), [guardrail sửa evaluation](../../evaluation/agent-evaluation/docs/CODING-INCIDENTS-AND-GUARDRAILS.md).
