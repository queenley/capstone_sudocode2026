# So sánh ASR trước–sau

Cùng hash audio và GT, đủ coverage. Dữ liệu TTS còn chờ nghe duyệt.

| Chỉ số (%) | Trước | Sau | Delta (điểm %) |
|---|---:|---:|---:|
| WER | 6.1 | 1.9 | -4.2 |
| CER | 4.6 | 1.3 | -3.3 |
| entity_accuracy | 52.5 | 80.0 | 27.5 |
| money_accuracy | 100.0 | 100.0 | 0.0 |
| phone_accuracy | 5.0 | 60.0 | 55.0 |

Xem lỗi cụ thể trong `errors.json` và nghe xác nhận trên `listen.html`. Không suy ra cải thiện trên audio thật từ bộ TTS này. Replay không có timing ASR để so tốc độ.
