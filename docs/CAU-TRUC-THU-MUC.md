# Cấu trúc thư mục

Dự án là một cửa hàng bán lẻ có trợ lý AI tư vấn bán hàng, trả lời khách qua chat web, Zalo và cuộc gọi thoại. Mã nguồn tổ chức kiểu monorepo: mỗi service một thư mục trong `apps/`, code dùng chung trong `packages/`, phần đánh giá AI tách riêng trong `evaluation/`.

Tài liệu này chỉ liệt kê các thư mục và file quan trọng.

## Tổng quan

```text
capstone_sudocode2026/
├── apps/                 Các service chạy được (web, gateway, AI, nghiệp vụ, thoại)
├── packages/             Code dùng chung cho các service backend
├── config/prompts/       Toàn bộ prompt đưa cho model
├── contracts/            Hợp đồng giữa các service: OpenAPI, sự kiện Kafka
├── data/seed/catalog/    Dữ liệu sản phẩm demo cho trang mua hàng
├── evaluation/           Đánh giá chất lượng AI: harness chấm điểm và bộ sinh dữ liệu test
├── scripts/              Script vận hành: seed dữ liệu, tạo admin, migration, deploy, dev
├── tests/                Test tự động (pytest) cho backend và agent
├── infra/                Hạ tầng triển khai: Docker Compose cloud, Kubernetes, Terraform
├── docs/                 Tài liệu kiến trúc, AI, API, kênh, đánh giá, kế hoạch
├── notebooks/            Notebook phân tích dữ liệu BTC
├── docker-compose.yml    Chạy toàn bộ hệ thống trên máy (cộng override cho môi trường dev)
├── run_eval.py           Lệnh chấm điểm theo đúng định dạng BTC yêu cầu
├── Makefile              Lệnh tắt: dev, seed, test, eval
└── .env.example          Mẫu biến môi trường (key model, token, cấu hình kênh)
```

## `apps/`: các service

```text
apps/
├── web/                  Giao diện Next.js: trang mua hàng, khung chat, trang bán hàng, console cuộc gọi
│   ├── src/app/          Các trang (route): cửa hàng, giỏ hàng, thanh toán, đăng nhập, bán hàng, cuộc gọi
│   ├── src/components/   Thành phần giao diện: sản phẩm, khung chat, header/footer
│   ├── src/features/     Màn hình lớn: console agent, console cuộc gọi, gọi thoại, công cụ admin
│   └── e2e/              Test end-to-end bằng Playwright
├── api-gateway/          Cổng vào duy nhất: định tuyến request đến từng service
├── identity-service/     Đăng nhập nhân viên, xác minh OTP của khách, phân quyền
├── sales-service/        Cuộc trò chuyện, chuyển máy cho nhân viên, phản hồi của tư vấn viên
├── commerce-service/     Sản phẩm, báo giá, tồn kho, đơn hàng
├── ai-agent-service/     Trợ lý AI (mô tả chi tiết bên dưới)
├── asr-service/          Nhận dạng giọng nói (speech-to-text), chạy CPU hoặc GPU
└── hotline-bridge/       Cầu nối tổng đài SIP với cuộc gọi của agent
```

### `apps/ai-agent-service/`: trợ lý AI

