# 06. Các quyết định thiết kế và lý do lựa chọn

Tài liệu này ghi lại các quyết định kiến trúc chính của hệ thống tư vấn bán hàng tự động, theo dạng ADR (Architecture Decision Record) rút gọn. Mỗi quyết định có bối cảnh, lý do, phương án đã cân nhắc, đánh đổi và vị trí trong mã nguồn để Ban tổ chức đối chiếu.

Phần lý do chỉ lấy từ những gì mã nguồn và docstring nói. Con số nào xuất hiện ở đây đều đi kèm tệp chứa nó. Chi tiết từng phần nằm ở các tài liệu cùng thư mục:

- Tổng quan hệ thống: [01-he-thong.md](01-he-thong.md)
- Vòng lặp harness (hot graph, guardrail): [02-vong-lap-harness.md](02-vong-lap-harness.md)
- Bộ nhớ khách hàng: [03-bo-nho.md](03-bo-nho.md)
- Tools và MCP: [04-tools.md](04-tools.md)
- Triển khai: [05-trien-khai.md](05-trien-khai.md)
- Mục lục: [00-tong-quan.md](00-tong-quan.md)

Mọi đường dẫn bên dưới tính từ gốc repo. `A/` là viết tắt của `apps/ai-agent-service/src/ai_agent_service/`.

## 1. Bảng tóm tắt

| # | Quyết định | Lý do chính | Phương án đã loại |
|---|---|---|---|
| 01 | Hot graph LangGraph 7 node với Postgres checkpointer; việc sau cuộc gọi tách sang cold path | Khách chỉ chờ phần trả lời, còn việc ghi nhớ thì không ai chờ | Ghi nhớ ngay trong lượt trả lời |
| 02 | Chọn lane bằng bảng luật thuần (pure function) | Mỗi dòng luật là một unit test; không đoán chủ đề rồi lấy mất tool của advisor | Bộ phân loại ý định bằng mô hình |
| 03 | Tools qua các MCP server, một client cho mỗi role, server kiểm tra role ở mọi lần gọi; bọc mock của BTC | Quyền được thực thi ở server; giá, tồn kho, khuyến mãi khớp với grader theo cấu trúc | Gọi hàm trực tiếp; tự viết lại logic nghiệp vụ |
| 04 | Guardrail nhiều lớp: kiểm tra trước khi ghi, hard check bằng code, soft check bằng PolicyAgent; regenerate 1 lần rồi nói câu an toàn | Hard check rẻ, tất định và chặn được phần lớn lỗi nên chạy trước | Chỉ dùng mô hình để duyệt |
| 05 | Soft guard và đọc ý định khách qua OpenAI Decisions API | Kết quả là xác suất để so ngưỡng, không phải chữ phải parse | Prompt chat model trả lời "pass/fail" |
| 06 | Stream từng câu, câu nào cũng được kiểm tra trước khi nói | Không bao giờ nói ra điều chưa kiểm tra, chỉ chậm hơn một chút | Kiểm tra cả bản nháp rồi mới nói; nói trước rồi kiểm tra sau |
| 07 | Bộ nhớ là ledger chỉ ghi thêm, viết sau cuộc gọi qua cổng bằng code | Chống đầu độc bộ nhớ; lời khách không ghi đè sự kiện nghiệp vụ | Để mô hình tự quyết ghi gì |
| 08 | Danh tính theo tầng, khóa băm HMAC; dữ liệu cá nhân được token hóa, vault AES-GCM | Số điện thoại 10 chữ số đảo ngược được từ hash thường; mô hình và trace không thấy dữ liệu thô | Băm SHA thường; gửi văn bản thô cho mô hình |
| 09 | Retrieval lai BM25 + embedding (pgvector trong Postgres), lọc hiệu lực trước top-k, ngưỡng từ chối trả lời | Bắt được câu hỏi diễn đạt khác; văn bản hết hiệu lực không lọt vào mô hình | Chỉ dùng từ khóa; Qdrant chạy riêng |
| 10 | Cải thiện không cần huấn luyện lại: Reflection sửa skill, Knowledge Gap Loop thêm FAQ, người duyệt, có phiên bản và rollback | Một cuộc gọi là một phiếu bằng chứng, chưa đủ thành luật; không agent nào vừa viết vừa duyệt | Fine-tune; tự động áp dụng bài học |
| 11 | Đánh giá bằng grader tham chiếu của BTC, chạy 2 cấu hình `full` và `baseline_no_memory` | Đúng quy trình chấm chéo của BTC; tách riêng đóng góp của bộ nhớ | Tự viết thang đo riêng |
| 12 | Mỗi role một mô hình trong `config/models.yaml`; factory không phụ thuộc provider | Đường nóng cần token đầu tiên nhanh, việc offline cần mô hình mạnh hơn; đổi mô hình chỉ cần sửa một dòng config | Một mô hình cho mọi việc; `if provider == ...` trong code |
| 13 | EKS với KEDA, scale theo tải agent và độ dài hàng đợi SQS | Agent chủ yếu chờ mô hình nên CPU không phản ánh tải | HPA theo CPU cho agent |
| 14 | Một Postgres dùng chung, mỗi domain một schema, transactional outbox, Kafka tùy chọn | Thực dụng trong giai đoạn chuyển tiếp: một CSDL để vận hành | Mỗi service một CSDL; bắt buộc có Kafka |

