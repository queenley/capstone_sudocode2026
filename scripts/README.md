# Scripts

Chạy từ root repo, trừ `create_data/` (có venv và README riêng).

| Thư mục | Việc | Lệnh |
|---|---|---|
| `seed/` | Nạp catalog, SKU variant, chính sách, khuyến mãi vào DB platform. Không nạp transcript hay khách | `python -m scripts.seed.catalog --dataset <dataset>` |
| `migration/` | Kiểm tra dataset trước khi nạp (chỉ đọc); tạo role DB runtime | `python scripts/migration/validate_dataset.py <dataset>` · `python scripts/migration/provision_db_role.py` |
| `admin/` | Tạo tài khoản admin đầu tiên | `python scripts/admin/create_admin.py` |
| `evaluation/` | Recall@k của retriever agent, chấm bằng `rag_eval` của BTC → `reports/generated/evaluation.json` | `python -m scripts.evaluation.evaluate` |
| `create_data/` | Sinh kịch bản test theo format BTC, ground truth, audio, bộ ASR, đánh giá RAG/ASR | xem [create_data/README.md](create_data/README.md) |
| `contracts/` | Xuất OpenAPI từng service → `contracts/api/openapi/<service>.json` | `python -m scripts.contracts.export_contracts` |
| `deployment/` | Render manifest Kubernetes theo image tag (không apply) | `python scripts/deployment/render_deployment.py --help` |
| `dev/` | PowerShell chạy/dừng stack và kiểm tra nhanh | `scripts/dev/dev.ps1`, `scripts/dev/check.ps1` |

Compose seed từ `data/seed/catalog/` (`catalog_skus.csv` + `synthetic_sku_variants.csv`). Catalog demo này dùng cho trang mua hàng. Agent lấy giá, tồn kho và khuyến mãi từ dữ liệu BTC trong `apps/ai-agent-service/data/btc`, vì BTC chấm điểm theo dữ liệu đó.
