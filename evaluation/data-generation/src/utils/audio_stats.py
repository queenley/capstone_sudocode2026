"""Analyse generated customer audio: volume, calls per customer, channel and noise.

Source files: ``<seed>/audio/scenarios_<id>/call_<n>/turn_<k>.wav`` plus the
adjacent ``turn_<k>.json`` written by ``synthesize_scenario_audio``. Customer and
channel come from the scenario file (old-schema scenarios are read leniently).

Noise status per turn:
* ``clean``   – metadata says ``"noise": null``
* ``<type>``  – street / cafe / wind / weak_signal (with ``snr_db``)
* ``unknown`` – no TTS metadata (the JSON stub was overwritten or never written);
  such turns are excluded from noise ratios instead of being counted as clean.
"""
from __future__ import annotations

import json
import statistics
import wave
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.utils.crm import load_customers
from src.utils.dataset import Dataset
from src.utils.paths import AUDIO_DIR

DATASET = Dataset()

UNKNOWN = "unknown"
MALE_HONORIFICS = {"anh", "chú", "ông", "em trai", "bác trai"}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scenario_info(scenario_id: str, cache: dict[str, dict], customers: dict[str, Any]) -> dict[str, Any]:
    """customer_id, persona and per-call channel/input_mode/speaker of a scenario."""
    if scenario_id not in cache:
        raw = _read(DATASET.scenarios_dir / f"{scenario_id}.json")
        meta = _read(DATASET.metadata_dir / f"{scenario_id}.json")
        calls = {name: {**call, **(meta.get("calls") or {}).get(name, {})} for name, call in (raw.get("calls") or {}).items()}
        customer = meta.get("customer_id")
        default_channel = "hotline"   # btc_export omits the channel of a hotline call
        cache[scenario_id] = {
            "customer_id": customer or UNKNOWN,
            "customer_name": raw.get("customer_name"),
            "region": meta.get("region", UNKNOWN),
            "persona": raw.get("persona", UNKNOWN),
            "channels": {name: call.get("channel", default_channel) for name, call in calls.items()},
            "input_modes": {name: call.get("input_mode", "text") for name, call in calls.items()},
            "genders": {name: ("male" if (customers.get(call.get("speaker_customer_id") or customer) and
                                              customers[call.get("speaker_customer_id") or customer].honorific.lower() in MALE_HONORIFICS)
                               else "female") for name, call in calls.items()},
        }
    return cache[scenario_id]


def _duration(wav: Path, meta: dict[str, Any]) -> float:
    if meta.get("duration_seconds"):
        return float(meta["duration_seconds"])
    try:
        with wave.open(str(wav), "rb") as stream:
            return stream.getnframes() / stream.getframerate()
    except (wave.Error, OSError):
        return 0.0


def collect(audio_dir: Path = AUDIO_DIR) -> list[dict[str, Any]]:
    """One record per synthesized customer turn."""
    cache: dict[str, dict] = {}
    customers = {customer.customer_id: customer for customer in load_customers()}
    turns = []
    for wav in sorted(audio_dir.glob("scenarios_*/call_*/turn_*.wav")):
        meta = _read(wav.with_suffix(".json"))
        scenario_id = wav.parent.parent.name.removeprefix("scenarios_")
        call = wav.parent.name
        info = _scenario_info(scenario_id, cache, customers)
        if "noise" not in meta:
            noise, snr = UNKNOWN, None
        elif meta["noise"]:
            noise, snr = meta["noise"].get("type", UNKNOWN), meta["noise"].get("snr_db")
        else:
            noise, snr = "clean", None
        turns.append({
            "scenario_id": scenario_id, "call": call, "customer_id": info["customer_id"],
            "customer_name": info["customer_name"], "region": info["region"], "persona": info["persona"],
            "channel": info["channels"].get(call, UNKNOWN),
            "gender": info["genders"].get(call, "female"),
            "input_mode": meta.get("input_mode") or info["input_modes"].get(call, "text"),
            "voice_id": meta.get("voice_id") or UNKNOWN, "noise": noise, "snr_db": snr,
            "seconds": _duration(wav, meta),
        })
    return turns


def _noise_share(rows: list[dict]) -> tuple[int, int]:
    """(noisy turns, turns with known noise status)."""
    known = [r for r in rows if r["noise"] != UNKNOWN]
    return sum(r["noise"] != "clean" for r in known), len(known)