## 2. Nguyên tắc xuyên suốt

Các ADR bên dưới đều theo vài nguyên tắc chung, có thể thấy ngay trong code:

- **Code quyết định, mô hình đề xuất.** Lane do bảng luật chọn (ADR-02). Bộ nhớ do cổng bằng code ghi (ADR-07). Giá và số tiền do hard check đối chiếu với kết quả tool (ADR-04). Mô hình chỉ được hỏi ở chỗ cần hiểu nghĩa câu.
- **Giữ lại thay vì chỉ cấm.** Thứ gì mô hình không được nói thì mô hình không được thấy: brief dưới VERIFIED, PII đã token hóa, đoạn văn hết hiệu lực (ADR-08, ADR-09).
- **Ghi an toàn khi lặp lại.** Write tool không retry và có idempotency key. Ledger chỉ ghi thêm. Sweep sau cuộc gọi cho cùng kết quả dù message bị lặp hay bị mất (ADR-01, ADR-03, ADR-07).
- **Mọi con số nằm trong config.** Mô hình, ngưỡng retrieval và ngưỡng scale nằm trong `config/*.yaml` và overlay Kubernetes, không nằm rải rác trong code (ADR-09, ADR-12, ADR-13).

## 3. Các ADR

### ADR-01. Tách hot graph và cold path

- **Bối cảnh:** Mỗi lượt khách nói phải được trả lời nhanh. Việc trích xuất bộ nhớ và chấm QA sau cuộc gọi thì tốn thời gian nhưng không ai đứng chờ.
- **Quyết định:** Hot graph LangGraph có đúng 7 node `perceive -> load_context -> route -> advisor -> guard -> respond -> persist`, ánh xạ 1-1 với hình C.2 của đề. `guard` có cạnh điều kiện quay lại `advisor`. State mỗi cuộc gọi nằm trong `AsyncPostgresSaver`, còn graph được compile một lần và dùng chung. Khi khách gác máy, `after_call` (MemoryAgent, QaAgent) chạy ngoài graph.
- **Lý do:** Theo docstring: "Hanging up is not in the graph ... because nobody waits for it" (`A/pipeline/hot/graph.py:21-22`). Graph không giữ state theo cuộc gọi, checkpointer mới giữ (`graph.py:42-43`).
- **Phương án đã cân nhắc:** Chạy ghi nhớ đồng bộ trong lượt cuối. Cách này chỉ được giữ lại cho evaluation runner để cuộc gọi sau đọc được kết quả cuộc trước (`A/pipeline/eval/runner.py:18-19`).
- **Đánh đổi / hệ quả:** Bộ nhớ được ghi trễ. Vì vậy `runtime/jobs.py` đánh dấu `memory_status = 'pending'` trước khi gửi message, và có một sweep mỗi 60 giây để message gửi hai lần, nhận hai lần hay không gửi được đều cho cùng kết quả (`A/runtime/jobs.py:11-13,25`).
- **Bảy node và ô tương ứng trong hình C.2** (`A/pipeline/hot/graph.py:5-13`):

  | Node | Ô trong hình của đề |
  |---|---|
  | `perceive` | PERCEIVE |
  | `load_context` | RESOLVE IDENTITY, RETRIEVE |
  | `route` | cách PLAN lượt này |
  | `advisor` | PLAN, GUARDRAIL trước write tool, ACT, OBSERVE |
  | `guard` | GUARDRAIL trên câu trả lời |
  | `respond` / `persist` | ACT (câu trả lời) / PERSIST |

- **Ở đâu trong code:** `A/pipeline/hot/graph.py`, `A/pipeline/cold/after_call.py`, `A/runtime/jobs.py`, `A/runtime/db.py:26,174-205` (checkpointer).

### ADR-02. Chọn lane bằng luật, không dùng classifier

- **Bối cảnh:** Mỗi lượt cần một "lane" (HANDOFF, CLARIFY, CONFIRM_IDENTITY, CONTINUITY, NEW) để quyết định cách lập kế hoạch.
- **Quyết định:** Bảng 5 luật trong `rules.py`. Mỗi luật chỉ đọc trạng thái mà code biết chắc: số lần lỗi liên tiếp, độ tin cậy ASR, tầng danh tính, có brief hay không. Việc đọc chủ đề của lượt (đơn hàng, sản phẩm, chính sách) do advisor đảm nhận.
- **Lý do:** "Pure, so every row is a unit test" (`A/components/orchestration/rules.py:1`). Nếu chọn lane theo lời khách, một lần đoán sai sẽ lấy mất tool và lượt đó không cứu lại được (`rules.py:15-23`). `RouteInput` chỉ chứa những trường được phép đọc, nên chính chữ ký hàm là cơ chế thực thi (`rules.py:24-25`).
- **Phương án đã cân nhắc:** Phân loại ý định bằng mô hình hoặc từ khóa. Cách này bị loại vì lý do trên.
- **Đánh đổi / hệ quả:** CONTINUITY và NEW mang toàn bộ tool nghiệp vụ, nên advisor tự chọn tool. Câu an toàn không được tính là lý do chuyển người, vì guard chặn nhầm hai lần sẽ biến thành `over_escalation` (`rules.py:11-13`).
- **Ở đâu trong code:** `A/components/orchestration/rules.py`, `apps/ai-agent-service/config/lanes.yaml`.

