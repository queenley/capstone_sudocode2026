"""The call-backs the agent books, on the shop's Google Calendar too.

``schedule.callback`` books a call back in the organisers' mock (``mcp/servers/btc.py``): the guardrails, the grader
and the sales console's "Hẹn gọi lại" page read it there, so it stays the record. A consultant, though, plans the day
in a calendar. With this module on, each call-back the agent books is also an event on one shared calendar, at the
booked time (after any move off a holiday).

**Notifications.** Google keeps reminders per user, so who is reminded depends on how the calendar is followed:

* a consultant who follows the shared calendar sets its notifications in their own Google Calendar settings (the
  event's reminders do not reach them);
* ``GOOGLE_CALENDAR_ATTENDEES`` invites consultants: Google e-mails them the invitation and reminds them with
  ``GOOGLE_CALENDAR_REMINDERS`` (``popup:10,email:60``). A service account may invite only on Google Workspace,
  acting as a user of the domain (``GOOGLE_CALENDAR_SUBJECT``, domain-wide delegation).

**On** when ``GOOGLE_CALENDAR_ID`` names the calendar and a service account's key is given, as a file
(``GOOGLE_CALENDAR_CREDENTIALS``) or inline (``GOOGLE_CALENDAR_CREDENTIALS_JSON``, for a Kubernetes secret), and the
database is not an evaluation one: an evaluation run never writes to a real calendar. The calendar is shared with
the service account's e-mail, with "Make changes to events".

**What it sends.** The customer's name when the number belongs to one CRM customer (as the console shows it), the
last four digits of the number, the agent's note and a link to the console. Never the whole number: staff read it
in the console, which is behind the staff login.

**Never in the way.** The event is created in a background thread after the tool has answered, so the call's
2-second budget is untouched, and a calendar that cannot be reached is a warning in the log, never a failed
call-back. The event's id is derived from the call-back's id, so a write replayed under its idempotency key (which
returns the first call-back) finds its event already there (HTTP 409) instead of making a second one.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import os
from datetime import timedelta
from typing import Any, Mapping
from urllib.parse import quote

from ..components import clock

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/calendar/v3"
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
#: How long an event lasts when GOOGLE_CALENDAR_SLOT_MINUTES does not say.
SLOT_MINUTES = 15
#: The reminders when GOOGLE_CALENDAR_REMINDERS does not say: a popup 10 minutes before.
REMINDERS = "popup:10"
#: Google's limits on an event's reminder overrides.
MAX_REMINDERS = 5
MAX_REMINDER_MINUTES = 40320
TIMEOUT_SECONDS = 10.0

#: Background tasks still running, kept so they are not collected half-way.
_pending: set[asyncio.Task[Any]] = set()


def enabled() -> bool:
    """On when a calendar and a key are configured, and the database is not an evaluation one."""
    if not os.environ.get("GOOGLE_CALENDAR_ID", "").strip():
        return False
    if not (os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "").strip()
            or os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON", "").strip()):
        return False
    name = os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].split("?", 1)[0]
    return not name.endswith("_eval")


def event_id(calendar_id: str, callback_id: str) -> str:
    """A stable event id for one call-back: Google takes 5 to 1024 characters of base32hex (0-9, a-v), hex fits."""
    return hashlib.sha256(f"{calendar_id}\n{callback_id}".encode()).hexdigest()


def reminders(spec: str | None) -> list[dict[str, Any]]:
    """``"popup:10,email:60"`` as Google's reminder overrides; a malformed entry is dropped with a warning.

    Google keeps an event's reminders per user: these reach whoever the key acts as (the service account, or
    GOOGLE_CALENDAR_SUBJECT) and the attendees invited, never someone who only follows the calendar. Those set the
    calendar's own notifications in their settings."""
    found: list[dict[str, Any]] = []
    for item in (spec if spec is not None else REMINDERS).split(","):
        method, _, minutes = item.strip().partition(":")
        if not item.strip():
            continue
        if method not in ("popup", "email") or not minutes.strip().isdigit() \
                or int(minutes) > MAX_REMINDER_MINUTES:
            logger.warning("GOOGLE_CALENDAR_REMINDERS: %r is not popup:<minutes> or email:<minutes>; left out", item)
            continue
        found.append({"method": method, "minutes": int(minutes)})
    return found[:MAX_REMINDERS]


def attendees(spec: str | None) -> list[dict[str, str]]:
    """``"a@shop.vn, b@shop.vn"`` as the event's attendees: the consultants Google invites and reminds."""
    return [{"email": email.strip()} for email in (spec or "").split(",") if "@" in email]


