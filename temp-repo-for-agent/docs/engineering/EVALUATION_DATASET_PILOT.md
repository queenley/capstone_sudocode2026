# Evaluation dataset pilot

## Purpose

This pilot turns the Appendix B scenario format into a stable evaluation
contract. It is not large enough to claim M1 readiness; it is enough to test
the dataset shape, scoring rules and the first improvement loop.

The pilot contains six synthetic air-purifier scenarios. Phone numbers and
catalog IDs are test-only values.

## Evaluation contract

Use the same six cases for memory-on and memory-off runs. The only baseline
change is `switches.memory=false`, which makes retrieval return no brief.

Score in this order:

1. deterministic tool/state assertions for TSR;
2. deterministic fact usage and question classification for CCR/RQR;
3. grounded claim checks for HR;
4. human or LLM judging only where an assertion is impossible.

The pilot reports the denominator for every metric and treats unsupported
price, promotion, stock or delivery claims as hard failures.

```text
RQR = repeated open questions about must_not_ask / all agent questions
CCR = correctly used must_carry_over facts / required carry-over facts
TSR = scenarios satisfying success_if / total scenarios
HR  = incorrect verifiable claims / all verifiable claims
```

## Dataset generation and review

1. Draft scenarios from the fixed air-purifier ontology and catalog snapshot.
2. Validate JSON shape, unique IDs, two or more calls, and references in
   `must_carry_over`, `must_not_ask` and `success_if`.
3. Check that every expected price, promotion, stock and delivery value exists
   in `ground_truth_facts` or the referenced catalog snapshot.
4. Review each case manually, especially the customer script and the intended
   failure mode.
5. Freeze the pilot hash before measuring it. Repaired cases belong in `growth`.

The future runner should use `customer_script` with a deterministic
`ScriptedCustomer` in M1. M2 can replace it with `SimulatorAgent` without
changing the scenario file.

## Pilot scenarios

