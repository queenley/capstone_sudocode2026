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


class OrderInput(BaseModel):
    sku_code: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100)
    shipping_address: str = Field(min_length=5, max_length=1000)
    expected_unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    expected_total: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=100)


class PromotionInput(BaseModel):
    sku_code: str
    channel: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    promotion_type: Literal["fixed", "percent", "informational"]
    value: Decimal | None = Field(default=None, ge=0)
    starts_at: str
    ends_at: str
