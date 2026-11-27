#!/bin/bash
# Point the agent back at this machine (ASR in the asr-service container, an API voice) and stop the Colab session.
# Run from the repository root:  bash infra/colab/down.sh  [voice]   (default openai:coral)
set -euo pipefail
VOICE="${1:-openai:coral}"; SESSION="${COLAB_SESSION:-voice}"; C="${COLAB_CLI:-$HOME/.local/bin/colab}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" && python3 - "$VOICE" <<'PY'
import sys
new = {"ASR_URL": "http://asr-service:8500", "ASR_API_KEY": "", "TTS_URL": "", "TTS_API_KEY": "", "VOICE_TTS": sys.argv[1]}
lines = open(".env").read().splitlines()
out = [f"{l.split('=', 1)[0]}={new[l.split('=', 1)[0]]}" if l.split("=", 1)[0] in new else l for l in lines]
open(".env", "w").write("\n".join(out) + "\n")
PY
docker compose up -d ai-agent-service >/dev/null && echo "agent back on local ASR, voice $VOICE"
(cd ~ && "$C" stop -s "$SESSION" 2>&1 | tail -1) || true
