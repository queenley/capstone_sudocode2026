"""A local Zalo platform: chat with the shop as Zalo users, without an Official Account.

    python scripts/dev/zalo_mock.py                 # http://127.0.0.1:8090, opens the browser
    python scripts/dev/zalo_mock.py --port 8091 --no-browser

It plays both parts Zalo plays for the shop's OA, in their formats
(``apps/ai-agent-service/src/ai_agent_service/runtime/zalo.py``):

- **the users' side**: a chat page where you are any Zalo user (the CRM's
  customers with a ``zalo_id``, or new ones). Each message is posted to the
  shop's webhook as Zalo posts it (``user_send_text``, ``user_send_image``,
  ``user_send_sticker``, ``follow``), signed ``X-ZEvent-Signature: mac=sha256(
  app_id + body + timestamp + OA secret key)``;
- **the platform's side**: Zalo's OA API, which the shop calls to answer,
  ``POST /v3.0/oa/message/cs`` (``access_token`` header), and its OAuth,
  ``POST /v4/oa/access_token`` (refresh a token). Replies appear in the chat as
  they arrive; refused ones show Zalo's error.

The shop uses this platform instead of Zalo's when ``.env`` points it here
(the agent runs in Docker, so it reaches this machine as ``host.docker.internal``)::

    ZALO_APP_ID=mock-app
    ZALO_OA_ID=mock-oa
    ZALO_OA_SECRET_KEY=mock-oa-secret
    ZALO_ACCESS_TOKEN=mock-access-token
    ZALO_OPENAPI_URL=http://host.docker.internal:8090
    ZALO_OAUTH_URL=http://host.docker.internal:8090
    ZALO_WEBHOOK_INSECURE=0

then ``docker compose up -d ai-agent-service``. The keys are read from the same
``.env``, so both sides agree; ``--check`` prints what is missing.

What it checks, as Zalo does: the access token (error -216), the message shape
and length (-201, at most 2000 characters), that the recipient is a user of
this platform (-213) who wrote to the OA in the last 7 days (-230; the window
in which an OA may answer). Error codes follow Zalo's documentation; the
messages are this mock's. Standard library only; state lives in memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRM = ROOT / "apps/ai-agent-service/data/btc/catalog"
#: An OA may answer a user for this long after the user's last message.
REPLY_WINDOW = 7 * 24 * 3600
MAX_TEXT = 2000
DEFAULTS = {"ZALO_APP_ID": "mock-app", "ZALO_OA_ID": "mock-oa", "ZALO_OA_SECRET_KEY": "mock-oa-secret",
            "ZALO_ACCESS_TOKEN": "mock-access-token"}


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    values.update({k: v for k, v in os.environ.items() if k.startswith("ZALO_") or k == "GATEWAY_URL"})
    return values


def sign(app_id: str, body: str, timestamp: str, secret: str) -> str:
    return "mac=" + hashlib.sha256((app_id + body + timestamp + secret).encode("utf-8")).hexdigest()


# ── the platform's state ──────────────────────────────────────────────────


class Platform:
    """Users, their messages with the OA, the tokens the OA holds, and who is watching."""

    def __init__(self, config: dict[str, str], webhook: str) -> None:
        self.config, self.webhook = config, webhook
        self.lock = threading.Lock()
        self.users: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.tokens = {config["ZALO_ACCESS_TOKEN"]}
        self.refresh = {config.get("ZALO_REFRESH_TOKEN") or ""} - {""}
        self.watchers: list[queue.Queue] = []
        for name in ("crm_seed.json", "crm_seed_synthetic.json"):
            path = CRM / name
            if path.is_file():
                for c in json.loads(path.read_text(encoding="utf-8"))["customers"]:
                    if c.get("zalo_id"):
                        self.add_user(c["zalo_id"], f"{c['honorific']} {c['name']} ({c['customer_id']})")
        self.add_user("9000000001", "Khách mới (chưa có trong CRM)")

    def add_user(self, user_id: str, name: str) -> dict:
        with self.lock:
            user = self.users.setdefault(user_id, {"id": user_id, "name": name, "last_message_at": 0.0})
        return user

    def note(self, user_id: str, direction: str, text: str, **extra) -> dict:
        """Record a message and show it to every open page."""
        message = {"id": len(self.messages) + 1, "user_id": user_id, "direction": direction, "text": text,
                   "at": time.strftime("%H:%M:%S"), **extra}
        with self.lock:
            self.messages.append(message)
            watchers = list(self.watchers)
        for watcher in watchers:
            watcher.put(message)
        arrow = {"in": "👤 →", "out": "🤖 ←", "system": "  ⚠"}[direction]
        print(f"{message['at']} {arrow} {user_id}: {text}" + (f"  [{extra['status']}]" if extra.get("status") else ""),
              flush=True)
        return message

    # ── the users' side: events to the shop's webhook ──

    def event(self, user_id: str, kind: str, text: str = "") -> dict:
        """Post one Zalo event for *user_id* to the webhook; returns what the shop answered."""
        config = self.config
        timestamp = str(int(time.time() * 1000))
        msg_id = secrets.token_hex(16)
        base = {"app_id": config["ZALO_APP_ID"], "user_id_by_app": user_id, "timestamp": timestamp}
        if kind == "follow":
            event = {**base, "event_name": "follow", "oa_id": config["ZALO_OA_ID"], "source": "oa_profile",
                     "follower": {"id": user_id}}
            shown = "[theo dõi OA]"
        else:
            message: dict = {"msg_id": msg_id, "text": text}
            if kind == "image":
                url = "https://example.invalid/mock-image.jpg"
                message = {"msg_id": msg_id, "text": text,
                           "attachments": [{"type": "image", "payload": {"thumbnail": url, "url": url}}]}
            elif kind == "sticker":
                message = {"msg_id": msg_id, "attachments": [
                    {"type": "sticker", "payload": {"id": "mock-sticker", "url": "https://example.invalid/sticker.png"}}]}
            event = {**base, "event_name": {"text": "user_send_text", "image": "user_send_image",
                                            "sticker": "user_send_sticker"}[kind],
                     "sender": {"id": user_id}, "recipient": {"id": config["ZALO_OA_ID"]}, "message": message}
            shown = text if kind == "text" else f"[{'ảnh' if kind == 'image' else 'sticker'}] {text}".strip()
        body = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        headers = {"Content-Type": "application/json",
                   "X-ZEvent-Signature": sign(config["ZALO_APP_ID"], body, timestamp, config["ZALO_OA_SECRET_KEY"])}
        with self.lock:
            self.users[user_id]["last_message_at"] = time.time()
        request = urllib.request.Request(self.webhook, data=body.encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, answer = response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status, answer = error.code, error.read().decode("utf-8")
        except OSError as error:
            status, answer = 0, f"{type(error).__name__}: {error}"
        webhook = "200" if status == 200 else f"{status or 'không kết nối được'} {answer[:200]}"
        return self.note(user_id, "in", shown, status=f"webhook {webhook}", msg_id=msg_id, event=event)

    # ── the platform's side: the OA API the shop calls ──

    def send(self, token: str, payload: dict) -> dict:
        """``POST /v3.0/oa/message/cs``: Zalo's answer to the shop."""
        if token not in self.tokens:
            return self._refuse(-216, "Access token is invalid", payload)
        recipient = str(((payload or {}).get("recipient") or {}).get("user_id") or "")
        text = ((payload or {}).get("message") or {}).get("text")
        if not recipient or not isinstance(text, str) or not text.strip():
            return self._refuse(-201, "Parameters are invalid: recipient.user_id and message.text are required", payload)
        if len(text) > MAX_TEXT:
            return self._refuse(-201, f"Text is longer than {MAX_TEXT} characters", payload)
        with self.lock:
            user = self.users.get(recipient)
        if user is None:
            return self._refuse(-213, "User has not followed or interacted with the OA", payload)
        if time.time() - user["last_message_at"] > REPLY_WINDOW:
            return self._refuse(-230, "User has not interacted with the OA in the last 7 days", payload)
        message_id = secrets.token_hex(16)
        self.note(recipient, "out", text, status="đã gửi", message_id=message_id)
        return {"error": 0, "message": "Success", "data": {"message_id": message_id, "user_id": recipient}}

    def _refuse(self, code: int, reason: str, payload: dict) -> dict:
        user_id = str(((payload or {}).get("recipient") or {}).get("user_id") or "?")
        self.note(user_id, "system", f"Zalo từ chối tin của shop: {code} {reason}")
        return {"error": code, "message": reason}

    def oauth(self, secret_key: str, form: dict[str, str]) -> tuple[int, dict]:
        """``POST /v4/oa/access_token``: a new access token for a refresh token, which is used up."""
        app_secret = self.config.get("ZALO_APP_SECRET", "")
        if not app_secret or secret_key != app_secret or form.get("app_id") != self.config["ZALO_APP_ID"]:
            return 400, {"error": -14014, "error_name": "Invalid app secret or app id"}
        if form.get("grant_type") != "refresh_token" or form.get("refresh_token") not in self.refresh:
            return 400, {"error": -14002, "error_name": "Invalid refresh token"}
        access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.lock:
            self.refresh.discard(form["refresh_token"])
            self.refresh.add(refresh)
            self.tokens.add(access)
        self.note("OA", "system", "Shop đã làm mới access token")
        return 200, {"access_token": access, "refresh_token": refresh, "expires_in": "90000"}


