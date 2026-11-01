# Báo cáo audio

## Bộ theo lượt khách (`audio/`)

- 3065 clip, 672 cuộc gọi, 342 kịch bản, **3.01 giờ** (mục tiêu 3 giờ).
- **Sạch 1506** · **nhiễu 1559** (51% số clip biết trạng thái; cấu hình 50% ở 6 dB) · không rõ 0.
- Cuộc có ít nhất một lượt nhiễu: 640/672.

| Loại | Clip | Tỉ lệ | Phút |
|---|---:|---:|---:|
| sạch | 1506 | 49% | 89.86 |
| gió | 412 | 13% | 23.93 |
| quán cà phê | 396 | 13% | 23.35 |
| đường phố | 394 | 13% | 22.71 |
| sóng yếu / điện thoại | 357 | 12% | 20.55 |

SNR của clip nhiễu: 6 dB × 1559

### Theo kênh

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| chat_fanpage | 299 | 151 | cafe 27, clean 148, street 43, weak_signal 39, wind 42 |
| hotline | 2425 | 1213 | cafe 320, clean 1212, street 307, weak_signal 273, wind 313 |
| zalo_oa | 341 | 195 | cafe 49, clean 146, street 44, weak_signal 45, wind 57 |

### Theo cách nhập (input mode)

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| asr_transcript | 153 | 71 | cafe 21, clean 82, street 14, weak_signal 17, wind 19 |
| chat_khong_dau | 51 | 29 | cafe 4, clean 22, street 8, weak_signal 4, wind 13 |
| chat_sai_chinh_ta | 25 | 9 | cafe 5, clean 16, weak_signal 3, wind 1 |
| chat_teencode | 48 | 23 | cafe 5, clean 25, street 8, weak_signal 4, wind 6 |
| text | 2788 | 1427 | cafe 361, clean 1361, street 364, weak_signal 329, wind 373 |

## Bộ hội thoại hai người (`asr_test/`)

- 24 hội thoại: **sạch 16**, **nhiễu 8** (weak_signal (băng thông điện thoại + mất gói), 10 dB).
- Có audio 24/24, 35.63 phút (nhiễu 11.97 phút).
