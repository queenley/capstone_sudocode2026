# Kiến trúc ASR local

Quyết định ngày 01/11/2026: **Zipformer 30M int8, greedy search (`zipformer-30m`) là mặc định cho mọi luồng ASR**. Web voice, HTTP, WebSocket, preload, tải weights và `run_eval.py` đều dùng mặc định này. Các adapter khác chỉ được dùng khi chọn rõ; không tự chuyển model khi có lỗi.

## Luồng xử lý

```text
Microphone + AEC/NS/AGC theo capture profile
  → PCM float32 → resample 16 kHz → VAD / Smart Turn
  → ASR service (Zipformer greedy)
  → recognition dùng chung: raw / corrected / agent_input
  → hội thoại agent hoặc runner đánh giá
```

- Service riêng tại `apps/asr-service`, backend truy cập qua `components/voice/asr.py`; khi không có `ASR_URL`, backend có thể dùng cùng engines trong tiến trình.
- `components/voice/recognition.py` dùng chung cho web và benchmark. Giữ raw output để đối chiếu; sửa tên sản phẩm và lọc echo không được ghi đè kết quả raw.
- Bằng chứng echo chỉ dùng chunk TTS thực sự được client xác nhận đã phát. Các kết quả ASR muộn bị kiểm tra theo lượt/epoch. Pause không được tự thành một lần ngắt lời đã xác nhận chỉ vì VAD phát hiện âm thanh.
- Timer giữ pause trong lúc còn nói/nhận dạng, có giới hạn utterance + ASR timeout. Lỗi/timeout cho cuộc gọi phục hồi. Transport dọn request, socket, timer và HTTP pool khi đóng.
- Hai capture profile: standard giữ AEC/NS/AGC; barge-in giữ AEC, yêu cầu tắt NS/AGC nếu browser hỗ trợ. Ghi settings thực tế. Fake tests không thay thế kiểm tra mic/loa thật.

## Nguồn và weights

Gói Zipformer mặc định: `sherpa-onnx-zipformer-vi-30M-int8-2026-02-09`, [release sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models). SHA256 archive: `da8b637947091829d7ee9eda23da2a4ec7caa399233a3f4e34eb719fb2ea6b9b`. `artifact.json` lưu nguồn, checksum từng file và cấu hình. Inference không tự tải weights. Fetch có lock cho volume dùng chung, staging và kiểm tra checksum trước publish.

```sh
PYTHONPATH=apps/asr-service/src python -m asr_service.fetch --model zipformer-30m
ASR_FETCH=0 ASR_PRELOAD=zipformer-30m HF_HUB_OFFLINE=1 \
  uvicorn asr_service.main:app --app-dir apps/asr-service/src --host 127.0.0.1 --port 18500
```

`ASR_FETCH_MODELS` mặc định chỉ `zipformer-30m`. Khi cần nghiên cứu adapter khác phải chọn rõ bằng `--model`/`--asr-model`; không coi đó là mặc định mới. `zipformer-30m-beam4` dùng cùng weights với decoder khác. PhoWhisper mặc định tải bản preconverted đã ghim phiên bản; chuyển VinAI sang int8 cần `--convert-phowhisper` và requirements research. VieGem cần Torch/Transformers riêng, có điều kiện phi thương mại theo model card. Kiến trúc adapter được giữ; không tự tải hoặc chạy chúng.

## Giao thức

- `GET /v1/models`, `POST /v1/models/{name}/load`, `GET /v1/models/{name}/artifact`.
- `POST /v1/transcribe`: PCM float32 little-endian mono 16 kHz; mặc định `model=zipformer-30m`.
- `WS /v1/stream`: cấu hình → ready → binary PCM → partial → end/final. Thiếu final, sai schema/model/audio, reset và disconnect đều cần kiểm tra. Partial hiện giải mã lại prefix, không được gọi là native streaming.
- Service giới hạn 120 giây/request theo cấu hình. Runner nhận WAV dài tối đa 30 phút và cắt tối đa 20 giây/chunk theo năng lượng, không nhìn transcript/GT và không bỏ sample.

## Đánh giá qua một lệnh

Bộ chấm vẫn là `reference_eval.py` trên main; không khôi phục ZIP và không sửa công thức. Gói BTC read-only, regression test ghim checksum.

```sh
export ASR_URL=http://127.0.0.1:18500 ASR_TIMEOUT=240
# Replay hypotheses đã có, không gọi model
python run_eval.py --asr /absolute/path/input \
  --asr-hypotheses /absolute/path/hypotheses.json --out evaluation/runs/asr-replay-new
# Audio có reference theo manifest; thử một clip trước cohort
python run_eval.py --asr-package /absolute/path/package --asr-unit segments --only CLIP_ID \
  --asr-transcribe --out evaluation/runs/asr-smoke-new
# Chưa có reference: chỉ transcript/timing, không WER/CER
python run_eval.py --asr-audio /absolute/path/audio.wav --asr-transcribe \
  --out evaluation/runs/asr-unlabelled-new
```

Đường `--asr-unit montage` chia audio bằng waveform. `segments` dùng ranh giới được cung cấp: phải báo oracle segmentation và tách khỏi phép chạy dài. Mọi evidence thô nằm trong `evaluation/runs`, không commit.

- WER/CER chính từ scorer main; raw/corrected/agent_input báo riêng. Không bỏ dấu tiếng Việt, phủ định hoặc từ lặp, không đổi chữ số để làm đẹp điểm.
- Sidecar: S/D/I, coverage, lỗi request, phân nhóm, RTF và số mẫu. Không lấy ASR decode time làm TTFA của agent. Score không tính được là `INCOMPLETE`.
- `--asr-entity-review` nhận nhãn canonical có nguồn, reviewer và phiên bản. Chưa duyệt thì diagnostic; không tự tạo gold từ model. Rule chỉ trích từ hypotheses, không đưa reference vào ASR. So các extractor trên cùng replies/hypotheses và cùng phiên bản dụng cụ đo.
- Signal descriptors: RMS/peak dBFS, DC offset, clipping, frame năng lượng thấp và dải tần. SNR/PESQ/STOI/SI-SDR cần clean reference phù hợp; DER cần speaker gold. Thiếu bằng chứng ghi chưa đo.

## Dữ liệu đã xóa

Audio, reference/nhãn và toàn bộ kết quả `asr_hard_vi` đã được xóa theo yêu cầu người dùng. Giữ kiến trúc, code, schema, unit tests, weights Zipformer, dữ liệu agent, pack BTC và ledger ngân sách. Không còn dùng nhãn hoặc số đo hard-test cũ làm cohort hoạt động. Chi tiết phạm vi tại `docs/plan/ASR-DATA-CLEANUP.md`.

Phần tiếp thu từ [VoiceGo cf3e42a](https://github.com/Tan28092006/VoiceGo/tree/cf3e42ae3a76e558086c673f9e45d096ad1a48db/voicego): quản lý lượt nói, echo theo phát loa thực tế và vòng pause/confirm/resume. Giấy phép MIT trong `THIRD_PARTY_NOTICES/VoiceGo.txt`. Các module đã đọc không cung cấp neural waveform denoiser; không coi tắt NS hoặc VAD là khử nhiễu đã được kiểm chứng.
