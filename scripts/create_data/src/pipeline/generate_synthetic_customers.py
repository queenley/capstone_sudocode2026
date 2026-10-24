"""Stage 2 — synthetic CRM profiles for M2 volume (multi-session / multi-channel customers).

Writes ``data/catalog/crm_seed_synthetic.json``; the source ``crm_seed.json`` is
never modified. The model writes names only. Everything else is assigned by the
pipeline from the catalogue, so the records hold up against the BTC mock: IDs,
phones and regions; orders of real, sold SKUs at their list price; and one
session per order, with an outcome BTC knows and a summary naming the product.

``--resume`` keeps the names already on disk and re-derives the rest, so an
older file is repaired without a model call.
"""
from __future__ import annotations

import argparse
from datetime import date

from src.schemas.catalog import Customer, CustomerCatalog, CustomerOrder, CustomerSession, Product, ProductCatalog
from src.utils.crm import SYNTHETIC_CRM
from src.utils.io import load_model, write_json
from src.utils.paths import CATALOG_DIR
from src.utils.settings import load_settings, model_client, sampling
from src.utils.quota import stop_on_daily_limit

BATCH_SIZE = 10
MAX_BATCH_ATTEMPTS = 5
CHANNELS = ["hotline", "zalo_oa", "fb", "web"]
REGIONS = ["bac", "trung", "nam"]
MULTI_CHANNEL_FIRST_N = 30  # first N customers rotate channels inside their own sessions
# Each customer buys within one category, in turn; the second order is still open.
CATEGORIES = ["gia-dung", "thoi-trang", "me-be"]
OPEN_STATUSES = ["shipping", "processing"]
HONORIFICS = {"mr.": "anh", "mr": "anh", "ms.": "chị", "ms": "chị", "mrs.": "chị", "mrs": "chị", "miss": "chị"}

PROMPT = (
    "Generate fictional Vietnamese ecommerce CRM customer profiles only. Do not use real people. "
    "Return a CustomerCatalog with the requested number of customers. Only each customer's name and "
    "honorific are kept: give a realistic, distinct Vietnamese full name and the honorific a shop would "
    "use (anh, chị, cô, chú). Leave orders empty and give one placeholder session; the pipeline replaces "
    "them. Use region bac, channel hotline, outcome khac, dates in 2026 and placeholder phone 0000000000."
)


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
    """Products a customer can have bought, by top-level category: in the catalogue, not discontinued."""
    by_category: dict[str, list[Product]] = {category: [] for category in CATEGORIES}
    for product in catalog.products:
        top = product.category.split("/")[0]
        if top in by_category and not product.attributes.get("discontinued"):
            by_category[top].append(product)
    return by_category


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


def _grounded(customer: Customer, i: int, products: dict[str, list[Product]], taken: set[str]) -> Customer:
    """*customer*'s name, with the orders and sessions the pipeline assigns to the *i*-th (from 0)."""
    pool = products[CATEGORIES[i % len(CATEGORIES)]]
    orders, sessions = [], []
    for k, product in enumerate((pool[i % len(pool)], pool[(i + 1 + i // len(pool)) % len(pool)])):
        # A garment is bought in one size and colour, which an exchange then names.
        sku = product.variants[i % len(product.variants)].variant_sku if product.variants else product.sku
        price = product.price_for_sku(sku)
        order_id = f"OD9{i + 1:03d}{k + 1:02d}"
        if order_id in taken:
            raise ValueError(f"Synthetic order id {order_id} collides with an existing order")
        status = "delivered" if k == 0 else OPEN_STATUSES[i % len(OPEN_STATUSES)]
        on = date(2026, 3 + i % 5, 1 + (i * 3) % 27) if k == 0 else date(2026, 10, 1 + i % 10)
        orders.append(CustomerOrder(order_id=order_id, sku=sku, price_vnd=price, date=on, status=status,
                                    tracking=f"VN{i + 1:03d}{k + 1}TRK" if status == "shipping" else None))
        progress = "đang giao" if status == "shipping" else "đang xử lý"
        summary = (f"Mua {product.name} giá {_vnd(price)}, đã nhận hàng." if k == 0
                   else f"Đặt {product.name} giá {_vnd(price)}, đơn {order_id} {progress}.")
        sessions.append(CustomerSession(
            session_id=f"SYN-{i + 1:03d}-S{k + 1}", date=on, summary=summary, outcome="chot_don",
            channel=CHANNELS[k % len(CHANNELS)] if i < MULTI_CHANNEL_FIRST_N else CHANNELS[(i + k) % len(CHANNELS)],
        ))
    honorific = HONORIFICS.get(customer.honorific.strip().lower(), customer.honorific.strip() or "anh/chị")
    return customer.model_copy(update={
        "customer_id": f"SYN-C{i + 1:03d}", "phone": f"099800{i + 1:04d}", "region": REGIONS[i % len(REGIONS)],
        "honorific": honorific, "orders": orders, "sessions": sessions, "synthetic": True, "shared_phone_with": None,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--resume", action="store_true",
                        help="keep the names in an existing synthetic CRM file; re-derive orders and sessions")
    args = parser.parse_args()

    if args.resume and SYNTHETIC_CRM.exists():
        generated = load_model(SYNTHETIC_CRM, CustomerCatalog).customers
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
        notes="Fictional CRM records: names by a model; IDs, phones, orders (catalogue SKUs) and sessions by the pipeline."))
    print(f"Wrote {len(customers)} synthetic CRM records to {SYNTHETIC_CRM}")


if __name__ == "__main__":
    stop_on_daily_limit(main)()
