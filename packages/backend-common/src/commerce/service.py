from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, update
from src.commerce.repository import CatalogRepository, catalog_row
from src.db.models import (
    Product,
    SKU,
    Inventory,
    Order,
    OrderItem,
    Outbox,
    Customer,
    now,
)


class CatalogService:
    def __init__(self, db):
        self.db, self.repo = db, CatalogRepository(db)

    def search(self, query="", budget=None):
        return [catalog_row(row) for row in self.repo.search(query, budget)]

    def get(self, code):
        row = self.repo.get(code)
        if not row:
            raise HTTPException(404, "SKU not found")
        return catalog_row(row)

    def create(self, data):
        if self.db.scalar(select(SKU).where(SKU.sku_code == data.sku_code)):
            raise HTTPException(409, "SKU already exists")
        product = Product(
            name=data.name,
            brand=data.brand,
            category=data.category,
            description=data.description,
        )
        self.db.add(product)
        self.db.flush()
        sku = SKU(
            product_id=product.id,
            sku_code=data.sku_code,
            variant=data.variant,
            list_price=data.list_price,
            sale_price=data.sale_price,
        )
        self.db.add(sku)
        self.db.flush()
        self.db.add(
            Inventory(sku_id=sku.id, quantity_on_hand=data.stock, reserved_quantity=0)
        )
        self.db.flush()
        return self.get(data.sku_code)

    def quote(self, code, quantity=1, channel="web", at=None):
        row = self.repo.get(code)
        if not row:
            raise HTTPException(404, "SKU not found")
        item = catalog_row(row)
        promos = self.repo.promotions(row[1].id, channel, at)
        price = Decimal(item["sale_price"])
        best, chosen = Decimal(0), None
        for p in promos:
            discount = (
                (price * p.value / 100)
                if p.promotion_type == "percent"
                else (p.value if p.promotion_type == "fixed" else Decimal(0))
            )
            discount = min(price, discount).quantize(Decimal(".01"))
            if discount > best:
                best, chosen = discount, p
        return {
            **item,
            "quantity": quantity,
            "discount": str(best * quantity),
            "total": str((price - best) * quantity),
            "promotion_id": str(chosen.id) if chosen else None,
            "promotions": [
                {"name": p.name, "description": p.description, "type": p.promotion_type}
                for p in promos
            ],
        }


class OrderService:
    def __init__(self, db, security):
        self.db, self.security = db, security

    def create(self, customer_id, conversation_id, channel, data):
        # Serialize customer writes; a unique key is an additional duplicate barrier.
        self.db.scalar(
            select(Customer)
            .where(Customer.id == customer_id, Customer.deleted_at.is_(None))
            .with_for_update()
        )
        key = self.security.digest(customer_id + ":" + data.idempotency_key)
        existing = self.db.scalar(select(Order).where(Order.idempotency_key == key))
        if existing:
            item = self.db.scalar(
                select(OrderItem).where(OrderItem.order_id == existing.id)
            )
            sku = self.db.get(SKU, item.sku_id)
            if (
                sku.sku_code != data.sku_code
                or item.quantity != data.quantity
                or self.security.decrypt(existing.encrypted_shipping_address)
                != data.shipping_address
            ):
                raise HTTPException(
                    409, "Idempotency key reused with a different order"
                )
            return self.serialize(existing)
        if not data.confirmed:
            raise HTTPException(422, "Explicit confirmation is required")
        sku = self.db.scalar(
            select(SKU).where(SKU.sku_code == data.sku_code).with_for_update()
        )
        if not sku:
            raise HTTPException(404, "SKU not found")
        quote = CatalogService(self.db).quote(data.sku_code, data.quantity, channel)
        if (
            Decimal(quote["sale_price"]) != data.expected_unit_price
            or Decimal(quote["total"]) != data.expected_total
        ):
            raise HTTPException(
                409,
                {"message": "Quote changed; confirm the current total", "quote": quote},
            )
        reserved = self.db.execute(
            update(Inventory)
            .where(
                Inventory.sku_id == sku.id,
                Inventory.quantity_on_hand - Inventory.reserved_quantity
                >= data.quantity,
            )
            .values(
                reserved_quantity=Inventory.reserved_quantity + data.quantity,
                updated_at=now(),
            )
        )
        if reserved.rowcount != 1:
            raise HTTPException(409, "Insufficient inventory")
        order = Order(
            customer_id=customer_id,
            conversation_id=conversation_id,
            idempotency_key=key,
            status="confirmed",
            subtotal=sku.sale_price * data.quantity,
            discount=Decimal(quote["discount"]),
            encrypted_shipping_address=self.security.encrypt(data.shipping_address),
            confirmed_at=now(),
        )
        self.db.add(order)
        self.db.flush()
        self.db.add(
            OrderItem(
                order_id=order.id,
                sku_id=sku.id,
                quantity=data.quantity,
                unit_price=sku.sale_price,
                discount=order.discount,
                promotion_id=quote["promotion_id"],
            )
        )
        self.db.add(
            Outbox(
                event_type="order.created",
                aggregate_id=order.id,
                payload={"order_id": str(order.id)},
            )
        )
        self.db.flush()
        return self.serialize(order)

    def serialize(self, order):
        return {
            "id": str(order.id),
            "status": order.status,
            "subtotal": str(order.subtotal),
            "discount": str(order.discount),
            "total": str(order.subtotal - order.discount),
            "currency": order.currency,
        }

    def cancel(self, order):
        order = self.db.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if order.status == "cancelled":
            return self.serialize(order)
        if order.status != "confirmed":
            raise HTTPException(409, "Order cannot be cancelled")
        for item in self.db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.sku_id)
        ):
            self.db.execute(
                update(Inventory)
                .where(Inventory.sku_id == item.sku_id)
                .values(
                    reserved_quantity=Inventory.reserved_quantity - item.quantity,
                    updated_at=now(),
                )
            )
        order.status = "cancelled"
        self.db.add(
            Outbox(
                event_type="order.cancelled",
                aggregate_id=order.id,
                payload={"order_id": str(order.id)},
            )
        )
        return self.serialize(order)
