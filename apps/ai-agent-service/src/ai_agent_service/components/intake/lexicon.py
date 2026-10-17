"""The product-name dictionary for recognised speech. ``docs/design.md`` section 4.1, step 3.

One module for text and voice: a scenario's ``customer_turns_asr`` and a live
call's recogniser output are corrected by the same rules (the brief, page 3:
"sửa lỗi ASR bằng từ điển tên sản phẩm").

1. Hints before recognition: the brands in the organisers' catalogue, for
   recognisers that accept them (Whisper's ``hotwords``).
2. Corrections after recognition: ``voice.lexicon.corrections`` in
   ``config/models.yaml``, what the recogniser wrote mapped to what was said,
   and the catalogue's own names, so a name written in lower case without
   its spacing comes back as the catalogue spells it. Matching ignores case
   and respects word edges, so "xiao mi" is fixed and "xiao minh" is not.

Corrections come from errors actually heard, in the lab or in the organisers'
ASR ground truth ("e pia y", "run lai", "ka rô phi"), never from guesses.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from ...config.config_manager import btc_data_dir, get_models_config


class Lexicon:
    def __init__(self) -> None:
        config = get_models_config().voice.lexicon
        self.hotwords = sorted(set(_brands()) | set(config.get("hotwords") or []))
        corrections: dict[str, str] = {**_catalogue_names(), **(config.get("corrections") or {})}
        # Longest first, so "xiao mi air" wins over "xiao mi".
        self._rules = [
            (re.compile(rf"(?<!\w){re.escape(wrong)}(?!\w)", re.IGNORECASE), right)
            for wrong, right in sorted(corrections.items(), key=lambda kv: -len(kv[0]))
            if wrong and wrong != right
        ]

    def correct(self, text: str) -> tuple[str, list[list[str]]]:
        """*text* with every known mishearing fixed, and which rules applied."""
        applied: list[list[str]] = []
        for pattern, right in self._rules:
            text, count = pattern.subn(right, text)
            if count:
                applied.append([pattern.pattern, right])
        return text, applied


@lru_cache(maxsize=1)
def lexicon() -> Lexicon:
    """The process's one dictionary, built on first use."""
    return Lexicon()


def correct(text: str) -> str:
    """*text* with the dictionary applied: what intake does to a recognised turn."""
    return lexicon().correct(text)[0]


def _products() -> list[dict]:
    path = btc_data_dir() / "catalog" / "products.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("products", [])


def _brands() -> list[str]:
    return sorted({p["brand"] for p in _products() if p.get("brand")})


def _catalogue_names() -> dict[str, str]:
    """Each brand as the catalogue spells it, keyed by how speech or a phone keyboard writes it."""
    names = {}
    for brand in _brands():
        names[brand.lower()] = brand
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", brand).lower()
        if spaced != brand.lower():
            names[spaced] = brand  # "air pure" -> AirPure
    return names