def summarize(turns: list[dict[str, Any]]) -> dict[str, Any]:
    calls: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for turn in turns:
        calls[(turn["scenario_id"], turn["call"])].append(turn)
    call_seconds = [sum(t["seconds"] for t in rows) for rows in calls.values()]
    noisy, known = _noise_share(turns)

    # -- per customer -----------------------------------------------------------
    by_customer: dict[str, dict[str, Any]] = {}
    for (scenario_id, call), rows in calls.items():
        first = rows[0]
        item = by_customer.setdefault(first["customer_id"], {
            "customer_id": first["customer_id"], "customer_name": first["customer_name"], "region": first["region"],
            "scenarios": set(), "calls": 0, "turns": 0, "seconds": 0.0, "channels": Counter(), "rows": []})
        item["scenarios"].add(scenario_id)
        item["calls"] += 1
        item["turns"] += len(rows)
        item["seconds"] += sum(r["seconds"] for r in rows)
        item["channels"][first["channel"]] += 1
        item["rows"] += rows
    customers = []
    for item in sorted(by_customer.values(), key=lambda x: (-x["calls"], x["customer_id"])):
        c_noisy, c_known = _noise_share(item.pop("rows"))
        customers.append({**item, "scenarios": len(item["scenarios"]), "channels": dict(item["channels"]),
                          "noisy_turns": c_noisy, "noise_known_turns": c_known})

    # -- per channel / input mode --------------------------------------------------
    def group(key: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for value in sorted({t[key] for t in turns}):
            rows = [t for t in turns if t[key] == value]
            g_noisy, g_known = _noise_share(rows)
            out[value] = {"calls": len({(r["scenario_id"], r["call"]) for r in rows}), "turns": len(rows),
                          "customers": len({r["customer_id"] for r in rows}),
                          "minutes": round(sum(r["seconds"] for r in rows) / 60, 2),
                          "noisy_turns": g_noisy, "noise_known_turns": g_known,
                          "noise_types": dict(Counter(r["noise"] for r in rows))}
        return out

    # -- noise ----------------------------------------------------------------------
    noise_types = {}
    for noise, count in Counter(t["noise"] for t in turns).most_common():
        rows = [t for t in turns if t["noise"] == noise]
        noise_types[noise] = {"turns": count, "minutes": round(sum(r["seconds"] for r in rows) / 60, 2),
                              "share_of_turns": round(count / len(turns), 4)}
    snr = Counter(str(t["snr_db"]) for t in turns if t["snr_db"] is not None)
    noisy_calls = sum(any(r["noise"] not in ("clean", UNKNOWN) for r in rows) for rows in calls.values())
    calls_per_customer = Counter(c["calls"] for c in customers)

    region_gender: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for turn in turns:
        grouped[(turn["region"], turn["gender"])].append(turn)
    for (region, gender), rows in sorted(grouped.items()):
        region_gender[region][gender] = {
            "voices": len({r["voice_id"] for r in rows if r["voice_id"] != UNKNOWN}),
            "calls": len({(r["scenario_id"], r["call"]) for r in rows}),
            "turns": len(rows),
            "customers": len({r["customer_id"] for r in rows}),
        }

    return {
        "overview": {
            "scenarios": len({t["scenario_id"] for t in turns}), "calls": len(calls), "turns": len(turns),
            "customers": len(customers), "voices": len({t["voice_id"] for t in turns} - {UNKNOWN}),
            "hours": round(sum(t["seconds"] for t in turns) / 3600, 3),
            "mean_turn_seconds": round(statistics.mean(t["seconds"] for t in turns), 2) if turns else 0,
            "mean_call_seconds": round(statistics.mean(call_seconds), 2) if call_seconds else 0,
        },
        "noise_summary": {"noisy_turns": noisy, "noise_known_turns": known,
                          "unknown_turns": len(turns) - known,
                          "noisy_ratio": round(noisy / known, 4) if known else None,
                          "noisy_calls": noisy_calls, "noisy_call_ratio": round(noisy_calls / len(calls), 4) if calls else None,
                          "by_type": noise_types, "snr_db": dict(sorted(snr.items(), key=lambda x: float(x[0])))},
        "calls_per_customer_distribution": {str(k): v for k, v in sorted(calls_per_customer.items())},
        "customers_multi_call": sum(c["calls"] >= 2 for c in customers),
        "customers_multi_channel": sum(len(c["channels"]) >= 2 for c in customers),
        "by_channel": group("channel"),
        "by_input_mode": group("input_mode"),
        "by_region_gender": {region: dict(genders) for region, genders in region_gender.items()},
        "by_customer": customers,
    }


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.0%}" if denominator else "n/a"


