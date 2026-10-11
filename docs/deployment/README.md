# Triển khai

Docker Compose dành cho máy local ([README gốc](../../README.md#chạy-nhanh-bằng-docker-compose)). Cloud dùng ba thành phần, và **không thành phần nào tự triển khai ứng dụng**:

- `infra/terraform/gcp`: GKE Autopilot private node, Cloud SQL PostgreSQL HA có backup, Memorystore Redis HA (TLS), Artifact Registry, một secret rỗng trong Secret Manager, VPC peering và Cloud NAT. **Có phát sinh chi phí.**
- `infra/kubernetes`: manifest Kustomize, overlay theo môi trường, Job migration.
- `infra/argocd`: ví dụ GitOps; phải thay repo URL trước khi dùng.

Terraform không tạo giá trị cho secret, user database, Kafka, Qdrant, ingress hay domain.

## 1. Nền tảng (Terraform)

Cần `gcloud`, Terraform ≥ 1.6, `kubectl`, Docker.

```powershell
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT
gcloud services enable cloudresourcemanager.googleapis.com
gcloud auth application-default login
Set-Location infra/terraform/gcp
terraform init
terraform plan  -var="project_id=YOUR_GCP_PROJECT" -var="region=asia-southeast1" -var="admin_cidr=YOUR_PUBLIC_IP/32"
terraform apply -var="project_id=YOUR_GCP_PROJECT" -var="region=asia-southeast1" -var="admin_cidr=YOUR_PUBLIC_IP/32"   # chỉ sau khi duyệt plan và chi phí
```

Lưu Terraform state ở remote backend có bảo vệ. Terraform tạo một database `app_db` dùng chung. Cluster và Cloud SQL bật deletion protection, nên muốn gỡ phải có quy trình riêng.

## 2. Build và push image

Gắn tag bất biến (commit SHA), không dùng `latest`.

```powershell
$Registry="asia-southeast1-docker.pkg.dev/YOUR_GCP_PROJECT/telesales"; $Tag="YOUR_GIT_SHA"
gcloud auth configure-docker asia-southeast1-docker.pkg.dev
$images = @(
  @("telesales-backend-common", "packages/backend-common/Dockerfile"),
  @("telesales-gateway",        "apps/api-gateway/Dockerfile"),
  @("telesales-commerce",       "apps/commerce-service/Dockerfile"),
  @("telesales-identity",       "apps/identity-service/Dockerfile"),
  @("telesales-sales",          "apps/sales-service/Dockerfile"),
  @("telesales-ai-agent",       "apps/ai-agent-service/Dockerfile"),
  @("telesales-web",            "apps/web/Dockerfile")
)
foreach ($i in $images) {
  docker build -f $i[1] -t "$Registry/$($i[0]):$Tag" .; if ($LASTEXITCODE) { throw "build $($i[0])" }
  docker push "$Registry/$($i[0]):$Tag";                 if ($LASTEXITCODE) { throw "push $($i[0])" }
}
```

Image AI Agent mặc định **không** có voice. Thêm `--build-arg WITH_VOICE=1` khi cần kênh gọi thoại (image lớn hơn vài trăm MB).

## 3. Cluster, secret và database

```powershell
gcloud container clusters get-credentials telesales --region asia-southeast1 --project YOUR_GCP_PROJECT
kubectl create namespace telesales-production
```

Tạo secret `telesales-secrets` trong namespace, qua Secret Manager và secret controller (không commit giá trị vào git):

| Khóa | Ghi chú |
|---|---|
| `DATABASE_URL` | role runtime `telesales_runtime` (tạo bằng `scripts/migration/provision_db_role.py` với `ADMIN_DATABASE_URL`) |
| `REDIS_URL` | TLS, cấu hình tin CA của Memorystore |
| `APP_SECRET` | ngẫu nhiên, ≥ 32 byte; AI Agent dùng để sinh khóa PII vault và khóa định danh. **Đổi giá trị này thì vault cũ không giải mã được nữa** |
| `ENCRYPTION_KEY` | khóa Fernet |
| `ADMIN_TOKEN`, `AGENT_TOKEN`, `SELLER_TOKEN`, `DEVELOPER_TOKEN` | mạnh, khác nhau, ≥ 32 ký tự |
| `GOOGLE_API_KEY` / `GROQ_API_KEY` / `NVIDIA_API_KEY` | ít nhất key của provider advisor đang dùng trong `config/models.yaml` |
| `AI_GATEWAY_API_KEY` | Jev (soft guard); thiếu thì agent chỉ chạy hard guard |
| `LANGFUSE_*`, `OTP_DELIVERY_URL`/`OTP_DELIVERY_TOKEN` | tùy chọn |

Tạo thêm `telesales-migration-secrets` với `MIGRATION_DATABASE_URL`, là credential có quyền DDL. Role runtime của AI Agent cần quyền `CREATE` trên database, hoặc schema `agent` phải được tạo sẵn với owner là role đó, vì agent tự tạo bảng khi khởi động.

Cloud SQL dùng private IP. Cấu hình TLS trong `DATABASE_URL` hoặc chạy Cloud SQL Auth Proxy; Terraform không cài proxy.

## 4. Render, migrate, rollout

```powershell
Set-Location ../../..
python scripts/deployment/render_deployment.py --environment production --registry $Registry --tag $Tag   # chỉ render
kubectl apply -f infra/kubernetes/migrate-job.yaml -n telesales-production
kubectl wait --for=condition=complete job/telesales-migrate -n telesales-production --timeout=10m
kubectl apply -f reports/generated/deployment.yaml
foreach ($d in "commerce-service","identity-service","sales-service","ai-agent-service","api-gateway","web") {
  kubectl rollout status deployment/$d -n telesales-production
}
```

Trước khi render, đổi `CORS_ORIGINS=https://example.invalid` trong `infra/kubernetes/base/kustomization.yaml` thành domain thật. Manifest đặt `AUTO_MIGRATE=false`, nên migration chỉ chạy bằng Job.

### Lưu ý riêng cho AI Agent

- **Bộ nhớ:** một pod chạy tiến trình API và 5 tiến trình con MCP. Request 1Gi, limit 3Gi; voice cần thêm khoảng 1,5Gi.
- **Ổ ghi:** root filesystem chỉ đọc. Weights voice nằm ở `/app/models` và bản ghi âm ở `/app/agent/runs`; cả hai đang mount `emptyDir`. Production nên dùng PVC cho `/app/models` để pod khởi động lại không phải tải lại.
- **Nhiều replica:** an toàn với chat, vì lease cuộc gọi và checkpoint nằm trong PostgreSQL. Tuy vậy, thay đổi runtime từ Agent Console (model, voice, ngày nghiệp vụ) chỉ áp dụng cho pod nhận request đó. Kênh voice cần sticky session ở ingress.
- **Ingress:** tắt buffering cho SSE (`/stream`), cho phép WebSocket (`/voice`), đặt timeout upstream ≥ 60 giây.

## 5. Mở ra Internet

Web và gateway đều là Service nội bộ. Hãy chọn ingress/load balancer HTTPS và domain, rồi chỉ expose web; web server gọi gateway trong cluster. Kafka production (dùng dịch vụ managed, hoặc tự vận hành có replication và backup) và Qdrant không do Terraform tạo. Trước khi đồng bộ ArgoCD, thay repo URL, image và cách nạp secret.

## OTP webhook

Backend gửi HTTPS POST có xác thực (`Authorization: Bearer OTP_DELIVERY_TOKEN`) đến `OTP_DELIVERY_URL`:

```json
{"kind":"phone","recipient":"+84901234567","code":"123456","expires_seconds":300}
```

Trả 2xx khi đã nhận gửi. Không log số người nhận hay mã. Production không trả mã trong response; dev không có provider thì có.

## Phạm vi kiểm chứng

`terraform validate` và render Kustomize chỉ kiểm cú pháp. Chúng không chứng minh quyền, quota, rollout, TLS hay chi phí. Test và Docker dùng cấu hình dev. Model thật, Jev, OTP và triển khai cloud cần một lần chạy với credential thật. Hãy áp chính sách lưu giữ dữ liệu tài chính và PII trước khi phục vụ khách thật.
