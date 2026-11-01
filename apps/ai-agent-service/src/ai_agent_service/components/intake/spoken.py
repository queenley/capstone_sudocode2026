"""Generic Vietnamese number/letter forms for entity parsing, not ASR text rewriting.

The spelling convention matches the independent TTS renderer in
evaluation/data-generation/src/asr/spoken.py; no scenarios or labels are read.
"""
from datetime import date
from functools import lru_cache
import re
import unicodedata

from . import itn

DIGITS = ('không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín')
LETTERS = dict(zip('abcdefghijklmnopqrstuvwxyz',
                  ('a', 'bê', 'xê', 'đê', 'e', 'ép', 'giê', 'hát', 'i', 'gi', 'ca', 'e lờ', 'em mờ',
                   'en nờ', 'ô', 'pê', 'quy', 'e rờ', 'ét', 'tê', 'u', 'vê', 'vê kép', 'ích', 'i dài', 'dét')))


def number_words(value: str) -> str:
    raw = str(value).strip()
    if not re.fullmatch(r'[+-]?\d+', raw):
        raise ValueError('Expected an integer')
    n = int(raw)
    if n < 0:
        return 'âm ' + number_words(str(-n))
    if n < 10:
        return DIGITS[n]
    if n < 100:
        tens, units = divmod(n, 10)
        return ('mười' if tens == 1 else DIGITS[tens] + ' mươi') + (
            ' ' + ('lăm' if units == 5 else 'mốt' if units == 1 and tens > 1 else DIGITS[units]) if units else '')
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return DIGITS[hundreds] + ' trăm' + ((' linh ' if rest < 10 else ' ') + number_words(str(rest)) if rest else '')
    for scale, unit in ((1_000_000_000, 'tỷ'), (1_000_000, 'triệu'), (1000, 'nghìn')):
        if n >= scale:
            head, rest = divmod(n, scale)
            tail = (' không trăm ' + ('linh ' if rest < 10 else '') if rest < 100 and rest else ' ')
            return number_words(str(head)) + ' ' + unit + (tail + number_words(str(rest)) if rest else '')
    raise ValueError('Invalid number')


def code_words(code: str) -> str:
    return ' '.join((' '.join(DIGITS[int(c)] for c in part) if part.startswith('0') and len(part) > 1
                     else number_words(part)) if part.isdigit() else ' '.join(LETTERS[c.lower()] for c in part)
                    for part in re.findall(r'[A-Za-z]+|\d+', code))


def catalogue_spoken(name: str) -> str:
    units = {'ml': 'mi li lít', 'kg': 'ki lô gam', 'cm': 'xen ti mét', 'mm': 'mi li mét',
             'mah': 'mi li am pe giờ', 'l': 'lít', 'g': 'gam', 'm': 'mét', 'w': 'oát'}
    name = unicodedata.normalize('NFC', name)
    def unit_words(match):
        # SI gram/metre symbols are lower case; uppercase G/M can be a code
        # (for example a network generation or a brand), not a physical unit.
        if match[2] in {'G', 'M'}:
            value = catalogue_numbers(match[1]) if re.search(r'[.,]', match[1]) else code_words(match[1])
            return value + ' ' + LETTERS[match[2].lower()]
        return catalogue_numbers(match[1]) + ' ' + units[match[2].lower()]
    name = re.sub(r'(?<![\w.,])(\d+(?:[.,]\d+)*)\s*(' + '|'.join(units) + r')\b',
                  unit_words, name, flags=re.IGNORECASE)
    name = re.sub(r'\b[A-Z]{1,4}(?:-[A-Z0-9]+)+\b|\b[A-Z]{1,4}\d+\b|\b[A-Z]{1,5}\b',
                  lambda m: code_words(m.group()), name)
    return catalogue_numbers(name)


def catalogue_numbers(name: str) -> str:
    def replace(match):
        raw = match.group()
        parts = re.split(r'[.,]', raw)
        if len(parts) > 2:
            if len(set(re.findall(r'[.,]', raw))) == 1 and 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
                return number_words(''.join(parts))
            return raw  # An invalid/mixed numeric token must not be rewritten in pieces.
        # Decimal digits are a sequence: 0.05 must keep the zero after the separator.
        fraction = ' phẩy ' + ' '.join(DIGITS[int(c)] for c in parts[1]) if len(parts) == 2 else ''
        return number_words(parts[0]) + fraction
    return re.sub(r'(?<![\d.,])\d+(?:[.,]\d+)*(?![\d.,])', replace, unicodedata.normalize('NFC', name))


