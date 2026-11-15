"""The staff queue groups an unverified session with the customer whose number it gave, when that number is theirs
alone (api/routes/agent_calls.py ``_same_number``): chị Hoa's web chat is not a stranger "Số đuôi 6714"."""
from types import SimpleNamespace

import pytest

from ai_agent_service.api.routes import agent_calls
from ai_agent_service.mcp.servers import btc
from ai_agent_service.runtime import vault as vaults

CRM = {
    "0984726714": {"found": True, "customer_id": "C001", "name": "Nguyễn Thị Hoa"},
    "0911000000": {"found": True, "ambiguous": True},
}


@pytest.fixture()
def rig(monkeypatch):
    phones = {2: {"<PHONE_1>": ("PHONE", "0984726714")}, 5: {"<PHONE_1>": ("PHONE", "0911000000")},
              6: {"<PHONE_1>": ("PHONE", "0900000001")},
              7: {"<PHONE_1>": ("PHONE", "0984726714"), "<PHONE_2>": ("PHONE", "0123456714")}}

    async def load(call_id):
        return SimpleNamespace(entries=phones.get(call_id, {}))

    monkeypatch.setattr(vaults, "load", load)
    monkeypatch.setattr(btc, "mock", lambda: SimpleNamespace(
        crm_get_customer=lambda phone: CRM.get(phone, {"found": False})))


@pytest.mark.asyncio
async def test_an_unverified_session_joins_the_one_customer_who_owns_its_number(rig):
    rows = [
        {"id": 1, "customer_id": "C001", "phone_last4": "6714"},  # identified: grouped already
        {"id": 2, "customer_id": None, "phone_last4": "6714"},  # chị Hoa's number, unverified
        {"id": 3, "customer_id": None, "phone_last4": None},  # a guest
        {"id": 5, "customer_id": None, "phone_last4": "0000"},  # a number two customers share
        {"id": 6, "customer_id": None, "phone_last4": "0001"},  # nobody in the CRM
        {"id": 7, "customer_id": None, "phone_last4": "6714"},  # two numbers ending 6714: which one is unknown
    ]
    assert await agent_calls._same_number(rows) == {2: "C001"}
