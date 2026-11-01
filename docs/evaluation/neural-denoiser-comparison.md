# Neural denoiser tùy chọn — 01/11/2026

Đã tích hợp **RNNoise** qua native wheel `pyrnnoise==0.4.5`, mặc định **tắt**. ASR vẫn **Zipformer 30M int8 greedy**. Cùng đường xử lý được dùng cho agent local, HTTP và WebSocket của ASR service. Không tự tải model khi nhận request; thiếu optional dependency trả lỗi, không âm thầm chạy đối chứng.

**Kết luận trên bộ này:** RNNoise làm tăng lỗi và thời gian xử lý, nên giữ `none` làm mặc định. Kết quả không đại diện cho mọi denoiser hoặc mọi môi trường âm thanh.

## Kết quả so bật/tắt

Điểm WER/CER và entity exact-match dưới đây tính bằng `reference_eval.py` trên main, không sửa công thức. So văn bản ASR **raw**, trước sửa lexicon/ITN và chính sách đưa vào agent. Báo cáo máy vẫn giữ cả raw/corrected/agent_input.

| 148 clip có ranh giới sẵn (oracle segmentation) | Tắt | RNNoise |
|---|---:|---:|
| WER | 15,9% | 17,8% |
| CER | 13,1% | 15,1% |
| Entity accuracy diagnostic, 90 nhãn | 58,9% | 53,3% |
| Entity micro-F1 bổ sung | 75,6% | 70,7% |
| Thời gian xử lý mỗi clip p50 | 160 ms | 818 ms |
| Thời gian xử lý mỗi clip p95 | 315 ms | 1.703 ms |
| Tổng xử lý 967 giây audio | 26,97 s | 132,37 s |
| RTF tổng | 0,0279 | 0,1369 |

So lỗi từ theo từng clip: **19 tốt hơn, 43 tệ hơn, 86 bằng nhau**. Số lỗi từ tăng **619 → 693** trên 3.888 từ tham chiếu. Theo file: `01_multivoice_medical` tăng 396→451 lỗi/2.153 từ; `02_numbers_negation_repetition` tăng 223→242 lỗi/1.735 từ.

| Hai montage nguyên vẹn, cắt bằng waveform tối đa 20 s, không dùng ranh giới transcript | Tắt | RNNoise |
|---|---:|---:|
| WER | 17,3% | 22,6% |
| CER | 14,1% | 19,1% |
| Entity accuracy diagnostic, 89 nhãn | 29,2% | 27,0% |
| Tổng xử lý 1.018,1 giây audio | 28,90 s | 129,62 s |

Không dùng p95 của chỉ hai montage làm kết luận latency. Montage gồm các phát ngôn ghép với khoảng lặng, không phải hai cuộc hội thoại tự nhiên. Entity ordinal-key bị ảnh hưởng dây chuyền khi bỏ sót một thực thể trước đó; không so trực tiếp accuracy 90 nhãn của clips với 89 nhãn montage. Chỉ so bật/tắt trong cùng đơn vị.

## Entity và phân tích lỗi

Người dùng chọn **nhãn diagnostic chờ duyệt**, không có gold entity được duyệt đi kèm. Phiên bản riêng `entity-review-diagnostic-v1.json` gồm số/đơn vị từ extractor v2 và 36 cụm từ bệnh/nhóm thuốc/thủ thuật đọc từ reference, đóng băng trước inference. Không sửa transcript gốc; không đưa reference, nhãn hay vocabulary lâm sàng cho ASR/denoiser hoặc lexicon sản phẩm.

| Nhóm mention trên 148 clips | Đúng khi tắt | Đúng khi bật |
|---|---:|---:|
| Bệnh | 19/37 | 16/37 |
| Nhóm thuốc | 5/5 | 4/5 |
| Thủ thuật | 4/17 | 4/17 |
| Số/đơn vị rõ | 25/31 | 24/31 |

Đây là matching vocabulary đóng, không phải medical NER độc lập. Nhãn thuốc là nhóm thuốc được nói, chưa đo tên hoạt chất/biệt dược. Vocab thiếu, cách ghi COVID/implant và sự dịch ordinal có thể tạo sai số đo; shared extractor tạo cả nhãn số tham chiếu lẫn dự đoán có thể bỏ qua cùng một lỗi. Chưa suy ra clinical entity accuracy đầy đủ hoặc xác nhận y khoa.

Các kết quả cho thấy không có cải thiện tổng thể ở WER/CER và entity. Một vài đơn vị như mg có thêm match, nhưng mẫu nhỏ; không chọn ví dụ có lợi để bật mặc định. Chưa có phép đo clean/noise-reference để kết luận vì sao âm nào bị mất, tính SNR/PESQ/STOI/SI-SDR hoặc nói chất lượng cảm nhận đã tăng. Nguồn VietMed vốn 8 kHz được upsample: resample 16→48 kHz không khôi phục băng thông đã thiếu; ảnh hưởng này là giả thuyết cần bộ clean/noisy phù hợp để phân xử.

## Giao thức và bằng chứng

