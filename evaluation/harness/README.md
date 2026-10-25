# Đánh giá AI agent

Thư mục này **chấm điểm AI tư vấn** (`apps/ai-agent-service`) bằng các kịch bản hội thoại có sẵn đáp án.

Mỗi kịch bản được chạy **hai lần**:

- **full**: AI được nhớ khách từ cuộc gọi trước;
- **baseline**: AI không có trí nhớ.

So hai kết quả cho biết trí nhớ giúp được bao nhiêu. Điểm được chấm bằng chính code chấm của BTC (`reference_eval.py`).

Logic của AI không bị sửa để chấm: thư mục `agent/` chỉ khởi động AI thật và nối nó với bộ chấm. Chạy được trên Windows và Linux.

---

## 1. Chuẩn bị (làm một lần)

1. **Bật database**: `docker compose up -d postgres` (từ thư mục gốc repo).
2. **Key AI**: file `.env` ở thư mục gốc có `OPENAI_API_KEY` (hoặc `GEMINI_API_KEY`).
3. **Cài thư viện** (Python 3.12) vào môi trường của AI agent:

   ```powershell
   py -3.12 -m venv apps/ai-agent-service/.venv          # bỏ qua nếu đã có
   apps/ai-agent-service/.venv/Scripts/python -m pip install -r evaluation/harness/requirements.txt
   ```

   [`requirements.txt`](requirements.txt) gồm thư viện của AI agent và của bộ chấm. AI luôn chạy bằng Python trong `apps/ai-agent-service/.venv` (đổi bằng biến `AGENT_PYTHON`), kể cả khi bạn gõ lệnh bằng Python khác.

Mọi lệnh dưới đây chạy **từ thư mục gốc repo**. Cho gọn, đặt trước:

```powershell
$PY = "apps/ai-agent-service/.venv/Scripts/python"
```

---

## 2. Chạy đánh giá trong 3 bước

**Bước 1. Chuyển dữ liệu từ `evaluation/data-generation` sang dạng bộ chấm đọc được** (chỉ chạy một lần):

```powershell
& $PY evaluation/harness/normalize_create_data.py
```

Kết quả: 150/150 kịch bản dùng được, lưu ở `datasets/create-data-diagnostic-v3/`. Lý do loại (nếu có) ghi trong `conversion-report.json`.

- **Lịch sử cuộc gọi cũ** (`seed_history`): trước cuộc gọi, `agent/bridge.py` ghi các phiên cũ và đơn cũ vào trí nhớ của khách, giống lệnh chấm của BTC (`pipeline/eval/runner.py`, hàm `seed`), ở cả hai cấu hình; riêng `baseline_no_memory` không đọc lại chúng.
- **Khách tổng hợp** (`SYN-C...`, 28 kịch bản): ngoài 50 khách của BTC, agent và mock của bộ chấm cùng nạp `apps/ai-agent-service/data/btc/catalog/crm_seed_synthetic.json`. Mỗi lần chạy chép và khóa hash file này (`crm-extension.json`); `BTC_SYNTHETIC_CRM=0` tắt cả hai. Sinh lại khách tổng hợp thì phải sinh lại kịch bản của họ và tạo bản dataset mới (`conversion-report.json` ghi hash file đã dùng).
- Bản cũ vẫn giữ: `v1` (101 kịch bản, không có `seed_history`), `v2` (122, không có khách tổng hợp).

**Bước 2. Kiểm tra trước, không tốn tiền gọi AI:**

```powershell
& $PY evaluation/harness/run_eval.py prepare --dataset-id create-data-diagnostic-v3 --level M2 --limit 5
```

Thấy `"allowed": true` là đầu vào hợp lệ.

**Bước 3. Chạy thật và chấm điểm:**

```powershell
& $PY evaluation/harness/run_eval.py evaluate --dataset-id create-data-diagnostic-v3 --level M2 --limit 5
```

