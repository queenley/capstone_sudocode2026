import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select
from src.db.session import Database
from src.db.models import Product, SKU, Inventory, Policy, Promotion
from src.commerce.schemas import ProductInput
from src.commerce.service import CatalogService
from src.core.config import Settings

DEMO = [
    {
        "name": "ASUS Vivobook 16",
        "brand": "ASUS",
        "category": "laptop",
        "sku_code": "ASUS-V16-BLACK",
        "list_price": 19000000,
        "sale_price": 17990000,
        "stock": 12,
        "variant": {"color": "black", "ram": "16GB"},
    },
    {
        "name": "Lenovo IdeaPad Slim 5",
        "brand": "Lenovo",
        "category": "laptop",
        "sku_code": "LENOVO-S5-SILVER",
        "list_price": 21000000,
        "sale_price": 19990000,
        "stock": 8,
        "variant": {"color": "silver", "ram": "16GB"},
    },
    {
        "name": "iPhone 17 Pro Max 128GB",
        "brand": "Apple",
        "category": "dien_thoai",
        "sku_code": "IP17P-128-BLACK",
        "list_price": 24990000,
        "sale_price": 22990000,
        "stock": 42,
        "variant": {"color": "black"},
    },
]


def seed(db, dataset=None):
    if dataset:
        catalog_dir = dataset / "catalog"
        rows = []
        for filename in ("catalog_skus.csv", "synthetic_sku_variants.csv"):
            path = catalog_dir / filename
            if path.exists():
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows.extend(csv.DictReader(stream))
        for row in rows:
            if db.scalar(select(SKU).where(SKU.sku_code == row["sku"])):
                continue
            product = db.scalar(
                select(Product).where(Product.external_id == row["parent_id"])
            )
            if not product:
                product = Product(
                    external_id=row["parent_id"],
                    name=row["name"],
                    brand=row["brand"],
                    category=row["domain"],
                )
                db.add(product)
                db.flush()
            sku = SKU(
                product_id=product.id,
                sku_code=row["sku"],
                variant={"color": row["color"]},
                list_price=row["list_price"],
                sale_price=row["sale_price"],
                synthetic=row["synthetic"].lower() == "true",
                source=row["source"],
            )
            db.add(sku)
            db.flush()
            db.add(
                Inventory(
                    sku_id=sku.id,
                    quantity_on_hand=int(row["stock"]),
                    reserved_quantity=0,
                )
            )
        with (dataset / "catalog/policies.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            for row in csv.DictReader(stream):
                if not db.scalar(
                    select(Policy).where(Policy.external_id == row["policy_id"])
                ):
                    db.add(
                        Policy(
                            external_id=row["policy_id"],
                            category=row["category"],
                            body=row["text"],
                            effective_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                        )
                    )
        with (dataset / "catalog/promotions.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            for row in csv.DictReader(stream):
                if not db.scalar(
                    select(Promotion).where(Promotion.external_id == row["promo_id"])
                ):
                    sku = db.scalar(select(SKU).where(SKU.sku_code == row["sku"]))
                    start = datetime.fromisoformat(row["start_date"]).replace(
                        tzinfo=timezone(timedelta(hours=7))
                    )
                    end = datetime.fromisoformat(row["end_date"]).replace(
                        tzinfo=timezone(timedelta(hours=7))
                    ) + timedelta(days=1)
                    db.add(
                        Promotion(
                            external_id=row["promo_id"],
                            sku_id=sku.id,
                            channel=row["channel"],
                            name=row["promo_id"],
                            description=row["text"],
                            promotion_type="informational",
                            value=None,
                            starts_at=start,
                            ends_at=end,
                            active=row["status"] == "active",
                            synthetic=row["synthetic"].lower() == "true",
                        )
                    )
    else:
        for row in DEMO:
            if not db.scalar(select(SKU).where(SKU.sku_code == row["sku_code"])):
                CatalogService(db).create(ProductInput(**row))
        if not db.scalar(select(Policy).where(Policy.external_id == "DEMO-WARRANTY")):
            db.add(
                Policy(
                    external_id="DEMO-WARRANTY",
                    category="bao hanh warranty",
                    body="Chính sách demo: bảo hành 12 tháng cho lỗi của nhà sản xuất. Chính sách này là dữ liệu minh họa, cần thay bằng tài liệu của cửa hàng.",
                    effective_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                )
            )
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    database = Database(Settings().database_url)
    database.migrate()
    with database.sessions() as session:
        seed(session, args.dataset)
    print(
        "Catalog seed complete; customer transcripts and gold labels were not imported into live memory."
    )


if __name__ == "__main__":
    main()
