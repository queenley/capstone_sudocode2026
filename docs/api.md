# HTTP API

Dành cho frontend, QA và tích hợp. Gateway (`:8000`) là entry point công khai duy nhất. Bảng dưới liệt kê route đang được đăng ký trong code.

## Gateway và OpenAPI

| Prefix | Service |
|---|---|
| `/api/catalog*`, `/api/seller/*`, `/api/admin/catalog`, `/api/admin/inventory/*`, `/api/admin/promotions` | Commerce `:8100` |
| `/api/auth/*`, `/api/customer/*`, `/api/admin/users*`, `/api/conversations/{id}/identity/*` | Identity `:8200` |
| `/api/conversations*` (còn lại), `/api/staff/*`, `/api/admin/proposals*` | Sales `:8300` |
| `/api/conversations/{id}/turns`, `/stream`, WS `/voice`; `/api/agent/*`, `/api/developer/*` | AI Agent `:8400` |
| route khác | 404 `No service owns this route` |

Mỗi service có `/docs` và `/openapi.json` trên địa chỉ nội bộ. Bản snapshot nằm ở `contracts/api/openapi/<service>.json`, sinh bằng `python -m scripts.contracts.export_contracts`. Gateway chưa gộp các OpenAPI này.

## Quy tắc chung

- JSON UTF-8. Gateway chuyển tiếp các header `Authorization`, `Content-Type`, `Accept`, `X-Request-ID`.
- Rate limit `/api/*` là 120 request/phút/IP. Nếu Redis đã cấu hình mà không truy cập được thì trả 503; không cấu hình Redis thì đếm trong tiến trình.
- Xác thực bằng `Authorization: Bearer <token>`. Có ba loại token:
  - **conversation token**: trả về khi tạo conversation, dùng cho thao tác của khách trên conversation đó;
  - **customer token**: trả về sau khi xác minh OTP;
  - **staff**: JWT HS256 hạn 8 giờ từ `/api/auth/login`, hoặc role token dev (`local-*-change-me`, chỉ dùng local).

| Role | Quyền chính |
|---|---|
| `agent` | Inbox, claim/reply/transfer; console cuộc gọi của agent |
| `admin` | Quản trị staff, catalog, tồn kho, khuyến mãi, proposal; mọi quyền staff và developer |
| `seller` | Xem và hủy order |
| `developer` | Agent Console: trace, model, voice, latency |

Mã lỗi: 401 token thiếu/sai · 403 thiếu quyền hoặc chưa xác minh · 404 không tìm thấy (kể cả token không mở được conversation) · 409 trạng thái không cho phép · 422 dữ liệu sai · 502 upstream lỗi. Thân lỗi có trường `detail`.

## Health

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Tiến trình sống. Ở AI Agent: trạng thái từng phần (database, checkpointer, MCP, agent, voice, tracing) hoặc `degraded` kèm `startup_error` |
| GET | `/health/ready` | Sẵn sàng nhận traffic. Ở gateway: kiểm tra mọi service |

## Commerce

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| GET | `/api/catalog?q=&budget=` | — | Tìm sản phẩm (`q` ≤ 200 ký tự) |
| GET | `/api/catalog/{sku_code}` | — | Chi tiết SKU |
| GET | `/api/catalog/{sku_code}/quote?quantity=1&channel=web` | — | Báo giá, `quantity` từ 1 đến 100 |
| POST | `/api/admin/catalog` | admin | Tạo sản phẩm |
| PUT | `/api/admin/inventory/{sku_code}` | admin | `{"quantity_on_hand": 120}`; không được thấp hơn lượng đã reserve (409) |
| POST | `/api/admin/promotions` | admin | Timestamp ISO-8601 có timezone, end sau start |
| GET | `/api/seller/orders` | seller/admin | 100 order gần nhất |
| POST | `/api/seller/orders/{order_id}/cancel` | seller/admin | Hủy và trả tồn kho đúng một lần |

