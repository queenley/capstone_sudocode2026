"""The bank transfer QR the assistant shows for an order (order_payment_qr, order_create), on an in-memory shop."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")
from langchain_core.messages import ToolMessage  # noqa: E402
from src.core.config import Settings  # noqa: E402
from src.db.models import Inventory, Order, Product, SKU  # noqa: E402
from src.db.session import Database  # noqa: E402
from src.security.service import Security  # noqa: E402

from ai_agent_service.api.routes.conversations import payment_qr_for, qr_order_of  # noqa: E402
from ai_agent_service.mcp.tools import trusted_orders  # noqa: E402
from ai_agent_service.runtime import shop_orders  # noqa: E402

PHONE = "0984726714"
BANK = {"bank_bin": "970436", "bank_name": "Vietcombank", "bank_account_no": "0123456789",
        "bank_account_name": "QUIVO SHOP"}


@pytest.fixture()
def shop(monkeypatch):
    database = Database("sqlite://")
    database.migrate()
    security = Security(Settings(database_url="sqlite://"))
    security.settings = replace(security.settings, **BANK)
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


def place(code: str, payment: str) -> None:
    shop_orders.mirror_create({"order_id": code}, {"customer_phone": PHONE, "sku": "SKU-AP-Y", "qty": 1,
                                                   "price_vnd": 5200000, "payment": payment, "address": "Hà Nội"})


def test_the_qr_has_the_orders_amount_and_the_checkouts_note(shop):
    database, _ = shop
    place("OD600001", "bank")
    qr = shop_orders.payment_qr("OD600001", trusted=("OD600001",))
    assert qr["ok"] and qr["order_id"] == "OD600001" and qr["amount"] == 5200000
    with database.sessions() as db:
        order = db.query(Order).one()
    # The note staff look for on the statement is the checkout's: TN and the order's id.
    assert qr["content"] == "TN" + str(order.id).replace("-", "")[:8].upper()
    assert qr["qr_url"].startswith("https://img.vietqr.io/image/970436-0123456789-compact2.png?amount=5200000")
    assert qr["account_name"] == "QUIVO SHOP"


def test_someone_elses_order_is_not_found(shop):
    database, _ = shop
    place("OD600001", "bank")
    # Not created this call, not a verified customer's, not the logged-in account's: as if it did not exist.
    assert shop_orders.payment_qr("OD600001", trusted=()) == {"ok": False, "code": "NOT_FOUND"}
    assert shop_orders.payment_qr("OD600001", account_id="someone-else") == {"ok": False, "code": "NOT_FOUND"}
    assert shop_orders.payment_qr("OD999999", trusted=("OD999999",)) == {"ok": False, "code": "NOT_FOUND"}
    with database.sessions() as db:
        order = db.query(Order).one()
        owner, ref = str(order.customer_id), "#" + str(order.id)[:8].upper()
    # The logged-in owner reaches it by the website's #ABCD1234 as well.
    assert shop_orders.payment_qr(ref, account_id=owner)["ok"]


@pytest.mark.parametrize("payment,paid,cancelled,code", [
    ("COD", False, False, "NOT_BANK_TRANSFER"),
    ("bank", True, False, "ALREADY_PAID"),
    ("bank", False, True, "CANCELLED"),
])
def test_no_qr_for_an_order_that_needs_no_transfer(shop, payment, paid, cancelled, code):
    database, _ = shop
    place("OD600001", payment)
    with database.sessions() as db:
        order = db.query(Order).one()
        if paid:
            order.payment_status = "paid"
        if cancelled:
            order.status = "cancelled"
        db.commit()
    assert shop_orders.payment_qr("OD600001", trusted=("OD600001",)) == {"ok": False, "code": code}
    assert code in shop_orders.QR_REFUSALS


def test_no_qr_without_the_shops_account(shop):
    _, security = shop
    place("OD600001", "bank")
    security.settings = replace(security.settings, bank_bin="", bank_account_no="")
    assert shop_orders.payment_qr("OD600001", trusted=("OD600001",)) == {"ok": False, "code": "NO_BANK_ACCOUNT"}


def test_an_evaluation_run_never_makes_a_qr(monkeypatch):
    monkeypatch.delenv("SHOP_ORDERS", raising=False)
    assert shop_orders.payment_qr("OD600001", trusted=("OD600001",)) == {"ok": False, "code": "NOT_FOUND"}


def created(code: str) -> ToolMessage:
    return ToolMessage(content=f'{{"ok": true, "data": {{"order_id": "{code}"}}}}', name="order_create",
                       tool_call_id="c1")


def test_trusted_orders_are_this_calls_and_a_verified_customers():
    shown = ToolMessage(content='{"ok": true, "data": {"orders": [{"order_id": "OD188213"}]}}', name="order_status",
                        tool_call_id="c2")
    state = {"messages": [created("OD600002"), shown]}
    guest = SimpleNamespace(tier="UNKNOWN", created_orders=({"order_id": "OD600001"},), known_orders=frozenset({"OD1"}))
    # A guest: only the orders this call created, in an earlier turn or this one.
    assert trusted_orders(guest, state) == ["OD600001", "OD600002"]
    verified = SimpleNamespace(tier="VERIFIED", created_orders=(), known_orders=frozenset({"OD1"}))
    assert trusted_orders(verified, state) == ["OD1", "OD188213", "OD600002"]


def result(name: str, data: dict) -> dict:
    return {"name": name, "result": {"ok": True, "data": data}}


def test_the_turns_qr_is_found_by_the_tools_that_made_it():
    assert qr_order_of([result("order.payment_qr", {"order_id": "OD600001", "amount_vnd": 1})]) == "OD600001"
    assert qr_order_of([result("order.create", {"order_id": "OD600002", "payment_qr": {"amount_vnd": 1}})]) == "OD600002"
    assert qr_order_of([result("order.create", {"order_id": "OD600003"})]) is None  # COD: no QR
    assert qr_order_of([{"name": "order.payment_qr", "result": {"ok": False, "error": {"code": "NOT_FOUND"}}}]) is None


@pytest.mark.asyncio
async def test_the_chat_reads_the_qr_from_the_shop_not_from_the_models_view(shop):
    place("OD600001", "bank")
    shown = await payment_qr_for("OD600001")
    # The tool's result went through the PII vault (<BANK_1> for the account): the chat's QR never does.
    assert shown["account_no"] == "0123456789" and "<" not in shown["qr_url"]
    assert shown["qr_url"].startswith("https://img.vietqr.io/image/970436-0123456789-")
    assert shown["amount_vnd"] == 5200000 and shown["order_id"] == "OD600001"
    assert await payment_qr_for(None) is None


class Request(SimpleNamespace):
    def override(self, **changes):
        return Request(**{**self.__dict__, **changes})


def test_the_qr_tool_is_offered_only_where_the_shops_orders_are(monkeypatch):
    from ai_agent_service.mcp.tools import LaneToolsMiddleware

    names = ["order_payment_qr", "catalog_search"]
    lanes = {"NEW": frozenset(names)}

    def offered():
        request = Request(runtime=SimpleNamespace(context=SimpleNamespace(lane="NEW", account_id=None)),
                          tools=[SimpleNamespace(name=n, args={}) for n in names])
        return [t.name for t in LaneToolsMiddleware(lanes, names)._filtered(request).tools]

    monkeypatch.setenv("SHOP_ORDERS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/app_db")
    assert offered() == names
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/app_db_eval")  # an evaluation run
    assert offered() == ["catalog_search"]


def test_the_model_never_chooses_which_orders_are_trusted():
    from ai_agent_service.mcp.tools import ToolGuardMiddleware

    guard = ToolGuardMiddleware.__new__(ToolGuardMiddleware)
    context = SimpleNamespace(account_id=None, on=None, customer_phone=None, tier="UNKNOWN", lane="NEW", addresses={},
                              vault=None, customer_id=None, call_id=None, created_orders=(), known_orders=frozenset())
    request = Request(runtime=SimpleNamespace(context=context), state={},
                      tool=SimpleNamespace(name="order_payment_qr",
                                           args={"order_id": {}, "account_id": {}, "trusted_orders": {}}),
                      tool_call={"name": "order_payment_qr", "id": "1",
                                 "args": {"order_id": "OD188213", "trusted_orders": ["OD188213"]}})
    assert guard._with_context(request).tool_call["args"] == {"order_id": "OD188213", "account_id": None,
                                                              "trusted_orders": []}


def test_a_cod_order_moves_to_a_transfer_and_gets_its_qr(shop):
    database, _ = shop
    place("OD600001", "COD")
    assert shop_orders.payment_qr("OD600001", trusted=("OD600001",))["code"] == "NOT_BANK_TRANSFER"
    moved = shop_orders.set_payment("OD600001", "bank_transfer", trusted=("OD600001",))
    assert moved == {"ok": True, "order_id": "OD600001", "payment": "bank_transfer", "changed": True}
    with database.sessions() as db:
        order = db.query(Order).one()
        assert (order.payment_method, order.payment_status) == ("bank_transfer", "awaiting_transfer")
    assert shop_orders.payment_qr("OD600001", trusted=("OD600001",))["ok"]
    # Asked again: nothing changes.
    assert shop_orders.set_payment("OD600001", "bank_transfer", trusted=("OD600001",))["changed"] is False
    # And back to cash on delivery.
    assert shop_orders.set_payment("OD600001", "cod", trusted=("OD600001",))["changed"] is True


def test_only_the_customers_unshipped_unpaid_order_changes(shop):
    database, _ = shop
    place("OD600001", "COD")
    assert shop_orders.set_payment("OD600001", "bank_transfer", trusted=()) == {"ok": False, "code": "NOT_FOUND"}
    with database.sessions() as db:
        db.query(Order).one().status = "shipping"
        db.commit()
    assert shop_orders.set_payment("OD600001", "bank_transfer", trusted=("OD600001",))["code"] == "ALREADY_SHIPPED"
    with database.sessions() as db:
        order = db.query(Order).one()
        order.status, order.payment_status = "confirmed", "paid"
        db.commit()
    assert shop_orders.set_payment("OD600001", "bank_transfer", trusted=("OD600001",))["code"] == "ALREADY_PAID"


def test_cod_stays_within_its_limit(shop):
    database, _ = shop
    place("OD600001", "bank")
    with database.sessions() as db:
        db.query(Order).one().subtotal = Decimal(12_000_000)
        db.commit()
    assert shop_orders.set_payment("OD600001", "cod", trusted=("OD600001",))["code"] == "COD_LIMIT"
    assert all(code in shop_orders.PAYMENT_REFUSALS for code in ("COD_LIMIT", "ALREADY_PAID", "NOT_FOUND"))


def test_the_website_order_number_finds_the_order_too(shop):
    database, _ = shop
    place("OD600001", "COD")
    with database.sessions() as db:
        order = db.query(Order).one()
        order.order_code = None  # an order placed on the website itself has no OD code
        owner, ref = str(order.customer_id), "#" + str(order.id)[:8].upper()
        db.commit()
    assert shop_orders.set_payment(ref, "bank_transfer", account_id=owner)["order_id"] == ref
    assert shop_orders.payment_qr(ref.lower(), account_id=owner)["ok"]


def test_zalo_gets_the_qr_as_a_picture_with_its_amount_and_note():
    import importlib.util
    from pathlib import Path

    from ai_agent_service.runtime import zalo

    caption = zalo.qr_caption({"order_id": "OD600001", "amount_vnd": 1690000, "transfer_note": "TN626A51B9",
                               "bank_name": "Vietcombank", "account_no": "0123456789", "account_name": "QUIVO"})
    assert "1.690.000đ" in caption and "TN626A51B9" in caption and "OD600001" in caption
    # The local Zalo mock reads the OA v3 image message the shop sends (scripts/dev/zalo_mock.py).
    spec = importlib.util.spec_from_file_location("zalo_mock", Path(__file__).parents[2] / "scripts/dev/zalo_mock.py")
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    url = "https://img.vietqr.io/image/970436-0123456789-compact2.png?amount=1690000"
    message = {"text": caption, "attachment": {"type": "template", "payload": {
        "template_type": "media", "elements": [{"media_type": "image", "url": url}]}}}
    assert mock._image_of(message) == url
    assert mock._image_of({"text": "chỉ có chữ"}) is None


@pytest.mark.parametrize("environment,shown", [("staging", True), ("production", False), (None, False)])
def test_the_zalo_mocks_clock_picker_is_for_staging_only(monkeypatch, environment, shown):
    import importlib.util
    from pathlib import Path

    if environment is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", environment)
    spec = importlib.util.spec_from_file_location("zalo_mock_env", Path(__file__).parents[2] / "scripts/dev/zalo_mock.py")
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    assert mock.CLOCK_PICKER is shown
