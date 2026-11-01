# asr-service

Nhận dạng giọng nói tiếng Việt (ASR) cho cuộc gọi web và hotline, tách khỏi AI agent để có thể chạy trên một máy riêng: CPU của máy local hôm nay, GPU thuê sau này. Agent vẫn giữ phần nghe của cuộc gọi (VAD, Smart Turn quyết định khi nào khách nói xong) và gửi từng câu sang đây.

```
ai-agent-service ── POST /v1/transcribe (một câu, PCM 16 kHz) ──► asr-service :8500 (CPU / GPU)
                 ── WS   /v1/stream    (realtime: partial + final) ─►
```

Mặc định: Zipformer 30M int8, greedy search. Các adapter khác chỉ dùng khi được chọn rõ. Code: `src/asr_service/engines.py` (bộ nhận dạng), `fetch.py` (tải model), `main.py` (API).

## Chạy

Trong Docker Compose service này chạy sẵn (`asr-service`), dùng chung volume `voice-models` với agent nên model đã tải không phải tải lại. Agent gọi nó qua `ASR_URL=http://asr-service:8500`.

Không dùng Docker:

```powershell
pip install -r apps/asr-service/requirements.txt
$env:ASR_MODELS_DIR="apps/ai-agent-service/models/voice"
uvicorn asr_service.main:app --app-dir apps/asr-service/src --port 8500
```

Khi không đặt `ASR_URL`, agent chạy cùng các model này ngay trong tiến trình của nó (cần cài `requirements.txt` ở trên).

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ASR_DEVICE` | `cpu` | `cpu` hoặc `cuda` |
| `ASR_PRELOAD` | `zipformer-30m` | Model nạp sẵn khi khởi động (danh sách, phân cách bằng dấu phẩy) |
| `ASR_API_KEY` | trống | Bắt buộc `Authorization: Bearer <key>` (WebSocket: thêm `?token=`). **Luôn đặt khi service truy cập được từ Internet** |
| `ASR_MODELS_DIR` | `/models` | Thư mục model |
| `ASR_THREADS` | `4` | Số luồng CPU mỗi model |
| `ASR_FETCH` | `1` | `0`: không tự tải model khi khởi động |
| `ASR_FETCH_MODELS` | `zipformer-30m` | Chỉ tải nhóm model được chỉ định, mặc định duy nhất Zipformer greedy |
| `ASR_FETCH_TURBO` | `0` | `1`: tải thêm Whisper large-v3-turbo (1,6 GB, nên dùng với GPU) |
| `ASR_MAX_SECONDS` | `120` | Độ dài tối đa của một câu |

## API

- `GET /health`, `GET /health/ready` (200 khi các model trong `ASR_PRELOAD` đã nạp)
- `GET /v1/models`: model có trên máy và đã nạp hay chưa
- `POST /v1/models/{name}/load`
- `POST /v1/transcribe?model=zipformer-30m&hotwords=AirPure,Xiaomi`, body là PCM float32 little-endian mono 16 kHz (`application/octet-stream`) → `{text, model, seconds, audio_seconds, rtf}`
- `WS /v1/stream` (realtime):
  1. Client gửi `{"model": "zipformer-30m", "sample_rate": 48000, "hotwords": [], "partial_ms": 600}`; service trả `{"type": "ready"}`.
  2. Client gửi các khung binary PCM float32 ở `sample_rate` đó; service trả `{"type": "partial", "text"}` khi chữ thay đổi.
  3. Client gửi `{"type": "end"}`; service trả `{"type": "final", "text", ...}` và bắt đầu câu mới. `{"type": "reset"}` bỏ phần đã nghe.

  Các model hiện có là model offline: partial là toàn bộ câu được giải mã lại (rẻ trên GPU). Khi có model streaming thật, giao thức giữ nguyên.

Phía agent: `ai_agent_service.components.voice.asr` (`transcribe()`, `stream()`).

## Lên GPU thuê

```bash
docker build -f apps/asr-service/Dockerfile.gpu -t telesales-asr:gpu .
docker run -d --gpus all -p 8500:8500 \
  -e ASR_API_KEY=<chuỗi ngẫu nhiên dài> -e ASR_PRELOAD=zipformer-30m \
  -e ASR_FETCH_MODELS=zipformer-30m -v asr-models:/models telesales-asr:gpu
