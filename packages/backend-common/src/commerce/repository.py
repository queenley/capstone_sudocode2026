from sqlalchemy import select, or_
from src.db.models import Product, SKU, Inventory, Promotion, now


class CatalogRepository:
    def __init__(self, db):
        self.db = db

    def search(self, query="", budget=None):
        stmt = (
            select(Product, SKU, Inventory)
            .join(SKU, SKU.product_id == Product.id)
            .join(Inventory, Inventory.sku_id == SKU.id)
            .where(Product.active.is_(True), SKU.active.is_(True))
        )
        if query:
            escaped = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = "%" + escaped + "%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(pattern, escape="\\"),
                    Product.category.ilike(pattern, escape="\\"),
                    SKU.sku_code.ilike(pattern, escape="\\"),
                )
            )
        if budget is not None:
            stmt = stmt.where(SKU.sale_price <= budget)
        return self.db.execute(
            stmt.order_by(Product.name, SKU.sku_code).limit(50)
        ).all()

    def get(self, code):
        return self.db.execute(
            select(Product, SKU, Inventory)
            .join(SKU, SKU.product_id == Product.id)
            .join(Inventory, Inventory.sku_id == SKU.id)
            .where(SKU.sku_code == code, SKU.active.is_(True), Product.active.is_(True))
        ).first()

    def promotions(self, sku_id, channel, at=None):
        at = at or now()
        return self.db.scalars(
            select(Promotion).where(
                Promotion.active.is_(True),
                Promotion.starts_at <= at,
                Promotion.ends_at > at,
                Promotion.channel.in_([channel, "all"]),
                or_(Promotion.sku_id == sku_id, Promotion.sku_id.is_(None)),
            )
        ).all()


def catalog_row(row):
    product, sku, inventory = row
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "description": product.description,
        "sku_code": sku.sku_code,
        "variant": sku.variant,
        "list_price": str(sku.list_price),
        "sale_price": str(sku.sale_price),
        "currency": sku.currency,
        "available": inventory.quantity_on_hand - inventory.reserved_quantity,
    }
