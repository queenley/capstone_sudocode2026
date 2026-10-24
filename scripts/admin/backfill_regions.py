"""Give web customers who ordered before regions existed one: from their latest order.

New orders set the customer's region themselves (``commerce/service.py``); this
fills in the customers whose last order came before that. Customers who
already have a region keep it. Safe to run again.

    docker compose run --rm identity-service python /app/scripts/admin/backfill_regions.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/backend-common"))
from sqlalchemy import select  # noqa: E402
from src.core.config import Settings  # noqa: E402
from src.core.regions import region_of  # noqa: E402
from src.db.models import Customer, Order  # noqa: E402
from src.db.session import Database  # noqa: E402
from src.security.service import Security  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    args = parser.parse_args()
    settings = Settings()
    security = Security(settings)
    database = Database(settings.database_url)
    counts = {"bac": 0, "trung": 0, "nam": 0, "unknown": 0}
    with database.sessions() as db:
        customers = db.scalars(
            select(Customer).where(Customer.region.is_(None), Customer.deleted_at.is_(None))
        ).all()
        for customer in customers:
            latest = db.scalar(
                select(Order).where(Order.customer_id == customer.id).order_by(Order.created_at.desc())
            )
            if latest is None:
                continue
            try:
                region = region_of(security.decrypt(latest.encrypted_shipping_address))
            except Exception:  # noqa: BLE001 - an address written under another key, or erased
                region = None
            counts[region or "unknown"] += 1
            if region and not args.dry_run:
                customer.region = region
        if not args.dry_run:
            db.commit()
    print(("Would set" if args.dry_run else "Set"), counts)
