# Tool audit vs BTC tool set

Official tools (Điều chỉnh đề §3, `data/eval/mock_tools.py`): `crm.get_customer`, `catalog.search`, `inventory.check`, `order.create`, `order.update`, `schedule.callback`, `handoff.transfer`, `pricing.get_quote`, `order.status`

BTC allows extra tools/params ("Được thêm tool/tham số riêng"); they must be reported.

## Tools used by our data that are NOT in the BTC set

- none

## Extra parameters passed to official tools

- `inventory.check`: `variant_sku`

## All tools

| Tool | Official | Level | Required params (mock) | Args we use | Used |
|---|---|---|---|---|---|
| `catalog.search` | yes | M1 | — | — | — |
| `crm.get_customer` | yes | M1 | — | phone | oracle_trace: 325 |
| `handoff.transfer` | yes | M1 | brief | brief | success_if.tool_called: 9, oracle_trace: 9, reference_transcripts: 12 |
| `inventory.check` | yes | M1 | sku | on, sku, variant_sku | fault_injection: 9, oracle_trace: 262, reference_transcripts: 1 |
| `order.create` | yes | M1 | customer_phone, sku | address, customer_phone, on, payment, price_vnd, qty, sku | success_if.tool_called: 88, success_if.must_not_call_tools: 194, oracle_trace: 109, reference_transcripts: 109 |
| `order.status` | yes | M2 | — | order_id | success_if.tool_called: 21, oracle_trace: 21, reference_transcripts: 24 |
| `order.update` | yes | M1 | order_id, action | action, new_variant_sku, on, order_id | success_if.tool_called: 18, oracle_trace: 18, reference_transcripts: 18 |
| `pricing.get_quote` | yes | M2 | sku | customer_phone, on, sku | oracle_trace: 262 |
| `schedule.callback` | yes | M1 | customer_phone, callback_at | callback_at, customer_phone, note | success_if.tool_called: 4, oracle_trace: 4, reference_transcripts: 4 |

Official tools not exercised by any scenario yet: `catalog.search`
