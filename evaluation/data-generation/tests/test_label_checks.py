from src.pipeline.check_labels import has_consent
from src.pipeline.sync_customer_turns import extend, spoken_tail


def test_only_a_transcript_that_continues_the_script_is_taken_from():
    assert spoken_tail(["a", "b"], ["a", "b", "c"]) == ["c"]
    assert spoken_tail(["a", "b"], ["a", "x", "c"]) == []
    assert spoken_tail(["a", "b"], ["a", "b"]) == []


def test_a_cut_line_returns_to_the_script_and_an_asr_call_stays_aligned():
    text = {"customer_turns": ["Chào em"], "input_mode": "text"}
    assert extend(text, ["Chào em", "Đúng rồi em."]) == ["Đúng rồi em."]
    assert text["customer_turns"] == ["Chào em", "Đúng rồi em."]
    asr = {"customer_turns": ["Chào em"], "customer_turns_asr": ["chao em"], "input_mode": "asr_transcript"}
    extend(asr, ["chao em", "dung roi em"])
    assert len(asr["customer_turns"]) == len(asr["customer_turns_asr"]) == 2


def test_consent_is_looked_for_at_the_end_of_the_call():
    assert has_consent(["Giá bao nhiêu?", "Đúng rồi em, lên đơn nhé."])
    assert not has_consent(["Chị cần suy nghĩ thêm một chút trước khi chốt"[:30], "Khu vực giao là Hà Nội."])
