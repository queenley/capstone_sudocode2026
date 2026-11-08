# Nhật ký cải tiến

Mỗi lần sửa case sai hoặc thêm tính năng, thêm một mục vào đây, mới nhất ở trên. Cách ghi: [skill `improvement-log`](../../.claude/skills/improvement-log/SKILL.md). Đề xuất trước khi code vẫn nằm ở [README](README.md) và [backlog](BACKLOG.md); file này ghi những gì đã làm và kết quả thật.

Trạng thái: `đang đo` (đã code, chưa có số trước/sau) · `xong` (có số đo) · `bỏ` (quay lui, ghi lý do).

## Mẫu

```markdown
### YYYY-MM-DD · Tên cải tiến

Loại: ... · Trạng thái: ... · Chỉ số: TSR / CCR / RQR / HR / latency / ...

- **Vấn đề:**
- **Bằng chứng:**
- **Sửa:**
- **Đã kiểm:**
- **Số đo:** trước ... / sau ..., cohort ..., hoặc `chưa đo`
- **Còn lại:**
```

## Các mục

Sáu mục đầu được ghi lại sau khi làm, từ đợt sửa ngày 05-06/11/2026. Chưa mục nào có số đo trên agent thật.

### 2026-11-08 · Redesign frontend theo taste-skill

Loại: tính năng · Trạng thái: xong · Chỉ số: bố cục (`check.mjs`), copy-lint, e2e

- **Vấn đề:** cửa hàng và trang nhân viên dùng font Inter và chữ 700/800, nhãn viết hoa giãn chữ, gradient, chữ 8–11px. Trang chủ là một chuỗi khối không theo hệ lưới.
- **Bằng chứng:** chạy kit của skill `Leonxlnx/taste-skill` (plugin không cài được trong môi trường này, nên clone repo và theo `SKILL.md`). Lần đo bố cục đầu tiên: khung chat lệch 28px, trang cuộn ngang ở 390px, hero ở 390px cao hơn một màn hình. `consistency.mjs` lần đầu: 78 FAIL ở 5 cỡ màn hình.
- **Sửa:** bốc thăm theo skill, không chọn tay: palette white-navy-tab, hero product, nav-split, footer-columns, close-type, brand-band, nút pill, moment photo-chapters. Font Work Sans, vì ba cặp font bốc được (Besley, Outfit, Red Hat) không có dấu tiếng Việt. Kit chép vào `apps/web/public/assets`; bảng màu và CSS riêng của trang ở `public/assets/site.css`. `theme.css` lấy token mới cho toàn frontend; độ đậm chữ tối đa 500; trang nhân viên bỏ nhãn viết hoa, gradient và chữ dưới 13px. Header, Footer và trang chủ viết lại theo markup của kit. Các trang ứng dụng được bọc `.s-app`, nên luật "mỗi section một màn hình" chỉ áp cho trang chủ. Cửa hàng luôn nền sáng; trang nhân viên vẫn đổi được sáng/tối. Thêm trang credit ảnh `/anh` và thẻ og. `KitMotion` gọi lại `motion.js` và mount moment sau mỗi lần chuyển route.
- **Đã kiểm:** `check.mjs` ở 1440/1024/820/768/390: không còn lỗi nào ngoài `hero-lines`, đã ghi waiver. copy-lint: 0 FAIL, 0 WARN. Gate round 2: 1 FAIL (`section-gaps` ở 390px), kèm 5 waiver ghi trong `.taste-skill/waivers.json`. Round 3: `GATE: ERROR`, vì `consistency.mjs` chạy quá 9,5 phút trên Edge chạy bằng CPU. e2e trên bản production: xem "Số đo".
- **Số đo:** e2e trên bản production (`next build` + `next start`, build trước khi có merge): 55 pass, 4 fail, 7 skip. Cả 4 fail nằm trong `e2e/redesign-snapshots.spec.ts`, file đến từ một nhánh khác đang merge dở (bộ lọc theo diện tích phòng, thông số trên card, call console). Đó là tính năng của nhánh kia, bản này chưa có. Trước redesign, trên dev server, 5 test fail do route biên dịch chậm và Fast Refresh; bản production không bị. Test `expired responses...` đã chập chờn từ trước: bản cũ trong docker fail 3/3, bản mới pass 2/3.
- **Còn lại:** chưa redesign bố cục các trang ứng dụng (danh mục, sản phẩm, giỏ hàng, thanh toán) và trang nhân viên; mới đổi token. 5 waiver: nút chat nổi (skill cấm, nhưng đó là sản phẩm), hotline thật, bảng chính sách và FAQ không ảnh, lưới tile đồng dạng, `hero-lines`. Ảnh trang chủ là stand-in (Wikimedia, Flickr), cần thay bằng ảnh thật của shop. Bài học về công cụ: profile Chrome của kit nằm trong `apps/web` làm Tailwind quét treo dev server; Tailwind sinh `.grid` và `.start-7` trùng tên với class kit; Next dev chặn hydrate khi mở bằng `127.0.0.1`.

### 2026-11-07 · Ảnh cho 13 sản phẩm còn thiếu

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không có (giao diện)

- **Vấn đề:** 13 sản phẩm hiện hình vẽ thay cho ảnh.
- **Bằng chứng:** `data/seed/catalog/README.md` liệt kê 13 mã không có ảnh phù hợp trên Openverse ngày 2026-10-25.
- **Sửa:** `scripts/seed/product_images.py --candidates` với từ khóa rộng hơn, xem từng bảng ứng viên, chọn bằng `--use`. Ảnh lưu ở `apps/web/public/products`, credit ở `product_images.json`.
- **Đã kiểm:** xem bảng tổng hợp 13 ảnh mới; thay ảnh `XM-4P` vì ảnh đầu tiên không thấy máy.
- **Số đo:** 40/40 sản phẩm có ảnh.
- **Còn lại:** vài ảnh chỉ gần đúng loại hàng (máy lọc nước nóng lạnh cho RO, bình sữa cho máy hâm và máy tiệt trùng). Cần chạy lại seed để ảnh vào database: `docker compose run --rm seed`.

