"""The organisers' pack in ``apps/ai-agent-service/data/btc`` is the only copy in the repository: it must not drift.

``reference_eval.py`` and ``mock_tools.py`` decide every official number and every price the agent quotes, so a changed
byte there changes the score or the truth. ``btc_pack.sha256.json`` pins each file (CRLF read as LF). The three files
the team extended (the persona prompts, the judge rubric, the synthetic CRM) are pinned apart, so adding to them is a
decision made in the open, not a silent edit. A change to the pack means editing the manifest in the same commit.
"""
import hashlib
import json
from pathlib import Path

from ai_agent_service.config.config_manager import btc_data_dir

MANIFEST = json.loads((Path(__file__).with_name("btc_pack.sha256.json")).read_text(encoding="utf-8"))
PACK = btc_data_dir()
IGNORED = ("__pycache__", ".DS_Store")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def files():
    return {p.relative_to(PACK).as_posix(): p for p in PACK.rglob("*")
            if p.is_file() and not any(part in IGNORED for part in p.parts)}


def test_the_organisers_files_are_byte_for_byte_theirs():
    changed = [name for name, digest in MANIFEST["official"].items()
               if not (PACK / name).is_file() or sha(PACK / name) != digest]
    assert not changed, f"changed or missing organiser files (never edit them): {changed}"


def test_the_files_the_team_extended_are_pinned_too():
    changed = [name for name, digest in MANIFEST["team"].items()
               if not (PACK / name).is_file() or sha(PACK / name) != digest]
    assert not changed, f"team-extended files changed: update btc_pack.sha256.json in the same commit: {changed}"


def test_no_file_enters_the_pack_unlisted():
    unlisted = sorted(set(files()) - set(MANIFEST["official"]) - set(MANIFEST["team"]))
    assert not unlisted, f"files in the pack that the manifest does not list: {unlisted}"


def test_the_scoring_script_and_the_mock_are_official():
    assert {"eval/reference_eval.py", "eval/mock_tools.py"} <= set(MANIFEST["official"])


def test_the_synthetic_crm_never_collides_with_the_organisers_customers():
    official = json.loads((PACK / "catalog/crm_seed.json").read_text(encoding="utf-8"))["customers"]
    synthetic = json.loads((PACK / "catalog/crm_seed_synthetic.json").read_text(encoding="utf-8"))["customers"]
    assert {c["customer_id"] for c in official}.isdisjoint(c["customer_id"] for c in synthetic)
    assert {c["phone"] for c in official}.isdisjoint(c["phone"] for c in synthetic)
