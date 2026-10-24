from decimal import Decimal
from urllib.parse import urlencode
from fastapi import HTTPException
from sqlalchemy import select, update
from src.commerce.repository import CatalogRepository, catalog_row
from src.core.regions import region_of
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

    def search(self, query="", budget=None, category=None, limit=50):
        return [catalog_row(row) for row in self.repo.search(query, budget, category, limit)]

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

    #: Cash on delivery only below this total (policy VC-03).
    COD_LIMIT = Decimal("10000000")

    def create(self, customer_id, conversation_id, channel, data):
        """One order of one or more lines, all quoted again and reserved together, or none."""
        # Serialize customer writes; a unique key is an additional duplicate barrier.
        customer = self.db.scalar(
            select(Customer)
            .where(Customer.id == customer_id, Customer.deleted_at.is_(None))
            .with_for_update()
        )
        lines = sorted(data.lines(), key=lambda line: line.sku_code)
        key = self.security.digest(customer_id + ":" + data.idempotency_key)
        existing = self.db.scalar(select(Order).where(Order.idempotency_key == key))
        if existing:
            stored = sorted(
                (sku.sku_code, item.quantity)
                for item, sku in self.db.execute(
                    select(OrderItem, SKU)
                    .join(SKU, SKU.id == OrderItem.sku_id)
                    .where(OrderItem.order_id == existing.id)
                )
            )
            if (
                stored != [(line.sku_code, line.quantity) for line in lines]
                or self.security.decrypt(existing.encrypted_shipping_address)
                != data.shipping_address
            ):
                raise HTTPException(
                    409, "Idempotency key reused with a different order"
                )
            return self.serialize(existing)
        if not data.confirmed:
            raise HTTPException(422, "Explicit confirmation is required")
        if data.payment_method == "bank_transfer" and not self._bank():
            raise HTTPException(422, "Bank transfer is not available")

        catalog = CatalogService(self.db)
        priced = []
        # SKUs locked in code order, so two orders never wait on each other.
        for line in lines:
            sku = self.db.scalar(
                select(SKU).where(SKU.sku_code == line.sku_code).with_for_update()
            )
            if not sku:
                raise HTTPException(404, f"SKU not found: {line.sku_code}")
            quote = catalog.quote(line.sku_code, line.quantity, channel)
            if Decimal(quote["sale_price"]) != line.expected_unit_price:
                raise HTTPException(
                    409,
                    {"message": "Quote changed; confirm the current total", "quote": quote},
                )
            priced.append((line, sku, quote))
        total = sum((Decimal(quote["total"]) for _, _, quote in priced), Decimal(0))
        if total != data.expected_total:
            raise HTTPException(
                409,
                {"message": "Quote changed; confirm the current total",
                 "quotes": [quote for _, _, quote in priced], "total": str(total)},
            )
        # Only a client that chose COD gets the limit; one that predates the choice keeps its contract.
        if data.payment_method == "cod" and total >= self.COD_LIMIT:
            raise HTTPException(
                422, "Cash on delivery is only for orders under 10,000,000 VND; choose bank transfer"
            )
        for line, sku, _ in priced:
            reserved = self.db.execute(
                update(Inventory)
                .where(
                    Inventory.sku_id == sku.id,
                    Inventory.quantity_on_hand - Inventory.reserved_quantity
                    >= line.quantity,
                )
                .values(
                    reserved_quantity=Inventory.reserved_quantity + line.quantity,
                    updated_at=now(),
                )
            )
            if reserved.rowcount != 1:
                # Nothing is committed: the caller's session rolls every line back.
                raise HTTPException(409, f"Insufficient inventory: {line.sku_code}")
        order = Order(
            customer_id=customer_id,
            conversation_id=conversation_id,
            idempotency_key=key,
            status="confirmed",
            subtotal=sum((sku.sale_price * line.quantity for line, sku, _ in priced), Decimal(0)),
            discount=sum((Decimal(quote["discount"]) for _, _, quote in priced), Decimal(0)),
            encrypted_shipping_address=self.security.encrypt(data.shipping_address),
            confirmed_at=now(),
            payment_method=data.payment_method or "cod",
            payment_status="awaiting_transfer" if data.payment_method == "bank_transfer" else "unpaid",
        )
        self.db.add(order)
        self.db.flush()
        # The region of the latest delivery address: the voice that answers their calls (core/regions.py).
        region = region_of(data.shipping_address)
        if customer is not None and region:
            customer.region = region
        for line, sku, quote in priced:
            self.db.add(
                OrderItem(
                    order_id=order.id,
                    sku_id=sku.id,
                    quantity=line.quantity,
                    unit_price=sku.sale_price,
                    discount=Decimal(quote["discount"]),
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

    def _bank(self):
        settings = self.security.settings
        if not (settings.bank_bin and settings.bank_account_no):
            return None
        return settings

    def transfer(self, order):
        """How to pay *order* by bank transfer: account, amount, the note to write, and a VietQR image."""
        bank = self._bank()
        if bank is None or order.payment_method != "bank_transfer":
            return None
        amount = int(order.subtotal - order.discount)
        note = "TN" + str(order.id).replace("-", "")[:8].upper()
        query = urlencode({"amount": amount, "addInfo": note, "accountName": bank.bank_account_name})
        return {
            "bank_name": bank.bank_name,
            "account_no": bank.bank_account_no,
            "account_name": bank.bank_account_name,
            "amount": amount,
            "content": note,
            "qr_url": f"https://img.vietqr.io/image/{bank.bank_bin}-{bank.bank_account_no}-compact2.png?{query}",
        }

    def mark_paid(self, order):
        order = self.db.scalar(
            select(Order).where(Order.id == order.id).with_for_update()
        )
        if order.status == "cancelled":
            raise HTTPException(409, "Order is cancelled")
        if order.payment_status != "paid":
            order.payment_status, order.paid_at = "paid", now()
            self.db.add(
                Outbox(
                    event_type="order.paid",
                    aggregate_id=order.id,
                    payload={"order_id": str(order.id), "method": order.payment_method},
                )
            )
            self.db.flush()
        return self.serialize(order)

    def serialize(self, order, *, include_address=False):
        """The order, its lines and when it was placed. The delivery address
        (encrypted at rest) only for staff who fulfil it."""
        items = [
            {
                "sku_code": sku.sku_code,
                "name": product.name,
                "variant": sku.variant or {},
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "discount": str(item.discount or 0),
            }
            for item, sku, product in self.db.execute(
                select(OrderItem, SKU, Product)
                .join(SKU, SKU.id == OrderItem.sku_id)
                .join(Product, Product.id == SKU.product_id)
                .where(OrderItem.order_id == order.id)
            )
        ]
        body = {
            "id": str(order.id),
            "status": order.status,
            "subtotal": str(order.subtotal),
            "discount": str(order.discount),
            "total": str(order.subtotal - order.discount),
            "currency": order.currency,
            "items": items,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "conversation_id": str(order.conversation_id) if order.conversation_id else None,
            "payment_method": order.payment_method or "cod",
            "payment_status": order.payment_status or "unpaid",
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "transfer": self.transfer(order),
        }
        if include_address:
            body["shipping_address"] = self.security.decrypt(order.encrypted_shipping_address)
        return body

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
