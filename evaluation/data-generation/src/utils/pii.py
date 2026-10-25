from __future__ import annotations
import re
from typing import Any

PHONE=re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){8,10}(?!\d)")
CCCD=re.compile(r"(?<!\d)\d{12}(?!\d)")
EMAIL=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.IGNORECASE)

def redact_contacts(value: Any) -> Any:
    """Redact direct contact/identity strings in prompts while preserving other facts."""
    if isinstance(value,dict):
        return {k:("[REDACTED]" if k.lower() in {"phone","zalo_id","fb_id","email","cccd"} and v else redact_contacts(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact_contacts(item) for item in value]
    if isinstance(value,str):
        value=PHONE.sub("[PHONE]",value)
        value=CCCD.sub("[ID]",value)
        return EMAIL.sub("[EMAIL]",value)
    return value
