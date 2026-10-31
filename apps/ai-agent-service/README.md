# AI Agent Service

Agent telesales chạy sau gateway, cổng `8400`. Đây là bản port của agent tham chiếu (`temp-repo-for-agent/backend`; đặc tả trong `docs/design.md` của repo đó) lên nền tảng này. Đồ thị, các agent, guardrail, MCP tool và kênh voice giữ như bản gốc. Conversation, xác thực và hàng chờ nhân viên dùng lại của platform.

Entry point: [src/ai_agent_service/main.py](src/ai_agent_service/main.py). Toàn bộ endpoint: [docs/api.md](../../docs/api.md#ai-agent-lượt-của-khách).

## Một lượt chạy thế nào

```mermaid
flowchart LR
    W[Web / Voice WS] -->|/api/conversations/:id/turns · stream · voice| GW[api-gateway]
    GW --> API[ai-agent-service]
    API -->|xác thực token| PDB[(DB platform<br/>conversation.*)]
    API -->|mỗi conversation một cuộc gọi,<br/>lease + turn_id idempotent| CALLS[(schema agent<br/>calls · turns · pii_vault<br/>checkpoint LangGraph)]
    API --> G

    subgraph G[Hot graph — pipeline/hot]
        direction LR
        P[perceive<br/>làm sạch · ITN · token PII] --> L[load_context<br/>tier định danh · CallBrief]
        L --> R[route<br/>chọn lane bằng luật]
        R --> A[advisor<br/>ReAct trên tool của lane]
        A --> GU[guard<br/>hard → Jev]
        GU -->|trượt, regen ≤ 2| A
        GU --> RS[respond<br/>giải token]
        RS --> PE[persist]
    end

    A <-->|stdio MCP| M[MCP servers<br/>catalog · crm · order<br/>memory · knowledge]
    M --> BTC[data/btc mock_tools<br/>+ kho chính sách]
    PE --> API
    API -->|transcript đã che PII,<br/>handoff của agent| PDB
```

1. **perceive**: chuẩn hóa văn bản (teencode, ký tự ẩn), sửa tên sản phẩm ASR nghe sai, đổi số nói thành số ("mười tám triệu" → 18.000.000đ, "tối mai 8 giờ" → giờ ISO), thay số điện thoại/CCCD/số tài khoản/địa chỉ bằng token `<PHONE_1>`, `<ADDR_1>`. Giá trị thật nằm trong vault mã hóa AES-GCM. Model, Jev, trace và checkpoint chỉ thấy token; tool cần địa chỉ thì harness điền lại địa chỉ thật.
2. **load_context**: xác định khách (tier `VERIFIED` / `PROBABLE` / `AMBIGUOUS` / `UNKNOWN`), dựng CallBrief từ fact ledger, rồi tra kho tri thức bằng lời khách (`kb_search`: BM25 + embedding local, gộp RRF, chọn đúng phiên bản chính sách theo ngày đặt đơn).
3. **route**: chọn lane bằng luật (bảng dưới). Lane quyết định advisor được thấy tool nào.
4. **advisor**: model trong `config/models.yaml` gọi tool kiểu ReAct qua MCP. Câu trả lời được stream và cắt theo câu; mỗi câu qua guard rồi mới phát (SSE `delta`). Câu đệm khi đang gọi tool không tính là câu trả lời.
5. **guard** (từng câu khi stream, cả bản nháp khi ở chế độ copilot):
   - Hard guard kiểm tra: mọi số tiền (cả viết bằng chữ) phải có trong kết quả tool, lời khách hoặc tài liệu đã đưa cho model; thời hạn ngày/tháng, tồn kho, mã khuyến mãi phải có nguồn; không nhắc khuyến mãi chưa bắt đầu; mã đơn chỉ đọc cho khách đã xác minh; không lộ PII thô hay giá nhập; không nhận là người; câu thừa nhận thiếu thông tin dùng đúng cụm BTC chấm; trả lời tiếng Việt và ngắn gọn.
   - Sau đó Jev (PolicyAgent) chấm theo chính sách, chỉ với câu có tín hiệu rủi ro.
   - Chặn trước khi phát thì advisor viết lại tối đa 2 lần; chặn khi đã phát một phần thì dừng và nói câu an toàn.
6. **respond / persist**: giải token (khách thấy lại số của mình), lưu lượt và checkpoint.

Giao diện trên web:

- khách bấm **☏ Gọi cửa hàng** để gọi thoại;
- nhân viên dùng `/calls` (hàng chờ, nhận handoff, gợi ý copilot, lưu FAQ, bằng chứng);
- developer dùng `/developer` (model, độ trễ p95, lượt, voice, ngày nghiệp vụ).

Khi cuộc gọi kết thúc, after_call chạy MemoryAgent (ghi fact ledger) và QaAgent (chấm điểm cuộc gọi). Cuộc gọi kết thúc khi nhân viên bấm kết thúc, khi Sales đóng conversation, hoặc sau 30 phút im lặng; reconciler kiểm tra mỗi phút.

### Lane (`config/lanes.yaml`, `components/orchestration/rules.py`)

| # | Lane | Khi nào |
|---|---|---|
| 1 | `HANDOFF` | ≥ 2 lỗi tool hoặc ≥ 2 câu an toàn trong cuộc gọi |
| 2 | `CLARIFY` | ASR không chắc |
| 3 | `CONFIRM_IDENTITY` | tier `PROBABLE` / `AMBIGUOUS`, khi câu hỏi xác nhận duy nhất còn chờ trả lời |
| 4 | `ORDER_SERVICE` | khách có đơn và đang nói về đơn |
| 5 | `OUT_OF_SCOPE` | chủ đề phải chuyển người (PB-06), ví dụ khiếu nại pháp lý |
| 6 | `CONTINUITY` | khách `VERIFIED` quay lại, đã có brief |
| 7 | `NEW` | mặc định |

Luật khớp đầu tiên thắng. Khách xin gặp nhân viên ở lane `NEW` thì advisor tự gọi `handoff.transfer`.

Những gì cần đọc hiểu lời khách không nằm trong luật mà nằm trong instruction của advisor (`agents/advisor.py`): tài liệu có trả lời được câu hỏi không, người đang nói có đúng là người trong hồ sơ không (xưng hô khác, tên khác), xử lý khách chê đắt hay so giá. Số dùng chung: câu hỏi tên do harness nói nguyên văn, hỏi đúng một lần. Khách khai số giữa cuộc mà chưa xác nhận rõ thì sau cuộc gọi MemoryAgent đọc cả cuộc để quyết định có ghi vào hồ sơ đó không; không chắc thì không ghi vào ai.

### Khi thiếu cấu hình

| Thiếu | Hành vi |
|---|---|
| Key của provider advisor | advisor lỗi, agent nói câu an toàn; sau hai câu như vậy, lane `HANDOFF` chuyển cho nhân viên |
| `TYPESAFE_API_KEY` (Jev) | bỏ qua soft guard, hard guard vẫn chạy |
| Database | service vẫn khởi động; `/health` báo `degraded` kèm lý do, `/health/ready` trả 503 |
| Gói voice | chat chạy bình thường; cuộc gọi voice nhận thông báo lỗi nêu rõ gói còn thiếu |

## Bản đồ code (`src/ai_agent_service/`)

| Đường dẫn | Nội dung |
|---|---|
| `api/routes/conversations.py` | `/turns` (JSON), `/stream` (SSE); giữ nguyên contract của web |
| `api/routes/voice.py` | WebSocket voice: VAD + Smart Turn → ASR local → lượt → TTS từng câu, có barge-in |
| `api/routes/agent_calls.py` | Console nhân viên `/api/agent/calls…`: transcript, nhận handoff, trả lời (qua hard guard), FAQ, kết thúc |
| `api/routes/developer.py` | `/api/developer/…`: model advisor, trace, phiên, voice, ngày nghiệp vụ, latency p50/p95 |
| `runtime/harness.py` | dựng đồ thị + MCP, chạy lượt, tác vụ nền, after_call |
| `runtime/calls.py` | vòng đời cuộc gọi: mở theo conversation, lease, replay, kết thúc, reconcile, handoff |
| `runtime/db.py`, `runtime/vault.py` | schema `agent`, pool, checkpointer; vault PII mã hóa |
| `runtime/platform.py` | **chỗ duy nhất** chạm bảng platform |
| `pipeline/hot`, `pipeline/cold` | đồ thị 7 bước; after_call |
| `pipeline/improve` | vòng cải tiến offline: lấy lỗi từ bộ chấm, khám phá gợi ý (LATS rút gọn), đề xuất, publish |
| `agents/` | Advisor, Policy (Jev), Memory, QA, Simulator (khách của bước khám phá, không phải simulator đánh giá) |
| `components/` | intake, identity, guardrails, memory/brief, handoff, voice, clock |
| `mcp/client.py`, `mcp/servers/` | client phân quyền theo role (tự chèn `on`, `customer_phone`, bỏ trường `_internal`) và 5 server |

Thư mục ngoài `src/`:

- `config/`: `models.yaml` (agent → provider/model, rate limit), `lanes.yaml`, `situations.yaml`, `knowledge.yaml` (phiên bản tri thức, tham số truy hồi, ngưỡng θ, model embedding).
- `data/btc/`: gói của BTC gồm catalog, CRM, chính sách, `mock_tools.py`, `reference_eval.py`, test set.
- `data/kb/v<N>.jsonl`: các mục FAQ/playbook đã duyệt của từng phiên bản tri thức; `v0` chưa có mục nào.

### MCP tools

| Server | Tool |
|---|---|
| catalog | `catalog_search`, `inventory_check`, `pricing_get_quote`, `delivery_estimate` |
| crm | `crm_get_customer`, `order_create`, `schedule_callback`, `handoff_transfer` |
| order | `order_status`, `order_update` |
| memory | `identity_find`, `identity_link_provisional`, `memory_get_profile`, `memory_get_episodes`, `memory_get_open_items`, `memory_commit_*`, `memory_confirm_identity`, `memory_request_deletion`, `memory_delete_customer` |
| knowledge | `kb_search` (harness, admin), `kb_upsert` (chỉ admin) |

Catalog, CRM và order bọc `mock_tools.py` của BTC. Trạng thái mock (đơn đã tạo, lịch gọi lại, khuyến mãi đã dùng) lưu ở một dòng `mock_state` có khóa advisory, nên ba tiến trình thấy cùng một trạng thái và vẫn còn sau restart. Nhờ vậy giá, khuyến mãi, tồn kho và giới hạn COD luôn khớp với cách BTC chấm. Trên dây, tên tool dùng dấu chấm (`catalog.search`) như trong đề.

## Lưu trữ

Schema `agent` (`AGENT_DB_SCHEMA`) được tạo khi khởi động. Gồm: `calls`, `turns`, `pii_vault`, checkpoint LangGraph, và bảng của MCP server (`mock_state`, ledger, `kb_chunks`). Agent dùng `AGENT_DATABASE_URL` nếu có, nếu không thì dùng `DATABASE_URL`.

Với bảng platform, agent chỉ ghi hai thứ, đều qua `runtime/platform.py`:

- transcript khách nhìn thấy, đã che PII;
- `Handoff` do agent khởi tạo: conversation chuyển sang `handed_off`, outbox `handoff.requested`.

Agent đọc conversation để xác thực lượt và để biết conversation nào đã đóng.

### Khớp với contract của BTC (`data/btc/schemas`)

| Dữ liệu | Lưu ở | Kiểm |
|---|---|---|
| CallBrief | `calls.brief_object` (+ dòng `B1…` ở `calls.brief`) | `call_brief.schema.json`; `must_not_ask` gồm nhu cầu và các fact nghiệp vụ được bảo vệ (sản phẩm, giá đã báo, mã đơn, thanh toán, khu vực giao) |
| HandoffBrief | tham số `handoff.transfer`, `calls.handoff_brief` | kiểm bằng chính `handoff_brief.schema.json` trước khi tool chạy. Riêng chat không có số điện thoại thì được miễn yêu cầu số; hotline thì phải xin số |
| Fact ledger / `memory_writes` | bảng `facts` của MCP memory; `calls.after_call` | tên slot trùng tên BTC (`objection`, `delivery_area`, `owned_sku`, `child_age_months`, …), `op` là `set\|supersede\|delete` |
| `trace_log` | dựng lại từ `turns` + `calls` khi xuất | `trace_log.schema.json`; xem `GET /api/developer/calls/{id}/trace` |

Test `tests/agent/test_btc_contract.py` giữ các điểm trên. Mọi tên slot mà kịch bản mẫu chấm phải có trong ledger.

`data/btc/catalog/crm_seed_synthetic.json` (khách tổng hợp do `evaluation/data-generation` sinh) được nạp thêm vào CRM của mock khi khởi động, nên kịch bản sinh ra tìm được khách. File `mock_tools.py` của BTC giữ nguyên. Tắt bằng `BTC_SYNTHETIC_CRM=0`.

## Cấu hình

| Biến | Mục đích |
|---|---|
| `DATABASE_URL`, `AGENT_DATABASE_URL` | PostgreSQL; chấp nhận dạng `postgresql+psycopg://` |
| `AGENT_DB_SCHEMA` | mặc định `agent` |
| `APP_SECRET` | ≥ 32 byte ở production; sinh khóa vault PII và khóa định danh. Đổi giá trị thì vault cũ không đọc được |
| `GOOGLE_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` | provider của advisor; model chỉ được đề xuất khi có key |
| `TYPESAFE_API_KEY`, `JEV_URL` | Jev gọi thẳng TypeSafe (`POST /v1/systemone`), mặc định của `evaluators.policy` |
| `AI_GATEWAY_API_KEY` | Jev qua Vercel AI Gateway (gói miễn phí bị từ chối: phải nạp credits) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | tracing (đã che PII) và trace `agent-turn` tổng hợp mỗi lượt, tùy chọn |
| `VOICE_MODELS_DIR` | weights voice, tải một lần (image: `/app/models`, volume) |
| `EMBEDDING_MODELS_DIR` | model embedding của kho tri thức (multilingual-e5-small, 118 MB), knowledge server tự tải lần đầu (image: `/app/models/embedding`); không có mạng thì chỉ tra theo từ khóa |
| `AGENT_HOME` | nơi chứa `config/` và `data/btc` (image: `/app/agent`) |
| `AGENT_PROFILE` | `local`: các agent liệt kê trong `profiles.local` của `models.yaml` dùng `gemini-3.5-flash-lite` (key miễn phí); extractor của phần đánh giá giữ nguyên model |
| `IMPROVEMENT_DIR` | tín hiệu, round, thẻ bài học, file duyệt, sổ cải tiến (mặc định `data/improvement`, không đưa lên git) |
| `EXPLORE_DATABASE_URL` | database của bước khám phá, tên phải kết thúc bằng `_explore` (mặc định: tên app + `_explore`) |
| `PROMPTS_DIR` | prompt của agent, mặc định `config/prompts/agent` ở root repo (image: `/app/agent/prompts`) |

Đổi model hoặc provider của advisor: sửa `config/models.yaml`, hoặc chọn tạm trong Agent Console (`/developer`); lựa chọn tạm mất khi restart.

## Chạy local

```powershell
cd apps/ai-agent-service
py -3.12 -m venv .venv
.venv\Scripts\pip install -r ..\..\packages\backend-common\requirements.txt -r requirements-dev.txt
.venv\Scripts\pip install -r requirements-voice.txt     # tùy chọn: kênh voice
$env:PYTHONPATH = "src;..\..\packages\backend-common"
$env:DATABASE_URL = "postgresql://postgres:local-postgres-change-me@localhost:5432/app_db"
$env:GOOGLE_API_KEY = "..."
.venv\Scripts\uvicorn ai_agent_service.main:app --port 8400
```

Docker: `docker compose up --build ai-agent-service`. Thêm voice bằng `--build-arg WITH_VOICE=1`.

## Test và đánh giá

- `python -m pytest -q` (từ root):
  - `tests/agent/` kiểm tra lane, hard guard, PII, ITN;
  - `tests/test_agent_turns.py` kiểm tra route với agent giả lập.
- `python evaluation/rag_offline.py`: Recall@k của kho tri thức trên `data/btc/rag/qa_labeled.json`.
- Lệnh đánh giá dạng BTC, `run_eval.py` ở thư mục gốc repo: chạy agent thật trên kịch bản định dạng BTC, ghi trace, chấm bằng `reference_eval.py`, kèm bảng RAG. Cần PostgreSQL và key model; tự dùng database `<tên>_eval`. Từ thư mục gốc:

  ```powershell
  apps/ai-agent-service/.venv/Scripts/python run_eval.py --scenarios apps/ai-agent-service/data/btc/test_set/public_sample --only SAMPLE-01 --provider google_genai --model gemini-3.5-flash-lite
  ```

  `--config full --out full.jsonl` chỉ ghi một trace, đúng dạng lệnh BTC yêu cầu. Kết quả ở `apps/ai-agent-service/runs/<thời-điểm>/`: `full.jsonl`, `baseline.jsonl`, `report.json`, `table.txt`, `diagnostics.jsonl`, `errors.jsonl`, `manifest.json`, `rag/`.
- `python -m ai_agent_service.pipeline.eval.rag --calibrate`: chỉ đo truy hồi và đề xuất θ từ nửa câu hỏi dùng để dò.
- Chỉ số Chương A: `evaluation/data-generation` + `data/btc/eval/reference_eval.py`. Xem [docs/evaluation](../../docs/evaluation/README.md).

## Vòng cải tiến (Reflection)

Chạy offline trên tập học, không bao giờ trên tập kiểm. Trước tiên ghi `data/improvement/frozen.json`: danh sách id kịch bản của tập kiểm và holdout. Từ thư mục gốc repo, với `PYTHONPATH=apps/ai-agent-service/src`:

```bash
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve harvest --run apps/ai-agent-service/runs/<run> --round learn-1
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve explore --round learn-1 --limit 1
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve propose --round learn-1
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve publish --review apps/ai-agent-service/data/improvement/review/learn-1.json
```

- `harvest`: lỗi theo đúng hàm của `reference_eval.py` (TSR theo lý do, RQR theo slot, CCR, HR, guardrail), phân luồng bằng code: `behaviour` vào Reflection, `knowledge` cho Gap Loop, `product` là lỗi code phải sửa trước khi đóng băng, `review` cho người xem.
- `simulate --round R --scenarios <dir> --only <id>`: thay cho `harvest` khi muốn khách tự quyết. Chơi tập học với khách giả lập: 8 quy tắc BTC đi trước, rồi persona phản ứng đúng như prompt của nó (vẫn lăn tăn, vặn lại "chương trình gì?", bỏ đi). Ngoài lỗi của bộ chấm còn ghi `SIM.lost` (khách bỏ khi kịch bản chờ chốt/hẹn) và `SIM.challenged`.
- `measure --label r0 --scenarios <dir> --only <id> --seeds 1 2` và `compare --labels r0 r1`: đo một tập (kể cả tập kiểm) với khách giả lập, rồi so hai lần đo theo từng cuộc và seed. Đây là số chẩn đoán của simulator khám phá, không phải số chính thức.
- `explore`: mỗi lỗi hành vi, chạy lại cuộc gọi với khách giả lập, một nhánh không gợi ý để kiểm lỗi có tái hiện, rồi các nhánh mỗi nhánh một gợi ý do QaAgent đề xuất; điểm là của bộ chấm BTC cộng phản ứng của persona, nhánh chốt sớm hơn được ưu tiên. Mọi nhánh khôi phục cùng một snapshot DB, thread và vault riêng.
- `propose`: lỗi có thẻ đã kiểm từ ít nhất 3 khách khác nhau thành một mục playbook, kiểm lại trên mọi cuộc lỗi cùng mã và vài cuộc đạt, rồi ghi file duyệt.
- `publish`: chỉ mục do người (không phải agent) duyệt và không bị gắn cờ, ghi thành `data/kb/v<N+1>.jsonl`. `rollback --to N` và `revoke --chunk ID` để quay lui.

## Giới hạn (kế thừa từ agent tham chiếu)

- `components/improvement/gaps.py` (Gap Loop) và `components/evaluation/rubric.py` còn là stub; `QaAgent.score` chưa chấm rubric. Không file nào nằm trên đường chạy của một lượt.
- Truy hồi trên 60 câu có nhãn của BTC (`rag_eval`): Recall@3 91,5, Recall@5 93,2, từ chối đúng 75% câu không có đáp án và 60% câu nội bộ, không từ chối nhầm câu nào.
- WER/CER của ASR chưa có lệnh xuất `hypotheses.json`: gói BTC chưa kèm audio.
- Lệnh xóa dữ liệu khách của platform chưa xóa `pii_vault` và fact ledger của agent.
- Thay đổi runtime (model, voice, ngày nghiệp vụ) nằm trong bộ nhớ tiến trình: mỗi replica giữ giá trị riêng và mất khi restart.
