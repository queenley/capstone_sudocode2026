"""Domain mappings. PostgreSQL migrations are authoritative; SQLite supports local tests."""

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Boolean,
    Numeric,
    DateTime,
    JSON,
    LargeBinary,
    Uuid,
    ForeignKey,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


def pk():
    return Column(Uuid(as_uuid=False), primary_key=True, default=uid)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    external_id = Column(String, unique=True)
    name = Column(String, nullable=False)
    brand = Column(String)
    category = Column(String, nullable=False)
    description = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class SKU(Base):
    __tablename__ = "skus"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    product_id = Column(
        Uuid(as_uuid=False), ForeignKey("commerce.products.id"), nullable=False
    )
    sku_code = Column(String, unique=True, nullable=False)
    variant = Column(JSON, default=dict)
    list_price = Column(Numeric(18, 2), nullable=False)
    sale_price = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="VND")
    active = Column(Boolean, default=True)
    synthetic = Column(Boolean, default=False)
    source = Column(String)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = {"schema": "commerce"}
    sku_id = Column(
        Uuid(as_uuid=False), ForeignKey("commerce.skus.id"), primary_key=True
    )
    quantity_on_hand = Column(Integer, nullable=False)
    reserved_quantity = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    external_id = Column(String, unique=True)
    sku_id = Column(Uuid(as_uuid=False), ForeignKey("commerce.skus.id"))
    channel = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    promotion_type = Column(String, nullable=False)
    value = Column(Numeric(18, 2))
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    active = Column(Boolean, default=True)
    synthetic = Column(Boolean, default=False)


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    external_id = Column(String, unique=True)
    category = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    effective_at = Column(DateTime(timezone=True), default=now)
    retired_at = Column(DateTime(timezone=True))


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": "identity"}
    id = pk()
    external_id = Column(String, unique=True)
    full_name = Column(String)
    region = Column(String)
    synthetic = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)
    deleted_at = Column(DateTime(timezone=True))


class CustomerIdentity(Base):
    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint("customer_id", "kind", "provider", "identifier_digest"),
        {"schema": "identity"},
    )
    id = pk()
    customer_id = Column(
        Uuid(as_uuid=False), ForeignKey("identity.customers.id"), nullable=False
    )
    kind = Column(String, nullable=False)
    identifier_digest = Column(String, nullable=False)
    provider = Column(String, default="")
    encrypted_value = Column(LargeBinary)
    verified_at = Column(DateTime(timezone=True))
    consent_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = {"schema": "conversation"}
    id = pk()
    customer_id = Column(Uuid(as_uuid=False), ForeignKey("identity.customers.id"))
    channel = Column(String, nullable=False)
    anonymous_session_digest = Column(String, nullable=False)
    status = Column(String, default="open")
    assigned_actor_id = Column(String)
    started_at = Column(DateTime(timezone=True), default=now)
    ended_at = Column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence"),
        {"schema": "conversation"},
    )
    id = pk()
    conversation_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.conversations.id"), nullable=False
    )
    sequence = Column(Integer, nullable=False)
    speaker = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    normalized_text = Column(Text)
    asr_text = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)


class ProfileFact(Base):
    __tablename__ = "profile_facts"
    __table_args__ = (
        Index(
            "one_current_fact",
            "customer_id",
            "slot",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"schema": "memory"},
    )
    id = pk()
    customer_id = Column(
        Uuid(as_uuid=False), ForeignKey("identity.customers.id"), nullable=False
    )
    slot = Column(String, nullable=False)
    value = Column(JSON, nullable=False)
    source_message_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.messages.id"), nullable=False
    )
    confidence = Column(Numeric, default=1)
    consent_at = Column(DateTime(timezone=True), nullable=False)
    valid_from = Column(DateTime(timezone=True), default=now)
    valid_to = Column(DateTime(timezone=True))
    supersedes_id = Column(Uuid(as_uuid=False), ForeignKey("memory.profile_facts.id"))


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = {"schema": "memory"}
    id = pk()
    customer_id = Column(
        Uuid(as_uuid=False), ForeignKey("identity.customers.id"), nullable=False
    )
    conversation_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("conversation.conversations.id"),
        unique=True,
        nullable=False,
    )
    summary = Column(Text, nullable=False)
    structured_context = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)


