import argparse
import json
from pathlib import Path

from src.schemas.catalog import CustomerCatalog, InventoryTimeline, ProductCatalog, PromotionCatalog


def load_catalog(path: Path) -> ProductCatalog:
    with path.open(encoding="utf-8-sig") as stream:
        return ProductCatalog.model_validate_json(stream.read())


def main():
    parser = argparse.ArgumentParser(description="Validate the source product catalog")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data/catalog/products.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write normalized, validated JSON",
    )
    args = parser.parse_args()
    catalog = load_catalog(args.input)
    source_dir = args.input.parent
    promotion_path = source_dir / "promotions.json"
    inventory_path = source_dir / "inventory_timeline.json"
    customer_path = source_dir / "crm_seed.json"
    promotions = None
    inventory = None
    customers = None
    if promotion_path.exists():
        promotions = PromotionCatalog.model_validate_json(
            promotion_path.read_text(encoding="utf-8-sig")
        )
    if inventory_path.exists():
        inventory = InventoryTimeline.model_validate_json(
            inventory_path.read_text(encoding="utf-8-sig")
        )
    if customer_path.exists():
        customers = CustomerCatalog.model_validate_json(customer_path.read_text(encoding="utf-8-sig"))
    synthetic_customers=source_dir / "crm_seed_synthetic.json"
    if synthetic_customers.exists():
        synthetic=CustomerCatalog.model_validate_json(synthetic_customers.read_text(encoding="utf-8-sig"))
        source_customers=customers.customers if customers else []
        source_ids={c.customer_id for c in source_customers}
        source_phones={c.phone for c in source_customers}
        duplicate_ids=[c.customer_id for c in synthetic.customers if c.customer_id in source_ids]
        duplicate_phones=[c.phone for c in synthetic.customers if c.phone in source_phones]
        if duplicate_ids or duplicate_phones:
            raise ValueError(f"Synthetic CRM collides with source IDs/phones: ids={duplicate_ids}, phones={duplicate_phones}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    variant_count = sum(len(product.variants) for product in catalog.products)
    summary = (
        f"Validated {len(catalog.products)} products and {variant_count} variants "
        f"(reference date {catalog.reference_date}, currency {catalog.currency})"
    )
    if promotions is not None:
        summary += f", {len(promotions.promotions)} promotions"
    if inventory is not None:
        summary += f", {len(inventory.events)} inventory events"
    if customers is not None:
        summary += f", {len(customers.customers)} CRM seed customers"
    print(summary + ".")


if __name__ == "__main__":
    main()
