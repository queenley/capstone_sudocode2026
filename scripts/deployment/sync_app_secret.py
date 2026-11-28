"""Copy the shop's own settings from .env into the EKS app secret (AWS Secrets Manager), by name.

The app secret (telesales-production/app, infra/kubernetes/overlays/aws-production/secrets.yaml) is filled by hand.
This copies only the keys in KEYS, never anything else in .env: .env also holds a laptop's settings that must not
reach production (ZALO_WEBHOOK_INSECURE, a local POSTGRES_PASSWORD, EVAL_DATABASE_URL, DEMO_CUSTOMER_PASSWORD...).
Keys already in the secret and not named here are kept. Values are never printed.

    python scripts/deployment/sync_app_secret.py            # what would change, by name
    python scripts/deployment/sync_app_secret.py --apply    # write it

The pods read the secret when they start: after --apply, run the Deploy EKS workflow, or force External Secrets
to sync and restart the deployments (docs/deployment/eks-deploy.md, section 2.4).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The keys production needs from .env, and why.
KEYS = {
    # Bank transfer payments: the checkout's VietQR and the assistant's (docs/channels.md, section 4).
    "BANK_BIN": "payments",
    "BANK_NAME": "payments",
    "BANK_ACCOUNT_NO": "payments",
    "BANK_ACCOUNT_NAME": "payments",
    # Call-backs on Google Calendar (apps/ai-agent-service/src/ai_agent_service/runtime/google_calendar.py).
    "GOOGLE_CALENDAR_ID": "calendar",
    "GOOGLE_CALENDAR_CREDENTIALS_JSON": "calendar",
    "GOOGLE_CALENDAR_SLOT_MINUTES": "calendar",
    "GOOGLE_CALENDAR_REMINDERS": "calendar",
    "GOOGLE_CALENDAR_ATTENDEES": "calendar",
    "GOOGLE_CALENDAR_SUBJECT": "calendar",
}


def dotenv(path: Path) -> dict[str, str]:
    """The non-empty values of *path*, as python-dotenv reads them."""
    from dotenv import dotenv_values

    return {key: value for key, value in dotenv_values(path).items() if value}


def aws(*args: str) -> str:
    done = subprocess.run(["aws", *args], capture_output=True, text=True,
                          env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    if done.returncode:
        sys.exit(f"aws {args[1] if len(args) > 1 else ''} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--secret-id", default="telesales-production/app")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-southeast-1"))
    parser.add_argument("--apply", action="store_true", help="write the secret; without it, only say what would change")
    args = parser.parse_args()

    env = dotenv(Path(args.env_file))
    wanted = {key: env[key] for key in KEYS if key in env}
    if "GOOGLE_CALENDAR_CREDENTIALS_JSON" in wanted:
        credentials = json.loads(wanted["GOOGLE_CALENDAR_CREDENTIALS_JSON"])
        if credentials.get("type") != "service_account":
            sys.exit("GOOGLE_CALENDAR_CREDENTIALS_JSON is not a service account key")
    secret = json.loads(aws("--region", args.region, "secretsmanager", "get-secret-value", "--secret-id",
                            args.secret_id, "--query", "SecretString", "--output", "text"))
    added = sorted(key for key in wanted if key not in secret)
    changed = sorted(key for key in wanted if key in secret and secret[key] != wanted[key])
    missing = sorted(key for key in KEYS if key not in env and key not in secret)
    print(f"{args.secret_id}: {len(secret)} keys")
    print("  add:      ", added or "-")
    print("  change:   ", changed or "-")
    print("  unchanged:", sorted(set(wanted) - set(added) - set(changed)) or "-")
    print("  not in .env, not in the secret:", missing or "-")
    if not (added or changed):
        return
    if not args.apply:
        print("Dry run: nothing written. Add --apply to write.")
        return
    merged = {**secret, **wanted}
    handle, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(merged, file)
        aws("--region", args.region, "secretsmanager", "put-secret-value", "--secret-id", args.secret_id,
            "--secret-string", "file://" + path)
    finally:
        os.remove(path)
    after = json.loads(aws("--region", args.region, "secretsmanager", "get-secret-value", "--secret-id",
                           args.secret_id, "--query", "SecretString", "--output", "text"))
    lost = sorted(set(secret) - set(after))
    ok = all(after.get(key) == value for key, value in wanted.items())
    print(f"Written: {len(after)} keys; lost: {lost or '-'}; values match .env: {ok}")
    if lost or not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
