"""The offline market research's settings and its cleaning of web text. ``docs/plan/002-so-sanh-doi-thu-tu-web.md``.

Both the MCP server ``market`` (which fetches) and the research round (which reads what was fetched) use these, so
a page is cleaned the same way wherever it is read. Web text is untrusted data: it is cleaned of markup, of control
characters and of sentences addressed to a model, and cut to a length, before any model reads it. The cleaning is a
second line; the first is that nothing reading web text can write to an order, a customer or the knowledge base
without a person (the research has no business tool and its cards wait for a reviewer).
"""

from __future__ import annotations

import functools
import html
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from ...config.config_manager import ROOT

MARKET_YAML = ROOT / "config" / "market.yaml"


@functools.lru_cache(maxsize=1)
def settings(path: Path = MARKET_YAML) -> Mapping[str, Any]:
    """``config/market.yaml``, read once."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section in ("search", "extract", "research", "battlecard"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"{path.name} lacks the `{section}` section")
    return data


SCRIPT = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TAG = re.compile(r"<[^>]+>")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
SPACE = re.compile(r"\s+")
#: A sentence that speaks to a model rather than to a reader: the shape of an indirect prompt injection.
INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|prompts?)|disregard (all |the )?(previous|above)|"
    r"system prompt|you are (now )?(an? )?(ai|assistant|chatgpt|claude)|as an ai (model|assistant)|"
    r"new instructions?:|<\|?(im_start|system|assistant)\|?>|"
    r"bỏ qua (mọi|các|tất cả)( các)? (hướng dẫn|chỉ dẫn|lệnh)|hướng dẫn hệ thống|bạn là (một )?(trợ lý|ai|mô hình))",
    re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
#: A phone, an ID or an account number: never carried out of a page.
DIGIT_RUN = re.compile(r"(?<!\d)\d{9,14}(?!\d)")
OMITTED = "[đã lược]"


def clean(text: Any, *, limit: int) -> str:
    """*text* as plain, single-spaced words, without what speaks to a model, at most *limit* characters."""
    value = str(text or "")
    value = SCRIPT.sub(" ", value)
    value = COMMENT.sub(" ", value)
    value = TAG.sub(" ", value)
    value = html.unescape(value)
    value = CONTROL.sub("", value)
    value = DIGIT_RUN.sub(OMITTED, value)
    kept = [OMITTED if INJECTION.search(part) else part for part in SENTENCE.split(value)]
    value = SPACE.sub(" ", " ".join(kept)).strip()
    if len(value) > limit:
        value = value[:limit].rsplit(" ", 1)[0] + " …"
    return value


#: What makes a customer's line a comparison with another seller, on the plain (unaccented) text. A battlecard is
#: found only on such a line (``components/knowledge/search.py``) and indexed only under such lines. The first real
#: card (2026-11-27) came first for "Bảo hành máy lọc không khí bao lâu?" and "phòng bao nhiêu m2?" about its
#: product, above BH-01 and SP-AIR-01: a product's entry is preferred on every turn about that product.
COMPARISON = re.compile(
    r"\b(ben kia|ben khac|ben do|cho khac|noi khac|shop khac|cua hang khac|tiem khac|tren mang|shopee|lazada|"
    r"tiki|tiktok|re hon|mac hon|dat hon|gia thap hon|gia tot hon|so voi|so sanh|so gia|duoc gi hon|"
    r"o day duoc gi|sao phai mua)\b")


def compares(text: str) -> bool:
    """Whether *text* compares the shop with another seller."""
    from ..intake.text import plain

    return COMPARISON.search(plain(str(text or ""))) is not None


def reference_domains() -> list[str]:
    """The manufacturers' domains a customer may be given a link to (``references.allowed_domains``)."""
    return [str(d) for d in (settings().get("references") or {}).get("allowed_domains") or ()]


def official(url: str) -> bool:
    """Whether *url* is an https page on a manufacturer's domain the shop allows."""
    return allowed(url, reference_domains())


def references(urls: Any) -> list[dict[str, str]]:
    """*urls* as the links an approved answer carries; raises ``ValueError`` naming a link that may not be given."""
    found = [str(u).strip() for u in urls or () if str(u).strip()]
    limit = int((settings().get("references") or {}).get("max_per_answer") or 2)
    if len(found) > limit:
        raise ValueError(f"At most {limit} links to a manufacturer's page per answer")
    refused = [u for u in found if not official(u)]
    if refused:
        raise ValueError("Only https pages on a manufacturer's domain in config/market.yaml (references) may be "
                         f"given to a customer: {', '.join(refused)}")
    return [{"url": u, "domain": domain(u)} for u in dict.fromkeys(found)]


def domain(url: str) -> str:
    """The host of *url*, lower-case, without a leading ``www.``."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def allowed(url: str, domains: list[str] | tuple[str, ...]) -> bool:
    """Whether *url* is https on one of *domains* or beneath it."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        return False
    host = domain(url)
    return any(host == d or host.endswith("." + d) for d in (str(d).lower().removeprefix("www.") for d in domains))