### 2026-11-08 · Chỉ đọc lại đơn khi đủ thông tin, và "đồng ý" kèm từ đệm vẫn tạo được đơn

Loại: hard guard, prompt · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** 23 cuộc trong `eval2` trượt TSR vì không có `order.create` nào (`success_if` chờ `order.create` khớp `args_match`). Khi trả lời câu agent đọc lại đơn, khách thường đưa thông tin còn thiếu chứ không nói "đồng ý", nên câu đọc lại bị phí. Còn khi khách đã đồng ý thì đơn vẫn không được tạo.
- **Bằng chứng:** `evaluation/runs/eval2-full-relabel-3`. Trong 23 cuộc, 19 có `pricing.get_quote` lỗi `BAD_ENVELOPE` vì tham số `payment` (đã sửa ở mục "Tham số thừa…", sau khi chạy run này); 13 cuộc đọc lại đơn ở lượt cuối nên không còn lượt để khách xác nhận. Trên toàn run có 153 câu trả lời ngay sau câu đọc lại đơn: 116 không phải lời đồng ý (phần lớn là địa chỉ hoặc cách thanh toán, ví dụ SCN-ADV-0018 call_2 lượt 3 "Giao hàng cho chị ở Thủ Đức"); 35 được `purchase.answer()` (qua `agrees()`) nhận là đồng ý nhưng không có đơn, trong khi `purchase.matches()` đòi `YES.fullmatch`; chỉ 2 tạo được đơn. `agrees()` còn từ chối "Ừ, vậy em lên đơn cho anh luôn đi." (SCN-GEN-0232) và "Chị đồng ý lên đơn rồi, em làm cho chị nhé." (SCN-GEN-0240). Mẫu BTC: cả 5 cuộc chấm `order.create` đều để khách nói "lên đơn" ở lượt cuối.
- **Sửa:** (1) `ActionGuardMiddleware` trả `ORDER_INCOMPLETE`, kèm phần còn thiếu và không phát hành bản nháp, khi đơn thiếu thanh toán do model truyền, thiếu địa chỉ (lấy từ lời khách hoặc bộ nhớ qua `order_arguments`) hoặc thiếu ngày giao từ `delivery.estimate` (`purchase.missing`, `purchase.estimated_delivery`). Câu đọc lại có thêm "giao dự kiến ngày …" (PB-09). Rule 12 trong `rule_packs.yaml` bỏ "thiếu địa chỉ hay thanh toán không phải lý do chờ / tự đặt COD": giờ chỉ hỏi phần còn thiếu, và gọi `order_create` ngay khi khách vừa đưa thông tin cuối cùng, để câu "chốt đơn" kế tiếp là lời xác nhận. (2) `purchase.matches()` dùng `agrees()`, cùng quy tắc với `answer()`; các điều kiện khác giữ nguyên: đúng câu đọc lại ở lượt trước, cùng nội dung đơn, còn trong 300 giây, có biên nhận HMAC. (3) `COURTESY` thêm "vậy", "làm"; câu có "nhưng", "đổi", "thêm", "chuyển khoản" vẫn không được tính là đồng ý.
- **Đã kiểm:** thêm 12 test trong `tests/agent/test_ec03_confirmation_isolation.py` (đơn thiếu từng trường; câu đọc lại có ngày giao; 4 câu đồng ý kèm từ đệm tạo được đơn; 4 câu có ý đổi đơn bị từ chối). Fixture được cập nhật cho đơn đủ thông tin. Kế hoạch mua sai trên kênh khác giờ dừng ở `ORDER_INCOMPLETE`, không còn tạo bản nháp. `tests/agent`: 1.285 passed; 11 failed và 14 errors đều nằm ở ASR và voice (`test_asr_*`, `test_voice_transport`), các file không bị đổi trong mục này.
- **Số đo:** chưa đo.
- **Còn lại:** khi lần đầu khách nói muốn mua lại rơi vào lượt cuối (như SAMPLE-02, SAMPLE-04, SAMPLE-05 của BTC), vẫn không còn lượt để xác nhận: đây là đánh đổi đã chọn (xác nhận trước khi tạo đơn). Số lượng mặc định là 1 khi khách không nói, và được đọc lại để khách sửa. Cần chạy lại các cuộc `order.create` của `eval2`, trước hết một kịch bản (SCN-ADV-0018).

### 2026-11-07 · Extractor v11: entity nạp từ contract, thêm today và crm_history

Loại: evaluation · Trạng thái: đang đo · Chỉ số: RQR, HR, CCR (đổi dụng cụ đo)

