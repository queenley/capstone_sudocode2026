from __future__ import annotations

import datetime as dt
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
    """Một đơn trong lịch sử CRM của khách."""

    order_id: str = Field(description="Mã đơn")
    sku: str = Field(description="SKU sản phẩm (hoặc variant_sku) trong catalog")
    price_vnd: int = Field(ge=0, description="Giá đã trả, số nguyên VND")
    date: dt.date = Field(description="Ngày đặt, YYYY-MM-DD")
    status: Literal["delivered", "shipping", "processing", "cancelled"] = Field(description="Trạng thái hiện tại của đơn")
    tracking: str | None = Field(None, description="Mã vận đơn; null khi chưa giao cho hãng vận chuyển")


class CustomerSession(StrictModel):
    """Một lần tư vấn trước đây của khách."""

    session_id: str = Field(description="Mã phiên")
    date: dt.date = Field(description="Ngày tư vấn, YYYY-MM-DD")
    channel: Literal["hotline", "zalo_oa", "fb", "web"] = Field(description="Kênh của phiên")
    summary: str = Field(description="Tóm tắt một câu điều đã bàn")
    outcome: str = Field(description="Kết quả phiên: hen_goi_lai, chot_don, chuyen_may, tu_choi hoặc khac")


class Customer(StrictModel):
    """Một hồ sơ khách trong CRM giả lập."""

    customer_id: str = Field(description="Mã khách")
    name: str = Field(description="Họ tên tiếng Việt, hư cấu, không trùng người thật")
    honorific: str = Field(description="Danh xưng shop dùng: anh, chị, cô, chú")
    phone: str = Field(description="Số điện thoại; ở bước sinh tên dùng 0000000000")
    zalo_id: str | None = Field(None, description="ID Zalo nếu khách liên hệ qua Zalo OA; null nếu không")
    fb_id: str | None = Field(None, description="ID Facebook nếu khách liên hệ qua Facebook; null nếu không")
    region: Literal["bac", "trung", "nam"] = Field(description="Miền của khách")
    orders: list[CustomerOrder] = Field(default_factory=list, description="Lịch sử đơn; pipeline điền, model để rỗng")
    sessions: list[CustomerSession] = Field(default_factory=list, description="Lịch sử tư vấn; pipeline điền")
    shared_phone_with: str | None = Field(None, description="customer_id của người dùng chung số điện thoại; null nếu không")
    synthetic: bool = Field(False, description="true cho khách giả lập (không có trong CRM của BTC)")


class CustomerCatalog(StrictModel):
    """Danh sách hồ sơ khách model sinh ra; pipeline chỉ giữ tên và danh xưng."""

    customers: list[Customer] = Field(description="Đúng số hồ sơ được yêu cầu, mỗi hồ sơ một tên khác nhau")
    notes: str | None = Field(None, description="Ghi chú tự do về bộ hồ sơ; null nếu không có")