def to_markdown(summary: dict[str, Any], max_customers: int = 40) -> list[str]:
    o, n = summary["overview"], summary["noise_summary"]
    if not o["turns"]:
        return ["## Audio analysis", "", "No synthesized audio yet (`python -m src.pipeline.synthesize_scenario_audio`).", ""]
    lines = ["## Audio analysis", "",
             f"- **{o['turns']} customer turns** in **{o['calls']} calls** from {o['scenarios']} scenarios and "
             f"{o['customers']} customers; **{o['hours']:.2f} h** total "
             f"(mean {o['mean_turn_seconds']} s/turn, {o['mean_call_seconds']} s/call), {o['voices']} distinct voices.",
             f"- Customers with ≥2 audio calls: {summary['customers_multi_call']} · with ≥2 channels: "
             f"{summary['customers_multi_channel']}.",
             f"- Noisy turns: {n['noisy_turns']}/{n['noise_known_turns']} with known status "
             f"({_pct(n['noisy_turns'], n['noise_known_turns'])}); calls with ≥1 noisy turn: "
             f"{n['noisy_calls']}/{o['calls']} ({_pct(n['noisy_calls'], o['calls'])}).", ""]
    if n["unknown_turns"]:
        lines += [f"> {n['unknown_turns']} turns have no TTS metadata (noise/voice unknown). Re-run "
                  "`synthesize_scenario_audio` for those scenarios to restore it.", ""]

    lines += ["### Noise", "", "| Noise | Turns | Share of turns | Minutes |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {v['turns']} | {v['share_of_turns']:.0%} | {v['minutes']} |" for k, v in n["by_type"].items()]
    if n["snr_db"]:
        lines += ["", "SNR (dB) of noisy turns: " + ", ".join(f"{k} dB × {v}" for k, v in n["snr_db"].items())]

    def group_table(title: str, data: dict[str, dict[str, Any]]) -> list[str]:
        rows = ["", f"### {title}", "", f"| {title.split()[-1].capitalize()} | Calls | Turns | Customers | Minutes | Noisy turns | Noise mix |",
                "|---|---:|---:|---:|---:|---:|---|"]
        for key, v in data.items():
            mix = ", ".join(f"{k} {c}" for k, c in sorted(v["noise_types"].items()))
            rows.append(f"| {key} | {v['calls']} | {v['turns']} | {v['customers']} | {v['minutes']} | "
                        f"{v['noisy_turns']}/{v['noise_known_turns']} ({_pct(v['noisy_turns'], v['noise_known_turns'])}) | {mix} |")
        return rows

    lines += group_table("By channel", summary["by_channel"])
    lines += group_table("By input mode", summary["by_input_mode"])

    lines += ["", "### Distinct voices by region and gender", "",
              "| Region | Gender | Voices | Calls | Turns | Customers |", "|---|---|---:|---:|---:|---:|"]
    for region, genders in summary["by_region_gender"].items():
        for gender, values in genders.items():
            lines.append(f"| {region} | {gender} | {values['voices']} | {values['calls']} | {values['turns']} | {values['customers']} |")

    dist = ", ".join(f"{k} call(s): {v} customers" for k, v in summary["calls_per_customer_distribution"].items())
    lines += ["", "### Calls per customer", "", f"Distribution — {dist}.", "",
              "| Customer | Name | Region | Scenarios | Audio calls | Turns | Minutes | Channels | Noisy turns |",
              "|---|---|---|---:|---:|---:|---:|---|---:|"]
    for c in summary["by_customer"][:max_customers]:
        channels = ", ".join(f"{k} ×{v}" for k, v in c["channels"].items())
        lines.append(f"| {c['customer_id']} | {c['customer_name'] or ''} | {c['region']} | {c['scenarios']} | {c['calls']} | "
                     f"{c['turns']} | {c['seconds'] / 60:.1f} | {channels} | {c['noisy_turns']}/{c['noise_known_turns']} |")
    if len(summary["by_customer"]) > max_customers:
        lines.append(f"\n_{len(summary['by_customer']) - max_customers} more customers in `audio_statistics.json`._")
    return lines + [""]
