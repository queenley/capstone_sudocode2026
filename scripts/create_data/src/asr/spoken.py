"""Written Vietnamese -> spoken form, in the style of BTC ``asr/ground_truth.json``.

BTC ground truth writes numbers as they are spoken ("năm triệu hai trăm nghìn",
"hai mươi lăm mét vuông", "ô đê năm trăm hai mươi mốt nghìn…"). We feed TTS this
spoken text, so the same string is both the audio content and the WER reference.
"""
from __future__ import annotations

import re

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
LETTERS = {"a": "a", "b": "bê", "c": "xê", "d": "đê", "đ": "đê", "e": "e", "f": "ép", "g": "giê", "h": "hát",
           "i": "i", "j": "gi", "k": "ca", "l": "e lờ", "m": "em mờ", "n": "en nờ", "o": "ô", "p": "pê", "q": "quy",
           "r": "e rờ", "s": "ét", "t": "tê", "u": "u", "v": "vê", "w": "vê kép", "x": "ích", "y": "i dài", "z": "dét"}
SCALES = ["", "nghìn", "triệu", "tỷ"]
#: Units read after a number ("4.5L", "1,2m", "3.000mAh").
UNITS = {"l": "lít", "ml": "mi li lít", "kg": "ki lô gam", "g": "gam", "cm": "xen ti mét", "mm": "mi li mét",
         "m": "mét", "w": "oát", "mah": "mi li am pe giờ"}
#: Acronyms said as words rather than letter by letter (BTC's ground truth writes COD as "cê ô đê").
ACRONYMS = {"COD": "cê ô đê", "RO": "rô", "OK": "ô kê", "HCM": "hồ chí minh"}


def _three(n: int, full: bool) -> str:
    """0..999; ``full`` = this group is preceded by a higher group (needs 'không trăm' / 'linh')."""
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    words = []
    if hundreds or full:
        words += [DIGITS[hundreds], "trăm"]
    if tens == 0:
        if ones:
            if hundreds or full:
                words.append("linh")
            words.append(DIGITS[ones])
    elif tens == 1:
        words.append("mười")
        if ones:
            words.append("lăm" if ones == 5 else DIGITS[ones])
    else:
        words += [DIGITS[tens], "mươi"]
        if ones:
            words.append({1: "mốt", 5: "lăm"}.get(ones, DIGITS[ones]))
    return " ".join(words)


def number_words(n: int) -> str:
    """4890000 -> 'bốn triệu tám trăm chín mươi nghìn'."""
    if n == 0:
        return "không"
    if n < 0:
        return "âm " + number_words(-n)
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        words.append(_three(g, full=i < len(groups) - 1))
        if SCALES[i % 4] or i >= 4:
            words.append(SCALES[i % 4] if i < 4 else "tỷ")
    return " ".join(w for w in words if w)


def _money(match: re.Match) -> str:
    return number_words(int(re.sub(r"\D", "", match.group(1))))


def _decimal_unit(match: re.Match) -> str:
    whole, frac, unit = match.group(1), match.group(2), match.group(3).lower()
    base = 1_000_000 if unit in ("triệu", "tr") else 1_000
    value = int(whole) * base + int((frac + "000")[:3]) * (base // 1000)
    return number_words(value)


def _date(match: re.Match) -> str:
    day, month, year = match.group(1), match.group(2), match.group(3)
    text = f"{number_words(int(day))} tháng {number_words(int(month))}"
    return text + (f" năm {number_words(int(year))}" if year else "")


def _code(match: re.Match) -> str:
    """OD600001 / SKU-AP-X -> letters spelled, digit runs read as numbers."""
    parts = []
    for token in re.findall(r"[A-Za-zĐđ]+|\d+", match.group(0)):
        if token.isdigit():
            parts.append(number_words(int(token)))
        else:
            parts.append(" ".join(LETTERS.get(ch.lower(), ch.lower()) for ch in token))
    return " ".join(parts)


def _number(raw: str) -> str:
    """'3.000' -> three thousand; '4.5' / '1,2' -> 'bốn phẩy năm' / 'một phẩy hai'."""
    if re.fullmatch(r"\d+|\d{1,3}(?:[.,]\d{3})+", raw):
        return number_words(int(re.sub(r"\D", "", raw)))
    whole, frac = re.split(r"[.,]", raw, maxsplit=1)
    return f"{number_words(int(whole))} phẩy {number_words(int(frac))}"


def _digits(match: re.Match) -> str:
    """Phone, ID card and account numbers, one digit at a time (BTC: "không chín một bảy...")."""
    return " ".join(DIGITS[int(d)] for d in match.group(0))


def to_spoken(text: str) -> str:
    """Rewrite digits, money, dates, units and codes as spoken Vietnamese (lowercase)."""
    t = re.sub(r"\bTP\.?\s*HCM\b", "thành phố hồ chí minh", text)
    t = re.sub(r"\bTP\.\s*|\bTP\s+(?=[A-ZĐÀ-Ỹ])", "thành phố ", t)  # "TP. Huế", "TP Huế"
    t = re.sub(r"(\d)([A-Za-zÀ-ỹ])", r"\1 \2", t)  # "4.5L", "3.000mAh": a number, then its unit
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", _date, t)
    t = re.sub(r"\b0\d{8,}\b|\b\d{9,}\b", _digits, t)
    t = re.sub(r"(\d+)[.,](\d{1,3})\s*(triệu|tr|nghìn|ngàn)\b", _decimal_unit, t, flags=re.IGNORECASE)
    t = re.sub(r"(\d+)\s*k\b", lambda m: number_words(int(m.group(1)) * 1000), t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2)(?!\w)", lambda m: f"{_number(m.group(1))} mét vuông", t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b",
               lambda m: f"{_number(m.group(1))} {UNITS[m.group(2).lower()]}", t, flags=re.IGNORECASE)
    t = re.sub(r"(\d{1,3}(?:[.,]\d{3})+)\s*(?:đồng|vnđ|vnd|đ)?(?!\w)", _money, t, flags=re.IGNORECASE)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", lambda m: f"{_number(m.group(1))} phần trăm", t)
    t = re.sub(r"\b\d+[.,]\d+\b", lambda m: _number(m.group(0)), t)
    t = re.sub(r"\b[A-Z]{1,4}(?:-[A-Z0-9]+)+\b|\b[A-Z]{1,4}\d+\b", _code, t)
    t = re.sub(r"\b[A-Z]{2,5}\b", lambda m: ACRONYMS.get(m.group(0)) or _code(m), t)
    t = re.sub(r"(\d+)\s*(?:đồng|đ)\b", lambda m: number_words(int(m.group(1))), t)
    t = re.sub(r"\d+", lambda m: number_words(int(m.group(0))), t)
    return re.sub(r"\s+", " ", t).strip().lower()