- `--level M2` hoặc `M1`: chỉ chạy một cấp độ. **Bỏ `--level`** thì chạy cả hai, mỗi cấp độ thành một lần chạy riêng (thư mục `<tên>-M1` và `<tên>-M2`), vì một lần chạy chỉ chứa được một cấp độ.
- `--limit 5`: chạy 5 kịch bản đầu (của mỗi cấp độ). **Nên bắt đầu nhỏ**, vì mỗi lượt chat gọi AI nhiều lần, nhân 2 cấu hình. Chạy toàn bộ 150 kịch bản là khoảng 2.500 lượt AI cộng 2.500 lượt chấm, mất nhiều giờ và tốn phí API đáng kể.
- `--only SCN-GEN-0003`: chạy đúng một kịch bản (lặp lại để chọn nhiều kịch bản).
- Trong lúc chạy, màn hình in tiến độ: bước đang làm (1/4 → 4/4), từng lượt chat (khách nói gì, AI trả lời gì, mất bao lâu, tốn bao nhiêu tiền, tổng tiền đến lúc đó) và thời gian ước tính. Mỗi kịch bản mất khoảng 1 phút để khởi động AI. Đặt `$env:EVAL_QUIET="1"` để tắt các dòng này.
- Bước chấm (extract) chạy **song song 6 lượt một lúc**, nhanh hơn khoảng 2 lần. Đổi bằng `$env:EVAL_EXTRACT_WORKERS="4"` (đặt `1` để chạy tuần tự). Không nên đặt quá cao vì OpenAI giới hạn số request mỗi phút.
- Bỏ `--dataset-id`: chạy 5 kịch bản mẫu có sẵn của nhóm.

---

## 3. Đọc kết quả

Mỗi lần chạy tạo một thư mục `evaluation/harness/runs/<ngày-giờ>/`. Bảng điểm in ra cuối lệnh và lưu ở `scored/scorer.stdout.txt`:

```
Chỉ số                                Baseline      Hệ thống
Repeat-Question Rate (%)                  None           0.0
Context Carryover Rate (%)                 0.0           0.0
Task Success Rate (%)                      0.0         100.0
...
```

| Chỉ số | Nghĩa | Tốt khi |
|---|---|---|
| **TSR**, Task Success Rate | Tỉ lệ kịch bản AI làm đúng việc (gọi đúng tool, nói đúng ý) | cao |
| **CCR**, Context Carryover Rate | AI có dùng lại thông tin khách đã nói ở cuộc trước không | cao |
| **RQR**, Repeat-Question Rate | AI có hỏi lại điều khách đã nói không | thấp |
| **HR**, Hallucination Rate | AI có bịa giá, khuyến mãi, tồn kho không | thấp |
| Latency | Thời gian AI trả lời (p50, p95) | thấp |

Các file khác trong thư mục run:

| File | Xem để làm gì |
|---|---|
| `case-trace.json` | Đọc lại từng hội thoại: khách nói gì, AI trả lời gì, gọi tool nào |
| `execution-report.json` | Tóm tắt các giai đoạn, lỗi nếu có |
| `scored/official-report.json` | Điểm chi tiết theo code chấm của BTC |
| `evidence/validation.json` | Những gì còn thiếu bằng chứng |

**Mã thoát của lệnh `evaluate`:** `0` = đạt hết · `1` = chạy xong nhưng AI trượt một số kiểm tra (kết quả bình thường) · `2` = thiếu bằng chứng để kết luận · `3` = lỗi khi chạy.

Thư mục `runs/` có thể chứa dữ liệu khách nên **không đưa lên Git**.

---

## 4. Theo dõi chi phí trên Langfuse

Mỗi lần `evaluate` chạy xong, số token và **số tiền (USD)** được tự động ghi lên Langfuse, kèm điểm TSR/CCR/RQR/HR. Chỉ ghi con số, không ghi nội dung hội thoại hay dữ liệu khách.

1. Đặt khóa trong `.env` (một lần): `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (ví dụ `https://cloud.langfuse.com`). Đây cũng là khóa mà AI dùng để trace.
2. Mở Langfuse → **Tracing**, lọc theo tên trace **evaluation-run** (môi trường `evaluation`). Các lần chạy cùng bộ dữ liệu nằm chung session `eval:<dataset>`.

Mỗi lần chạy là một trace:

