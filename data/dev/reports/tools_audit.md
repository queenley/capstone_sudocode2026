# Tool audit vs BTC tool set

Official tools (Điều chỉnh đề §3, `data/eval/mock_tools.py`): `crm.get_customer`, `catalog.search`, `inventory.check`, `order.create`, `order.update`, `schedule.callback`, `handoff.transfer`, `pricing.get_quote`, `order.status`

BTC allows extra tools/params ("Được thêm tool/tham số riêng"); they must be reported.

## Tools used by our data that are NOT in the BTC set

- `delivery_estimate` — used 235× (oracle_trace 235)

## Extra parameters passed to official tools

- `order.create`: `order_group`

## All tools

| Tool | Official | Level | Required params (mock) | Args we use | Used |
|---|---|---|---|---|---|
| `catalog.search` | yes | M1 | — | query | oracle_trace: 6 |
| `crm.get_customer` | yes | M1 | — | phone | oracle_trace: 801 |
| `delivery_estimate` | **no** | team | — | address, on | oracle_trace: 235 |
| `handoff.transfer` | yes | M1 | brief | brief | success_if.must_not_call_tools: 21, success_if.tool_called: 20, oracle_trace: 20 |
| `inventory.check` | yes | M1 | sku | on, sku | fault_injection: 15, oracle_trace: 587 |
| `order.create` | yes | M1 | customer_phone, sku | address, basket_skus, customer_phone, on, order_group, payment, price_vnd, qty, sku | success_if.must_not_call_tools: 479, success_if.tool_called: 232, oracle_trace: 281 |
| `order.status` | yes | M2 | — | order_id | success_if.tool_called: 47, oracle_trace: 64 |
| `order.update` | yes | M1 | order_id, action | action, new_variant_sku, on, order_id, reason | success_if.must_not_call_tools: 19, success_if.tool_called: 36, oracle_trace: 36 |
| `pricing.get_quote` | yes | M2 | sku | basket_skus, customer_phone, on, sku | success_if.tool_called: 6, oracle_trace: 605 |
| `schedule.callback` | yes | M1 | customer_phone, callback_at | callback_at, customer_phone, note | success_if.tool_called: 92, oracle_trace: 92 |