- **Vấn đề:** từ vựng của extractor được viết tay, lệch khỏi `contracts/scenario/scenario-keys.yaml`. Slot `return_reason` và `tracking` có trong contract nhưng extractor không có, nên câu hỏi về hai slot này bị gán `other` và RQR không thấy. `callback_at`, `gift_sku`, `new_variant_sku`, `successor_sku`, `price_vnd:<SKU>` và `future_promo_disclosed` có trong `ground_truth_facts` nhưng không bao giờ được trích, nên HR không kiểm các trường này. Fact lấy từ hồ sơ CRM (`seed_history`) không được tính là `facts_used`. Relabel `eval2` 3.592 lượt chạy nhiều giờ.
- **Bằng chứng:** so `scorers.vocabulary()`/`CLAIM_FIELDS` với contract: thiếu `return_reason`, `tracking`. Các trường claim mới xuất hiện trong kịch bản của `evaluation/runs/eval2-full-relabel-3/scenarios` (ví dụ `gift_sku` 51 lần, `callback_at` dạng `2026-10-19T19:00`). Về tốc độ: giới hạn OpenAI trong `models.yaml` là 200k token đầu vào/phút (giữ lại 10%). Mỗi lượt khoảng 6,6k token prompt cộng lịch sử, nên chỉ chạy được khoảng 20 lượt/phút. Ngoài ra cache 5,9 MB được ghi lại toàn bộ sau mỗi lượt, ngay trên event loop.
- **Sửa:** `scorers.contract()` đọc contract. `EXTRA_SLOTS` là các slot contract có mà ontology không có. `CLAIM_FIELDS` là khóa `ground_truth_facts` trừ `NOT_CLAIMS`, cộng `shipping_fee_vnd` và `cod_limit_vnd`. Thêm kiểu `datetime` (chuẩn hóa về `YYYY-MM-DDTHH:MM`) và `sku` (phải có đúng mã trong quote); `price_vnd:<SKU>` cũng phải có mã trong quote. `turn_input` nhận `today` và `crm_history`, do `cli.call_context` lấy từ plan của kịch bản, ở cả run thường lẫn relabel. Fact usage được giữ khi có `previous_sessions` hoặc `crm_history`. Prompt cập nhật theo bản người dùng đưa; vẫn giữ slot `issue` và quy tắc `estimated_delivery` của v10. Cache ghi theo lô (50 nhãn hoặc 30 giây, và một lần khi gắn nhãn xong) trong thread riêng, JSON không thụt lề. `VERSION` lên `product-extractor-v11`.
- **Đã kiểm:** chạy 11 file test extractor/relabel/eval trong `apps/ai-agent-service/.venv`: 126 passed. Ba test mới nằm trong `test_extractor_vocabulary.py` (entity theo contract; `callback_at`/SKU/`price_vnd:<SKU>`; `crm_history` làm bằng chứng). Python hệ thống thiếu `pytest-asyncio`, nên test async phải chạy bằng venv này.
- **Số đo:** chưa đo.
- **Còn lại:** hash và version đổi nên cache cũ không dùng được; relabel lại sẽ gọi model cho mọi lượt. Muốn nhanh hơn rõ rệt phải nâng `input_tokens_per_minute` của OpenAI theo tier thật của key, hoặc gắn nhãn cả một cuộc trong một lần gọi; cách sau lại đổi dụng cụ đo, cần duyệt trước. Các lỗi TSR "không có tool call order.create khớp args_match" là lỗi của agent, không phải của extractor, nên extractor không sửa được.

### 2026-11-07 · Extractor v10: một lượt không gán được nhãn không làm hỏng cả run

Loại: evaluation · Trạng thái: đang đo · Chỉ số: RQR, HR, CCR (đổi dụng cụ đo)

- **Vấn đề:** relabel `full` của `eval2` dừng ở lượt 521/3.747. Một lượt hỏng cả hai lần thử, và `_label` dừng mọi lượt còn lại.
- **Bằng chứng:** `evaluation/runs/eval2-full-relabel-2`, SCN-ADV-0061 call_2 lượt 4, câu "em chưa tra được giá chính xác lúc này": cả hai lần model trả `kind: "other"`, schema chỉ nhận `question`, `claim`, `fact_usage`. Prompt dùng `other` làm nhãn dự phòng của slot; ở nhiệt độ 0 chạy lại vẫn ra như vậy.
- **Sửa:** `scorers.Item` nhận `kind: other`, `label_items` bỏ mục đó và tính vào `changed`; `VERSION` lên `product-extractor-v10`. `cli._label` gán nhãn tiếp các lượt khác khi một lượt hỏng, trừ khi có `EVAL_BUDGET_DB`; bảng vẫn bị giữ khi còn lượt chưa gán nhãn.
- **Đã kiểm:** hai test mới trong `tests/agent/test_relabel_one_config.py`; `test_eval_guardrails` cập nhật theo hành vi mới; toàn bộ `tests/agent` chỉ còn lỗi ASR của môi trường.
- **Số đo:** chưa đo.
- **Còn lại:** đổi `scorers.py` đổi `prompt_sha256`, nên cache cũ không dùng được. Lần sửa trước (thử lại khi ghi cache) cũng đã đổi hash mà không nâng version: run `thu-1` có hash `bc5653…`, relabel lần 2 có `29c4d1…`. Không so số giữa các hash khác nhau.

### 2026-11-07 · Chấm riêng một cấu hình và extractor không còn treo

Loại: evaluation · Trạng thái: đang đo · Chỉ số: TSR, CCR, RQR, HR của `full`

- **Vấn đề:** `eval2` chạy xong `full` (404 kịch bản, 3.747 lượt) thì extractor đứng yên hơn 20 phút ở lượt 143 rồi tiến trình dừng. Manifest còn `INCOMPLETE`, không có baseline, nên relabel từ chối và không chấm được gì. Lúc gán nhãn cũng không in tiến độ, nên không phân biệt được treo hay đang chạy.
- **Bằng chứng:** `evaluation/runs/eval2`: cache extractor ghi lần cuối 16:43 với 143 mục; CPU của tiến trình không đổi; 5 kết nối HTTPS ở trạng thái `CLOSE_WAIT`.
- **Sửa:** `relabel` nhận `--config`: chỉ chấm cấu hình đó, không cần cấu hình kia. Một run dừng mà không ghi lý do chỉ được nhận khi chọn `--config` và trace của cấu hình đó đủ mọi lượt (`report.trace_errors`), không lượt hay `after_call` nào lỗi; lỗi đã ghi trong manifest vẫn chặn. `cli._label` giới hạn 300 s mỗi lượt: quá thì dừng với lỗi, phần đã gán nhãn giữ trong cache. In tiến độ sau mỗi 200 lượt. Lần relabel đầu dừng ở lượt 256 vì Windows từ chối ghi đè `extractor.json` (`PermissionError`, repo nằm trong OneDrive); `scorers._replace` thử lại 5 lần, vẫn bị giữ thì cảnh báo và gán nhãn tiếp.
- **Đã kiểm:** `tests/agent/test_relabel_one_config.py`, hai test mới trong `test_extractor_cache_integrity.py`. Kiểm `eval2` qua đúng các bước kiểm của relabel, không gọi model: đủ 3.747 lượt, không lỗi.
- **Số đo:** chưa đo.
- **Còn lại:** số của `eval2` là của code trước các bản sửa guard, chỉ dùng làm mốc. Relabel xoá `facts_used` cũ, nên CCR là cận dưới. Chưa tìm được vì sao lời gọi extractor treo dù đã đặt timeout 60 s; giới hạn 300 s chỉ chặn hậu quả.

### 2026-11-07 · Đo thời gian từng bước của một lượt

Loại: evaluation · Trạng thái: đang đo · Chỉ số: TTFT, Total Latency