| Trong trace | Nghĩa |
|---|---|
| Generation `agent:full:<kịch bản>`, `agent:baseline:<kịch bản>` | Token và tiền của AI theo từng kịch bản và cấu hình — Langfuse tự cộng vào cột Cost |
| Generation `extractor` | Token và tiền của model chấm (đọc câu trả lời) |
| Score `total_cost_usd` | Tổng tiền của lần chạy (AI + chấm) |
| Score `full_cost_usd`, `baseline_cost_usd`, `extractor_cost_usd` | Tiền theo từng phần |
| Score `cost_per_turn_usd` | Tiền trung bình mỗi lượt chat |
| Score `*_input_tokens`, `*_output_tokens` | Số token |
| Score `full_tsr`, `baseline_tsr`, ... | Điểm, để so chi phí với chất lượng |

- **Giá** lấy từ `apps/ai-agent-service/config/models.yaml` (`input_token_price_per_million`, `output_token_price_per_million` của từng provider). Hiện đã đặt giá OpenAI `gpt-4.1-mini`; Gemini chưa có giá nên chỉ ghi token (`agent_priced = 0`). Đổi model thì cập nhật giá ở đó.
- **Ghi lại lần chạy cũ** (hoặc khi lúc chạy chưa có khóa / mất mạng): `& $PY evaluation/harness/run_eval.py langfuse-log --run evaluation/harness/runs/<tên>`. Mỗi lần chạy chỉ được ghi một lần; thêm `--force` để ghi lại.
- Trong lúc chạy, từng lời gọi model của AI cũng tự lên Langfuse (trace của LangChain), nếu muốn xem chi tiết.

---

## 5. Đánh giá ASR (AI nghe lời khách đúng đến đâu)

Đo **WER/CER** (tỉ lệ sai từ/ký tự) và **entity accuracy** (nghe đúng ngân sách, diện tích, cách thanh toán…) của mô hình nhận dạng giọng nói mà agent dùng, bằng hàm `wer_cer` của BTC. **Không gọi LLM, không tốn phí API**; chỉ cần `asr-service` đang chạy.

### 5.1 Dữ liệu đi qua những đâu

```text
create_data: synthesize_scenario_audio (ElevenLabs)
   evaluation/data-generation/output/audio/scenarios_SCN-GEN-xxxx/call_N/turn_K.wav + .json     ← mỗi file = 1 lượt nói của khách
        │  run_eval.py asr-build   (lọc, đổi sang định dạng BTC, ghi hash)
        ▼
   evaluation/harness/datasets/asr-team-v2/
        ground_truth.json          đáp án (định dạng asr/ground_truth.json của BTC)
        audio/<id>.wav             PCM16, mono, 16 kHz (không lên Git, xem 5.5)
        conversion-report.json     giữ/loại bao nhiêu clip, vì sao, hash từng file
        │  run_eval.py asr         (gửi từng clip tới asr-service, chấm bằng wer_cer của BTC)
        ▼
   evaluation/harness/runs/asr/<ngày-giờ>-<model>/
        raw/      ground_truth.json + hypotheses.json   chữ mô hình nghe được
        lexicon/  ground_truth.json + hypotheses.json   sau khi sửa bằng lexicon của agent (cái AI tư vấn thực sự đọc)
        report.json                                     điểm, phân theo loại nhiễu, clip sai nhiều nhất
```

**Định dạng một mục trong `ground_truth.json`** (các trường BTC đọc: `id`, `full_text`, `noisy`, `entities`; các trường còn lại để tra cứu):

```json
{
  "id": "SCN-GEN-0001-call_1-t2",
  "full_text": "chị nhớ là phòng mình khoảng hai mươi lăm mét vuông, không có trẻ nhỏ đâu.",
  "noisy": false,
  "entities": {"room_area_m2": 25, "has_children": false},
  "turns": [{"idx": 1, "speaker": "C", "text": "…", "entities": {…}}],
  "source_text": "Chị nhớ là phòng mình khoảng 25 mét vuông, không có trẻ nhỏ đâu.",
  "noise": "clean", "snr_db": null, "input_mode": "text", "number_or_code": true,
  "customer_region": "bac", "voice_id": "…", "duration_seconds": 4.0,
  "source_clip": "scenarios_SCN-GEN-0001/call_1/turn_2.json"
}
```

