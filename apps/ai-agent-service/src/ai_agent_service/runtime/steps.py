"""What the agent is doing during a turn, as it does it: one step per tool call, for the chat and the staff console.

A turn binds a sink (:func:`bound`, ``runtime/harness.py``); every tool call made inside it, by the advisor
(``mcp/tools.ToolGuardMiddleware``) or by the harness (``mcp/tools.ToolBox``), opens a step with :func:`tool` and
closes it ok or failed with its duration. Each change goes:

- to the turn's stream (``api/routes/conversations.py``, SSE event ``step``). The customer's stream carries the
  label only (:func:`for_customer`): no tool name, no arguments, no result;
- to Valkey (``steps:{<call>}``, two minutes), so a staff console on any pod reads the steps of the turn in progress
  (``GET /calls/{id}``, ``live_steps``). Without ``AGENT_REDIS_URL``, this pod's memory;
- at the end, to the agent turn's ``meta.steps`` (the harness), so the console shows them after the turn too.

Arguments and results are never recorded: they hold tokens of phone numbers and CRM data. Nothing here may fail a
turn: every write is best effort.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator

from . import load

logger = logging.getLogger(__name__)

TTL_SECONDS = 120

#: What the customer reads while a tool runs. A tool missing here reads DEFAULT_LABEL.
LABELS = {
    "catalog_search": "Đang tìm sản phẩm phù hợp",
    "inventory_check": "Đang kiểm tra tồn kho",
    "pricing_get_quote": "Đang lấy giá và khuyến mãi",
    "pricing_quote_order": "Đang tính giá đơn hàng",
    "delivery_estimate": "Đang ước tính thời gian giao",
    "kb_search": "Đang tra chính sách cửa hàng",
    "kb_upsert": "Đang cập nhật ghi chú",
    "crm_get_customer": "Đang xem thông tin khách hàng",
    "identity_find": "Đang nhận diện khách hàng",
    "identity_link_provisional": "Đang nhận diện khách hàng",
    "memory_get_profile": "Đang xem lịch sử mua hàng",
    "memory_get_episodes": "Đang xem các lần trao đổi trước",
    "memory_get_open_items": "Đang xem việc còn dang dở",
    "memory_search_calls": "Đang xem các lần trao đổi trước",
    "memory_confirm_identity": "Đang xác nhận thông tin",
    "memory_commit_facts": "Đang ghi nhớ thông tin",
    "memory_commit_episode": "Đang ghi nhớ cuộc trò chuyện",
    "memory_settle_unconfirmed": "Đang ghi nhớ thông tin",
    "memory_request_deletion": "Đang xử lý yêu cầu xoá dữ liệu",
    "memory_delete_customer": "Đang xử lý yêu cầu xoá dữ liệu",
    "order_create": "Đang tạo đơn hàng",
    "order_status": "Đang kiểm tra đơn hàng",
    "order_update": "Đang cập nhật đơn hàng",
    "order_payment_qr": "Đang tạo mã QR thanh toán",
    "order_set_payment": "Đang đổi cách thanh toán",
    "account_orders": "Đang xem đơn hàng của bạn",
    "account_cart": "Đang xem giỏ hàng",
    "account_profile": "Đang xem tài khoản",
    "schedule_callback": "Đang đặt lịch gọi lại",
    "handoff_transfer": "Đang chuyển cho nhân viên",
}
DEFAULT_LABEL = "Đang tra cứu"

Sink = Callable[[dict[str, Any]], Awaitable[None]]


class _Turn:
    def __init__(self, call_id: str, sink: Sink | None) -> None:
        self.call_id = call_id
        self.sink = sink
        self.steps: list[dict[str, Any]] = []


_turn: contextvars.ContextVar[_Turn | None] = contextvars.ContextVar("turn_steps", default=None)
_local: dict[str, list[dict[str, Any]]] = {}


def label(tool_name: str) -> str:
    return LABELS.get(tool_name, DEFAULT_LABEL)


def for_customer(step: dict[str, Any]) -> dict[str, Any]:
    """What the shop's chat may see of a step."""
    return {key: step[key] for key in ("id", "label", "status") if key in step}


def key(call_id: str) -> str:
    return f"steps:{{{call_id}}}"


@contextmanager
def bound(call_id: Any, sink: Sink | None) -> Iterator[list[dict[str, Any]]]:
    """Around one turn: the steps of the tool calls made inside it. Yields the list, filled as they happen."""
    turn = _Turn(str(call_id), sink)
    token = _turn.set(turn)
    try:
        yield turn.steps
    finally:
        _turn.reset(token)


@asynccontextmanager
async def tool(name: str) -> AsyncIterator[dict[str, Any]]:
    """Around one tool call. Set ``step["ok"] = False`` inside to close it as failed (an error envelope)."""
    turn = _turn.get()
    if turn is None:
        yield {}
        return
    step = {"id": len(turn.steps) + 1, "tool": name, "label": label(name), "status": "running", "ms": None}
    turn.steps.append(step)
    started = time.perf_counter()
    await _publish(turn, step)
    try:
        yield step
    except BaseException:
        step["ok"] = False
        raise
    finally:
        step["status"] = "ok" if step.pop("ok", True) else "error"
        step["ms"] = int((time.perf_counter() - started) * 1000)
        await _publish(turn, step)


async def _publish(turn: _Turn, step: dict[str, Any]) -> None:
    if turn.sink is not None:
        try:
            await turn.sink(dict(step))
        except Exception as error:  # noqa: BLE001 - a closed stream must not fail the tool call
            logger.debug("Could not stream a step: %s", type(error).__name__)
    await _store(turn.call_id, turn.steps)


async def _store(call_id: str, steps: list[dict[str, Any]]) -> None:
    redis = load.client()
    if redis is None:
        _local[call_id] = [dict(step) for step in steps]
        return
    try:
        await redis.set(key(call_id), json.dumps(steps, ensure_ascii=False), ex=TTL_SECONDS)
    except Exception as error:  # noqa: BLE001 - the console falls back to the saved meta
        logger.debug("Could not store steps: %s", type(error).__name__)


async def clear(call_id: Any) -> None:
    """The turn is saved: its steps now live in the turn's meta."""
    call = str(call_id)
    redis = load.client()
    if redis is None:
        _local.pop(call, None)
        return
    try:
        await redis.delete(key(call))
    except Exception:  # noqa: BLE001
        pass


async def live(call_id: Any) -> list[dict[str, Any]]:
    """The steps of the turn in progress on this call, from any pod; empty between turns."""
    call = str(call_id)
    redis = load.client()
    if redis is None:
        return [dict(step) for step in _local.get(call, [])]
    try:
        raw = await redis.get(key(call))
    except Exception:  # noqa: BLE001
        return []
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []
