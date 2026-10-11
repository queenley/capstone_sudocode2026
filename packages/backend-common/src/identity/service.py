import secrets
import httpx
from datetime import timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from src.db.models import Challenge, Customer, CustomerIdentity, Outbox, now
from src.security.service import normalize_identifier


def aware(date):
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


class IdentityService:
    def __init__(self, db, security):
        self.db, self.security = db, security

    def challenge(self, conversation, kind, value, consent):
        if not consent:
            raise HTTPException(422, "Identity and memory consent is required")
        if (
            self.security.settings.environment == "production"
            and not self.security.settings.otp_url
        ):
            raise HTTPException(
                503, "Configure an OTP delivery provider before enabling identification"
            )
        value = normalize_identifier(kind, value)
        code = str(secrets.randbelow(900000) + 100000)
        challenge = Challenge(
            conversation_id=conversation.id,
            kind=kind,
            identifier_digest=self.security.digest(kind + ":" + value),
            encrypted_value=self.security.encrypt(value),
            code_digest=self.security.digest(code),
            expires_at=now() + timedelta(minutes=5),
        )
        self.db.add(challenge)
        self.db.flush()
        settings = self.security.settings
        if settings.otp_url:
            try:
                response = httpx.post(
                    settings.otp_url,
                    headers={"Authorization": "Bearer " + settings.otp_token},
                    json={
                        "kind": kind,
                        "recipient": value,
                        "code": code,
                        "expires_seconds": 300,
                    },
                    timeout=5,
                )
                response.raise_for_status()
            except httpx.HTTPError:
                raise HTTPException(
                    503, "Verification delivery unavailable; try again later"
                )
            return {"challenge_id": str(challenge.id), "delivery": "provider"}
        return {
            "challenge_id": str(challenge.id),
            "development_code": code,
            "delivery": "development-only",
        }

    def verify(self, conversation, challenge_id, code, full_name, access_token=""):
        challenge = self.db.scalar(
            select(Challenge)
            .where(
                Challenge.id == challenge_id,
                Challenge.conversation_id == conversation.id,
            )
            .with_for_update()
        )
        if (
            not challenge
            or challenge.consumed_at
            or aware(challenge.expires_at) < now()
            or challenge.attempts >= 5
        ):
            raise HTTPException(422, "Challenge expired or invalid")
        challenge.attempts += 1
        if not secrets.compare_digest(
            challenge.code_digest, self.security.digest(code)
        ):
            self.db.commit()  # Persist failed attempts even though the request fails.
            raise HTTPException(422, "Incorrect verification code")
        matches = self.db.scalars(
            select(CustomerIdentity).where(
                CustomerIdentity.identifier_digest == challenge.identifier_digest,
                CustomerIdentity.revoked_at.is_(None),
            )
        ).all()
        if access_token:
            customer_id = self.security.customer(self.db, access_token)
        elif matches:
            # A verified shared number cannot prove which person is returning.
            raise HTTPException(
                409, "Returning/shared identifier: use your saved customer access token"
            )
        else:
            customer = Customer(full_name=full_name)
            self.db.add(customer)
            self.db.flush()
            customer_id = customer.id
        existing = next((m for m in matches if m.customer_id == customer_id), None)
        if not existing:
            self.db.add(
                CustomerIdentity(
                    customer_id=customer_id,
                    kind=challenge.kind,
                    identifier_digest=challenge.identifier_digest,
                    encrypted_value=challenge.encrypted_value,
                    consent_at=now(),
                    verified_at=now(),
                )
            )
        challenge.consumed_at = now()
        conversation.customer_id = customer_id
        token = self.security.issue_access(self.db, customer_id)
        self.db.add(
            Outbox(
                event_type="identity.customer.verified",
                aggregate_id=customer_id,
                payload={
                    "customer_id": str(customer_id),
                    "conversation_id": str(conversation.id),
                },
            )
        )
        return {"customer_id": str(customer_id), "customer_token": token}
