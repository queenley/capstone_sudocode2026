"""``run_eval.py --report``: the report's three tables, from finished runs.

No model and no database: it reads what ``run_eval.py`` wrote. Each configuration is one run directory, named with
``--run router=<dir>``; the Baseline column is that run's own baseline. A cell nothing measured says so, with the
reason under the table, and two columns that cannot be compared are flagged rather than printed side by side in silence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import performance

SECTIONS = ("asr", "agent", "performance")
COLUMNS = {
    "router": "Agent Harness (Router)",
    "subagent": "Agent Harness (Subagent)",
    "gaploop": "Agent Harness (GapLoop)",
    "reflection": "Agent Harness (Reflection)",
    "ab": "Agent Harness (A/B Testing)",
}
#: Columns the agent has no mode for yet: a run of it would be the Router again.
NOT_BUILT = {"subagent": "Subagent", "ab": "A/B Testing"}
#: Columns that differ from the Router only in the approved entries of the knowledge version.
FROM_KNOWLEDGE = {"gaploop": "GapLoop", "reflection": "Reflection"}
AGENT_METRICS = (
    ("1. Repeat-Question Rate (RQR)", "repeat_question_rate", None),
    ("2. Context Carryover Rate (CCR)", "context_carryover_rate", None),
    ("3. Task Success Rate (TSR)", "task_success_rate", None),
    # The figure the organisers' own table prints for HR.
    ("4. Hallucination Rate (HR)", "hallucination_rate", "price_promo_only"),
)


def sections(value: str) -> tuple[str, ...]:
    """``all``, or a comma-separated choice of :data:`SECTIONS`."""
    chosen = tuple(part.strip() for part in value.split(",") if part.strip())
    if chosen == ("all",):
        return SECTIONS
    unknown = sorted(set(chosen) - set(SECTIONS))
    if unknown or not chosen:
        raise ValueError(f"--report takes all or {', '.join(SECTIONS)}, not {value!r}")
    return tuple(name for name in SECTIONS if name in chosen)


def named_run(value: str) -> tuple[str, Path]:
    """``router=evaluation/runs/x`` as ``("router", Path(...))``."""
    name, separator, directory = value.partition("=")
    if not separator or name not in COLUMNS or not directory:
        raise ValueError(f"--run takes <{'|'.join(COLUMNS)}>=<run dir>, not {value!r}")
    return name, Path(directory)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _rate(section: Mapping[str, Any] | None, key: str, sub: str | None) -> str:
    """A rate of the organisers' report, with what it was counted on."""
    metric = (section or {}).get(key)
    if not isinstance(metric, Mapping):
        return "chưa đo"
    part = metric.get(sub) if sub and isinstance(metric.get(sub), Mapping) else metric
    return "chưa đo" if part.get("value") is None else f"{part['value']:g}%"


