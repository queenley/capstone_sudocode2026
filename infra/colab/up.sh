#!/bin/bash
# Bring up ASR + TTS on a Colab GPU runtime and point the local agent at it.
# Run from the repository root:  bash infra/colab/up.sh  [voice] [asr-model]
#   voice     the agent's TTS (default "remote:vieneu:Mỹ Duyên"; "remote:zerotts:maichi", ...)
#   asr-model the agent's ASR on the GPU (default phowhisper-large)
# Needs the Colab CLI signed in once (see docs/deployment/colab-gpu.md). Writes ASR_URL, ASR_API_KEY, TTS_URL,
# TTS_API_KEY and VOICE_TTS into .env (the key is never printed) and restarts ai-agent-service.
set -euo pipefail
VOICE="${1:-remote:vieneu:Mỹ Duyên}"; ASR_MODEL="${2:-phowhisper-large}"
SESSION="${COLAB_SESSION:-voice}"; GPU="${COLAB_GPU:-T4}"
C="${COLAB_CLI:-$HOME/.local/bin/colab}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; STATE="${XDG_CACHE_HOME:-$HOME/.cache}/telesales-colab"
mkdir -p "$STATE"; chmod 700 "$STATE"

echo "== session $SESSION ($GPU)"
if ! (cd ~ && "$C" sessions 2>/dev/null | grep -q "\[$SESSION\]"); then
  for attempt in 1 2 3 4 5 6; do
    (cd ~ && "$C" new -s "$SESSION" --gpu "$GPU" 2>&1 | tail -1)
    (cd ~ && "$C" sessions 2>/dev/null | grep -q "\[$SESSION\]") && break
    echo "   not allocated (a free account has one GPU at a time); retrying in 60 s"; sleep 60
  done
fi

echo "== code"
rm -f "$STATE/bundle.zip"
(cd "$ROOT" && zip -q -r "$STATE/bundle.zip" apps/asr-service/src apps/asr-service/requirements.txt -x '*__pycache__*')
(cd "$ROOT/infra/colab" && zip -q "$STATE/bundle.zip" tts_server.py)
(cd ~ && "$C" upload -s "$SESSION" "$STATE/bundle.zip" /content/bundle.zip >/dev/null)
(cd ~ && "$C" upload -s "$SESSION" "$ROOT/infra/colab/setup.sh" /content/setup.sh >/dev/null)

echo "== install, models, services, tunnels (about 10 minutes the first time)"
(cd ~ && "$C" ssh -s "$SESSION" -- bash /content/setup.sh) | grep -E '^(== |ASR_URL|TTS_URL|onnxruntime)'

echo "== connect the agent"
(cd ~ && "$C" download -s "$SESSION" /content/run/key "$STATE/key" >/dev/null && "$C" download -s "$SESSION" /content/run/urls "$STATE/urls" >/dev/null)
KEY="$(tr -d '\n' < "$STATE/key")"; set -a; . "$STATE/urls"; set +a
for i in $(seq 1 40); do curl -s -m 10 "$ASR_URL/health/ready" | grep -q '"ready":true' && break; sleep 5; done
for engine in vieneu zerotts; do
  curl -s -m 900 -X POST -H "Authorization: Bearer $KEY" "$TTS_URL/v1/load/$engine" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('   TTS', d.get('engine'), d.get('device'), d.get('error') or '')"
done
cd "$ROOT" && python3 - "$ASR_URL" "$TTS_URL" "$KEY" "$VOICE" <<'PY'
import sys
asr, tts, key, voice = sys.argv[1:]
new = {"ASR_URL": asr, "TTS_URL": tts, "ASR_API_KEY": key, "TTS_API_KEY": key, "VOICE_TTS": f'"{voice}"'}
lines = open(".env").read().splitlines(); seen = set(); out = []
for line in lines:
    k = line.split("=", 1)[0].strip()
    if k in new: out.append(f"{k}={new[k]}"); seen.add(k)
    else: out.append(line)
out += [f"{k}={v}" for k, v in new.items() if k not in seen]
open(".env", "w").write("\n".join(out) + "\n")
PY
docker compose up -d ai-agent-service >/dev/null
for i in $(seq 1 60); do docker compose logs --since 2m ai-agent-service 2>&1 | grep -qE 'Voice ready|Voice preparation failed' && break; sleep 5; done
docker compose logs --since 2m ai-agent-service 2>&1 | grep -E 'Voice ready|Voice preparation failed' | tail -1
docker compose exec -T ai-agent-service python -c '
import os, json, sys, urllib.request
r = urllib.request.Request("http://localhost:8400/api/developer/voice", data=json.dumps({"asr": sys.argv[1]}).encode(),
    method="POST", headers={"Authorization": "Bearer " + os.environ["DEVELOPER_TOKEN"], "Content-Type": "application/json"})
d = json.load(urllib.request.urlopen(r)); print("== agent:", d["asr"], "|", d["tts"])' "$ASR_MODEL"
