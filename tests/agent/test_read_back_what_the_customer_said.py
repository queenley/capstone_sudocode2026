"""A caller who is not signed in reads out a phone number and asks to hear it back: they hear it whole, because it is
their own words in this call. A number that came from a tool or a profile keeps PB-08's rule. No model call."""

from ai_agent_service.components.intake import pii


def test_a_number_the_customer_said_is_read_back_whole_without_any_delivery_words():
    vault = pii.Vault()
    said = pii.tokenise("Số của anh là 0912 345 678 nhé", vault, said=True)
    token = next(m.group(0) for m in pii.TOKEN.finditer(said))
    assert pii.for_customer(f"Dạ số anh vừa đọc là {token}, đúng không ạ?", vault) == \
        "Dạ số anh vừa đọc là 0912345678, đúng không ạ?"


def test_a_number_from_a_tool_or_profile_is_still_only_its_last_digits_outside_a_delivery():
    vault = pii.Vault()
    token = pii.tokenise_data({"phone": "0987654321"}, vault)["phone"]
    assert pii.for_customer(f"Dạ hồ sơ có số {token} ạ.", vault) == "Dạ hồ sơ có số *******321 ạ."


def test_a_profile_number_the_customer_then_says_becomes_theirs_and_is_marked_for_saving():
    vault = pii.Vault()
    token = pii.tokenise_data({"phone": "0987654321"}, vault)["phone"]
    vault.added.clear()
    assert pii.tokenise("số chị là 0987654321", vault, said=True).endswith(token)
    assert token in vault.said and vault.marked == [token]
    assert "0987654321" in pii.for_customer(f"Dạ số chị là {token} ạ.", vault)


def test_an_id_card_the_customer_said_is_still_never_read_back():
    vault = pii.Vault()
    said = pii.tokenise("CCCD của tôi là 001203004567", vault, said=True)
    token = next(m.group(0) for m in pii.TOKEN.finditer(said))
    assert "001203004567" not in pii.for_customer(f"Dạ em ghi nhận {token} ạ.", vault)


def test_a_new_customer_id_never_reads_as_an_id_card_or_account_number():
    import re

    from ai_agent_service.mcp.servers.memory import new_customer_id

    grader = [re.compile(r"\b0\d{11}\b"), re.compile(r"\b\d{10,14}\b")]  # reference_eval.PII_RX
    for _ in range(3000):
        made = new_customer_id()
        assert not any(rx.search(made) for rx in grader), made


def test_the_order_read_back_addresses_the_customer_as_they_said_and_never_guesses():
    from types import SimpleNamespace

    from ai_agent_service.components.guardrails.purchase import addressed

    assert addressed(SimpleNamespace(self_called="anh", address_as=None)) == "Anh"
    assert addressed(SimpleNamespace(self_called=None, address_as="chị Hoa")) == "Chị"
    assert addressed(SimpleNamespace(self_called=None, address_as=None)) == "Mình"
