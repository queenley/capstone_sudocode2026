"""Which part of Vietnam an address is in: ``bac``, ``trung`` or ``nam``.

The regions the CRM uses (``crm_seed.json``), so a customer the shop met on
the web gets one too: from the delivery address of their order
(``commerce/service.py``), for the voice that answers their calls in their
own accent (the agent's ``elevenlabs:`` voice).

Every province of the 63, by the usual three regions (Bắc Trung Bộ, from
Thanh Hóa, counts as Trung), with the city names and short forms addresses
are written with ("TP.HCM", "Sài Gòn", "HN", "Đà Lạt"). Accents and case do
not matter. An address names its province last, so the last name found wins:
"đường Nguyễn Huệ, Q.1, TP.HCM" is in the south, not in Huế.
"""

from __future__ import annotations

import re
import unicodedata

REGIONS: dict[str, tuple[str, ...]] = {
    "bac": (
        "ha noi", "hanoi", "hn", "hai phong", "quang ninh", "ha long", "bac ninh", "bac giang", "hai duong",
        "hung yen", "thai binh", "nam dinh", "ninh binh", "ha nam", "vinh phuc", "phu tho", "viet tri",
        "thai nguyen", "tuyen quang", "ha giang", "cao bang", "bac kan", "bac can", "lang son", "lao cai", "sa pa",
        "sapa", "yen bai", "dien bien", "lai chau", "son la", "hoa binh",
    ),
    "trung": (
        "thanh hoa", "nghe an", "ha tinh", "quang binh", "dong hoi", "quang tri", "thua thien hue", "hue",
        "da nang", "quang nam", "hoi an", "tam ky", "quang ngai", "binh dinh", "quy nhon", "phu yen", "tuy hoa",
        "khanh hoa", "nha trang", "cam ranh", "ninh thuan", "phan rang", "binh thuan", "phan thiet", "mui ne",
        "kon tum", "gia lai", "pleiku", "dak lak", "dac lac", "buon ma thuot", "buon me thuot", "dak nong",
        "lam dong", "da lat", "dalat",
    ),
    "nam": (
        "ho chi minh", "tp hcm", "tphcm", "hcm", "hcmc", "sai gon", "saigon", "sg", "binh duong", "thu dau mot",
        "di an", "thuan an", "dong nai", "bien hoa", "ba ria", "vung tau", "brvt", "tay ninh", "binh phuoc",
        "long an", "tan an", "tien giang", "my tho", "ben tre", "tra vinh", "vinh long", "dong thap", "cao lanh",
        "sa dec", "an giang", "long xuyen", "chau doc", "kien giang", "rach gia", "phu quoc", "can tho",
        "hau giang", "vi thanh", "soc trang", "bac lieu", "ca mau",
    ),
}

_NAMES = sorted(((name, region) for region, names in REGIONS.items() for name in names), key=lambda nr: -len(nr[0]))
_PATTERN = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(name) for name, _ in _NAMES) + r")(?![a-z0-9])")
_REGION_OF = dict(_NAMES)


def plain(text: str) -> str:
    """Lower case without accents (đ as d), punctuation as spaces: how the names above are written."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def region_of(address: str | None) -> str | None:
    """``bac``, ``trung`` or ``nam`` for the province *address* ends with; None when it names none."""
    if not address:
        return None
    found = list(_PATTERN.finditer(plain(address)))
    return _REGION_OF[found[-1].group(1)] if found else None
