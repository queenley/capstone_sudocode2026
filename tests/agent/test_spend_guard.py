"""The spend switch: with the stop file present no model call goes out, chat model or Decisions. No model call."""

import pytest

from ai_agent_service.llm import decisions, spend_guard


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    path = tmp_path / "SPEND_STOP"
    monkeypatch.setenv("SPEND_STOP_FILE", str(path))
    monkeypatch.setenv("SPEND_SINCE", "2026-11-09T16:40:00Z")  # a run the assistant started on its own
    spend_guard.stop("test: the limit was reached")
    return path


def test_the_switch_raises_before_a_chat_model_call(stopped):
    with pytest.raises(spend_guard.SpendStopped, match="limit was reached"):
        spend_guard.StopSwitch().on_chat_model_start({}, [])


@pytest.mark.asyncio
async def test_a_decisions_request_is_never_sent_once_stopped(stopped, monkeypatch):
    def sent(*args, **kwargs):
        raise AssertionError("a request went out")

    monkeypatch.setattr(decisions, "_api", sent)
    with pytest.raises(spend_guard.SpendStopped):
        await decisions.evaluate("policy", [], {}, timeout=1)


def test_every_model_the_factory_makes_carries_the_switch(monkeypatch):
    """The real factory (the suite stubs it, so its function is read from the class's module), with the provider's
    constructor captured instead of called."""
    import importlib

    factory = importlib.reload(importlib.import_module("ai_agent_service.llm.factory"))
    made = {}
    monkeypatch.setattr(factory, "init_chat_model", lambda *args, **kwargs: made.update(kwargs) or object())
    monkeypatch.setattr(factory, "require_api_key", lambda provider: None)
    factory.LLMFactory.create_llm({"provider": "openai", "model": "gpt-4.1-mini"}, agent_name="memory",
                                   rate_limited=False)
    assert any(isinstance(cb, spend_guard.StopSwitch) for cb in made.get("callbacks") or [])


def test_a_person_s_run_is_never_stopped_even_with_the_stop_file(stopped, monkeypatch):
    monkeypatch.delenv("SPEND_SINCE")
    spend_guard.check()
    spend_guard.StopSwitch().on_chat_model_start({}, [])


def test_without_the_stop_file_calls_go_out(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEND_STOP_FILE", str(tmp_path / "none"))
    spend_guard.check()


def test_no_new_round_starts_at_the_planned_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEND_STOP_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("SPEND_SOFT_LIMIT_USD", "2")
    monkeypatch.setattr(spend_guard, "spent", lambda start=None: 2.0)
    with pytest.raises(spend_guard.SpendStopped, match="planned ceiling"):
        spend_guard.may_start()
    monkeypatch.setattr(spend_guard, "spent", lambda start=None: 1.99)
    spend_guard.may_start()


def test_a_run_whose_spend_cannot_be_read_is_stopped_not_left_unwatched(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setenv("SPEND_STOP_FILE", str(tmp_path / "STOP"))

    def unreadable(start=None):
        raise httpx.HTTPError("429")

    monkeypatch.setattr(spend_guard, "spent", unreadable)
    monkeypatch.setattr(spend_guard.time, "sleep", lambda seconds: None)
    assert spend_guard.watch(None, deadline_minutes=60, every=0, blind=0) == 3
    assert "could not be read" in (tmp_path / "STOP").read_text(encoding="utf-8")


def test_a_langfuse_that_refuses_new_traces_blocks_every_paid_run(monkeypatch, tmp_path, capsys):
    import httpx

    monkeypatch.setenv("SPEND_STOP_FILE", str(tmp_path / "STOP"))
    monkeypatch.setenv("SPEND_SINCE", "2026-11-09T16:40:00Z")
    for name in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.setenv(name, "https://langfuse.example" if name.endswith("URL") else "k")

    def post(url, **kwargs):
        return httpx.Response(403, text='{"message":"Ingestion suspended: Usage threshold exceeded."}',
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(spend_guard.httpx, "post", post)
    assert spend_guard.main(["status"]) == 3
    assert "UNREADABLE" in capsys.readouterr().out
