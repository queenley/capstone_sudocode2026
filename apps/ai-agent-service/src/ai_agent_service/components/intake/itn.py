"""Inverse text normalisation, and reading money back out of a reply.

``docs/design.md`` sections 4.1 and 4.5. Two directions, one module, so that
what the customer said and what the guardrail reads are counted the same way.

:func:`normalise`, spoken to written, for a turn on its way in:

- "bốn triệu tám" is 4.800.000, not 4.000.008; "hai trăm bốn chín k" is
  249.000; "một củ hai" is 1.200.000; "hai triệu rưỡi" is 2.500.000;
- a run of three or more bare digits is a digit string: "không chín tám bốn
  ..." is a phone number, 0984...;
- "ô đê" followed by a number is an order code: "ô đê ba trăm mười hai
  nghìn bốn trăm năm mươi sáu" is OD312456, not money (catalogue case D13);
- a time with its part of the day before or after it, and a day if one is
  said ("tối mai 8 giờ", "8 giờ tối mai", "chiều thứ bảy 3 giờ rưỡi"), gets
  the moment it means appended in ISO 8601 with +07:00, the form
  ``schedule.callback`` takes (G01); a day alone ("ngày mai", "thứ tư tuần
  sau") gets its date; "bảy giờ tối" gets 19:00 today. Always from the
  virtual clock, never the system clock, because the evaluator runs
  scenarios days apart.

The canonical value goes next to the words it came from, so the model reads
both (section 4.1, step 4); a number replaces its words.

:func:`money_spans`, written to value, for a reply on its way out: every
amount in 5.200.000đ, 5,2 triệu, 5 triệu 2, 4tr890, 249k form, with its value
in VND, so the guard can check each against the tools. :func:`amounts` reads
the same and the spoken forms too ("năm triệu hai trăm nghìn"), through the
same code the customer's words go through.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

from ..clock import day_label


class Span(NamedTuple):
    start: int
    end: int
    text: str
    value: int


# ── spoken numbers ────────────────────────────────────────────────────────

DIGITS = {
    "không": 0, "linh": 0, "lẻ": 0,
    "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "nhăm": 5,
    "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
SCALES = {"nghìn": 1_000, "ngàn": 1_000, "k": 1_000, "triệu": 1_000_000, "củ": 1_000_000, "tỷ": 1_000_000_000, "tỉ": 1_000_000_000}
NUMBER_WORDS = set(DIGITS) | set(SCALES) | {"mười", "mươi", "trăm", "rưỡi"}

#: Words that are digits only inside a number: "tư" and "năm" are also "fourth"
#: and "year", "một" is also "a". A run must hold something unambiguous.
WEAK = {"tư", "năm", "một", "ba", "lẻ", "linh", "không"}


def _below_thousand(words: list[str]) -> int | None:
    """A number under 1000 from its words, or None if they do not form one."""
    if not words:
        return 0
    value = 0
    rest = list(words)
    if "trăm" in rest:
        at = rest.index("trăm")
        head = rest[:at]
        if len(head) != 1 or head[0] not in DIGITS:
            return None
        value = DIGITS[head[0]] * 100
        rest = rest[at + 1:]
        if rest == ["rưỡi"]:
            return value + 50
        if len(rest) == 1 and rest[0] in DIGITS and rest[0] not in ("linh", "lẻ"):
            # "hai trăm tư" is 240 in speech.
            return value + DIGITS[rest[0]] * 10
        if len(rest) == 2 and rest[0] in ("linh", "lẻ") and rest[1] in DIGITS:
            return value + DIGITS[rest[1]]
    if not rest:
        return value
    if rest[0] == "mười":
        units = rest[1:]
        if not units:
            return value + 10
        if len(units) == 1 and units[0] in DIGITS:
            return value + 10 + DIGITS[units[0]]
        return None
    if len(rest) >= 2 and rest[1] == "mươi" and rest[0] in DIGITS:
        tens = DIGITS[rest[0]] * 10
        units = rest[2:]
        if not units:
            return value + tens
        if len(units) == 1 and units[0] in DIGITS:
            return value + tens + DIGITS[units[0]]
        return None
    if len(rest) == 2 and all(w in DIGITS for w in rest):
        # "hai lăm" is 25, "bốn chín" 49.
        return value + DIGITS[rest[0]] * 10 + DIGITS[rest[1]]
    if len(rest) == 1 and rest[0] in DIGITS:
        return value + DIGITS[rest[0]]
    return None


def parse_number(words: list[str]) -> int | None:
    """A spoken number with scales: "bốn triệu tám" -> 4_800_000."""
    total = 0
    group: list[str] = []
    last_scale: int | None = None
    for word in words:
        if word in SCALES:
            scale = SCALES[word]
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += (chunk or (1 if not group else 0)) * scale
            group = []
            last_scale = scale
        elif word == "rưỡi" and last_scale and not group:
            total += last_scale // 2
        else:
            group.append(word)
    if group:
        if last_scale and len(group) == 1 and group[0] in DIGITS:
            # A lone digit after a scale is that digit of the next place down:
            # "bốn triệu tám" is 4.8 million, "một củ hai" 1.2 million.
            total += DIGITS[group[0]] * last_scale // 10
        elif last_scale and "trăm" in group:
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += chunk * (last_scale // 1000 if last_scale >= 1000 else 1)
        else:
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += chunk
    return total


def _written(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _bare(token: str) -> str:
    return token.lower().strip(".,!?;:")


#: Words after which a weak number word ("ba", "năm") is a count, not a word.
UNITS = {"giờ", "h", "phút", "tháng", "tuổi", "ngày", "tuần", "mét", "m2", "m²", "người", "cái", "chiếc", "đôi",
         "size", "lần"}


def _runs(tokens: list[str]) -> list[tuple[int, int]]:
    """Index ranges of maximal runs of number words; "thứ hai" is a weekday, not a two."""
    runs, start = [], None
    for i, token in enumerate(tokens + [""]):
        weekday = start is None and i > 0 and _bare(tokens[i - 1]) == "thứ"
        if token and _bare(token) in NUMBER_WORDS and not weekday:
            start = i if start is None else start
            if token[-1] in ".,!?;:":
                # Punctuation closes the run after this word.
                runs.append((start, i + 1))
                start = None
        elif start is not None:
            runs.append((start, i))
            start = None
    return runs


def _spoken_numbers(text: str) -> str:
    tokens = text.split(" ")
    out: list[str] = []
    cursor = 0
    for start, end in _runs(tokens):
        words = [_bare(t) for t in tokens[start:end]]
        bare = all(w in DIGITS for w in words)
        # "không năm triệu" is a negation before a number, not a zero.
        while len(words) > 1 and words[0] == "không" and not bare:
            start += 1
            words = words[1:]
        has_digit = any(w in DIGITS or w == "mười" for w in words)
        unit_follows = end < len(tokens) and _bare(tokens[end]) in UNITS
        if not has_digit or (all(w in WEAK for w in words) and len(words) < 3 and not unit_follows):
            continue
        code = start >= 2 and [_bare(t) for t in tokens[start - 2:start]] in (["ô", "đê"], ["o", "đê"], ["ô", "đe"])
        out.extend(tokens[cursor:start - 2 if code else start])
        trailing = tokens[end - 1][len(tokens[end - 1].rstrip(".,!?;:")):]
        if bare and len(words) >= 3:
            out.append(("OD" if code else "") + "".join(str(DIGITS[w]) for w in words) + trailing)
        else:
            value = parse_number(words)
            if value is None:
                out.extend(tokens[start - 2 if code else start:end])
            elif code:
                out.append(f"OD{value}{trailing}")
            else:
                money = any(w in SCALES for w in words)
                out.append((format_vnd(value) if money else str(value)) + trailing)
        cursor = end
    out.extend(tokens[cursor:])
    return " ".join(out)


# ── dates and times ───────────────────────────────────────────────────────

WEEKDAYS = {"thứ hai": 0, "thứ ba": 1, "thứ tư": 2, "thứ năm": 3, "thứ sáu": 4, "thứ bảy": 5, "chủ nhật": 6}
RELATIVE_DAYS = {"hôm nay": 0, "nay": 0, "ngày mai": 1, "mai": 1, "ngày kia": 2, "ngày mốt": 2, "mốt": 2}
_DAY = r"thứ hai|thứ ba|thứ tư|thứ năm|thứ sáu|thứ bảy|chủ nhật|hôm nay|ngày mai|ngày kia|ngày mốt"
_PART = r"sáng|trưa|chiều|tối|đêm"
_WEEK = r"(?:\s+tuần\s+(?:sau|tới|này))"
DATE_PHRASE = re.compile(rf"\b({_DAY})({_WEEK})?\b", re.IGNORECASE)
#: A time with its part of the day and day on either side: "tối mai 8 giờ",
#: "8 giờ tối mai", "chiều thứ bảy 3 giờ rưỡi", "tối nay lúc 8h30".
MOMENT = re.compile(
    rf"(?:\b(?P<part1>{_PART})\s+)?(?:\b(?P<day1>{_DAY}|mai|nay|mốt)(?P<week1>{_WEEK})?\s+)?(?:lúc\s+)?"
    rf"\b(?P<hour>\d{{1,2}})\s*(?:giờ|h)(?:\s*(?P<minute>\d{{1,2}}|rưỡi)\b)?"
    rf"(?:\s+(?P<part2>{_PART})\b)?(?:\s+(?P<day2>{_DAY}|mai|nay|mốt)\b(?P<week2>{_WEEK})?)?",
    re.IGNORECASE,
)
def _day(phrase: str, week: str | None, today: date) -> date:
    """The day a day phrase means, counted from *today*."""
    lower = phrase.lower()
    if lower in RELATIVE_DAYS:
        return today + timedelta(days=RELATIVE_DAYS[lower])
    weekday = WEEKDAYS[lower]
    if week and week.split()[-1] in ("sau", "tới"):
        return today + timedelta(days=7 - today.weekday() + weekday)
    if week and week.split()[-1] == "này":
        return today + timedelta(days=weekday - today.weekday())
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _clock(hour: int, minute: str | None, part: str | None) -> tuple[int, int] | None:
    """24-hour time from what was said: "3 giờ rưỡi chiều" is 15:30."""
    minutes = 30 if (minute or "").lower() == "rưỡi" else int(minute or 0)
    part = (part or "").lower()
    if part in ("chiều", "tối") and hour < 12:
        hour += 12
    elif part == "đêm" and 6 <= hour < 12:
        hour += 12
    elif part == "trưa" and hour < 6:
        hour += 12
    if hour > 23 or minutes > 59:
        return None
    return hour, minutes


def _moments(text: str, now: datetime) -> tuple[str, list[tuple[int, int]]]:
    """Each time said, with the moment it means appended; and the spans consumed, for :func:`_dates`."""
    today = now.date()
    spans: list[tuple[int, int]] = []

    def replace(match: re.Match[str]) -> str:
        clock = _clock(int(match.group("hour")), match.group("minute"), match.group("part1") or match.group("part2"))
        if clock is None:
            return match.group(0)
        phrase, week = (match.group("day1"), match.group("week1")) if match.group("day1") else (
            match.group("day2"), match.group("week2"))
        day = _day(phrase, week, today) if phrase else today
        moment = datetime.combine(day, time(*clock), tzinfo=now.tzinfo)
        spans.append(match.span())
        return f"{match.group(0)} ({moment.isoformat(timespec='minutes')})"

    return MOMENT.sub(replace, text), spans


def _dates(text: str, now: datetime) -> str:
    """A day said without a time gets its date; one inside a moment already has it."""
    today = now.date()

    def replace(match: re.Match[str]) -> str:
        after = text[match.end():match.end() + 40]
        if re.match(r"[^()]*\(\d{4}-\d{2}-\d{2}T", after):
            return match.group(0)
        return f"{match.group(0)} ({day_label(_day(match.group(1), match.group(2), today))})"

    return DATE_PHRASE.sub(replace, text)


def normalise(text: str, now: datetime) -> str:
    """Money, phone numbers, order codes, dates and times in *text*, spoken form to written."""
    written = _spoken_numbers(text)
    written, _ = _moments(written, now)
    return _dates(written, now)


def amounts(text: str) -> list[int]:
    """Every amount of money in *text*, written or spoken, in VND: what the guard checks."""
    return [span.value for span in money_spans(_spoken_numbers(text))]


# ── written money, read back ──────────────────────────────────────────────

_MILLION = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(triệu|tr|củ)(?![a-zà-ỹ])(?:\s*(\d{1,3})(?![\d.,]\d))?", re.IGNORECASE)
_BILLION = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(tỷ|tỉ)(?![a-zà-ỹ])", re.IGNORECASE)
_THOUSAND = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(k|nghìn|ngàn)(?![a-zà-ỹ])", re.IGNORECASE)
_GROUPED = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+)(?:\s*(đồng|đ|vnđ|vnd|d)(?![a-zà-ỹ]))?", re.IGNORECASE)
_PLAIN = re.compile(r"(?<![\w.,])(\d{4,9})\s*(đồng|đ|vnđ|vnd)(?![a-zà-ỹ])", re.IGNORECASE)


def _decimal(raw: str) -> float:
    return float(raw.replace(",", "."))


def money_spans(text: str) -> list[Span]:
    """Every amount of money written in *text*, in VND, without overlaps."""
    found: list[Span] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s.start or start >= s.end for s in found)

    for match in _BILLION.finditer(text):
        found.append(Span(match.start(), match.end(), match.group(0), int(round(_decimal(match.group(1)) * 1_000_000_000))))
    for match in _MILLION.finditer(text):
        if not free(match.start(), match.end()):
            continue
        value = _decimal(match.group(1)) * 1_000_000
        tail = match.group(3)
        if tail and "." not in match.group(1) and "," not in match.group(1):
            value += int(tail) * 10 ** (6 - len(tail))
        found.append(Span(match.start(), match.end(), match.group(0), int(round(value))))
    for match in _THOUSAND.finditer(text):
        if free(match.start(), match.end()):
            found.append(Span(match.start(), match.end(), match.group(0), int(round(_decimal(match.group(1)) * 1_000))))
    for match in _GROUPED.finditer(text):
        if free(match.start(), match.end()):
            digits = re.sub(r"[.,]", "", match.group(1))
            value = int(digits)
            # 1.000 on its own is a thousand; a grouped number under 1.000 dong
            # is not money anyone quotes.
            if value >= 1_000:
                found.append(Span(match.start(), match.end(), match.group(0), value))
    for match in _PLAIN.finditer(text):
        if free(match.start(), match.end()):
            found.append(Span(match.start(), match.end(), match.group(0), int(match.group(1))))
    return sorted(found)


def format_vnd(value: int) -> str:
    """``5.200.000đ``, as the advisor writes a price."""
    return f"{_written(int(value))}đ"
