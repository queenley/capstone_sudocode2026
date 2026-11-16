"""The 2x2 verdict of the improvement methods (scripts/evaluation/ablation_verdict.py): no model call."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "evaluation"))

import ablation_verdict as av  # noqa: E402


def test_the_same_runs_always_give_the_same_interval():
    diffs = [0.0, 1.0, 0.33, -0.33, 0.0, 0.67]
    assert av.bootstrap(diffs) == av.bootstrap(diffs)
    low, high = av.bootstrap(diffs)
    assert low <= sum(diffs) / len(diffs) <= high


def test_a_scenario_share_is_the_runs_it_passed_in():
    assert av.shares([{"A": True, "B": False}, {"A": True, "B": True}, {"A": False, "B": False}]) == \
        {"A": 2 / 3, "B": 1 / 3}


def test_a_learner_must_pass_every_target_in_every_run_and_keep_the_controls():
    by_config = {"router": {"T1": 0.0, "T2": 0.33, "C1": 1.0},
                 "gaploop": {"T1": 1.0, "T2": 1.0, "C1": 1.0},
                 "combined": {"T1": 1.0, "T2": 0.67, "C1": 0.67}}
    checks = {(c["config"], c["check"]): c["status"] for c in av.proof_checks("gap-loop", by_config, {"C1"})}
    assert checks[("gaploop", "ca mục tiêu đạt mọi lần chạy")] == "PASS"
    assert checks[("gaploop", "ca đối chứng không mất")] == "PASS"
    assert checks[("combined", "ca mục tiêu đạt mọi lần chạy")] == "FAIL"   # T2 failed in one of three runs
    assert checks[("combined", "ca đối chứng không mất")] == "FAIL"        # C1 lost once


def test_no_harm_is_judged_against_the_routers_own_spread():
    router = {"TSR": {"mean": 60.0, "min": 55.0, "max": 65.0, "runs": 3}, "HR": {"mean": 13.0, "min": 11.0, "max": 15.0, "runs": 3}}
    inside = {"TSR": {"mean": 58.3, "min": 55.0, "max": 60.0, "runs": 3}, "HR": {"mean": 12.0, "min": 11.0, "max": 13.0, "runs": 3}}
    below = {"TSR": {"mean": 50.0, "min": 45.0, "max": 55.0, "runs": 3}, "HR": {"mean": 12.0, "min": 11.0, "max": 13.0, "runs": 3}}
    shares = {"router": {"A": 1.0, "B": 0.67, "C": 0.0}, "gaploop": {"A": 1.0, "B": 0.67, "C": 0.0},
              "combined": {"A": 0.0, "B": 0.0, "C": 0.0}}
    result = {c["config"]: c["status"] for c in av.control_checks({"router": router, "gaploop": inside, "combined": below}, shares)}
    assert result == {"gaploop": "PASS", "combined": "FAIL"}


def _scenario(folder: Path, sid: str, turns: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sid}.json").write_text(json.dumps({"scenario_id": sid, "calls": {"call_1": {"customer_turns": turns}}}),
                                        encoding="utf-8")


def test_a_proof_set_must_not_hold_what_was_learned(tmp_path):
    learn, proof = tmp_path / "learn", tmp_path / "proof"
    _scenario(learn, "L1", ["Anh ở Đà Nẵng mua máy lọc nước có người tới lắp không em"])
    _scenario(proof, "F1", ["Shop có showroom ở đâu để anh ghé coi máy không"])
    assert av.apart(learn, proof)["status"] == "PASS"
    _scenario(proof, "F2", ["Anh ở Đà Nẵng, mua máy lọc nước có người tới lắp không em?"])
    assert av.apart(learn, proof)["status"] == "WARN"   # the same question, word for word
    _scenario(proof, "L1", ["khác"])
    assert av.apart(learn, proof)["status"] == "FAIL"   # the same scenario
