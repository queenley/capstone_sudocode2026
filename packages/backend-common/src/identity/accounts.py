"""Storefront accounts: register, log in, reset a password, the profile and the cart.

The phone stays the customer's identity, as on the hotline and Zalo: an account
is a verified phone (``CustomerIdentity`` kind ``phone``) with a password beside
it. Registering proves the phone with a one-time code, the same ``Challenge``
the chat uses, with no conversation. A shopper already verified in the chat (a
customer without a password) keeps their history: registering with that phone
gives them the password, it does not start a second customer. Logging in
returns the same customer access token the chat and the order pages already
take (``Security.issue_access``), so everything that knew a verified shopper
now knows a logged-in one.

- Passwords: PBKDF2 (``src.security.auth.password_hash``), 8 to 128 characters.
- Five wrong passwords lock the account for 15 minutes.
- What a code confirms (name, e-mail, password hash) waits in the challenge, encrypted.
- Resetting a password ends every session of the account.
- The cart: one row per SKU, replaced whole by the page (which merges the
  browser's cart into it on login).
"""
import json
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select

from src.db.models import (
    SKU,
    CartItem,
    Challenge,
    Customer,
    CustomerAccess,
    CustomerIdentity,
    Outbox,
    Product,
    now,
)
from src.identity.service import IdentityService, aware
from src.security.auth import password_hash, password_matches
from src.security.service import normalize_identifier

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
CART_LINES = 30


def check_password(password):
    if not 8 <= len(password or "") <= 128:
        raise HTTPException(422, "Mật khẩu cần từ 8 đến 128 ký tự")


def local_phone(value):
    """+84901234567 -> 0901234567, as Vietnamese shoppers write it."""
    return "0" + value[3:] if value and value.startswith("+84") else value


