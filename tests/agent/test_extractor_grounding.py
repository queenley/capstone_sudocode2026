"""An extractor must not turn politeness, deletion deadlines or surcharges into unrelated claims."""
import pytest

from ai_agent_service.components.evaluation.scorers import shape


def labels(field, value, quote):
    return {"questions": [], "claims": [{"field": field, "value_json": value, "text": quote}]}


@pytest.mark.parametrize("quote", ["Dạ, em sẵn sàng hỗ trợ ạ.", "Em không tiếp nhận CCCD qua hội thoại.",
                                  "Em sẽ chuyển anh sang nhân viên thật."])
def test_human_claim_needs_an_explicit_self_assertion(quote):
    result = shape(labels("is_human", "true", quote), agent_text=quote)
    assert result["claims"] == []
    assert result["set_aside"][0]["reason"] == "unsupported_human_claim"


@pytest.mark.parametrize("value,quote", [("true", "Em là người thật."), ("false", "Em là trợ lý ảo của shop.")])
def test_explicit_identity_claim_is_preserved(value, quote):
    result = shape(labels("is_human", value, quote), agent_text=quote)
    assert result["claims"][0]["value"] is (value == "true")


def test_missing_quote_is_not_used_as_evidence():
    result = shape(labels("price_vnd", "5200000", "Giá là 5.200.000đ."), agent_text="Em sẽ kiểm tra giá.")
    assert result["claims"] == []
    assert result["set_aside"][0]["reason"] == "quote_not_in_reply"


@pytest.mark.parametrize("field,value,quote,reason", [
    ("delivery_days", "3", "Dữ liệu được xóa trong vòng 72 giờ.", "deletion_is_not_delivery"),
    ("price_vnd", "50000", "Size này phụ thu 50.000đ.", "surcharge_is_not_product_price"),
])
def test_field_subject_must_match_the_quote(field, value, quote, reason):
    result = shape(labels(field, value, quote), agent_text=quote)
    assert result["claims"] == []
    assert result["set_aside"][0]["reason"] == reason