def event_body(booked: Mapping[str, Any], *, customer_name: str | None, phone: str | None,
               calendar_id: str, console_url: str | None = None, slot_minutes: int = SLOT_MINUTES,
               reminder_spec: str | None = None, attendee_spec: str | None = None) -> dict[str, Any]:
    """The event for one booked call-back; pure, so it is tested without Google."""
    start = clock.parse_local(booked.get("callback_at"))
    if start is None:
        raise ValueError(f"A call-back without a readable time: {booked.get('callback_at')!r}")
    start = start.astimezone(clock.VIETNAM)
    end = start + timedelta(minutes=slot_minutes)
    last4 = phone[-4:] if phone else None
    who = " ".join(part for part in (customer_name, f"(số đuôi {last4})" if last4 else None) if part) or "khách"
    lines = [f"Ghi chú: {booked['note']}" if booked.get("note") else None,
             f"Khách hẹn lúc {clock.moment_label(clock.parse_local(booked['moved_from']))}, đã dời vì ngoài giờ "
             "làm việc hoặc ngày nghỉ." if clock.parse_local(booked.get("moved_from")) else None,
             f"Mã lịch: {booked.get('callback_id')}" if booked.get("callback_id") else None,
             f"Xem số điện thoại và cuộc gọi: {console_url}" if console_url else None]
    return {
        "id": event_id(calendar_id, str(booked.get("callback_id") or booked.get("callback_at"))),
        "summary": f"Gọi lại {who}",
        "description": "\n".join(line for line in lines if line),
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Ho_Chi_Minh"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Ho_Chi_Minh"},
        "reminders": {"useDefault": False, "overrides": reminders(reminder_spec)},
        **({"attendees": invited} if (invited := attendees(attendee_spec)) else {}),
        "extendedProperties": {"private": {"callback_id": str(booked.get("callback_id") or "")}},
    }


@functools.lru_cache(maxsize=1)
def _credentials() -> Any:
    from google.oauth2 import service_account

    inline = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON", "").strip()
    if inline:
        credentials = service_account.Credentials.from_service_account_info(json.loads(inline), scopes=SCOPES)
    else:
        credentials = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_CALENDAR_CREDENTIALS"].strip(), scopes=SCOPES)
    # Google Workspace only: act as this user (domain-wide delegation), which a service account needs to invite.
    subject = os.environ.get("GOOGLE_CALENDAR_SUBJECT", "").strip()
    return credentials.with_subject(subject) if subject else credentials


def _token() -> str:
    from google.auth.transport.requests import Request

    credentials = _credentials()
    if not credentials.valid:
        credentials.refresh(Request())
    return str(credentials.token)


def warm() -> None:
    """Read the key and fetch a token when an MCP server starts, so a broken key shows in the log at once."""
    if not enabled():
        return
    try:
        _token()
    except Exception as error:  # noqa: BLE001 - the server starts without the calendar
        logger.warning("Google Calendar not reachable at start: %s", error)


def _console_url() -> str | None:
    base = (os.environ.get("CALLBACKS_CONSOLE_URL") or "").strip()
    if base:
        return base
    shop = (os.environ.get("SHOP_PUBLIC_URL") or "").strip().rstrip("/")
    return f"{shop}/ban-hang/hen-goi-lai" if shop else None


def add_callback(booked: Mapping[str, Any], *, customer_phone: str | None) -> dict[str, Any] | None:
    """Put one booked call-back on the calendar; the event's id and link, or None. Synchronous; never raises."""
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
    try:
        import httpx

        from ..mcp.servers import btc

        crm = btc.mock().crm_get_customer(phone=customer_phone) if customer_phone else {"found": False}
        name = crm.get("name") if crm.get("found") and not crm.get("ambiguous") else None
        body = event_body(booked, customer_name=name, phone=customer_phone, calendar_id=calendar_id,
                          console_url=_console_url(),
                          slot_minutes=int(os.environ.get("GOOGLE_CALENDAR_SLOT_MINUTES") or SLOT_MINUTES),
                          reminder_spec=os.environ.get("GOOGLE_CALENDAR_REMINDERS"),
                          attendee_spec=os.environ.get("GOOGLE_CALENDAR_ATTENDEES"))
        # Invited consultants get Google's e-mail; nobody else is told.
        params = {"sendUpdates": "all" if body.get("attendees") else "none"}
        response = httpx.post(f"{API}/calendars/{quote(calendar_id, safe='')}/events", json=body, params=params,
                              headers={"Authorization": f"Bearer {_token()}"}, timeout=TIMEOUT_SECONDS)
        if response.status_code == 409:
            logger.info("Call-back %s already on the calendar", booked.get("callback_id"))
            return {"event_id": body["id"], "html_link": None}
        if response.status_code == 403 and "forbiddenForServiceAccounts" in response.text:
            raise RuntimeError("a service account may invite attendees only when it acts as a Google Workspace "
                               "user: set GOOGLE_CALENDAR_SUBJECT (domain-wide delegation), or empty "
                               "GOOGLE_CALENDAR_ATTENDEES")
        response.raise_for_status()
        event = response.json()
        logger.info("Call-back %s on the calendar as %s", booked.get("callback_id"), event.get("id"))
        return {"event_id": event.get("id"), "html_link": event.get("htmlLink")}
    except Exception as error:  # noqa: BLE001 - the call-back stands in the mock whatever the calendar says
        logger.warning("Call-back %s not put on Google Calendar: %s", booked.get("callback_id"), error)
        return None


def add_callback_later(booked: Mapping[str, Any], *, customer_phone: str | None) -> None:
    """:func:`add_callback` in a worker thread, after the tool has answered; nothing when the module is off."""
    if not enabled() or not isinstance(booked, Mapping) or not booked.get("callback_at"):
        return
    task = asyncio.get_running_loop().create_task(
        asyncio.to_thread(add_callback, dict(booked), customer_phone=customer_phone))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
