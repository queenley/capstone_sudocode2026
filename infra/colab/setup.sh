#!/bin/bash
# Runs ON the Colab VM (infra/colab/up.sh uploads it with /content/bundle.zip): installs, downloads the models, starts
# asr-service :8500 and tts_server :8600 detached with one key, and opens a Cloudflare quick tunnel to each.
# Logs, the key and the two URLs are in /content/run/.
set -u
mkdir -p /content/run /content/app /content/models; cd /content
unzip -q -o /content/bundle.zip -d /content/app
echo "== pip" ; pip -q install fastapi==0.142.2 'uvicorn[standard]==0.54.0' soxr==1.0.0 sherpa-onnx==1.13.8 ctranslate2==4.8.2 \
  faster-whisper==1.2.1 huggingface_hub zerotts vieneu nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*' > /content/run/pip.log 2>&1
pip -q uninstall -y onnxruntime >> /content/run/pip.log 2>&1; pip -q install onnxruntime-gpu >> /content/run/pip.log 2>&1
python3 -c "import onnxruntime as o; print('onnxruntime', o.__version__, o.get_available_providers())"
echo "== models"
python3 - <<'PY'
import os, shutil
from huggingface_hub import snapshot_download, hf_hub_download
M='/content/models'
for repo, folder in [('kiendt/PhoWhisper-large-ct2','phowhisper-large'), ('mad1999/pho-whisper-medium-ct2','phowhisper-medium'), ('deepdml/faster-whisper-large-v3-turbo-ct2','whisper-large-v3-turbo')]:
    snapshot_download(repo, local_dir=f'{M}/{folder}')
    if not os.path.exists(f'{M}/{folder}/tokenizer.json'):
        shutil.copy(hf_hub_download('openai/whisper-large-v2','tokenizer.json'), f'{M}/{folder}/tokenizer.json')
    print(folder, 'ok', flush=True)
snapshot_download('zeroweight-ai/ZeroTTS', local_dir='/content/zerotts'); print('zerotts ok')
PY
[ -f /content/models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09/tokens.txt ] || (cd /content/app/apps/asr-service/src && ASR_MODELS_DIR=/content/models python3 -m asr_service.fetch --model zipformer-30m)
echo "== start"
LIBS=$(python3 -c "import nvidia.cublas.lib as a, nvidia.cudnn.lib as b; print(a.__path__[0]+':'+b.__path__[0])")
[ -f /content/run/key ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > /content/run/key
KEY=$(cat /content/run/key)
fuser -k 8500/tcp 8600/tcp 2>/dev/null; pkill -f cloudflared 2>/dev/null; sleep 2
export LD_LIBRARY_PATH="$LIBS:${LD_LIBRARY_PATH:-}" ASR_DEVICE=cuda ASR_MODELS_DIR=/content/models ASR_FETCH=0 \
  ASR_API_KEY="$KEY" TTS_API_KEY="$KEY" ASR_PRELOAD=phowhisper-large,zipformer-30m
setsid nohup uvicorn asr_service.main:app --app-dir /content/app/apps/asr-service/src --host 0.0.0.0 --port 8500 --no-access-log > /content/run/asr.log 2>&1 < /dev/null &
setsid nohup uvicorn tts_server:app --app-dir /content/app --host 0.0.0.0 --port 8600 --no-access-log > /content/run/tts.log 2>&1 < /dev/null &
[ -x /content/cloudflared ] || (wget -q -O /content/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /content/cloudflared)
for p in 8500 8600; do setsid nohup /content/cloudflared tunnel --url http://localhost:$p --no-autoupdate > /content/run/tunnel-$p.log 2>&1 < /dev/null & done
for i in $(seq 1 60); do grep -qo 'https://[a-z0-9-]*\.trycloudflare\.com' /content/run/tunnel-8500.log /content/run/tunnel-8600.log 2>/dev/null && [ $(grep -ho 'https://[a-z0-9-]*\.trycloudflare\.com' /content/run/tunnel-*.log | sort -u | wc -l) -ge 2 ] && break; sleep 2; done
echo "ASR_URL=$(grep -ho 'https://[a-z0-9-]*\.trycloudflare\.com' /content/run/tunnel-8500.log | head -1)" > /content/run/urls
echo "TTS_URL=$(grep -ho 'https://[a-z0-9-]*\.trycloudflare\.com' /content/run/tunnel-8600.log | head -1)" >> /content/run/urls
cat /content/run/urls; echo "== done"
