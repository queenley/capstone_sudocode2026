from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field(default="", max_length=100)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    sku_code: str = Field(min_length=1, max_length=100)
    variant: dict[str, str] = Field(default_factory=dict)
    list_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    sale_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    stock: int = Field(ge=0, le=1000000)

    @model_validator(mode="after")
    def prices(self):
        if self.sale_price > self.list_price:
            raise ValueError("Sale price exceeds list price")
        return self


class OrderLine(BaseModel):
    sku_code: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100)
    expected_unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


#: How a customer pays. Bank transfer is to the shop's account (VietQR), confirmed by a seller.
PaymentMethod = Literal["cod", "bank_transfer"]


class OrderInput(BaseModel):
    """One order: several lines in ``items``, or one line in the older flat form
    (``sku_code``, ``quantity``, ``expected_unit_price``)."""

    items: list[OrderLine] | None = Field(default=None, min_length=1, max_length=20)
    sku_code: str | None = Field(default=None, min_length=1, max_length=100)
    quantity: int | None = Field(default=None, ge=1, le=100)
    expected_unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    shipping_address: str = Field(min_length=5, max_length=1000)
    expected_total: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=100)
    #: Older clients may omit the choice; this means COD, including the COD limit.
    payment_method: PaymentMethod | None = None

    @model_validator(mode="after")
    def one_form(self):
        flat = (self.sku_code, self.quantity, self.expected_unit_price)
        if self.items is None and any(v is None for v in flat):
            raise ValueError("Give items, or sku_code, quantity and expected_unit_price")
        if self.items is not None and any(v is not None for v in flat):
            raise ValueError("Give items or the single-line fields, not both")
        if self.items is not None and len({line.sku_code for line in self.items}) != len(self.items):
            raise ValueError("Each SKU once per order: add up its quantity instead")
        return self

    def lines(self) -> list[OrderLine]:
        if self.items is not None:
            return list(self.items)
        return [OrderLine(sku_code=self.sku_code, quantity=self.quantity, expected_unit_price=self.expected_unit_price)]


class PromotionInput(BaseModel):
    sku_code: str
    channel: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    promotion_type: Literal["fixed", "percent", "informational"]
    value: Decimal | None = Field(default=None, ge=0)
    starts_at: str
    ends_at: str
