"""Read-only competition input validation; never imports gold into live memory."""

import argparse
import csv
import json
from pathlib import Path


def read_csv(root, relative):
    with (root / relative).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def validate(root: Path) -> dict:
    skus = read_csv(root, "catalog/catalog_skus.csv")
    customers = read_csv(root, "conversations/customers.csv")
    promotions = read_csv(root, "catalog/promotions.csv")
    with (root / "conversations/conversations.jsonl").open(
        encoding="utf-8-sig"
    ) as stream:
        conversations = [json.loads(line) for line in stream if line.strip()]
    scenarios_raw = json.loads(
        (root / "scenarios/scenarios.json").read_text(encoding="utf-8-sig")
    )
    scenarios = (
        scenarios_raw["scenarios"] if isinstance(scenarios_raw, dict) else scenarios_raw
    )
    errors = []

    def identifiers(rows, field):
        values = [row[field] for row in rows]
        if len(values) != len(set(values)) or any(not value for value in values):
            errors.append(f"Duplicate or empty {field}")
        return set(values)

    sku_ids = identifiers(skus, "sku")
    customer_ids = identifiers(customers, "customer_id")
    conversation_ids = identifiers(conversations, "conversation_id")
    identifiers(promotions, "promo_id")
    identifiers(scenarios, "scenario_id")
    for row in skus:
        try:
            if (
                not (0 <= float(row["sale_price"]) <= float(row["list_price"]))
                or int(row["stock"]) < 0
            ):
                raise ValueError()
        except ValueError:
            errors.append(f"Invalid price/stock: {row['sku']}")
    for row in promotions:
        if row["sku"] not in sku_ids:
            errors.append(f"Unknown promotion SKU: {row['sku']}")
    for row in conversations:
        if row["customer_id"] not in customer_ids:
            errors.append(f"Unknown customer in {row['conversation_id']}")
        for turn in row["turns"]:
            if turn.get("speaker") not in {
                "customer",
                "agent",
                "system",
            } or not isinstance(turn.get("text"), str):
                errors.append(f"Invalid turn in {row['conversation_id']}")
    for row in scenarios:
        for key in ("call_1", "call_2", "call_3"):
            reference = row.get(key, {}).get("reference_conversation_id")
            if reference and reference not in conversation_ids:
                errors.append(f"Unknown reference conversation: {reference}")
    return {
        "counts": {
            "skus": len(skus),
            "customers": len(customers),
            "conversations": len(conversations),
            "scenarios": len(scenarios),
            "promotions": len(promotions),
        },
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    report = validate(args.dataset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report["errors"]))
