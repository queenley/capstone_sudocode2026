"""ASR ground truth of the scenario audio: each customer turn in spoken form, written by a model before TTS reads it.

``synthesize_scenario_audio`` uses this module in three steps:

1. :func:`load_or_build` writes ``output/asr_reference/scenarios_<id>/call_<n>.json``.
   It makes one model call per call and is cached while the lines keep the same words. A line is
   ``{idx, speaker: A|C, text}``: the per-turn clips use the customer's lines, ``build_asr_testset``'s whole
   dialogues both speakers' (under ``output/asr_test/spoken/``).
2. TTS reads ``turns[k].spoken_text``. The ``.json`` written beside each WAV keeps that text and its ``entities``.
3. :func:`write_ground_truth` writes ``output/asr_reference/ground_truth.json`` in BTC's ``data/asr/`` format, one dialogue per clip.

Because the voice reads exactly the reference, the reference is right by construction.
:func:`problems` checks the model's answer line by line:
- no digit or code is left;
- the other words of the line are kept;
- every entity is stated in the line.

A line that still fails after one more try falls back to the rules (``spoken.py``, ``entities.py``),
and its ``reference_source`` says ``rule``.
Typed chat (teencode, no diacritics, typos) is not speech: it gets no reference.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.asr import entities as rule_entities
from src.asr.spoken import to_spoken
from src.schemas.asr import SpokenCall, SpokenTurn, entity_schema
from src.schemas.scenario import CallSpec, Scenario
from src.utils.dataset import Dataset, call_folder
from src.utils.paths import ASR_REFERENCE_DIR, AUDIO_DIR, DATA_DIR, PROMPTS_DIR

PROMPT = (PROMPTS_DIR / "asr_reference.md").read_text(encoding="utf-8").strip()
#: Typed chat read aloud is not what a caller says; the ASR set leaves it out (as the harness does).
NOT_SPEECH = {"chat_teencode", "chat_khong_dau", "chat_sai_chinh_ta"}
MAX_ATTEMPTS = 2
#: Share of a line's plain words the spoken form must keep, in order.
MIN_KEPT = 0.9
#: Entities read as numbers, checked against the numbers the line states (0, "miễn phí", is not said as a number).
NUMERIC = ("room_area_m2", "budget_vnd", "competitor_price_vnd", "size_old", "size_new", "price_vnd", "delivery_days",
           "warranty_months", "return_days", "min_free_ship_vnd", "bulky_fee_vnd", "exchange_fee_vnd", "refund_vnd")
#: BTC's speaker labels: the shop agent and the customer.
AGENT, CUSTOMER = "A", "C"


def _norm(text: str) -> str:
    """BTC's WER normalisation: lowercase, NFC, no punctuation, single spaces."""
    text = re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", text.lower()))
    return re.sub(r"\s+", " ", text).strip()


def _plain_words(text: str) -> list[str]:
    """The words of *text* a spoken form must keep: not numbers, codes, units or brand names."""
    words = []
    for token in re.findall(r"[^\s,.;:!?()\"']+", text):
        if re.search(r"\d", token) or re.search(r"[A-Z]", token[1:]) or (token.isascii() and token.isupper()):
            continue
        words += _norm(token).split()
    return words


def numbers(text: str) -> set[int]:
    """Every number *text* states, digits or words, as the agent's ITN reads it ("năm triệu bảy" -> 5700000)."""
    written = rule_entities._itn().normalise(text.lower(), datetime(2026, 1, 1))
    return {int(re.sub(r"[.,]", "", raw)) for raw in re.findall(r"\d[\d.,]*\d|\d", written)}