- **Vấn đề:** trace chỉ có `ttft_ms` và `total_ms`, nên không biết giây nào đi vào model, tool, guard hay PolicyAgent, và không quyết được có nên thêm Redis. Langfuse chỉ thấy model và tool của advisor; PolicyAgent, hard guard, tra knowledge và nạp brief không có span, `stage_timings` gửi lên luôn rỗng.
- **Bằng chứng:** `evaluation/runs/eval2`, 3.419 lượt: TTFT p50 3,2 s, p95 9,3 s; Call Brief p50 84 ms, p95 267 ms; lượt có tool p50 3,9 s so với 1,6 s; lượt viết lại p50 6,3 s. Trung bình 2,03 lần gọi advisor và 0,91 lần gọi PolicyAgent mỗi lượt.
- **Sửa:** `observability/stopwatch.py` mở một đồng hồ mỗi lượt qua contextvar, đo thời gian thực của từng bước: `context`, `knowledge`, `compact`, `advisor` (thời gian chờ chữ tiếp theo, kể cả tool), `guard`, `policy`, `respond`, `persist`, `other`; thêm `model` và `tools` đo bên trong advisor. Hai tool chạy song song chỉ tính một lần. Ghi vào `diagnostics.jsonl` (`timings`), không vào trace BTC; `--performance` in bảng theo bước; API đưa vào `latency.stages_ms`, nên màn Developer và Langfuse (`stage_timings`) có số.
- **Đã kiểm:** `tests/agent/test_turn_stopwatch.py`, gồm một lượt qua graph thật với model giả. Toàn bộ `tests/agent` không thêm lỗi mới.
- **Số đo:** chưa đo; `eval2` chạy trước khi có đồng hồ.
- **Còn lại:** chạy lại một kịch bản để có bảng đầu tiên. PolicyAgent vẫn chưa có span riêng trên Langfuse. Khi stream, model chạy trước trong lúc câu đang được kiểm, nên `model` có thể dài hơn `chờ advisor`.

### 2026-11-07 · Guard nhận đúng nguồn của số tiền

Loại: hard guard, soft guard, tool · Trạng thái: đang đo · Chỉ số: TSR, HR, số lần fallback

- **Vấn đề:** phần lớn lần chặn số tiền là chặn oan, nên khách nhận câu an toàn thay cho câu trả lời đúng. `schedule.callback` lỗi `INTERNAL` khi chưa có số của khách.
- **Bằng chứng:** `evaluation/runs/eval2`, phân loại toàn bộ, không lấy mẫu: giá của lượt trước trong cùng cuộc; `1.400 W` bị đọc là tiền; ngân sách gõ không dấu hoặc kiểu "5 triệu rưỡi"; tổng các báo giá; phí bằng 8% giá theo BH-05; giá của Call Brief ở lượt mở đầu; `order.status` trả rỗng; PolicyAgent chặn số viết bằng chữ và số đã có trong tool. SCN-ADV-0093, SCN-ADV-0145: `schedule.callback` thiếu `customer_phone`.
- **Sửa:** `call_numbers` giữ số của giá, catalog và giao hàng trong cả cuộc; `allowed_amounts` nhận tổng các báo giá và tỷ lệ trong tài liệu nhân với giá; `itn` đọc "rưỡi" và bỏ số có đơn vị đo; `customer_amounts` đọc tiền không dấu; `PRICE_HISTORY` nhận cách nhắc giá cũ ở lượt mở đầu; `_order_state` chấp nhận tra rỗng và câu hỏi xác nhận; `open_amounts` để PolicyAgent chỉ xét số không có nguồn; thiếu số khách thì `actions` yêu cầu hỏi số, `crm` báo lỗi rõ thay vì `INTERNAL`.
- **Đã kiểm:** `tests/agent/test_money_sources.py`. Phát lại 140 bản nháp bị chặn qua guard mới, không gọi model: 92 qua, 48 còn bị chặn. Trong 48 ca có tổng tính sai thật (11.380.000 so với 10.935.000), và khoảng 15 ca lượt mở đầu mà bản phát lại không có giá của Call Brief.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** chạy lại `eval2` sau khi sửa. Theo dõi HR vì guard nới ra ở một số nguồn. Model viết lại nguyên câu ở 14 lần fallback, nên chưa dùng được lý do bị chặn để sửa câu.

### 2026-11-07 · Tham số thừa làm hỏng báo giá và chuyển máy

Loại: hard guard, tool · Trạng thái: đang đo · Chỉ số: TSR, HR

- **Vấn đề:** model truyền tham số tool không khai báo, server từ chối cả lần gọi và model chỉ nhận `BAD_ENVELOPE`. PolicyAgent chặn cả số có trong tài liệu đã đọc. Guard coi câu "em chưa chuyển được máy" là lời hứa chuyển máy.
- **Bằng chứng:** `evaluation/runs/eval2` (150 kịch bản, đang chạy): 141 trên 660 `pricing.get_quote` lỗi, cả 141 có `payment`, không lần thành công nào có; 3 `handoff.transfer` lỗi đều có `escalation_reason` thừa; 118 trên 1.290 lượt dính lỗi. SCN-ADV-0104 call_1 turn 4: chuyển máy lỗi, cả 3 bản nháp bị chặn, khách nhận câu an toàn. Lỗi tham số chỉ nằm ở 3 trên 36 lần fallback.
- **Sửa:** `advisor.declared_arguments` bỏ tham số không khai báo trước mọi tool; câu hỏi `unquoted_price` tính cả tài liệu đã đọc; `hard.TRANSFER_REFUSED` cho câu từ chối đi qua.
- **Đã kiểm:** `tests/agent/test_tool_arguments.py`. Chưa chạy lại `eval2`.
- **Số đo:** chưa đo.
- **Còn lại:** xem mục "Guard nhận đúng nguồn của số tiền".

### 2026-11-07 · Admin duyệt Knowledge Gap Loop

Loại: tính năng, hard guard · Trạng thái: đang đo · Chỉ số: HR

- **Vấn đề:** màn hình duyệt gap chỉ có ở trang developer; `gaps.resolve` không gọi `gap.gate` nên câu trả lời có số tiền, mã khuyến mãi hoặc tồn kho vẫn được xuất bản; không có cách loại câu không cần trả lời; nguồn trích có thể là chính sách hết hiệu lực.
- **Bằng chứng:** `gate` không có nơi gọi nào trong `gaps.py`; `KnowledgeGaps` chỉ được gắn trong `agent-console.tsx`.
- **Sửa:** gắn `KnowledgeGaps` vào `/admin`; `gaps.resolve` gọi `gate` và từ chối nguồn hết hiệu lực; thêm `gaps.dismiss` và `POST /api/developer/knowledge-gaps/{id}/dismiss`; câu đang mở hiện trước.
- **Đã kiểm:** `tests/agent/test_gap_review_and_judge.py`, `tests/agent/test_faq_admin.py`, `apps/web/e2e/gap-admin.spec.ts` với backend giả.
- **Số đo:** chưa đo; chưa có câu hỏi thật.
- **Sửa thêm:** `POST /api/developer/knowledge-gaps/{id}/faq` và nút "Chuyển thành FAQ nháp": tạo mục nháp `FAQ-GAP-<id>`, việc duyệt bật vẫn ở phần FAQ, không đổi phiên bản kiến thức.
- **Còn lại:** gom câu trùng nghĩa, chuyển kho gap sang DB, gợi ý câu trả lời, xóa bản sao trong FAQ khi khách yêu cầu xóa dữ liệu.

### 2026-11-07 · Trang quản lý FAQ và bộ FAQ nháp

Loại: tính năng · Trạng thái: đang đo · Chỉ số: token mỗi lượt, TSR

- **Vấn đề:** chưa có FAQ thật cho các đợt, và admin không có giao diện để thêm, sửa, xóa FAQ.
- **Bằng chứng:** `data/kb/v0.jsonl` trống; `kb_upsert` chỉ gọi được qua MCP.
- **Sửa:** thêm `data/kb/drafts.jsonl` (10 mục nháp lấy từ KM, LN, DT, VC), `components/knowledge/faq.py`, API `/api/developer/faq` chỉ cho admin, cột `status` trong `kb_chunks`, màn hình `faq-admin.tsx` ở `/admin`. Mục nháp không được agent đọc; bật cần người xác nhận và qua `gap.gate`.
- **Đã kiểm:** `tests/agent/test_faq_admin.py`; cả vòng đời trên database tạm của Postgres (nạp nháp, duyệt, tìm theo sản phẩm, hết hạn, tắt, xóa, khởi động lại không nạp lại mục đã xóa); `apps/web/e2e/faq-admin.spec.ts` trên Chromium với backend giả; `tsc --noEmit`. Chưa chạy trên service thật.
- **Số đo:** chưa đo; chưa có mục nào được bật.
- **Còn lại:** người duyệt đọc từng mục, gồm cả ngày mở đợt Giáng sinh và Tết do tôi tự chọn. Chưa phát hiện xu hướng từ cuộc gọi thật.

### 2026-11-07 · FAQ theo sản phẩm và theo đợt

Loại: knowledge, tính năng · Trạng thái: đang đo · Chỉ số: RAG, TSR, token mỗi lượt

- **Vấn đề:** mục FAQ của nhóm không gắn được với sản phẩm hay đợt khuyến mãi; `kb_upsert` không nhận ngày hiệu lực; đổi ngày trong bản phát hành không được ghi xuống `kb_chunks`.
- **Bằng chứng:** `sync_release` chỉ cập nhật khi title hoặc text đổi; `data/kb/v0.jsonl` trống; model chỉ đọc 3 đoạn mỗi lượt.
- **Sửa:** thêm `campaign`, `applies_to` trong `corpus.py`, lưu qua `provenance` nên không cần migration; `with_campaigns` lấy ngày và sản phẩm từ `promotions.json`, từ chối đợt không có ngày kết thúc; `search(about=...)` ưu tiên mục khớp sản phẩm và bỏ mục của sản phẩm khác; `shown_passages` đọc thêm tối đa 1 mục theo đợt khớp sản phẩm; `kb_upsert` nhận ngày, đợt, sản phẩm; `sync_release` so cả ngày và `provenance`.
- **Đã kiểm:** `tests/agent/test_knowledge_campaigns.py`; câu lệnh `sync_release` chạy trên database tạm của Postgres 16: dữ liệu giống thì không ghi, đổi `valid_to` thì cập nhật. `kb_upsert` chưa được gọi thật qua MCP.
- **Số đo:** RAG 60 câu không đổi (Recall@3 91,5, Recall@5 93,2), vì `v0` chưa có mục nào. Tác dụng thật chưa đo.
- **Còn lại:** thêm mục FAQ thật cho một đợt rồi đo. Bước phát hiện xu hướng từ cuộc gọi thật chưa làm. Mục do nhóm thêm vẫn cần người đối chiếu với chính sách.

### 2026-11-07 · Đo prompt cache và đặt `prompt_cache_key`

Loại: tính năng, evaluation · Trạng thái: đang đo · Chỉ số: token mỗi lượt, chi phí

- **Vấn đề:** agent dựa vào cache tự động của nhà cung cấp nhưng không ghi số token đọc từ cache, nên không biết tiết kiệm bao nhiêu.
- **Bằng chứng:** `token_ledger` chỉ có `calls`, `input`, `output`; `performance.py` ghi rõ chưa tính cache.
- **Sửa:** `token_ledger` thêm `cached`, đọc từ `input_token_details.cache_read`; `usage.json`, `performance.py` và `--report performance` có tỷ lệ cache, run cũ hiện "chưa đo"; `factory.cache_options` đặt `prompt_cache_key` theo từng agent cho OpenAI. Chi phí vẫn chưa trừ phần cache vì repo chưa có giá token cache.
- **Đã kiểm:** `tests/agent/test_knowledge_campaigns.py`, gồm kiểm khóa nằm trong payload của `ChatOpenAI`. Chưa gọi API thật.
- **Số đo:** chưa đo. Lần chạy `cache-thu-1` dừng vì `eval2` đang giữ database.
- **Còn lại:** chạy SCN-GEN-0050 khi `eval2` xong, đọc dòng cache trong `--report performance`, rồi quyết định có ổn định thêm phần prompt phía sau không.