### ADR-03. Tools qua MCP, một client mỗi role, bọc mock của BTC

- **Bối cảnh:** Advisor, harness, MemoryAgent và admin có quyền khác nhau. Đồng thời giá, tồn kho, khuyến mãi phải khớp với cách grader của BTC tính.
- **Quyết định:** Có 6 MCP server (memory, catalog, crm, order, knowledge, account) và 4 role (`advisor`, `harness`, `memory_writer`, `admin`). Mỗi role có một client riêng. Role được truyền qua biến môi trường `MCP_ROLE` khi dùng stdio, hoặc header `x-role` khi dùng HTTP. `RoleMiddleware` từ chối mọi tool không có role trong danh sách của nó. Catalogue, CRM và order bọc `eval/mock_tools.py` của BTC.
- **Lý do:** Quyền do server kiểm tra "whatever the client claims" (`A/mcp/server_base.py:6-11,96-113`). Một role chỉ khởi động những server nó được dùng (`A/mcp/client.py:62-71`). Bọc mock giúp giá và tồn kho đúng với grader "by construction rather than by care" (`A/mcp/servers/btc.py:3-6`).
- **Phương án đã cân nhắc:** Gọi hàm Python trực tiếp, hoặc tự viết lại logic nghiệp vụ. Cách thứ hai dễ lệch so với grader.
- **Đánh đổi / hệ quả:** Thêm tiến trình và độ trễ IPC. Tên tool có dấu chấm của BTC phải đổi thành gạch dưới khi truyền đi rồi đổi ngược lại (`client.py:9-17`). State của mock nằm trong một dòng Postgres, ghi dưới advisory lock, có idempotency key, và write tool không bao giờ được retry (`btc.py:25-35`).
- **Role nào khởi động server nào** (`A/mcp/client.py:64-71`). Tool `health` thì role nào cũng gọi được:

  | Server | Role được dùng |
  |---|---|
  | `memory` | cả 4 role (quyền từng tool do server kiểm tra) |
  | `catalog`, `crm`, `order` | `advisor`, `harness` |
  | `knowledge` | `harness`, `admin` |
  | `account` | `advisor` |

- **Hợp đồng lỗi chung:** mọi tool trả `{"ok": true, "data": ...}` hoặc `{"ok": false, "error": {...}}`. Kết quả nghiệp vụ như quote hết hạn được trả về dưới dạng dữ liệu để mô hình đọc và xử lý, không raise (`A/mcp/server_base.py:12-17`).
- **Ở đâu trong code:** `A/mcp/client.py`, `A/mcp/server_base.py`, `A/mcp/servers/*.py`.

### ADR-04. Guardrail nhiều lớp, hard trước soft

- **Bối cảnh:** Không câu trả lời sai giá, lộ dữ liệu cá nhân hay hành động sai nào được đến tay khách hoặc vào hệ thống nghiệp vụ.
- **Quyết định:** Có ba lớp. (1) Trước khi chạy write tool (`order.create`, `order.update`, `schedule.callback`, `handoff.transfer`, `memory.request_deletion`), harness kiểm tra tham số: giá bằng quote hôm nay, COD tối đa 10.000.000đ, Handoff Brief hợp lệ theo schema. (2) Hard check bằng code trên từng câu: PII, thuật ngữ nội bộ, tự nhận là người, giới hạn theo tầng, khuyến mãi chưa bắt đầu (KM-02), mọi số tiền phải có nguồn. (3) Soft check bằng PolicyAgent. Một bản nháp bị chặn được regenerate tối đa 1 lần, nếu vẫn bị chặn thì nói câu an toàn của lane.
- **Lý do:** "Hard before soft, because hard is cheap, deterministic and stops most of what goes wrong" (`A/components/guardrails/__init__.py:3-4`). Hard check chạy "under 50 ms" (`__init__.py:9`). Khi bị chặn, mọi lý do đều được trả về để một lần regenerate sửa hết (`A/components/guardrails/hard.py:21-22`).
- **Phương án đã cân nhắc:** Chỉ dùng mô hình để duyệt. Cách này bị loại vì đắt, không tất định, và dễ "mềm" trước lời nài nỉ của khách (xem ADR-05).
- **Đánh đổi / hệ quả:** Lỗi ở write tool được trả cho mô hình dưới dạng tool error có lý do, không có gì xảy ra trong nghiệp vụ (`A/components/guardrails/actions.py:3-5`). Lưu ý: comment trong code ghi "two regenerations", nhưng hằng số thật là `MAX_REGENERATIONS = 1` (`A/pipeline/hot/nodes.py:59-60`).
- **Thứ tự các lớp:**

  ```mermaid
  flowchart LR
    D[Advisor: bản nháp / lệnh tool] --> W{Write tool?}
    W -- có --> AC[actions.check: tham số] -->|lỗi| D
    AC -->|đạt| T[Chạy tool]
    W -- không --> H[hard.check: từng câu, bằng code]
    H -->|đạt| P[PolicyAgent: soft check]
    H -->|chặn| R{Còn lượt regenerate?}
    P -->|chặn| R
    R -- còn --> D
    R -- hết --> F[Câu an toàn của lane]
    P -->|đạt| S[Nói cho khách]
  ```

  Với câu trả lời stream, mỗi câu qua `hard.check`. PolicyAgent chỉ duyệt từng câu khi bật `ADVISOR_SENTENCE_REVIEW` (mục 4).