# ── HTTP ──────────────────────────────────────────────────────────────────


def handler(platform: Platform) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # the platform prints its own log
            pass

        def reply(self, status: int, body: object, content_type: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def do_GET(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            if path == "/":
                self.reply(200, PAGE.encode("utf-8"), "text/html")
            elif path == "/api/state":
                with platform.lock:
                    self.reply(200, {"users": list(platform.users.values()), "messages": platform.messages,
                                     "webhook": platform.webhook})
            elif path == "/api/stream":
                self.stream()
            else:
                self.reply(404, {"error": "not found"})

        def stream(self) -> None:
            """Server-sent events: every new message, to this page."""
            watcher: queue.Queue = queue.Queue()
            with platform.lock:
                platform.watchers.append(watcher)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    try:
                        message = watcher.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(message, ensure_ascii=False)}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                with platform.lock:
                    platform.watchers.remove(watcher)

        def do_POST(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            raw = self.body()
            if path == "/v3.0/oa/message/cs":
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    payload = {}
                self.reply(200, platform.send(self.headers.get("access_token", ""), payload))
            elif path == "/v4/oa/access_token":
                form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()}
                status, answer = platform.oauth(self.headers.get("secret_key", ""), form)
                self.reply(status, answer)
            elif path == "/api/send":
                data = json.loads(raw or b"{}")
                user_id, kind = str(data.get("user_id") or ""), data.get("kind", "text")
                text = str(data.get("text") or "").strip()
                if user_id not in platform.users or kind not in ("text", "image", "sticker", "follow") \
                        or (kind == "text" and not text):
                    self.reply(400, {"error": "user_id, kind and (for text) text are required"})
                    return
                self.reply(200, platform.event(user_id, kind, text))
            elif path == "/api/users":
                data = json.loads(raw or b"{}")
                user_id = str(data.get("id") or "").strip() or str(9000000000 + secrets.randbelow(999999))
                self.reply(200, platform.add_user(user_id, str(data.get("name") or "").strip() or f"Người dùng {user_id}"))
            else:
                self.reply(404, {"error": "not found"})

    return Handler


def check(config: dict[str, str], port: int) -> list[str]:
    """What ``.env`` lacks for the shop to talk to this platform."""
    expected = f"http://host.docker.internal:{port}"
    problems = [f"{key}= (not set; this mock uses {value!r}, set the same in .env)"
                for key, value in DEFAULTS.items() if not config.get(key)]
    for key in ("ZALO_OPENAPI_URL", "ZALO_OAUTH_URL"):
        if config.get(key, "").rstrip("/") != expected:
            problems.append(f"{key}={expected}  (now {config.get(key) or 'unset'}: replies would go to Zalo, not here)")
    if config.get("ZALO_WEBHOOK_INSECURE") == "1":
        problems.append("ZALO_WEBHOOK_INSECURE=0  (this mock signs every event; keep the check on)")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--webhook", help="The shop's webhook (default: GATEWAY_URL or http://127.0.0.1:8000, "
                                          "+ /api/channels/zalo/webhook)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Print what .env lacks, then exit")
    args = parser.parse_args()

    config = load_env()
    problems = check(config, args.port)
    if args.check or problems:
        print("Cấu hình .env cho mock Zalo:" if problems else "Cấu hình .env đã khớp với mock.")
        for problem in problems:
            print("  " + problem)
        if problems:
            print("Sửa .env rồi chạy lại `docker compose up -d ai-agent-service` để agent đọc cấu hình mới.")
        if args.check:
            return 1 if problems else 0
    config = {**DEFAULTS, **{k: v for k, v in config.items() if v}}
    gateway = config.get("GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
    platform = Platform(config, args.webhook or gateway + "/api/channels/zalo/webhook")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(platform))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}"
    print(f"Mock Zalo: {url}  → webhook {platform.webhook}  ({len(platform.users)} users). Ctrl+C để dừng.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mock Zalo</title>
<style>
:root{--blue:#0068ff;--bg:#f0f2f5;--panel:#fff;--line:#e4e6eb;--muted:#65676b;--me:#e5efff;--shop:#fff;--warn:#fff4e5}
*{box-sizing:border-box}body{margin:0;font:15px/1.4 system-ui,sans-serif;background:var(--bg);color:#081c36;height:100vh;display:flex}
aside{width:300px;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column}
aside h1{margin:0;padding:14px 16px;font-size:18px;color:var(--blue);border-bottom:1px solid var(--line)}
#users{flex:1;overflow:auto}.user{padding:10px 16px;cursor:pointer;border-bottom:1px solid var(--line)}
.user:hover{background:#f5f6f7}.user.on{background:var(--me)}.user small{display:block;color:var(--muted)}
#add{display:flex;gap:6px;padding:10px;border-top:1px solid var(--line)}#add input{flex:1;min-width:0}
main{flex:1;display:flex;flex-direction:column;min-width:0}
header{background:var(--panel);padding:12px 16px;border-bottom:1px solid var(--line)}header small{color:var(--muted);display:block}
#chat{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
.msg{max-width:70%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}
.in{align-self:flex-end;background:var(--me)}.out{align-self:flex-start;background:var(--shop);border:1px solid var(--line)}
.system{align-self:center;background:var(--warn);font-size:13px}.msg small{display:block;color:var(--muted);font-size:12px;margin-top:2px}
form{display:flex;gap:6px;padding:10px;background:var(--panel);border-top:1px solid var(--line)}
input{padding:9px 12px;border:1px solid var(--line);border-radius:18px;font:inherit}#text{flex:1}
button{border:0;border-radius:18px;padding:8px 12px;background:#e4e6eb;cursor:pointer;font:inherit}
button.primary{background:var(--blue);color:#fff}
@media (max-width:700px){body{flex-direction:column}aside{width:auto;max-height:35vh}}
</style></head><body>
<aside><h1>Mock Zalo</h1><div id="users"></div>
<div id="add"><input id="newname" placeholder="Tên người dùng mới"><button id="adduser">Thêm</button></div></aside>
<main><header><b id="who">Chọn một người dùng</b><small id="hint"></small></header>
<div id="chat"></div>
<form id="form"><button type="button" data-kind="follow" title="Theo dõi OA">➕</button>
<button type="button" data-kind="image" title="Gửi ảnh">📷</button><button type="button" data-kind="sticker" title="Gửi sticker">😀</button>
<input id="text" placeholder="Nhập tin nhắn gửi shop" autocomplete="off"><button class="primary">Gửi</button></form></main>
<script>
let state = {users: [], messages: []}, current = null;
const $ = (id) => document.getElementById(id);
function renderUsers() {
  $("users").innerHTML = "";
  for (const u of state.users) {
    const el = document.createElement("div");
    el.className = "user" + (u.id === current ? " on" : "");
    el.innerHTML = "<b></b><small></small>";
    el.querySelector("b").textContent = u.name;
    el.querySelector("small").textContent = "zalo id: " + u.id;
    el.onclick = () => { current = u.id; renderUsers(); renderChat(); $("text").focus(); };
    $("users").appendChild(el);
  }
}
function renderChat() {
  const user = state.users.find((u) => u.id === current);
  $("who").textContent = user ? user.name : "Chọn một người dùng";
  $("hint").textContent = user ? "zalo id " + user.id + " · webhook " + state.webhook : "";
  $("chat").innerHTML = "";
  for (const m of state.messages.filter((m) => m.user_id === current || (m.user_id === "OA" && current))) {
    const el = document.createElement("div");
    el.className = "msg " + m.direction;
    el.textContent = m.text;
    const meta = document.createElement("small");
    meta.textContent = m.at + (m.status ? " · " + m.status : "");
    el.appendChild(meta);
    $("chat").appendChild(el);
  }
  $("chat").scrollTop = $("chat").scrollHeight;
}
async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  return r.json();
}
async function send(kind, text) {
  if (!current) { alert("Chọn một người dùng trước"); return; }
  await post("/api/send", {user_id: current, kind, text});
}
$("form").onsubmit = (e) => { e.preventDefault(); const t = $("text").value.trim(); if (t) { $("text").value = ""; send("text", t); } };
document.querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => send(b.dataset.kind, ""));
$("adduser").onclick = async () => {
  const u = await post("/api/users", {name: $("newname").value});
  $("newname").value = ""; state.users.push(u); current = u.id; renderUsers(); renderChat();
};
fetch("/api/state").then((r) => r.json()).then((s) => { state = s; renderUsers(); renderChat(); });
const events = new EventSource("/api/stream");
events.onmessage = (e) => { state.messages.push(JSON.parse(e.data)); renderChat(); };
</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
