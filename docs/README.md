# Tài liệu dự án

| Tài liệu | Nội dung | Dành cho |
|---|---|---|
| [HTTP API](api.md) | Định tuyến gateway, xác thực, toàn bộ endpoint (kể cả agent, voice WebSocket) | frontend, QA, tích hợp |
| [Tài liệu AI](ai/README.md) | Pipeline, xử lý tình huống, thuật toán, dữ liệu, đánh giá (bản dễ đọc) | mọi người, người mới |
| [Kế hoạch cải tiến](plan/README.md) | Thêm skill cho agent ở đâu, mẫu đề xuất, backlog | người cải tiến agent |
| [AI Agent](../apps/ai-agent-service/README.md) | Đồ thị 7 bước, lane, guard, MCP tools, lưu trữ, cấu hình | người phát triển agent |
| [Kiến trúc microservice](architecture/microservices-target-structure.md) | Ranh giới service, luồng request/event, cấu trúc đích | mọi người |
| [Sở hữu dữ liệu](architecture/data-ownership-migration.md) | Bảng thuộc service nào, phụ thuộc chéo, trình tự tách DB | backend |
| [Schema & dataset](architecture/competition-schema.md) | Migration `0001`, ánh xạ dataset BTC, bất biến nghiệp vụ | backend, data |
| [Kafka](kafka.md) | Topic, envelope, outbox relay, consumer | backend, vận hành |
| [Đánh giá](evaluation/README.md) | Test, Recall@k, chỉ số Chương A với `reference_eval.py` | cả nhóm |
| [Triển khai](deployment/README.md) | Compose, GCP/Terraform, Kubernetes, secret, rollout | vận hành |

Tài liệu mô tả code hiện tại. Thư mục `domain/`, `application/` và `infrastructure/` trong mỗi service là ranh giới đích; việc thư mục đã tồn tại không có nghĩa service đã độc lập.
