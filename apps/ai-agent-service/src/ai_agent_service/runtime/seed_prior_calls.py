"""The organisers' earlier calls as the live shop's memory: one story per customer, from the scenario files.

    python -m ai_agent_service.runtime.seed_prior_calls --scenarios data/dev/scenarios [--dry-run] [--shop]

``--shop`` first puts the organisers' CRM customers (and their order history) into the website's database, so
the same chị Hoa is one customer on the website, on Zalo and on the hotline (``runtime/shop_orders.py``).

A scenario of two calls or more tells what the customer said in its first call (``call_1``: the goal, and
``facts_established``, what that call settled). The live database holds nothing of it, so a customer the organisers
wrote about (chị Hoa, ``0984726714``) meets an assistant that knows nothing of her past. This writes, for each
phone number, the first scenario (by id) that has an earlier call: its facts on the ledger and one episode, dated
``days_later`` before the shop's business day, exactly as an evaluation run seeds ``seed_history``
(:func:`ai_agent_service.pipeline.eval.runner.seed`), through the ``memory_writer`` role.

One scenario a number, never all: ``data/dev`` tells eleven different stories of chị Hoa (25 m² in one, 30 m² in
another), and the ledger would hold the last one written with the others as superseded history.

The live database only (``DATABASE_URL`` / ``AGENT_DATABASE_URL``): never an ``*_eval`` one, which every evaluation
run empties. Safe to run again: an episode is keyed by its call id, a fact already active is skipped. No model call.

The call-backs ``call_1`` booked (``schedule.callback`` in ``data/dev/conversations/scenarios_<id>/call_1.json``) are
booked again in the shared mock state, each under its own idempotency key, so the sales team's "Hẹn gọi lại" lists
them as the assistant left them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from ..components.memory import brief, ontology
from ..config.database import configured_url
from ..pipeline.eval import scenarios as scenario_files


def first_story_per_phone(directory: Path) -> list[dict[str, Any]]:
    """For each phone number, the first scenario (by file name) with an earlier call that settled something."""
    chosen: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        phone = scenario.get("customer_phone")
        calls = scenario.get("calls") or {}
        first = calls.get("call_1") or {}
        if not phone or phone in chosen or len(calls) < 2 or not first.get("facts_established"):
            continue
        chosen[phone] = scenario
    return list(chosen.values())


def session_of(scenario: Mapping[str, Any], *, today: str) -> dict[str, Any]:
    """``call_1`` as one ``seed_history`` entry: the slots the ledger knows, in their canonical form."""
    calls = scenario["calls"]
    first = calls["call_1"]
    later = next((spec for name, spec in calls.items() if name != "call_1"), {})
    facts: dict[str, Any] = {}
    for slot, value in (first.get("facts_established") or {}).items():
        if ontology.slot(slot) is None:
            continue  # e.g. "issue": not a memory slot; the summary still names the goal
        valid, canonical = ontology.coerce(slot, value)
        if valid:
            facts[slot] = canonical
    said = "; ".join(brief.spoken(slot, value) for slot, value in facts.items())
    goal = str(first.get("customer_goal") or "").strip().rstrip(".")
    summary = " ".join(part for part in (f"Khách hỏi: {goal}." if goal else "", f"Đã chốt: {said}." if said else "")
                       if part)
    days = int(later.get("days_later") or 1)
    return {
        "session_id": f"btc-{scenario['scenario_id']}-call_1",
        "date": (date.fromisoformat(today) - timedelta(days=days)).isoformat(),
        "channel": first.get("channel") or "hotline",
        "summary": summary or "Cuộc gọi trước theo kịch bản của BTC.",
        "outcome": str(first.get("expected_outcome") or "khac"),
        "facts": facts,
    }


def callbacks_of(scenario: Mapping[str, Any], conversations: Path) -> list[dict[str, Any]]:
    """The call-backs the assistant booked in ``call_1`` (``schedule.callback`` in the written-out conversation,
    ``<conversations>/scenarios_<id>/call_1.json``): what the sales team's "Hẹn gọi lại" lists for that customer."""
    path = conversations / f"scenarios_{scenario['scenario_id']}" / "call_1.json"
    if not path.exists():
        return []
    booked = []
    for turn in json.loads(path.read_text(encoding="utf-8")).get("turns") or []:
        for call in turn.get("tool_calls") or []:
            args = call.get("args") or {}
            if call.get("name") == "schedule.callback" and args.get("callback_at"):
                booked.append({"customer_phone": args.get("customer_phone") or scenario["customer_phone"],
                               "callback_at": args["callback_at"], "note": args.get("note")})
    return booked