- **Ở đâu trong code:** `A/components/guardrails/{actions,hard,fallback}.py`, `A/agents/advisor.py:854` (gọi `actions.check`), `A/pipeline/hot/nodes.py:1452-1500` (node `guard`).

### ADR-05. Decisions API cho soft guard và đọc ý định

- **Bối cảnh:** Có những lỗi mà regex không bắt được, ví dụ hứa ngoài chính sách hay gây áp lực mà tồn kho không biện minh được. Một số hành động cũng phụ thuộc vào ý khách: muốn gặp người thật, đồng ý xóa dữ liệu, mua thêm, xác nhận danh tính.
- **Quyết định:** PolicyAgent gọi `POST /v1/decisions` (mô hình `evaluators.policy`). Mỗi câu hỏi là một predicate được trả lời độc lập bằng xác suất, và bản nháp bị chặn khi có xác suất vượt ngưỡng. PolicyAgent chỉ nhận `PolicyInput`, không nhận brief hay lịch sử hội thoại.
- **Lý do:** "the answer is a probability to threshold, not a word to parse" (`A/llm/decisions.py:3-5`). Không cho PolicyAgent xem brief để giá cũ đứng cạnh giá mới được thấy rõ (`A/agents/policy.py:7-12`). Đọc ý định thay cho danh sách từ khóa vốn đã đọc sai các câu thực tế (`policy.py:24-31`).
- **Phương án đã cân nhắc:** Prompt chat model trả lời verdict, hoặc danh sách từ khóa. Danh sách từ khóa chỉ còn là phương án dự phòng khi không có câu trả lời.
- **Đánh đổi / hệ quả:** Không retry. Quá timeout thì bản nháp qua được nhờ hard check và verdict ghi lại điều đó (`policy.py:19-22`, `decisions.py:16-19`). Timeout của `evaluators.policy` là 1.5 giây (`models.yaml:355-359`). Ngưỡng vẫn là tạm thời vì được đặt trên một mô hình khác và chưa hiệu chỉnh lại (`policy.py:15-18`).
- **Ở đâu trong code:** `A/llm/decisions.py`, `A/agents/policy.py`, `apps/ai-agent-service/config/models.yaml:355-358`.

### ADR-06. Stream từng câu, kiểm tra trước khi nói

- **Bối cảnh:** Trên kênh thoại, khoảng im lặng trước câu đầu tiên chính là độ trễ khách cảm nhận. Nhưng câu đã nói ra thì không rút lại được.
- **Quyết định:** Câu trả lời của advisor được stream rồi cắt thành câu (`SentenceSplitter`, kết thúc ở `.!?…` + khoảng trắng hoặc tối đa 200 ký tự). Câu nào cũng qua hard check trước khi được nói. Nếu một câu bị chặn sau khi các câu trước đã nói, lần regenerate sẽ tiếp tục từ những gì khách đã nghe.
- **Lý do:** Cách làm giống NeMo Guardrails với `stream_first: False`: "trading a little delay for never saying what it has not checked" (`A/components/guardrails/stream.py:3-9`).
- **Phương án đã cân nhắc:** Kiểm tra cả bản nháp rồi mới nói, an toàn hơn nhưng chậm. Nói trước rồi kiểm tra sau, nhanh hơn nhưng có thể nói điều sai.
- **Đánh đổi / hệ quả:** Với bản nháp đã stream, node `guard` không còn gì để kiểm tra (`A/pipeline/hot/nodes.py:1462-1463`). Việc PolicyAgent duyệt từng câu bị tắt mặc định (xem mục 4). Quá 3 câu thì phần còn lại không được nói, trừ khi đang đọc lại đơn hàng (`nodes.py:1048-1049`).
- **Ở đâu trong code:** `A/components/guardrails/stream.py`, `A/pipeline/hot/nodes.py:1039` (`_streamed`), `nodes.py:523-533` (`advisor`).

### ADR-07. Bộ nhớ: ledger chỉ ghi thêm, cổng ghi bằng code

