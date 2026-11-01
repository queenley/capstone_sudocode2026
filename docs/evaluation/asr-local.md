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

## Cập nhật neural denoiser tùy chọn

Người dùng đã thêm lại `asr_hard_vi` và yêu cầu đo mới; quyết định xóa cũ là lịch sử, không xóa lại bộ hiện tại. Bộ audio/reference và kết quả mới được giữ ngoài Git. Mặc định `none` + Zipformer greedy; RNNoise bật bằng `ASR_DENOISER=rnnoise`, HTTP/WS config hoặc root runner `--asr-denoiser rnnoise`. Kết quả và cách tái lập ở [neural-denoiser-comparison.md](neural-denoiser-comparison.md). Nhãn entity mới là diagnostic chờ duyệt theo lựa chọn hiện tại của người dùng.


## Entity theo contract scenario

`components/intake/commerce.py` dùng trực tiếp tên trường, kiểu và enum của
`contracts/scenario/scenario-keys.yaml`. `scenario_entities()` trả quan sát theo
contract (ví dụ `size`, `product_advised`, `owned_sku`, `quantity`, `phone_provided`).
Chỉ nhận `product_advised` khi có lời tư vấn, `owned_sku` khi có lời sở hữu;
nhắc tên sản phẩm đơn thuần không thiết lập slot nhớ. Không có thao tác ghi nhớ.
`phone_provided` là bool theo quy ước của team, không chứa số thô.

Adapter `commerce()` giữ các tên riêng của schema ASR để scorer main chấm được:
`sku`, `size_old`, `size_new`, `phone`; các trường ASR-only về phí vẫn nằm ngoài
output contract. Không đổi tên nhãn test hoặc sửa pack BTC. Bộ trích dùng rule,
catalog sản phẩm và lexicon hiện có; không đọc scenario/đáp án để tạo prediction,
không lấy giá, tồn kho hay chính sách từ catalog để điền lời khách chưa nói.
Nhiều sản phẩm không phân biệt được, câu hỏi và khoảng ngày chưa có giá trị đơn
được để trống. Đây chưa phải bộ hiểu mọi trường tự do của contract.

Version đầu là `scenario-commerce-v2`; bản `scenario-commerce-v3` bổ sung
cách đọc chữ cái/mã/model sinh từ catalog và số/ngày/điện thoại/size theo quy tắc
ngôn ngữ dùng chung (`components/intake/spoken.py`). Không thêm alias từ đáp án
của bộ test. Version này tách khỏi version extractor clinical.
Manifest ASR ghi version, SHA256 contract/catalog/lexicon và số mẫu được trích mới;
prediction có cả `entities` cho ASR scorer và `scenario_entities` theo contract.
Hypotheses đã có `entities` được giữ nguyên; muốn thử extractor mới phải replay
bản transcript gốc chưa có entities, qua root `run_eval.py --asr ...
--asr-hypotheses ... --out <new-directory>`. Không chạy lại decoder và không sửa
transcript để cải thiện WER/CER. So bản trích cũ/mới trên cùng transcript là phép
so extractor; không gọi phần chênh lệch đó là cải thiện ASR. Nhãn chưa duyệt vẫn
là diagnostic; metric entity exact-match của main không phạt entity dư, nên xem
cả lỗi thiếu, sai và prediction dư khi đọc kết quả.


Bản `scenario-commerce-v4.1` sửa lỗi nhầm từ “năm” trong số tiền thành đơn vị năm,
giữ giá trị được nói rõ trong câu hỏi và tách mục đích/chủ thể của từng số tiền.
Các cách nói về thanh toán và gia đình bám schema cùng rule fallback của
MemoryAgent. SKU được đối chiếu với tên/model sinh từ catalog và lexicon có sẵn:
cho phép khác khoảng trắng và lỗi nhẹ ở hãng khi toàn bộ model còn nguyên,
nhưng không suy SKU từ hãng đơn thuần, model bị mất, mã ngoài catalog hoặc
nhiều ứng viên. Số thập phân/dung tích và phần tiếp nối của số model được bảo vệ
để 7.4L không thành 74L, 240 không thành 241. Các alias trùng sau khi gộp khoảng
trắng được hợp ứng viên để bỏ qua trường hợp mơ hồ, không chọn theo thứ tự catalog.
Không thêm alias theo đáp án clip.