```

Rồi trong `.env` của máy chạy agent:

```
ASR_URL=https://<địa chỉ máy GPU>:8500   # nên đặt sau HTTPS (reverse proxy) khi đi qua Internet
ASR_API_KEY=<cùng chuỗi ở trên>
ASR_LOCAL=0                             # không chạy container asr-service trên máy này
```

`docker compose up -d ai-agent-service`. Kiểm tra: `GET /health` của máy GPU báo `"device": "cuda"`, và `rtf` trong kết quả `/v1/transcribe` nhỏ hơn nhiều so với CPU. `Dockerfile.gpu` chưa được chạy thử trên GPU trong dự án này.

## So sánh local và model nghiên cứu

VieGem đã được thêm với ID `viegem`; cần `requirements-research.txt` (Torch/Transformers) ngoài bộ service cơ bản. `zipformer-30m-beam4` là biến thể decoder dùng cùng weights của Zipformer 30M, không phải model tải thêm. Phiên bản greedy cũ vẫn giữ ID `zipformer-30m`. Trong phép so sánh research, PhoWhisper được chuyển từ bản VinAI đã ghim revision sang int8 bằng `--convert-phowhisper`; đường fetch mặc định giữ bản preconverted trên main để không cần Torch trong image gọn. Inference giữ `temperature=0` để tránh sampling fallback không tái lập.

```sh
PYTHONPATH=apps/asr-service/src python -m asr_service.fetch --model zipformer-30m --model phowhisper-small --model viegem --convert-phowhisper
```

`--model` lặp được; khi không chỉ định chỉ tải Zipformer greedy. `ASR_FETCH_MODELS=zipformer-30m,phowhisper-small,viegem` giới hạn nhóm fetch lúc service khởi động; dùng `ASR_FETCH=0` khi đánh giá. Không tự tải trong `engines.load/transcribe`. Folder thiếu weights/tokenizer không được quảng bá là model sẵn sàng.

`GET /v1/models/{name}/artifact` trả source revision, checksum và cấu hình decoder; inference/adapter dùng cùng contract cho web voice và `run_eval.py`. VieGem hỗ trợ tối đa 30 s một utterance trong adapter; runner WAV dài cắt theo waveform tối đa 20 s. Service vẫn giới hạn 120 s/request; model có giới hạn nhỏ hơn trả 422. Giao thức partial hiện giải mã lại prefix, chưa phải native streaming VieGem.

VieGem: CC-BY-NC-SA-4.0 và điều khoản Gemma, chỉ dùng nghiên cứu phi thương mại theo model card. Hướng dẫn đo, không suy diễn SNR/DER/entity gold và các giới hạn: [ASR local](../../docs/evaluation/asr-local.md).

## Neural denoiser tùy chọn

Mặc định vẫn `zipformer-30m` greedy và `denoiser=none`. RNNoise là neural noise suppression, không phải acoustic echo cancellation; giữ AEC và xử lý echo của web như trước.

```sh
# Đã cài requirements.txt; chỉ cần native wheel, không dùng wrapper audiolab/AV.
python -m pip install --no-deps -r apps/asr-service/requirements-denoise.txt
# Docker CPU/GPU: thêm --build-arg INSTALL_DENOISER=1 khi build image ASR.
```

- HTTP: `POST /v1/transcribe?model=zipformer-30m&denoiser=rnnoise`.
- WebSocket: thêm `"denoiser":"rnnoise"` vào frame config. Bỏ trường này thì tắt. Partials dùng offline recognizer nên xử lý lại prefix từ đầu; mỗi prefix/utterance có state lọc mới.
- Agent web: đặt `ASR_DENOISER=rnnoise` trong môi trường ai-agent-service; ASR service phải cài optional wheel. Local in-process cần cài wheel trong venv agent. Không có denoiser/model thì trả lỗi, không tự tải hoặc âm thầm bỏ qua lựa chọn.
- Benchmark: root `run_eval.py --asr-package ... --asr-transcribe --asr-denoiser rnnoise`; `--asr-denoiser none` là đối chứng.

Input/output giữ float32 mono 16kHz và cùng số sample. RNNoise chạy ở 48kHz, hop480, với resample HQ và bù/flush một hop theo ví dụ v0.2 upstream. API trả `seconds` gồm denoise+ASR, `denoise_seconds`, `decoder_seconds`, `preprocessing` (version và hash binary). Model load và chờ queue/network không nằm trong `seconds`; benchmark ghi thêm wall time. RNNoise không nhận transcript, ground truth hoặc vocabulary entity.

Kết quả/giới hạn trên audio người dùng: [so sánh neural denoiser](../../docs/evaluation/neural-denoiser-comparison.md).