- **Bối cảnh:** Bộ nhớ dài hạn có thể bị đầu độc, ví dụ người lạ gõ số điện thoại của người khác, khách nói đùa, hay khách khẳng định trái với sự kiện đã ghi.
- **Quyết định:** MemoryAgent chỉ đề xuất ứng viên. Cổng bằng code quyết định qua 4 bước: lọc nhiễu và độ tin cậy dưới 0.6, giới hạn 10 ghi chú mở, kiểm tra kiểu và khoảng hợp lý, rồi áp luật thắng theo loại slot. Ledger không bao giờ bị ghi đè hay xóa dòng: thay đổi sẽ đóng cửa sổ hiệu lực của dòng cũ và mở dòng mới. Chỉ role `memory_writer` được commit, dưới advisory lock của khách hàng.
- **Lý do:** "A joke never reaches the ledger because a model was in a good mood" (`A/components/memory/gate.py:3-4`). Với sự kiện nghiệp vụ, tool thắng. Lời khách trái ngược được giữ như lời đã nói và đánh dấu `disputed` (`gate.py:13-17`, `A/components/memory/ledger.py:10-11`). Chỉ ghi cho khách đã được cuộc gọi xác nhận. Ở trạng thái AMBIGUOUS lúc gác máy thì không ghi cho ai (`A/pipeline/cold/after_call.py:3-14`).
- **Phương án đã cân nhắc:** Để mô hình tự quyết ghi gì và ghi đè hồ sơ. Cách này bị loại vì lý do trên.
- **Đánh đổi / hệ quả:** Có thêm bảng và chỉ mục. Một partial unique index chỉ cho phép một dòng active mỗi slot, nên nếu có ghi trùng thì sẽ báo lỗi rõ ràng chứ không âm thầm (`A/mcp/servers/memory.py:24-33`). Yêu cầu quên khách (QT-06) được thực hiện bằng role `admin` và để lại tombstone (`memory.py:35-39`).
- **Ai thắng, theo loại slot** (`A/components/memory/gate.py:11-17`):

  | Loại slot | Bên thắng |
  |---|---|
  | sở thích, nhu cầu | khách, lời mới nhất thắng ("thôi anh lấy màu trắng") |
  | sự kiện nghiệp vụ | tool; lời khách trái ngược được giữ, đánh dấu `disputed` |
  | sự kiện quá khứ | bản ghi của hệ thống |

- **Ở đâu trong code:** `A/components/memory/{gate,ledger,ontology}.py`, `A/mcp/servers/memory.py`, `A/pipeline/cold/after_call.py`.

### ADR-08. Danh tính theo tầng và token hóa dữ liệu cá nhân

- **Bối cảnh:** Một số điện thoại có thể là của cả hộ gia đình. Khách có thể đọc số của người khác. Dữ liệu cá nhân không được lọt vào mô hình hay trace.
- **Quyết định:** Có 4 tầng VERIFIED / PROBABLE / AMBIGUOUS / UNKNOWN. Khóa (phone, Zalo, Facebook) được băm HMAC-SHA256 với secret trước khi tra cứu. Dưới VERIFIED, brief không được cho mô hình thấy dòng nào chứa giá, địa chỉ hay mã đơn. Ở intake, số điện thoại, CCCD và tài khoản ngân hàng được thay bằng token `<PHONE_1>`. Giá trị thật nằm trong vault, mã hóa AES-GCM bằng khóa dẫn xuất từ secret của nền tảng.
- **Lý do:** "ten digits reverse from a plain hash in seconds" (`A/components/identity/resolver.py:4-6`). Thông tin bị giữ lại "withheld here, not merely forbidden in the prompt" (`A/pipeline/hot/nodes.py:526-528`). "The models, Langfuse and the checkpoint only ever see the token" (`A/components/intake/pii.py:5-7`).
- **Phương án đã cân nhắc:** Hash thường. Chỉ cấm trong prompt. Gửi văn bản thô cho mô hình.
- **Đánh đổi / hệ quả:** Ở tầng PROBABLE hay AMBIGUOUS, agent phải hỏi một câu xác nhận trước khi nói thông tin riêng (`resolver.py:10-15`). CCCD và số tài khoản không bao giờ được đọc lại, chỉ đọc 4 số cuối (`pii.py:8-10`). Xóa khách hàng đồng nghĩa với xóa các dòng vault của họ (`pii.py:12-14`).
- **Bảng tầng** (`A/components/identity/resolver.py:10-15`):

  | Tầng | Khi nào | Hệ quả |
  |---|---|---|
  | VERIFIED | khóa từ kết nối khớp đúng một khách, hoặc đã xác nhận trong cuộc gọi | brief đầy đủ |
  | PROBABLE | khóa khách tự đọc giữa cuộc gọi khớp một khách | CONFIRM_IDENTITY: một câu hỏi, không giá, địa chỉ, mã đơn |
  | AMBIGUOUS | khóa khớp từ hai khách trở lên | không brief cho ai; CONFIRM_IDENTITY |
  | UNKNOWN | không khớp | khách mới, lane NEW |

- **Ở đâu trong code:** `A/components/identity/resolver.py:69-70` (`digest`), `A/components/intake/pii.py`, `A/runtime/vault.py:20-31`, `A/config/database.py:96-98` (`derived_key`).

