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

Độ trễ hiện tại khoảng 10–15 giây mỗi câu trả lời vì tổng hợp giọng nói chạy trên CPU; cần GPU hoặc TTS nhanh hơn trước khi dùng thật.

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
