"""Personal data: tokenised before a model or a trace sees it, restored after.

``docs/design.md`` sections 4.1 and 4.5. A phone number becomes
``<PHONE_1>``, an ID card number ``<CCCD_1>``, a bank account ``<BANK_1>``,
and the value goes into the call's :class:`Vault`. The model, Jev, Langfuse
and the checkpoint only ever see the token. :func:`detokenize` runs after
every guard has passed, and restores only this call's own tokens: a phone
number the customer gave may be read back to them; an ID card or account
number never is, only its last four digits (policies QT-04, PB-08).

The vault here is in memory, one per call. The API loads the call's rows
from the ``pii_vault`` table before a turn and saves what was added after
it, encrypted; the evaluation runner keeps it in memory. Deleting a
customer is deleting their vault rows.

**Addresses** have no ready-made recogniser for Vietnamese (Presidio has
none for addresses either, and its documentation advises a pattern plus a
list of place names), so the rule is section 4.1's: a cue ("địa chỉ", "giao
về", "nhà chị ở", "anh ở") followed, in the same clause, by an
administrative marker (số nhà, ngõ, hẻm, đường, phường, quận, huyện, "q7",
"p12") or a province's name. The harness puts the real address back into the
tools that take one (section 4.4): a regional promotion is decided by it
(KM-08).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Order matters: a 12-digit ID card before a 9-14 digit account, a phone before both.
#: A mobile number as people type and ASR writes it: "0901 234 567",
#: "090.123.4567", "+84 90 123 4567". Separators are accepted only after a
#: leading 0 or +84, so a grouped amount such as "500.000.000" stays money.
SPACED_PHONE = r"(?:\+84|84|0)[ .\-]?[35789](?:[ .\-]?\d){8}"

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PHONE", re.compile(rf"(?<![\d<])(?:{SPACED_PHONE}|(?:\+84|84)?0?[35789]\d{{8}})(?![\d]|[ .\-]\d)")),
    ("CCCD", re.compile(r"(?<![\d<])0\d{11}(?!\d)")),
    ("BANK", re.compile(r"(?<![\d<])\d{9,14}(?!\d)")),
)
TOKEN = re.compile(r"<(PHONE|CCCD|BANK|ADDR)_(\d+)>")

#: Section 4.1: what announces an address, matched without diacritics.
ADDRESS_CUE = re.compile(
    r"\b(dia chi( la| nha)?|giao (ve|toi|den|qua)|gui (ve|toi|den)|ship (ve|toi|den|qua)|"
    r"nha (anh|chi|em|minh|toi|tui|co|chu|a|c|e) o|(anh|chi|em|minh|toi|tui|co|chu|a|c|e) (dang )?o)\s+"
)
#: What makes the words after a cue an address: an administrative marker...
ADMIN_MARKER = re.compile(
    r"\b(so nha|so \d+|ngo|ngach|hem|kiet|duong|pho|phuong|xa|thi tran|quan|huyen|thi xa|thanh pho|tp|tinh|"
    r"khu pho|to dan pho|ap|thon|chung cu|toa|[pq]\.?\s?\d{1,2})\b"
)
#: ...or a province (the mock's own region lists, ``mock_tools._region_of``, and the rest of the 63).
PROVINCES = re.compile(r"\b(" + "|".join([
    "ha noi", "hn", "hai phong", "quang ninh", "bac ninh", "bac giang", "hai duong", "hung yen", "thai binh", "nam dinh",
    "ninh binh", "ha nam", "vinh phuc", "phu tho", "thai nguyen", "tuyen quang", "ha giang", "cao bang", "bac kan",
    "lang son", "lao cai", "yen bai", "dien bien", "lai chau", "son la", "hoa binh", "thanh hoa", "nghe an", "ha tinh",
    "quang binh", "quang tri", "thua thien hue", "hue", "da nang", "quang nam", "quang ngai", "binh dinh", "phu yen",
    "khanh hoa", "nha trang", "ninh thuan", "binh thuan", "kon tum", "gia lai", "dak lak", "dak nong", "lam dong",
    "da lat", "ho chi minh", "hcm", "tphcm", "sai gon", "sg", "binh duong", "dong nai", "ba ria", "vung tau", "tay ninh",
    "binh phuoc", "long an", "tien giang", "ben tre", "tra vinh", "vinh long", "dong thap", "an giang", "kien giang",
    "can tho", "hau giang", "soc trang", "bac lieu", "ca mau",
]) + r")\b")
#: Where a part of an address ends: a comma, the sentence, or a closing particle.
#: A dot inside a name ("TP.HCM") is not an end.
ADDRESS_END = re.compile(r"[,;!?]|\.(?=\s|$)|\s+(nhe|nha|a|nhen|do|ne|va|con|thi|roi|nhe em|nha em)\b|$")


def _plain(text: str) -> str:
    """Lower case without diacritics, one character for one: positions stay those of *text*."""
    out = []
    for char in text.lower():
        if char == "đ":
            out.append("d")
            continue
        base = unicodedata.normalize("NFD", char)[0]
        out.append(base if base.isascii() or not unicodedata.combining(base) else char)
    return "".join(out)


def address_spans(text: str) -> list[tuple[int, int]]:
    """Where *text* states an address: after a cue, part by part, when a marker or a province is in it.

    The parts of a Vietnamese address are joined by commas ("12 ngõ 34 Láng
    Hạ, Đống Đa, Hà Nội"), so after the first part each next one is taken
    while it is itself a place: a marker, a province, or a short name in
    title case.
    """
    plain = _plain(text)
    spans = []
    for cue in ADDRESS_CUE.finditer(plain):
        start = cue.end()
        end = start + ADDRESS_END.search(plain[start:]).start()
        first = text[start:end].strip()
        if not first or not (first[0].isdigit() or first[0].isupper() or ADMIN_MARKER.match(plain[start:end].strip())):
            continue
        while end < len(plain) and plain[end] == ",":
            following = end + 1 + ADDRESS_END.search(plain[end + 1:]).start()
            if not _place(text[end + 1:following], plain[end + 1:following]):
                break
            end = following
        if ADMIN_MARKER.search(plain[start:end]) or PROVINCES.search(plain[start:end]):
            spans.append((start, end))
    return spans


def _place(part: str, plain: str) -> bool:
    """Whether one comma-separated part is a place: a marker, a province, or a short title-case name."""
    words = part.split()
    if not words:
        return False
    if ADMIN_MARKER.search(plain) or PROVINCES.search(plain):
        return True
    return len(words) <= 4 and all(word[0].isupper() for word in words)


def normalise_phone(raw: str) -> str | None:
    """Ten digits starting with 0, or None when *raw* is not a Vietnamese mobile."""
    digits = re.sub(r"[\s\-.()]", "", raw)
    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    elif len(digits) == 9:
        digits = "0" + digits
    return digits if re.fullmatch(r"0\d{9}", digits) else None


@dataclass
class Vault:
    """One call's tokens and the values behind them."""

    entries: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (kind, value)
    #: Tokens added since the vault was loaded, for the caller to persist.
    added: list[str] = field(default_factory=list)

    def put(self, kind: str, value: str) -> str:
        for token, (known_kind, known) in self.entries.items():
            if known_kind == kind and known == value:
                return token
        index = 1 + sum(1 for k, _ in self.entries.values() if k == kind)
        token = f"<{kind}_{index}>"
        self.entries[token] = (kind, value)
        self.added.append(token)
        return token

    def get(self, token: str) -> str | None:
        entry = self.entries.get(token)
        return entry[1] if entry else None

    def values(self, kind: str) -> list[str]:
        return [value for k, value in self.entries.values() if k == kind]


def tokenise(text: str, vault: Vault) -> str:
    """*text* with personal data replaced by this call's tokens: addresses first, then numbers."""
    for start, end in reversed(address_spans(text)):
        text = text[:start] + vault.put("ADDR", text[start:end].strip()) + text[end:]
    for kind, pattern in PATTERNS:
        def swap(match: re.Match[str], kind: str = kind) -> str:
            value = match.group(0)
            if kind == "PHONE":
                value = normalise_phone(value) or value
            return vault.put(kind, value)

        text = pattern.sub(swap, text)
    return text


def tokenise_data(value: Any, vault: Vault) -> Any:
    """Mask JSON values before they enter model messages or checkpoint state."""
    if isinstance(value, dict):
        return {k: (vault.put("ADDR", v) if k in ("address", "delivery_address", "shipping_address")
                    and isinstance(v, str) and v and not TOKEN.fullmatch(v) else tokenise_data(v, vault))
                for k, v in value.items()}
    if isinstance(value, list):
        return [tokenise_data(v, vault) for v in value]
    return tokenise(value, vault) if isinstance(value, str) else value


def detokenize_data(value: Any, vault: Vault, *, reveal_phone: bool = True) -> Any:
    """Restore JSON values only at an authorized output boundary, without string substitution into JSON."""
    if isinstance(value, dict):
        return {k: detokenize_data(v, vault, reveal_phone=reveal_phone) for k, v in value.items()}
    if isinstance(value, list):
        return [detokenize_data(v, vault, reveal_phone=reveal_phone) for v in value]
    return detokenize(value, vault, reveal_phone=reveal_phone) if isinstance(value, str) else value


def detokenize(text: str, vault: Vault, *, reveal_phone: bool = True) -> str:
    """Restore this call's tokens: the customer's own phone number and address
    in full for the customer themselves (``reveal_phone``); an ID card or
    account number, and anything on a staff screen, as its last four
    characters."""

    def swap(match: re.Match[str]) -> str:
        value = vault.get(match.group(0))
        if value is None:
            return match.group(0)
        if match.group(1) in ("PHONE", "ADDR") and reveal_phone:
            return value
        return "****" + value[-4:]

    return TOKEN.sub(swap, text)


def unknown_tokens(text: str, vault: Vault) -> list[str]:
    """Tokens in *text* that are not this call's: a leak from somewhere else."""
    return [m.group(0) for m in TOKEN.finditer(text) if vault.get(m.group(0)) is None]


def mask(text: str) -> str:
    """For logs: long digit strings keep their last four digits only."""
    return re.sub(r"(?<!\d)\d{9,14}(?!\d)", lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)