### ADR-09. Retrieval lai, lọc hiệu lực trước top-k, ngưỡng từ chối

- **Bối cảnh:** Tìm theo từ khóa bỏ sót những câu hỏi không chung chữ nào với câu trả lời (`A/components/knowledge/semantic.py:3-6`). Tài liệu chính sách có văn bản hết hiệu lực. Có những câu hỏi mà đáp án đúng là "chưa có thông tin".
- **Quyết định:** Kết hợp xếp hạng BM25 và embedding (multilingual-e5-small, ONNX trên CPU) bằng Reciprocal Rank Fusion. Vector được lưu bằng **pgvector trong cùng Postgres**, nên chỉ có một CSDL phải vận hành và không cần thêm vector DB riêng. Văn bản không còn hiệu lực vào ngày liên quan bị loại trước khi lấy top-k. Hệ thống từ chối trả lời khi lý do là `restricted`, `absence`, hoặc `no_match` (cosine dưới `abstain_cosine`).
- **Lý do:** Lọc trước top-k để "its old figures cannot reach the model and a passage in force gets its place" (`A/components/knowledge/search.py:9-12`). Ngưỡng cosine không đủ để từ chối trả lời, vì câu hỏi "không trả lời được" vẫn khớp mạnh với đoạn văn chứng minh sự vắng mặt (`search.py:21-27`). Theo comment trong config: chỉ từ khóa đạt Recall@3 83 / Recall@5 88, lai đạt 91.5 / 93.2 trên `rag/qa_labeled.json` (`apps/ai-agent-service/config/knowledge.yaml:6-9`).
- **Phương án đã cân nhắc:** Chỉ dùng từ khóa. Qdrant như một vector DB riêng, đã cân nhắc rồi bỏ để không phải vận hành thêm một hệ thống. Mô hình bge-m3 nặng 2.2 GB, không vừa máy triển khai (`knowledge.yaml:25-27`).
- **Đánh đổi / hệ quả:** Thiếu mô hình embedding thì retrieval chỉ còn từ khóa, vẫn đúng nhưng không bắt được câu diễn đạt khác, và manifest sẽ ghi lại (`semantic.py:14-17`).
- **Hiện trạng:** Code hiện tính vector trong tiến trình `mcp-knowledge`, cache trên đĩa và tính cosine ngay trong tiến trình (`A/components/knowledge/semantic.py`); chuyển phần lưu và tìm vector sang pgvector là bước tiếp theo.
- **Ở đâu trong code:** `A/components/knowledge/{search,lexical,semantic,corpus}.py`, `apps/ai-agent-service/config/knowledge.yaml`.

### ADR-10. Cải thiện không cần huấn luyện lại

- **Bối cảnh:** QA chỉ nghe khoảng 2% số cuộc gọi, nên kịch bản không học được gì từ 98% còn lại (Case 4) (`A/components/improvement/__init__.py:3-5`).
- **Quyết định:** **Reflection** sửa skill của advisor, và chỉ sửa chỗ skill chưa nói phải làm gì. **Knowledge Gap Loop** biến câu trả lời của tư vấn viên cho câu hỏi chưa có đáp án thành mục FAQ. Cả hai đều do người duyệt, có phiên bản, có rollback hoặc thu hồi. Nhật ký `improvement-log.jsonl` chỉ ghi thêm.
- **Lý do:** "a lesson from one call may be true only for that customer". Một thay đổi cần cùng một bài học, trong cùng tình huống, từ nhiều khách (`improvement/__init__.py:14-16`). "No agent both writes and approves" (`A/components/improvement/review.py:8`).
- **Phương án đã cân nhắc:** Fine-tune mô hình. Tự động áp dụng bài học từ một cuộc gọi. Những lỗi mà skill đã có hướng dẫn được coi là việc của sản phẩm, không thành bài học (`improvement/__init__.py:11-12`).
- **Đánh đổi / hệ quả:** Cải thiện chậm hơn vì cần người duyệt. Trong vòng chạy bằng script (không có người), quyết định của ApprovalAgent được giữ, nhưng các cờ của bộ lọc vẫn chặn thay đổi (`review.py:13-14`).
- **Ở đâu trong code:** `A/components/improvement/*`, `A/pipeline/improve/{cli,weekly}.py`, `A/agents/{reflection,approval}.py`.

### ADR-11. Đánh giá bằng grader tham chiếu của BTC

- **Bối cảnh:** Đề yêu cầu một lệnh in ra bảng chỉ số và quy trình chấm chéo của BTC.
- **Quyết định:** `run_eval.py` ở gốc repo chuyển sang `A/pipeline/eval/cli.py`. Lệnh chạy hai cấu hình `full` và `baseline_no_memory` rồi gọi `eval/reference_eval.py` của BTC. Mỗi lần chạy dùng CSDL riêng có hậu tố `_eval`, được làm trống trước mỗi kịch bản, cùng checkpointer trong bộ nhớ.
- **Lý do:** Đúng hình thức trong README của BTC (`run_eval.py:2-6`, `A/pipeline/eval/cli.py:1-12`). Hai cấu hình chỉ khác nhau ở một công tắc `memory`, nên phần chênh lệch chính là đóng góp của bộ nhớ (`A/pipeline/eval/runner.py:21-26`).
- **Phương án đã cân nhắc:** Tự viết thang đo riêng, không so sánh được với các đội khác.
- **Đánh đổi / hệ quả:** Exit code 1 làm vô hiệu bảng số khi có lượt lỗi, lượt chưa gán nhãn hoặc dòng sai schema (`cli.py:23-26`). `--relabel` gán nhãn lại mà không chạy lại agent (`cli.py:15-18`).
- **Ở đâu trong code:** `run_eval.py`, `A/pipeline/eval/{cli,runner,report}.py`.

