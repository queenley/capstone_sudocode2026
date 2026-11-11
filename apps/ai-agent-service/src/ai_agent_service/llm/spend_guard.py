"""A hard stop on model spend, read from the real traces.

Three parts, so a run that overspends or outlives the person watching it stops by itself:

- **the switch**: before any model call (every chat model the factory makes, and every Decisions request) the
  process looks for the stop file; while it exists every call fails with :class:`SpendStopped`, no request is sent;
- **the reading**: what was really spent since a moment, from Langfuse's Metrics API (v2, its real-time read path),
  which prices each call by its model definition, cached input at the cached rate; plus a fixed offset for spend
  made before tracing covered it;
- **the watchdog**: polls that reading beside a paid run; at the limit, or past its deadline, it writes the stop
  file and ends the run's process group::

      python -m ai_agent_service.llm.spend_guard status            # exit 3 when stopped or at the limit
      python -m ai_agent_service.llm.spend_guard watch --pgid <pid> --deadline-minutes 60
      python -m ai_agent_service.llm.spend_guard resume            # remove the stop file (a person decides)

Settings come from the environment: ``SPEND_LIMIT_USD`` (default 3), ``SPEND_SINCE`` (ISO time the budget started),
``SPEND_OFFSET_USD`` (spend before tracing, default 0), ``SPEND_STOP_FILE``.

It guards runs an assistant (Claude Code) starts on its own, and only those: it is on when ``SPEND_SINCE`` is set,
which only such a run sets. A person running the agent, an evaluation or an improvement round is never stopped by it
(the user's rule, 2026-11-10).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
from langchain_core.callbacks import BaseCallbackHandler

from ..config.config_manager import ROOT

DEFAULT_STOP_FILE = ROOT.parents[1] / "evaluation" / "runs" / "SPEND_STOP"


class SpendStopped(RuntimeError):
    """The spend limit was reached or a run outlived its deadline: no model call goes out."""


def stop_file() -> Path:
    return Path(os.environ.get("SPEND_STOP_FILE") or DEFAULT_STOP_FILE)


def active() -> bool:
    """Whether this process is a run the guard watches: ``SPEND_SINCE`` is set."""
    return bool(os.environ.get("SPEND_SINCE"))


def check() -> None:
    """Raise :class:`SpendStopped` when the guard is on and the stop file exists."""
    if not active():
        return
    path = stop_file()
    if path.exists():
        raise SpendStopped(f"Model calls are stopped: {path.read_text(encoding='utf-8').strip() or path}")


class StopSwitch(BaseCallbackHandler):
    """Checks the stop file before each chat model call; ``raise_error`` makes LangChain end the call with it."""

    raise_error = True

    def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, **kwargs: Any) -> None:
        check()

    def on_llm_start(self, serialized: dict[str, Any], prompts: Any, **kwargs: Any) -> None:
        check()


def limit() -> float:
    """The hard stop: at it every model call is refused and every watched run ended."""
    return float(os.environ.get("SPEND_LIMIT_USD") or 3.0)


def soft_limit() -> float:
    """The planned ceiling: at it no new paid round may start, while one already running may finish under the hard
    stop."""
    return float(os.environ.get("SPEND_SOFT_LIMIT_USD") or 2.0)


def reading(start: str | None = None) -> dict[str, float]:
    """The spend, split: what Langfuse priced from the traces, and the fixed offset for spend before tracing."""
    traced = spent(start) - float(os.environ.get("SPEND_OFFSET_USD") or 0)
    return {"traced": round(traced, 4), "offset": float(os.environ.get("SPEND_OFFSET_USD") or 0),
            "total": round(traced + float(os.environ.get("SPEND_OFFSET_USD") or 0), 4)}


def may_start() -> None:
    """Raise :class:`SpendStopped` when a new paid round must not start: stopped, or at the planned ceiling."""
    check()
    used = spent()
    if used >= soft_limit():
        raise SpendStopped(f"spend {used} USD reached the planned ceiling of {soft_limit()} USD: no new round")


def since() -> str:
    value = os.environ.get("SPEND_SINCE")
    if not value:
        raise SystemExit("Set SPEND_SINCE to the ISO time the budget started")
    return value


def spent(start: str | None = None) -> float:
    """USD spent since *start* by every traced model call, as Langfuse priced it, plus ``SPEND_OFFSET_USD``."""
    base = (os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "").rstrip("/")
    key, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (base and key and secret):
        raise SystemExit("Langfuse keys are not set: the real spend cannot be read")
    _receiving(base, (key, secret))
    query = {"view": "observations", "metrics": [{"measure": "totalCost", "aggregation": "sum"}], "dimensions": [],
             "filters": [], "fromTimestamp": start or since(),
             "toTimestamp": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    response = httpx.get(f"{base}/api/public/v2/metrics", params={"query": json.dumps(query)}, auth=(key, secret),
                         timeout=30)
    if response.status_code == 429:
        traced = _observations(base, (key, secret), start or since())
    else:
        response.raise_for_status()
        rows = response.json().get("data") or []
        traced = sum(float(row.get("sum_totalCost") or 0) for row in rows)
    return round(traced + float(os.environ.get("SPEND_OFFSET_USD") or 0), 4)


class SpendUnreadable(httpx.HTTPError):
    """Langfuse no longer records new calls: what it reports is no longer what was spent."""


def _receiving(base: str, auth: tuple[str, str]) -> None:
    """Raise :class:`SpendUnreadable` when Langfuse refuses new traces (its plan's usage threshold, 2026-11-10): a sum
    of the traces it kept would stand still while money is spent, and a limit read from it would never be reached."""
    response = httpx.post(f"{base}/api/public/ingestion", json={"batch": []}, auth=auth, timeout=30)
    if response.status_code == 403:
        raise SpendUnreadable(f"Langfuse refuses new traces: {response.text[:160]}")


def _observations(base: str, auth: tuple[str, str], start: str) -> float:
    """The same sum from the observations themselves, read when the Metrics API's daily quota (100 reads) is spent:
    each generation carries the cost Langfuse priced for it, cached input at the cached rate."""
    total, cursor = 0.0, None
    while True:
        params: dict[str, Any] = {"fromStartTime": start, "type": "GENERATION", "fields": "core,usage", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        response = httpx.get(f"{base}/api/public/v2/observations", params=params, auth=auth, timeout=60)
        response.raise_for_status()
        body = response.json()
        total += sum(float(row.get("totalCost") or 0) for row in body.get("data") or [])
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor or not body.get("data"):
            return total


def stop(reason: str) -> None:
    path = stop_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{datetime.now(timezone.utc).isoformat()} {reason}\n", encoding="utf-8")


#: How long a watched run may go on while its spend cannot be read: past it the run is stopped, never left unwatched.
BLIND_SECONDS = 300.0


def watch(pgid: int | None, deadline_minutes: float, every: float = 120.0, blind: float = BLIND_SECONDS) -> int:
    """Poll the spend until the watched process group ends; at the limit, at the deadline, or when the spend has been
    unreadable for *blind* seconds, stop and end it."""
    deadline = time.monotonic() + deadline_minutes * 60
    last_read = time.monotonic()
    while True:
        reason = None
        try:
            used = spent()
            last_read = time.monotonic()
            if used >= limit():
                reason = f"spend {used} USD reached the limit of {limit()} USD"
        except (httpx.HTTPError, ValueError) as error:
            print(f"spend unreadable: {type(error).__name__}", flush=True)
            used = None
            if time.monotonic() - last_read >= blind:
                reason = f"the spend could not be read for {int(blind)} seconds"
        if reason is None and time.monotonic() >= deadline:
            reason = f"the run passed its deadline of {deadline_minutes} minutes"
        if reason:
            stop(reason)
            print(f"STOPPED: {reason}", flush=True)
            if pgid:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            return 3
        print(f"spent {used} USD of {limit()}", flush=True)
        if pgid:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return 0  # the run ended on its own
        time.sleep(every)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spend_guard")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Print the spend; exit 3 when stopped or at the limit")
    watching = commands.add_parser("watch", help="Watch a paid run and stop it at the limit or its deadline")
    watching.add_argument("--pgid", type=int, help="The run's process group, ended when it must stop")
    watching.add_argument("--deadline-minutes", type=float, required=True)
    commands.add_parser("resume", help="Remove the stop file")
    args = parser.parse_args(argv)
    if args.command == "resume":
        stop_file().unlink(missing_ok=True)
        print("Model calls may go out again.")
        return 0
    if args.command == "watch":
        return watch(args.pgid, args.deadline_minutes)
    try:
        split = reading()
    except SpendUnreadable as error:
        print(f"UNREADABLE: {error}; no paid run may start until the spend can be read again")
        return 3
    if stop_file().exists():
        print(f"STOPPED: {stop_file().read_text(encoding='utf-8').strip()}")
        return 3
    used = split["total"]
    print(f"spent {used} USD (Langfuse traces {split['traced']} + offset {split['offset']}) of {limit()} "
          f"(new rounds stop at {soft_limit()}) since {since()}")
    if used >= limit():
        stop(f"spend {used} USD reached the limit of {limit()} USD")
        return 3
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT.parents[1] / ".env", override=False)
    load_dotenv(ROOT / ".env", override=False)
    sys.exit(main())