- `full_text`: câu gốc đổi sang **dạng đọc** bằng `evaluation/data-generation/src/asr/spoken.py` theo quy ước ground truth của BTC: số viết bằng chữ; số điện thoại, CCCD, số tài khoản đọc từng chữ số; `COD` thành "cê ô đê"; `4.5L` thành "bốn phẩy năm lít"; `TP.HCM` thành "thành phố hồ chí minh".
- `entities`: lấy từ `full_text` bằng `evaluation/data-generation/src/asr/entities.py`, cũng là bước áp lên chữ mô hình nghe được (ITN của agent). Bản chép đúng từng chữ được 100%.
- `hypotheses.json` (do lệnh `asr` tạo): `{"<id>": {"text": "...", "entities": {...}}}`, đúng `hypotheses_format` của BTC.

### 5.2 Các bước chạy

Mọi lệnh chạy từ thư mục gốc repo, `$PY` như ở mục 1.

**Bước 0. Bật dịch vụ ASR** (một lần). File `docker-compose.override.yml` mở cổng `127.0.0.1:8500` cho máy local:

```powershell
docker compose up -d asr-service
curl http://127.0.0.1:8500/v1/models        # thấy zipformer-30m "loaded": true là sẵn sàng
```

Lần đầu dịch vụ tự tải trọng số vào volume `voice-models`. Nếu `.env` có `ASR_API_KEY`, lệnh `asr` tự đọc và gửi kèm.

**Bước 1. Có audio nguồn.** Kiểm tra thư mục `evaluation/data-generation/output/audio/` đã có các thư mục `scenarios_SCN-GEN-*`. Nếu chưa có hoặc thiếu (cần key ElevenLabs, tốn ký tự):

```powershell
cd evaluation/data-generation
.venv/Scripts/python -m src.pipeline.synthesize_scenario_audio --limit 150 --resume   # --resume: bỏ qua lượt đã có
cd ../..
```

**Bước 2. Lọc audio thành bộ chấm** (vài giây, không gọi model):

```powershell
& $PY evaluation/harness/run_eval.py asr-build                      # tạo datasets/asr-team-v2
& $PY evaluation/harness/run_eval.py asr-build --set-id asr-team-v3 # khi audio hoặc kịch bản đã đổi: luôn dùng tên mới
```

Một clip chỉ được giữ khi đạt **tất cả** các điều kiện sau. Clip bị loại được ghi vào `conversion-report.json` → `dropped` cùng lý do.

| Điều kiện | Lý do loại |
|---|---|
| Có file `.wav` cạnh file `.json` | `wav_missing` |
| Kịch bản, cuộc gọi và lượt vẫn còn trong `evaluation/data-generation/output/scenarios_internal/` | `scenario_missing`, `call_missing`, `turn_out_of_range` (clip cũ của bản kịch bản trước) |
| Câu trong `.json` trùng đúng lượt nói hiện tại của kịch bản | `text_changed` (audio cũ, kịch bản đã sinh lại) |
| Không phải `input_mode: chat_teencode` (chữ chat như "ko", "dc", người gọi không nói vậy) | `not_speech` |
| WAV đọc được, PCM16 mono 16 kHz, không rỗng, dài đúng `duration_seconds` ± 0,05 s | `wav_unreadable`, `wav_format`, `wav_empty`, `wav_length_mismatch` |

Lệnh không bao giờ ghi đè một bộ đã có. Muốn tạo lại thì dùng `--set-id` mới. Riêng bộ chưa được lần chạy nào dùng thì xóa thư mục rồi chạy lại. Bộ mới phải được thêm vào `asr_sets` trong `datasets/registry.json`.

**Bước 3. Kiểm tra bộ chấm** (không gọi model). Lệnh xác nhận mọi `id` có file WAV đúng định dạng và hash khớp `conversion-report.json`:

```powershell
& $PY evaluation/harness/run_eval.py data-check --set asr-team-v2
```

Thấy `"issues": []` là được. `"allowed": false` là bình thường vì bộ còn `diagnostic`, chưa có người duyệt.

**Bước 4. Chạy đánh giá:**

```powershell
& $PY evaluation/harness/run_eval.py asr --limit 10                       # thử 10 clip trước
& $PY evaluation/harness/run_eval.py asr                                  # cả bộ, model zipformer-30m của agent
& $PY evaluation/harness/run_eval.py asr --model phowhisper-small         # so một model khác
```

