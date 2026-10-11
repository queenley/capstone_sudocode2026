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

1. **perceive**: chuẩn hóa văn bản (teencode, ký tự ẩn), đổi số nói thành số ("mười tám triệu" → 18.000.000đ), thay số điện thoại/CCCD/số tài khoản bằng token `<PHONE_1>`. Giá trị thật nằm trong vault mã hóa AES-GCM. Model, Jev, trace và checkpoint chỉ thấy token.
2. **load_context**: xác định khách (tier `VERIFIED` / `PROBABLE` / `AMBIGUOUS` / `UNKNOWN`) và dựng CallBrief từ fact ledger.
3. **route**: chọn lane bằng luật (bảng dưới). Lane quyết định advisor được thấy tool nào.
4. **advisor**: model trong `config/models.yaml` (mặc định Gemini) gọi tool kiểu ReAct qua MCP.
5. **guard**:
   - Hard guard kiểm tra: mọi số tiền phải có trong kết quả tool, lời khách hoặc chính sách; mã đơn chỉ đọc cho khách đã xác minh; không lộ PII thô hay giá nhập; không nhận là người; trả lời tiếng Việt và ngắn gọn.
   - Sau đó Jev (PolicyAgent) chấm theo chính sách.
   - Nếu trượt, advisor viết lại tối đa 2 lần; sau đó agent dùng câu an toàn.
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
| 3 | `CONFIRM_IDENTITY` | tier `PROBABLE` / `AMBIGUOUS` |
| 4 | `ORDER_SERVICE` | khách có đơn và đang nói về đơn |
| 5 | `OUT_OF_SCOPE` | chủ đề phải chuyển người (PB-06), ví dụ khiếu nại pháp lý |
| 6 | `CONTINUITY` | khách `VERIFIED` quay lại, đã có brief |
| 7 | `NEW` | mặc định |

Luật khớp đầu tiên thắng. Khách xin gặp nhân viên ở lane `NEW` thì advisor tự gọi `handoff.transfer`.

### Khi thiếu cấu hình

| Thiếu | Hành vi |
|---|---|
| Key của provider advisor | advisor lỗi, agent nói câu an toàn; sau hai câu như vậy, lane `HANDOFF` chuyển cho nhân viên |
| `AI_GATEWAY_API_KEY` (Jev) | bỏ qua soft guard, hard guard vẫn chạy |
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
| `agents/` | Advisor, Policy (Jev), Memory, QA |
| `components/` | intake, identity, guardrails, memory/brief, handoff, voice, clock |
| `mcp/client.py`, `mcp/servers/` | client phân quyền theo role (tự chèn `on`, `customer_phone`, bỏ trường `_internal`) và 5 server |

Thư mục ngoài `src/`:

- `config/`: `models.yaml` (agent → provider/model, rate limit), `lanes.yaml`, `situations.yaml`.
- `data/btc/`: gói của BTC gồm catalog, CRM, chính sách, `mock_tools.py`, `reference_eval.py`, test set.

### MCP tools

| Server | Tool |
|---|---|
| catalog | `catalog_search`, `inventory_check`, `pricing_get_quote` |
| crm | `crm_get_customer`, `order_create`, `schedule_callback`, `handoff_transfer` |
| order | `order_status`, `order_update` |
| memory | `identity_find`, `identity_link_provisional`, `memory_get_profile`, `memory_get_episodes`, `memory_get_open_items`, `memory_commit_*`, `memory_confirm_identity`, `memory_delete_customer` |
| knowledge | `kb_search`, `kb_upsert` (chỉ admin) |

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

`data/btc/catalog/crm_seed_synthetic.json` (khách tổng hợp do `scripts/create_data` sinh) được nạp thêm vào CRM của mock khi khởi động, nên kịch bản sinh ra tìm được khách. File `mock_tools.py` của BTC giữ nguyên. Tắt bằng `BTC_SYNTHETIC_CRM=0`.

## Cấu hình

| Biến | Mục đích |
|---|---|
| `DATABASE_URL`, `AGENT_DATABASE_URL` | PostgreSQL; chấp nhận dạng `postgresql+psycopg://` |
| `AGENT_DB_SCHEMA` | mặc định `agent` |
| `APP_SECRET` | ≥ 32 byte ở production; sinh khóa vault PII và khóa định danh. Đổi giá trị thì vault cũ không đọc được |
| `GOOGLE_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` | provider của advisor; model chỉ được đề xuất khi có key |
| `AI_GATEWAY_API_KEY` | Jev qua Vercel AI Gateway |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | tracing (đã che PII), tùy chọn |
| `MLFLOW_TRACKING_URI` | metric tổng hợp theo lượt, tùy chọn |
| `VOICE_MODELS_DIR` | weights voice, tải một lần (image: `/app/models`, volume) |
| `AGENT_HOME` | nơi chứa `config/` và `data/btc` (image: `/app/agent`) |

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
- `python -m scripts.evaluation.evaluate`: Recall@k của `kb_search` trên `data/btc/rag/qa_labeled.json`.
- Chỉ số Chương A: `scripts/create_data` + `data/btc/eval/reference_eval.py`. Xem [docs/evaluation](../../docs/evaluation/README.md).

## Giới hạn (kế thừa từ agent tham chiếu)

- `pipeline/eval/runner.py`, `components/improvement/*`, `components/evaluation/*`, `agents/simulator.py` mới là stub (`NotImplementedError`). Không file nào nằm trên đường chạy của một lượt.
- `kb_search` chỉ từ chối khi không tìm thấy gì: từ chối 0% câu không có đáp án, trong khi baseline của `scripts/create_data` từ chối 87,5%. Nên port luật `should_abstain`.
- Địa chỉ chưa được mã hóa thành token (`<ADDR_n>` đã giữ chỗ). Số điện thoại, CCCD và số tài khoản thì đã có.
- Lệnh xóa dữ liệu khách của platform chưa xóa `pii_vault` và fact ledger của agent.
- Thay đổi runtime (model, voice, ngày nghiệp vụ) nằm trong bộ nhớ tiến trình: mỗi replica giữ giá trị riêng và mất khi restart.
