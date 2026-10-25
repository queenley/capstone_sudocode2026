"""LLM-judge ↔ human agreement (BTC rubric ``agreement_protocol``).

1. Export a random sample of ≥ 20 (call, criterion) pairs that have an LLM verdict::

       python -m src.pipeline.judge_agreement --export --n 30
       -> output/review/judge_agreement.csv  (fill `human_verdict` with PASS or FAIL; LLM verdict is hidden)

2. Compute agreement::

       python -m src.pipeline.judge_agreement --ingest
       -> output/reports/judge_agreement.json  (% agreement, Cohen's kappa, per-criterion breakdown)

BTC: kappa < 0.6 means the rubric/judge is not reliable yet and errors must be analysed.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict

from src.utils.paths import CONVERSATIONS_DIR, JUDGMENTS_DIR, REPORTS_DIR, REVIEW_DIR

CSV_PATH = REVIEW_DIR / "judge_agreement.csv"
KEY_PATH = REVIEW_DIR / "judge_agreement_key.json"   # LLM verdicts kept apart so reviewers are blind
FIELDS = ["sample_id", "conversation_id", "criterion_id", "evidence_llm_hidden", "transcript_path", "human_verdict", "notes"]


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum((sum(a == l for a, _ in pairs) / n) * (sum(b == l for _, b in pairs) / n) for l in labels)
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def export(n: int, seed: int) -> None:
    items = []
    for path in sorted(JUDGMENTS_DIR.glob("*.json")):
        judgment = json.loads(path.read_text(encoding="utf-8"))
        for v in judgment.get("verdicts", []):
            items.append((judgment["conversation_id"], v["criterion_id"], v["verdict"]))
    if len(items) < 20:
        raise SystemExit(f"Only {len(items)} judged (call, criterion) pairs; BTC requires ≥ 20 — judge more calls first.")
    sample = random.Random(seed).sample(items, min(n, len(items)))
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for i, (cid, criterion, _) in enumerate(sample, start=1):
            writer.writerow({"sample_id": i, "conversation_id": cid, "criterion_id": criterion, "evidence_llm_hidden": "",
                             "transcript_path": str(CONVERSATIONS_DIR / f"{cid}.json"), "human_verdict": "", "notes": ""})
    KEY_PATH.write_text(json.dumps({str(i): v for i, (_, _, v) in enumerate(sample, start=1)}, indent=2), encoding="utf-8")
    print(f"Exported {len(sample)} samples -> {CSV_PATH} (fill human_verdict with PASS/FAIL)")


def ingest() -> None:
    key = json.loads(KEY_PATH.read_text(encoding="utf-8"))
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as stream:
        rows = [r for r in csv.DictReader(stream) if r["human_verdict"].strip().upper() in {"PASS", "FAIL"}]
    pairs = [(key[r["sample_id"]], r["human_verdict"].strip().upper()) for r in rows]
    by_criterion: dict[str, list] = defaultdict(list)
    for r, pair in zip(rows, pairs):
        by_criterion[r["criterion_id"]].append(pair)
    kappa = cohen_kappa(pairs)
    report = {"n_samples": len(pairs), "meets_min_20": len(pairs) >= 20,
              "agreement_pct": round(100 * sum(a == b for a, b in pairs) / len(pairs), 1) if pairs else None,
              "cohen_kappa": kappa, "reliable": kappa is not None and kappa >= 0.6,
              "by_criterion": {c: {"n": len(p), "agreement_pct": round(100 * sum(a == b for a, b in p) / len(p), 1)}
                               for c, p in sorted(by_criterion.items())},
              "disagreements": [{"sample_id": r["sample_id"], "conversation_id": r["conversation_id"],
                                 "criterion_id": r["criterion_id"], "llm": a, "human": b}
                                for r, (a, b) in zip(rows, pairs) if a != b]}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "judge_agreement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "disagreements"}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true")
    group.add_argument("--ingest", action="store_true")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261007)
    args = parser.parse_args()
    export(args.n, args.seed) if args.export else ingest()


if __name__ == "__main__":
    main()
