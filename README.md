# capstone_sudocode2026
=======
# Tiếp Nối — SUDO CODE 2026

Nền tảng telesales có AI agent tư vấn bán hàng qua chat và cuộc gọi. Agent nhớ khách giữa các cuộc gọi (CallBrief), tra giá, tồn kho và chính sách bằng tool, tự kiểm tra câu trả lời trước khi nói, và chuyển cho nhân viên khi cần.

Hệ thống gồm giao diện Next.js, API Gateway và bốn service FastAPI (Commerce, Identity, Sales, AI Agent). Các service dùng chung PostgreSQL, có thêm Redis và Kafka (tùy chọn).

> **Trạng thái:** đây là giai đoạn chuyển tiếp. Mỗi service chạy thành tiến trình riêng nhưng vẫn dùng chung database, outbox và code trong `packages/backend-common`. Riêng AI Agent đã có schema `agent` của mình. Xem [kế hoạch sở hữu dữ liệu](docs/architecture/data-ownership-migration.md) trước khi tách database.

## Kiến trúc

```mermaid
flowchart LR
    B[Trình duyệt<br/>khách · nhân viên · admin] --> WEB[web :3000<br/>Next.js]
    WEB --> GW[api-gateway :8000<br/>CORS · rate limit · proxy · WS voice]
    GW --> ID[identity :8200]
    GW --> SA[sales :8300]
    GW --> CO[commerce :8100]
    GW --> AI[ai-agent :8400]
    AI <-->|stdio MCP| MCP[5 MCP servers<br/>catalog · crm · order · memory · knowledge]
    ID & SA & CO & AI --> PG[(PostgreSQL<br/>schema domain + schema agent)]
    ID & SA & CO --> R[(Redis)]
    PG -.outbox.-> W[event workers] -.-> K[(Kafka, tùy chọn)]
    AI -.-> LLM[Gemini / Groq / NVIDIA<br/>Jev qua AI Gateway]
```

| Thành phần | Trách nhiệm | Cổng |
|---|---|---:|
| `apps/web` | Trang mua hàng + chat + gọi thoại, workspace nhân viên/admin/seller, console cuộc gọi của agent (`/calls`), Agent Console (`/developer`) | 3000 |
| `apps/api-gateway` | CORS, rate limit 120 req/phút/IP, định tuyến HTTP, relay WebSocket voice | 8000 |
| `apps/identity-service` | Đăng nhập staff, xác minh khách (OTP), dữ liệu cá nhân | 8200 |
| `apps/sales-service` | Conversation, inbox nhân viên, handoff, feedback, proposal | 8300 |
| `apps/commerce-service` | Catalog/SKU, báo giá, tồn kho, khuyến mãi, order | 8100 |
| `apps/ai-agent-service` | Lượt chat/stream/voice của agent, console cuộc gọi, developer API | 8400 |
| PostgreSQL / Redis / Kafka | Dữ liệu giao dịch / rate limit + working state / domain events | 5432 / 6379 / 9092 |

Lượt chat của khách đi theo đường: trình duyệt → gateway → AI Agent → đồ thị 7 bước (`perceive → load_context → route → advisor → guard → respond → persist`). Agent hoạt động mà không cần Kafka. Chi tiết agent xem [apps/ai-agent-service/README.md](apps/ai-agent-service/README.md).

## Cấu trúc repo

```text
apps/
  web/                    Next.js
  api-gateway/            gateway công khai (src/main.py: bảng định tuyến)
  identity-service/  sales-service/  commerce-service/
                          FastAPI; còn import handler/persistence từ backend-common
  ai-agent-service/       agent telesales: config/, data/btc/, src/ai_agent_service/
packages/backend-common/  models, migrations, security, handler dùng chung (chuyển tiếp)
contracts/                OpenAPI theo service, Kafka envelope/topics
data/seed/catalog/        catalog demo được seed vào Compose
infra/                    kubernetes/ (Kustomize), terraform/gcp/, argocd/
scripts/                  seed, migration, evaluation, contracts, deployment, dev,
                          create_data/ (sinh dữ liệu kiểm thử theo format BTC)
tests/                    pytest: workflow nền tảng, route agent, tests/agent/ (logic agent)
notebooks/                phân tích dữ liệu BTC
docs/                     tài liệu (xem docs/README.md)
```

## Chạy nhanh bằng Docker Compose

Yêu cầu Docker Desktop (Linux containers).

```powershell
Copy-Item .env.example .env
# Điền ít nhất một key model cho agent: GOOGLE_API_KEY (mặc định advisor dùng Gemini).
# AI_GATEWAY_API_KEY bật soft guard Jev; thiếu thì agent chỉ chạy hard guard.
docker compose up --build -d
docker compose run --rm identity-service python /app/scripts/admin/create_admin.py
```

- Ứng dụng: `http://localhost:3000`. Đăng nhập staff ở `/login`.
- Health: `http://localhost:8000/health` và `/health/ready` (gateway kiểm tra mọi service).
- Log: `docker compose logs -f ai-agent-service api-gateway`.

Compose chờ PostgreSQL/Redis, chạy `seed` (migration + catalog demo) rồi mới bật các service. Dữ liệu nằm trong volume `postgres-data`. Weights voice nằm trong volume `voice-models`. Lệnh `docker compose down` giữ dữ liệu; `down -v` xóa sạch.

Khi thiếu key model, agent vẫn trả lời bằng câu an toàn và sau hai câu như vậy sẽ chuyển cho nhân viên. Để bật kênh gọi thoại, build image với `--build-arg WITH_VOICE=1`.