def _markdown(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    return "\n".join("| " + " | ".join(row) + " |" for row in (header, ["---"] * len(header), *rows))


def _empty(name: str) -> str:
    return "chưa có" if name in NOT_BUILT else "chưa đo"


def asr_table(directory: Path | None) -> str:
    """WER, CER and Entity Accuracy of an ``--asr`` run, by the organisers' scorer."""
    report = None
    if directory is not None:
        report = _json(directory / "report.json") or _json(directory / "result" / "report.json")
        if report is None:
            raise ValueError(f"{directory} has no ASR report.json")
    scores = (report or {}).get("main_scorer") or {}
    model = str(((report or {}).get("manifest") or {}).get("model") or "Zipformer 30M")
    # One scorer run per stage of the text: the recogniser's own words, then after each correction.
    stages = [(stage, scores.get(stage) or {}) for stage in scores] or [("raw", {})]

    def cell(score: Mapping[str, Any], key: str) -> str:
        return "chưa đo" if score.get(key) is None else f"{score[key]:g}%"

    header = ["Metrics", *[model if stage == "raw" else f"{model} ({stage})" for stage, _ in stages]]
    return "Phần ASR\n\n" + _markdown(header, [
        [title, *[cell(score, key) for _, score in stages]]
        for title, key in (("1. WER (Word Error Rate)", "WER"), ("2. CER (Character Error Rate)", "CER"),
                           ("3. Entity Accuracy", "entity_accuracy"))])


def agent_table(runs: Mapping[str, Path]) -> str:
    reports = {name: _json(directory / "report.json") or {} for name, directory in runs.items()}
    baseline = (reports.get("router") or {}).get("baseline")
    header = ["Metrics", "Baseline", *[label.replace(" (Router)", "") for label in COLUMNS.values()]]
    rows = [[title, _rate(baseline, key, sub),
             *[_rate(reports[name].get("system"), key, sub) if name in reports else _empty(name) for name in COLUMNS]]
            for title, key, sub in AGENT_METRICS]
    return "Phần Agent\n\n" + _markdown(header, rows)


def _figures(directory: Path) -> dict[str, Any] | None:
    try:
        figures = performance.measure(directory)
    except (OSError, ValueError):
        return None
    return {**figures, "sessions": _json(directory / "sessions.json") or []}


def _stat(figures: Mapping[str, Any], name: str) -> str:
    stats = figures["latency"].get(name)
    return f"{stats['p95_ms'] / 1000:.2f} s" if stats else "chưa đo"


def _held(figures: Mapping[str, Any]) -> str:
    if not figures["sessions"]:
        return "chưa đo"
    held = [level["sessions"] for level in figures["sessions"] if level["held"]]
    return f"{max(held)} phiên" if held else "không mức nào đạt"


def _mode(figures: Mapping[str, Any]) -> str:
    advisor = figures.get("advisor") or {}
    modes = ", ".join(figures["modes"])
    return f"{modes}; {advisor.get('model', '?')}"


def performance_table(runs: Mapping[str, Path]) -> str:
    figures = {name: _figures(directory) for name, directory in runs.items()}

    def row(title: str, read: Any) -> list[str]:
        cells = [read(figures[name]) if figures.get(name) else _empty(name) for name in COLUMNS]
        return [title, *cells]

    def tokens(field: str, model: str | None = None) -> Any:
        def read(one: Mapping[str, Any]) -> str:
            spent = one["tokens_per_turn"]
            if spent is None:
                return "chưa đo"
            return f"${spent['cost_usd'][model]:.5f}" if model else f"{spent[field]:g}"
        return read

    def cached(one: Mapping[str, Any]) -> str:
        share = (one["tokens_per_turn"] or {}).get("cached_share")
        return "chưa đo" if share is None else f"{share:g}%"

    rows = [
        row("Chế độ vận hành", _mode),
        row("Thời gian nạp Call Brief (p95)", lambda one: _stat(one, "call_brief")),
        row("TTFT chat (p95)", lambda one: _stat(one, "ttft")),
        row("TTFA voice (p95)", lambda one: _stat(one, "ttfa")),
        row("Total Latency (p95)", lambda one: _stat(one, "total")),
        row("Số phiên đồng thời (demo)", _held),
        row("Số token mỗi lượt hỏi (TB)", tokens("total")),
        row("Token đầu vào lấy từ prompt cache", cached),
        *[row(f"Số tiền mỗi lượt hỏi (TB), {model}", tokens("cost_usd", model)) for model in performance.PRICES],
    ]
    return "Chế độ hoạt động & hiệu năng\n\n" + _markdown(("Metrics", *COLUMNS.values()), rows)


def _scenario_set(manifest: Mapping[str, Any]) -> Any:
    """The scenario files of a run by hash, so renaming their folder does not make it another set."""
    scenarios = manifest.get("scenarios")
    return scenarios.get("files") if isinstance(scenarios, Mapping) else scenarios


def notes(runs: Mapping[str, Path]) -> list[str]:
    """Why a cell is empty, and which columns must not be read side by side."""
    found = [f"{label}: agent chưa có chế độ này, nên cột không có số." for name, label in NOT_BUILT.items() if name not in runs]
    manifests = {name: _json(directory / "manifest.json") or {} for name, directory in runs.items()}
    router = manifests.get("router") or {}
    expected_profiles = {"router": "router", "gaploop": "gaploop", "reflection": "reflection"}
    for name, manifest in manifests.items():
        profile = (manifest.get("evaluation") or {}).get("profile")
        expected = expected_profiles.get(name)
        if profile and expected and profile != expected:
            found.append(f"{COLUMNS[name]}: nhãn cột là {expected} nhưng manifest ghi profile {profile}.")
    for name, label in FROM_KNOWLEDGE.items():
        if name not in runs:
            requirement = "knowledge version có mục đã duyệt, rồi chạy với --kb-version <N>" if name == "gaploop" \
                else "skills version đã duyệt, rồi chạy với --skills-version <N>"
            found.append(f"{label}: chưa có run; cần {requirement}.")
        elif manifests[name].get("knowledge_sha256") == router.get("knowledge_sha256"):
            found.append(f"{label}: cùng knowledge với Router, nên số này chỉ là chạy lại Router.")
    reflection = manifests.get("reflection") or {}
    reflection_version = (reflection.get("evaluation") or {}).get("skills_version_override")
    router_version = (router.get("evaluation") or {}).get("skills_version_override")
    if "reflection" in manifests and reflection_version is not None and reflection_version == router_version:
        found.append("Reflection: cùng skills version với Router, nên đây không phải phép đo thay đổi Reflection.")
    for name, manifest in manifests.items():
        if name != "router" and router and _scenario_set(manifest) != _scenario_set(router):
            found.append(f"{COLUMNS[name]}: khác bộ kịch bản với Router, không so được.")
        if name != "router" and router and manifest.get("models") != router.get("models"):
            found.append(f"{COLUMNS[name]}: khác model với Router.")
    return found


def render(chosen: Sequence[str], runs: Mapping[str, Path], asr_run: Path | None = None) -> str:
    """The chosen tables, in the report's order, then the notes on what they leave out."""
    missing = [str(directory) for directory in (*runs.values(), *([asr_run] if asr_run else [])) if not directory.is_dir()]
    if missing:
        raise ValueError(f"Not a run directory: {', '.join(missing)}")
    parts = []
    if "asr" in chosen:
        parts.append(asr_table(asr_run))
    if "agent" in chosen:
        parts.append(agent_table(runs))
    if "performance" in chosen:
        parts.append(performance_table(runs))
    if {"agent", "performance"} & set(chosen):
        parts.append("Ghi chú\n\n" + "\n".join(f"- {note}" for note in notes(runs)))
    return "\n\n".join(parts)