| Tùy chọn | Nghĩa |
|---|---|
| `--set asr-team-v2` | Bộ trong `datasets/` (mặc định `asr-team-v2`) |
| `--model` | `zipformer-30m` (agent đang dùng, `voice.asr` trong `config/models.yaml`), `zipformer-2025`, `phowhisper-small`, `whisper-turbo`. Danh sách có trọng số: `GET /v1/models` |
| `--url` | Địa chỉ dịch vụ ASR (mặc định `http://127.0.0.1:8500`; GPU thuê thì đổi ở đây) |
| `--limit N` | Chỉ N clip đầu |
| `--no-hotwords` | Không gửi danh sách hotword của agent (Zipformer bỏ qua hotword, Whisper thì dùng) |
| `--hypotheses file.json` | Chấm một `hypotheses.json` có sẵn (ví dụ do hệ khác sinh) thay vì gọi dịch vụ |
| `--out` | Thư mục kết quả (mặc định `runs/asr/<ngày-giờ>-<model>`; phải chưa tồn tại) |

Mã thoát: `0` xong và đủ hypothesis · `2` thiếu hypothesis cho một số clip · `3` lỗi (dịch vụ không chạy, bộ chấm hỏng…).

**Bước 5. Đọc `report.json`:**

| Trường | Nghĩa |
|---|---|
| `raw.official` / `lexicon.official` | Kết quả `wer_cer` của BTC: `WER`, `CER`, `entity_accuracy`, `wer_noisy`, `wer_clean` (%) |
| `raw.breakdown` / `lexicon.breakdown` | WER trung bình theo `noise:*` (clean, cafe, street, weak_signal, wind), `input_mode:*`, `number_or_code:yes/no` |
| `worst_clips_lexicon` | 25 clip sai nhiều nhất: câu đáp án và câu nghe được, để nghe lại và tìm lỗi |
| `rtf_mean` | Thời gian nhận dạng chia độ dài audio (dưới 1 là nhanh hơn thời gian thực) |
| `timing` | Thời gian từng clip |

`raw` là chữ mô hình trả về. `lexicon` là chữ sau khi agent sửa bằng `voice.lexicon` (ví dụ "e pia" thành "AirPure"), tức chữ mà AI tư vấn thực sự nhận. Đáp án của bộ team giữ tên hãng theo catalog ("airpure", "karofi"), nên **trên bộ team hãy xem `lexicon`**. Đáp án của BTC viết tên hãng theo cách đọc ("e pia x", "ka rô phi"), nên trên bộ BTC hãy xem `raw`.

### 5.3 Kết quả hiện tại

Ngày 25/10/2026, bộ `asr-team-v2` (674 clip, 85 kịch bản, 0,62 giờ audio), model `zipformer-30m` qua `asr-service` trên CPU (Docker, Windows, 4 luồng):

| Chỉ số | Giá trị |
|---|---|
| WER / CER | **6,2%** / 4,2% |
| Entity accuracy | **97,1%** (170/175; 96,0% trước khi sửa ITN, xem dưới) |
| WER clean / có nhiễu | 4,3% / 6,9% |
| WER theo nhiễu | wind 3,3% · clean 4,3% · street 4,4% · cafe 4,6% · **weak_signal 15,9%** |
| WER câu có số, mã, viết tắt / câu thường | 8,7% (240 clip) / 4,0% (434 clip) |
| RTF trung bình | 0,385 (cả bộ mất khoảng 15 phút) |

`raw` và `lexicon` cho cùng điểm: lexicon chỉ sửa được 7 câu, vì các lỗi Zipformer thực sự mắc không nằm trong `voice.lexicon`.

Lỗi lặp lại nhiều nhất, đếm theo cụm từ:

| Lỗi | Số lần | Ghi chú |
|---|---:|---|
| "size" → "sai" / "cice" / "side" | 27 | Zipformer viết theo âm tiếng Việt |
| "chị" → "chỉ" | 21 | Sai dấu thanh; không ảnh hưởng ý nhưng làm tăng WER |
| "AirPure Pro" → "epiopro", "AirPure" → "epio" / "el" | khoảng 17 | Tên sản phẩm, rõ nhất khi tín hiệu yếu |
| "COD" ("cê ô đê") → "ceo d" / "cood" / "c o d" | khoảng 20 | Entity `payment` vẫn đúng nhờ ITN của agent |
| "ngàn" → "nghìn" | 6 | Hai cách nói cùng nghĩa; vẫn bị tính là lỗi |