### 2026-11-07 · Lọc chính sách không còn hiệu lực trước khi lấy top k

Loại: knowledge, prompt · Trạng thái: đang đo · Chỉ số: RAG, version accuracy, TSR

- **Vấn đề:** đoạn hết hiệu lực vẫn vào top 5 và text của nó vẫn tới model, chỉ kèm câu dặn đừng nhắc lại. Ngày đặt khách tự nói không được dùng. Khách có đơn ở hai bản chính sách bị lấy đơn mới nhất mà không hỏi. `NQ-*` ghi không dùng để tư vấn khách vẫn đọc được. Mục changelog được tính nhưng chưa tới model.
- **Bằng chứng:** `rag/qa_labeled.json`, 9 trên 60 câu trả về đoạn không áp dụng; Q43 không dùng ngày đơn. 20 trên 22 khách có đơn nằm ở cả hai phía 01/10/2026.
- **Sửa:** `KnowledgeBase.search` lọc theo `in_force` trước khi lấy top k, bỏ `superseded`, `validity`, `counterpart`; `stated_order_day` đọc ngày đặt từ lời khách, dùng cho cả hot path và `rag.py`; `version_differs` thêm ghi chú để agent hỏi đơn nào; `_passages` gửi kèm mục changelog của đoạn bị lọc, ngoài hạn mức 3 đoạn model đọc (`shown_passages`); tiêu đề tài liệu quyết định `restricted` và ngày hết hiệu lực; sửa luật 3 trong `rules.md`.
- **Đã kiểm:** `tests/agent/test_knowledge_in_force.py`; bộ `tests/agent` không có lỗi mới so với trước.
- **Số đo:** RAG 60 câu, hybrid, trước và sau như nhau: Recall@3 91,5, Recall@5 93,2, abstain không trả lời được 75, abstain restricted 60, false abstain 0. Keyword cũng không đổi. Câu có đoạn không áp dụng: 9 xuống 0, Q43 là câu duy nhất lấy bản cũ và đúng. Tác động lên TSR, RQR chưa đo vì chưa chạy agent.
- **Còn lại:** chạy nhóm kịch bản đổi trả để xem câu hỏi "đơn nào" có làm tăng RQR không. Với đơn cũ, DT-06 và DT-07 không có bản cũ tương ứng nên không còn được đọc. Khách hỏi về ghi âm cuộc gọi giờ nhận câu thông tin nội bộ vì NQ-03 bị chặn. Mục FAQ do nhóm thêm chưa được đối chiếu tự động với chính sách.

### 2026-11-07 · `run_all --output`

Loại: tính năng · Trạng thái: xong · Chỉ số: không áp dụng

- **Vấn đề:** chạy thử `run_all --fresh` không chỉ định thư mục sẽ xóa dữ liệu sinh ra trong `data/dev`, bộ dữ liệu duy nhất; chỉ đổi được thư mục đích qua `--seed` hoặc biến môi trường.
- **Bằng chứng:** `Dataset.clear` xóa các thư mục dữ liệu trong thư mục output, mặc định là `data/dev`.
- **Sửa:** `run_all.py` thêm `--output`, tính đường dẫn từ nơi gõ lệnh và truyền cho mọi bước qua `DATAGEN_OUTPUT`. Lệnh mẫu trong README có `--fresh` đều kèm `--output`.
- **Đã kiểm:** `tests/test_run_all_output.py`; chạy thật `--plan-only --output`, `data/dev` không đổi.
- **Số đo:** không áp dụng.
- **Còn lại:** `--fresh` không kèm thư mục vẫn xóa `data/dev`; chưa thêm chặn.

### 2026-11-07 · Chỉ giữ một bộ dữ liệu: `data/dev`

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không đổi cách chấm

- **Vấn đề:** ba bản `seed-dev`, `seed-dev-r2`, `seed-dev-r3` nằm cạnh nhau, tài liệu và đồng đội không chắc phải chạy bản nào.
- **Bằng chứng:** r3 chỉ có ở máy cục bộ, `seed-dev` trong git là bản chưa sửa nhãn.
- **Sửa:** đổi tên r3 thành `data/dev`, chép `asr_test/` từ r2 sang, xóa `seed-dev` và r2. Bộ sinh dữ liệu ghi vào `data/<tên>`, mặc định `data/dev`. Xóa `revise_seed_dev_r3.py` vì nguồn của nó không còn. `--report` so bộ kịch bản theo hash file, nên đổi tên thư mục không làm run cũ thành bộ khác. Báo cáo có ngày giữ nguyên.
- **Đã kiểm:** hash `scenarios/` trước và sau khi đổi tên trùng nhau; 404 kịch bản, 73 file `asr_test/`.
- **Số đo:** không áp dụng, nội dung kịch bản và nhãn không đổi.
- **Còn lại:** `seed-dev-r2` không còn bản nào vì chưa từng vào git; `seed-dev` còn trong lịch sử git.

### 2026-11-06 · Skill viết tài liệu kèm sơ đồ

Loại: tính năng · Trạng thái: xong · Chỉ số: không áp dụng

- **Vấn đề:** chưa có quy tắc chung để viết tài liệu đủ chi tiết và biết khi nào cần vẽ sơ đồ.
- **Bằng chứng:** yêu cầu của người dùng ngày 06/11.
- **Sửa:** thêm `.claude/skills/write-docs/SKILL.md`: đọc code trước khi viết, độ chi tiết của một trang, chọn loại Mermaid theo nội dung như `docs/ai/`, và các bước kiểm.
- **Đã kiểm:** đọc lại quy ước tài liệu và sơ đồ đang có trong repo. Skill chưa được dùng thử trên một trang thật.
- **Số đo:** không áp dụng.
- **Còn lại:** không.

### 2026-11-06 · Hợp nhất commit `06a5ecad` với thay đổi bộ nhớ và dữ liệu

Loại: evaluation, dữ liệu · Trạng thái: xong · Chỉ số: không đổi cách chấm

