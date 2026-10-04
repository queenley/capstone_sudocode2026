# Audio mới bằng Edge TTS cũ

Lời thoại lấy nguyên từ `../voicemaker-v1/scripts.json`, sinh bằng công cụ `prepare_audio.py --input-scripts`; không gọi FPT hoặc dùng API key.

- 26 hội thoại: 6 dev + 20 eval; khách hàng hai split không trùng nhau.
- Agent: `vi-VN-HoaiMyNeural`; khách: `vi-VN-NamMinhNeural`.
- 1 dev và 4 eval có nhiễu trắng SNR mục tiêu 20 dB và băng thông mô phỏng 300–3400 Hz.
- WAV PCM16, mono, 16 kHz. Audio TTS tổng hợp, không phải ghi âm người thật hay audio BTC.
- `planned_customer_region` chỉ là kế hoạch script trước đây, **không phải vùng miền của audio**. Hai voice cũ chưa xác minh vùng miền; `region=unverified`.
- Transcript, entity và ranh giới speaker đều chờ người nghe duyệt. Không dùng nhãn ranh giới sinh TTS làm kết quả diarization.

Mở `listen.html` bằng trình duyệt để nghe và xuất phiếu duyệt. Chưa chạy ASR trên bộ này; chưa có kết quả PASS M1/M2.

Sinh lại an toàn, tiếp tục phần còn thiếu (không đổi script trong cùng phiên bản):

```sh
evaluation/asr/.venv/bin/python evaluation/asr/prepare_audio.py --input-scripts evaluation/asr/datasets/voicemaker-v1/scripts.json --out evaluation/asr/datasets/edge-new-v1
evaluation/asr/.venv/bin/python evaluation/asr/make_review.py --dataset evaluation/asr/datasets/edge-new-v1
```