```text
ai-agent-service/
├── config/
│   ├── models.yaml       Chọn model cho từng vai (advisor, memory, guard…), giá token, giới hạn
│   ├── lanes.yaml        Mỗi lane (khách mới, khách quen, đơn hàng…) được gọi những tool nào
│   ├── situations.yaml   Playbook xử lý tình huống đã duyệt
│   └── knowledge.yaml    Cấu hình truy hồi tri thức (ngưỡng từ chối, số đoạn)
├── data/
│   ├── btc/              Bộ dữ liệu của BTC: catalog, CRM, chính sách, RAG, ASR, bộ chấm, schema
│   └── kb/               Các phiên bản kho tri thức đã duyệt
└── src/ai_agent_service/
    ├── main.py           Khởi động service FastAPI
    ├── agents/           Các agent: advisor (tư vấn), memory (rút thông tin sau cuộc gọi), policy (kiểm chính sách)
    ├── pipeline/
    │   ├── hot/          Luồng xử lý trong cuộc gọi (LangGraph): nhận lời khách → chọn lane → trả lời
    │   ├── cold/         Việc sau cuộc gọi: ghi bộ nhớ, tóm tắt
    │   └── eval/         Lệnh chấm điểm theo định dạng BTC (gọi từ run_eval.py)
    ├── components/       Các khối chức năng: tri thức (RAG), guardrail, bộ nhớ, nhận diện khách,
    │                     chuẩn hóa đầu vào (ITN, che PII), giọng nói (ASR/TTS), chuyển máy, nén ngữ cảnh
    ├── mcp/servers/      Tool cho agent qua MCP: catalog, CRM, đơn hàng, tài khoản, tri thức, bộ nhớ
    ├── llm/              Tạo model, đếm token, giới hạn tốc độ, ngân sách, output có cấu trúc (JSON + retry)
    ├── runtime/          Quản lý cuộc gọi, kết nối DB, Zalo, xuất trace
    └── api/routes/       API: lượt hội thoại, stream, voice, kênh, công cụ dev
```

## `packages/backend-common/`: code dùng chung

```text
backend-common/
├── src/
│   ├── api/              Route và schema chung của các service nghiệp vụ
│   ├── commerce/         Logic sản phẩm, giá, đơn hàng
│   ├── identity/         Tài khoản, OTP
│   ├── memory/           Bộ nhớ làm việc của cuộc trò chuyện
│   ├── messaging/        Gửi và nhận sự kiện (Kafka hoặc worker nội bộ)
│   ├── security/         Mã hóa, token, phân quyền
│   ├── db/               Kết nối và session cơ sở dữ liệu
│   └── core/             Cấu hình, khởi động service
└── migrations/           Migration cơ sở dữ liệu
```

## `config/prompts/`: prompt

Mọi prompt đưa cho model đều nằm ở đây; code chỉ đọc file. Mỗi file được dùng ở đâu xem trong [config/prompts/README.md](../config/prompts/README.md).

```text
config/prompts/
├── agent/                Prompt của trợ lý: luật cứng, ghi chú theo lane, rút bộ nhớ, tóm tắt, gán nhãn, giọng đọc
├── evaluation/           Prompt của harness: extractor, bộ quan sát và giọng khách của simulator
└── data-generation/      Prompt sinh dữ liệu: kịch bản, hội thoại mẫu, hồ sơ khách giả lập
```

## `evaluation/`: đánh giá chất lượng AI