```json
[
  {
    "scenario_id": "SC-AIR-001",
    "persona": "hesitant_customer",
    "tags": ["continuity", "order"],
    "customer": {"phone": "0900000001", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T09:00:00Z",
        "customer_script": {
          "opening": "Tôi cần máy lọc không khí cho phòng 25m2, ngân sách khoảng 5 triệu.",
          "goal": "find_suitable_product",
          "answers": {"room_area_m2": "25", "budget_vnd": "5000000", "has_children": "yes"},
          "confirm_reply": "Đúng rồi.",
          "buy_if_offered": "no",
          "wants_human_if_oos": "no",
          "max_turns": 8
        },
        "facts_established": {
          "room_area_m2": 25,
          "budget_vnd": 5000000,
          "has_children": true,
          "product_advised": "SKU-AP-X",
          "price_quoted_vnd": 4890000,
          "blocker": "ask_husband"
        },
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [
          {"name": "pricing.get_quote", "args_subset": {"sku": "SKU-AP-X"}}
        ],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "callback_requested"}},
        "ground_truth_facts": {"price_vnd": 4890000, "promo_active": true, "in_stock": true, "delivery_days": 2},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 2,
        "now": "2026-09-22T09:00:00Z",
        "customer_script": {
          "opening": "Tôi gọi lại về máy hôm trước, giờ tôi muốn đặt.",
          "goal": "place_order",
          "answers": {},
          "confirm_reply": "Đúng, đặt máy đó giúp tôi.",
          "buy_if_offered": "yes",
          "wants_human_if_oos": "yes",
          "max_turns": 6
        },
        "must_carry_over": ["product_advised", "price_quoted_vnd", "room_area_m2", "blocker"],
        "must_not_ask": ["room_area_m2", "budget_vnd", "has_children", "product_advised"],
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [
          {"name": "pricing.get_quote", "args_subset": {"sku": "SKU-AP-X"}},
          {"name": "order.create", "args_subset": {"sku": "SKU-AP-X", "price_vnd": 4890000}}
        ],
        "success_if": {"graded_by": "assertion", "assertion": {"tool": "order.create", "args_match": {"sku": "SKU-AP-X", "price_vnd": 4890000}}},
        "ground_truth_facts": {"price_vnd": 4890000, "promo_active": true, "in_stock": true, "delivery_days": 2},
        "catalog_snapshot_id": "catalog-air-2026-09-22-a"
      }
    ]
  },
  {
    "scenario_id": "SC-AIR-002",
    "persona": "customer_changes_product",
    "tags": ["continuity", "changed_mind"],
    "customer": {"phone": "0900000002", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T10:00:00Z",
        "customer_script": {"opening": "Tư vấn máy cho phòng 18m2, ngân sách 3 triệu.", "goal": "find_suitable_product", "answers": {"room_area_m2": "18", "budget_vnd": "3000000"}, "confirm_reply": "Đúng.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 6},
        "facts_established": {"room_area_m2": 18, "budget_vnd": 3000000, "product_advised": "SKU-AP-S", "price_quoted_vnd": 2790000},
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "pricing.get_quote", "args_subset": {"sku": "SKU-AP-S"}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "callback_requested"}},
        "ground_truth_facts": {"price_vnd": 2790000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 1,
        "now": "2026-09-21T10:00:00Z",
        "customer_script": {"opening": "Tôi đổi ý, muốn loại cho phòng 30m2 nếu giá không quá 5 triệu.", "goal": "find_alternative", "answers": {"room_area_m2": "30", "budget_vnd": "5000000"}, "confirm_reply": "Đúng, tôi đổi sang loại lớn hơn.", "buy_if_offered": "yes", "wants_human_if_oos": "no", "max_turns": 7},
        "must_carry_over": ["budget_vnd"],
        "must_not_ask": ["budget_vnd"],
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "catalog.search", "args_subset": {"room_area_m2": 30}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "alternative_presented"}},
        "ground_truth_facts": {"price_vnd": 4590000, "promo_active": true, "in_stock": true, "delivery_days": 2},
        "catalog_snapshot_id": "catalog-air-2026-09-21-a"
      }
    ]
  },
  {
    "scenario_id": "SC-AIR-003",
    "persona": "customer_gives_conflicting_fact",
    "tags": ["conflict", "memory"],
    "customer": {"phone": "0900000003", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T11:00:00Z",
        "customer_script": {"opening": "Phòng nhà tôi 20m2, tư vấn giúp.", "goal": "find_suitable_product", "answers": {"room_area_m2": "20", "budget_vnd": "4000000"}, "confirm_reply": "Đúng.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 6},
        "facts_established": {"room_area_m2": 20, "budget_vnd": 4000000, "product_advised": "SKU-AP-M"},
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "catalog.search", "args_subset": {"room_area_m2": 20}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "callback_requested"}},
        "ground_truth_facts": {"price_vnd": 3690000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 3,
        "now": "2026-09-23T11:00:00Z",
        "customer_script": {"opening": "Tôi nhớ là phòng 35m2, không phải 20m2.", "goal": "refresh_recommendation", "answers": {"room_area_m2": "35"}, "confirm_reply": "Đúng, thông tin mới là 35m2.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 7},
        "must_carry_over": ["budget_vnd", "product_advised"],
        "must_not_ask": ["budget_vnd"],
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "catalog.search", "args_subset": {"room_area_m2": 35}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "conflict_recorded_and_recommendation_refreshed"}},
        "ground_truth_facts": {"price_vnd": 4990000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-23-a"
      }
    ]
  },
  {
    "scenario_id": "SC-AIR-004",
    "persona": "promo_expiry_customer",
    "tags": ["freshness", "expired_promotion", "safety"],
    "customer": {"phone": "0900000004", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T12:00:00Z",
        "customer_script": {"opening": "Máy cho phòng 25m2 có khuyến mãi gì không?", "goal": "get_quote", "answers": {"room_area_m2": "25"}, "confirm_reply": "Tôi ghi lại giá rồi.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 6},
        "facts_established": {"room_area_m2": 25, "product_advised": "SKU-AP-X", "price_quoted_vnd": 4890000, "promo_code": "GIFT-FILTER", "promo_expiry": "2026-09-21"},
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "pricing.get_quote", "args_subset": {"sku": "SKU-AP-X"}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "quote_recorded"}},
        "ground_truth_facts": {"price_vnd": 4890000, "promo_active": true, "in_stock": true, "delivery_days": 2},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 3,
        "now": "2026-09-23T12:00:00Z",
        "customer_script": {"opening": "Tôi muốn dùng khuyến mãi GIFT-FILTER hôm trước.", "goal": "refresh_expired_quote", "answers": {}, "confirm_reply": "Nếu hết thì báo giá hiện tại giúp tôi.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 6},
        "must_carry_over": ["product_advised", "price_quoted_vnd", "promo_code"],
        "must_not_ask": ["product_advised"],
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "pricing.get_quote", "args_subset": {"sku": "SKU-AP-X"}}],
        "success_if": {"graded_by": "assertion", "assertion": {"quote_must_be_refreshed": true, "expired_promo_must_not_be_claimed": true}},
        "ground_truth_facts": {"price_vnd": 4990000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-23-a"
      }
    ]
  },
  {
    "scenario_id": "SC-AIR-005",
    "persona": "out_of_scope_customer",
    "tags": ["out_of_scope", "no_tool"],
    "customer": {"phone": "0900000005", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T13:00:00Z",
        "customer_script": {"opening": "Tôi cần máy cho phòng 15m2.", "goal": "find_suitable_product", "answers": {"room_area_m2": "15"}, "confirm_reply": "Đúng.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 5},
        "facts_established": {"room_area_m2": 15},
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "catalog.search", "args_subset": {"room_area_m2": 15}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "callback_requested"}},
        "ground_truth_facts": {"price_vnd": 2490000, "promo_active": false, "in_stock": true, "delivery_days": 4},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 1,
        "now": "2026-09-21T13:00:00Z",
        "customer_script": {"opening": "Bên bạn có bán bảo hiểm nhân thọ không?", "goal": "ask_unsupported_question", "answers": {}, "confirm_reply": "Tôi hiểu.", "buy_if_offered": "no", "wants_human_if_oos": "yes", "max_turns": 4},
        "must_carry_over": [],
        "must_not_ask": ["room_area_m2"],
        "expected_lane": "OUT_OF_SCOPE",
        "expected_tool_calls": [],
        "success_if": {"graded_by": "assertion", "assertion": {"no_tool_calls": true, "lane": "OUT_OF_SCOPE"}},
        "ground_truth_facts": {"price_vnd": null, "promo_active": null, "in_stock": null, "delivery_days": null},
        "catalog_snapshot_id": "catalog-air-2026-09-21-a"
      }
    ]
  },
  {
    "scenario_id": "SC-AIR-006",
    "persona": "impatient_customer",
    "tags": ["repetition", "handoff", "patience"],
    "customer": {"phone": "0900000006", "channels": ["chat"]},
    "calls": [
      {
        "channel": "chat",
        "days_later": 0,
        "now": "2026-09-20T14:00:00Z",
        "customer_script": {"opening": "Tôi cần máy cho phòng 40m2, tư vấn nhanh giúp.", "goal": "find_suitable_product", "answers": {"room_area_m2": "40", "budget_vnd": "7000000"}, "confirm_reply": "Đúng.", "buy_if_offered": "no", "wants_human_if_oos": "no", "max_turns": 5},
        "facts_established": {"room_area_m2": 40, "budget_vnd": 7000000, "product_advised": "SKU-AP-L"},
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "catalog.search", "args_subset": {"room_area_m2": 40}}],
        "success_if": {"graded_by": "assertion", "assertion": {"outcome": "callback_requested"}},
        "ground_truth_facts": {"price_vnd": 6490000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-20-a"
      },
      {
        "channel": "chat",
        "days_later": 2,
        "now": "2026-09-22T14:00:00Z",
        "customer_script": {"opening": "Tôi gọi lại, nói nhanh giúp tôi.", "goal": "place_order", "answers": {}, "confirm_reply": "Đúng máy đó, nếu còn hàng thì đặt luôn.", "buy_if_offered": "yes", "wants_human_if_oos": "yes", "max_turns": 5},
        "must_carry_over": ["room_area_m2", "budget_vnd", "product_advised"],
        "must_not_ask": ["room_area_m2", "budget_vnd", "product_advised"],
        "expected_lane": "CONTINUITY",
        "expected_tool_calls": [{"name": "inventory.check", "args_subset": {"sku": "SKU-AP-L"}}, {"name": "order.create", "args_subset": {"sku": "SKU-AP-L"}}],
        "success_if": {"graded_by": "assertion", "assertion": {"tool": "order.create", "args_match": {"sku": "SKU-AP-L"}}},
        "ground_truth_facts": {"price_vnd": 6490000, "promo_active": false, "in_stock": true, "delivery_days": 3},
        "catalog_snapshot_id": "catalog-air-2026-09-22-a"
      }
    ]
  }
]
```

## Next step

Use these cases as the contract for a future `eval run` command. Do not call
the pilot a passing M1 evaluation until it reaches at least 20 multi-call
scenarios plus 5 hard cases and produces an immutable manifest and report.
