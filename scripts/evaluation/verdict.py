"""The verdict of an improvement round measured on a data/dev sample and on proof sets, against fixed criteria.

    python scripts/evaluation/verdict.py --name gap-dev-1 --proof gap-loop
    python scripts/evaluation/verdict.py --name refl-dev-1 --proof budget --proof warranty

Reads the round's runs in evaluation/runs/<name> (r0-<set>-<i> before, r1-<set>[-<i>] after; full config only, no
baseline) and checks:

  data/dev sample (set <name>): broken 0, no HARM, TSR and hallucination not worse than the runs before vary
                                (with one run a side that cannot be told: WARN, run with -Runs 2).
  proof set (gap-loop, budget, warranty, conduct): every target case passes every check in every run after; no
                                control case (one that must stay as it was) is broken.

Writes evaluation/runs/<name>/verdict.json. Exit 0 PASS (or nothing to measure), 1 FAIL, 3 WARN only. No model call.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
PROOF_DIRS = {"gap-loop": ROOT / "data" / "gap-loop" / "frozen" / "scenarios"}
PROOF_DIRS.update({s: ROOT / "data" / "reflection" / s / "frozen" / "scenarios" for s in ("budget", "warranty", "conduct")})
#: The controls of the gap-loop set: radon still refused and transferred (FAQ-03), DT-04 and LN-02 still answered.
GAP_CONTROLS = {"SCN-GAP-F11", "SCN-GAP-F12", "SCN-GAP-F13"}


def _has(o: object, key: str) -> bool:
    if isinstance(o, dict):
        return any((k == key and v) or _has(v, key) for k, v in o.items())
    return isinstance(o, list) and any(_has(v, key) for v in o)


def controls(label: str) -> set[str]:
    """Cases that must stay as they were: gap-loop's three, elsewhere the ones whose labels forbid a claim."""
    if label == "gap-loop":
        return set(GAP_CONTROLS)
    return {f.stem for f in PROOF_DIRS[label].glob("*.json") if _has(json.loads(f.read_text(encoding="utf-8")), "forbidden_claims")}


def runs(folder: Path, label: str) -> tuple[list[Path], list[Path]]:
    pick = lambda pattern: sorted(p for p in folder.iterdir() if p.is_dir() and re.fullmatch(pattern, p.name))
    return pick(rf"r0-{re.escape(label)}-\d+"), pick(rf"r1-{re.escape(label)}(-\d+)?")


def metric(run: Path, *path: str) -> float | None:
    value: object = json.loads((run / "report.json").read_text(encoding="utf-8"))["system"]
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, (int, float)) else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--proof", action="append", default=[], choices=sorted(PROOF_DIRS))
    args = p.parse_args()

    from ai_agent_service.pipeline.improve import cli  # needs PYTHONPATH, as the round does

    folder = ROOT / "evaluation" / "runs" / args.name
    if not folder.is_dir():
        sys.exit(f"No {folder}: run the round first")
    checks: list[dict] = []

    def check(set_label: str, what: str, status: str, detail: str) -> None:
        checks.append({"set": set_label, "check": what, "status": status, "detail": detail})

    for label in [args.name, *args.proof]:
        before, after = runs(folder, label)
        if not before or not after:
            check(label, "đã đo", "NONE", "không có r0/r1: vòng không có thay đổi nào để đo, hoặc chưa chạy bước measure")
            continue
        result = cli.comparison(before, after)
        if label == args.name:  # the data/dev sample
            check(label, "broken = 0", "PASS" if not result["broken"] else "FAIL",
                  f"{len(result['broken'])} broken: " + ", ".join(f"{r['scenario_id']} {r['code']}" for r in result["broken"][:8]))
            check(label, "không HARM", "PASS" if not result["harm"] else "FAIL", f"{len(result['harm'])} vi phạm mới")
            for name, path, higher_is_better in (("TSR", ("task_success_rate", "value"), True),
                                                 ("Hallucination", ("hallucination_rate", "value"), False)):
                b = [v for v in (metric(r, *path) for r in before) if v is not None]
                a = [v for v in (metric(r, *path) for r in after) if v is not None]
                if not b or not a:
                    check(label, f"{name} không xấu đi", "NONE", "thiếu số liệu")
                    continue
                worse = mean(a) < min(b) if higher_is_better else mean(a) > max(b)
                detail = f"trước {mean(b):.1f} [{min(b):.1f}-{max(b):.1f}], sau {mean(a):.1f} ({len(b)}/{len(a)} lần chạy)"
                status = "PASS" if not worse else ("WARN" if len(b) < 2 else "FAIL")
                if worse and len(b) < 2:
                    detail += "; một lần chạy mỗi bên không tách được dao động: chạy lại với -Runs 2"
                check(label, f"{name} không xấu đi quá dao động", status, detail)
            check(label, "fixed (tham khảo)", "INFO", f"{len(result['fixed'])} fixed, {len(result['unstable'])} unstable")
        else:  # a proof set
            ctl = controls(label)
            failed_after, played = cli._failed_share(after)
            targets = sorted({s for s, _ in played} - ctl)
            still = sorted({s for (s, _, _), share in failed_after.items() if share > 0 and s in targets})
            check(label, "ca mục tiêu đạt sau", "PASS" if not still else "FAIL",
                  f"{len(targets) - len(still)}/{len(targets)} đạt mọi lần chạy" + (f"; còn trượt: {', '.join(still)}" if still else ""))
            hurt = sorted({r["scenario_id"] for r in result["broken"] + result["harm"] if r["scenario_id"] in ctl})
            check(label, "ca đối chứng không broken", "PASS" if not hurt else "FAIL",
                  (f"{len(ctl)} ca đối chứng" if ctl else "bộ này không có ca đối chứng") + (f"; broken: {', '.join(hurt)}" if hurt else ""))

    measured = {c["set"] for c in checks if c["status"] != "NONE"}
    if measured:  # a round measures every frozen set or none: one without runs is missing evidence, never a PASS
        for c in checks:
            if c["status"] == "NONE" and c["check"] == "đã đo":
                c["status"], c["detail"] = "FAIL", "thiếu run r0/r1 trong khi bộ khác đã đo: thiếu bằng chứng"
    statuses = {c["status"] for c in checks}
    verdict = ("FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses
               else "NO_CHANGE" if statuses <= {"NONE", "INFO"} else "PASS")
    for c in checks:
        print(f"[{c['status']:<4}] {c['set']:<14} {c['check']:<34} {c['detail']}")
    print(f"\nKết luận: {verdict}")
    (folder / "verdict.json").write_text(json.dumps({"name": args.name, "verdict": verdict, "checks": checks},
                                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"FAIL": 1, "WARN": 3}.get(verdict, 0)


if __name__ == "__main__":
    raise SystemExit(main())