def problems(text: str, turn: SpokenTurn, products: dict[str, str]) -> list[str]:
    """How *turn* (the model's spoken form of the line *text*) fails the rules of ``asr_reference.md``."""
    spoken = turn.spoken_text
    found = []
    if re.search(r"\d", spoken):
        found.append("digit_left")
    if re.search(r"\bsku-|\b[a-z]{1,4}-[a-z0-9]{1,4}-[a-z0-9]+", spoken.lower()):   # SKU-AP-X, TV-OLED-55
        found.append("code_left")
    plain, said = _plain_words(text), _norm(spoken).split()
    if plain:
        kept = sum(block.size for block in SequenceMatcher(None, plain, said, autojunk=False).get_matching_blocks())
        if kept / len(plain) < MIN_KEPT:
            found.append("words_changed")
    if len(said) > 1.5 * len(_norm(to_spoken(text)).split()) + 4:
        found.append("words_added")
    stated_numbers, said_numbers = numbers(to_spoken(text)) | numbers(text), numbers(spoken)
    for key, value in turn.entities.stated().items():
        if key == "sku" and value not in products:
            found.append("entity_unknown:sku")
        elif key == "order_id" and str(value).lower() not in text.lower():
            found.append("entity_not_stated:order_id")
        elif key == "phone" and re.sub(r"\D", "", str(value)) not in re.sub(r"\D", "", text):
            found.append("entity_not_stated:phone")
        elif key in NUMERIC and str(value).isdigit() and int(value) and not {int(value)} <= stated_numbers & said_numbers:
            found.append(f"entity_not_stated:{key}")
    return found


