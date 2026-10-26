"""Stage 2 — synthetic CRM customers, added to BTC's 50 (``crm_seed.json``).

Writes ``data/catalog/crm_seed_synthetic.json`` (10 customers by default) and
copies it to the agent's catalogue (``apps/ai-agent-service/data/btc/catalog``),
so the agent, the evaluation harness and these scenarios know the same callers.
``crm_seed.json`` is never modified.

The model writes names only. The rest is the pipeline's, consistent with BTC's
catalogue on the day of each order:

* every order is a sold SKU (a variant in stock that day) at its price after the
  promotions of that day (``mock_tools.pricing_get_quote``);
* each customer has a delivered order (warranty and return cases), an open one
  (order status, delivery complaints), and every second customer an older
  delivered appliance whose warranty has ended;
* a Zalo id for every second customer and a Facebook id for every third, so
  scenarios can start on those channels and continue on the hotline;
* one session per order, with an outcome BTC knows and a summary naming the product.

``--resume`` keeps the names already on disk and re-derives the rest, without a model call.
"""
from __future__ import annotations

import argparse
import shutil
import unicodedata
from datetime import date

from src.schemas.catalog import Customer, CustomerCatalog, CustomerOrder, CustomerSession, Product, ProductCatalog
from src.utils.btc_tools import mock_tools
from src.utils.crm import SYNTHETIC_CRM
from src.utils.io import load_model, write_json
from src.utils.paths import AGENT_CATALOG_DIR, CATALOG_DIR, PROMPTS_DIR
from src.utils.quota import stop_on_daily_limit
from src.utils.settings import load_settings, model_client, sampling

BATCH_SIZE = 10
MAX_BATCH_ATTEMPTS = 5
CHANNELS = ["hotline", "zalo_oa", "fb", "web"]
REGIONS = ["bac", "trung", "nam"]
# Each customer buys within one category, in turn; the second order is still open.
CATEGORIES = ["gia-dung", "thoi-trang", "me-be"]
OPEN_STATUSES = ["shipping", "processing"]
#: An appliance bought long enough ago that its 12-month warranty has ended (BH-01).
EXPIRED_WARRANTY_MONTHS = 12
HONORIFICS = {"mr.": "anh", "mr": "anh", "ms.": "chị", "ms": "chị", "mrs.": "chị", "mrs": "chị", "miss": "chị"}

PROMPT = (PROMPTS_DIR / "synthetic_customers.md").read_text(encoding="utf-8").replace("\r\n", "\n").removesuffix("\n")


def _generate_customers(client, params: dict, count: int, batch_number: int) -> list:
    """Fill one batch while tolerating valid but undersized model responses."""
    generated = []
    for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
        remaining = count - len(generated)
        if not remaining:
            break
        result = client.generate(
            f"{PROMPT}\nGenerate exactly {remaining} profiles. Batch {batch_number}, attempt {attempt}. "
            "Return all requested profiles in this response; do not stop early.",
            CustomerCatalog, temperature=params["temperature"], max_output_tokens=params["max_output_tokens"])
        generated.extend(result.customers[:remaining])
        if len(generated) < count:
            print(f"  synthetic batch {batch_number} attempt {attempt}: "
                  f"received {len(result.customers)}, still need {count - len(generated)}", flush=True)
    if len(generated) != count:
        raise ValueError(f"Expected {count} customers after {MAX_BATCH_ATTEMPTS} attempts, got {len(generated)}")
    return generated


def _sellable(catalog: ProductCatalog) -> dict[str, list[Product]]:
    """Products a customer can have bought, by top-level category: in the catalogue, not discontinued, no accessories."""
    by_category: dict[str, list[Product]] = {category: [] for category in CATEGORIES}
    for product in catalog.products:
        top = product.category.split("/")[0]
        if top in by_category and not product.attributes.get("discontinued") and "phu-kien" not in product.category:
            by_category[top].append(product)
    return by_category


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


def _sold(pool: list[Product], start: int, i: int, on: date) -> tuple[Product, str, int]:
    """What was bought on *on*: the first product of *pool* from *start* with a SKU in stock that day
    (a garment is bought in one size), that SKU, and its price after the promotions of that day."""
    mock = mock_tools()
    for k in range(len(pool)):
        product = pool[(start + k) % len(pool)]
        skus = [v.variant_sku for v in product.variants] or [product.sku]
        in_stock = [s for s in skus if mock.inventory_check(s, on.isoformat()).get("in_stock")]
        if in_stock:
            sku = in_stock[i % len(in_stock)]
            return product, sku, mock.pricing_get_quote(sku, on.isoformat())["final_price_vnd"]
    raise ValueError(f"Nothing in this category is in stock on {on}")


def _handle(name: str) -> str:
    """'Nguyễn Thị Hoa' -> 'hoa', for ids such as zalo_hoa07 (BTC's CRM uses the given name)."""
    given = (name.split() or ["khach"])[-1].lower()
    return "".join(c for c in unicodedata.normalize("NFD", given) if unicodedata.category(c) != "Mn").replace("đ", "d")


