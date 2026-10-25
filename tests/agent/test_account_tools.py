"""The website account's tools (mcp/servers/account.py) reach only the logged-in shopper of the call."""
from types import SimpleNamespace

from ai_agent_service.mcp.tools import LaneToolsMiddleware, ToolGuardMiddleware


class Request(SimpleNamespace):
    def override(self, **changes):
        return Request(**{**self.__dict__, **changes})


def tool(name, args=("account_id",)):
    return SimpleNamespace(name=name, args={a: {} for a in args})


LANES = {"CONTINUITY": frozenset({"account_cart", "catalog_search"})}
NAMES = ["account_cart", "catalog_search"]


def offered(account_id):
    request = Request(runtime=SimpleNamespace(context=SimpleNamespace(lane="CONTINUITY", account_id=account_id)),
                      tools=[tool("account_cart"), tool("catalog_search", ("query",))])
    return [t.name for t in LaneToolsMiddleware(LANES, NAMES)._filtered(request).tools]


def test_account_tools_are_offered_only_to_a_logged_in_shopper():
    assert offered(None) == ["catalog_search"]
    assert offered("cust-1") == ["account_cart", "catalog_search"]


def test_the_account_is_the_call_s_never_the_model_s():
    guard = ToolGuardMiddleware.__new__(ToolGuardMiddleware)
    context = SimpleNamespace(account_id="cust-1", on=None, customer_phone=None, tier="UNKNOWN", lane="CONTINUITY",
                              addresses={}, vault=None, customer_id=None, call_id=None)
    request = Request(runtime=SimpleNamespace(context=context), tool=tool("account_cart"),
                      tool_call={"name": "account_cart", "args": {"account_id": "someone-else"}, "id": "1"})
    assert guard._with_context(request).tool_call["args"] == {"account_id": "cust-1"}


def test_a_logged_in_account_s_name_settles_a_shared_number():
    from ai_agent_service.components.identity.resolver import Match, pick_by_account
    oanh, hoa = Match("C031", "Oanh", "chị"), Match("C099", "Hoa", "chị")
    assert pick_by_account("Trần Thị Oanh", [oanh, hoa]) is oanh
    assert pick_by_account("Nguyễn Văn Bình", [oanh, hoa]) is None
    assert pick_by_account(None, [oanh, hoa]) is None
    # Two candidates both named by it: still the question, never a guess.
    assert pick_by_account("Trần Thị Oanh", [oanh, Match("C100", "Thị Oanh", "cô")]) is None
