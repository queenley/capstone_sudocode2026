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
NO = re.compile(r"\b(?:khong (?:mua|dat|dong y)|huy|thoi|de sau)\b")
#: A yes as people give it after the read-back ("Đúng rồi em, lên đơn giúp chị nhé"): a consent phrase, and beside it
#: only address words and courtesy. Anything else left over ("đúng rồi nhưng đổi địa chỉ") keeps it from being a yes.
CONSENT = re.compile(r"\b(?:dong y|xac nhan|dung(?: roi)?|chinh xac|vang|u|uh|um|ok|oke|"
                     r"(?:len|lam|ghi) don|(?:dat|chot)(?: don| hang| may)?|mua)\b")
#: "vậy", "làm (cho)", "luôn" are filler around a yes ("Ừ, vậy em lên đơn cho anh luôn đi", "Chị đồng ý lên đơn rồi, em
#: làm cho chị nhé": eval2 SCN-GEN-0232, SCN-GEN-0240). A word that changes the order ("đổi", "nhưng", "thêm", a
#: number) is not here, so "đúng rồi nhưng đổi địa chỉ" still is no yes.
COURTESY = re.compile(r"\b(?:da|a|nhe|nha|nhen|em|anh|chi|co|chu|cau|bac|toi|minh|chau|con|oi|giup|gium|cho|luon|di|"
                      r"voi|nhu vay|vay|lam|thong tin|la|du|roi|cam on|nay)\b")


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


def missing(args: Mapping[str, Any], order: Mapping[str, Any], delivery: str | None) -> list[str]:
    """What the order still lacks before it may be read back (PB-09), in the words the model is told.

    Product and today's price are the action guard's (a trusted code, the current quote); the quantity reads back as
    1 unless said. The payment must be one the model passed, from the customer or the brief: :func:`payload` would
    write COD for a missing one, and a read-back the customer answers by naming the payment is a read-back wasted
    (eval2: 116 of 153 read-backs were answered with a missing field, not a yes).
    """
    gaps = []
    if not args.get("payment"):
        gaps.append("phương thức thanh toán khách chọn (COD hay chuyển khoản)")
    if not order.get("address"):
        gaps.append("địa chỉ giao hàng (lời khách hoặc Call Brief)")
    if not delivery:
        gaps.append("ngày giao dự kiến (gọi delivery_estimate với địa chỉ giao)")
    return gaps


def estimated_delivery(results: Any) -> str | None:
    """The day the latest successful ``delivery.estimate`` of the call gave, ``YYYY-MM-DD``."""
    for result in reversed(list(results or ())):
        envelope = result.get("result") if isinstance(result, Mapping) else None
        if str(result.get("name", "")).replace("_", ".", 1) != "delivery.estimate" or not isinstance(envelope, Mapping):
            continue
        data = envelope.get("data") if "data" in envelope else envelope
        if (envelope.get("ok", True) and isinstance(data, Mapping) and data.get("estimated_delivery")
                and data.get("address_known", True)):
            return str(data["estimated_delivery"])[:10]
    return None


def _day(value: str) -> str:
    year, month, day = (int(part) for part in value.split("-"))
    return f"{day}/{month}/{year}"


def draft(args: Mapping[str, Any], context: Any, delivery: str | None = None, *,
          names: Mapping[str, str] | None = None, quotes: Mapping[str, int] | None = None) -> dict[str, Any]:
    """The order to read back, as it is said aloud: names and amounts, never a product code; with *delivery*,
    the day :func:`estimated_delivery` found."""
    order = payload(args)
    known = {**{p.get("sku"): p.get("name") for p in context.seen_products if p.get("name")}, **(names or {})}
    address = context.vault.put("ADDR", order["address"]) if order["address"] else "chưa cung cấp địa chỉ"
    label = known.get(order["sku"]) or "đã chọn"
    promo = f", mã khuyến mãi: {order['promo_code']}" if order["promo_code"] else ""
    payment = {"COD": "trả tiền khi nhận hàng", "bank": "chuyển khoản"}.get(order["payment"], order["payment"])
    arrives = f", giao dự kiến ngày {_day(delivery)}" if delivery else ""
    question = (f"Anh/chị xác nhận đặt {order['qty']} sản phẩm {label}, đơn giá {format_vnd(order['price_vnd'])}, "
                f"tổng {format_vnd(order['price_vnd'] * order['qty'])}, thanh toán {payment}{promo}, "
                f"địa chỉ giao hàng: {address}{arrives}, đồng ý không ạ?")
    read_back = (f"Dạ em đọc lại đơn: {order['qty']} sản phẩm {label}, đơn giá {format_vnd(order['price_vnd'])}, "
                 f"tổng {format_vnd(order['price_vnd'] * order['qty'])}, thanh toán {payment}{promo}, "
                 f"địa chỉ giao hàng: {address}{arrives}.")
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
            or not agrees(said)):
        return None
    return authorize(opened, turn_id)


def authorize(draft_record: Mapping[str, Any], turn_id: str | None) -> dict[str, Any]:
    """A draft the customer agreed to, in this turn."""
    return {**draft_record, "status": "authorized", "confirmed_turn_id": turn_id}


def agrees(said: str) -> bool:
    """Whether *said*, the whole of it, is a yes to the question just read out."""
    if YES.fullmatch(plain(said).strip()):
        return True
    rest, found = CONSENT.subn(" ", " ".join(re.findall(r"[a-z0-9]+", plain(said))))
    return bool(found) and not COURTESY.sub(" ", rest).strip()


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
