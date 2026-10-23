"""Chat with the shop as a Zalo user, without a Zalo Official Account.

    python scripts/dev/zalo_simulator.py "Máy lọc không khí AirPure X giá bao nhiêu?"
    python scripts/dev/zalo_simulator.py --user 9000000001 "Phòng 25m2 dùng được không?"
    python scripts/dev/zalo_simulator.py --interactive

Each message is posted to the webhook exactly as Zalo would (``user_send_text``,
signed with ``ZALO_APP_ID`` and ``ZALO_OA_SECRET_KEY`` from ``.env`` when they
are set; otherwise the agent must run with ``ZALO_WEBHOOK_INSECURE=1``). The
agent's reply is read back from the Zalo message log (staff endpoint, with
``AGENT_TOKEN`` from ``.env``). With no Zalo access token configured the reply
is logged as ``not_sent`` instead of being delivered, which is what this tool
shows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def env() -> dict[str, str]:
    values = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    values.update({k: v for k, v in os.environ.items() if k.startswith(("ZALO_", "AGENT_TOKEN", "GATEWAY_URL"))})
    return values


def request(url: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def send(base: str, config: dict[str, str], user: str, text: str, token: str, wait: int) -> None:
    msg_id = hashlib.sha1(f"{user}{text}{time.time()}".encode()).hexdigest()
    event = {
        "app_id": config.get("ZALO_APP_ID", "simulator"),
        "event_name": "user_send_text",
        "timestamp": str(int(time.time() * 1000)),
        "sender": {"id": user},
        "recipient": {"id": config.get("ZALO_OA_ID", "simulator-oa")},
        "message": {"text": text, "msg_id": msg_id},
    }
    body = json.dumps(event, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.get("ZALO_APP_ID") and config.get("ZALO_OA_SECRET_KEY"):
        mac = hashlib.sha256((config["ZALO_APP_ID"] + body.decode("utf-8") + event["timestamp"] + config["ZALO_OA_SECRET_KEY"]).encode("utf-8"))
        headers["X-ZEvent-Signature"] = "mac=" + mac.hexdigest()
    status, answer = request(f"{base}/api/channels/zalo/webhook", body, headers)
    print(f"\n👤 Bạn: {text}")
    if status != 200:
        print(f"   webhook refused ({status}): {answer}")
        return
    # The reply arrives in the log once the agent has answered (a few seconds).
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        status, listing = request(f"{base}/api/channels/zalo/messages?user_id={user}&limit=20",
                                  headers={"Authorization": f"Bearer {token}"})
        if status != 200:
            print(f"   cannot read the message log ({status}): {listing}")
            return
        rows = json.loads(listing)
        incoming = next((r for r in rows if r.get("zalo_msg_id") == msg_id), None)
        if incoming is None:
            continue
        replies = [r for r in rows if r["direction"] == "out" and r["id"] > incoming["id"]]
        if replies:
            for reply in replies:
                print(f"🤖 Shop ({reply['status']}): {reply['text']}")
            return
        if incoming["status"] not in ("received", "answered"):
            print(f"   {incoming['status']}: {incoming.get('error') or ''}")
            return
        if incoming["status"] == "answered":
            print("   (a consultant has this conversation: their reply comes from the console)")
            return
    print("   no reply yet; check `docker compose logs ai-agent-service`")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("message", nargs="*", help="What the Zalo user says")
    parser.add_argument("--user", default="9000000001", help="The simulated Zalo user id")
    parser.add_argument("--interactive", action="store_true", help="Keep chatting until an empty line")
    parser.add_argument("--wait", type=int, default=90, help="Seconds to wait for each reply")
    args = parser.parse_args()
    config = env()
    base = config.get("GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
    token = config.get("AGENT_TOKEN") or "local-agent-change-me"
    if args.message:
        send(base, config, args.user, " ".join(args.message), token, args.wait)
    if args.interactive or not args.message:
        while True:
            try:
                text = input("\nNhắn (Enter để thoát): ").strip()
            except EOFError:
                break
            if not text:
                break
            send(base, config, args.user, text, token, args.wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
