"""Every file the pipeline writes matches BTC's schemas (data/schemas)."""
from src.ground_truth.traces import oracle_rows
from src.utils.btc_schemas import dataset_errors, errors, tool_call_errors
from src.utils.dataset import Dataset


def test_every_generated_file_matches_btc_schemas(tmp_path, all_scenarios):
    dataset = Dataset(tmp_path)
    for scenario in all_scenarios:
        dataset.write_scenario(scenario)
        for call in scenario.calls:
            dataset.write_trace(scenario.scenario_id, call, [r for r in oracle_rows(scenario) if r["call"] == call])
    assert dataset_errors(dataset) == {}


def test_schema_checks_catch_what_btc_rejects():
    assert tool_call_errors("order.create", {"customer_phone": "0912345678", "sku": "SKU-AP-Y", "qty": 1,
                                             "price_vnd": 5200000, "payment": "chuyen_khoan"})
    assert tool_call_errors("order.update", {"order_id": "OD1"})                       # action is required
    assert tool_call_errors("memory.write", {})                                       # not a BTC tool
    assert not tool_call_errors("pricing.get_quote", {"sku": "SKU-AP-Y", "basket_skus": ["SKU-AP-X"]})
    row = {"run_id": "r", "config": "oracle", "scenario_id": "S", "call": "call_1", "turn": 1, "customer_text": "",
           "agent_text": "", "questions": [], "claims": [], "tool_calls": [], "latency": {"ttft_ms": None, "total_ms": 1}}
    found = " ".join(errors("trace_log", row))
    assert "config" in found and "ttft_ms" in found


def test_scenarios_use_registered_outcomes_and_memory_writes_say_how(all_scenarios):
    from src.schemas import keys

    outcomes = {c["expected_outcome"] for s in all_scenarios for c in s.btc_export()["calls"].values()}
    # The outcome itself, never BTC's catch-all "khac": the finer ones are registered (scenario-keys.yaml).
    assert outcomes <= set(keys.registry()["expected_outcome"]) - {"khac"}
    writes = [w for s in all_scenarios for r in oracle_rows(s) for w in r["memory_writes"]]
    assert writes and all({"key", "value", "op", "source", "customer_id"} <= set(w) for w in writes)
    assert {w["op"] for w in writes} <= {"set", "supersede"} and any(w["op"] == "supersede" for w in writes)
