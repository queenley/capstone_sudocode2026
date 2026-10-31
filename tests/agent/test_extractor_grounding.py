"""An extractor must not turn politeness, deletion deadlines or surcharges into unrelated claims."""
import pytest

from ai_agent_service.components.evaluation.scorers import label_items


def claim(field, value, quote):
    return {"kind": "claim", "slot_or_field": field, "value": value, "question_type": None, "speaker": "agent",
            "source_field": "agent_text", "quote": quote, "start": 0, "end": len(quote), "purpose": "claim"}


def labels(field, value, quote, agent_text=None):
    return label_items([claim(field, value, quote)], {"agent_text": agent_text or quote, "tool_texts": [], "consultant_texts": []})


@pytest.mark.parametrize("quote", ["Dạ, em sẵn sàng hỗ trợ ạ.", "Em không tiếp nhận CCCD qua hội thoại.",
                                  "Em sẽ chuyển anh sang nhân viên thật."])
def test_human_claim_needs_an_explicit_self_assertion(quote):
    result = labels("is_human", True, quote)
    assert result["claims"] == []
    assert result["changed"] == 1


@pytest.mark.parametrize("value,quote", [(True, "Em là người thật."), (False, "Em là trợ lý ảo của shop.")])
def test_explicit_identity_claim_is_preserved(value, quote):
    result = labels("is_human", value, quote)
    assert result["claims"][0]["value"] is value


def test_a_quote_not_in_the_reply_is_not_used_as_evidence():
    result = labels("price_vnd", 5200000, "Giá là 5.200.000đ.", agent_text="Em sẽ kiểm tra giá.")
    assert result["claims"] == []
    assert result["dropped"] == 1


@pytest.mark.parametrize("field,value,quote", [
    ("delivery_days", 3, "Dữ liệu được xóa trong vòng 72 giờ."),
    ("price_vnd", 50000, "Size này phụ thu 50.000đ."),
])
def test_field_subject_must_match_the_quote(field, value, quote):
    result = labels(field, value, quote)
    assert result["claims"] == []
    assert result["changed"] == 1


def test_a_value_is_written_in_its_fields_type():
    result = labels("price_vnd", "5.200.000đ", "giá 5.200.000đ")
    assert result["claims"] == [{"field": "price_vnd", "value": 5200000, "text": "giá 5.200.000đ"}]


def test_a_value_that_cannot_be_typed_is_set_aside_not_written_as_false():
    result = labels("price_vnd", "rất rẻ", "giá rất rẻ")
    assert result["claims"] == []
    assert result["changed"] == 1


def test_a_claim_quoted_from_a_tool_request_is_not_the_agents_claim():
    item = {**claim("price_vnd", 4900000, '"price_vnd": 4900000'), "source_field": "tool_texts/0"}
    data = {"agent_text": "Dạ em lên đơn ạ.", "tool_texts": ['{"args": {"price_vnd": 4900000}, "name": "order.create"}'],
            "consultant_texts": []}
    assert label_items([item], data)["claims"] == []
