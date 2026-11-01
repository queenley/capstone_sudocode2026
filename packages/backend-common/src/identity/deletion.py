"""Deliver an outbox deletion to the agent owner; no customer text or contact data is sent."""
import hashlib
import hmac
import json
import os

import httpx


def signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), b"customer-deletion:" + body, hashlib.sha256).hexdigest()


def deliver(event, settings):
    base = os.environ.get("AI_AGENT_SERVICE_URL", "http://ai-agent-service:8400").rstrip("/")
    conversations = event["payload"].get("conversation_ids", [])
    for start in range(0, max(1, len(conversations)), 5000):
        payload = {"request_id": event["id"], "customer_id": event["payload"]["customer_id"],
                   "conversation_ids": conversations[start:start + 5000]}
        body = json.dumps(payload, sort_keys=True).encode()
        response = httpx.post(base + "/internal/customer-deletions", content=body,
                              headers={"Content-Type": "application/json", "X-Deletion-Signature": signature(settings.secret, body)},
                              timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
        response.raise_for_status()
        if response.json().get("status") != "deleted":
            raise RuntimeError("The agent has not completed the deletion")
