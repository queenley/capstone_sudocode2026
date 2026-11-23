"""The live steps of a turn (runtime/steps.py): one per tool call, streamed to the chat as a label only, kept for
the staff console while the turn runs."""
import asyncio

import pytest

from ai_agent_service.mcp.tools import ToolBox
from ai_agent_service.runtime import load, steps


@pytest.fixture(autouse=True)
def no_valkey(monkeypatch):
    monkeypatch.delenv("AGENT_REDIS_URL", raising=False)
    load.set_client(None)
    yield
    load.set_client(None)


class FakeTool:
    def __init__(self, name, answer):
        self.name, self.answer = name, answer

    async def ainvoke(self, args):
        await asyncio.sleep(0)
        return self.answer


def run(coro):
    return asyncio.run(coro)


def test_a_tool_call_opens_then_closes_a_step_with_its_label_and_duration():
    heard = []

    async def sink(step):
        heard.append(step)

    async def turn():
        with steps.bound(7, sink) as made:
            async with steps.tool("catalog_search"):
                live = await steps.live(7)
            return made, live

    made, live = run(turn())
    assert [(s["status"], s["label"]) for s in heard] == [("running", "Đang tìm sản phẩm phù hợp"),
                                                          ("ok", "Đang tìm sản phẩm phù hợp")]
    assert live == [{"id": 1, "tool": "catalog_search", "label": "Đang tìm sản phẩm phù hợp", "status": "running", "ms": None}]
    assert made[0]["status"] == "ok" and isinstance(made[0]["ms"], int)


def test_a_failed_envelope_and_an_exception_both_close_the_step_as_an_error():
    async def turn():
        with steps.bound(8, None) as made:
            async with steps.tool("kb_search") as step:
                step["ok"] = False
            with pytest.raises(RuntimeError):
                async with steps.tool("order_status"):
                    raise RuntimeError("down")
            return made

    assert [(s["tool"], s["status"]) for s in run(turn())] == [("kb_search", "error"), ("order_status", "error")]


def test_the_customer_sees_the_label_only():
    step = {"id": 2, "tool": "crm_get_customer", "label": "Đang xem thông tin khách hàng", "status": "ok", "ms": 40}
    assert steps.for_customer(step) == {"id": 2, "label": "Đang xem thông tin khách hàng", "status": "ok"}


def test_an_unknown_tool_reads_a_plain_label():
    assert steps.label("something_new") == steps.DEFAULT_LABEL


def test_outside_a_turn_a_tool_call_records_nothing():
    async def alone():
        async with steps.tool("catalog_search") as step:
            return step

    assert run(alone()) == {}


def test_the_harness_toolbox_records_each_call_and_its_outcome():
    box = ToolBox([FakeTool("inventory_check", '{"ok": true, "data": {"stock": 3}}'),
                   FakeTool("pricing_get_quote", '{"ok": false, "error": {"code": "NOT_FOUND", "retryable": false, "message": "x"}}')])

    async def turn():
        with steps.bound(9, None) as made:
            await box.call("inventory_check", sku="A")
            await box.call("pricing_get_quote", sku="B")
            await box.call("not_a_tool")
            return made

    assert [(s["tool"], s["status"]) for s in run(turn())] == [("inventory_check", "ok"), ("pricing_get_quote", "error")]


def test_clear_empties_the_live_steps_once_the_turn_is_saved():
    async def turn():
        with steps.bound(10, None):
            async with steps.tool("catalog_search"):
                pass
        before = await steps.live(10)
        await steps.clear(10)
        return before, await steps.live(10)

    before, after = run(turn())
    assert len(before) == 1 and after == []


def test_the_valkey_key_has_a_hash_tag():
    assert steps.key(12) == "steps:{12}"
