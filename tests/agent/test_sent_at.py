"""A tester's chosen moment for a chat message or a call (``sent_at``): parsed in Vietnam time, off in production."""

import pytest

from ai_agent_service.components import clock
from ai_agent_service.runtime import options


def test_a_moment_without_an_offset_is_vietnam_time():
    moment = clock.parse_sent_at("2026-10-20T19:30")
    assert clock.tool_time(moment) == "2026-10-20T19:30"
    assert clock.on(moment) == "2026-10-20"


def test_a_bare_day_is_the_call_time_and_an_offset_is_converted():
    assert clock.parse_sent_at("2026-11-11") == clock.at("2026-11-11")
    assert clock.tool_time(clock.parse_sent_at("2026-10-20T12:00+00:00")) == "2026-10-20T19:00"


@pytest.mark.parametrize("value", [None, "", "   ", "tomorrow", "2026-13-01", 20261020])
def test_anything_else_is_not_a_moment(value):
    assert clock.parse_sent_at(value) is None


def test_empty_means_the_shops_clock(monkeypatch):
    monkeypatch.delenv("CLIENT_CLOCK", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert options.sent_at(None) is None
    assert options.sent_at("") is None
    assert options.sent_at("2026-10-20T19:30") == clock.parse_sent_at("2026-10-20T19:30")
    with pytest.raises(ValueError):
        options.sent_at("not a time")


@pytest.mark.parametrize("environment,flag,allowed", [
    ("development", "", True),
    ("production", "", False),
    ("production", "1", True),
    ("development", "0", False),
])
def test_production_ignores_it_unless_turned_on(monkeypatch, environment, flag, allowed):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("CLIENT_CLOCK", flag)
    assert options.client_clock_allowed() is allowed
    assert (options.sent_at("2026-10-20T19:30") is not None) is allowed
