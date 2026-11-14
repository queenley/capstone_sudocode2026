"""Entries for a product and a campaign: found for that product, gone when the campaign ends. And the prompt cache count."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from ai_agent_service.agents.advisor import shown_passages
from ai_agent_service.components import knowledge
from ai_agent_service.components.knowledge.corpus import Chunk, covers, entry_chunk, with_campaigns
from ai_agent_service.components.knowledge.search import KnowledgeBase
from ai_agent_service.llm import token_ledger
from ai_agent_service.llm.callback_handler import cached_tokens
from ai_agent_service.pipeline.eval.performance import _per_turn, _tokens

CATEGORIES = {"SKU-AP-X": "gia-dung/may-loc-khong-khi", "SKU-SN-RUN2": "thoi-trang/giay"}
PROMOTION = {"promo_code": "SALE-1111", "start": "2026-11-11", "end": "2026-11-12", "applies_to": ["category:gia-dung"]}


def entry(chunk_id="FAQ-T-1", **more) -> Chunk:
    return entry_chunk({"chunk_id": chunk_id, "source": "faq", "title": "Đợt sale ưu đãi cộng dồn",
                        "text": "Ưu đãi đợt sale không cộng dồn.", **more}, doc="v1.jsonl")


def base(*entries: Chunk) -> KnowledgeBase:
    other = Chunk("VC-99", "x.md", "Vận chuyển", "Giao hàng", "Đơn giao trong hai ngày.")
    return KnowledgeBase([other, *with_campaigns(entries, [PROMOTION])], categories=CATEGORIES)


def test_a_campaign_takes_its_days_and_products_from_its_promotion():
    chunk = with_campaigns([entry(campaign="SALE-1111")], [PROMOTION])[0]
    assert (chunk.valid_from, chunk.valid_to, chunk.applies_to) == ("2026-11-11", "2026-11-12", ("category:gia-dung",))


def test_an_entry_keeps_its_own_days_over_the_promotions():
    chunk = with_campaigns([entry(campaign="SALE-1111", valid_to="2026-11-30")], [PROMOTION])[0]
    assert chunk.valid_to == "2026-11-30"


def test_a_campaign_that_could_never_end_is_refused():
    with pytest.raises(ValueError, match="no valid_to"):
        with_campaigns([entry(campaign="Tết")], [PROMOTION])
    assert with_campaigns([entry(campaign="Tết", valid_to="2027-02-20")], [PROMOTION])[0].valid_to == "2027-02-20"


def test_applies_to_must_be_a_list():
    with pytest.raises(ValueError, match="list"):
        entry(applies_to="SKU-AP-X")


def test_the_campaign_and_product_survive_the_database_column():
    chunk = entry(campaign="SALE-1111", applies_to=["SKU-AP-X"])
    assert chunk.provenance == {"campaign": "SALE-1111", "applies_to": ["SKU-AP-X"]}


def test_the_entry_ends_with_its_campaign():
    kb = base(entry(campaign="SALE-1111"))
    ids = lambda on: [hit.chunk.chunk_id for hit in kb.search("đợt sale ưu đãi cộng dồn", on=on).hits]
    assert "FAQ-T-1" in ids("2026-11-12")
    assert "FAQ-T-1" not in ids("2026-11-13") and "FAQ-T-1" not in ids("2026-11-10")


@pytest.mark.parametrize("targets, sku, category, expected", [
    (["SKU-AP-X"], "SKU-AP-X", None, True),
    (["SKU-SN-RUN2"], "SKU-SN-RUN2-42", None, True),
    (["category:gia-dung"], "SKU-AP-X", "gia-dung/may-loc-khong-khi", True),
    (["category:gia"], "SKU-AP-X", "gia-dung/may-loc-khong-khi", False),
    (["*"], "SKU-AP-X", None, True),
    (["SKU-AP"], "SKU-AP-X", None, True),
    (["SKU-AP-X"], "SKU-AP-Y", None, False),
])
def test_targets_match_as_promotions_write_them(targets, sku, category, expected):
    assert covers(targets, sku, category) is expected


def test_an_entry_for_another_product_is_left_out_and_with_no_product_it_is_found():
    kb = base(entry(applies_to=["category:gia-dung"]))
    question = "đợt sale ưu đãi cộng dồn"
    assert "FAQ-T-1" in [h.chunk.chunk_id for h in kb.search(question, on="2026-11-11").hits]
    assert "FAQ-T-1" not in [h.chunk.chunk_id for h in kb.search(question, on="2026-11-11", about=["SKU-SN-RUN2"]).hits]
    found = kb.search(question, on="2026-11-11", about=["SKU-AP-X"]).hits
    assert [h.for_product for h in found if h.chunk.chunk_id == "FAQ-T-1"] == [True]


def test_a_campaign_entry_for_this_product_is_read_beyond_the_three_at_most_one():
    plain = [{"chunk_id": f"DT-0{n}"} for n in range(1, 4)]
    campaign = [{"chunk_id": f"FAQ-{n}", "campaign": "X", "for_product": True} for n in (1, 2)]
    read, _ = shown_passages([*plain, *campaign])
    assert [p["chunk_id"] for p in read] == ["DT-01", "DT-02", "DT-03", "FAQ-1"]


def test_a_campaign_entry_for_no_product_of_this_call_gets_no_extra_place():
    plain = [{"chunk_id": f"DT-0{n}"} for n in range(1, 4)]
    read, _ = shown_passages([*plain, {"chunk_id": "FAQ-1", "campaign": "X", "for_product": False}])
    assert len(read) == 3


def test_a_campaign_entry_already_among_the_three_takes_no_second_place():
    first = [{"chunk_id": "FAQ-1", "campaign": "X", "for_product": True}, {"chunk_id": "A"}, {"chunk_id": "B"}]
    read, _ = shown_passages([*first, {"chunk_id": "FAQ-2", "campaign": "X", "for_product": True}])
    assert "FAQ-2" not in [p["chunk_id"] for p in read]


def test_the_shipped_promotions_and_products_load():
    assert all(promotion["promo_code"] for promotion in knowledge.promotions())
    assert knowledge._categories()["SKU-AP-X"] == "gia-dung/may-loc-khong-khi"
    assert knowledge._categories()["SKU-SN-RUN1-38-DEN"].startswith("thoi-trang")


def llm_result(cache_read: int) -> LLMResult:
    usage = {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105, "input_token_details": {"cache_read": cache_read}}
    return LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x", usage_metadata=usage))]])


def test_the_ledger_counts_what_the_cache_served():
    assert cached_tokens(llm_result(64)) == 64
    token_ledger.reset()
    token_ledger.record("advisor", 100, 5, 64)
    assert token_ledger.snapshot()["advisor"] == {"calls": 1, "input": 100, "output": 5, "cached": 64}
    token_ledger.reset()


def test_a_run_from_before_the_count_says_unknown_not_zero():
    old = _tokens([{"turns": {"advisor": {"calls": 1, "input": 100, "output": 5}}}], "turns")
    new = _tokens([{"turns": {"advisor": {"calls": 1, "input": 100, "output": 5, "cached": 25}}}], "turns")
    assert _per_turn(old, 1)["cached_share"] is None
    assert _per_turn(new, 1)["cached_share"] == 25.0


def test_cached_tokens_are_summed_once_across_calls():
    # eval_3 showed 133.6%: from the second call on, "cached" was added twice.
    entry = {"turns": {"advisor": {"calls": 1, "input": 100, "output": 5, "cached": 25}}}
    tokens = _tokens([entry, entry, entry], "turns")
    assert tokens["advisor"] == {"calls": 3, "input": 300, "output": 15, "cached": 75}
    assert _per_turn(tokens, 3)["cached_share"] == 25.0


def test_requests_carry_a_cache_key_per_agent():
    from langchain_openai import ChatOpenAI

    from ai_agent_service.llm.factory import cache_options

    # The key must reach the request itself, not stop at the client.
    model = ChatOpenAI(model="gpt-4.1-mini", api_key="test", **cache_options("openai", "advisor"))
    assert model._get_request_payload([("human", "x")])["prompt_cache_key"] == "advisor"


def test_other_providers_get_no_cache_key():
    from ai_agent_service.llm.factory import cache_options

    assert cache_options("google_genai", "advisor") == {} and cache_options("openai", "") == {}
