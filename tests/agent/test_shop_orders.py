"""The agent's orders on the website's database (runtime/shop_orders.py), on an in-memory SQLite shop."""
from decimal import Decimal

import pytest

pytest.importorskip("sqlalchemy")
from src.core.config import Settings  # noqa: E402
from src.db.models import Customer, Inventory, Order, Product, SKU  # noqa: E402
from src.db.session import Database  # noqa: E402
from src.security.service import Security  # noqa: E402

from ai_agent_service.runtime import shop_orders  # noqa: E402

PHONE = "0984726714"


@pytest.fixture()
def shop(monkeypatch):
    database = Database("sqlite://")
    database.migrate()
    security = Security(Settings(database_url="sqlite://"))
    with database.sessions() as db:
        product = Product(name="Máy lọc không khí AirPure Y", brand="AirPure", category="gia-dung")
        db.add(product)
        db.flush()
        sku = SKU(product_id=product.id, sku_code="SKU-AP-Y", list_price=Decimal(5500000), sale_price=Decimal(5200000))
        db.add(sku)
        db.flush()
        db.add(Inventory(sku_id=sku.id, quantity_on_hand=5, reserved_quantity=0))
        db.commit()
    monkeypatch.setenv("SHOP_ORDERS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app_db")
    monkeypatch.setattr(shop_orders, "_resources", lambda: (database, security))
    return database, security


def test_an_order_the_agent_placed_is_in_the_customers_website_orders(shop):
    database, security = shop
    shop_orders.mirror_create({"order_id": "OD600001", "status": "created"},
                              {"customer_phone": PHONE, "sku": "SKU-AP-Y", "qty": 1, "price_vnd": 5200000,
                               "payment": "COD", "address": "Hồ Chí Minh"})
    shop_orders.mirror_create({"order_id": "OD600001"}, {"customer_phone": PHONE, "sku": "SKU-AP-Y", "qty": 1,
                                                         "price_vnd": 5200000})  # a replay adds nothing
    listed = shop_orders.orders_for_phone(PHONE)
    assert [o["order_id"] for o in listed] == ["OD600001"]
    assert listed[0]["source"] == "agent" and listed[0]["total_vnd"] == 5200000 and listed[0]["payment"] == "cod"
    shop_orders.mirror_address("OD600001", "Hà Nội")
    with database.sessions() as db:
        order = db.query(Order).one()
        assert security.decrypt(order.encrypted_shipping_address) == "Hà Nội"
        assert db.query(Inventory).one().reserved_quantity == 1
        assert db.query(Customer).count() == 1


def test_the_crm_customer_is_the_one_the_agent_orders_for(shop):
    database, _ = shop
    crm = [{"customer_id": "C001", "name": "Hoa", "phone": PHONE,
            "orders": [{"order_id": "OD188213", "sku": "SKU-AP-Y", "price_vnd": 4290000, "date": "2026-02-17",
                        "status": "delivered"},
                       {"order_id": "OD188214", "sku": "SKU-NOT-SOLD", "price_vnd": 1, "status": "delivered"}]}]
    assert shop_orders.seed_crm_customers(crm) == (1, 1)
    assert shop_orders.seed_crm_customers(crm) == (1, 1)  # again: nothing new
    shop_orders.mirror_create({"order_id": "OD600001"}, {"customer_phone": PHONE, "sku": "SKU-AP-Y", "qty": 1,
                                                         "price_vnd": 5200000})
    with database.sessions() as db:
        assert db.query(Customer).count() == 1
        assert db.query(Customer).one().external_id == "C001"
    listed = {o["order_id"]: o for o in shop_orders.orders_for_phone(PHONE)}
    assert set(listed) == {"OD600001", "OD188213"}
    assert listed["OD188213"]["status"] == "delivered" and listed["OD188213"]["created_on"] == "2026-02-17"


def test_an_evaluation_database_never_reaches_the_website(monkeypatch):
    monkeypatch.setenv("SHOP_ORDERS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/app_db_eval")
    assert not shop_orders.enabled()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/app_db")
    assert shop_orders.enabled()
    monkeypatch.delenv("SHOP_ORDERS")
    assert not shop_orders.enabled()
    assert shop_orders.orders_for_phone(PHONE) == []


def _web_order(database, security, *, status="confirmed"):
    """An order the customer placed on the website (no OD code), and its WEB- code."""
    from src.db.models import OrderItem

    shop_orders.mirror_create({"order_id": "TMP"}, {"customer_phone": PHONE, "sku": "SKU-AP-Y", "qty": 1,
                                                    "price_vnd": 5200000, "address": "Hồ Chí Minh"})
    with database.sessions() as db:
        order = db.query(Order).filter(Order.order_code == "TMP").one()
        order.order_code, order.source, order.status = None, "website", status
        db.commit()
        return f"WEB-{str(order.id)[:8].upper()}", order.id


def _second_sku(database, code="SKU-AP-Y-PRO", price=6200000, stock=3):
    with database.sessions() as db:
        product = db.query(Product).first()
        sku = SKU(product_id=product.id, sku_code=code, list_price=Decimal(price), sale_price=Decimal(price))
        db.add(sku)
        db.flush()
        db.add(Inventory(sku_id=sku.id, quantity_on_hand=stock, reserved_quantity=0))
        db.commit()


