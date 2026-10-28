"""Check a dataset's labels against BTC's reference mock, the way BTC's own ``validate_scenarios.py`` does.

BTC runs that script "after each edit" to keep scenarios and catalogue consistent, but does not ship it. This is the
part we can do with what it ships: for every call that expects an ``order.create`` (or states a price in
``ground_truth_facts``), the price the label wants must be what ``mock_tools.pricing_get_quote`` returns for that SKU on
that call's date. A mismatch means the label, not the agent, is wrong.

    python run_eval.py label-check --dataset-id create-data-diagnostic-v4
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]   # evaluation/agent-evaluation
BTC = HERE / "contracts/sources/btc"


def mock():
    # No __pycache__ beside the organisers' file: sources/btc is hash-locked, file by file.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("btc_mock_tools", BTC / "eval/mock_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(directory: Path):
    tools = mock()
    problems, checked = [], 0
    for path in sorted(directory.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for name, call in scenario["calls"].items():
            wanted = (call.get("success_if") or {})
            args = wanted.get("args_match") or {}
            on = call.get("call_date") or tools.REF
            where = f"{scenario['scenario_id']} {name}"
            if wanted.get("tool_called") == "order.create" and args.get("sku"):
                checked += 1
                quote = tools.pricing_get_quote(args["sku"], on=on, qty=1, customer_phone=scenario.get("customer_phone"),
                                                address=(call.get("facts_established") or {}).get("delivery_area"))
                if "error" in quote:
                    problems.append((where, "sku", args["sku"], quote["error"]))
                elif args.get("price_vnd") not in (None, quote["final_price_vnd"]):
                    problems.append((where, "price_vnd", args["price_vnd"], f"mock {quote['final_price_vnd']} on {on}"))
                stock = tools.inventory_check(args["sku"], on=on)
                if isinstance(stock, dict) and stock.get("in_stock") is False:
                    problems.append((where, "in_stock", args["sku"], f"out of stock on {on}"))
            truth = call.get("ground_truth_facts") or {}
            sku = args.get("sku") or (call.get("facts_established") or {}).get("variant_sku")
            if sku and "price_vnd" in truth:
                checked += 1
                quote = tools.pricing_get_quote(sku, on=on, qty=1, customer_phone=scenario.get("customer_phone"),
                                                address=(call.get("facts_established") or {}).get("delivery_area"))
                if "error" not in quote and truth["price_vnd"] != quote["final_price_vnd"]:
                    problems.append((where, "gt price_vnd", truth["price_vnd"], f"mock {quote['final_price_vnd']} on {on}"))
    return checked, problems


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "create-data-diagnostic-v4"
    checked, problems = check(HERE / "datasets" / name / "scenarios")
    print(f"{name}: {checked} price/stock checks, {len(problems)} label problems")
    for row in problems[:40]:
        print("  ", *row)
