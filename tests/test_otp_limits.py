"""Verification codes are rationed (src/identity/otp_limits.py, eks-architecture.md 3.3): each is a paid SMS."""
from conftest import conversation

PHONE = "0912345678"


def ask(client, phone=PHONE):
    c, h = conversation(client)
    return client.post(f"/api/conversations/{c}/identity/challenge", headers=h,
                       json={"kind": "phone", "value": phone, "consent": True})


def register(client, phone=PHONE):
    return client.post("/api/customer/register/start",
                       json={"full_name": "Nguyễn Thị Oanh", "phone": phone, "password": "matkhau123"})


def test_send_again_within_the_cooldown_is_refused_with_the_wait(client, monkeypatch):
    monkeypatch.setenv("OTP_COOLDOWN_SECONDS", "60")
    assert ask(client).status_code == 200
    again = ask(client)
    assert again.status_code == 429
    assert 1 <= int(again.headers["Retry-After"]) <= 60
    assert ask(client, "0987654321").status_code == 200  # another number is not held


def test_another_step_on_the_same_number_is_not_made_to_wait(client, monkeypatch):
    monkeypatch.setenv("OTP_COOLDOWN_SECONDS", "60")
    assert ask(client).status_code == 200  # verified in the chat
    assert register(client).status_code == 200  # then registers at once


def test_the_hourly_limit_counts_every_step(client, monkeypatch):
    monkeypatch.setenv("OTP_PER_HOUR_IDENTIFIER", "2")
    assert ask(client).status_code == 200
    assert register(client).status_code == 200
    refused = ask(client)
    assert refused.status_code == 429 and refused.headers["Retry-After"] == "3600"
