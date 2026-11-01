"""Deterministic ASR entity predictions. No reference labels or model provider are read."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from . import itn

EXTRACTOR_VERSION = 'asr-entities-v2'


def commerce(text: str) -> dict:
    """Existing data-generation rules, now usable by the runtime/evaluator without that package."""
    plain = itn.normalise(text.lower(), datetime(2026, 1, 1))
    found = {}
    money = r'(\d[\d.,]*)\s*(?:đ|đồng|vnđ|vnd)'
    for key, cue in [('budget_vnd', r'ngân sách[^.?!]*?'), ('competitor_price_vnd', r'(?:bên kia|chỗ khác|nơi khác|rẻ hơn)[^.?!]*?'),
                     ('price_vnd', r'giá[^.?!]*?')]:
        match = re.search(cue + money, plain)
        if match:
            found[key] = int(re.sub(r'[.,]', '', match.group(1)))
    area = re.search(r'(\d+)\s*(?:mét vuông|m2|m²)', plain)
    if area:
        found['room_area_m2'] = int(area.group(1))
    if re.search(r'không (?:có )?(?:trẻ|con nhỏ|em bé|bé)', plain):
        found['has_children'] = False
    elif re.search(r'(?:có|nhà có) (?:trẻ|con nhỏ|em bé|bé)', plain):
        found['has_children'] = True
    if re.search(r'\bcod\b|thu hộ|nhận hàng.*trả tiền', plain):
        found['payment'] = 'COD'
    elif re.search(r'chuyển khoản|banking', plain):
        found['payment'] = 'bank'
    return found


# Freeze this vocabulary independently of any reference/hypothesis pair. Only explicit units are interpreted.
WORDS = sorted(itn.NUMBER_WORDS - {'k', 'củ', 'rưỡi', 'linh', 'lẻ'}, key=len, reverse=True)
WORD = '(?:' + '|'.join(WORDS) + ')'
NUMBER = rf'(?:\d+(?:[.,]\d+)?|{WORD})(?:\s+(?:{WORD}|phẩy))*'
UNITS = {'percent': r'phần\s+trăm|%', 'age_months': r'tháng\s+tuổi', 'age_years': r'tuổi',
         'mass_mg': r'miligam|miligram|mi\s+li\s+gam|mg', 'length_mm': r'milimet|mi\s+li\s+mét|mm',
         'volume_l': r'lít|lit', 'tablet_count': r'viên'}
UNIT_PATTERN = '(?P<unit>' + '|'.join(f'(?P<{k}>{v})' for k, v in UNITS.items()) + ')'
PATTERN = re.compile(rf'(?<!\w)(?P<number>{NUMBER})\s*' + UNIT_PATTERN + r'(?=$|[\s.,;:!?])')
RANGE = re.compile(rf'(?<!\w)(?P<lower>{NUMBER})\s+(?:đến|tới|–|-)\s+(?P<upper>{NUMBER})\s*' + UNIT_PATTERN + r'(?=$|[\s.,;:!?])')


def canonical(raw: str) -> str | None:
    try:
        if re.fullmatch(r'\d+(?:[.,]\d+)?', raw):
            number = Decimal(raw.replace(',', '.'))
        elif ' phẩy ' in raw:
            left, right = raw.split(' phẩy ', 1)
            whole = itn.parse_number(left.split())
            digits = [itn.DIGITS.get(word) for word in right.split()]
            if whole is None or not digits or any(digit is None for digit in digits):
                return None
            number = Decimal(str(whole) + '.' + ''.join(map(str, digits)))
        else:
            words = raw.split()
            # Repeated bare numbers could be a stutter, a range or a digit string; do not guess.
            if len(words) > 1 and all(w in itn.DIGITS for w in words) and len(set(words)) < len(words):
                return None
            value = itn.parse_number(words)
            if value is None:
                return None
            number = Decimal(value)
        return format(number.normalize(), 'f')
    except (ValueError, InvalidOperation):
        return None


def measurements(text: str, *, ranges: bool = True) -> list[dict]:
    plain = unicodedata.normalize('NFC', text.lower())
    result = []
    for match in RANGE.finditer(plain) if ranges else []:
        lower, upper = canonical(match['lower']), canonical(match['upper'])
        if lower is None or upper is None:
            continue
        kind = next(key for key in UNITS if match[key] is not None)
        result.append({'type': kind + '_range', 'value': lower + '..' + upper, 'start': match.start(),
                       'end': match.end(), 'evidence': plain[match.start():match.end()]})
    for match in PATTERN.finditer(plain):
        if any(match.start() < other['end'] and other['start'] < match.end() for other in result):
            continue
        value = canonical(match['number'])
        if value is None:
            continue
        kind = next(key for key in UNITS if match[key] is not None)
        result.append({'type': kind, 'value': value, 'start': match.start(), 'end': match.end(), 'evidence': plain[match.start():match.end()]})
    return sorted(result, key=lambda item: item['start'])


def measurement_entities(text: str, *, ranges: bool = True) -> dict:
    counts, result = Counter(), {}
    for item in measurements(text, ranges=ranges):
        counts[item['type']] += 1
        result[f"{item['type']}_{counts[item['type']]}"] = item['value']
    return result


def extract(text: str) -> dict:
    return {**commerce(text), **measurement_entities(text)}