def test_the_agent_changes_an_order_placed_on_the_website(shop):
    database, security = shop
    code, order_id = _web_order(database, security)
    assert [o["order_id"] for o in shop_orders.orders_for_phone(PHONE)] == [code]
    moved = shop_orders.update_order(code, "update_address", new_address="Hà Nội")
    assert moved["status"] == "updated"
    _second_sku(database)
    first = shop_orders.update_order(code, "exchange_product", new_variant_sku="SKU-AP-Y-PRO")
    assert first["fee_vnd"] == 0 and first["extra_payment_vnd"] == 1000000
    second = shop_orders.update_order(code, "exchange_product", new_variant_sku="SKU-AP-Y")
    assert second["fee_vnd"] == 60000 and second["refund_vnd"] == 1000000
    assert shop_orders.update_order(code, "return")["error"] == "order_not_delivered"
    assert shop_orders.update_order("WEB-00000000", "return") is None  # no such order: the mock's refusal stands
    with database.sessions() as db:
        order = db.get(Order, order_id)
        assert security.decrypt(order.encrypted_shipping_address) == "Hà Nội"
        reserved = {i.sku_id: i.reserved_quantity for i in db.query(Inventory)}
        assert sorted(reserved.values()) == [0, 1]  # the old item's hold went back each time


def test_sales_moves_an_order_on_and_the_agent_reads_it_back(shop):
    from src.commerce.service import OrderService

    database, security = shop
    code, order_id = _web_order(database, security)
    with database.sessions() as db:
        service = OrderService(db, security)
        service.set_status(db.get(Order, order_id), "shipping")
        db.commit()
    assert shop_orders.orders_for_phone(PHONE)[0]["status"] == "shipping"
    assert shop_orders.update_order(code, "update_address", new_address="Đà Nẵng")["error"] == "order_already_shipped"
    with database.sessions() as db:
        OrderService(db, security).set_status(db.get(Order, order_id), "fulfilled")
        db.commit()
        order = db.get(Order, order_id)
        assert order.payment_status == "paid"  # COD collected on delivery
        assert db.query(Inventory).one().quantity_on_hand == 4
    assert shop_orders.orders_for_phone(PHONE)[0]["status"] == "delivered"
    asked = shop_orders.update_order(code, "return", reason="không vừa")
    assert asked["status"] == "pickup_scheduled" and asked["refund_vnd"] == 5200000
    with database.sessions() as db:
        OrderService(db, security).set_status(db.get(Order, order_id), "returned")
        db.commit()
        order = db.get(Order, order_id)
        assert order.status == "returned" and order.payment_status == "refunded"
        assert db.query(Inventory).one().quantity_on_hand == 5
        with pytest.raises(Exception):
            OrderService(db, security).set_status(db.get(Order, order_id), "shipping")


def test_a_crm_order_of_a_product_the_shop_no_longer_lists_is_kept(shop):
    database, _ = shop
    crm = [{"customer_id": "C002", "name": "Lan", "phone": "0900000002",
            "orders": [{"order_id": "OD188213", "sku": "SKU-AP-X-2024", "price_vnd": 4290000, "status": "shipping"}]}]
    assert shop_orders.seed_crm_customers(crm) == (1, 1)
    listed = shop_orders.orders_for_phone("0900000002")
    assert listed[0]["status"] == "shipping" and listed[0]["sku"] == "SKU-AP-X-2024"
    with database.sessions() as db:
        assert db.query(SKU).filter(SKU.sku_code == "SKU-AP-X-2024").one().active is False


def test_a_demo_password_opens_every_crm_customer_but_keeps_a_real_account(shop):
    from src.db.models import CustomerIdentity
    from src.security.auth import password_matches

    database, _ = shop
    crm = [{"customer_id": "C001", "name": "Hoa", "phone": PHONE, "orders": []},
           {"customer_id": "C002", "name": "Lan", "phone": "0900000002", "orders": []}]
    with database.sessions() as db:
        db.add(Customer(full_name="Nguyễn Thị Hoa", password_hash="real"))
        db.commit()
    shop_orders.seed_crm_customers(crm[1:], demo_password="quivo-demo-2026")
    with database.sessions() as db:
        lan = db.query(Customer).filter(Customer.external_id == "C002").one()
        assert password_matches("quivo-demo-2026", lan.password_hash)
        assert db.query(CustomerIdentity).filter(CustomerIdentity.customer_id == lan.id).one().verified_at
    shop_orders.seed_crm_customers(crm[1:], demo_password="another-password")  # again: the first one stays
    with database.sessions() as db:
        lan = db.query(Customer).filter(Customer.external_id == "C002").one()
        assert password_matches("quivo-demo-2026", lan.password_hash)


@pytest.mark.asyncio
async def test_a_slow_website_never_costs_the_organisers_answer(shop, monkeypatch):
    """order_status timed out twice (16:10, chị Hoa on the web) while the website's database was first opened."""
    import time

    from ai_agent_service.mcp.servers import btc
    from ai_agent_service.mcp.servers import order as order_server

    answer = {"orders": [{"order_id": "OD600001", "status": "created", "customer_phone": PHONE}]}

    async def call(name, fn, /, **kwargs):
        return answer

    monkeypatch.setattr(btc, "call", call)
    monkeypatch.setattr(order_server, "WEBSITE_BUDGET", 0.05)
    monkeypatch.setattr(shop_orders, "orders_for_phone", lambda phone: time.sleep(0.5) or [{"order_id": "WEB-1"}])
    assert await order_server.order_status(customer_phone=PHONE) == answer


def test_warming_up_opens_the_website_and_survives_one_that_is_down(shop, monkeypatch):
    shop_orders.warm()  # the in-memory shop answers SELECT 1

    def down():
        raise OSError("connection refused")

    monkeypatch.setattr(shop_orders, "_resources", down)
    shop_orders.warm()  # logged, not raised: the MCP server still starts