## Identity

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/api/auth/login` | — | `{"username","password"}` → `access_token`, `role`, `username` |
| POST | `/api/conversations/{id}/identity/challenge` | conversation | `{"kind":"phone"\|"email","value","consent":true}` |
| POST | `/api/conversations/{id}/identity/verify` | conversation | `{"challenge_id","code"}` (6 chữ số) → `customer_token` |
| GET | `/api/customer/profile` · `/api/customer/orders` | customer | Hồ sơ và order |
| DELETE | `/api/customer/data` | customer | Xóa/ẩn dữ liệu cá nhân; record tài chính giữ lại đã bỏ địa chỉ |
| GET · POST | `/api/admin/users` | admin | Liệt kê / tạo staff (`username` 3–100 ký tự, `password` 12–200 ký tự) |
| DELETE | `/api/admin/users/{user_id}` | admin | Vô hiệu hóa staff |

Ở môi trường dev không có OTP provider, response `challenge` trả kèm `development_code`.

## Sales

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/api/conversations` | customer (tùy chọn) | `{"channel":"web"}` → `conversation_id`, `conversation_token` |
| GET | `/api/conversations/{id}` | conversation | Conversation và messages |
| POST | `/api/conversations/{id}/messages` | conversation | Khách nhắn khi đang nói chuyện với nhân viên |
| POST | `/api/conversations/{id}/end` | conversation | Đóng; agent sẽ chạy after_call cho cuộc gọi tương ứng |
| GET | `/api/conversations/{id}/brief` | conversation | Brief của conversation |
| POST | `/api/conversations/{id}/orders` | conversation | Tạo order: khách đã xác minh, conversation đang mở, giá khớp quote |
| POST | `/api/conversations/{id}/feedback` | conversation | `rating` 1–5, `category`, `comment` |
| GET | `/api/staff/agents`, `/api/staff/conversations[/{id}]` | agent/admin | Nhân viên và inbox |
| POST | `/api/staff/conversations/{id}/claim` · `/messages` · `/transfer` | agent/admin | Nhận, trả lời, chuyển (`to_actor_id: null` trả về AI) |
| GET · POST | `/api/admin/proposals`, `/api/admin/proposals/{id}/review` | admin | Duyệt proposal (`approved` cần `knowledge_text`) |

Các channel hợp lệ: `web`, `chat`, `call`, `hotline`, `fanpage`, `zalo`.

## AI Agent: lượt của khách

| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/api/conversations/{id}/turns` | conversation | Một lượt, trả JSON |
| POST | `/api/conversations/{id}/stream` | conversation | Cùng lượt đó, trả qua SSE |
| WS | `/api/conversations/{id}/voice` | conversation (frame đầu) | Cuộc gọi thoại |

Request:

```json
{"message": "Tư vấn giày chạy bộ dưới 2 triệu", "selected_sku": null, "memory_enabled": true, "turn_id": "c1-t3"}
```

- `message` 1–4.000 ký tự.
- `selected_sku`: sản phẩm khách đang xem; được đưa vào ngữ cảnh, không coi là lời khách nói.
- `memory_enabled: false` chạy chế độ baseline: cùng đồ thị, không dùng bộ nhớ.
- `turn_id` do client chọn. Gửi lại cùng `turn_id` sẽ nhận lại câu trả lời đã lưu (`"replayed": true`), không chạy lượt mới.

Response (`TurnResult`):

```json
{
  "reply": "Dạ, ...",
  "route": "NEW",
  "confidence": 1.0,
  "trace_id": "42:c1-t3",
  "products": [{"sku_code": "...", "name": "...", "list_price": "...", "sale_price": "...", "available": 3}],
  "stages": ["perceive", "load_context", "route", "advisor", "guard", "respond", "persist"],
  "stage_timings_ms": {},
  "tool_calls": ["catalog.search", "pricing.get_quote"],
  "signals": {"lane": "NEW", "route_rule": 7, "tier": "UNKNOWN", "guard_passed": true, "guard_reasons": [],
              "regenerations": 0, "fallback": false, "handoff_required": false, "latency": {"total_ms": 1830}}
}
```

- `route` là lane do luật chọn (`HANDOFF`, `CLARIFY`, `CONFIRM_IDENTITY`, `ORDER_SERVICE`, `OUT_OF_SCOPE`, `CONTINUITY`, `NEW`), vì vậy `confidence` luôn là 1.0.
- Mỗi lượt được ghi vào `conversation.messages` dưới dạng đã che PII.
- Khi agent chuyển cho nhân viên, platform tạo `Handoff` và conversation chuyển sang `handed_off`. Sau đó web vẫn gửi tin của khách qua `/turns`. Nếu chính agent đã chuyển máy (cuộc gọi ở chế độ copilot), agent soạn **gợi ý** cho nhân viên và không tự trả lời: response có `"waiting": true`, `reply` rỗng. Nếu Sales chuyển máy, tin nhắn chỉ được ghi lại (`route: "HUMAN"`).
- Conversation đã đóng cũng trả 409.

SSE: event `start`, rồi `: keepalive` mỗi 15 giây, rồi các event `delta {"text"}` (từng dòng của reply), cuối cùng `done` (TurnResult) hoặc `error {"status","message"}`. Reply được chia sau khi lượt đã xong, nên đây không phải token streaming. Lượt vẫn chạy tiếp nếu trình duyệt ngắt kết nối.

Voice WebSocket:

1. Frame đầu là text `{"token": "<conversation token>", "sample_rate": 48000}`.
2. Sau đó client gửi audio micro dạng binary và phát audio server gửi xuống.
3. Mã đóng: `4404` khi token sai, `4409` khi conversation không mở, `1011` khi gateway không tới được AI service.
4. Nếu server chưa cài gói voice, server gửi `{"type":"error"}` rồi đóng.

Trên web, nút **☏ Gọi cửa hàng** ở khung chat mở cuộc gọi này (`src/features/voice-call.tsx`). Trình duyệt kết nối WebSocket thẳng tới gateway, vì route handler của Next không proxy được WebSocket: dùng `NEXT_PUBLIC_VOICE_URL` (build arg của image web), mặc định `ws(s)://<host của trang>:8000`.

