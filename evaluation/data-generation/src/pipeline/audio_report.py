"""How much of the generated audio is clean and how much is noisy, for both ASR sets.

* the turn set (``<seed>/audio/``, ``synthesize_scenario_audio``): one clip per customer turn, a share of them
  mixed with street / cafe / wind / weak_signal noise at ``scenario_audio.noise_snr_db`` (``src/utils/audio_stats.py`` reads
  each clip's metadata: noise type, SNR, duration, channel, input mode);
* the dialogue set (``<seed>/asr_test/``, ``build_asr_testset``): two-speaker calls, every third one on a
  telephone band with packet loss (``weak_signal``, 10 dB), as BTC's 4 of 12.

Writes ``<seed>/reports/audio_report.json`` and ``audio_report.md`` and prints the summary. Reads files only,
no API call.

    python -m src.pipeline.audio_report
"""
from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from src.utils.audio_stats import UNKNOWN, collect, summarize
from src.utils.paths import ASR_TEST_DIR, AUDIO_DIR, REPORTS_DIR
from src.utils.settings import load_settings


def _seconds(wav: Path) -> float | None:
    try:
        with wave.open(str(wav)) as stream:
            return stream.getnframes() / stream.getframerate()
    except (FileNotFoundError, wave.Error, EOFError):
        return None


def turn_set() -> dict[str, Any]:
    summary = summarize(collect(AUDIO_DIR))
    o, n = summary["overview"], summary["noise_summary"]
    settings = load_settings().get("scenario_audio", {})
    by_type = {noise: {"turns": v["turns"], "minutes": v["minutes"], "share": round(v["share_of_turns"], 4)}
               for noise, v in n["by_type"].items()}
    return {"turns": o["turns"], "calls": o["calls"], "scenarios": o["scenarios"], "hours": o["hours"],
            "clean_turns": by_type.get("clean", {}).get("turns", 0), "noisy_turns": n["noisy_turns"],
            "unknown_turns": n["unknown_turns"], "noisy_ratio": n["noisy_ratio"],
            "noisy_ratio_configured": settings.get("noise_fraction"), "snr_db_configured": settings.get("noise_snr_db"),
            "noisy_calls": n["noisy_calls"], "by_type": by_type, "snr_db": n["snr_db"],
            "by_channel": {k: {"turns": v["turns"], "noisy": v["noisy_turns"], "mix": v["noise_types"]}
                           for k, v in summary["by_channel"].items()},
            "by_input_mode": {k: {"turns": v["turns"], "noisy": v["noisy_turns"], "mix": v["noise_types"]}
                              for k, v in summary["by_input_mode"].items()},
            "target_hours": load_settings().get("generation", {}).get("audio_hours_target")}


def dialogue_set() -> dict[str, Any] | None:
    path = ASR_TEST_DIR / "ground_truth.json"
    if not path.exists():
        return None
    dialogues = json.loads(path.read_text(encoding="utf-8")).get("dialogues") or []
    rows = []
    for d in dialogues:
        seconds = _seconds(ASR_TEST_DIR / "audio" / f"{d['id']}.wav")
        rows.append({"id": d["id"], "noisy": bool(d.get("noisy")), "seconds": seconds, "turns": d.get("n_turns")})
    present = [r for r in rows if r["seconds"] is not None]
    return {"dialogues": len(rows), "noisy": sum(r["noisy"] for r in rows), "clean": sum(not r["noisy"] for r in rows),
            "noise": "weak_signal (băng thông điện thoại + mất gói), 10 dB",
            "with_audio": len(present), "missing_audio": [r["id"] for r in rows if r["seconds"] is None],
            "minutes": round(sum(r["seconds"] for r in present) / 60, 2),
            "noisy_minutes": round(sum(r["seconds"] for r in present if r["noisy"]) / 60, 2)}


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "—"


def markdown(report: dict[str, Any]) -> str:
    t, d = report["turn_set"], report["dialogue_set"]
    lines = ["# Báo cáo audio", ""]
    if not t["turns"]:
        lines += ["Chưa có audio theo lượt (`python -m src.pipeline.synthesize_scenario_audio`).", ""]
    else:
        known = t["turns"] - t["unknown_turns"]
        lines += ["## Bộ theo lượt khách (`audio/`)", "",
                  f"- {t['turns']} clip, {t['calls']} cuộc gọi, {t['scenarios']} kịch bản, **{t['hours']:.2f} giờ** "
                  f"(mục tiêu {t['target_hours']} giờ).",
                  f"- **Sạch {t['clean_turns']}** · **nhiễu {t['noisy_turns']}** ({_pct(t['noisy_turns'], known)} số clip "
                  f"biết trạng thái; cấu hình {t['noisy_ratio_configured'] or 0:.0%} ở {t['snr_db_configured']} dB) · "
                  f"không rõ {t['unknown_turns']}.",
                  f"- Cuộc có ít nhất một lượt nhiễu: {t['noisy_calls']}/{t['calls']}.", "",
                  "| Loại | Clip | Tỉ lệ | Phút |", "|---|---:|---:|---:|"]
        names = {"clean": "sạch", "street": "đường phố", "cafe": "quán cà phê", "wind": "gió",
                 "weak_signal": "sóng yếu / điện thoại", UNKNOWN: "không rõ (thiếu metadata)"}
        lines += [f"| {names.get(k, k)} | {v['turns']} | {v['share']:.0%} | {v['minutes']} |" for k, v in t["by_type"].items()]
        if t["snr_db"]:
            lines += ["", "SNR của clip nhiễu: " + ", ".join(f"{k} dB × {v}" for k, v in t["snr_db"].items())]
        for title, key in (("Theo kênh", "by_channel"), ("Theo cách nhập (input mode)", "by_input_mode")):
            lines += ["", f"### {title}", "", "| | Clip | Nhiễu | Các loại |", "|---|---:|---:|---|"]
            lines += [f"| {k} | {v['turns']} | {v['noisy']} | {', '.join(f'{n} {c}' for n, c in sorted(v['mix'].items()))} |"
                      for k, v in t[key].items()]
    lines += ["", "## Bộ hội thoại hai người (`asr_test/`)", ""]
    if d is None:
        lines += ["Chưa dựng (`python -m src.pipeline.build_asr_testset --limit 24`)."]
    else:
        lines += [f"- {d['dialogues']} hội thoại: **sạch {d['clean']}**, **nhiễu {d['noisy']}** ({d['noise']}).",
                  f"- Có audio {d['with_audio']}/{d['dialogues']}, {d['minutes']} phút (nhiễu {d['noisy_minutes']} phút)."]
        if d["missing_audio"]:
            lines += [f"- Thiếu file WAV: {', '.join(d['missing_audio'][:20])}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    report = {"turn_set": turn_set(), "dialogue_set": dialogue_set()}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "audio_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = markdown(report)
    (REPORTS_DIR / "audio_report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {REPORTS_DIR / 'audio_report.md'}")


if __name__ == "__main__":
    main()