class Handoff(Base):
    __tablename__ = "handoffs"
    __table_args__ = {"schema": "conversation"}
    id = pk()
    conversation_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.conversations.id"), nullable=False
    )
    from_actor_id = Column(String, nullable=False)
    to_actor_id = Column(String)
    reason = Column(Text, nullable=False)
    brief = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    accepted_at = Column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    customer_id = Column(
        Uuid(as_uuid=False), ForeignKey("identity.customers.id"), nullable=False
    )
    conversation_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.conversations.id")
    )
    idempotency_key = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False)
    currency = Column(String(3), default="VND")
    subtotal = Column(Numeric(18, 2), nullable=False)
    discount = Column(Numeric(18, 2), default=0)
    encrypted_shipping_address = Column(LargeBinary, nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"schema": "commerce"}
    id = pk()
    order_id = Column(
        Uuid(as_uuid=False), ForeignKey("commerce.orders.id"), nullable=False
    )
    sku_id = Column(Uuid(as_uuid=False), ForeignKey("commerce.skus.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    discount = Column(Numeric(18, 2), default=0)
    promotion_id = Column(Uuid(as_uuid=False), ForeignKey("commerce.promotions.id"))


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = {"schema": "improvement"}
    id = pk()
    conversation_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.conversations.id"), nullable=False
    )
    message_id = Column(Uuid(as_uuid=False), ForeignKey("conversation.messages.id"))
    actor_id = Column(String, nullable=False)
    rating = Column(Integer)
    category = Column(String, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = {"schema": "improvement"}
    id = pk()
    source_message_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.messages.id")
    )
    kind = Column(String, nullable=False)
    candidate = Column(JSON, nullable=False)
    status = Column(String, default="pending")
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = {"schema": "improvement"}
    id = pk()
    event_type = Column(String, nullable=False)
    aggregate_id = Column(Uuid(as_uuid=False), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    published_at = Column(DateTime(timezone=True))


class TurnTrace(Base):
    __tablename__ = "turn_traces"
    __table_args__ = {"schema": "conversation"}
    id = pk()
    message_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.messages.id"), nullable=False
    )
    route = Column(String)
    route_confidence = Column(Numeric)
    config_version = Column(String, nullable=False)
    latency_ms = Column(Integer)
    token_usage = Column(JSON, default=dict)
    errors = Column(JSON, default=list)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = {"schema": "conversation"}
    id = pk()
    trace_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.turn_traces.id"), nullable=False
    )
    tool_name = Column(String, nullable=False)
    redacted_arguments = Column(JSON, nullable=False)
    redacted_result = Column(JSON)
    status = Column(String, nullable=False)
    latency_ms = Column(Integer)
    observed_at = Column(DateTime(timezone=True), default=now)


class Challenge(Base):
    __tablename__ = "challenges"
    __table_args__ = {"schema": "identity"}
    id = pk()
    conversation_id = Column(
        Uuid(as_uuid=False), ForeignKey("conversation.conversations.id"), nullable=False
    )
    identifier_digest = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    encrypted_value = Column(LargeBinary, nullable=False)
    code_digest = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, default=0)
    consumed_at = Column(DateTime(timezone=True))


class CustomerAccess(Base):
    __tablename__ = "customer_access"
    __table_args__ = {"schema": "identity"}
    id = pk()
    customer_id = Column(
        Uuid(as_uuid=False), ForeignKey("identity.customers.id"), nullable=False
    )
    token_digest = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = {"schema": "improvement"}
    id = Column(Uuid(as_uuid=False), primary_key=True)
    processed_at = Column(DateTime(timezone=True), default=now)


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = {"schema": "identity"}
    id = pk()
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "identity"}
    id = pk()
    actor_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
