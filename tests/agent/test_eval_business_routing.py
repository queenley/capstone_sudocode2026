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
