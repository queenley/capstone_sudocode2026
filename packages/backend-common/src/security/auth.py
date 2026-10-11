import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
import jwt
from fastapi import HTTPException
from sqlalchemy import select
from src.db.models import StaffUser, now


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()


def password_matches(password, encoded):
    salt, digest = encoded.split(":")
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt), 310000
    )
    return hmac.compare_digest(actual, base64.b64decode(digest))


def login(db, security, username, password):
    user = db.scalar(
        select(StaffUser).where(
            StaffUser.username == username, StaffUser.active.is_(True)
        )
    )
    # Always do password hashing, including invalid usernames.
    valid = password_matches(
        password, user.password_hash if user else password_hash("unavailable")
    )
    if not user or not valid:
        raise HTTPException(401, "Invalid username or password")
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            "exp": now() + timedelta(hours=8),
            "iat": now(),
            "aud": "telesales-staff",
        },
        security.settings.secret,
        algorithm="HS256",
    )
    return {"access_token": token, "role": user.role, "username": user.username}


def resolve_staff(db, security, token, allowed):
    try:
        claims = jwt.decode(
            token,
            security.settings.secret,
            algorithms=["HS256"],
            audience="telesales-staff",
        )
        user = db.get(StaffUser, claims["sub"])
        if not user or not user.active or user.role not in allowed:
            raise HTTPException(403, "Staff role is not authorized")
        return user.role, str(user.id)
    except jwt.InvalidTokenError:
        # Development service tokens remain convenient for tests and local scripts.
        if security.settings.environment != "production":
            role = security.role(token, allowed)
            return role, role
        raise HTTPException(401, "Staff session expired or invalid")