def rule_turn(line: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    """The rule-made reference of one line, when the model's could not be used."""
    spoken = to_spoken(line["text"])
    return {**line, "spoken_text": spoken, "entities": rule_entities.extract(spoken), "reference_source": "rule",
            "issues": issues}


def customer_lines(call: CallSpec) -> list[dict[str, Any]]:
    """The lines of the per-turn clips: the customer's turns of the call."""
    return [{"idx": i, "speaker": CUSTOMER, "text": text} for i, text in enumerate(call.customer_turns, start=1)]


def products_of(call: CallSpec, names: dict[str, str], lines: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """SKU -> name of the products this call is about (its labels), or whose name a line says."""
    labels = json.dumps(call.model_dump(mode="json"), ensure_ascii=False)
    said = " ".join(line["text"] for line in (lines or customer_lines(call))).lower()
    return {sku: name for sku, name in names.items() if sku in labels or name.lower() in said}


def _sha(lines: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps([[line["speaker"], line["text"]] for line in lines], ensure_ascii=False).encode("utf-8")).hexdigest()


def reference_path(scenario_id: str, call: str, root: Path = ASR_REFERENCE_DIR) -> Path:
    return root / call_folder(scenario_id) / f"{call}.json"


def build(client, scenario: Scenario, call_name: str, call: CallSpec, products: dict[str, str],
          line_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ask the model for the spoken form of every line (``{idx, speaker: A|C, text}``); check it; fall back per line."""
    line_list = line_list or customer_lines(call)
    by_idx = {line["idx"]: line for line in line_list}
    lines = {line["idx"]: line["text"] for line in line_list}
    request = {"input_mode": call.input_mode, "region": scenario.region, "products": products,
               "lines": [{"idx": line["idx"], "speaker": "agent" if line["speaker"] == AGENT else "customer",
                          "text": line["text"]} for line in line_list]}
    prompt = f"{PROMPT}\n\nCALL JSON (trusted):\n{json.dumps(request, ensure_ascii=False)}"
    accepted: dict[int, dict[str, Any]] = {}
    issues: dict[int, list[str]] = {i: ["no_answer"] for i in lines}
    for attempt in range(MAX_ATTEMPTS):
        hint = "" if attempt == 0 else "\n\nYour previous answer broke the rules on these lines; fix them:\n" + \
            json.dumps({i: issues[i] for i in lines if i not in accepted}, ensure_ascii=False)
        try:
            answer = client.generate(prompt + hint, SpokenCall, temperature=0, max_output_tokens=4096)
        except RuntimeError as error:   # no valid JSON after the client's own retries
            issues = {i: [f"model_error: {error}"] for i in lines if i not in accepted}
            break
        for turn in answer.turns:
            if turn.idx in lines and turn.idx not in accepted:
                turn = turn.model_copy(update={"spoken_text": unicodedata.normalize("NFC", turn.spoken_text.lower()).strip()})
                issues[turn.idx] = problems(lines[turn.idx], turn, products)
                if not issues[turn.idx]:
                    accepted[turn.idx] = {**by_idx[turn.idx], "spoken_text": turn.spoken_text,
                                          "entities": turn.entities.stated(), "reference_source": "llm", "issues": []}
        if len(accepted) == len(lines):
            break
    turns = [accepted.get(i) or rule_turn(by_idx[i], issues.get(i, ["no_answer"])) for i in lines]
    return {"scenario_id": scenario.scenario_id, "call": call_name, "input_mode": call.input_mode,
            "source_sha256": _sha(line_list), "model": getattr(client, "model", None), "turns": turns}


def load_or_build(client_factory, scenario: Scenario, call_name: str, call: CallSpec, names: dict[str, str],
                  root: Path = ASR_REFERENCE_DIR, lines: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The call's reference from disk while its lines are unchanged, otherwise built and saved; None for typed chat.

    *lines* default to the customer's turns (the per-turn clips); a whole dialogue passes both speakers' lines
    and its own *root* (``build_asr_testset``).
    """
    lines = lines or customer_lines(call)
    if call.input_mode in NOT_SPEECH or not lines:
        return None
    path = reference_path(scenario.scenario_id, call_name, root)
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("source_sha256") == _sha(lines):
            return record
    record = build(client_factory(), scenario, call_name, call, products_of(call, names, lines), lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def write_ground_truth(audio_root: Path = AUDIO_DIR, out: Path = ASR_REFERENCE_DIR / "ground_truth.json",
                       dataset: Dataset | None = None) -> dict[str, Any]:
    """``ground_truth.json`` in BTC's ``asr/`` format from the clips on disk: one dialogue per spoken customer turn.

    A clip is left out when it is typed chat, has no spoken reference (spoken before this module existed),
    or its words are no longer that turn of the current scenario (stale audio).
    """
    dataset = dataset or Dataset()
    btc = json.loads((DATA_DIR / "asr" / "ground_truth.json").read_text(encoding="utf-8"))
    dialogues, left_out = [], {}
    for meta_path in sorted(audio_root.glob("scenarios_*/call_*/turn_*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        scenario = dataset.scenario(meta.get("scenario_id", ""))
        call = scenario.calls.get(meta.get("call")) if scenario else None
        turn = meta.get("turn")
        if meta.get("input_mode") in NOT_SPEECH:
            reason = "not_speech"
        elif not meta.get("spoken_text"):
            reason = "no_spoken_reference"
        elif call is None or not isinstance(turn, int) or not 1 <= turn <= len(call.customer_turns) \
                or call.customer_turns[turn - 1] != meta.get("text") or not meta_path.with_suffix(".wav").exists():
            reason = "stale"
        else:
            reason = None
        if reason:
            left_out[reason] = left_out.get(reason, 0) + 1
            continue
        spoken, stated = meta["spoken_text"], meta.get("entities") or {}
        noise = (meta.get("noise") or {}).get("type")
        dialogues.append({
            "id": f"{meta['scenario_id']}-{meta['call']}-t{turn}",
            "customer_region": scenario.region, "customer_gender": meta.get("customer_gender"),
            "agent_gender": None, "agent_region": None,
            "scenario_ref": f"{meta['scenario_id']} {meta['call']} turn {turn}", "noisy": bool(noise),
            "note": f"{scenario.persona}; {noise or 'clean'}",
            "entities": stated, "full_text": spoken, "n_turns": 1,
            "turns": [{"idx": 1, "speaker": "C", "text": spoken, "entities": stated}],
            # Not in BTC's file: where the clip is and how its reference was made.
            "audio": meta_path.with_suffix(".wav").relative_to(audio_root.parent).as_posix(),
            "source_text": meta["text"], "reference_source": meta.get("reference_source"), "noise": noise or "clean",
            "input_mode": meta.get("input_mode"), "duration_seconds": meta.get("duration_seconds"),
        })
    seconds = sum(float(d["duration_seconds"] or 0) for d in dialogues)
    ground_truth = {
        "description": f"ASR ground truth of the scenario audio: {len(dialogues)} customer turns "
                       f"({sum(d['noisy'] for d in dialogues)} with noise, {seconds / 3600:.2f} h). The model wrote "
                       "each turn in spoken form and the TTS voice read exactly that text; 'rule' references "
                       "come from src/asr/spoken.py.",
        "hypotheses_format": btc["hypotheses_format"], "normalization_rule": btc["normalization_rule"],
        "reference_date": btc["reference_date"], "kind": "turns",
        # Not in BTC's file: the entity keys and types, so the evaluator extracts the same ones from what was heard.
        "entity_schema": entity_schema(), "dialogues": dialogues,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sources = [d["reference_source"] for d in dialogues]
    return {"dialogues": len(dialogues), "llm": sources.count("llm"), "rule": sources.count("rule"),
            "audio_hours": round(seconds / 3600, 3), "left_out": left_out, "path": out.as_posix()}