5 entity còn sai, đều do mô hình nghe sai:
- 3 ca sai số hoặc từ khóa: "ba mươi lăm" thành "hai mươi lăm", mất chữ "trăm", "ngân sách" thành "gấp".
- 2 ca cắt câu hoặc nghe nhầm: "chuyển khoản" thành "chuyển", "trẻ" thành "thịt".

Lần chạy này cũng tìm ra một **lỗi ITN của agent** (`components/intake/itn.py`), đã sửa ngày 25/10/2026. Chữ "không" đứng sau một số bị ghép vào số: "bốn triệu tám không biết" thành 4.000.080đ, "giá năm triệu hai không em" thành 5.000.020đ, "size bốn mốt không em" thành 410. ASR không trả về dấu câu, nên với giọng nói thì mọi câu hỏi kiểu "…không?" đều gặp lỗi này.

### 5.4 Giới hạn, cần biết khi đọc số

- **Mỗi clip là một lượt nói đơn lẻ của khách**, giọng tổng hợp ElevenLabs, nhiễu thêm nhân tạo (SNR 6 dB). Bộ của BTC là cả cuộc hội thoại hai người, giọng thật hơn. Đừng so trực tiếp hai con số.
- **Không đo diarization (M2)**: mỗi clip chỉ có một người nói. Muốn đo thì dùng bộ hội thoại `build_asr_testset` của `create_data` (`python -m src.pipeline.eval_asr --set team --transcribe --diarize …`, xem `docs/evaluation/asr/README.md`).
- **Đáp án do luật sinh ra, chưa có người duyệt** (`status: diagnostic`). Câu có số, mã hoặc từ viết tắt (`number_or_code: yes`) được chấm theo cách ta *đoán* giọng đọc đã đọc. Nếu clip loại này sai, hãy nghe lại file trước khi kết luận lỗi do mô hình.
- **Audio D01–D04 của BTC không có trong repo** (chỉ có `ground_truth.json`). Khi có audio: đặt vào `evaluation/data-generation/data/asr/audio/<id>.wav`, tạo `hypotheses.json` rồi chấm bằng `python -m src.pipeline.eval_asr --set btc --hypotheses <file>` (trong `evaluation/data-generation`).
- Không chỉnh lexicon hay hotword dựa trên các clip của bộ này rồi báo điểm trên chính bộ đó: như vậy là học thuộc đáp án. Lỗi phát hiện ở đây phải được xác nhận trên cuộc gọi thật trước khi thêm vào `voice.lexicon`.

### 5.5 Vì sao audio không lên Git

`datasets/asr-*/audio/` nặng khoảng 71 MB nên nằm trong `.gitignore`. Git chỉ giữ `ground_truth.json` và `conversion-report.json`, trong đó có hash SHA-256 của từng WAV. Trên một bản clone mới (thư mục bộ đã có nhưng thiếu `audio/`), chép audio về từ `evaluation/data-generation/output/audio/`:

```powershell
& $PY evaluation/harness/run_eval.py asr-build --restore        # chép theo source_clip, kiểm hash từng file
```

Clip nào thiếu hoặc khác hash sẽ không được chép mà liệt kê trong `missing_or_changed` (mã thoát 2). Khi đó audio nguồn đã đổi: tạo bộ mới bằng `--set-id asr-team-v3`.

---

## 6. Các lệnh khác

| Lệnh | Làm gì | Gọi AI? |
|---|---|---|
| `run_eval.py history` | Liệt kê mọi lần chạy cũ và điểm của chúng | Không |
| `run_eval.py data-check --set create-data-diagnostic-v3` | Kiểm tra bộ dữ liệu có hợp lệ không | Không |
| `run_eval.py asr-build` | Lọc audio của `create_data` thành bộ chấm ASR (mục 5) | Không |
| `run_eval.py asr` | Chấm ASR qua `asr-service` bằng `wer_cer` của BTC (mục 5) | Không (chỉ model ASR local) |
| `run_eval.py rag-recall --out evaluation/harness/runs/rag-1` | Đo khả năng tìm đúng đoạn chính sách (Recall@3/@5 trên 60 câu BTC) | Không |
| `python evaluation/harness/evaluate.py` | Bản đo Recall nhanh, cũ hơn, không cần database | Không |