```text
evaluation/
├── harness/              Bộ chấm điểm agent end-to-end
│   ├── run_eval.py       Lệnh chính: preflight, chạy agent trên kịch bản, chấm, xuất báo cáo
│   ├── evaluate.py       Đo nhanh Recall@k của kho tri thức, không cần model
│   ├── eval_harness/     Lõi harness: chạy, thu trace, chấm điểm, báo cáo, ASR, RAG
│   ├── agent/            Cầu nối từ harness tới agent thật trong apps/ai-agent-service
│   ├── simulate.py       Khách giả lập phản ứng theo câu trả lời của agent
│   ├── datasets/         Các bộ dữ liệu test đã chuẩn hóa, có registry
│   ├── evaluation-contracts/  Hợp đồng chấm điểm và bản sao nguồn BTC (khóa bằng hash)
│   └── runs/             Bằng chứng từng lượt chạy (chỉ lưu local, không commit)
└── data-generation/      Bộ sinh dữ liệu test theo định dạng BTC
    ├── config/
    │   ├── personas.yaml           Persona của BTC và chỉ tiêu số kịch bản
    │   ├── personas_advanced.yaml  Persona nâng cao của nhóm (khách vô danh, bảo hành, trả hàng, giỏ hàng,
    │   │                           chuyển AI ↔ nhân viên, hỏi thông tin khách khác, prompt injection…): chỉ tiêu, cách nói, độ kiên nhẫn, prompt simulator
    │   ├── settings.yaml           Model, giới hạn gọi API, chỉ tiêu M2 (3 giờ audio, 30 khách đa kênh)
    │   └── voices.yaml             Giọng ElevenLabs theo miền, giới tính, độ tuổi
    ├── data/                       Đầu vào của BTC (chỉ đọc): catalog, CRM, chính sách, mock_tools, reference_eval, schema
    ├── src/planning/               Lập kế hoạch kịch bản; nhãn tính bằng mock_tools của BTC (call_kinds, personas, planner)
    ├── src/pipeline/               Các bước: kiểm catalog, sinh kịch bản, hội thoại mẫu, kiểm tra, judge, audio, báo cáo
    ├── src/utils/dataset.py        Quy định vị trí mọi file output, đọc/ghi kịch bản
    └── output/                     Dữ liệu sinh ra, mỗi thông tin chỉ lưu một nơi:
        ├── scenarios/              Kịch bản test, đúng định dạng mẫu của BTC
        ├── metadata/               Trường nội bộ của pipeline (khách, miền, tag, loại cuộc gọi)
        ├── call_brief/scenarios_<id>/call_<n>.json     Call Brief mong đợi của từng cuộc
        ├── handoff_brief/scenarios_<id>/call_<n>.json  Handoff Brief mong đợi (cuộc chuyển nhân viên)
        ├── tools/scenarios_<id>/call_<n>.json          Tool call của agent lý tưởng, kèm kết quả mock
        ├── trace_log/scenarios_<id>/call_<n>.jsonl     Trace của agent lý tưởng (chấm điểm tuyệt đối)
        ├── conversations/, judgments/                  Hội thoại mẫu và phán quyết judge của từng cuộc
        ├── audio/scenarios_<id>/call_<n>/turn_<k>.wav  Giọng khách từng lượt
        └── asr_test/, rag/, review/, reports/          Bộ ASR, đánh giá RAG, duyệt tay, báo cáo
```

Chi tiết các bước và từng loại output: [evaluation/data-generation/README.md](../evaluation/data-generation/README.md).

## `scripts/`: vận hành

```text
scripts/
├── seed/                 Nạp catalog, khuyến mãi, chính sách vào DB
├── migration/            Kiểm tra dataset trước khi nạp, tạo role DB
├── admin/                Tạo tài khoản admin đầu tiên
├── contracts/            Xuất OpenAPI của từng service vào contracts/
├── deployment/           Render manifest Kubernetes theo image tag
└── dev/                  Chạy/dừng stack, kiểm tra nhanh, giả lập Zalo, gọi thử hotline
```

## Các thư mục còn lại

```text
contracts/
├── api/openapi/          OpenAPI của từng service (sinh tự động)
└── kafka/                Schema sự kiện chung và danh sách topic

infra/
├── compose/              Docker Compose cho máy chủ cloud, Caddy (HTTPS)
├── kubernetes/           Manifest gốc và overlay cho local, staging, production
├── terraform/gcp/        Hạ tầng trên Google Cloud
└── livekit/              Cấu hình máy chủ thoại thời gian thực

tests/
├── agent/                Logic agent không cần model hay DB: lane, guardrail, PII, bộ nhớ, ITN, JSON output
└── test_*.py             Route, xác thực, workflow nền tảng, chuyển máy

docs/
├── ai/                   Tài liệu AI: pipeline, xử lý tình huống, thuật toán, dữ liệu, đánh giá
├── architecture/         Kiến trúc microservice, quyền sở hữu dữ liệu
├── evaluation/           Kết quả, nhật ký và ledger các lượt chạy đánh giá
├── deployment/           Hướng dẫn triển khai
├── plan/                 Backlog và mẫu kế hoạch
├── api.md, channels.md, kafka.md   API HTTP, kênh Zalo/hotline, sự kiện Kafka
└── BAN-GIAO-2026-10-24.md          Tài liệu bàn giao
```
