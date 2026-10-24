# Kênh liên hệ: Website, Zalo OA, Hotline

Cả ba kênh dùng **cùng một trợ lý AI và cùng hồ sơ khách**: khách nói chuyện ở đâu, nhân viên cũng thấy trong trang **Bán hàng** (`/ban-hang`) và khi AI chuyển máy, nhân viên trả lời ngay trong console.

| Kênh | Khách dùng | Cần cấu hình |
|---|---|---|
| Website | Khung chat và nút ☏ (gọi thoại trên trình duyệt) ở mọi trang | Không (gọi thoại cần `AGENT_WITH_VOICE=1`) |
| Zalo OA | Nhắn tin vào Official Account của shop | Tài khoản Zalo OA + app Zalo for Developers + URL HTTPS công khai |
| Hotline | Gọi số điện thoại của shop | LiveKit (có sẵn trong Docker) + SIP trunk từ nhà mạng + `AGENT_WITH_VOICE=1` |

---

## 1. Zalo Official Account

### Luồng xử lý

```
Khách nhắn Zalo OA → Zalo gửi webhook → api-gateway → ai-agent /api/channels/zalo/webhook
   → kiểm chữ ký → (mỗi khách một cuộc trò chuyện, kênh "zalo") → AI trả lời
   → gửi lại qua Zalo OA API (tin tư vấn)
```

Khi AI chuyển máy, AI im lặng; tư vấn viên trả lời trong `/ban-hang` → *Hội thoại* và câu trả lời được gửi sang Zalo cho khách.

### Thử ngay, chưa cần tài khoản Zalo

```powershell
$env:ZALO_WEBHOOK_INSECURE="1"; docker compose up -d ai-agent-service
python scripts/dev/zalo_simulator.py "Máy lọc không khí AirPure X giá bao nhiêu?"
python scripts/dev/zalo_simulator.py --interactive
```

Trình giả lập gửi webhook giống hệt Zalo và in câu trả lời. Chưa có access token nên câu trả lời được ghi `not_sent` (không gửi đi). **Không bật `ZALO_WEBHOOK_INSECURE` khi chạy thật.**

### Mock nền tảng Zalo (cả hai chiều, có giao diện chat)

`scripts/dev/zalo_mock.py` đóng cả hai vai mà Zalo đảm nhận: **phía người dùng** (trang chat, mỗi tin được gửi vào webhook kèm chữ ký thật `X-ZEvent-Signature`) và **phía nền tảng** (OA API `POST /v3.0/oa/message/cs` và OAuth `POST /v4/oa/access_token` mà shop gọi để trả lời). Câu trả lời của AI đi qua đúng đường gửi thật, hiện ngay trên trang chat với trạng thái `sent`.

```
Trình duyệt :8090 ──webhook có chữ ký──► api-gateway :8000 ──► ai-agent-service
       ▲                                                         │
       └────── POST /v3.0/oa/message/cs (access_token) ◄─────────┘
```

1. Thêm vào `.env` (bỏ `ZALO_WEBHOOK_INSECURE=1` nếu có), rồi `docker compose up -d --build ai-agent-service`:

```
ZALO_APP_ID=mock-app
ZALO_OA_ID=mock-oa
ZALO_OA_SECRET_KEY=mock-oa-secret
ZALO_ACCESS_TOKEN=mock-access-token
ZALO_OPENAPI_URL=http://host.docker.internal:8090
ZALO_OAUTH_URL=http://host.docker.internal:8090
ZALO_WEBHOOK_INSECURE=0
```

2. Chạy `python scripts/dev/zalo_mock.py` (chỉ cần Python, không cần thư viện), trình duyệt mở `http://127.0.0.1:8090`. `--check` in ra những gì `.env` còn thiếu.
3. Chọn người dùng ở cột trái: các khách CRM có `zalo_id` (để thử AI nhận ra khách quen) hoặc "Khách mới"; nút **Thêm** tạo người dùng mới. Gõ tin, hoặc gửi ảnh 📷, sticker 😀, theo dõi OA ➕.

