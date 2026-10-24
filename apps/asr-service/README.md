# asr-service

Nhận dạng giọng nói tiếng Việt (ASR) cho cuộc gọi web và hotline, tách khỏi AI agent để có thể chạy trên một máy riêng: CPU của máy local hôm nay, GPU thuê sau này. Agent vẫn giữ phần nghe của cuộc gọi (VAD, Smart Turn quyết định khi nào khách nói xong) và gửi từng câu sang đây.

```
ai-agent-service ── POST /v1/transcribe (một câu, PCM 16 kHz) ──► asr-service :8500 (CPU / GPU)
                 ── WS   /v1/stream    (realtime: partial + final) ─►
```

Model: Zipformer 30M và Zipformer 2025 (sherpa-onnx), PhoWhisper small và Whisper large-v3-turbo (faster-whisper). Code: `src/asr_service/engines.py` (bộ nhận dạng), `fetch.py` (tải model), `main.py` (API).

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
  -e ASR_API_KEY=<chuỗi ngẫu nhiên dài> -e ASR_PRELOAD=phowhisper-small,zipformer-30m \
  -e ASR_FETCH_TURBO=1 -v asr-models:/models telesales-asr:gpu
```

Rồi trong `.env` của máy chạy agent:

```
ASR_URL=https://<địa chỉ máy GPU>:8500   # nên đặt sau HTTPS (reverse proxy) khi đi qua Internet
ASR_API_KEY=<cùng chuỗi ở trên>
ASR_LOCAL=0                             # không chạy container asr-service trên máy này
```

`docker compose up -d ai-agent-service`. Kiểm tra: `GET /health` của máy GPU báo `"device": "cuda"`, và `rtf` trong kết quả `/v1/transcribe` nhỏ hơn nhiều so với CPU. `Dockerfile.gpu` chưa được chạy thử trên GPU trong dự án này.