- **Vấn đề:** rebase `408e2769` lên `06a5ecad` xung đột ở 7 file: upstream chọn `data/seed-dev`, commit chọn `data/seed-dev-r3`; cả hai cùng sửa lỗi kênh `fb`; commit xóa `evaluation/datasets/README.md` mà upstream vừa cập nhật.
- **Bằng chứng:** `seed-dev` và r2 chỉ khác 2 file kịch bản; r3 sửa nhãn trên r2 (168 file khác, 404 kịch bản) và không nằm trong git.
- **Sửa:** r3 là đường chạy hiện tại; giữ `evaluation/datasets/README.md` vì đó là nơi duy nhất ghi ID đã dùng và holdout; `scenarios.py` chỉ còn `CRM_SESSION_CHANNELS`; `_TEMPLATE.md` trỏ đúng danh sách ID.
- **Đã kiểm:** không còn dấu xung đột; test evaluation, prompt, bộ nhớ, BTC pack và budget: 100 qua, 1 lỗi khóa file trên Windows có từ trước.
- **Số đo:** không áp dụng, code chấm và nhãn không đổi.
- **Còn lại:** không; r3 đã trở thành `data/dev` (xem mục 07/11).

### 2026-11-06 · Cho model biết hôm nay là ngày nào

Loại: prompt · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** model không biết ngày hiện tại nên "tối mai" không đổi được thành ngày đúng; agent tự đoán năm, bị guard chặn rồi nói với khách là giờ đó ngoài giờ làm việc.
- **Bằng chứng:** `evaluation/runs/mem-truoc-2`, `mem-sau`, `mem-sau-2`, SCN-GEN-0050 call_1 turn 5: `schedule.callback` với `callback_at` năm 2024, bị chặn "đã qua".
- **Sửa:** `advisor.system_prompt` thêm dòng "Bây giờ là ..." vào phần lane; `run_eval` in và ghi `advisor_context`; thông báo riêng khi thư mục chỉ có `run.lock` rỗng.
- **Đã kiểm:** `test_prompt_focus.py`, `tests/agent`; chạy thật SCN-GEN-0050 ở cả hai chế độ.
- **Số đo:** SCN-GEN-0050, TSR 0 lên 100 ở cả hai chế độ (`date-full`, `date-focused`). Chỉ một kịch bản.
- **Còn lại:** đo trên nhóm kịch bản hẹn gọi lại. Ở `date-focused`, call_2 agent đặt thêm một lịch 27/10 không có trong nhãn.

### 2026-11-06 · Luật lõi, episode và tra lịch sử

Loại: prompt, slot bộ nhớ, tool · Trạng thái: đang đo · Chỉ số: token mỗi lượt, CCR, RQR

- **Vấn đề:** luật lõi còn 1.389 token; episode không có mục tiêu và việc còn dở; agent không tra được lời đã nói ở cuộc trước.
- **Bằng chứng:** đo `tokens(HARD_RULES)`; bảng `episodes` chỉ có `summary`, `outcome`, `commitments`.
- **Sửa:** chuyển luật 11, 14, 18, 19, 21 sang `rule_packs.yaml`; `episodes` thêm cột `goal`, `open_items`, `MemoryAgent.goal_of` lấy mục tiêu bằng code; brief có dòng việc còn dở; thêm tool `memory_search_calls` cho lane CONTINUITY, che token PII và bỏ qua cuộc hiện tại.
- **Đã kiểm:** `tests/agent` 1.117 test qua; 4 fail và 14 error thuộc nhóm ASR, voice và khóa file. Trên PostgreSQL thật (database tạm): migrate bảng cũ giữ nguyên dữ liệu, chạy lại an toàn; câu truy vấn đúng khách, bỏ cuộc hiện tại, che token. Luật lõi 1.045 token, toàn bộ 2.547 token.
- **Số đo:** `chưa đo`.
- **Còn lại:** chạy thật một kịch bản; `run_eval` không có bảng `turns` nên tool chỉ tìm được trong episode khi đánh giá.

### 2026-11-06 · Prompt đủ bằng chứng, nạp theo tình huống, có trạng thái cuộc

Loại: prompt, slot bộ nhớ, tool · Trạng thái: đang đo · Chỉ số: TSR, CCR, RQR, HR, token mỗi lượt

- **Vấn đề:** agent trả lời lệch yêu cầu, prompt dài và có thể mất đúng phần nó phải dựa vào.
- **Bằng chứng:** ngân sách 3.000 token, luật cứng chiếm 2.663. Trên ngữ cảnh mẫu, `knowledge` và `summary` bị cắt; `products` và `orders` cũng thuộc diện bị cắt. Danh sách phần bị cắt bị bỏ đi. Có hai luật 12.
- **Sửa:** `budget.py` chỉ còn playbook là tùy chọn, ngân sách 4.000; `focus.py` chọn luật và dòng brief theo lượt, công tắc `ADVISOR_CONTEXT=full`; `rule_packs.yaml` tách 8 luật và gộp luật 12; `call_state.py` giữ điều khách đã nói, sản phẩm vừa báo giá, câu hỏi đang mở; "Yêu cầu hiện tại" đặt cuối prompt; brief đánh dấu blocker đã xong; thêm `memory_get_episodes` cho lane CONTINUITY; diagnostics có `context`.
- **Đã kiểm:** test mới `test_prompt_focus.py` và bộ `tests/agent` (kết quả ở báo cáo của lượt này). Luật lõi và kích thước cuối xem mục "Luật lõi, episode và tra lịch sử".
- **Số đo:** `chưa đo`. So trước/sau bằng `ADVISOR_CONTEXT=full` trên cùng cohort.
- **Còn lại:** nhận chủ đề bằng từ khóa có thể sót, sai sót chỉ làm thiếu luật chứ không mất tool; cần xem `context.packs` trên trace thật.

### 2026-11-06 · Bảng báo cáo `--report`

Loại: evaluation · Trạng thái: đang đo · Chỉ số: tất cả

