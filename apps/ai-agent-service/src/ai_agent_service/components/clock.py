"""The virtual clock, and the shop's working hours. ``docs/design.md`` Appendix A.

Business logic reads ``now`` from the state, never the system clock: the
evaluation runner sets it to the scenario's day, the API to the business day
the Admin page chose (by default the organisers' "today", 2026-10-15, the
day their catalogue, promotions and stock are written for). The time of day
of a call is fixed at 10:00, Vietnam time. Tools take the day as ``on``,
``YYYY-MM-DD``. Latency is measured on the real, monotonic clock, never this
one.

The working hours and holidays of ``thong-bao-lich-nghi.md`` (LN-01, LN-02)
are here too, because a callback, a delivery date and the Sunday rule all ask
the same question of the same table. The holidays are the organisers' mock's
(``eval/mock_tools.py`` ``HOLIDAYS``), so a time this module accepts is one the
mock will not move.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

VIETNAM = timezone(timedelta(hours=7))

#: Appendix A: the time of day every call is placed at, recorded in the manifest.
CALL_TIME = time(10, 0)

#: The organisers' reference date, the default business day.
REFERENCE_DAY = "2026-10-15"

#: LN-02: no calls and no deliveries on these days.
HOLIDAYS = frozenset({"2026-10-26", "2027-01-01"})

#: LN-01: the switchboard's hours by weekday (Monday is 0), closing exclusive
#: as in the mock: Monday to Saturday 08:00–21:00, Sunday 09:00–18:00.
HOURS: dict[int, tuple[time, time]] = {**{day: (time(8), time(21)) for day in range(6)}, 6: (time(9), time(18))}

#: The latest callback worth proposing is this long before closing.
LAST_SLOT = timedelta(minutes=30)

WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def at(day: str | date) -> datetime:
    """10:00 in Vietnam on *day*."""
    if isinstance(day, str):
        day = date.fromisoformat(day[:10])
    return datetime.combine(day, CALL_TIME, tzinfo=VIETNAM)


def on(now: datetime) -> str:
    """The ``on`` argument of a tool: the day of *now* in Vietnam."""
    return now.astimezone(VIETNAM).date().isoformat()


def day_label(value: str | date | datetime) -> str:
    """``15/10/2026``, as the advisor says a date."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        value = value.astimezone(VIETNAM).date()
    return value.strftime("%d/%m/%Y")


def moment_label(moment: datetime) -> str:
    """``20:00 thứ Sáu 16/10/2026``: a time the way it is said to a customer."""
    local = moment.astimezone(VIETNAM)
    return f"{local:%H:%M} {WEEKDAYS[local.weekday()]} {day_label(local)}"


def parse_local(value: object) -> datetime | None:
    """An ISO 8601 date and time in Vietnam time, or None when *value* is not one.

    A value without an offset is read as Vietnam time, which is what a
    customer means; one with another offset is converted, so the comparison
    with working hours is always made on the shop's clock.
    """
    if not isinstance(value, str) or "T" not in value and " " not in value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=VIETNAM)
    return moment.astimezone(VIETNAM)


def iso_local(moment: datetime) -> str:
    """``2026-10-16T20:00+07:00``: minutes, Vietnam offset, as tools take a time."""
    return moment.astimezone(VIETNAM).isoformat(timespec="minutes")


def is_holiday(day: date) -> bool:
    return day.isoformat() in HOLIDAYS


def is_working_time(moment: datetime) -> bool:
    """Whether the switchboard is open at *moment* (LN-01, LN-02)."""
    local = moment.astimezone(VIETNAM)
    if is_holiday(local.date()):
        return False
    opening, closing = HOURS[local.weekday()]
    return opening <= local.time() < closing


def nearest_working_time(moment: datetime, *, not_before: datetime | None = None) -> datetime:
    """The working time closest to *moment* that is not before *not_before*.

    A holiday moves to the same time on the next working day, which is what
    LN-02 says happens to a callback booked on 26/10; any other time outside
    the hours moves to the nearer of the day's last slot and the next
    opening (LN-01, "đề xuất khung gần nhất trong giờ làm việc").
    """
    local = moment.astimezone(VIETNAM)
    floor = not_before.astimezone(VIETNAM) if not_before else None
    if is_working_time(local) and (floor is None or local >= floor):
        return local
    if is_holiday(local.date()):
        day = local.date() + timedelta(days=1)
        while is_holiday(day):
            day += timedelta(days=1)
        opening, closing = HOURS[day.weekday()]
        wanted = min(max(local.time(), opening), (datetime.combine(day, closing) - LAST_SLOT).time())
        return _not_before(datetime.combine(day, wanted, tzinfo=VIETNAM), floor)
    candidates = [c for c in (_previous_slot(local), _next_opening(local)) if c is not None]
    best = min(candidates, key=lambda c: (abs((c - local).total_seconds()), -c.timestamp()))
    return _not_before(best, floor)


def _previous_slot(local: datetime) -> datetime | None:
    """The last proposable slot at or before *local* on its own day, if that day works."""
    if is_holiday(local.date()):
        return None
    opening, closing = HOURS[local.weekday()]
    last = datetime.combine(local.date(), closing, tzinfo=VIETNAM) - LAST_SLOT
    first = datetime.combine(local.date(), opening, tzinfo=VIETNAM)
    return last if local >= last and last >= first else None


def _next_opening(local: datetime) -> datetime:
    """The next opening time after *local*, skipping holidays."""
    day = local.date()
    opening = datetime.combine(day, HOURS[day.weekday()][0], tzinfo=VIETNAM)
    if local < opening and not is_holiday(day):
        return opening
    day += timedelta(days=1)
    while is_holiday(day):
        day += timedelta(days=1)
    return datetime.combine(day, HOURS[day.weekday()][0], tzinfo=VIETNAM)


def _not_before(candidate: datetime, floor: datetime | None) -> datetime:
    """*candidate*, or the first working time after *floor* when it would be in the past."""
    if floor is None or candidate >= floor:
        return candidate
    if is_working_time(floor):
        return floor
    return _next_opening(floor)
