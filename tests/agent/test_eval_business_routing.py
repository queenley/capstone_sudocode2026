"""The evaluation routes business tools to the organisers' mock, which has no idempotency_key."""
import asyncio
import json
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evaluation"))

from agent import runner  # noqa: E402


class _Args(BaseModel):
    sku: str
    idempotency_key: str | None = None


def test_routed_business_tool_drops_idempotency_key():
    seen = {}

    async def business(name, args):
        seen[name] = args
        return {"ok": True}

    async def noop(**_):
        return ""

    tool = StructuredTool.from_function(coroutine=noop, name="order_create", description="d", args_schema=_Args)
    routed = runner._routed([tool], business)[0]
    out = asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "k"}))
    assert json.loads(out) == {"ok": True}
    assert seen["order.create"] == {"sku": "S"}


def test_a_repeated_idempotency_key_returns_the_first_answer_without_a_second_call():
    calls = []

    async def business(name, args):
        calls.append(args)
        return {"ok": True, "data": {"order_id": f"OD{len(calls)}"}}

    async def noop(**_):
        return ""

    tool = StructuredTool.from_function(coroutine=noop, name="order_create", description="d", args_schema=_Args)
    routed = runner._routed([tool], business)[0]
    first = asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "call:order_create:abc"}))
    again = asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "call:order_create:abc"}))
    other = asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "call:order_create:def"}))
    assert first == again and len(calls) == 2
    assert json.loads(other)["data"]["order_id"] == "OD2"


def test_a_failed_write_is_not_remembered_so_it_can_be_retried():
    calls = []

    async def business(name, args):
        calls.append(1)
        return {"ok": False, "error": {"code": "X"}}

    async def noop(**_):
        return ""

    tool = StructuredTool.from_function(coroutine=noop, name="order_create", description="d", args_schema=_Args)
    routed = runner._routed([tool], business)[0]
    asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "k"}))
    asyncio.run(routed.ainvoke({"sku": "S", "idempotency_key": "k"}))
    assert len(calls) == 2
