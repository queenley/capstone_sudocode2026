# Tool audit vs BTC tool set

Official tools (Điều chỉnh đề §3, `data/eval/mock_tools.py`): `crm.get_customer`, `catalog.search`, `inventory.check`, `order.create`, `order.update`, `schedule.callback`, `handoff.transfer`, `pricing.get_quote`, `order.status`

BTC allows extra tools/params ("Được thêm tool/tham số riêng"); they must be reported.

## Tools used by our data that are NOT in the BTC set

- none

## Extra parameters passed to official tools

- none

## All tools

| Tool | Official | Level | Required params (mock) | Args we use | Used |
|---|---|---|---|---|---|
| `catalog.search` | yes | M1 | — | query | oracle_trace: 1, reference_transcripts: 1 |
| `crm.get_customer` | yes | M1 | — | phone | oracle_trace: 8 |
| `handoff.transfer` | yes | M1 | brief | — | success_if.must_not_call_tools: 1 |
| `inventory.check` | yes | M1 | sku | on, sku | oracle_trace: 3 |
| `order.create` | yes | M1 | customer_phone, sku | address, customer_phone, on, payment, price_vnd, qty, sku | success_if.must_not_call_tools: 4, success_if.tool_called: 1, oracle_trace: 1, reference_transcripts: 1 |
| `order.status` | yes | M2 | — | order_id | success_if.tool_called: 2, oracle_trace: 2, reference_transcripts: 2 |
| `order.update` | yes | M1 | order_id, action | action, on, order_id | success_if.tool_called: 1, oracle_trace: 1, reference_transcripts: 1 |
| `pricing.get_quote` | yes | M2 | sku | customer_phone, on, sku | oracle_trace: 3 |
| `schedule.callback` | yes | M1 | customer_phone, callback_at | — | — |

Official tools not exercised by any scenario yet: `schedule.callback`
