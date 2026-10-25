"""Storefront accounts (src.identity.accounts): register with a code, log in, reset, profile, cart."""

from conftest import conversation, identify

PHONE = "0912345678"


def register(client, phone=PHONE, password="matkhau123", name="Nguyễn Thị Oanh", email=None):
    started = client.post("/api/customer/register/start", json={
        "full_name": name, "phone": phone, "password": password, **({"email": email} if email else {})})
    assert started.status_code == 200, started.text
    body = started.json()
    done = client.post("/api/customer/register/verify",
                       json={"challenge_id": body["challenge_id"], "code": body["development_code"]})
    assert done.status_code == 200, done.text
    return done.json()


def auth(token):
    return {"Authorization": "Bearer " + token}


def test_register_then_login_and_profile(client):
    account = register(client, email="Oanh@Example.com")["account"]
    assert account["full_name"] == "Nguyễn Thị Oanh"
    assert account["phone"] == PHONE and account["email"] == "oanh@example.com" and account["registered"]

    login = client.post("/api/customer/login", json={"phone": "+84912345678", "password": "matkhau123"})
    assert login.status_code == 200, login.text
    token = login.json()["customer_token"]
    assert client.get("/api/customer/me", headers=auth(token)).json()["customer_id"] == account["customer_id"]

    updated = client.patch("/api/customer/me", headers=auth(token), json={"full_name": "Oanh Nguyễn", "email": ""})
    assert updated.json()["full_name"] == "Oanh Nguyễn" and updated.json()["email"] is None

    # The token logs the shopper into the chat as the verified customer.
    c, h = conversation(client, token)
    assert client.get(f"/api/conversations/{c}", headers=h).json()["customer_id"] == account["customer_id"]

    assert client.post("/api/customer/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/customer/me", headers=auth(token)).status_code == 401


def test_registration_needs_the_right_code_and_a_free_phone(client):
    started = client.post("/api/customer/register/start",
                          json={"full_name": "An", "phone": PHONE, "password": "matkhau123"}).json()
    wrong = "000000" if started["development_code"] != "000000" else "111111"
    assert client.post("/api/customer/register/verify",
                       json={"challenge_id": started["challenge_id"], "code": wrong}).status_code == 422
    assert client.post("/api/customer/login", json={"phone": PHONE, "password": "matkhau123"}).status_code == 401
    register(client)
    again = client.post("/api/customer/register/start",
                        json={"full_name": "Khác", "phone": PHONE, "password": "matkhau123"})
    assert again.status_code == 409
    short = client.post("/api/customer/register/start",
                        json={"full_name": "Bình", "phone": "0987654321", "password": "ngan"})
    assert short.status_code == 422


def test_a_shopper_verified_in_chat_keeps_their_customer_when_registering(client):
    c, h = conversation(client)
    chat_token = identify(client, c, h, phone=PHONE)
    chat_customer = client.get("/api/customer/me", headers=auth(chat_token)).json()
    assert not chat_customer["registered"]
    account = register(client)["account"]
    assert account["customer_id"] == chat_customer["customer_id"]


def test_wrong_passwords_lock_the_account(client):
    register(client)
    for _ in range(5):
        assert client.post("/api/customer/login", json={"phone": PHONE, "password": "saimatkhau"}).status_code == 401
    locked = client.post("/api/customer/login", json={"phone": PHONE, "password": "matkhau123"})
    assert locked.status_code == 429
    # An unknown phone answers like a wrong password.
    assert client.post("/api/customer/login", json={"phone": "0999999999", "password": "x"}).status_code == 401


def test_reset_password_ends_other_sessions(client):
    old_token = register(client)["customer_token"]
    started = client.post("/api/customer/password/reset/start", json={"phone": PHONE}).json()
    reset = client.post("/api/customer/password/reset/verify", json={
        "challenge_id": started["challenge_id"], "code": started["development_code"], "password": "matkhaumoi1"})
    assert reset.status_code == 200, reset.text
    assert client.get("/api/customer/me", headers=auth(old_token)).status_code == 401
    assert client.post("/api/customer/login", json={"phone": PHONE, "password": "matkhaumoi1"}).status_code == 200
    assert client.post("/api/customer/password/reset/start", json={"phone": "0999999999"}).status_code == 404


def test_change_password_keeps_this_session(client):
    token = register(client)["customer_token"]
    other = client.post("/api/customer/login", json={"phone": PHONE, "password": "matkhau123"}).json()["customer_token"]
    bad = client.post("/api/customer/password", headers=auth(token),
                      json={"current_password": "sai", "new_password": "matkhaumoi1"})
    assert bad.status_code == 401
    ok = client.post("/api/customer/password", headers=auth(token),
                     json={"current_password": "matkhau123", "new_password": "matkhaumoi1"})
    assert ok.status_code == 200
    assert client.get("/api/customer/me", headers=auth(token)).status_code == 200
    assert client.get("/api/customer/me", headers=auth(other)).status_code == 401


def test_cart_is_kept_per_customer_and_only_holds_sold_codes(client):
    token = register(client)["customer_token"]
    assert client.get("/api/customer/cart", headers=auth(token)).json() == {"items": []}
    saved = client.put("/api/customer/cart", headers=auth(token), json={"items": [
        {"sku": "ASUS-V16-BLACK", "qty": 2}, {"sku": "NO-SUCH-SKU", "qty": 1}]})
    assert saved.json() == {"items": [{"sku": "ASUS-V16-BLACK", "qty": 2}]}
    again = client.post("/api/customer/login", json={"phone": PHONE, "password": "matkhau123"}).json()["customer_token"]
    assert client.get("/api/customer/cart", headers=auth(again)).json()["items"] == [{"sku": "ASUS-V16-BLACK", "qty": 2}]
    other = register(client, phone="0987654321")["customer_token"]
    assert client.get("/api/customer/cart", headers=auth(other)).json() == {"items": []}
    assert client.get("/api/customer/cart").status_code == 401


def test_the_logged_in_shopper_reaches_the_agent_as_their_account(client, agent):
    account = register(client)
    c, h = conversation(client, account["customer_token"])
    assert client.post(f"/api/conversations/{c}/turns", headers=h, json={"message": "giỏ hàng tôi có gì"}).status_code == 200
    assert agent.turns[-1]["account_id"] == account["account"]["customer_id"]
    guest, gh = conversation(client)
    client.post(f"/api/conversations/{guest}/turns", headers=gh,
                json={"message": "giỏ hàng tôi có gì", "cart": [{"sku": "ASUS-V16-BLACK", "qty": 1, "name": "ASUS"}]})
    assert agent.turns[-1]["account_id"] is None
    assert "(Giỏ hàng trên website của khách: ASUS [ASUS-V16-BLACK] x1." in agent.turns[-1]["content"]
