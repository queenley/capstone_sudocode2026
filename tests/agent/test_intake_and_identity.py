"""Intake (``docs/design.md`` 4.1) and identity resolution (4.2): no model, no database."""

from datetime import datetime

import pytest

from ai_agent_service.components.identity import resolver
from ai_agent_service.components.intake import itn, pii, text

REFERENCE_DAY = datetime(2026, 10, 15, 10)


@pytest.mark.parametrize("said", [
    "0901234567", "090 123 4567", "0901.234.567", "0901-234-567", "+84 90 123 4567", "+84901234567",
])
def test_phone_numbers_become_tokens_however_they_are_written(said):
    vault = pii.Vault()
    assert pii.tokenise(f"số của anh là {said} nhé", vault) == "số của anh là <PHONE_1> nhé"
    assert vault.values("PHONE") == ["0901234567"]
    assert resolver.phones_in(said) == ["0901234567"]


@pytest.mark.parametrize("amount", ["500.000.000đ", "18.990.000đ", "2.500.000 đồng"])
def test_grouped_amounts_are_money_not_phone_numbers(amount):
    vault = pii.Vault()
    assert pii.tokenise(f"giá {amount}", vault) == f"giá {amount}"
    assert vault.entries == {}


def test_vault_reveals_phones_to_the_customer_and_last_four_to_staff():
    vault = pii.Vault()
    said = pii.tokenise("anh 0901234567, CCCD 012345678901", vault)
    assert said == "anh <PHONE_1>, CCCD <CCCD_1>"
    assert pii.detokenize(said, vault) == "anh 0901234567, CCCD ****8901"
    assert pii.detokenize(said, vault, reveal_phone=False) == "anh ****4567, CCCD ****8901"
    # The same value twice keeps its token; a token from another call is a leak.
    assert pii.tokenise("0901234567", vault) == "<PHONE_1>"
    assert pii.unknown_tokens("<PHONE_1> <PHONE_7>", vault) == ["<PHONE_7>"]


def test_mask_keeps_the_last_four_digits_for_logs():
    assert pii.mask("gọi 0901234567") == "gọi ******4567"


def test_text_clean_expands_teencode_and_drops_invisible_characters():
    assert text.clean("sp này  ko​ có màu đen à") == ("sản phẩm này không có màu đen à", True)
    assert text.plain("Điện thoại") == "dien thoai"


@pytest.mark.parametrize("said,amount", [
    ("ngân sách mười tám triệu", 18_000_000),
    ("hai triệu rưỡi", 2_500_000),
    ("tầm 18tr", 18_000_000),
])
def test_spoken_amounts_are_normalised(said, amount):
    assert [span.value for span in itn.money_spans(itn.normalise(said, REFERENCE_DAY))] == [amount]


def test_confirmation_answers():
    assert resolver.confirms("dạ đúng rồi") is True
    assert resolver.confirms("không phải") is False
