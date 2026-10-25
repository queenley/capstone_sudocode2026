from sqlalchemy import select, or_
from src.db.models import Product, SKU, Inventory, Promotion, now


class CatalogRepository:
    def __init__(self, db):
        self.db = db

    def search(self, query="", budget=None, category=None, limit=50):
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
        if category:
            # A slug or a prefix of one: "gia-dung" matches "gia-dung/quat".
            escaped = category.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Product.category.like(escaped + "%", escape="\\"))
        return self.db.execute(
            stmt.order_by(Product.name, SKU.sku_code).limit(limit)
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
        # The product's own code (variants share it), e.g. SKU-SN-RUN2.
        "product_ref": product.external_id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "description": product.description,
        "image_url": product.image_url,
        "image_credit": product.image_credit,
        "sku_code": sku.sku_code,
        "variant": sku.variant,
        "list_price": str(sku.list_price),
        "sale_price": str(sku.sale_price),
        "currency": sku.currency,
        "available": inventory.quantity_on_hand - inventory.reserved_quantity,
    }