Mock kiểm tra như Zalo: access token (`-216`), định dạng và độ dài tin, tối đa 2000 ký tự (`-201`), người nhận có tồn tại (`-213`) và đã nhắn OA trong 7 ngày qua (`-230`). Tin bị từ chối hiện thành dòng cảnh báo trên trang chat, và backend ghi `failed` trong nhật ký. Nếu `.env` có `ZALO_APP_SECRET` và `ZALO_REFRESH_TOKEN`, việc làm mới token cũng đi qua mock. **Không đặt `ZALO_OPENAPI_URL`/`ZALO_OAUTH_URL` khi chạy thật.**

### Kết nối OA thật

1. Tạo **Zalo Official Account** (oa.zalo.me) và một app trên **Zalo for Developers** (developers.zalo.me), liên kết app với OA.
2. Trong app → *Webhook*: đặt URL `https://<domain-của-bạn>/api/channels/zalo/webhook` (cổng gateway 8000 phải truy cập được qua HTTPS; khi phát triển có thể dùng `ngrok http 8000`). Bật sự kiện **user_send_text** (và các sự kiện gửi ảnh/sticker nếu muốn trả lời "chỉ đọc được chữ"). Zalo yêu cầu xác minh tên miền theo hướng dẫn trong trang app.
3. Lấy **OA Secret Key** (dùng để kiểm chữ ký webhook) và tạo **access token / refresh token** của OA (OAuth v4).
4. Điền vào `.env` rồi `docker compose up -d --build ai-agent-service web`:

```
ZALO_OA_ID=...            # hiện nút "Chat Zalo" trên website
ZALO_APP_ID=...
ZALO_OA_SECRET_KEY=...    # kiểm chữ ký X-ZEvent-Signature
ZALO_APP_SECRET=...       # để tự làm mới access token
ZALO_REFRESH_TOKEN=...    # refresh token chỉ dùng một lần: hệ thống tự lưu token mới vào DB
ZALO_ACCESS_TOKEN=        # tùy chọn, dùng khi chưa có refresh token
ZALO_WEBHOOK_INSECURE=0
```

5. Kiểm tra: `GET /api/channels/status` (token nhân viên) phải báo `webhook_verification: true` và `can_send: true`. Nhật ký tin Zalo: `GET /api/channels/zalo/messages`.

Ghi chú:
- Tin "tư vấn" của OA chỉ gửi được trong khoảng thời gian Zalo cho phép sau tin nhắn của khách; tin bị Zalo từ chối được ghi `failed` kèm lý do trong nhật ký.
- AI nhận ra khách quen qua `zalo_id` trong CRM; tin nhắn trả lời dài hơn 2000 ký tự được tách nhiều tin.
- Tư vấn viên nên trả lời khách Zalo trong **console** (`/ban-hang` → Hội thoại). Tin gửi từ hộp thư cũ `/agent` chưa được chuyển sang Zalo.

---

## 2. Hotline (LiveKit + SIP)

### Luồng xử lý

```
Khách gọi số hotline → nhà mạng (SIP trunk) → livekit-sip → phòng LiveKit "hotline-<ngẫu nhiên>"
   → hotline-bridge vào phòng, mở cuộc trò chuyện kênh "hotline", nối âm thanh với
     /api/conversations/{id}/voice của AI (nhận dạng giọng nói → AI → đọc câu trả lời)
```

Bridge gửi kèm **số người gọi** (bảo vệ bằng `HOTLINE_BRIDGE_KEY`), nên AI nhận ra khách quen và lập Call Brief như với web. Ngắt lời (barge-in) và đo độ trễ hoạt động như cuộc gọi trên web.

### Bật

```powershell
# .env đã có AGENT_WITH_VOICE=1: image AI kèm nhận dạng và tổng hợp giọng nói
docker compose --profile hotline up -d --build
```

