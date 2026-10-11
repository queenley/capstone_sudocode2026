"""Stage 2 — synthetic CRM profiles for M2 volume (multi-session / multi-channel customers).

Writes ``data/catalog/crm_seed_synthetic.json``; the source ``crm_seed.json`` is
never modified. The model writes names and session summaries only; IDs, phone
numbers, regions, session dates and channels are assigned by the pipeline.
"""
from __future__ import annotations

import argparse
from datetime import date

from src.schemas.catalog import CustomerCatalog
from src.utils.crm import SYNTHETIC_CRM
from src.utils.io import write_json
from src.utils.settings import load_settings, model_client, sampling
from src.utils.quota import stop_on_daily_limit

BATCH_SIZE = 10
MAX_BATCH_ATTEMPTS = 5
CHANNELS = ["hotline", "zalo_oa", "fb", "web"]
REGIONS = ["bac", "trung", "nam"]
MULTI_CHANNEL_FIRST_N = 30  # first N customers rotate channels inside their own sessions

PROMPT = (
    "Generate fictional Vietnamese ecommerce CRM customer profiles only. Do not use real people. "
    "Return a CustomerCatalog with the requested number of customers, each having at least two realistic "
    "historical sessions about household appliances, fashion or mother & baby products. "
    "Use only region bac/trung/nam; order status delivered/shipping/processing/cancelled; channels "
    "hotline/zalo_oa/fb/web. Use fictional names, concise Vietnamese summaries and no address, identity "
    "document or payment information. Dates must be in 2026 and before 2026-10-15. "
    "Use placeholder phone 0000000000; the pipeline replaces it."
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--resume", action="store_true", help="reuse an existing synthetic CRM file")
    args = parser.parse_args()
    if args.resume and SYNTHETIC_CRM.exists():
        print(f"Reuse {SYNTHETIC_CRM.name}")
        return

    settings = load_settings()
    client = model_client("customer", settings)
    params = sampling(settings)
    generated = []
    for offset in range(0, args.count, BATCH_SIZE):
        count = min(BATCH_SIZE, args.count - offset)
        generated.extend(_generate_customers(client, params, count, offset // BATCH_SIZE + 1))

    customers = []
    for i, customer in enumerate(generated):
        sessions = list(customer.sessions)
        if not sessions:
            raise ValueError("Model returned a customer without sessions")
        while len(sessions) < 2:
            sessions.append(sessions[-1].model_copy())
        normalized = [
            session.model_copy(update={
                "session_id": f"SYN-{i + 1:03d}-S{j + 1}",
                "channel": CHANNELS[j % len(CHANNELS)] if i < MULTI_CHANNEL_FIRST_N else CHANNELS[(i + j) % len(CHANNELS)],
                "date": date(2026, 9, 1 + j),
            })
            for j, session in enumerate(sessions)
        ]
        customers.append(customer.model_copy(update={
            "customer_id": f"SYN-C{i + 1:03d}", "phone": f"099800{i + 1:04d}", "region": REGIONS[i % len(REGIONS)],
            "sessions": normalized, "synthetic": True, "shared_phone_with": None,
        }))
    write_json(SYNTHETIC_CRM, CustomerCatalog(
        customers=customers, notes="Model-generated fictional CRM records; IDs and phone numbers assigned by pipeline."))
    print(f"Wrote {len(customers)} synthetic CRM records to {SYNTHETIC_CRM}")


if __name__ == "__main__":
    stop_on_daily_limit(main)()