async def book_callbacks(scenario: Mapping[str, Any], conversations: Path) -> int:
    """Book ``call_1``'s call-backs in the shared mock state, as the call did; keyed, so a second run books nothing."""
    from ..mcp.servers import btc

    booked = callbacks_of(scenario, conversations)
    for index, args in enumerate(booked):
        await btc.call("schedule.callback", btc.mock().schedule_callback,
                       idempotency_key=f"btc-{scenario['scenario_id']}-call_1-callback-{index}", **args)
    return len(booked)


async def seed_all(directory: Path, *, dry_run: bool, conversations: Path | None = None) -> int:
    from ..mcp import client as mcp_client
    from ..mcp.servers import btc
    from ..mcp.tools import ToolBox
    from ..pipeline.eval import runner

    conversations = conversations or directory.parent / "conversations"
    today = btc.reference_date()
    stories = first_story_per_phone(directory)
    print(f"{len(stories)} customers with an earlier call in {directory} (business day {today})")
    if dry_run:
        for scenario in stories:
            entry = session_of(scenario, today=today)
            callbacks = callbacks_of(scenario, conversations)
            print(f"  {scenario['scenario_id']}  {scenario.get('customer_name') or '?'}  ...{scenario['customer_phone'][-4:]}"
                  f"  {entry['date']}  {entry['summary'][:110]}"
                  + (f"  [+{len(callbacks)} hẹn gọi lại]" if callbacks else ""))
        return 0
    rig = type("SeedRig", (), {})()
    rig.writer = ToolBox(await mcp_client.tools_for("memory_writer"), timeout=10.0)
    written = failed = 0
    try:
        for scenario in stories:
            entry = session_of(scenario, today=today)
            channel = scenario_files.CHANNELS.get(str(entry["channel"]), "hotline")
            try:
                sessions = scenario_files.seed_sessions([entry], day=today, channel=channel)
                customer = await runner.seed(rig, sessions, customer_phone=scenario["customer_phone"],
                                             customer_name=scenario.get("customer_name"))
            except scenario_files.ScenarioError as error:
                failed += 1
                print(f"  skipped {scenario['scenario_id']}: {error}")
                continue
            written += 1
            callbacks = await book_callbacks(scenario, conversations)
            print(f"  {scenario['scenario_id']} -> {customer}: {len(entry['facts'])} facts, 1 episode"
                  + (f", {callbacks} call-back(s)" if callbacks else ""))
    finally:
        await mcp_client.close_all()
    print(f"written {written}, skipped {failed}")
    return 1 if failed and not written else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", type=Path, default=Path("data/dev/scenarios"))
    parser.add_argument("--conversations", type=Path, default=None,
                        help="The written-out calls (default: conversations/ beside --scenarios), for call_1's call-backs.")
    parser.add_argument("--dry-run", action="store_true", help="List what would be written; touch nothing.")
    parser.add_argument("--shop", action="store_true",
                        help="Also put the CRM's customers and their orders into the website's database.")
    args = parser.parse_args()
    url, _ = configured_url()
    if not args.dry_run:
        if not url:
            raise SystemExit("Set DATABASE_URL (or AGENT_DATABASE_URL) to the live database.")
        if url.rstrip("/").split("/")[-1].split("?")[0].endswith("_eval"):
            raise SystemExit("This is an evaluation database: every run empties it. Point it at the live one.")
    if args.shop and not args.dry_run:
        from ..mcp.servers import btc
        from . import shop_orders

        customers, orders = shop_orders.seed_crm_customers(btc.mock().CRM)
        print(f"website: {customers} CRM customers, {orders} CRM orders present")
    return asyncio.run(seed_all(args.scenarios, dry_run=args.dry_run, conversations=args.conversations))


if __name__ == "__main__":
    raise SystemExit(main())
