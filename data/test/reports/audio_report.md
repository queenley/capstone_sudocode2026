# Báo cáo audio

## Bộ theo lượt khách (`audio/`)

- 874 clip, 192 cuộc gọi, 99 kịch bản, **0.86 giờ** (mục tiêu 3 giờ).
- **Sạch 410** · **nhiễu 464** (53% số clip biết trạng thái; cấu hình 50% ở 6 dB) · không rõ 0.
- Cuộc có ít nhất một lượt nhiễu: 185/192.

| Loại | Clip | Tỉ lệ | Phút |
|---|---:|---:|---:|
| sạch | 410 | 47% | 24.61 |
| gió | 119 | 14% | 6.94 |
| sóng yếu / điện thoại | 118 | 14% | 6.82 |
| quán cà phê | 116 | 13% | 6.94 |
| đường phố | 111 | 13% | 6.5 |

SNR của clip nhiễu: 6 dB × 464

### Theo kênh

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| chat_fanpage | 95 | 44 | cafe 12, clean 51, street 5, weak_signal 12, wind 15 |
| hotline | 673 | 353 | cafe 88, clean 320, street 91, weak_signal 86, wind 88 |
| zalo_oa | 106 | 67 | cafe 16, clean 39, street 15, weak_signal 20, wind 16 |

### Theo cách nhập (input mode)

| | Clip | Nhiễu | Các loại |
|---|---:|---:|---|
| asr_transcript | 39 | 15 | cafe 6, clean 24, street 4, weak_signal 4, wind 1 |
| chat_khong_dau | 16 | 10 | cafe 2, clean 6, street 3, wind 5 |
| chat_sai_chinh_ta | 8 | 3 | cafe 2, clean 5, weak_signal 1 |
| chat_teencode | 13 | 4 | cafe 2, clean 9, street 1, weak_signal 1 |
| text | 798 | 432 | cafe 104, clean 366, street 103, weak_signal 112, wind 113 |

## Bộ hội thoại hai người (`asr_test/`)

Chưa dựng (`python -m src.pipeline.build_asr_testset --limit 24`).