- Một clip smoke trước cohort; chạy local CPU trên macOS 26.5.2 arm64, Python 3.12, `ASR_THREADS=4`. Hai điều kiện chạy tuần tự, tắt trước bật, một pass mỗi điều kiện; chưa phải latency study lặp/ngẫu nhiên hoặc benchmark production.
- Nguồn audio/reference/manifest được kiểm checksum. Mỗi cặp clip có **PCM float32 giống hệt từng sample** và cùng sample rate, cùng ranh giới. WAV slice FLOAT có timestamp trong PEAK chunk nên file hash có thể khác ở bytes 60..63; đã kiểm đó là khác biệt header duy nhất, không phải khác âm thanh. Hai montage dùng đúng cùng file gốc.
- Cùng Zipformer weights/greedy/hotwords, cùng mã đo, source hash, reference và entity labels. `cohort-lock.json`, `comparison.json`, `source-used/manifest.json`, decoded reports và error analysis nằm riêng tại `evaluation/runs/20261101-denoiser/`, không lên Git.
- RNNoise native library SHA256 trên máy đo: `b0b0f3c038b8106f04c638596bd8d6594bddaeeaef5db39c5b401de80334efee`. Library/weights nằm trong venv, không commit. Mỗi utterance/prefix có state mới, scale float PCM về biên độ int16 trước RNNoise, resample HQ và bù/flush một hop theo ví dụ v0.2 upstream. Không thay waveform đầu vào bằng transcript hoặc vocabulary.
- `seconds` là denoise + ASR, không gồm model load, file read hoặc network/queue. Có thêm `denoise_seconds`, `decoder_seconds` và wall time. Trên 148 clips, denoise chiếm 113,43 s; decode ghi nhận 26,97 s (tắt) và 18,93 s (bật). Không gán riêng biến thiên decoder cho một cải tiến vì máy không được cách ly tải/thermal hoặc lặp nhiều seed.
- Tất cả bốn cohort COMPLETE, không thiếu clip/file. Không dùng API trả phí hoặc thay đổi budget ledger. Các trường wer_clean/wer_noisy của main không được dùng để gán nhãn sạch/nhiễu: bộ này không có nhãn noise độc lập được duyệt.
- **86 test ASR/voice/pack BTC pass**, gồm adapter native giả, giải phóng state khi lỗi, flush/tail, HTTP/WS tùy chọn, tắt không load thư viện, metadata/timing sai và dependency thiếu. Native RNNoise + Zipformer được kiểm bằng các cohort local nêu trên và smoke root runner → HTTP service localhost, trạng thái COMPLETE; server tạm đã dừng. Chưa nghiệm thu Docker/GPU, mic/loa thật, hiệu quả AEC hoặc full web voice với người nói thật. RNNoise ở đây nằm trước ASR, sau bước phân đoạn lượt/VAD; không chứng minh cải thiện VAD/barge-in.

## Bật và tái lập

```sh
# Trên venv đã cài requirements ASR; chỉ dùng native library, tránh deps wrapper không sử dụng.
python -m pip install --no-deps -r apps/asr-service/requirements-denoise.txt
# Agent web: ASR_DENOISER=rnnoise; mặc định ASR_DENOISER=none.
# ASR Docker CPU/GPU: build thêm --build-arg INSTALL_DENOISER=1.
# HTTP: POST /v1/transcribe?model=zipformer-30m&denoiser=rnnoise
# WS config: {"model":"zipformer-30m","denoiser":"rnnoise",...}
```

Từ gốc repo, đổi `none` thành `rnnoise`; dùng thư mục output MỚI cho mỗi lần chạy:

```sh
EVAL_BUDGET_DB="$PWD/evaluation/runs/20261024-work/budget.sqlite" \
ASR_URL='' ASR_FETCH=0 HF_HUB_OFFLINE=1 ASR_THREADS=4 \
apps/ai-agent-service/.venv/bin/python run_eval.py \
  --asr-package data/seed/catalog/asr_hard_vi --asr-unit segments \
  --asr-transcribe --asr-model zipformer-30m --asr-denoiser none \
  --asr-entity-review evaluation/runs/20261101-denoiser/entity-review-diagnostic-v1.json \
  --out evaluation/runs/<new-run-name>
```

Smoke thêm `--only 01_multivoice_medical_001`. Montage dùng `--asr-unit montage` và không chọn clip ID. Nếu không còn file nhãn riêng thì bỏ `--asr-entity-review`; entity không có gold là chưa đo, không điền 0 hay PASS. Giữ AEC browser; RNNoise không phải AEC, và chồng noise suppression browser với server cần kiểm bằng mic thật.

Nguồn kỹ thuật: [RNNoise v0.2](https://github.com/xiph/rnnoise/tree/v0.2), [ví dụ xử lý frame/first hop](https://github.com/xiph/rnnoise/blob/v0.2/examples/rnnoise_demo.c), [PyRNNoise/native wheel](https://github.com/pengzhendong/pyrnnoise). Giấy phép trong `THIRD_PARTY_NOTICES/RNNoise.txt`.