Đổi model:

- `--advisor openai:gpt-4.1-mini`: model AI tư vấn (mặc định lấy theo `apps/ai-agent-service/config/models.yaml`).
- `--extractor openai:gpt-4.1-mini`: model đọc câu trả lời để chấm (mặc định OpenAI khi có key).

---

## 7. Gặp lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `Postgres is not reachable` hoặc treo rất lâu lúc khởi động | Bật `docker compose up -d postgres`. Dùng `127.0.0.1`, không dùng `localhost`, trong URL database (trên Windows `localhost` làm mỗi server chậm vài phút) |
| `No API key for provider ...` | Thêm key vào `.env` ở thư mục gốc |
| Gemini báo 402 `RESOURCE_EXHAUSTED` | Hết tiền tài khoản Google; dùng `--advisor openai:gpt-4.1-mini` |
| `The selection mixes levels` | Thêm `--level M1` hoặc `--level M2` |
| `Choose a new run directory` | `--out` đã tồn tại; chọn tên khác |
| Nhiều lượt chấm báo `OpenAIConnectionError` | Đã xử lý tự động trên Windows (dùng bộ chứng chỉ `certifi`). Nếu vẫn gặp, giảm `EVAL_EXTRACT_WORKERS` |
| `Langfuse not reachable` / `Langfuse keys not set` | Kiểm tra mạng và khóa `LANGFUSE_*` trong `.env`, rồi ghi lại bằng `run_eval.py langfuse-log --run ...` |
| `ASR service at http://127.0.0.1:8500 not reachable` | `docker compose up -d asr-service`; kiểm tra `docker-compose.override.yml` có `ports: ["127.0.0.1:8500:8500"]` cho `asr-service` |
| `asr-team-v2 fails its offline check` | Chạy `data-check --set asr-team-v2` xem lỗi; thiếu `audio/` thì `asr-build --restore` |
| `... exists: a used revision is never overwritten` | `asr-build` không ghi đè; dùng `--set-id` mới (hoặc `--restore` nếu chỉ thiếu audio) |
| `The agent's code changed after preparation` | Đã sửa code AI sau bước `prepare`; chạy lại `evaluate` từ đầu |

---

## 8. Cấu trúc thư mục

```text
run_eval.py               Điểm vào của mọi lệnh
product.py                Chuẩn bị đầu vào, chạy, thu bằng chứng, chấm
product_adapter.py        Cầu nối giữa bộ chấm và AI (chạy AI ở tiến trình riêng)
agent/                    Khởi động AI thật của repo cho bộ chấm
  launch.py               Đọc .env, chọn database, chọn key
  bridge.py               Nhận từng lượt chat từ bộ chấm, đưa vào AI
  runner.py               Lắp ráp AI giống như khi chạy thật
  extract_command.py      Gọi model để trích câu hỏi/khẳng định trong câu trả lời
  spend.py                Tính tiền từ số token và giá trong models.yaml
  langfuse_log.py         Ghi chi phí và điểm của một lần chạy lên Langfuse
normalize_create_data.py  Chuyển dữ liệu create_data thành bộ dữ liệu chấm
datasets/                 Các bộ kịch bản (registry.json là danh sách)
eval_harness/             Code chấm
  asr_eval.py             Lọc audio thành bộ ASR, gọi asr-service, chấm wer_cer (mục 5)
evaluation-contracts/     Định dạng và dữ liệu gốc của BTC (không sửa)
tests/                    Test không gọi AI
docs/                     Quy tắc gán nhãn, lỗi đã gặp, các luồng cải tiến
runs/                     Kết quả các lần chạy (không lên Git)
```

---

## 9. Cách hoạt động (cho người muốn hiểu sâu)

