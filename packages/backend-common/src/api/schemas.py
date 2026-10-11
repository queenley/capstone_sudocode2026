from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class NewConversation(BaseModel):
    channel: Literal["web", "chat", "call", "hotline", "fanpage", "zalo"] = "web"


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class StaffInput(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=200)
    role: Literal["agent", "admin", "seller", "developer"]


class Identification(BaseModel):
    kind: Literal["phone", "email"]
    value: str = Field(min_length=3, max_length=200)
    consent: bool


class Verification(BaseModel):
    challenge_id: UUID
    code: str = Field(pattern=r"^\d{6}$")
    full_name: str = Field(default="", max_length=200)
    customer_token: str = Field(default="", max_length=200)


class FeedbackInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    category: str = Field(default="general", max_length=100)
    comment: str = Field(default="", max_length=2000)


class ReviewInput(BaseModel):
    decision: Literal["approved", "rejected"]
    knowledge_text: str = Field(default="", max_length=10000)
    category: str = Field(default="faq", max_length=100)


class HumanMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class TransferInput(BaseModel):
    to_actor_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=1000)


class StockInput(BaseModel):
    quantity_on_hand: int = Field(ge=0, le=1000000)
