# So sánh 3 mô hình ASR và diarization (24/10/2026)

> Đánh giá trên cả bộ (674 lượt nói của khách, 85 kịch bản) chạy bằng `scripts/evaluation/run_eval.py asr`; cách làm và kết quả ở [scripts/evaluation/README.md](../../../scripts/evaluation/README.md) mục 5. Trang này là thí nghiệm so sánh ban đầu trên 7 clip.

Dữ liệu: audio `scenarios_SCN-GEN-0001/` (7 clip khách hàng, một giọng ElevenLabs; 4 clip có nhiễu quán cà phê/đường phố/sóng yếu, 3 clip sạch). Reference là văn bản gốc đổi sang dạng đọc bằng `scripts/create_data/src/asr/spoken.py` (số thành chữ, giống ground truth ASR của BTC). Chấm bằng `wer_cer` của BTC (`reference_eval.py`). CPU Apple, 4 luồng, lúc đó simulator đang chạy nền nên RTF chỉ để so sánh tương đối.

## WER

| Mô hình | WER | CER | WER nhiễu | WER sạch | RTF | Tải mô hình |
|---|---|---|---|---|---|---|
| **VieGem-ASR** (greedy, fp32) | **3,0%** | 3,3% | 4,8% | 0,0% | 0,62 | ~17 s |
| **Zipformer 30M int8** (sherpa-onnx) | 5,0% | **1,8%** | 5,9% | 0,0% | **0,03** | 0,7 s |
| faster-whisper PhoWhisper-small int8 | 6,0% | 4,5% | 9,5% | 0,0% | 0,52 | 3,7 s |

Chi tiết từng clip: `asr-bench-result.json`. Sai sót nằm ở tên sản phẩm và từ viết tắt trong câu có nhiễu: "AirPure X" (Zipformer: "eprox", PhoWhisper: "airasia exc", VieGem: "air x") và "COD" (Zipformer: "c od", PhoWhisper: "seo đi", VieGem: "siêu"). Lexicon của agent (`voice.lexicon` trong `config/models.yaml`) sửa được một phần các lỗi kiểu này sau ASR; điểm trên chưa áp lexicon.

**Entity accuracy** (`scripts/create_data/src/asr/entities.py`, mới): entity lấy từ văn bản ASR bằng đúng ITN của agent (số chữ thành số) rồi so khớp tuyệt đối với ground truth theo `wer_cer` của BTC. Trên 4 entity của SCN-GEN-0001 call_1 (`room_area_m2` 25, `has_children` False, `budget_vnd` 5.000.000, `payment` COD) cả ba mô hình đều đạt **75% (3/4)**: sai cùng một entity, `payment=COD` trong clip nhiễu quán cà phê, vì cả ba nghe "COD" thành "c od" / "seo đi" / "siêu". Lexicon hiện tại chưa có các biến thể này và tôi không thêm chúng để khớp mẫu thử.

**Giới hạn:** chỉ 7 clip, khoảng 60 từ. Chênh lệch 1–2 từ, chưa đủ để kết luận mô hình nào chính xác hơn. Cần bộ `build_asr_testset` đầy đủ (85 kịch bản) để có số có ý nghĩa.

## Chọn mô hình

Giữ **Zipformer 30M** (`voice.asr: zipformer-30m`).
- Nhanh gấp ~17–20 lần hai mô hình còn lại (RTF 0,03), nằm trong ngân sách TTFT 3 giây của agent; tải 33 MB, không cần torch.
- CER thấp nhất (1,8%); WER 5,0% sát VieGem trên mẫu nhỏ này.
- **VieGem-ASR** chính xác hơn nhưng không dùng làm mặc định: giấy phép **CC-BY-NC-SA 4.0 + Gemma Terms (phi thương mại)**, cần torch/transformers và thêm `google/embeddinggemma-2` (1,5 GB), tải ~17 s, chậm hơn ~20 lần trên CPU. Phù hợp để tham chiếu nghiên cứu, không phù hợp để đóng gói vào sản phẩm.
- **PhoWhisper-small** vừa chậm hơn vừa kém hơn Zipformer trên mẫu này.

## Diarization

`scripts/create_data/src/asr/diarize.py` (mới), nối vào `eval_asr.py --diarize`:
1. sherpa-onnx cắt đoạn theo người nói (pyannote segmentation 3.0 + embedding 3D-Speaker ERes2Net, CPU), đặt trước 2 người nói.
2. Gán vai BTC: người nói trước là **A** (shop nghe máy trước, như các hội thoại BTC), người còn lại là **C**; một cụm duy nhất thì nhận nhãn `single` (clip khách đơn lẻ = C).
3. Nối các đoạn cùng vai cách nhau ≤ 0,6 s, bỏ đoạn < 0,3 s.
4. Nhận dạng từng đoạn bằng Zipformer rồi xuất `turns` {speaker, start, end, text}. Khi đó `wer_cer` của BTC tính `diarization_turn_accuracy`.

Cách chạy: `python -m src.pipeline.eval_asr --set team --transcribe --engine zipformer --diarize --segmentation <model.onnx> --embedding <.onnx>`.

**Kiểm tra** (`diarization_check.py`; không có audio agent thật của SCN-GEN-0001 nên dựng hội thoại 8 lượt từ clip khách của bộ dữ liệu và 2 câu của giọng nam Edge-TTS làm "agent"):

| Thử | Kết quả |
|---|---|
| 1 người nói (clip khách) | 1 cụm, nhãn C |
| Hội thoại 2 giọng thật khác nhau, 8 đoạn | **100%** `diarization_turn_accuracy`; mốc thời gian lệch ≤ ~0,3 s |
| Hội thoại giả giọng bằng đổi cao độ (resample) | 50–83%: embedding không coi đó là người khác; đây là hạn chế của cách giả giọng, không phải của mã |

Giới hạn: nhãn người nói chỉ đúng khi shop nói trước và chỉ có 2 người; một lượt ngắn bị nhiễu có thể gán nhầm; 8 đoạn là mẫu rất nhỏ. Cần bộ hội thoại 2 giọng thật (BTC D01–D12 hoặc `build_asr_testset`) để có con số chính thức.

## Tái lập

- Mô hình (không commit): Zipformer 30M (github k2-fsa/sherpa-onnx), `diepho/PhoWhisper-small-ct2`, `5CD-AI/VieGem-ASR` + `google/embeddinggemma-2`, `sherpa-onnx-pyannote-segmentation-3-0`, `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`.
- `asr_bench.py` so 3 mô hình; `diarization_check.py` kiểm diarization. Đặt `ASR_LAB` trỏ tới thư mục chứa `models/` và `agent_tts/`.
- Test: `scripts/create_data/tests/test_diarize.py` (5 test, không cần mô hình).
