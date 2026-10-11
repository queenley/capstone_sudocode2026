"""The PII vault's rows. ``docs/design.md`` sections 4.1 and 5.3.

A call's tokens and the values behind them, encrypted with AES-GCM under a key
derived from the platform secret. Loaded into a
:class:`~ai_agent_service.components.intake.pii.Vault` before a turn, the new
entries saved after it. The checkpoint, the transcript and the model only ever
see ``<PHONE_1>``.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..components.intake.pii import Vault
from ..config.database import derived_key
from .db import connection


def identity_secret() -> str:
    """The secret identity keys are hashed with (section 4.2)."""
    return derived_key("identity").hex()


def _seal(value: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(derived_key("pii-vault")).encrypt(nonce, value.encode(), None)


def _open(blob: bytes) -> str:
    return AESGCM(derived_key("pii-vault")).decrypt(blob[:12], blob[12:], None).decode()


async def load(call_id: int) -> Vault:
    async with connection() as conn:
        cursor = await conn.execute("SELECT token, kind, value_enc FROM pii_vault WHERE call_id = %s", (call_id,))
        rows = await cursor.fetchall()
    return Vault(entries={r["token"]: (r["kind"], _open(bytes(r["value_enc"]))) for r in rows})


async def save(call_id: int, vault: Vault, *, customer_id: str | None = None) -> None:
    """Write the entries added since the vault was loaded."""
    if not vault.added:
        return
    async with connection() as conn:
        for token in vault.added:
            kind, value = vault.entries[token]
            await conn.execute(
                "INSERT INTO pii_vault (call_id, token, kind, value_enc, customer_id) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (call_id, token) DO NOTHING",
                (call_id, token, kind, _seal(value), customer_id),
            )
    vault.added.clear()