def _grounded(customer: Customer, i: int, products: dict[str, list[Product]], taken: set[str]) -> Customer:
    """*customer*'s name, with the identities, orders and sessions the pipeline assigns to the *i*-th (from 0)."""
    pool = products[CATEGORIES[i % len(CATEGORIES)]]
    # (status, the products it is chosen from, where in them to start, the order date)
    bought = [("delivered", pool, i, date(2026, 3 + i % 5, 1 + (i * 3) % 27)),
              (OPEN_STATUSES[i % len(OPEN_STATUSES)], pool, i + 1 + i // len(pool), date(2026, 10, 1 + i % 10))]
    if i % 2 == 1:   # an older appliance, out of its 12-month warranty by the scenarios' dates
        old = [p for p in products["gia-dung"] if p.attributes.get("warranty_months") == EXPIRED_WARRANTY_MONTHS]
        bought.append(("delivered", old, i, date(2025, 2 + i % 6, 5 + i % 20)))
    orders, sessions = [], []
    already: set[str] = set()   # two orders of one customer are two different products
    for k, (status, choices, start, on) in enumerate(bought):
        product, sku, price = _sold([p for p in choices if p.sku not in already] or choices, start, i, on)
        already.add(product.sku)
        order_id = f"OD9{i + 1:03d}{k + 1:02d}"
        if order_id in taken:
            raise ValueError(f"Synthetic order id {order_id} collides with an existing order")
        orders.append(CustomerOrder(order_id=order_id, sku=sku, price_vnd=price, date=on, status=status,
                                    tracking=f"VN{i + 1:03d}{k + 1}TRK" if status == "shipping" else None))
        progress = {"delivered": "đã nhận hàng", "shipping": "đang giao", "processing": "đang xử lý"}[status]
        summary = (f"Mua {product.name} giá {_vnd(price)}, {progress}." if status == "delivered"
                   else f"Đặt {product.name} giá {_vnd(price)}, đơn {order_id} {progress}.")
        sessions.append(CustomerSession(session_id=f"SYN-{i + 1:03d}-S{k + 1}", date=on, summary=summary,
                                        outcome="chot_don", channel=CHANNELS[(i + k) % len(CHANNELS)]))
    honorific = HONORIFICS.get(customer.honorific.strip().lower(), customer.honorific.strip() or "anh/chị")
    handle = _handle(customer.name)
    return customer.model_copy(update={
        "customer_id": f"SYN-C{i + 1:03d}", "phone": f"099800{i + 1:04d}", "region": REGIONS[i % len(REGIONS)],
        "honorific": honorific, "orders": orders, "sessions": sorted(sessions, key=lambda s: s.date),
        "zalo_id": f"zalo_{handle}{i + 1:02d}" if i % 2 == 0 else None,
        "fb_id": f"fb.{handle}.{900 + i}" if i % 3 == 0 else None,
        "synthetic": True, "shared_phone_with": None,
    })


def sync_to_agent() -> None:
    """Copy the synthetic CRM to the agent's catalogue, which its BTC mock and the harness read."""
    if AGENT_CATALOG_DIR.is_dir():
        shutil.copyfile(SYNTHETIC_CRM, AGENT_CATALOG_DIR / SYNTHETIC_CRM.name)
        print(f"Copied {SYNTHETIC_CRM.name} to {AGENT_CATALOG_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=10, help="customers to add to BTC's 50")
    parser.add_argument("--resume", action="store_true",
                        help="keep the names in an existing synthetic CRM file; re-derive everything else")
    args = parser.parse_args()

    if args.resume and SYNTHETIC_CRM.exists():
        generated = load_model(SYNTHETIC_CRM, CustomerCatalog).customers[:args.count]
        print(f"Reuse the {len(generated)} names in {SYNTHETIC_CRM.name}")
    else:
        settings = load_settings()
        client = model_client("customer", settings)
        params = sampling(settings)
        generated = []
        for offset in range(0, args.count, BATCH_SIZE):
            count = min(BATCH_SIZE, args.count - offset)
            generated.extend(_generate_customers(client, params, count, offset // BATCH_SIZE + 1))

    products = _sellable(load_model(CATALOG_DIR / "products.json", ProductCatalog))
    official = load_model(CATALOG_DIR / "crm_seed.json", CustomerCatalog).customers
    taken = {order.order_id for customer in official for order in customer.orders}
    customers = [_grounded(customer, i, products, taken) for i, customer in enumerate(generated)]
    write_json(SYNTHETIC_CRM, CustomerCatalog(
        customers=customers,
        notes="Fictional CRM records: names by a model; IDs, phones, identities, orders (catalogue SKUs at the "
              "price of their day) and sessions by the pipeline."))
    print(f"Wrote {len(customers)} synthetic CRM records to {SYNTHETIC_CRM}")
    sync_to_agent()


if __name__ == "__main__":
    stop_on_daily_limit(main)()
