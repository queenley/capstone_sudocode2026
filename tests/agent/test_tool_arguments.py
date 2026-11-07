"""A stray argument must not cost the customer the tool call, and an honest "not transferred" is not a promise."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from ai_agent_service.agents.advisor import ActionGuardMiddleware, declared_arguments
from ai_agent_service.agents.policy import QUESTIONS
from ai_agent_service.components.guardrails import hard

SCHEMA = {"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["sku"]}


def tool() -> StructuredTool:
    """Built as the MCP adapter builds one: its schema is a dict."""

    async def run(**kwargs):
        return kwargs

    return StructuredTool(name="pricing_get_quote", description="x", args_schema=SCHEMA, coroutine=run)


def test_only_declared_arguments_reach_the_tool():
    args = {"sku": "SKU-AP-X", "qty": 1, "payment": "COD"}
    assert declared_arguments(tool(), args) == {"sku": "SKU-AP-X", "qty": 1}


def test_a_tool_that_declares_nothing_keeps_its_arguments():
    assert declared_arguments(None, {"sku": "X"}) == {"sku": "X"}


class Request:
    def __init__(self, name, args):
        self.tool_call = {"name": name, "args": args, "id": "1"}
        self.tool = tool()

    def override(self, *, tool_call):
        changed = Request(tool_call["name"], tool_call["args"])
        changed.tool_call = tool_call
        return changed


def call(args):
    seen = {}

    async def handler(request):
        seen.update(request.tool_call["args"])
        return "ran"

    done = asyncio.run(ActionGuardMiddleware().awrap_tool_call(Request("catalog_search", args), handler))
    return done, seen


def test_the_middleware_drops_a_stray_argument_before_the_call():
    assert call({"sku": "SKU-AP-X", "payment": "COD"}) == ("ran", {"sku": "SKU-AP-X"})


def test_arguments_all_declared_pass_untouched():
    assert call({"sku": "SKU-AP-X", "qty": 2}) == ("ran", {"sku": "SKU-AP-X", "qty": 2})


view = SimpleNamespace(check_handoff=True, tool_results=())


@pytest.mark.parametrize("text", [
    "Dạ em rất xin lỗi anh, hiện tại em chưa chuyển được máy cho nhân viên phụ trách ngay lúc này.",
    "Dạ em không kết nối được với nhân viên lúc này ạ.",
])
def test_saying_the_transfer_did_not_happen_is_not_a_promise(text):
    assert hard._transfer(text, view) == []


@pytest.mark.parametrize("text", [
    "Dạ em sẽ chuyển anh sang nhân viên phụ trách ạ.",
    "Dạ em chuyển máy cho nhân viên ngay, không để anh chờ lâu ạ.",
])
def test_a_real_promise_is_still_refused(text):
    assert hard._transfer(text, view)


def test_the_price_check_counts_what_the_documents_say():
    assert "policy passages" in QUESTIONS["unquoted_price"].instructions