def _calendar_forms(limit: int) -> str:
    forms = set()
    for n in range(1, limit + 1):
        canonical = number_words(str(n))
        forms.update((canonical, canonical.replace('mốt', 'một'), canonical.replace('lăm', 'năm'), canonical.replace('bốn', 'tư')))
        tens, units = divmod(n, 10)
        if tens >= 2 and units:
            forms.add(DIGITS[tens] + ' ' + ('lăm' if units == 5 else 'mốt' if units == 1 else DIGITS[units]))
    return '|'.join(map(re.escape, sorted(forms, key=lambda s: (-len(s), s))))


@lru_cache(maxsize=1)
def _date_pattern():
    day, month = _calendar_forms(31), _calendar_forms(12)
    words = '|'.join(sorted(itn.NUMBER_WORDS, key=len, reverse=True))
    thousands = '|'.join(DIGITS[1:])
    return re.compile(r'\b(?:ngày|mùng)\s+(?P<day>\d{1,2}|' + day + r')\s+tháng\s+(?P<month>\d{1,2}|' + month +
                      r')\b(?:\s+năm\s+(?P<year>\d{4}(?!\w|[.,/-]\d)|(?:' + thousands + r')\s+(?:nghìn|ngàn)\b(?:\s+(?:' + words + r')\b)*))?', re.IGNORECASE)


def dates(text: str, year: int) -> str:
    def replace(match):
        def value(raw):
            return int(raw) if raw.isdigit() else itn.parse_number(raw.lower().split())
        after = match.string[match.end():]
        # Do not default the year, or accept a partial number, when more was explicitly said.
        continuation = '|'.join(sorted(itn.NUMBER_WORDS | {'phẩy'}, key=len, reverse=True))
        if ((not match['year'] and re.match(r'\s+năm\b', after, re.I))
                or re.match(r'[.,/-]\d|\s+(?:' + continuation + r'|\d+)\b', after, re.I)):
            return match.group()
        try:
            return date(value(match['year']) if match['year'] else year,
                        value(match['month']), value(match['day'])).isoformat()
        except (ValueError, TypeError):
            return match.group()
    return _date_pattern().sub(replace, unicodedata.normalize('NFC', text))


def phones(text: str) -> set[str]:
    text = unicodedata.normalize('NFC', text).lower()
    digit_values = {word: value for word, value in itn.DIGITS.items() if word not in {'linh', 'lẻ', 'mốt', 'lăm', 'nhăm'}}
    digit = r'(?:\d+|' + '|'.join(sorted(digit_values, key=len, reverse=True)) + r')(?!\w)'
    number = re.compile(r'(?:(?:\+|cộng)\s*)?' + digit + r'(?:[\s,().-]+' + digit + r')*')
    cue = re.compile(r'\b(?:điện thoại|sđt|số liên hệ)\b\s*(?:(?:của (?:tôi|mình|anh|chị|em|cô|chú|bác|bạn)|là|số)\s*)*[:=]?\s*')
    found = set()
    for marker in cue.finditer(text):
        match = number.match(text, marker.end())
        while match:
            raw = match.group()
            parts = re.findall(digit, raw)
            digits = ''.join(''.join(str(unicodedata.decimal(c)) for c in part) if part.isdecimal() else str(digit_values[part]) for part in parts)
            international = raw.startswith(('+', 'cộng'))
            if digits.startswith('84') and len(digits) == 11:
                digits = '0' + digits[2:]
            elif international:
                digits = ''  # A foreign/invalid country prefix is not a Vietnamese mobile.
            if re.fullmatch(r'0\d{9}', digits):
                found.add(digits)
            alternative = re.match(r'\s*(?:hoặc|hay|và|/)\s*', text[match.end():])
            match = number.match(text, match.end() + alternative.end()) if alternative else None
    return found


def size_letters(text: str) -> str:
    forms = {'ích ích ích e lờ': 'XXXL', 'ích ích e lờ': 'XXL', 'ích ích ét': 'XXS',
             'ích e lờ': 'XL', 'ích ét': 'XS', 'em mờ': 'M', 'e lờ': 'L', 'ét': 'S'}
    letters = '|'.join(map(re.escape, sorted(set(LETTERS.values()), key=lambda s: (-len(s), s))))
    pattern = r'\b(size|cỡ)\s+(' + '|'.join(map(re.escape, forms)) + r')\b(?!\s+(?:' + letters + r')\b)'
    return re.sub(pattern, lambda m: m[1] + ' ' + forms[m[2].lower()].lower(),
                  unicodedata.normalize('NFC', text), flags=re.IGNORECASE)
