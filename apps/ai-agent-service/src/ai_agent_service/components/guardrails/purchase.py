"""Purchase consent belongs to one call, one question and one immutable order.

Checkpoint only hashes and the tokenised question. A signed, short-lived receipt
crosses the MCP boundary; the backend consumes its draft id with the order write.
The security TTL uses wall time, independently of the catalogue's virtual day.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any, Mapping
from uuid import uuid4

from ...config.database import derived_key
from ..intake.itn import format_vnd
from ..intake.text import plain

TTL_SECONDS = 300
#: What a customer agreed to and the model need not write again: filled in by code when it left them out.
FILLED = ("promo_code", "address", "payment", "qty", "basket_skus", "order_group")
#: Only when the PolicyAgent gave no answer (*intents* ``purchase``): a short yes right after the exact read-back.
YES = re.compile(
    r"(?:da )?(?:(?:vang|da|u|uh|co|dong y|xac nhan|ok|oke|dung roi)(?: a| nhe| nha)?|"
    r"(?:dong y |xac nhan )?(?:dat(?: hang| may| don)?|chot(?: don)?|len don|mua)"
    r"(?: cho (?:anh|chi|toi))?(?: di| a| nhe| nha)?)[.!]*")


def now() -> float:
    return time.time()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload(args: Mapping[str, Any]) -> dict[str, Any]:
    values = {"sku": args.get("sku"), "price_vnd": int(args["price_vnd"]), "qty": int(1 if args.get("qty") is None else args["qty"]),
            "payment": args.get("payment") or "COD", "promo_code": args.get("promo_code") or None,
            "address": args.get("address") or None, "customer_phone": args.get("customer_phone"), "on": args.get("on")}
    for field in ('basket_skus', 'order_group'):
        if args.get(field):
            values[field] = args[field]
    return values


def fingerprint(args: Mapping[str, Any]) -> str:
    order = payload(args)
    if order["address"]:  # the same address, typed differently, is the same order
        order["address"] = " ".join(str(order["address"]).casefold().split())
    return hashlib.sha256(_json(order).encode()).hexdigest()


def order_key(call_id: str, args: Mapping[str, Any]) -> str:
    business = {k: v for k, v in args.items() if k not in {"call_id", "turn_id", "purchase_authorization", "idempotency_key"}}
    # Preserve keys issued before consent receipts were added, including omitted optional fields.
    encoded = json.dumps(business, ensure_ascii=False, sort_keys=True, default=str)
    return f"{call_id}:order_create:{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"


def order_keys(call_id: str, args: Mapping[str, Any]) -> set[str]:
    variants = [payload(args)]
    for field in ("promo_code", "address"):
        if variants[0][field] is None:
            variants += [{k: v for k, v in variant.items() if k != field} for variant in variants]
    return {order_key(call_id, variant) for variant in variants}


def _owner(context: Any) -> str:
    return hashlib.sha256(_json([context.customer_id, context.customer_phone]).encode()).hexdigest()


def draft(args: Mapping[str, Any], context: Any, *, names: Mapping[str, str] | None = None,
          quotes: Mapping[str, int] | None = None) -> dict[str, Any]:
    """The order to read back, as it is said aloud: names and amounts, never a product code."""
    order = payload(args)
    known = {**{p.get("sku"): p.get("name") for p in context.seen_products if p.get("name")}, **(names or {})}
    address = context.vault.put("ADDR", order["address"]) if order["address"] else "chưa cung cấp địa chỉ"
    label = known.get(order["sku"]) or "đã chọn"
    promo = f", mã khuyến mãi: {order['promo_code']}" if order["promo_code"] else ""
    payment = {"COD": "trả tiền khi nhận hàng", "bank": "chuyển khoản"}.get(order["payment"], order["payment"])
    question = (f"Anh/chị xác nhận đặt {order['qty']} sản phẩm {label}, đơn giá {format_vnd(order['price_vnd'])}, "
                f"tổng {format_vnd(order['price_vnd'] * order['qty'])}, thanh toán {payment}{promo}, "
                f"địa chỉ giao hàng: {address}, đồng ý không ạ?")
    read_back = (f"Dạ em đọc lại đơn: {order['qty']} sản phẩm {label}, đơn giá {format_vnd(order['price_vnd'])}, "
                 f"tổng {format_vnd(order['price_vnd'] * order['qty'])}, thanh toán {payment}{promo}, "
                 f"địa chỉ giao hàng: {address}.")
    basket = [sku for sku in order.get("basket_skus") or [] if sku != order["sku"]]
    others = [known[sku] for sku in basket if known.get(sku)]
    if others:
        prices = [(quotes or {}).get(sku) for sku in basket]
        whole = "" if None in prices else f", tổng cả giỏ {format_vnd(order['price_vnd'] * order['qty'] + sum(prices))}"
        question = f"Đơn này đi cùng {', '.join(others)}{whole}. " + question
        read_back = f"Đơn này đi cùng {', '.join(others)}{whole}. " + read_back
    if order.get("order_group"):
        question = f"Đây là đơn {order['order_group']} của phần tách đơn. " + question
    return {"draft_id": uuid4().hex, "call_id": context.call_id, "channel": context.channel,
            "owner": _owner(context), "issued_turn_id": context.turn_id, "action_type": "order_create",
            "target_id": order["sku"], "payload_hash": fingerprint(order), "expires_at": now() + TTL_SECONDS,
            "status": "pending", "question": question, "read_back": read_back,
            "args": {k: (address if k == "address" else v) for k, v in order.items() if k in FILLED and v}}


def still_open(pending: Mapping[str, Any] | None, *, call_id: str, channel: str, turn_id: str) -> dict[str, Any] | None:
    """The read-back of this call still in force: until it expires or the order changes, whatever was said between."""
    if not pending or pending.get("status") != "pending":
        return None
    if (pending.get("call_id") != call_id or pending.get("channel") != channel
            or pending.get("issued_turn_id") == turn_id or pending.get("expires_at", 0) <= now()):
        return None
    return dict(pending)


def answer(pending: Mapping[str, Any] | None, *, call_id: str, channel: str, turn_id: str,
           said: str, last_reply: str | None) -> dict[str, Any] | None:
    """The fallback when the PolicyAgent gave no answer: a short yes to a read-back the customer just heard, nothing else."""
    opened = still_open(pending, call_id=call_id, channel=channel, turn_id=turn_id)
    if (opened is None or not last_reply or not last_reply.endswith(opened.get("question") or "\0")
            or not YES.fullmatch(plain(said).strip())):
        return None
    return authorize(opened, turn_id)


def authorize(draft_record: Mapping[str, Any], turn_id: str | None) -> dict[str, Any]:
    """A draft the customer agreed to, in this turn."""
    return {**draft_record, "status": "authorized", "confirmed_turn_id": turn_id}


def matches(pending: Mapping[str, Any] | None, args: Mapping[str, Any], context: Any) -> bool:
    return bool(pending and pending.get("status") == "authorized"
                and pending.get("call_id") == context.call_id and pending.get("channel") == context.channel
                and pending.get("owner") == _owner(context) and pending.get("action_type") == "order_create"
                and pending.get("confirmed_turn_id") == context.turn_id
                and pending.get("expires_at", 0) > now() and pending.get("payload_hash") == fingerprint(args))


def receipt(pending: Mapping[str, Any], args: Mapping[str, Any], context: Any) -> str | None:
    if not matches(pending, args, context):
        return None
    claims = {key: pending[key] for key in ("draft_id", "call_id", "action_type", "payload_hash", "expires_at")}
    claims["turn_id"] = context.turn_id
    encoded = base64.urlsafe_b64encode(_json(claims).encode()).decode()
    signature = hmac.new(derived_key("purchase-consent"), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def verify(token: str | None, args: Mapping[str, Any], call_id: str | None, turn_id: str | None) -> dict[str, Any]:
    """Verify binding here; expiry and consumed state are checked inside the write transaction."""
    try:
        encoded, signature = (token or "").split(".")
        expected = hmac.new(derived_key("purchase-consent"), encoded.encode(), hashlib.sha256).hexdigest()
        claims = json.loads(base64.urlsafe_b64decode(encoded))
        valid = (hmac.compare_digest(signature, expected) and call_id and turn_id
                 and claims["call_id"] == call_id and claims["turn_id"] == turn_id
                 and claims["action_type"] == "order_create" and claims["payload_hash"] == fingerprint(args)
                 and isinstance(claims["expires_at"], (int, float)) and bool(claims["draft_id"]))
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Purchase confirmation is missing or does not match this session and order")
    return claims
