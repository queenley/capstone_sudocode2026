"""Load source catalog inputs once, with the optional synthetic CRM appended."""
from __future__ import annotations

from dataclasses import dataclass

from src.schemas.catalog import Customer, CustomerCatalog, InventoryTimeline, ProductCatalog, PromotionCatalog
from src.utils.io import load_model
from src.utils.paths import CATALOG_DIR

SYNTHETIC_CRM = CATALOG_DIR / "crm_seed_synthetic.json"


def load_customers(include_synthetic: bool = True) -> list[Customer]:
    customers = load_model(CATALOG_DIR / "crm_seed.json", CustomerCatalog).customers
    if include_synthetic and SYNTHETIC_CRM.exists():
        customers.extend(load_model(SYNTHETIC_CRM, CustomerCatalog).customers)
    return customers


@dataclass(frozen=True)
class SourceData:
    """Authoritative inputs used to compute ground truth."""

    catalog: ProductCatalog
    promotions: PromotionCatalog
    timeline: InventoryTimeline
    customers: list[Customer]

    @classmethod
    def load(cls) -> "SourceData":
        return cls(
            catalog=load_model(CATALOG_DIR / "products.json", ProductCatalog),
            promotions=load_model(CATALOG_DIR / "promotions.json", PromotionCatalog),
            timeline=load_model(CATALOG_DIR / "inventory_timeline.json", InventoryTimeline),
            customers=load_customers(),
        )
