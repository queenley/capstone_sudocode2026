import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.migration.validate_dataset import validate


class DatasetValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("catalog", "conversations", "scenarios"):
            (self.root / folder).mkdir()
        self.write_csv(
            "catalog/catalog_skus.csv",
            {"sku": "A", "sale_price": "10", "list_price": "12", "stock": "2"},
        )
        self.write_csv("catalog/promotions.csv", {"promo_id": "P", "sku": "A"})
        self.write_csv("conversations/customers.csv", {"customer_id": "C"})
        (self.root / "conversations/conversations.jsonl").write_text(
            json.dumps(
                {
                    "conversation_id": "S",
                    "customer_id": "C",
                    "turns": [{"speaker": "customer", "text": "hello"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.write_scenario("S")

    def write_csv(self, relative, row):
        with (self.root / relative).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    def write_scenario(self, reference):
        (self.root / "scenarios/scenarios.json").write_text(
            json.dumps(
                {
                    "scenarios": [
                        {
                            "scenario_id": "TEST",
                            "call_1": {"reference_conversation_id": reference},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_valid_fixture(self):
        self.assertEqual(validate(self.root)["errors"], [])

    def test_unknown_reference(self):
        self.write_scenario("missing")
        self.assertIn(
            "Unknown reference conversation: missing", validate(self.root)["errors"]
        )

    def test_invalid_price_and_stock(self):
        self.write_csv(
            "catalog/catalog_skus.csv",
            {"sku": "A", "sale_price": "15", "list_price": "12", "stock": "-1"},
        )
        self.assertIn("Invalid price/stock: A", validate(self.root)["errors"])


if __name__ == "__main__":
    unittest.main()