### ADR-12. Mô hình theo role, factory không phụ thuộc provider

- **Bối cảnh:** Advisor nằm trên đường nóng, còn QA, Reflection và Approval chạy offline.
- **Quyết định:** `config/models.yaml` gán mỗi agent một provider và một mô hình. Advisor dùng `gpt-5.6-luna` với `reasoning_effort: none`. Reflection và Approval dùng `gpt-6.1-terra`. Mọi lệnh gọi có `temperature: 0` khi mô hình nhận tham số này, và `max_retries: 0` để rate limiter thấy được mọi request. Factory dùng `init_chat_model` của LangChain.
- **Lý do:** Advisor được chọn theo thời gian ra token đầu tiên, vì "The first token decides the call's silence, so no reasoning" (`apps/ai-agent-service/config/models.yaml:85-96`). Nhờ `init_chat_model`, thêm provider chỉ là thêm một dòng config chứ không phải một nhánh code (`A/llm/factory.py:7-11,249`).
- **Phương án đã cân nhắc:** Một mô hình cho mọi việc. Chuỗi `if provider == ...`. Các mô hình bị loại sau đợt so sánh ngày 2026-09-17, kèm lý do, được ghi đầu tệp (`models.yaml:9-13`).
- **Đánh đổi / hệ quả:** Tham số nào không được đặt ở cả ba cấp `defaults`, `providers`, `agents` sẽ gây lỗi lúc khởi động (`models.yaml:42-45`).
- **Phân công hiện tại** (`apps/ai-agent-service/config/models.yaml:85-200,355-359`):

  | Role | Mô hình | `reasoning_effort` | Đường chạy |
  |---|---|---|---|
  | `advisor` | `gpt-5.6-luna` | `none` | nóng |
  | `evaluators.policy` (Decisions) | `gpt-6-luna` | - | nóng, timeout 1.5 s |
  | `memory` | `gpt-4.1-mini` | - | sau cuộc gọi |
  | `compactor` | `gpt-4.1-mini` | - | nóng, chỉ khi cuộc gọi quá 16 message |
  | `qa` | `gpt-5.6-luna` | `medium` | sau cuộc gọi, vòng cải thiện |
  | `knowledge` | `gpt-5.6-luna` | `low` | offline, không bao giờ trên đường nóng |
  | `reflection`, `approval` | `gpt-6.1-terra` | `low` | vòng cải thiện |

- **Ở đâu trong code:** `apps/ai-agent-service/config/models.yaml`, `A/llm/factory.py`, `A/llm/rate_limiter.py`.

### ADR-13. EKS, KEDA scale theo tải agent và hàng đợi SQS

- **Bối cảnh:** Agent phần lớn thời gian chỉ chờ mô hình. Một cuộc gọi thoại kéo dài vài phút.
- **Quyết định:** `ai-agent-service` dùng KEDA `metrics-api` đọc `GET /internal/load`, tức số lượt đang chạy (mục tiêu 6/pod) và số WebSocket thoại đang mở (4/pod), với 2 đến 10 replica và `cooldownPeriod: 300`. `ai-agent-worker` scale theo `aws-sqs-queue` (`queueLength: "5"`, tối thiểu 1 vì sweep chạy ở đây). Các dịch vụ HTTP không trạng thái dùng HPA theo CPU 70%.
- **Lý do:** "its CPU says nothing: it scales on the turns and voice calls in progress" (`infra/kubernetes/overlays/aws-production/scaling.yaml:1-4`). Không bao giờ scale-in nhanh hơn một cuộc gọi (`scaling.yaml:17`).
- **Phương án đã cân nhắc:** HPA theo CPU cho agent. Chạy `after_call` trong tiến trình API, cách này chỉ dùng cho local và evaluation (`A/runtime/jobs.py:3-9`).
- **Đánh đổi / hệ quả:** Mục tiêu theo pod "are first figures, not measurements" (`scaling.yaml:6-7`). Tải được cộng dồn qua Valkey (`A/runtime/load.py`).
- **Tóm tắt cấu hình scale:**

  | Workload | Cơ chế | Tín hiệu | Replica |
  |---|---|---|---|
  | `ai-agent-service` | KEDA `metrics-api` | `turns` 6/pod, `calls` 4/pod | 2-10 |
  | `ai-agent-worker` | KEDA `aws-sqs-queue` | 5 message/replica, tính cả in-flight | 1-6 |
  | `mcp-servers`, `api-gateway`, `web` | HPA | CPU 70% | 2-6 |
  | `commerce-service`, `identity-service`, `sales-service` | HPA | CPU 70% | 2-4 |

