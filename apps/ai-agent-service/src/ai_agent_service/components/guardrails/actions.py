"""The guardrail before act: checking a write tool's arguments. ``docs/design.md`` section 4.4.

The brief's figure puts GUARDRAIL before ACT. Before a tool with an effect
runs, the harness checks its arguments; a failure goes back to the model as
a tool error with the reason, and nothing happens in the business.

| Tool | Checked |
|---|---|
| ``order.create`` | a phone to order for; the tier allows it; the product code is trusted (it came from a tool this call or from the brief, never made up from a name); the unit price equals today's ``pricing.get_quote`` for that code; COD total at most 10.000.000đ; not the same product as an order this call already created, unless the customer wants one more (*intents* ``one_more``, read by Jev; the word list :data:`ONE_MORE` only when Jev gave no answer) |
| ``order.update`` | the order is one this customer has, or one a tool showed this call; the new variant is trusted; not the same change as one this call already made, in any turn (a second exchange is charged, DT-03); the customer asked for this change or agreed to it (*intents* ``change``, read by Jev: a complaint alone, "size M hơi chật", is not a choice yet). An order this call created may be corrected by its caller whatever the tier |
| ``schedule.callback`` | an ISO 8601 time with +07:00, inside working hours (LN-01, LN-02) and not in the past; otherwise the nearest working slot, for the model to propose |
| ``handoff.transfer`` | the advisor decides; outside lane HANDOFF Jev checks the transfer is warranted (*intents* ``handoff``: a request for a person, medical or legal advice, a serious complaint, a question the documents and tools do not answer); no answer from Jev leaves the advisor's decision standing. The brief validates against ``schemas/handoff_brief.schema.json`` itself (required fields, enums, phone pattern, summary length), after the harness filled in what it knows |
| ``memory.request_deletion`` | VERIFIED, and the customer agreed when asked to confirm (QT-06): *intents* ``delete``, read by Jev; the word lists only when Jev gave no answer |
| any write tool in copilot mode | refused: the consultant acts, the advisor only suggests (section 4.6) |

A customer the shop has never met may order on their own line: UNKNOWN with
a phone from the connection is allowed; PROBABLE and AMBIGUOUS are not,
because the order would be booked to someone who has not been confirmed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Sequence

from .. import btc_schemas, clock
from ..intake.itn import format_vnd
from ..intake.text import plain
from . import Verdict

WRITE_TOOLS = frozenset({"order_create", "order_update", "schedule_callback", "handoff_transfer", "memory_request_deletion"})
SKU_READ_TOOLS = frozenset({"pricing_get_quote", "inventory_check"})
CUSTOMER_READ_TOOLS = frozenset({"order_status", "crm_get_customer"})

COD_LIMIT_VND = 10_000_000

UPDATE_ACTIONS = frozenset({"exchange_size", "exchange_product", "return", "update_address"})

#: The fallback when Jev gives no answer (*intents* ``one_more``). The customer asks for one more of
#: what was ordered, on the plain (unaccented) text: a second
#: order of the same product is theirs to ask for, never the agent's way of adding an address.
ONE_MORE = re.compile(
    r"\b(mua them|dat them|lay them|them (?:mot|1|hai|2|ba|3) (?:cai|chiec|bo|don)|them (?:cai|chiec|don)|"
    r"(?:mot|1|hai|2) (?:cai|chiec|don) nua|cai nua|chiec nua|don (?:khac|moi|thu hai|nua))\b")

#: The fallback when Jev gives no answer (*intents* ``delete``): the agent asked to confirm a deletion;
#: the customer agreed (QT-06).
ASKED_TO_DELETE = re.compile(r"\bxoa\b.*\?|\bxac nhan\b.*\bxoa\b")
AGREED = re.compile(r"\b(dong y|dung roi|dung vay|xoa di|xoa giup|xoa het|ok|oke|vang|da|u|uh|co)\b")
DECLINED = re.compile(r"\b(khong|thoi|chua|de sau)\b")
#: Splitting an order was proposed or asked for (QT-01: only if the customer agrees).
SPLIT = re.compile(r"\btach\b")


def check(
    name: str,
    args: Mapping[str, Any],
    *,
    tier: str,
    mode: str,
    has_phone: bool,
    quotes: Mapping[str, int],
    orders: frozenset[str] = frozenset(),
    trusted: frozenset[str] | None = None,
    lane: str | None = None,
    intents: Mapping[str, bool | None] | None = None,
    now: datetime | None = None,
    last_agent_said: str | None = None,
    customer_said: str | None = None,
    deletion_asked: bool | None = None,
    shared_phone: bool = False,
    created: Sequence[Mapping[str, Any]] = (),
    updated: Sequence[Mapping[str, Any]] = (),
    placed: Sequence[Mapping[str, Any]] = (),
) -> Verdict:
    """Whether a write tool may run with *args*; the reasons if not.

    *trusted* is every product code this call has seen from a tool or the
    brief; None skips that check (a caller without the call's history).
    *intents* is what the customer means, where an action depends on it,
    read by the PolicyAgent on Jev (``handoff``, ``delete``, ``one_more``):
    True, False, or None when it gave no answer (a word list decides then,
    or, for a transfer, the advisor's decision stands).
    *created* is the orders this call created, ``{order_id, sku}``: the
    caller may correct those whatever the tier, and is not booked the same
    product twice unless they ask for more. *updated* is the arguments of the
    ``order_update`` calls that succeeded in this call: the same change is not
    made twice.
    *placed* are the order lines already created this call (:func:`placed_lines`).
    """
    created_ids = frozenset(str(o["order_id"]) for o in created if o.get("order_id"))
    if name in CUSTOMER_READ_TOOLS:
        if tier != "VERIFIED":
            return Verdict(False, ("Xác nhận danh tính khách trước khi đọc thông tin riêng.",))
        if name == "order_status":
            order_id = args.get("order_id")
            if order_id and order_id not in orders:
                return Verdict(False, ("Mã đơn chưa được xác minh cho khách này; tra order_status theo số đã xác minh trước, không đoán mã.",))
            if not order_id and shared_phone:
                return Verdict(False, ("Số dùng chung: chỉ tra mã đơn đã xác minh thuộc khách đang nói; không liệt kê đơn của cả số.",))
            if order_id:
                return Verdict(True)
        if not has_phone:
            return Verdict(False, ("Chưa có số đã xác minh để tra hồ sơ hoặc danh sách đơn.",))
        return Verdict(True)
    if name in SKU_READ_TOOLS:
        sku = args.get("sku")
        if trusted is not None and (not sku or sku not in trusted):
            return Verdict(False, ("Mã sản phẩm chưa được xác nhận; tra catalog_search và dùng đúng sku hoặc variant_sku trả về.",))
        return Verdict(True)
    if name not in WRITE_TOOLS:
        return Verdict(True)
    if mode == "copilot":
        return Verdict(False, ("Chế độ copilot: tư vấn viên thực hiện thao tác này, trợ lý chỉ gợi ý.",))
    checks = {
        "order_create": lambda: _order_create(args, tier=tier, has_phone=has_phone, quotes=quotes, trusted=trusted,
                                              created=created, customer_said=customer_said, placed=placed,
                                              said=f"{last_agent_said or ''} {customer_said or ''}",
                                              wants_more=(intents or {}).get("one_more")),
        "order_update": lambda: (["Xác nhận danh tính trước khi sửa đơn."]
                                 if tier != "VERIFIED" and args.get("order_id") not in created_ids
                                 else _order_update(args, orders=orders | created_ids, trusted=trusted,
                                                    updated=updated, agreed=(intents or {}).get("change"))),
        "schedule_callback": lambda: _schedule_callback(args, now=now),
        "handoff_transfer": lambda: _handoff(args, lane=lane, warranted=(intents or {}).get("handoff")),
        "memory_request_deletion": lambda: _deletion(tier=tier, last_agent_said=last_agent_said,
                                                     customer_said=customer_said, deletion_asked=deletion_asked, agreed=(intents or {}).get("delete")),
    }
    reasons = checks[name]()
    return Verdict(not reasons, tuple(reasons))


def placed_lines(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The order lines created by *results* (tool results, organisers' names), one per order id."""
    lines: dict[str, dict[str, Any]] = {}
    for result in results:
        envelope = result.get("result") or {}
        order_id = (envelope.get("data") or {}).get("order_id")
        if result.get("name") != "order.create" or not envelope.get("ok") or not order_id:
            continue
        args = result.get("args") or {}
        lines[order_id] = {"order_id": order_id, "sku": args.get("sku"), "qty": int(args.get("qty") or 1),
                           "price_vnd": int(args.get("price_vnd") or 0), "payment": args.get("payment") or "COD",
                           "order_group": args.get("order_group")}
    return list(lines.values())


def _cod_order(args: Mapping[str, Any], line: int, placed: Sequence[Mapping[str, Any]], said: str) -> list[str]:
    """VC-03 on the whole order: the COD lines of this call in the same ``order_group`` with this one.

    QT-01: an order above the limit may be split, if the customer agrees; the
    agent's previous turn proposed it or the customer asked (``tach``), or an
    earlier line of the call is already in a group.
    """
    group = args.get("order_group")
    if group is not None and not SPLIT.search(plain(said)) and not any(p.get("order_group") for p in placed):
        return ["Chỉ tách đơn khi khách đã đồng ý; hỏi khách có muốn tách thành hai đơn không trước khi đặt order_group."]
    if (args.get("payment") or "COD") != "COD":
        return []
    same = [p for p in placed if p.get("order_group") == group and p.get("payment") == "COD"]
    total = line + sum(int(p["price_vnd"]) * int(p["qty"]) for p in same)
    if total <= COD_LIMIT_VND:
        return []
    with_placed = f" (gồm {len(same)} món đã đặt trong cuộc gọi)" if same else ""
    if group is None:
        return [f"Đơn COD {format_vnd(total)}{with_placed} vượt giới hạn {format_vnd(COD_LIMIT_VND)}; đề nghị chuyển "
                "khoản, hoặc hỏi khách có muốn tách thành hai đơn, mỗi đơn COD tối đa 10.000.000đ (order_group \"1\", \"2\")."]
    return [f"Đơn tách {group} COD {format_vnd(total)}{with_placed} vẫn vượt giới hạn {format_vnd(COD_LIMIT_VND)}; "
            "xếp lại các món giữa hai đơn hoặc đề nghị chuyển khoản."]


def _order_create(args: Mapping[str, Any], *, tier: str, has_phone: bool, quotes: Mapping[str, int],
                  trusted: frozenset[str] | None, created: Sequence[Mapping[str, Any]] = (),
                  customer_said: str | None = None, placed: Sequence[Mapping[str, Any]] = (),
                  said: str = "", wants_more: bool | None = None) -> list[str]:
    again = [o for o in created if o.get("sku") and o.get("sku") == args.get("sku")]
    # The same sku in the other half of a split order (QT-01) is the order the customer agreed to, not a repeat.
    other_half = args.get("order_group") is not None and all(
        p.get("order_group") != args.get("order_group") for p in placed if p.get("sku") == args.get("sku"))
    if wants_more is None:
        wants_more = bool(ONE_MORE.search(plain(customer_said or "")))  # Jev gave no answer
    if again and not other_half and not wants_more:
        return [f"Đơn {again[-1]['order_id']} cho {args.get('sku')} đã tạo trong cuộc này. Khách bổ sung hay đổi địa chỉ, "
                "thanh toán thì gọi order_update trên đơn đó; chỉ tạo đơn mới khi khách muốn mua thêm."]
    reasons = []
    if not has_phone:
        reasons.append("Chưa có số điện thoại của khách để tạo đơn; xin số điện thoại trước.")
    if tier in ("PROBABLE", "AMBIGUOUS"):
        reasons.append("Danh tính khách chưa được xác nhận; hỏi xác nhận trước khi tạo đơn.")
    sku, price = args.get("sku"), args.get("price_vnd")
    if not sku or price is None:
        return reasons + ["Thiếu sku hoặc price_vnd."]
    if trusted is not None and sku not in trusted:
        reasons.append(f"Mã {sku} chưa xuất hiện trong kết quả tool của cuộc gọi; tra catalog_search để lấy đúng mã trước.")
    elif sku not in quotes:
        reasons.append(f"Chưa có báo giá hôm nay cho {sku}; gọi pricing_get_quote trước.")
    elif int(price) != quotes[sku]:
        reasons.append(f"price_vnd {format_vnd(int(price))} khác giá hôm nay của {sku} là {format_vnd(quotes[sku])}.")
    quantity = args.get("qty", 1)
    if quantity is None:
        quantity = 1
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return reasons + ["Số lượng phải là số nguyên dương."]
    qty = quantity
    return reasons + _cod_order(args, int(price) * qty, placed, said)


def _order_update(args: Mapping[str, Any], *, orders: frozenset[str], trusted: frozenset[str] | None,
                  updated: Sequence[Mapping[str, Any]] = (), agreed: bool | None = None) -> list[str]:
    order_id, action = args.get("order_id"), args.get("action")
    if not order_id:
        return ["Thiếu order_id."]
    if any(done.get("order_id") == order_id and done.get("action") == action
           and done.get("new_variant_sku") == args.get("new_variant_sku") for done in updated):
        # A second exchange of the same order is a new one, and charged (DT-03): the customer asked once.
        return [f"Đơn {order_id} đã được {action} đúng như vậy trong cuộc gọi này; không gọi lại. "
                "Báo khách kết quả và phí của lần trước."]
    reasons = []
    if order_id not in orders:
        reasons.append(f"Đơn {order_id} chưa thấy trong đơn của khách; tra order_status trước.")
    if action not in UPDATE_ACTIONS:
        reasons.append(f"action phải là một trong {', '.join(sorted(UPDATE_ACTIONS))}.")
    new = args.get("new_variant_sku")
    if action in ("exchange_size", "exchange_product"):
        if not new:
            reasons.append("Đổi size hay đổi sản phẩm cần new_variant_sku.")
        elif trusted is not None and new not in trusted:
            reasons.append(f"Mã {new} chưa xuất hiện trong kết quả tool của cuộc gọi; tra catalog_search hoặc inventory_check trước.")
    if agreed is False:
        reasons.append("Khách chưa chọn hay đồng ý thay đổi này: đề xuất cách xử lý (đổi size, đổi sản phẩm, trả hàng) "
                       "kèm phí theo chính sách, hỏi khách chọn, chỉ gọi order_update khi khách đồng ý (luật 20).")
    return reasons


def _schedule_callback(args: Mapping[str, Any], *, now: datetime | None) -> list[str]:
    moment = clock.parse_local(args.get("callback_at"))
    if moment is None:
        return ["callback_at phải là ngày giờ ISO 8601, ví dụ 2026-10-17T19:00+07:00."]
    if clock.is_working_time(moment) and (now is None or moment >= now):
        return []
    slot = clock.nearest_working_time(moment, not_before=now)
    why = "đã qua" if now is not None and moment < now else "ngoài giờ làm việc (thứ Hai đến thứ Bảy 08:00–21:00, Chủ nhật 09:00–18:00, nghỉ 26/10 và 01/01)"
    return [f"Giờ hẹn {clock.moment_label(moment)} {why}; đề xuất với khách {clock.moment_label(slot)} "
            f"({clock.iso_local(slot)}) rồi mới đặt lịch."]


def _handoff(args: Mapping[str, Any], *, lane: str | None, warranted: bool | None) -> list[str]:
    reasons = []
    if lane != "HANDOFF" and warranted is False:
        reasons.append("Cuộc này chưa cần chuyển máy: khách không xin gặp người, không xin lời khuyên y tế, thuốc hay "
                       "pháp lý, không khiếu nại nghiêm trọng, và câu hỏi trả lời được bằng tài liệu hoặc tool. Tư vấn "
                       "tiếp bằng tool (sản phẩm mẹ và bé: nêu thông số hãng).")
    return reasons + handoff_problems(args.get("brief") or {})


def handoff_problems(brief: Mapping[str, Any]) -> list[str]:
    """The brief against ``schemas/handoff_brief.schema.json`` itself, after the harness filled it.

    One exception: a chat customer who never gave a number. The consultant
    answers them in the same chat, so the brief goes without a phone; on the
    hotline a person must be able to call back, so the number is asked for.
    """
    problems: list[str] = []
    for error in btc_schemas.errors("handoff_brief", dict(brief)):
        field = error.split(":", 1)[0]
        if field == "customer_phone" and not brief.get("customer_phone"):
            if brief.get("channel") == "hotline":
                problems.append("Chưa có số điện thoại để tư vấn viên gọi lại; xin số điện thoại của khách trước khi chuyển.")
            continue
        problems.append(f"Handoff Brief sai schema ở {error}")
    # Never more than a few lines back to the model: the first ones say enough.
    return problems[:5]


def _deletion(*, tier: str, last_agent_said: str | None, customer_said: str | None,
              deletion_asked: bool | None = None, agreed: bool | None = None) -> list[str]:
    if tier != "VERIFIED":
        return ["Chưa xác minh danh tính nên chưa ghi nhận được yêu cầu xóa dữ liệu."]
    if agreed is False:
        return ["Khách chưa đồng ý xóa dữ liệu."]
    immediate = bool(last_agent_said and ASKED_TO_DELETE.search(plain(last_agent_said)))
    asked = immediate if deletion_asked is None else deletion_asked
    said = plain(customer_said or "")
    agreed = bool(AGREED.search(said)) and not DECLINED.search(said)
    if not immediate:
        agreed = agreed and bool(re.search(r'\b(?:dong y|xac nhan)\b.*\bxoa\b|\bxoa (?:di|giup|het)\b', said))
    if asked and agreed:
        return []
    return ["Hỏi khách xác nhận một câu là muốn xóa dữ liệu, đợi khách đồng ý rồi mới gọi memory_request_deletion."]


def deletion_succeeded(name: str, envelope: Mapping[str, Any]) -> bool:
    """Only the memory server's successful response shape is evidence of an erasure action."""
    data = envelope.get('data')
    if envelope.get('ok') is not True or not isinstance(data, dict):
        return False
    if name == 'memory.request_deletion':
        return (data.get('status') == 'recorded' and isinstance(data.get('request_id'), str)
                and re.fullmatch(r'D-[0-9a-f]{12}', data['request_id']) is not None
                and type(data.get('deleted_within_hours')) is int and data['deleted_within_hours'] == 72)
    if name == 'memory.delete_customer':
        deleted = data.get('deleted')
        return (isinstance(deleted, dict) and isinstance(data.get('customer_id'), str) and bool(data['customer_id'])
                and all(isinstance(key, str) and type(count) is int and count >= 0 for key, count in deleted.items()))
    return False


def fill_handoff(brief: Mapping[str, Any], known: Mapping[str, Any]) -> dict[str, Any]:
    """The model's brief with what the harness already knows filled in.

    The harness's values win for identity and time; the model's win for what
    only the conversation knows (reason, summary, open questions, next step).
    """
    filled = {k: v for k, v in known.items() if v is not None or k in ("product_advised", "price_quoted_vnd", "customer_name")}
    filled.update({k: v for k, v in brief.items() if k not in ("customer_phone", "generated_at", "customer_id")})
    filled.setdefault("open_questions", [])
    filled.setdefault("next_action", "Gọi lại khách và trả lời câu hỏi còn mở.")
    filled.setdefault("escalation_reason", "khac")
    return filled
