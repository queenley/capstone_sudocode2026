# Scripts

Script vận hành platform, chạy từ root repo. Đánh giá AI (harness chấm điểm, sinh dữ liệu test) nằm ở [`evaluation/`](../evaluation/README.md).

| Thư mục | Việc | Lệnh |
|---|---|---|
| `seed/` | Nạp catalog, SKU variant, chính sách, khuyến mãi vào DB platform. Không nạp transcript hay khách | `python -m scripts.seed.catalog --dataset <dataset>` |
| `migration/` | Kiểm tra dataset trước khi nạp (chỉ đọc); tạo role DB runtime | `python scripts/migration/validate_dataset.py <dataset>` · `python scripts/migration/provision_db_role.py` |
| `admin/` | Tạo tài khoản admin đầu tiên | `python scripts/admin/create_admin.py` |
| `contracts/` | Xuất OpenAPI từng service → `contracts/api/openapi/<service>.json` | `python -m scripts.contracts.export_contracts` |
| `deployment/` | Render manifest Kubernetes theo image tag (không apply) | `python scripts/deployment/render_deployment.py --help` |
| `dev/` | PowerShell chạy/dừng stack và kiểm tra nhanh | `scripts/dev/dev.ps1`, `scripts/dev/check.ps1` |

Compose seed từ `data/seed/catalog/` (`catalog_skus.csv` + `synthetic_sku_variants.csv`). Catalog demo này dùng cho trang mua hàng. Agent lấy giá, tồn kho và khuyến mãi từ dữ liệu BTC trong `apps/ai-agent-service/data/btc`, vì BTC chấm điểm theo dữ liệu đó.
