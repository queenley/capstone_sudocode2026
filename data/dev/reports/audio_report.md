# Báo cáo audio

## Bộ theo lượt khách (`audio/`)

- 3612 clip, 797 cuộc gọi, 400 kịch bản, **3.55 giờ** (mục tiêu 3 giờ).
- **Sạch 1800** · **nhiễu 1812** (50% số clip biết trạng thái; cấu hình 50% ở 6 dB) · không rõ 0.
- Cuộc có ít nhất một lượt nhiễu: 757/797.

| Loại | Clip | Tỉ lệ | Phút |
|---|---:|---:|---:|
| sạch | 1800 | 50% | 107.45 |
| đường phố | 473 | 13% | 27.33 |
| quán cà phê | 472 | 13% | 28.09 |
| gió | 455 | 13% | 26.55 |
| sóng yếu / điện thoại | 412 | 11% | 23.84 |

SNR của clip nhiễu: 6 dB × 1812

### Theo kênh

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| chat_fanpage | 330 | 167 | cafe 36, clean 163, street 44, weak_signal 43, wind 44 |
| hotline | 2926 | 1441 | cafe 386, clean 1485, street 380, weak_signal 323, wind 352 |
| zalo_oa | 356 | 204 | cafe 50, clean 152, street 49, weak_signal 46, wind 59 |

### Theo cách nhập (input mode)

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| asr_transcript | 185 | 88 | cafe 24, clean 97, street 22, weak_signal 19, wind 23 |
| chat_khong_dau | 51 | 29 | cafe 4, clean 22, street 8, weak_signal 4, wind 13 |
| chat_sai_chinh_ta | 25 | 9 | cafe 5, clean 16, weak_signal 3, wind 1 |
| chat_teencode | 64 | 33 | cafe 9, clean 31, street 10, weak_signal 7, wind 7 |
| text | 3287 | 1653 | cafe 430, clean 1634, street 433, weak_signal 379, wind 411 |

## Bộ hội thoại hai người (`asr_test/`)

- 24 hội thoại: **sạch 16**, **nhiễu 8** (weak_signal (băng thông điện thoại + mất gói), 10 dB).
- Có audio 24/24, 35.63 phút (nhiễu 11.97 phút).