Lần khởi động đầu, AI tải model giọng nói (~2,5 GB, khoảng 7 phút) vào volume `voice-models`; log có dòng `Voice ready` là xong. Cuộc gọi đến trước lúc đó sẽ im lặng. Các lần sau khởi động nhanh vì model đã có sẵn.

Dịch vụ thêm: `livekit` (cổng 7880, media UDP 40000–40100), `livekit-sip` (SIP 5060, RTP UDP 40200–40300), `hotline-bridge`. Bridge tự tạo **dispatch rule** "mỗi cuộc gọi một phòng `hotline-*`".

### Gọi thử khi chưa có số điện thoại

```powershell
docker compose --profile hotline run --rm -v "${PWD}/scripts/dev:/dev-scripts" hotline-bridge `
  python /dev-scripts/hotline_test_call.py --wav /dev-scripts/question.wav --number +84965384535
docker compose logs -f hotline-bridge     # thấy câu khách nói (transcript) và câu AI trả lời
```

Script giả làm một cuộc gọi SIP (thuộc tính `sip.phoneNumber`), phát `question.wav` (câu hỏi giá AirPure X, có sẵn trong `scripts/dev`) làm giọng khách và ghi lại tiếng của shop vào `scripts/dev/answer.wav`. Với số của khách CRM C032 như trên, AI chào đúng tên khách và nhắc lại cuộc trò chuyện trước, kể cả khi lần trước khách chat trên web.

### Nhận dạng giọng nói: service riêng

ASR chạy trong `asr-service` (cổng 8500), không nằm trong AI agent: agent gửi từng câu khách nói sang đó qua `ASR_URL`. Trong Docker nó chạy trên CPU máy này; khi thuê GPU, chạy `apps/asr-service/Dockerfile.gpu` trên máy đó và đặt `ASR_URL`, `ASR_API_KEY`, `ASR_LOCAL=0`. Service có thêm WebSocket realtime `/v1/stream` (chữ hiện dần khi khách đang nói). Chi tiết: [apps/asr-service/README.md](../apps/asr-service/README.md).

### Chọn giọng đọc: cloud hay local

Nhận dạng giọng nói luôn chạy cục bộ. Giọng đọc câu trả lời (TTS) chọn bằng `VOICE_TTS` trong `.env`:

| `VOICE_TTS` | Chạy ở đâu | Tốc độ (Docker 4 CPU) | Chi phí | Tải về |
|---|---|---|---|---|
| `openai:coral` (hoặc `nova`, `sage`, `shimmer`…) | API OpenAI, dùng `OPENAI_API_KEY` | khoảng 1–3 giây mỗi câu, các câu đọc song song | trả theo số ký tự | không tải gì |
| `elevenlabs:` | API ElevenLabs, dùng `ELEVENLABS_API_KEY` | khoảng 0,6 giây mỗi câu (lần đầu 3–5 giây) | trả theo số ký tự, đắt hơn OpenAI | không tải gì |
| `vieneu:` | CPU trong container | 10–15 giây mỗi câu, chiếm CPU của nhận dạng | miễn phí | ~1,4 GB lần đầu dùng |
| (để trống) | theo `voice.tts` trong `apps/ai-agent-service/config/models.yaml` (`vieneu:`) | | | |

Với `elevenlabs:`, giọng được chọn theo **miền của khách** trong CRM (`bac`, `trung`, `nam`), lấy từ nhóm `agent` của [scripts/create_data/config/voices.yaml](../scripts/create_data/config/voices.yaml): cùng một khách luôn nghe cùng một giọng; khách chưa nhận ra (hoặc CRM không có miền) nghe giọng **nữ miền Bắc** (`VOICE_DEFAULT_REGION=bac`, `VOICE_GENDER=female`). Hotline nhận ra khách ngay khi nối máy nên lời chào đã đúng giọng miền; trên web, giọng đổi theo miền khi khách được nhận ra, rồi giữ nguyên đến hết cuộc gọi. `elevenlabs:<voice id>` dùng một giọng cố định.

Chỉ giọng được chọn mới được nạp: chọn `openai:` thì model VieNeu không được tải, không được nạp, và gói `vieneu` cũng không được cài vào image. Đổi qua lại thì build lại:

```powershell
docker compose up -d --build ai-agent-service
```

Model của bên được chọn nằm trong volume `voice-models` (`HF_HOME=/app/models/huggingface`), nên chỉ tải một lần. Trang Developer vẫn đổi được giọng lúc đang chạy, trong số những giọng image có.

### Kết nối số điện thoại thật

1. Thuê **SIP trunk** từ nhà cung cấp (VNPT, Viettel, FPT, CMC Telecom… hoặc nhà cung cấp quốc tế như Twilio/Telnyx). Họ cấp số hotline và trỏ cuộc gọi vào địa chỉ SIP của bạn.
2. Máy chạy `livekit-sip` cần **IP công khai** và mở UDP 5060 + 40200–40300 (và 40000–40100 cho LiveKit). Đặt `SIP_USE_EXTERNAL_IP=true`; với LiveKit đặt `use_external_ip: true` trong `infra/livekit/livekit.yaml`.
3. Tạo **inbound trunk** trong LiveKit với số hotline (và IP/username của nhà mạng), ví dụ bằng LiveKit CLI:
   `lk sip inbound create --name hotline --numbers +8419006868 --auth-user ... --auth-pass ...`
4. Đặt khóa thật trong `.env` (không dùng giá trị mặc định khi chạy thật):

```
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...     # ít nhất 32 ký tự
HOTLINE_BRIDGE_KEY=...     # chuỗi ngẫu nhiên dài
HOTLINE_NUMBER=1900 6868   # số hiện trên website
LIVEKIT_URL=ws://livekit:7880
SIP_TRUNK_ID=...           # ID inbound trunk, để trang trạng thái báo "đã có trunk"
```

---

## 3. Trang bán hàng `/ban-hang`

Đăng nhập ở `/login` (tài khoản tạo bằng `scripts/admin/create_admin.py` hoặc trang Quản trị). Mục hiện theo vai trò:

| Mục | Vai trò | Nội dung |
|---|---|---|
| Tổng quan | mọi vai trò | Cuộc trò chuyện đang mở theo kênh, khách chờ nhân viên, đơn và doanh thu hôm nay |
| Hội thoại & chuyển máy | agent, admin | Console tư vấn viên: nhận cuộc AI chuyển, trả lời cùng gợi ý của AI (web và Zalo) |
| Đơn hàng | seller, admin | Danh sách, lọc, chi tiết (sản phẩm, địa chỉ giao), hủy đơn |
| Hẹn gọi lại | agent, admin | Lịch gọi lại do AI đặt với khách |

---

## 4. Thanh toán chuyển khoản (VietQR)

Khách chọn **COD** (đơn dưới 10.000.000₫) hoặc **chuyển khoản** khi đặt hàng. Bật chuyển khoản bằng tài khoản của shop trong `.env`, rồi `docker compose up -d`:

```
BANK_BIN=970436                 # mã VietQR của ngân hàng (970436 = Vietcombank, 970422 = MB, 970407 = Techcombank…)
BANK_NAME=Vietcombank
BANK_ACCOUNT_NO=...
BANK_ACCOUNT_NAME=CONG TY ...   # tên chủ tài khoản, viết hoa không dấu
```

Sau khi đặt, khách thấy mã **VietQR** (ảnh từ img.vietqr.io) với đúng số tiền và nội dung `TN<mã đơn>`. Nhân viên đối soát sao kê rồi bấm **"Đã nhận tiền"** trong `/ban-hang` → Đơn hàng. Cổng thanh toán online (MoMo, VNPAY, thẻ) cần tài khoản merchant nên chưa tích hợp.
