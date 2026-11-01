"""Main's basket/split fields stay bound to the local consent boundary."""
import pytest
from dataclasses import replace

from ai_agent_service.agents.advisor import AgentContext

from ai_agent_service.components.guardrails import purchase


@pytest.mark.parametrize('extra', [{'basket_skus': ['SKU-SYNTHETIC-B']}, {'order_group': '2'}])
def test_main_order_fields_are_bound_by_consent_and_idempotency(extra):
    original = {'sku': 'SKU-SYNTHETIC-A', 'price_vnd': 123000, 'qty': 1,
                'customer_phone': '0900000000', 'on': '2034-01-02'}
    changed = {**original, **extra}
    assert purchase.fingerprint(original) != purchase.fingerprint(changed)
    for field, value in extra.items():
        assert purchase.payload(changed)[field] == value
    assert purchase.order_key('synthetic-call', purchase.payload(changed)) in purchase.order_keys('synthetic-call', changed)


@pytest.mark.parametrize('extra', [{'basket_skus': ['SKU-SYNTHETIC-B']}, {'order_group': '2'}])
def test_signed_receipt_rejects_a_changed_basket_or_split_group(monkeypatch, extra):
    monkeypatch.setattr(purchase, 'derived_key', lambda _: b'synthetic-test-key')
    args = {'sku': 'SKU-SYNTHETIC-A', 'price_vnd': 123000, 'qty': 1}
    context = AgentContext(call_id='synthetic-call', turn_id='prepare', channel='web')
    pending = purchase.draft(args, context)
    confirmed = purchase.answer(pending, call_id=context.call_id, channel='web', turn_id='confirm',
                                said='vâng', last_reply=pending['question'])
    context = replace(context, turn_id='confirm', pending_purchase=confirmed,
                      last_agent_said=pending['question'], customer_said='vâng')
    token = purchase.receipt(confirmed, args, context)
    assert purchase.verify(token, args, context.call_id, context.turn_id)
    with pytest.raises(ValueError, match='Purchase confirmation'):
        purchase.verify(token, {**args, **extra}, context.call_id, context.turn_id)