Điểm entity của ASR runner đo bộ trích rule này; MemoryAgent của sản phẩm có
đường structured-output riêng, nên điểm này không thay thế TSR hay đánh giá
NLU của advisor. Điều tra dùng các đối chứng “reference text → cùng extractor”
và “original written text → cùng extractor” qua root runner để tách lỗi decode
khỏi lỗi trích xuất/nhãn. Các đối chứng text không phải output ASR mới. WER nhóm
clip có tên model có thể khác xa WER toàn tập; một lỗi model ngắn vẫn làm sai
một SKU hoàn toàn. Entity accuracy của main là exact match trên nhãn dương,
không phải phần trăm từ nghe đúng và không phạt prediction dư.

Nhãn gốc đang được giữ nguyên. Những vấn đề về SKU phụ thuộc ngữ cảnh, phone là
CCCD/tài khoản, màu/size/mã đơn chưa canonical và ngày hẹn bị gắn nhãn ngày KM
được đưa vào file review riêng với bằng chứng và trạng thái pending. Không tự
sửa nhãn hay đổi công thức để tăng điểm. Trước một lần đo lại, cố định code,
contract, catalog, lexicon và hash transcript, sau đó dùng output directory mới.

### Tổng quát hóa cho bộ BTC chưa công bố

`scenario-commerce-v5` được phát triển từ contract, tài liệu định dạng ASR của
BTC, catalog nghiệp vụ và các câu kiểm thử bịa độc lập. Không tạo alias, điều
kiện theo ID hay giá trị mặc định từ nhãn seed-dev. Các kiểm thử mới bao gồm phủ
định/đính chính, khoảng giá, trở ngại đã giải quyết, mã model đầy đủ không có
hãng, xung đột catalog, biến thể size/màu, số điện thoại so với tài khoản/CCCD,
Unicode và số/ngày không hợp lệ. Kiểm thử biến đổi thứ tự catalog, giá/tồn kho
không được nói và cách viết kiểm tra các bất biến của bộ trích. Đây là kiểm
thử chức năng, không phải phép đo accuracy trên holdout.

Mặc định input BTC là hội thoại: dùng lượt dự đoán thực (nếu có), sắp theo
`idx` và giữ ranh giới lượt; chọn scalar có bằng chứng theo thời gian và đính
chính. `document.kind=turns` hoặc `document.provenance.unit=segments` dùng chế
độ từng phát ngôn. Không lấy idx, người nói hay ranh giới từ reference để dựng
prediction. Entities người dùng cung cấp được giữ nguyên ở cả parent và turns.
Ngày gọi chỉ lấy từ prediction `context.call_date` hoặc `document.reference_date`;
thiếu cả hai thì dùng reference_date của catalog, được ghi rõ trong manifest.
`price_quoted_vnd` chỉ được thêm khi có metadata người nói agent thực; không
giả định vai người nói từ đáp án. Manifest ghi mode, nguồn clock và số parent/
turn entities được cung cấp hoặc sinh ra.

Catalog/contract được giữ thành snapshot theo đường dẫn thực trong mỗi process;
hash manifest là hash chính snapshot đã dùng, thay file tại cùng đường dẫn cần
khởi động process mới. Đường dẫn catalog mới tạo chỉ mục mới. Quy tắc SKU bỏ
qua model ngắn/generic và model bị mất; model có chữ-số đầy đủ chỉ dùng khi
định danh duy nhất. SKU biến thể chỉ suy ra khi có chọn hàng rõ ràng và size,
màu khớp duy nhất với catalog. Không suy giá, tồn kho hay chính sách.

Quy trình: đạt kiểm thử độc lập → cố định source/asset hash và protocol → một
smoke → một replay toàn bộ transcript đã lưu. Seed-dev chỉ là hồi quy đã thấy,
không phải bộ BTC ẩn hay holdout. Giữ nguyên decoder greedy, transcript, nhãn
gốc và scorer main. Có thể so phần thay đổi của extractor trên cùng transcript,
nhưng phải ghi version và không gọi đó là cải thiện WER/CER hoặc điểm BTC ẩn.
Không tiếp tục sửa rule theo từng lỗi seed-dev sau replay. Commerce v5 chỉ nối
vào ASR benchmark; không thay production MemoryAgent hoặc extractor claims/
questions, và không chứng minh cải thiện TSR/RQR/CCR của agent.