- **Ở đâu trong code:** `infra/kubernetes/overlays/aws-production/{scaling,kustomization}.yaml`, `infra/kubernetes/overlays/production/after-call-worker.yaml:62-88`.

### ADR-14. Postgres dùng chung, schema theo domain, transactional outbox

- **Bối cảnh:** Có nhiều service (commerce, identity, sales, ai-agent), nhưng đội ngũ nhỏ và thời gian có hạn.
- **Quyết định:** Dùng một Postgres với các schema `commerce`, `identity`, `conversation`, `memory`, `improvement`. Agent có schema riêng qua `search_path`. Sự kiện miền được ghi vào bảng `outbox` trong cùng transaction. Worker lấy tối đa 20 dòng mỗi tick bằng `FOR UPDATE SKIP LOCKED`, và chỉ publish lên Kafka khi `KAFKA_BROKERS` được đặt, nếu không thì xử lý ngay tại chỗ.
- **Lý do:** Đây là lựa chọn chuyển tiếp mang tính thực dụng: một CSDL để vận hành, trong khi outbox giữ ranh giới sự kiện để sau này tách ra. Code tự gọi phần này là "Transitional" (`A/runtime/platform.py:3-5`).
- **Phương án đã cân nhắc:** Mỗi service một CSDL. Bắt buộc có Kafka.
- **Đánh đổi / hệ quả:** Ranh giới giữa các domain chỉ được giữ bằng quy ước chứ chưa bằng hạ tầng (xem mục 4).
- **Ở đâu trong code:** `packages/backend-common/src/db/models.py:316-318` (`Outbox`), `packages/backend-common/src/messaging/worker.py:23-48,82-135,143`, `A/runtime/db.py:6-7`.

## 4. Giới hạn hiện tại và hướng tới

Các giới hạn dưới đây đều đã được đối chiếu với code:

1. **Một CSDL dùng chung, agent ghi xuyên schema.** `A/runtime/platform.py` tự mô tả là "Transitional". Agent ghi bản sao hiển thị của từng lượt vào `conversation.messages`, ghi `Handoff`, và chuyển hội thoại sang `handed_off` (`platform.py:3-15`). `runtime/shop_orders.py` cũng ghi đơn vào `commerce.orders` (`shop_orders.py:10-11`). Hướng tới: Sales cung cấp API hoặc sự kiện cho các thao tác này ("Until Sales exposes these as APIs/events").
2. **Kafka là tùy chọn và chưa được triển khai.** Không có `KAFKA_BROKERS` thì worker chỉ poll outbox mỗi giây và xử lý tại chỗ (`packages/backend-common/src/messaging/worker.py:143,189`). Kafka chỉ có trong profile `async` của `docker-compose.yml:340-341`, và không xuất hiện trong `infra/kubernetes`.
3. **Facebook Messenger mới chỉ là nhãn kênh.** `facebook` có trong kiểu `Channel` (`A/pipeline/hot/state.py:41`) và trong ánh xạ kịch bản đánh giá (`A/pipeline/eval/scenarios.py:37`). Tuy vậy chỉ có webhook Zalo (`A/api/routes/channels.py:1-7,26`), và `/api/channels/status` chỉ liệt kê `web`, `zalo`, `hotline` (`channels.py:46-55`).
4. **Hotline thoại (LiveKit SIP + `apps/hotline-bridge`) chỉ chạy qua docker-compose.** Các service `livekit`, `livekit-sip`, `hotline-bridge` nằm trong profile `hotline` (`docker-compose.yml:358-393`), và không có manifest tương ứng trong `infra/kubernetes`.
5. **Dữ liệu thương mại của agent đến từ mock của BTC, không qua API của commerce-service.** Giá, khuyến mãi, mã đơn và ngày giao do mock quyết định, vì guardrail và grader đọc state đó. `SHOP_ORDERS=1` chỉ là cầu nối phản chiếu đơn sang website (`A/runtime/shop_orders.py:1-17`).
6. **PolicyAgent duyệt từng câu bị tắt mặc định** (`ADVISOR_SENTENCE_REVIEW`, `A/mcp/tools.py:803-805`). Lý do ghi trong code: tắt từ 2026-11-25 vì không chỉ số nào của BTC đọc nó, các cờ của nó lại gây sửa câu hoặc từ chối ghi, còn hard guard vẫn giữ những gì được chấm (PII, tự nhận là người, giá, KM-02) (`A/pipeline/hot/nodes.py:1281-1284`). Hệ quả: trên câu trả lời stream, mỗi câu chỉ qua hard check. PolicyAgent vẫn duyệt bản nháp nguyên khối trong node `guard` và vẫn đọc ý định trước các write tool.
7. **Ngưỡng của PolicyAgent là tạm thời** cho tới khi có ví dụ gán nhãn từ chính ứng dụng (`A/agents/policy.py:15-18`). Ngưỡng tải KEDA cũng vậy (`scaling.yaml:6-7`).
