# Khôi phục cuộc gọi web local — 2026-11-01

## Nguyên nhân và thay đổi

Docker xác nhận agent cũ bị `OOMKilled=true`, exit 137. Gateway mất upstream và đóng WebSocket bằng mã 1011; Zipformer ở cổng 8500 vẫn ready. Docker VM có khoảng 4,31 GiB RAM.

- MCP chỉ kết nối các server có tool nghiệp vụ dành cho vai trò đang dùng. Advisor không nạp knowledge; memory_writer chỉ mở memory; admin mở memory và knowledge. Kiểm tra quyền tại server vẫn giữ nguyên.
- Adapter giữ kết nối trong suốt vòng đời; tắt `keep_alive` của transport để subprocess được giải phóng khi đóng hoặc kết nối thất bại. Dùng handshake `legacy` mà cả adapter và server hỗ trợ, tránh lỗi auto-negotiation đã xuất hiện trong log.
- Gateway bỏ qua `WebSocketDisconnect` khi browser đã rời đi, kể cả lúc kết nối upstream thất bại, và vẫn dọn task/connection.
- Giữ ASR `zipformer-30m` / greedy, denoiser mặc định tắt, TTS `vieneu:` local.

## Kiểm chứng

52 test passed, 1 skipped (Redis integration chưa cấu hình trong lệnh này):

```bash
apps/ai-agent-service/.venv/bin/python -m pytest \
  tests/agent/test_mcp_lifecycle.py tests/test_gateway.py tests/test_auth_mcp.py \
  tests/agent/test_voice_transport.py tests/agent/test_voice_decisions.py \
  tests/agent/test_asr_denoise.py -q
```

Test MCP dùng subprocess và protocol thật với fixture không cần database/model: gọi tool nhiều lần, đóng rồi kết nối lại. Test gateway bao phủ browser rời đi khi relay hoặc khi upstream không kết nối được.

Hai cuộc gọi live liên tiếp đã đi qua Next.js `/backend` để tạo conversation, gateway WebSocket, VAD/SmartTurn, Zipformer, agent thật, TTS local và hangup. Input là câu hỏi chính sách đổi trả tổng hợp bằng giọng Linh local; output WAV từng chunk được decode và kiểm tra có tín hiệu hữu hạn, khác zero.

| Kiểm tra | Cuộc 1 | Cuộc 2 |
|---|---:|---:|
| Transcript khớp câu hỏi sau bỏ hoa/thường, dấu câu | Có | Có |
| Audio chunks (lời chào + trả lời) | 55 | 70 |
| Thời lượng output (giây) | 17,20 | 21,68 |
| ASR trong sự kiện transcript (ms) | 638 | 144 |
| TTFA server cho lượt hỏi (ms) | 7.582 | 7.884 |
| Lỗi được báo qua voice | 0 | 0 |
| Agent OOM / restart sau test | Không | Không |

RAM agent quan sát sau warm-up/cuộc gọi khoảng 2,7–3,0 GiB. Đây là hai smoke test, chưa phải kiểm tra tải hoặc cam kết latency. Tổng thời gian mỗi script khoảng 77 giây, gồm khởi tạo, lời chào, gửi audio theo thời gian thực và nhận hết TTS.

Một lần thử trước khi preload TTS hoàn tất bị timeout kết nối upstream; không tính là cuộc gọi thành công. Chỉ kiểm tra packages/weights chưa đủ xác nhận voice đã warm xong: cần log `Voice ready` và kiểm tra audio thật.

## Stack đang chạy

- Web: `http://127.0.0.1:3000`; gateway: `http://127.0.0.1:8000`.
- ASR native: cổng 8500; agent Docker dùng `http://host.docker.internal:8500`.
- Docker build trước đó lỗi `Bus error`, nên live test dùng image sẵn có và bind code/config/dependency JSON repair local. Override đang dùng: `/private/tmp/quivo-voice-live.json`.
- Cache TTS đã giữ ở volume `voice-models`, dưới `/app/models/huggingface`.
- Ledger gốc `evaluation/runs/20261024-work/budget.sqlite` được bind trực tiếp vào agent. Không tạo/reset ledger; không giải phóng các reservation cũ chưa xác định.
- Bằng chứng và audio tổng hợp ở `/private/tmp/quivo-voice-smoke/`; không đưa raw conversation/token vào Git.

Chưa kiểm tra microphone, loa, echo thực tế trên máy người dùng hoặc nhiều cuộc đồng thời. Playback acknowledgement trong smoke là của client kiểm thử, không phải phép đo phát âm thanh trên phần cứng trình duyệt. Người dùng cần thử lại nút **Gọi thoại** trên web sau khi stack đã warm.