### Profile tùy chọn

| Profile | Bật | Ghi chú |
|---|---|---|
| `async` | Kafka + event workers | đặt `KAFKA_BROKERS=kafka:9092` trong `.env` |
| `tracking` | MLflow `:5000` | đặt `MLFLOW_TRACKING_URI=http://mlflow:5000`; mỗi lượt agent ghi một run (lane, model, tool, latency), không ghi prompt hay PII |
| `retrieval` | Qdrant | agent hiện **không** dùng Qdrant: tra chính sách bằng BM25 trên `data/btc/policy` |

```powershell
docker compose --profile async --profile tracking up --build -d
```

## Phát triển

Frontend với hot reload, backend chạy trong Compose:

```powershell
docker compose up -d postgres redis seed commerce-service identity-service sales-service ai-agent-service api-gateway
Set-Location apps/web; npm ci; npm run dev
```

Chạy Python trực tiếp (Python 3.12). Các service dùng namespace `src` của backend-common, nên cần đặt `PYTHONPATH`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r apps/api-gateway/requirements.txt
$env:DATABASE_URL="postgresql+psycopg://postgres:local-postgres-change-me@localhost:5432/app_db"

# Commerce (đổi thư mục/cổng cho identity 8200, sales 8300)
$env:PYTHONPATH="$PWD/packages/backend-common;$PWD/apps/commerce-service/src"
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir apps/commerce-service/src --port 8100

# AI Agent
$env:PYTHONPATH="$PWD/packages/backend-common;$PWD/apps/ai-agent-service/src"
.\.venv\Scripts\python.exe -m uvicorn ai_agent_service.main:app --port 8400

# Gateway
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir apps/api-gateway/src --port 8000
```

Khi chạy ngoài Compose, đổi hostname `postgres`/`redis` thành `localhost`.

## Kiểm tra và đánh giá

```powershell
.\.venv\Scripts\python.exe -m pytest -q                      # 64 test, không cần DB hay model
.\.venv\Scripts\python.exe -m scripts.evaluation.evaluate    # Recall@k của retriever agent (rag_eval của BTC)
Set-Location apps/web; npm run typecheck; npm run build
```

Các chỉ số bắt buộc của Chương A (CCR, RQR, TSR, HR, over-escalation) được chấm bằng `reference_eval.py` của BTC trên dữ liệu do `scripts/create_data` sinh. Xem [docs/evaluation](docs/evaluation/README.md).

Test PostgreSQL dùng database riêng `telesales_test` qua `TEST_DATABASE_URL`, không trỏ vào database thật. Playwright: `npx playwright install chromium` rồi `npx playwright test` khi ứng dụng đang chạy.

## Biến môi trường

Bắt đầu từ [.env.example](.env.example).

| Nhóm | Biến |
|---|---|
| Nền tảng | `DATABASE_URL`, `REDIS_URL`, `APP_SECRET`, `ENCRYPTION_KEY`, `ENVIRONMENT`, `CORS_ORIGINS` |
| Role token (dev) | `ADMIN_TOKEN`, `AGENT_TOKEN`, `SELLER_TOKEN`, `DEVELOPER_TOKEN` |
| AI Agent | `GOOGLE_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `AI_GATEWAY_API_KEY`, `AGENT_DB_SCHEMA`, `LANGFUSE_*`, `MLFLOW_TRACKING_URI` |
| Khác | `OTP_DELIVERY_URL`/`OTP_DELIVERY_TOKEN`, `KAFKA_BROKERS`, `QDRANT_URL`, embedding |

Model của từng agent được khai báo trong [`apps/ai-agent-service/config/models.yaml`](apps/ai-agent-service/config/models.yaml), không qua biến môi trường. Token demo và mật khẩu trong `.env.example` chỉ dùng cho máy local. Production yêu cầu `APP_SECRET` dài ít nhất 32 byte, `ENCRYPTION_KEY`, các role token mạnh và khác nhau, và `REDIS_URL`.

## Triển khai

Repo có Terraform (GCP: GKE Autopilot, Cloud SQL, Memorystore, Artifact Registry), manifest Kustomize và ví dụ ArgoCD. Các công cụ này **không tự triển khai ứng dụng** và có phát sinh chi phí. Từng bước (build image, secret, migration, rollout) xem [docs/deployment](docs/deployment/README.md).

## Tài liệu

- [Mục lục docs](docs/README.md): [HTTP API](docs/api.md), [kiến trúc](docs/architecture/microservices-target-structure.md), [Kafka](docs/kafka.md), [đánh giá](docs/evaluation/README.md), [triển khai](docs/deployment/README.md)
- [AI Agent](apps/ai-agent-service/README.md) · [backend-common](packages/backend-common/README.md) · [scripts](scripts/README.md) · [sinh dữ liệu test](scripts/create_data/README.md)

## Giới hạn hiện tại

- Các service vẫn dùng chung database và outbox. Việc tách cần API/event contract và saga cho order và xóa dữ liệu ([kế hoạch](docs/architecture/data-ownership-migration.md)).
- Agent: retriever chính sách chưa biết từ chối khi không có tài liệu; địa chỉ chưa được mã hóa PII; eval runner và vòng cải tiến (playbook, FAQ gap) mới là stub. Xem mục *Giới hạn* trong [README agent](apps/ai-agent-service/README.md).
- CI chưa build, scan và push image; chưa có ingress/TLS tự động.
