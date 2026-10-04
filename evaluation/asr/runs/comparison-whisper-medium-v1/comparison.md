# So sánh ASR trước–sau

Cùng hash audio và GT, đủ coverage. Dữ liệu TTS còn chờ nghe duyệt.

| Chỉ số (%) | Trước | Sau | Delta (điểm %) |
|---|---:|---:|---:|
| WER | 6.3 | 2.3 | -4.0 |
| CER | 5.0 | 1.0 | -4.0 |
| entity_accuracy | 50.0 | 100.0 | 50.0 |
| money_accuracy | 100.0 | 100.0 | 0.0 |
| phone_accuracy | 0.0 | 100.0 | 100.0 |

Xem lỗi cụ thể trong `errors.json` và nghe xác nhận trên `listen.html`. Không suy ra cải thiện trên audio thật từ bộ TTS này. Replay không có timing ASR để so tốc độ.