class AccountService:
    def __init__(self, db, security):
        self.db, self.security = db, security

    # ── who owns a phone ───────────────────────────────────────────────

    def _digest(self, kind, value):
        return self.security.digest(kind + ":" + value)

    def _customers_with_phone(self, phone):
        return self.db.scalars(
            select(Customer)
            .join(CustomerIdentity, CustomerIdentity.customer_id == Customer.id)
            .where(
                CustomerIdentity.kind == "phone",
                CustomerIdentity.identifier_digest == self._digest("phone", phone),
                CustomerIdentity.revoked_at.is_(None),
                Customer.deleted_at.is_(None),
            )
        ).unique().all()

    def _account_with_phone(self, phone):
        return next((c for c in self._customers_with_phone(phone) if c.password_hash), None)

    # ── one-time codes ─────────────────────────────────────────────────

    def _code(self, purpose, phone, payload):
        settings = self.security.settings
        if settings.environment == "production" and not settings.otp_url:
            raise HTTPException(503, "Configure an OTP delivery provider before enabling accounts")
        code = str(secrets.randbelow(900000) + 100000)
        challenge = Challenge(
            conversation_id=None,
            purpose=purpose,
            kind="phone",
            identifier_digest=self._digest("phone", phone),
            encrypted_value=self.security.encrypt(phone),
            encrypted_payload=self.security.encrypt(json.dumps(payload)),
            code_digest=self.security.digest(code),
            expires_at=now() + timedelta(minutes=5),
        )
        self.db.add(challenge)
        self.db.flush()
        return IdentityService(self.db, self.security).deliver(challenge, "phone", phone, code)

    def _redeem(self, purpose, challenge_id, code):
        """The challenge's phone and payload once *code* matches; a wrong code counts an attempt."""
        challenge = self.db.scalar(
            select(Challenge)
            .where(Challenge.id == str(challenge_id), Challenge.purpose == purpose,
                   Challenge.conversation_id.is_(None))
            .with_for_update()
        )
        if (not challenge or challenge.consumed_at or aware(challenge.expires_at) < now()
                or challenge.attempts >= 5):
            raise HTTPException(422, "Mã xác minh đã hết hạn, hãy gửi lại mã mới")
        challenge.attempts += 1
        if not secrets.compare_digest(challenge.code_digest, self.security.digest(code or "")):
            self.db.commit()  # the failed attempt counts even though the request fails
            raise HTTPException(422, "Mã xác minh không đúng")
        challenge.consumed_at = now()
        phone = self.security.decrypt(challenge.encrypted_value)
        return phone, json.loads(self.security.decrypt(challenge.encrypted_payload))

    # ── register, log in, reset ────────────────────────────────────────

    def register_start(self, full_name, phone, password, email=None):
        full_name = " ".join((full_name or "").split())
        if not 2 <= len(full_name) <= 80:
            raise HTTPException(422, "Hãy nhập họ tên (2 đến 80 ký tự)")
        check_password(password)
        phone = normalize_identifier("phone", phone)
        email = normalize_identifier("email", email) if email else None
        if self._account_with_phone(phone):
            raise HTTPException(409, "Số điện thoại này đã có tài khoản. Hãy đăng nhập hoặc lấy lại mật khẩu.")
        return self._code("register", phone,
                          {"full_name": full_name, "email": email, "password_hash": password_hash(password)})

    def register_verify(self, challenge_id, code):
        phone, payload = self._redeem("register", challenge_id, code)
        if self._account_with_phone(phone):
            raise HTTPException(409, "Số điện thoại này đã có tài khoản. Hãy đăng nhập.")
        # A shopper the chat already verified on this phone (no password yet) keeps
        # their history; a phone shared by several such customers starts a new one.
        known = [c for c in self._customers_with_phone(phone) if not c.password_hash]
        customer = known[0] if len(known) == 1 else Customer()
        if customer.id is None:
            self.db.add(customer)
            self.db.flush()
            self.db.add(CustomerIdentity(
                customer_id=customer.id, kind="phone", identifier_digest=self._digest("phone", phone),
                encrypted_value=self.security.encrypt(phone), consent_at=now(), verified_at=now()))
        customer.full_name = payload["full_name"]
        customer.password_hash = payload["password_hash"]
        customer.registered_at = now()
        customer.failed_logins, customer.locked_until = 0, None
        if payload.get("email"):
            self._set_email(customer.id, payload["email"])
        self.db.add(Outbox(event_type="identity.customer.registered", aggregate_id=customer.id,
                           payload={"customer_id": str(customer.id)}))
        token = self.security.issue_access(self.db, customer.id)
        self.db.flush()
        return {"customer_token": token, "account": self.me(customer.id)}

    def login(self, phone, password):
        try:
            phone = normalize_identifier("phone", phone)
        except HTTPException:
            raise HTTPException(401, "Sai số điện thoại hoặc mật khẩu")
        customer = self._account_with_phone(phone)
        if customer and customer.locked_until and aware(customer.locked_until) > now():
            raise HTTPException(429, "Tài khoản tạm khóa 15 phút vì nhập sai mật khẩu nhiều lần")
        # Hash even without an account, so a wrong phone takes as long as a wrong password.
        valid = password_matches(password or "", customer.password_hash if customer else password_hash("unavailable"))
        if not customer or not valid:
            if customer:
                customer.failed_logins = (customer.failed_logins or 0) + 1
                if customer.failed_logins >= MAX_FAILED_LOGINS:
                    customer.locked_until, customer.failed_logins = now() + LOCKOUT, 0
                self.db.commit()
            raise HTTPException(401, "Sai số điện thoại hoặc mật khẩu")
        customer.failed_logins, customer.locked_until = 0, None
        token = self.security.issue_access(self.db, customer.id)
        self.db.flush()
        return {"customer_token": token, "account": self.me(customer.id)}

    def reset_start(self, phone):
        phone = normalize_identifier("phone", phone)
        if not self._account_with_phone(phone):
            raise HTTPException(404, "Chưa có tài khoản với số điện thoại này")
        return self._code("reset", phone, {})

    def reset_verify(self, challenge_id, code, password):
        check_password(password)
        phone, _ = self._redeem("reset", challenge_id, code)
        customer = self._account_with_phone(phone)
        if not customer:
            raise HTTPException(404, "Chưa có tài khoản với số điện thoại này")
        customer.password_hash = password_hash(password)
        customer.failed_logins, customer.locked_until = 0, None
        self._end_sessions(customer.id)
        token = self.security.issue_access(self.db, customer.id)
        self.db.flush()
        return {"customer_token": token, "account": self.me(customer.id)}

    def change_password(self, customer_id, current, new, keep_token):
        check_password(new)
        customer = self.db.get(Customer, customer_id)
        if not customer.password_hash or not password_matches(current or "", customer.password_hash):
            raise HTTPException(401, "Mật khẩu hiện tại không đúng")
        customer.password_hash = password_hash(new)
        self._end_sessions(customer_id, keep=self.security.digest(keep_token))
        return {"status": "changed"}

    def logout(self, token):
        access = self.db.scalar(select(CustomerAccess).where(CustomerAccess.token_digest == self.security.digest(token)))
        if access and not access.revoked_at:
            access.revoked_at = now()
        return {"status": "logged_out"}

    def _end_sessions(self, customer_id, keep=None):
        for access in self.db.scalars(select(CustomerAccess).where(
                CustomerAccess.customer_id == customer_id, CustomerAccess.revoked_at.is_(None))):
            if access.token_digest != keep:
                access.revoked_at = now()

    # ── the profile ────────────────────────────────────────────────────

    def _identity(self, customer_id, kind):
        return self.db.scalars(select(CustomerIdentity).where(
            CustomerIdentity.customer_id == customer_id, CustomerIdentity.kind == kind,
            CustomerIdentity.revoked_at.is_(None))).first()

    def _set_email(self, customer_id, email):
        current = self._identity(customer_id, "email")
        digest = self._digest("email", email)
        if current and current.identifier_digest == digest:
            return
        if current:
            current.revoked_at = now()
        self.db.add(CustomerIdentity(customer_id=customer_id, kind="email", identifier_digest=digest,
                                     encrypted_value=self.security.encrypt(email), consent_at=now()))

    def me(self, customer_id):
        customer = self.db.get(Customer, customer_id)
        phone = self._identity(customer_id, "phone")
        email = self._identity(customer_id, "email")
        return {
            "customer_id": str(customer.id),
            "full_name": customer.full_name,
            "phone": local_phone(self.security.decrypt(phone.encrypted_value)) if phone and phone.encrypted_value else None,
            "email": self.security.decrypt(email.encrypted_value) if email and email.encrypted_value else None,
            "registered": bool(customer.password_hash),
            "registered_at": customer.registered_at.isoformat() if customer.registered_at else None,
        }

    def update_me(self, customer_id, full_name=None, email=None):
        customer = self.db.get(Customer, customer_id)
        if full_name is not None:
            full_name = " ".join(full_name.split())
            if not 2 <= len(full_name) <= 80:
                raise HTTPException(422, "Hãy nhập họ tên (2 đến 80 ký tự)")
            customer.full_name = full_name
        if email is not None:
            if email.strip():
                self._set_email(customer_id, normalize_identifier("email", email))
            elif (current := self._identity(customer_id, "email")) is not None:
                current.revoked_at = now()
        self.db.flush()
        return self.me(customer_id)

    # ── the cart ───────────────────────────────────────────────────────

    def cart(self, customer_id):
        return [{"sku": row.sku_code, "qty": row.quantity} for row in self.db.scalars(
            select(CartItem).where(CartItem.customer_id == customer_id).order_by(CartItem.updated_at, CartItem.sku_code))]

    def replace_cart(self, customer_id, lines):
        wanted = {}
        for line in lines:
            wanted[line["sku"]] = max(1, min(99, int(line["qty"])))
        if len(wanted) > CART_LINES:
            raise HTTPException(422, f"Giỏ hàng tối đa {CART_LINES} sản phẩm")
        # Only codes the shop sells; a code retired since the page saved it is dropped.
        sold = set(self.db.scalars(
            select(SKU.sku_code).join(Product, Product.id == SKU.product_id)
            .where(SKU.sku_code.in_(list(wanted)), SKU.active.is_(True), Product.active.is_(True))
        )) if wanted else set()
        self.db.execute(delete(CartItem).where(CartItem.customer_id == customer_id))
        for sku, qty in wanted.items():
            if sku in sold:
                self.db.add(CartItem(customer_id=customer_id, sku_code=sku, quantity=qty, updated_at=now()))
        self.db.flush()
        return self.cart(customer_id)
