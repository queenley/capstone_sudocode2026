# Tài liệu dự án

| Tài liệu | Nội dung | Dành cho |
|---|---|---|
| [HTTP API](api.md) | Định tuyến gateway, xác thực, toàn bộ endpoint (kể cả agent, voice WebSocket) | frontend, QA, tích hợp |
| [Tài liệu AI](ai/README.md) | Pipeline, xử lý tình huống, thuật toán, dữ liệu, đánh giá (bản dễ đọc) | mọi người, người mới |
| [Kế hoạch cải tiến](plan/README.md) | Thêm skill cho agent ở đâu, mẫu đề xuất, backlog | người cải tiến agent |
| [Kịch bản demo](kich-ban-demo.md) | 15 cảnh: đăng ký, tư vấn, chốt đơn, giao hàng, hỏi đơn trên web và Zalo, đổi size, chính sách cũ, thoại, chuyển nhân viên có copilot, admin (chỉ số, GapLoop, Reflection, skills), Langfuse | người trình bày demo |
| [AI Agent](../apps/ai-agent-service/README.md) | Đồ thị 7 bước, lane, guard, MCP tools, lưu trữ, cấu hình | người phát triển agent |
| [Kiến trúc microservice](architecture/microservices-target-structure.md) | Ranh giới service, luồng request/event, cấu trúc đích | mọi người |
| [Sở hữu dữ liệu](architecture/data-ownership-migration.md) | Bảng thuộc service nào, phụ thuộc chéo, trình tự tách DB | backend |
| [Schema & dataset](architecture/competition-schema.md) | Migration `0001`, ánh xạ dataset BTC, bất biến nghiệp vụ | backend, data |
| [Kafka](kafka.md) | Topic, envelope, outbox relay, consumer | backend, vận hành |
| [Đánh giá](evaluation/README.md) | Test, Recall@k, chỉ số Chương A với `reference_eval.py` | cả nhóm |
| [Triển khai](deployment/README.md) | Compose, GCP/Terraform, Kubernetes, secret, rollout | vận hành |
| [Kế hoạch AWS](deployment/aws-plan.md) | Thiết kế (có code, chưa apply trên AWS thật): EC2 + Compose, rồi bản gọn ALB + 2 EC2 + RDS + EFS (không EKS, WAF, NAT); khi nào nâng lên EKS; điểm riêng của AI Agent | vận hành |
| [Kiến trúc EKS](deployment/eks-architecture.md) | Hệ thống đang chạy tại `quivo.io.vn`: một sơ đồ gồm CI/CD, workload, dữ liệu và theo dõi; từng Deployment scale theo gì; hạ tầng AWS (Free plan); Valkey dùng vào việc gì; bảo mật đã có và chưa có; chi phí; việc còn lại | vận hành |
| [Deploy lên EKS và tắt hệ thống](deployment/eks-deploy.md) | Từng bước: Terraform `aws-eks`, secret, image, render, migrate, rollout, DNS; tắt theo ba mức (tạm dừng, xóa cluster giữ dữ liệu, xóa hết) | vận hành |
| [CI/CD cho EKS](deployment/eks-cicd.md) | GitHub Actions: workflow kiểm tra và phát hành, cấu hình environment, variables và role OIDC (không cần secret trong GitHub), phát hành và quay lui | vận hành |
| [AWS: Terraform và CI/CD](deployment/aws-terraform-cicd.md) | Dựng hạ tầng AWS bằng Terraform, cấu hình GitHub OIDC, phát hành và quay lui bằng GitHub Actions, bật vòng cải tiến hằng tuần | vận hành |

Tài liệu mô tả code hiện tại. Thư mục `domain/`, `application/` và `infrastructure/` trong mỗi service là ranh giới đích; việc thư mục đã tồn tại không có nghĩa service đã độc lập.
