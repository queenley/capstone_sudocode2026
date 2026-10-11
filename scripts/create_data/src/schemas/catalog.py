from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductVariant(StrictModel):
    variant_sku: str = Field(min_length=1)
    size: str | int | None = None
    color: str | None = None
    price_delta_vnd: int
    stock: int = Field(ge=0)

class Product(StrictModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    list_price_vnd: int = Field(gt=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    stock: int = Field(ge=0)
    variants: list[ProductVariant] = Field(default_factory=list)
    synthetic: bool = False

    @model_validator(mode="after")
    def validate_variant_prices_and_ids(self):
        variant_skus = [variant.variant_sku for variant in self.variants]
        if len(variant_skus) != len(set(variant_skus)):
            raise ValueError(f"Duplicate variant_sku under product {self.sku}")
        for variant in self.variants:
            if self.list_price_vnd + variant.price_delta_vnd <= 0:
                raise ValueError(
                    f"Variant {variant.variant_sku} has a non-positive effective price"
                )
        return self

    def price_for_sku(self, sku: str) -> int:
        """Return list price before promotions for the product or one variant SKU."""
        if sku == self.sku:
            return self.list_price_vnd
        for variant in self.variants:
            if variant.variant_sku == sku:
                return self.list_price_vnd + variant.price_delta_vnd
        raise KeyError(f"SKU {sku!r} is not part of product {self.sku!r}")


class ProductCatalog(StrictModel):
    reference_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    products: list[Product] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_skus(self):
        sku_ids = []
        for product in self.products:
            sku_ids.append(product.sku)
            sku_ids.extend(variant.variant_sku for variant in product.variants)
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("Product and variant SKUs must be globally unique")
        return self


class Promotion(StrictModel):
    promo_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    applies_to: list[str]
    type: Literal["fixed", "freecod", "freeship", "gift", "percent", "percent_second_item"]
    discount_vnd: int = Field(ge=0)
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    min_order_vnd: int | None = Field(default=None, ge=0)
    start: date
    end: date
    stackable: bool
    gift_sku: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_period(self):
        if self.end < self.start:
            raise ValueError("Promotion end date precedes start date")
        return self


class PromotionCatalog(StrictModel):
    reference_date: date
    promotions: list[Promotion]


class InventoryEvent(StrictModel):
    sku: str = Field(min_length=1)
    date: date
    qty: int = Field(ge=0)
    note: str = ""


class InventoryTimeline(StrictModel):
    reference_date: date
    rule: str
    events: list[InventoryEvent]


class CustomerOrder(StrictModel):
    order_id: str
    sku: str
    price_vnd: int = Field(ge=0)
    date: date
    status: Literal["delivered", "shipping", "processing", "cancelled"]
    tracking: str | None = None


class CustomerSession(StrictModel):
    session_id: str
    date: date
    channel: Literal["hotline", "zalo_oa", "fb", "web"]
    summary: str
    outcome: str


class Customer(StrictModel):
    customer_id: str
    name: str
    honorific: str
    phone: str
    zalo_id: str | None = None
    fb_id: str | None = None
    region: Literal["bac", "trung", "nam"]
    orders: list[CustomerOrder] = Field(default_factory=list)
    sessions: list[CustomerSession] = Field(default_factory=list)
    shared_phone_with: str | None = None
    synthetic: bool = False


class CustomerCatalog(StrictModel):
    customers: list[Customer]
    notes: str | None = None