## AI Agent: console nhân viên (`/api/agent`, role agent/admin)

Giao diện: trang `/calls` của web (`src/features/call-console.tsx`).


| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/agent/calls?open_only=&limit=` | Danh sách cuộc gọi: lane, tier, trạng thái handoff, brief |
| GET | `/api/agent/calls/{call_id}` | Cuộc gọi, transcript và `held_by_you`; số điện thoại chỉ hiện 4 số cuối. Tin khách có thể mang `meta.handoff`: `{"role":"trigger","reason","label"}` (tin ngay trước khi chuyển máy) hoặc `{"role":"waiting","label"}` (gửi lúc chờ nhân viên), để console tô đỏ |
| POST | `/api/agent/calls/{call_id}/handoff` | `{"reason"}`: yêu cầu chuyển nhân viên |
| POST | `/api/agent/calls/{call_id}/accept` | Nhân viên nhận cuộc gọi |
| POST | `/api/agent/calls/{call_id}/reply` | `{"content","action":"used"\|"edited"\|"own","force"}`; cùng hard guard như agent, trả `warnings` nếu không `force`. Khi gửi được, câu trả lời hiện trong chat của khách (speaker `agent`) |
| POST | `/api/agent/calls/{call_id}/suggestion-feedback` | `{"thumb":"up"\|"down","reason?"}`: 👍/👎 của tư vấn viên đang giữ cuộc gọi trên gợi ý hiện tại; ghi thành tín hiệu `consultant` (`data/improvement/signals.jsonl`). 409 nếu cuộc đã kết thúc, người khác đang giữ, hoặc chưa có gợi ý |
| POST | `/api/agent/calls/{call_id}/faq` | `{"question","answer"}`: lưu FAQ vào kho tri thức của agent |
| POST | `/api/agent/calls/{call_id}/end` | Kết thúc (idempotent) và chạy after_call một lần |

## AI Agent: developer (`/api/developer`, role developer/admin)

| Method | Path | Mô tả |
|---|---|---|
| GET · PUT · DELETE | `/model` | Model của advisor `{provider, model, configured, overridden, choices}`. PUT `{"provider","model"}`; DELETE trả về giá trị trong `models.yaml` |
| POST | `/advisor` | Đổi model và `temperature` cùng lúc |
| GET | `/traces` | 100 lượt agent gần nhất: lane, guard, tool, latency, model |
| GET | `/calls/{call_id}/trace?scenario_id=&call=call_1&config=full&run_id=&format=json\|jsonl` | Một cuộc gọi đã lưu dưới dạng dòng `trace_log` của BTC (kèm lỗi so với `trace_log.schema.json` khi `json`); `jsonl` là file `reference_eval.py --trace` đọc |
| GET | `/sessions` | `{open, today, handoffs_waiting}` |
| GET · POST | `/voice`, POST `/voice/warm` | Chọn ASR, endpointing, barge-in, TTS; nạp model |
| GET · POST | `/clock` | Ngày nghiệp vụ (mặc định 2026-10-15) dùng để thử “cuộc gọi thứ 2” |
| GET | `/latency?channel=&days=` | p50/p95 của TTFT, total, TTFA, call_brief, kèm ngưỡng của BTC |

Các thay đổi runtime (model, voice, ngày) chỉ sống trong tiến trình hiện tại và mất khi restart.

## Cập nhật contract

- Schema nằm ở `packages/backend-common/src/api/schemas.py`, `src/commerce/schemas.py` và `apps/ai-agent-service/src/ai_agent_service/api/routes/`.
- Bảng định tuyến nằm ở `apps/api-gateway/src/main.py`.
- Khi đổi route, cập nhật tài liệu này và chạy lại `export_contracts`.