- **Vấn đề:** chưa có lệnh ghép bảng ASR, Agent và hiệu năng theo cấu hình cho báo cáo.
- **Bằng chứng:** `run_eval.py` chỉ in bảng Baseline/Hệ thống; WER, CER và hiệu năng nằm ở các lệnh riêng.
- **Sửa:** thêm `pipeline/eval/tables.py`, các tham số `--report`, `--run`, `--asr-run`, `--kb-version`; biến môi trường `KNOWLEDGE_VERSION` trong `config_manager.py`.
- **Đã kiểm:** 18 test liên quan qua; `--report all --run router=evaluation/runs/test` in đúng ba bảng.
- **Số đo:** không áp dụng.
- **Còn lại:** chưa chạy `--report` kèm một run mới, `--kb-version` và bảng ASR trên run thật. GapLoop, Reflection cần knowledge version có mục đã duyệt (`v0.jsonl` đang rỗng). Subagent và A/B Testing chưa có trong agent.

### 2026-11-06 · Tạo audio chỉ cho lượt đã đổi

Loại: dữ liệu · Trạng thái: xong · Chỉ số: chi phí tạo dữ liệu

- **Vấn đề:** đổi một câu làm phải tạo lại dạng đọc của cả cuộc; câu chèn vào làm lệch số lượt nên clip cũ không dùng lại được.
- **Bằng chứng:** r3 có 42 cuộc thêm câu đồng ý và 73 cuộc khôi phục câu cuối; r3 chưa có clip nào.
- **Sửa:** thêm `carry_audio.py`; `reference.load_or_build` chỉ gọi model cho dòng mới; `synthesize_scenario_audio` có `--changed-only`, `--only`, `--dry-run`, và giữ giọng của cuộc.
- **Đã kiểm:** 105 test `data-generation` qua; sau khi chạy, `--dry-run` báo 0 lượt còn thiếu.
- **Số đo:** dùng lại 3.612 clip, tạo mới 135 lượt, gửi 2.766 ký tự (31 lượt lấy từ cache). Chưa tính chi phí model viết dạng đọc.
- **Còn lại:** `asr_test/` vẫn ở `seed-dev-r2`.

### 2026-11-06 · Giữ `blocker` khi model bộ nhớ bỏ sót, đọc được ASR không dấu

Loại: slot bộ nhớ · Trạng thái: đang đo · Chỉ số: CCR

- **Vấn đề:** ý "cần bàn với gia đình" không vào bộ nhớ, nên cuộc sau không nhắc lại được.
- **Bằng chứng:** `evaluation/runs/test`, SCN-GEN-0050 call_1: model bộ nhớ đã chạy, ghi `callback_time` nhưng không có `blocker`. Regex chỉ chạy khi model lỗi và chỉ khớp chữ có dấu.
- **Sửa:** `agents/memory.py`: lớp `Words` đọc câu không dấu; `BACKSTOP` giữ `blocker`, `decision_maker` từ luật khi model bỏ sót, trừ khi cuộc đã có đơn. Thêm `fold`, `unmarked` vào `intake/text.py`; thêm hướng dẫn vào `memory_extractor.md`.
- **Đã kiểm:** 66 test bộ nhớ qua, gồm `test_memory_unmarked.py`.
- **Số đo:** `chưa đo`.
- **Còn lại:** chạy lại SCN-GEN-0050 để xác nhận CCR. Đổi prompt nên extractor của bộ nhớ có version mới.

### 2026-11-05 · Nhận lời đồng ý mua có từ xưng hô

Loại: action guard · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** khách nói đồng ý kèm từ xưng hô thì đơn không được tạo.
- **Bằng chứng:** `YES.fullmatch` từ chối 72 trong 73 câu xác nhận được khôi phục ở r3.
- **Sửa:** `guardrails/purchase.py`: thêm `CONSENT`, `COURTESY`, `agrees`. Câu chỉ gồm lời đồng ý và từ lịch sự mới tính; câu có thêm yêu cầu khác thì không.
- **Đã kiểm:** test agent liên quan qua.
- **Số đo:** `chưa đo`.
- **Còn lại:** số TSR r3 không so trực tiếp với r2 vì nhãn đã đổi.

### 2026-11-05 · Hẹn gọi lại đúng giờ, gồm ngày nghỉ và 11/11

Loại: action guard · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** giờ hẹn có múi giờ không khớp `args_match` của BTC; guard chặn giờ khách xin vào ngày nghỉ; agent hứa gọi lại mà chưa gọi tool.
- **Bằng chứng:** báo cáo lỗi bộ `seed-dev` mục thời gian; SCN-GEN-0050 hứa gọi lại.
- **Sửa:** `clock.tool_time` bỏ múi giờ; `SPECIAL_HOURS` cho 11/11; `actions._schedule_callback` cho phép ngày nghỉ để mock dời giờ; `hard.moved_callback` buộc báo giờ mới; guard chặn câu hứa khi chưa gọi tool; `crm.py` giữ giờ hợp lệ của 11/11.
- **Đã kiểm:** `test_callback_time.py` qua.
- **Số đo:** `chưa đo`.
- **Còn lại:** mock của BTC không biết giờ 11/11, nên SCN-ADV-0154 chỉ đúng qua wrapper của agent.

### 2026-11-05 · Bộ dữ liệu `seed-dev-r3`

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: TSR, CCR

- **Vấn đề:** kịch bản bị cắt câu xác nhận cuối, thiếu câu đồng ý, sai kênh `fb`, thiếu ca hẹn ngoài giờ và ngày nghỉ.
- **Bằng chứng:** báo cáo lỗi bộ `seed-dev`; chi tiết từng trường ở `data/seed-dev-r3/conversion-report.json`.
- **Sửa:** `revise_seed_dev_r3.py`, thêm stage `sync_customer_turns`, `check_labels`. Thêm SCN-ADV-0151..0154, dời SCN-GEN-0224 call_2.
- **Đã kiểm:** 404/404 kịch bản nạp được; oracle CCR 100, RQR 0, TSR 100, HR 0; hội thoại mẫu TSR 98,8.
- **Số đo:** `chưa đo` trên agent thật.
- **Còn lại:** nhãn chưa có người duyệt; xem `data/seed-dev-r3/DISPUTES.md`, gồm SCN-ADV-0023, SCN-ADV-0028 và 34 cuộc J02.
