import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from src.db.models import Conversation, CustomerAccess, now


class Security:
    def __init__(self, settings):
        self.settings = settings
        key = settings.encryption_key or base64.urlsafe_b64encode(
            hashlib.sha256(settings.secret.encode()).digest()
        )
        self.cipher = Fernet(key)

    def digest(self, value):
        return hmac.new(
            self.settings.secret.encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    def encrypt(self, value):
        return self.cipher.encrypt(value.encode())

    def decrypt(self, value):
        return self.cipher.decrypt(value).decode()

    def issue_access(self, db, customer_id):
        token = secrets.token_urlsafe(32)
        db.add(
            CustomerAccess(
                customer_id=customer_id,
                token_digest=self.digest(token),
                expires_at=now() + timedelta(days=30),
            )
        )
        return token

    def customer(self, db, token):
        access = db.scalar(
            select(CustomerAccess).where(
                CustomerAccess.token_digest == self.digest(token),
                CustomerAccess.revoked_at.is_(None),
                CustomerAccess.expires_at > now(),
            )
        )
        if not access:
            raise HTTPException(401, "Customer access expired or invalid")
        return access.customer_id

    def conversation(self, db, conversation_id, token, lock=False):
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if lock:
            stmt = stmt.with_for_update()
        conv = db.scalar(stmt)
        if not conv or not hmac.compare_digest(
            conv.anonymous_session_digest, self.digest(token)
        ):
            raise HTTPException(404, "Conversation not found")
        return conv

    def role(self, token, allowed):
        for role in ("admin", "agent", "seller", "developer"):
            if (
                hmac.compare_digest(token, getattr(self.settings, role + "_token"))
                and role in allowed
            ):
                return role
        raise HTTPException(403, "Role not authorized")


def normalize_identifier(kind, value):
    if kind == "phone":
        digits = re.sub(r"[^0-9+]", "", value)
        if digits.startswith("0"):
            digits = "+84" + digits[1:]
        if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
            raise HTTPException(422, "Use a valid international phone number")
        return digits
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Invalid email")
    return email


def mask(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    return re.sub(r"(?<!\w)(?:\+?\d[\s.-]?){9,15}(?!\w)", "[phone]", text)