1. `prepare` sao chép và "khóa" (hash) mọi đầu vào: kịch bản, nhãn, code AI. Code AI bị sửa giữa chừng thì lần chạy bị từ chối, để kết quả luôn ứng với đúng một phiên bản code.
2. `evaluate` mở AI trong một tiến trình riêng cho từng kịch bản và từng cấu hình. Các tool nghiệp vụ (giá, tồn kho, đơn hàng) **không** chạy trong AI mà được trả lời bởi bản mock của BTC nằm trong bộ chấm, để biết chính xác AI đã gọi gì và làm thay đổi gì.
3. Trí nhớ và chính sách vẫn chạy qua server MCP của AI, trên schema database riêng `agent_eval`, được xóa trước mỗi kịch bản. Dữ liệu thật trong schema `agent` không bị đụng tới.
4. Sau khi chạy, một model "extractor" đọc từng câu trả lời để tách câu hỏi, khẳng định (giá, tồn kho, ...) và thông tin được dùng lại; code chấm của BTC tính điểm từ đó.
5. Không thử lại khi lỗi: mọi lần gọi AI hay tool thất bại đều được ghi nhận như nó xảy ra.

Biến môi trường có thể đổi: `EVAL_DB_SCHEMA` (mặc định `agent_eval`, phải kết thúc bằng `_eval`), `EVAL_DATABASE_URL`, `AGENT_PYTHON` (Python dùng để chạy AI).

---

## 10. Quy tắc khi sửa dữ liệu hoặc code chấm

- **Trước khi sửa code** trong thư mục này: đọc [lỗi đã gặp và guardrail](docs/CODING-INCIDENTS-AND-GUARDRAILS.md).
- **Trước khi thêm hoặc sửa kịch bản, đáp án, nhãn:** đọc [hướng dẫn duyệt ground truth](datasets/ground-truth-review/SKILL.md). Tóm tắt:
  - không sửa dữ liệu gốc, luôn tạo bản (revision) mới;
  - nhãn do máy sinh chỉ là `diagnostic`; muốn `approved` phải có người duyệt từng cuộc gọi;
  - không đổi điều kiện chấm sau khi đã xem điểm.
- Các bộ dữ liệu hiện có:
  - `output1-diagnostic-v2`: 5 kịch bản mẫu, mặc định ([quyết định duyệt](datasets/output1-btc-diagnostic-v2/review-decisions.md));
  - `create-data-diagnostic-v3`: 150 kịch bản từ `create_data`, gồm cả `seed_history` và khách tổng hợp, nhãn chờ duyệt;
  - `create-data-diagnostic-v2`: bản cũ, 122 kịch bản, không có khách tổng hợp;
  - `create-data-diagnostic-v1`: bản cũ, 101 kịch bản, không có `seed_history`;
  - `asr-team-v2` (trong `asr_sets`): 674 lượt nói của khách có audio, cho đánh giá ASR (mục 5), nhãn chờ duyệt.

Chạy test của bộ chấm:

```powershell
Set-Location evaluation/harness
& ../../apps/ai-agent-service/.venv/Scripts/python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

---

## 11. Tính năng nâng cao

Đã có trong bộ chấm nhưng chưa nối hết vào AI:

- **Knowledge Gap:** mỗi lần chấm tạo `scored/knowledge-gap-candidates.json`, danh sách các lượt AI phải chuyển người hoặc nói "chưa có thông tin". Người duyệt chọn câu nào nên thành FAQ (`gap-publish`), rồi kiểm tra lại (`gap-check`). Hiện AI **chưa** tự dùng FAQ mới. Chi tiết: [luồng Knowledge Gap](docs/flows/KNOWLEDGE-GAP-LOOP.md).
- **Reflection / playbook:** từ đánh giá cuộc gọi rút ra bài học cho AI. Xem [luồng Reflection](docs/flows/REFLECTION-FLOW.md).
- **Exemplar bank:** đang tạm hoãn, xem [thiết kế](docs/flows/EXEMPLAR-BANK-FLOW.md).
- Báo cáo phụ trong mỗi run: `scored/claim-adjudication.json` (khẳng định khác đáp án nhưng có thể tương đương) và `scored/tool-business-error-review.json` (tool lỗi và AI có tự sửa không). Hai file này không thay đổi điểm chính thức.

Đề bài gốc: [requirements/project-brief.pdf](requirements/project-brief.pdf).
