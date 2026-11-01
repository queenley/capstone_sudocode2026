# Lịch sử chạy evaluation

Đọc file này trước khi chọn case. Đây là mục theo dõi chung; raw log/trace giữ local, không commit.
Một scenario chạy cả full/baseline vẫn là một scenario mới về độ phủ. Chạy R1 cùng cohort là retest có chủ đích, không cộng vào số case mới.

Từ 25/10/2026, `scripts/evaluation/` đổi thành `evaluation/harness/` và `scripts/create_data/` thành `evaluation/data-generation/`. Các mục bên dưới giữ đường dẫn lúc ghi; thư mục bằng chứng `scripts/evaluation/runs/<run>` giờ nằm ở `evaluation/harness/runs/<run>`, nội dung không đổi. Từ 28/10/2026, `evaluation/harness/` đổi tiếp thành `evaluation/agent-evaluation/` (code chuyển vào `src/`, `evaluation-contracts/` thành `contracts/`); bằng chứng nằm ở `evaluation/agent-evaluation/runs/<run>`, nội dung không đổi.

## Các lượt chạy

| Run | Ngày | Mục đích | Scenario | Cấu hình | Trạng thái |
|---|---|---|---:|---|---|
| 20261017-111459 | 17/10/2026 | Run chị cung cấp, chỉ đọc log | 10 | full + baseline | Execution xong; scoring INCOMPLETE |
| 20261022-204952 / smoke-r0 | 22/10/2026 | Smoke pipeline mới | 2 | full + baseline, Jev không khả dụng | Xong; diagnostic, phát hiện lỗi guard trong smoke |
| 20261022-205443 / development-r0 | 22/10/2026 | R0 sau sửa guard smoke | 10 | full + baseline, hard guard | Xong; 168 lượt, 0 lỗi extractor; nhãn diagnostic |
| 20261022-211242 / development-r1 | 22/10/2026 | Retest cùng 10 case của R0 | 10 | full + baseline, hard guard | INCOMPLETE; 168 lượt, 1 lỗi model-call cap, không xuất điểm tổng |
| 20261022-212808 / holdout-final | 22/10/2026 | Case giữ riêng, chỉ chạy sau chốt sửa | 10 | full + baseline, hard guard | INCOMPLETE scoring; 172/172 lượt product, 30 lượt thiếu nhãn |
| 20261024-work / development-r0 | 24/10/2026 | R0 dev, Jev bật (TypeSafe), v3 | 16 (12 M2 + 4 M1) | full + baseline | Xong nhưng bị lỗi hạ tầng `idempotency_key` làm mọi lệnh ghi bị mock từ chối; TSR M2 16,7%; giữ làm bằng chứng gỡ lỗi |
| 20261024-work / development-r1 | 24/10/2026 | Retest cùng cohort sau sửa nối tool (`scripts/evaluation/agent/runner.py`) | 16 | full + baseline | Xong; TSR M2 25,0% (v3) |
| 20261024-work / development-r2-v4 | 24/10/2026 | Retest, nhãn `chuyen_khoan` → `bank` (dataset v4); agent không đổi so với R1 | 16 | full + baseline | Xong; TSR M2 33,3%, HR giá/KM 25% |
| 20261024-work / development-r3-v4 | 24/10/2026 | Retest sau thêm quy tắc prompt | 16 | full + baseline | INCOMPLETE: 3 scenario hết thời gian khởi động adapter (78/104 lượt); không dùng điểm |
| 20261024-work / simulator-final | 24/10/2026 | Customer simulator BTC, 3 seed (0,1,2) | 5 M2 (SCN-GEN-0003, 0032, 0062, 0066, 0069) | full + baseline | Xong; TSR full 40% / 40% / 40%, baseline 20% / 0% / 20%; biên độ 0 (full), 20 (baseline) |
| asr/full-zipformer-30m → asr/v2-zipformer-30m | 25/10/2026 | ASR (không LLM): `zipformer-30m` qua `asr-service`, chấm `wer_cer` BTC | 674 lượt nói khách của 85 kịch bản (`asr-team-v2`); không tốn coverage kịch bản text | raw + lexicon | Xong; WER 6,2%, entity 96,0% → 97,1% sau sửa ITN (`v2-zipformer-30m-itnfix`, cùng hypothesis); v1 bỏ vì lỗi đáp án "TP Huế"; evidence `scripts/evaluation/runs/asr/` |

## Chi tiết từng lượt

### 20261017-111459 — không chạy lại trong task này

- Case: **0010, 0011, 0012, 0013, 0014, 0017, 0018, 0020, 0021, 0026** (mọi ID trong file này có tiền tố `SCN-GEN-`).
- Evidence: `20261017-111459/`; 1.765 file trong lock đã kiểm hash, không lệch.
- Code: commit `8d2929e`, dirty; không tái dựng được source đầy đủ từ commit.
- Có 190 raw turn, 164 exported turn; 24 lỗi pacing + 2 lỗi output truncation của extractor.
- Điểm diagnostic full/baseline: TSR 30%/40%; CCR 1,3%/0%; RQR 3%/0%. HR giá/KM full sai 1/1 claim, có tranh chấp GT.
- Chi phí lịch sử: chưa đối soát; không thuộc ngân sách API 20 USD của ngày 22/10.

### 20261022-204952 — smoke-r0

- Case: **0007, 0008**. Đây là hai case mới đầu tiên, sau đó được chạy lại có chủ đích trong cohort development R0.
- Evidence: `scripts/evaluation/runs/20261022-work/smoke-r0/`; log cạnh thư mục là `smoke-r0.log`.
- 24 turn full/baseline; extractor 23 call + 1 cache hit, 0 lỗi.
- Điểm diagnostic full/baseline: TSR 0%/50%; CCR 0%/0%; RQR 33,3%/75%.
- Đã phát hiện và sửa lỗi guard: delivery.estimate không có SKU; public catalogue codes phải được giữ qua các turn.
- Không dùng smoke làm đối chứng R0/R1: code và trạng thái Jev khác vòng development chính.

### 20261022-205443 — development-r0

- Case: **0007, 0008, 0023, 0027, 0029, 0030, 0034, 0036, 0037, 0083**.
- Evidence: `scripts/evaluation/runs/20261022-work/development-r0/`; `r0-source-lock.json` khóa hash source/config trước chạy.
- 84 turn full + 84 baseline; extractor 156 call + 12 cache hit, 0 lỗi. Source không đổi trong run.
- Điểm diagnostic full/baseline: TSR **40%/40%**; CCR **1,5%/0%**; RQR **16,7%/39%**; HR tổng **37,1%/20,4%**; HR giá/KM **41,4%/22,7%**.
- Giới hạn: nhãn chưa human-approved; 0008 thiếu chỉ rõ mẫu giày; phụ thu size có thể bị extractor gán thành giá sản phẩm. Có requested tool không có result, cần đối chiếu framework limit, không coi tên order.create là bằng chứng tạo đơn thành công.
- Giữ nguyên report đã đóng, không sửa/re-score như một lượt chạy mới.

### 20261022-211242 — development-r1 — INCOMPLETE

- Case giữ nguyên development-r0; đây là **10 retest**, không phải 10 case mới.
- Đổi product: giới hạn 6 tool/lượt không đủ chuỗi nhiều món; nâng 20 tool/lượt, vẫn giữ 8 model call và budget 20 USD. Framework ToolMessage báo hết limit được ghi blocked, không export như executed order.
- Trong R1 không đổi GT, scorer, extractor prompt/model, KB hay điều kiện chấm.
- Kết thúc 168 lượt; full 0036/call_3/t2 gặp ModelCallLimitExceededError, baseline không lỗi. Runner từ chối xuất điểm tổng: INCOMPLETE.
- 0083/call_2/t7 tạo thành công 4 đơn (4 ID riêng); đây là bằng chứng sửa luồng nhiều món, chưa chứng minh tăng metrics toàn cohort.
- Evidence: `scripts/evaluation/runs/20261022-work/development-r1/`; source/config khóa trong `r1-source-lock.json`. Prepare M1/M2 đều allowed=true trước khi chạy.

### 20261022-212808 — holdout-final — execution xong, scoring INCOMPLETE

- Case: **0006, 0024, 0033, 0038, 0039, 0040, 0043, 0046, 0050, 0053**.
- Không trùng ID hoặc khách của development/run cũ. Không dùng đáp án/transcript để chỉnh hệ thống.
- Snapshot/hash: `2026-10-22-cohort.json`; bản local đầy đủ trong `scripts/evaluation/runs/20261022-work/cohort-lock.json`.
- Gate prepare mới M1/M2 allowed=true, 94 + 78 planned turn; đây là gate diagnostic, không phải chứng nhận GT.
- Measurement `claim-grounding-v1`: claims phải có quote thật; loại khỏi chấm các suy diễn is_human, thời hạn xóa thành giao hàng, phụ thu thành giá. Giữ claim bị loại trong set_aside; 8 test offline. Thay đổi này sau R1, nên không so trực tiếp HR/TSR holdout với R0/R1. Không đổi BTC scorer/GT.
- Chốt source/config trong holdout-source-lock.json (118 file không đổi); không chỉnh product dựa trên holdout.
- Đã chạy 86 lượt full + 86 baseline, cả 10 case; 0 failed turn/after_call/schema. Full đủ nhãn; baseline thiếu 30 lượt: 1 extractor vượt 4096 output token, 29 request bị ngân sách chặn trước dispatch. Runner không xuất điểm tổng. Không chạy lại holdout.
- 25 + 11 claim bị set_aside, 6 + 6 safe-line turn; đây là số đếm diagnostic, không tự là số vi phạm guardrail.
- Evidence: scripts/evaluation/runs/20261022-work/holdout-final/; manifest run 20261022-212808, kết thúc 21:38:41 giờ Việt Nam.

## Chọn case cho lần sau

- **Đã chạy ít nhất một lần:** 30 ID = 10 lịch sử + 10 development + 10 holdout. Hôm nay thêm **20 scenario mới**, 532 lượt product tổng cộng (24 smoke + 168 R0 + 168 R1 + 172 holdout). Hai ID smoke nằm trong development, không cộng thêm.
- **Holdout đã dùng:** 10 ID ở trên; không chọn làm holdout mới hoặc tối ưu tiếp trong thí nghiệm này.
- Muốn tăng độ phủ: chọn ID ngoài cả hai nhóm. Muốn kiểm hồi quy: ghi rõ retest và đối chứng nào.
- Khi có run mới: thêm hàng vào bảng, danh sách ID đầy đủ, cấu hình/model, trạng thái, đường dẫn evidence và lý do retest nếu có. Chỉ đổi “chưa chạy” thành “xong” khi có manifest/trace; run dở phải ghi số case/turn thực chạy.

## Ngân sách ngày 22/10

Sổ dùng chung: `scripts/evaluation/runs/20261022-work/budget.sqlite`, trần 20 USD; không khởi tạo lại để chạy tiếp.
Trước holdout (sau smoke, R0, R1 và probe): usage đã đối soát **1,440442439 USD**, giữ **10,592624 USD dự phòng** cho request thiếu usage. Tổng giữ 12,033066439 USD, còn 7,966933561 USD. Dự phòng không phải chi phí đã xác nhận. Mọi request mới phải reserve trước dispatch; thiếu ngân sách sẽ dừng và ghi INCOMPLETE, không reset sổ.

Snapshot cuối: **2,075312643 USD usage tính theo token**, **16,5082016 USD dự phòng chưa đối soát**; tổng giữ **18,583514243 USD / 20 USD**. Còn 1,416485757 USD ở snapshot cuối. Điều tra tiếp xác nhận các request bị chặn khi nhiều request cùng giữ reservation; sau đó request đang chạy settle nên snapshot cuối có lại headroom. Không phải đã tiêu hết 20 USD. Các request bị chặn không được dispatch. Không coi usage là hóa đơn đã đối soát. Sổ không reset; muốn chạy tiếp phải đối soát usage thiếu hoặc mở ngân sách mới được người dùng cho phép.

## Revision sửa từ log sau khi đóng các run

Theo yêu cầu tiếp theo của người dùng “fix dựa trên log”, đã mở revision **post-log-fix (offline)**. Không có model run/API mới, không đổi điểm hoặc sửa trace đã đóng. Các ID holdout-final đã được dùng để debug lỗi extraction/điều phối, nên từ đây là dữ liệu development đã tiêu thụ; không dùng làm holdout độc lập nữa. Lần đo độc lập sau phải chọn ID khác toàn bộ 30 ID trên.

Chi tiết evidence → root cause → test: [2026-10-22-log-fixes.md](2026-10-22-log-fixes.md). Ngân sách hiện tại không reset, không đối soát thủ công request thiếu usage. Số dư có headroom sau settle không tự là quyền tăng ngân sách hoặc chạy lại holdout.


### Revision kiến trúc sau yêu cầu sửa toàn diện

Không có run model mới. Đã kiểm offline các đường identity, business memory, multi-order, tool privacy, streaming và provenance; thêm test graph và kiểm PostgreSQL trong schema tạm riêng. [Chi tiết revision](2026-10-22-architecture-fixes.md). Đây là sửa product/measurement sau thí nghiệm đã đóng, không có delta metrics mới. Danh sách 30 scenario đã dùng và trần API 20 USD giữ nguyên.

## Ngày 24/10/2026 (sổ riêng, trần 50 USD)

Sổ `scripts/evaluation/runs/20261024-work/budget.sqlite`, tạo mới; không reset sổ 22/10. Đã dùng khoảng **41,6 USD** gồm dự phòng cho request thiếu usage; không phải hóa đơn đã đối soát. Cohort dev (16 case) đã dùng để gỡ lỗi nên **không còn là đo độc lập**. **Holdout 10 case chưa chạy.** Lần chạy 24/10 bật Jev nên không so trực tiếp với 22/10 (hard guard).

- Dev M2 (12): SCN-GEN-0003, 0148, 0028, 0150, 0032, 0060, 0069, 0066, 0062, 0118, 0126, 0146. Dev M1 (4): 0075, 0089, 0088, 0072.
- Holdout chưa chạy (10): M2 0145, 0105, 0002, 0071, 0035, 0121, 0019; M1 0091, 0138, 0052.
- Thay đổi giữa các lần chạy: R0→R1 chỉ sửa lỗi nối tool; R1→R2 chỉ đổi nhãn (v4); R2→R3 đổi prompt agent (R3 chưa hoàn chỉnh). Mọi nhãn là diagnostic, chưa người duyệt.
- Ba lần chạy simulator trước `simulator-final` (`simulator-main`, `simulator-main3`, các lần smoke) dùng để sửa lỗi simulator; không lấy số liệu từ đó.

### Extractor khớp đường chấm chính thức (`product-extractor-v3`, 24/10/2026)

BTC không cung cấp extractor: `trace_log.schema.json` ghi việc trích `questions[]` và `claims[]` là trách nhiệm của team, và BTC chỉ chấm tay ngẫu nhiên 20 lượt để kiểm tra extractor có bỏ sót không. BTC chỉ cố định **tên** qua các kịch bản của họ. Lệnh BTC yêu cầu (`run_eval.py --scenarios`, ở thư mục gốc) chạy extractor riêng của agent (`components/evaluation/scorers.py`) với từ vựng cố định, không đọc từ kịch bản: 34 slot của ontology bộ nhớ (chứa mọi slot `must_not_ask`/`must_carry_over` trong mẫu công khai của BTC, và 1759/1759 lượt dùng slot của dataset v4) và `CLAIM_FIELDS` (khóa `ground_truth_facts` của BTC kèm kiểu giá trị).

Bộ chấm phân tích trước đây để extractor tự đặt tên slot và tên trường claim, nên RQR, CCR và HR lệch khỏi đường chính thức. v3 (`scripts/evaluation/agent/slots.py`) dùng đúng từ vựng, ép kiểu và quy tắc gắn nhãn của đường chính thức: slot ngoài bộ là `other` kiểu `open`, `fact_usage` ngoài bộ bị bỏ, claim phải thuộc trường BTC với giá trị đúng kiểu. Đây là đổi công cụ đo sau khi đã xem điểm, nên chỉ so sánh trên **cùng transcript**; không so với run dùng v2.

Một bản thử trung gian (chỉ 30 slot lấy từ mẫu công khai BTC, trước khi thống nhất với đường chính thức) chấm lại 104 lượt của `development-r2-v4-M2` cho RQR hệ thống 4,1% và baseline 25,3% (v2: 3,8% và 3,7%). Số này **chưa được đo lại** với bản v3 cuối; cần chạy lại `docs/evaluation/rescore_with_scoped_extractor.py`.


## 29/10/2026 — web-memory (sổ riêng, trần 10 USD)

- Cohort mới: **WEB-MEM-01, WEB-MEM-02, WEB-MEM-03, WEB-MEM-04, WEB-MEM-05, WEB-MEM-06, WEB-MEM-07**; dữ liệu giả riêng, không dùng case lịch sử hoặc holdout.
- Config: web local, memory enabled, model cấu hình hiện tại `openai:gpt-4.1-mini`; soft guard theo cấu hình hiện tại. Tiêu chí `web-memory-v1` khóa trong cohort.json.
- Evidence local (gitignored): `evaluation/agent-evaluation/runs/20261029-web-memory/`; sổ `budget.sqlite`, không reset sổ lịch sử.
- R0: PREPARING / INCOMPLETE; 0 turn model. Frontend dev trả HTTP 200; backend chưa khả dụng: Docker BuildKit lỗi metadata_v2.db input/output sau khi host hết dung lượng (110 MiB ở thời điểm lỗi). Đã xóa cache/browser tải riêng cho task để lấy lại khoảng 686 MiB; không reset volume. R1: PLANNED, paired retest cùng cohort/grading, không tính coverage mới.
- Trạng thái tổng: INCOMPLETE cho đến khi đủ UI/server evidence và usage/billing.

- Tiếp tục sau phục hồi: Docker daemon 29.7.2 hoạt động, host còn khoảng 13 GiB. Build lại backend từ source hiện tại theo README; frontend chạy npm dev. Chưa gửi turn model.
- R0 STARTING: WEB-MEM-01…07, web-memory-v1, source repo hiện tại qua bind mount; image local bổ sung json-repair (đã có trong requirements). Bắt đầu UI khi AI ready; mọi request dùng budget.sqlite trần 10 USD.

- R0 kết thúc: WEB-MEM-01…04 FAIL ở khôi phục phiên/nhận diện, WEB-MEM-05 PASS một nhánh đổi khách; 06–07 NOT RUN do lỗi điều phối login của script. Giữ R0 INCOMPLETE, không coi 05 là chứng minh đầy đủ cách ly. Evidence: R0/results.json, turns.json, call-3.json, ảnh hai phía; 2 lỗi setup trước đó lưu riêng.
- R1 STARTING: paired retest WEB-MEM-01…07, cùng input/tiêu chí, dùng danh tính fixture mới tương đương để không đọc memory từ R0; không cộng coverage mới. Source bản sửa nhận diện, lưu từng lượt và phiên; sổ budget chung không reset.

- R1 kết thúc INCOMPLETE: 01/05 PASS; 02–04 nhận VERIFIED và nhớ đúng sản phẩm/blocker nhưng script đòi đọc ra cả room/budget trong lời chào nên đánh FAIL; server brief chứa đủ 25 m², 6 triệu, SKU-AP-Y, 5.200.000đ. 06–07 chưa xong do script chờ vô hạn, đã dừng riêng script. Không tuyên bố 7/7.
- R2 STARTING, paired retest cùng WEB-MEM-01…07/input; bổ sung sửa brief thiếu tên khi chỉ có facts chưa có episode. Tiêu chí web-memory-v2 kiểm room/budget/giá trong brief và lời tiếp nối + tên trong reply, thay vì buộc bot đọc lại toàn bộ profile. R0 theo v2 vẫn FAIL các nhánh nhận diện; giữ nguyên artifacts v1. Sổ budget dùng chung không reset.

- R2 kết thúc: 02/04/05/06 PASS; 01 bị assertion so cả card sản phẩm tải bất đồng bộ, phần text hội thoại không đổi; 03 phát hiện race mở hai conversation đồng thời (đã sửa chia sẻ request mở phiên); 07 bị gateway 429 trước dispatch. R2 INCOMPLETE. Evidence R2/results.json + turns.json + call-*.json + ảnh.
- R3 STARTING, paired retest WEB-MEM-01…07 cùng tiêu chí web-memory-v2, snapshot ảnh/brief/facts; assertion 01 so phần text tin nhắn, không so thời điểm card tải. Giãn 6 giây giữa case để giữ rate limit, không tắt guard/rate limit. Fixtures mới tương đương, sổ budget chung.

- R3: 01–05 PASS; 06–07 chưa kết luận do gateway 429/queue polling. R3-followup STARTING: chỉ WEB-MEM-06/07, cùng khách R3 và tiêu chí, chờ cửa sổ rate-limit mới; 06 đặt bank rồi COD để chứng minh cập nhật thật thay vì hưởng facts có sẵn. Không cộng coverage, không reset budget.

### Kết quả cuối web-memory, 29/10/2026

- **Chức năng: PASS 7/7 nhóm case**, gồm 01–05 ở R3 và retest riêng 06–07 ở R3-followup; không phải một run độc lập 7/7. Các lượt trước giữ nguyên FAIL/INCOMPLETE và evidence.
- 01: reload/đóng khung chat khôi phục đúng conversation và text, không thêm tin. 02–03: mất tab/session vẫn nhận đúng khách, memory có ngay. 04: trình duyệt sạch không biết khách trước login, đọc đúng sau login. 05: đổi A/B không mang transcript/memory A sang B. 06: hai tab giữ độc lập, đổi bank→COD được nhớ ở cuộc mới, đóng tab đang stream không kết thúc tab kia. 07: console thấy brief trước handoff; nhân viên nhận và gửi reply tới khách.
- Brief đã đối chiếu với server: phòng 25 m², ngân sách 6 triệu, SKU-AP-Y, giá lịch sử 5.200.000đ, payment COD và nguồn fact ID. Tên khách có trong context cả khi chưa có episode. Không giả lập số cuộc đã kết thúc.
- Sửa: chống stale profile response xóa token mới; gắn phiên chat với token, đồng bộ đổi khách giữa tab; dùng chung request mở phiên để không tạo hai cuộc. Tài khoản web mới có identity ổn định; giữ match ledger/CRM cũ, không chuyển/xóa memory lịch sử. Lưu facts trước khi trả done, episode/QA vẫn ở cuối cuộc; retry memory không chạy lại advisor. Chặn tab/finalizer cũ ghi đè hoặc invalidate fact mới; union order IDs dưới khóa. Thêm guard cho lời đã tạo/đổi đơn thiếu tool thành công.
- Validation: **230 backend tests PASS**, **3 frontend Playwright regressions PASS**, Next production build/typecheck PASS, PostgreSQL schema tạm PASS (replay, mới thắng cũ, stale invalidation, concurrent order union, cách ly khách); schema đã drop. Diff kiểm bằng `git -c core.whitespace=cr-at-eol diff --check`.
- Model/config: gpt-4.1-mini + policy Jev theo config hiện có; ngày nghiệp vụ local vẫn **2026-10-15**, không phải xác minh giá/KM thực ngày 29/10. Dữ liệu chỉ là fixture giả. Không chạy case lịch sử bị loại hoặc holdout.
- Chi phí token đã biết: **0.123677131 USD**; **0.4223072 USD dự phòng thiếu usage**; tổng giữ **0.545984331/10 USD**. Không settle phỏng đoán, không reset sổ. **Đối soát billing/measurement tổng vẫn INCOMPLETE** dù kiểm chức năng PASS.
- Evidence local gitignored: `evaluation/agent-evaluation/runs/20261029-web-memory/summary.json`, `R3/`, `R3-followup/`, `postgres-check.json`, `budget.sqlite`. Ảnh `R3-followup/07-call-brief.png`, `07-staff.png`, `07-customer.png`; call 36 VERIFIED, handoff accepted, memory done. Tài khoản/dữ liệu test giữ local để review; không ghi credentials/transcript vào ledger.
- Hai dự án khác đã dừng, chỉ telesales-ai chạy. Backend source bind mount theo `compose.local.yml` trong evidence; frontend npm dev. Image base build chuẩn từng gặp Bus error sau hết ổ; dùng image local bổ sung dependency đã có trong requirements để test, chưa deploy production/commit. Ngoài phạm vi: audio, kênh ngoài web, chấm toàn bộ BTC, latency p95 và hoá đơn nhà cung cấp.


## 01/11/2026 — Khóa cohort và đối chiếu extractor trên cùng replies

**Trạng thái cuối: baseline v4 COMPLETE; smoke v5 COMPLETE; cohort v5 INCOMPLETE (77/78 lượt có nhãn).** Đây là retest development, không tăng coverage và không phải gold/holdout độc lập. Chưa chạy lại agent hiện tại.

- Cohort cố định: **SAMPLE-01, SAMPLE-02, SAMPLE-03, SAMPLE-04, SAMPLE-05, SAMPLE-06, SAMPLE-07**, nguồn `apps/ai-agent-service/data/btc/test_set/public_sample/`; 13 cuộc, **39 lượt/config**, 78 lượt tổng. Không sửa byte scenario, nhãn, pack BTC hoặc `reference_eval.py`.
- Nền bộ chấm: main `41eda490bc47577018541c7778c0e8443ed8e6c8`; SHA-256 `reference_eval.py`: `18f1fa0881a345b8dd01c4160ec8fc31aea5ff8385c09a3eb3db96a88372843e`. Không tuyên bố đây là ZIP BTC gốc.
- `cohort-lock.json` khóa IDs, toàn bộ SHA-256, nguồn và expected tools/args cho **cả full lẫn baseline_no_memory**, giữ nguyên `success_if`; không suy diễn thiếu nhãn positive là cấm mọi tool. Call thiếu assertion giữ đúng cách main xử lý; không thêm tiêu chí sau khi thấy điểm. Nhãn public có sẵn được kế thừa, không tự chứng nhận human approval mới. Tranh chấp GT ở báo cáo 28/10 vẫn giữ nguyên.
- PII: chỉ nguồn synthetic public của BTC; trace, bản sao input và cache ở evidence gitignored. Ledger này không chứa raw hội thoại hay key. ASR/hypotheses không thuộc phép đo này.

| Scenario | SHA-256 byte của file gốc |
|---|---|
| SAMPLE-01 | `1602366d3e268ee918ceee3cbb6ef61bb0fecbc45d524257b8d311bd7a90ad90` |
| SAMPLE-02 | `119007d2e4812720f02ffbd5e0805303bc62ccffb5a11be87e88abcf1673767c` |
| SAMPLE-03 | `b010471d5c0c9c034b8ef3151e0639ac5b411a08ca8987692b9492616d25260a` |
| SAMPLE-04 | `35aa3a66c553797fa74ead57f67905caf1690b14d27d8448d8b9d2e81a6661ef` |
| SAMPLE-05 | `900a664f527fa989c8e5e9e1015997e24a5ebeb418f0b44d993010175574e6fa` |
| SAMPLE-06 | `b526a378610483d69baf31459ea9608d4b761843e63d817ef1eec47256e2da23` |
| SAMPLE-07 | `cc2d28aec00ca598122a963f317a39fae5206264fa9d514432e91a79a7a01ec0` |

### Baseline được tái lập chính xác

Evidence local: `evaluation/runs/20261101-rqr-extractor/`.

1. Snapshot `before/` có **146 file** code/config/prompt, `product-extractor-v4`; đã đối chiếu đủ mọi hash trong manifest, không có lệch. Manifest SHA-256: `2cd70f635957ea3fc46b9c7de3fc6aa057abc1a6bca297870b53ff8c9de21709`.
2. `bootstrap-old/sitecustomize.py` xác minh 146 hash rồi preload **package source cũ**, đặt `AGENT_HOME`, `PROMPTS_DIR`, `EXTRACTOR_PROMPT` tới snapshot. Lệnh thực thi vẫn là **`run_eval.py` tại gốc repo**, không có SDK invocation riêng. `baseline-preflight.json` xác minh scorer, structured helper, config và harness thực sự import từ snapshot. Chỉ đổi prompt cũ trên code mới không được coi là baseline.
3. Replies lấy từ `evaluation/runs/20261028-public-sample-v4/`, full và baseline lịch sử, giữ riêng theo config. `source-lock.json` ở hai thư mục input khóa trace gốc và trace chọn lại. `environment-lock.json` khóa root command, backend common, model config, prompt, KB/pack/scorer và budget snapshot.
4. Chạy **SAMPLE-01 trước**, rồi đủ 7 mẫu; cả hai thoát mã 0, không failed/unlabelled/schema error. `baseline-v4-smoke/`: 14 cache hits; `baseline-v4-cohort/`: **78 cache hits, 0 model calls, 0 retry**. Chi phí mới **0 USD**; ledger không đổi 10.220 requests.

Lệnh baseline cohort (từ gốc repo; đổi input/output sang `*-smoke` để tái lập smoke):

```bash
EVAL_CODE_SNAPSHOT="$PWD/evaluation/runs/20261101-rqr-extractor/before" \
PYTHONPATH="$PWD/evaluation/runs/20261101-rqr-extractor/bootstrap-old:$PWD/packages/backend-common" \
BTC_DATA_DIR="$PWD/apps/ai-agent-service/data/btc" \
EVAL_RUNS_DIR="$PWD/evaluation/runs" \
EVAL_BUDGET_DB="$PWD/evaluation/runs/20261024-work/budget.sqlite" \
apps/ai-agent-service/.venv/bin/python run_eval.py \
  --relabel evaluation/runs/20261101-rqr-extractor/relabel-input-cohort \
  --out evaluation/runs/20261101-rqr-extractor/baseline-v4-cohort
```

### Số baseline v4 — cùng extractor_version, cùng historical replies

| Main scorer, relabel v4 | full | baseline_no_memory |
|---|---:|---:|
| RQR | 13,3% (2/15) | 17,6% (3/17) |
| CCR từ extractor, cận dưới | 33,3% (7/21) | 23,8% (5/21) |
| TSR | 28,6% (2/7) | 28,6% (2/7) |
| HR tổng | 22,2% (6/27) | 24,0% (6/25) |
| HR giá/KM | 17,6% (3/17) | 25,0% (3/12) |

RQR full giảm tương đối **24,4%** so baseline trong **v4**, chưa đạt ngưỡng 40%. `--relabel` xóa toàn bộ `facts_used` cũ và không khôi phục citation brief, nên CCR full **33,3%** khác 38,1% của live run 28/10: đây không phải agent bị giảm chất lượng. Không so lẫn CCR live với CCR relabel. TTFT/latency trong trace là lịch sử 28/10, 39 lượt/config, dưới 100 lượt; không phải latency của lần đo hiện tại.

### Protocol extractor mới và ngân sách

- Chỉ bắt đầu khi **cả** `docs/evaluation/extractor-implementation.json` và `docs/evaluation/rqr-policy.json` có `status: ready`. Chụp source/model/prompt/scorer/KB trước đo và kiểm hash lại sau đo; thay đổi giữa run làm kết quả INCOMPLETE.
- Smoke trace đầu tiên thuộc SAMPLE-01 trước cohort để kiểm auth/budget/schema. Nếu provider auth lỗi hoặc cap không đủ, **dừng**, giữ reservation, ghi INCOMPLETE; không chạy cohort tiếp và không đổi provider/model để lách ledger. Helper không retry lỗi invocation.
- Sau smoke, `run_eval.py --relabel .../relabel-input-cohort --out ...` trên đúng 78 replies đã khóa. So **old/new extractor trên cùng replies** để đánh giá instrument; đây không phải bằng chứng agent hiện tại tốt hơn. Trong mỗi version mới so full/baseline lịch sử riêng, cùng agent/model/prompt/tools/KB, khác bộ nhớ. Nếu chạy lại product sau này cần paired run riêng, một scenario trước cohort; không gộp vào delta extractor.
- Sổ hiện có duy nhất cho task: `evaluation/runs/20261024-work/budget.sqlite`, luôn truyền `EVAL_BUDGET_DB`. Không recreate, tăng cap, xóa request hoặc tự settle phần thiếu usage. Trước run: cap **50 USD**; usage theo token đã settle **9,949699483 USD**; **34,635910405 USD** dự phòng chưa đối soát (87 requests); tổng giữ **44,585609888 USD**; headroom **5,414390112 USD**. Đây không phải hóa đơn billing đã đối soát.
- Đã kiểm key presence theo boolean, không ghi giá trị key. Advisor/memory/extractor giữ `openai:gpt-4.1-mini`, temperature 0 và giới hạn token của snapshot; policy giữ TypeSafe Jev theo config, không tự tắt/đổi model. Relabel chỉ cần OpenAI, không cần PostgreSQL/Redis và không đụng Docker.
- Giá OpenAI kiểm ngày 01/11/2026: [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini), 0,40 USD/1M input, 1,60 USD/1M output, khớp budget callback. Giá cache input không dùng để giảm bảo lưu. Mỗi request extractor phải còn ít nhất 0,425584 USD reservation theo code hiện có.
- `protocol.json` là kế hoạch và `environment-lock.json` là khóa bằng chứng; chưa có số extractor mới hoặc current-agent delta cho đến khi có manifest/trace và run hoàn tất.

### Cập nhật phép đo v5 sau gate ready

- Hai file readiness đã `ready`; toàn bộ hash bàn giao khớp. Snapshot mới `after/` có **150 file** source/config/prompt/contracts; instrument `product-extractor-v5`, SHA-256 `e6c9e6fe3e7dd6cdc25dcca7d1616d604c6b4ad3e88cac8ec4ab96c16c76e721`. Snapshot dùng layout `apps/ai-agent-service` để đường đọc contract bằng `ROOT.parents[1]/docs/evaluation` giữ nguyên; preflight khẳng định hash runtime khớp bản ready.
- Root `run_eval.py` vẫn là entrypoint, `bootstrap-new/` chỉ chọn package frozen mới; model config không đổi. Chạy theo đúng thứ tự: `new-v5-api-smoke/` (1 lượt, không lấy bảng thiếu scenario làm metric) → `new-v5-smoke/` (SAMPLE-01, 14 lượt full/baseline) → `new-v5-cohort/` (78 lượt).
- API smoke: 1 call, 0 lỗi/retry. Scenario smoke: 13 calls + 1 cache hit, 0 lỗi/retry; 7 lượt/config, không failed/unlabelled/schema error. Sau hai smoke, chi phí token mới **0,049444406 USD**, không có reservation mới chưa settle; headroom **5,364945706 USD**. Cohort mới đang chạy, chưa công bố số v5.
- Lệnh cohort giống lệnh baseline ở trên, đổi `before` → `after`, `bootstrap-old` → `bootstrap-new`, output `baseline-v4-cohort` → `new-v5-cohort`. Không dùng trace mới sinh từ agent và không thay model/GT giữa full/baseline.

### Kết quả cuối attempt v5 — INCOMPLETE, không có bảng điểm

- `new-v5-cohort/` thoát **mã 1**. Đã xử lý 39 lượt full + 39 lượt baseline; **77/78 lượt đủ nhãn**. Full: 0 lỗi nhãn; baseline: **1 unlabelled**, không có lỗi schema trace/agent. Cohort dùng **62 model calls + 16 cache hits**, 1 failure, **0 retry**, 0 repair; cộng hai smoke: **76 model requests thật**, không chạy lại agent.
- Lượt lỗi: **baseline_no_memory / SAMPLE-04 / call_2 / turn 3**. Native structured output ném `ValidationError` tại `Items.items.9`: `end phải lớn hơn start cho quote không rỗng`. Đây là lỗi validation span trong output; helper phân loại exception phát ra ở invocation là không retry. Diagnostics giữ nguyên lỗi; task này không sửa helper do luồng extractor sở hữu. Không tự gọi lại model, không đổi config, không loại lượt để lấy điểm.
- Root command đã chặn bảng đúng quy tắc: **không có `new-v5-cohort/report.json` hay `table.txt`**. RQR/CCR/TSR/HR v5 của cohort và delta v4→v5 **CHƯA ĐO ĐỦ / INCOMPLETE**; không thay missing bằng 0 hoặc PASS. Bảng baseline v4 ở trên vẫn hợp lệ theo phạm vi đã nêu. Không dùng bảng API smoke một lượt làm kết quả scenario/cohort.
- Toàn bộ trường trace ngoài `questions`, `claims`, `facts_used` đã đối chiếu đúng với input lịch sử cho cả smoke/cohort. Không có agent call, PostgreSQL/Redis hoặc Docker trong task này. Không sửa scenario/labels hoặc chấm trực tiếp bằng script khác root command.
- Hai snapshot frozen trước/sau đo đều không đổi hash. Trong khi phép đo chạy, working copy `config/prompts/evaluation/extractor.txt` đổi so bản ready ban đầu; frozen `after/` và instrument đã chạy không đổi. Phép đo này gắn với snapshot v5 SHA `e6c9e6fe3e7dd6cdc25dcca7d1616d604c6b4ad3e88cac8ec4ab96c16c76e721`; không tự gán cho prompt đang sửa. Trước retest cần luồng sở hữu cập nhật ready/hash và snapshot revision mới.

| Trace cohort | SHA-256 |
|---|---|
| v4 full | `bc95fac1432672dd75f3d9fb45bd7ed2386ce70dd9ae1c26867c8ad113ff4290` |
| v4 baseline | `660444b0a2ee3e5cbc5afffecafc97baf70a3b69733d03e63f2ff19ada350fad` |
| v5 full | `8f5ef89e407bbb134f3598dbab080013ab30d1edc2f6446f1029271788ea606b` |
| v5 baseline (1 unlabelled) | `fdeff025ee2c5c7fb43ee086729fff3e8159ba00c45c6ff71a279ba7c5e209be` |

Các hash report/diagnostics/log và toàn bộ provenance ở `new-v5-result.json`, `summary.json`, `environment-lock.json` trong evidence private. ASR/hypothesis hash: **không áp dụng**, không chạy ASR trong task này.

**Ngân sách cuối task:** 75 request có usage đã settle **0,267342834 USD**; 1 request lỗi native parse giữ nguyên dự phòng **0,425584 USD**; tổng giữ mới **0,692926834 USD**. Không giả định request lỗi miễn phí. Ledger toàn cục: usage đã settle **10,217042317 USD**; dự phòng chưa đối soát **35,061494405 USD** (88 requests); tổng giữ **45,278536722 / 50 USD**; headroom **4,721463278 USD**. Không reset ledger, không tăng cap, không xóa/settle thủ công reservation. Đây là token accounting và dự phòng, chưa phải hóa đơn provider đã đối soát.

**Bàn giao:** `new-v5-result.json` chỉ ra field lỗi để chủ sở hữu structured helper xem đường native parse/repair. Retest phải được ghi như attempt mới, giữ bằng chứng attempt INCOMPLETE này và dùng đúng cùng replies; không thay score của attempt đã đóng. Chưa có bằng chứng agent hiện tại cải thiện hoặc extractor v5 chính xác hơn; semantic labels vẫn diagnostic, không phải human-approved gold.


### Retest v6 — 01/11/2026, cùng cohort/replies, attempt riêng

**Trạng thái cuối v6: COMPLETE sau đúng một caller replay; cohort attempt đầu INCOMPLETE được giữ nguyên.** Bản v5 ở trên vẫn đóng INCOMPLETE, không ghi đè evidence hoặc giải phóng reservation.

- Root đã sửa đường native parse: gửi `Items.model_json_schema()` cho provider, nhận raw/usage rồi mới Pydantic validate tại helper; lỗi output có thể repair/retry với đầy đủ lỗi. Readiness v6 báo 155 test offline, có real ChatOpenAI SDK + MockTransport sync/async tái hiện invalid span. Đây là bằng chứng regression của luồng code, không tự phê duyệt semantic gold.
- Đã kiểm lại đủ hash trong `extractor-implementation.json` và `rqr-policy.json`, cả hai `ready`. Snapshot **`after-v6/`**, 150 file source/config/prompt/contracts, giữ nguyên prompt user đang có; `product-extractor-v6`, instrument SHA-256 **`e5502a3253b8b64b43b43a431182924efa5fdafb1853fd0579f4b2f81c1fe219`**. `before/` v4 và `after/` v5 không đổi.
- Bootstrap `bootstrap-v6/` chọn toàn bộ package frozen; preflight runtime khớp instrument ready. Root entrypoint, model config, main scorer/KB/pack và cohort/replies giữ nguyên; không đổi GT/provider, không chạy agent hoặc ASR. Không nạp raw labels cũ vào model.
- Khởi điểm ledger: rowid **10296**, headroom **4,721463278 USD**, 88 reservations cũ chưa settle được giữ. Mỗi command truyền `EVAL_BUDGET_DB` hiện có. Không tăng cap, không reset, không gọi SDK trực tiếp. Quy trình: root `run_eval.py --relabel .../relabel-input-smoke --out .../new-v6-smoke`, kiểm SAMPLE-01 xong rồi root `--relabel .../relabel-input-cohort --out .../new-v6-cohort`.
- Lệnh frozen giống v5, đổi snapshot `after` → `after-v6`, bootstrap `bootstrap-new` → `bootstrap-v6`, output `new-v5-*` → `new-v6-*`. `v6-protocol.json` khóa hash readiness/snapshot/cohort/root command và trạng thái budget ban đầu.

- SAMPLE-01 v6: **14/14 lượt đủ nhãn**, exit 0; **15 model calls, 1 lỗi output được retry thành công**, 0 unlabelled/schema/agent error. Chi phí **0,053286407 USD**, cả 15 attempts đều có usage và đã settle, không tạo pending mới. Bằng chứng recovery: baseline/SAMPLE-01/call_2/turn 3, `InvalidOutput` được helper xử lý; không phải retry lỗi auth/network/budget. Cohort 78 lượt bắt đầu sau gate này.

- Cohort v6 lần đầu (`new-v6-cohort/`) đóng **INCOMPLETE**, exit 1, **77/78** nhãn: full/SAMPLE-05/call_2/turn 3 hết hai attempts với `InvalidOutput` / `Items.items.8` / `end phải lớn hơn start cho quote không rỗng`. Full có 1 unlabelled; baseline đủ 39 nhãn. Cohort: 65 calls + 16 cache hits, 4 output failures trong đó 2 đã recovery và 1 lượt hết hai attempts, 3 retries; không có lỗi invocation/auth/budget. Không có report/table hoặc paired metrics của attempt này.
- Smoke + cohort v6 dùng **80 requests, tất cả đã settle usage: 0,286745232 USD**, không thêm pending mới. Hash của toàn bộ 10.296 ledger rows trước v6 không đổi; pending v5 vẫn giữ. `new-v6-r0-result.json` giữ result, errors và file hashes, không ghi đè attempt.
- Chạy **một completion retest riêng** `new-v6-replay/` trên cùng instrument v6 và đúng 78 replies, không thay source/model/prompt/GT; 77 labels thành công dùng cache, chỉ lượt thiếu nhãn gọi lại model. Đây là xử lý thiếu output hợp lệ, không lựa nhãn theo score (attempt trước chưa có bảng). Không ghép full v5 với baseline v6 hoặc bỏ lượt lỗi. Nếu completion retest vẫn thiếu nhãn thì giữ INCOMPLETE, không lặp vô hạn.


### Kết quả v6 hoàn tất sau một caller replay — không phải first-pass 78/78

- **`new-v6-replay/`: COMPLETE, exit 0, 78/78 lượt đủ nhãn**, 39 full + 39 baseline, 0 failed/unlabelled/schema/after_call error. **77 cache hits + 2 model attempts** cho duy nhất full/SAMPLE-05/call_2/turn 3; output đầu vẫn invalid, helper retry thành công. Không sửa schema/prompt/source/contract/config hoặc nhãn giữa initial run và replay. Không có caller replay thứ hai.
- Phân biệt độ ổn định: attempt `new-v6-cohort/` đầu tiên chỉ đạt **77/78 sau helper retries**, vẫn đóng INCOMPLETE. Replay hoàn tất dữ liệu để chấm, không biến attempt trước thành PASS hoặc chứng minh first-pass reliability 100%. Smoke + initial cohort + replay cộng **82 model attempts**, 6 output-validation failures ghi trong stats, 5 helper retries, 0 local JSON repair; tất cả attempts có usage và đã settle.
- Mọi hash của `before/`, `after/`, `after-v6/` không đổi; live readiness/source/prompt/contracts vẫn khớp frozen v6 khi kết thúc. Hash toàn bộ **10.296 dòng ledger trước v6 không đổi**, gồm pending của v5. Root command/main scorer/KB, 7 scenario hashes và mọi trường reply/tool/history ngoài ba nhãn đều đối chiếu giữ nguyên.

**Đối chiếu instrument trên đúng cùng 78 replies lịch sử**, không phải delta chất lượng agent hiện tại:

| Main scorer / relabel | v4 full | v6 full | v4 baseline_no_memory | v6 baseline_no_memory |
|---|---:|---:|---:|---:|
| RQR | 13,3% (2/15) | 13,3% (2/15) | 17,6% (3/17) | 17,6% (3/17) |
| CCR, extractor-only cận dưới | 33,3% (7/21) | 42,9% (9/21) | 23,8% (5/21) | 14,3% (3/21) |
| TSR | 28,6% (2/7) | 28,6% (2/7) | 28,6% (2/7) | 28,6% (2/7) |
| HR tổng | 22,2% (6/27) | 23,1% (6/26) | 24,0% (6/25) | 25,0% (5/20) |
| HR giá/KM | 17,6% (3/17) | 18,8% (3/16) | 25,0% (3/12) | 20,0% (2/10) |

- **Không có giảm RQR trên cohort này:** trong mỗi version, main báo full giảm tương đối **24,4%** so baseline, chưa đạt 40%; TSR và HR giá/KM full vẫn không đạt ngưỡng. RQR aggregate giữ nguyên dù hai lượt full ở eligible calls thay đổi projection slot/type; baseline eligible projection giữ nguyên. Tổng question items ở mọi call (bao gồm call bị RQR loại) đổi full **29→33**, baseline **34→35**; không đồng nhất chúng với mẫu số RQR 15/17.
- CCR/HR đổi là **nhãn do instrument khác sinh trên lời cũ**; denominators của HR cũng đổi, nên không trình bày như agent giảm/tăng hallucination thật. Chưa có human-approved gold để kết luận v6 chính xác hơn. Claim `restock_date` tại full/SAMPLE-06/call_2/turn 2 vẫn bị main đánh sai như v4; lỗi semantic đã nêu trong báo cáo 28/10 chưa thể coi là đã hết. Không sửa GT để khớp model.
- Current-agent delta, live CCR/citation brief và latency mới **chưa đo**. Latency trong trace là lịch sử 28/10, 39 lượt/config; không dùng như benchmark latency hiện tại. Không ghép nhãn hoặc full/baseline từ khác extractor_version.

| Trace v6 hoàn tất | SHA-256 |
|---|---|
| full | `47147f084dcc7e9b80abd86908bd3532e667ff597e74a7f39a1507e7e806ff58` |
| baseline | `c5bd0c650eb9a410c23085f919c2ffbeda35285dfa333161a382ece98fe1f489` |

`new-v6-result.json` ghi version, paired reports theo từng instrument, mọi trace/report/diagnostic/log hash, proof giữ nguyên replies, budget và giới hạn reliability. `new-v6-r0-result.json`, `new-v5-result.json` và các thư mục attempt cũ được giữ nguyên. `summary.json` là điểm vào tổng hợp private. Không có raw hội thoại/key trong ledger này.

**Ngân sách cuối v6:** 82 requests đều settle **0,294994033 USD**, trong đó replay 2 attempts **0,008248801 USD**; không thêm reservation pending. Cộng v5 + v6 của task: **158 requests**, usage đã settle **0,562336867 USD**, giữ nguyên pending v5 **0,425584 USD**; tổng giữ mới **0,987920867 USD**. Ledger toàn cục: settled **10,512036350 USD**, pending **35,061494405 USD** (88 requests), tổng giữ **45,573530755/50 USD**, headroom **4,426469245 USD**. Không reset, tăng cap, xóa request hoặc manual settle. Token accounting vẫn không phải hóa đơn provider đã đối soát.


### Retest v7 — 01/11/2026, sửa ranh giới restock/delivery, cùng replies

**Trạng thái cuối v7: COMPLETE ngay cohort attempt đầu, sau một helper output retry; không caller replay.** Giữ nguyên baseline v4, attempt v5 và mọi attempt v6, gồm v6 COMPLETE sau replay; không đổi kết quả cũ.

- Audit trên development replies xác nhận lỗi cũ: cụm ngày giao được v4/v6 gán `restock_date` khi quote không chứa chủ thể nhập/bổ sung kho. Root sửa quy tắc tổng quát trong prompt và deterministic projection; không thêm ID, ngày GT hoặc giá cohort vào prompt, không sửa GT để lấy điểm. Readiness báo 11 synthetic regressions và full suite **548 passed, 9 skipped**; đây là test của chủ sở hữu code, không phải human-approved semantic gold.
- Đã kiểm đủ readiness/hash, cả policy và implementation `ready`. Frozen **`after-v7/` 150 file**, `product-extractor-v7`, instrument SHA-256 **`0a1ac711e04f9f32f835b72da65843afead5a93c0db20e9e9fc5f1912acfb6ce`**; model config, structured helper v6, root entrypoint, main scorer/KB/pack và cohort/replies giữ nguyên. Tất cả snapshot trước vẫn khớp manifest.
- Ngân sách trước v7: rowid **10378**, headroom **4,426469245 USD**, 88 pending cũ giữ nguyên. `v7-protocol.json` khóa hash 10.378 prior ledger rows, readiness/snapshot/cohort/root command. Mọi call qua root `run_eval.py --relabel`, luôn truyền ledger hiện có; không SDK riêng, không agent/Docker/ASR.
- `new-v7-smoke/` dùng SAMPLE-01 (14 lượt) trước `new-v7-cohort/` (78 lượt). Nếu chỉ lỗi output còn thiếu nhãn, cho phép tối đa **một** caller replay output mới, cùng v7 và cache các lượt đạt; không replay invocation/auth/budget. Không sửa source/prompt/schema/contract trong khi đo.
- Lệnh frozen giống v6, đổi snapshot/bootstraps sang `after-v7` / `bootstrap-v7`, output `new-v7-*`. Audit sau run phân biệt raw model items với claims cuối sau projection, kiểm lỗi ngày giao đã biết và các claim nhập kho thực sự; không coi mọi claim bị xóa là chứng minh model đúng.

- SAMPLE-01 v7 smoke: **14/14 lượt đủ nhãn, exit 0**, 14 model calls, 0 lỗi/retry/repair/cache hit; tất cả 14 requests đã settle **0,049780408 USD**. Headroom trước cohort **4,376688837 USD**. Kiểm frozen hash xong mới bắt đầu cohort.


### Kết quả v7 — COMPLETE, không caller replay

- **`new-v7-cohort/`: exit 0, 78/78 lượt đủ nhãn**, 39 full + 39 baseline; không failed/unlabelled/schema/after_call error. Cohort: **63 model attempts + 16 cache hits**, 1 output failure được helper retry thành công, 0 repair. Lượt recovery: full/SAMPLE-05/call_2/turn 3, `InvalidOutput`. Không có auth/network/budget error và không dùng quyền caller replay dự phòng.
- Đây là **78/78 ở cohort invocation đầu sau helper retry**, không phải mọi raw output đều đúng ngay lần model đầu tiên. Khác v6: v6 initial cohort 77/78 sau helper retries và cần một caller replay riêng mới complete. Không gộp hai mức reliability hoặc coi schema completeness là semantic accuracy.

**Cùng 78 replies, main scorer và GT, đối chiếu ba instrument đã ghi version:**

| Extractor / config | RQR | CCR, extractor-only | TSR | HR tổng | HR giá/KM |
|---|---:|---:|---:|---:|---:|
| v4 full | 13,3% (2/15) | 33,3% (7/21) | 28,6% (2/7) | 22,2% (6/27) | 17,6% (3/17) |
| v6 full | 13,3% (2/15) | 42,9% (9/21) | 28,6% (2/7) | 23,1% (6/26) | 18,8% (3/16) |
| v7 full | 13,3% (2/15) | 42,9% (9/21) | 28,6% (2/7) | 19,2% (5/26) | 18,8% (3/16) |
| v4 baseline_no_memory | 17,6% (3/17) | 23,8% (5/21) | 28,6% (2/7) | 24,0% (6/25) | 25,0% (3/12) |
| v6 baseline_no_memory | 17,6% (3/17) | 14,3% (3/21) | 28,6% (2/7) | 25,0% (5/20) | 20,0% (2/10) |
| v7 baseline_no_memory | 17,6% (3/17) | 14,3% (3/21) | 28,6% (2/7) | 25,0% (5/20) | 22,2% (2/9) |

- RQR và TSR **không đổi** trên cohort này. Trong mỗi version, full giảm tương đối **24,4%** RQR so baseline, vẫn dưới 40%; TSR và HR giá/KM full vẫn không đạt ngưỡng. CCR trong bảng là relabel cận dưới không có citation brief; không so lẫn live CCR 28/10.
- HR tổng full đổi v6 **23,1% (6/26)** → v7 **19,2% (5/26)**. Đây là thay đổi nhãn/instrument trên lời cũ, không phải agent vừa giảm hallucination. Full HR giá/KM giữ 18,8%; baseline HR giá/KM đổi mẫu số 10→9 nên 20,0%→22,2% dù số claim sai vẫn 2. Không chọn nhãn, loại scenario hay sửa GT để cải thiện bảng.

**Audit restock sau projection và raw model:**

- Full/SAMPLE-06/call_2/turn 2: v4/v6 có claim sai `restock_date` lấy từ ngày giao; v7 **không có `restock_date` ở raw items hoặc trace cuối**. Lỗi cụ thể này không còn trong output v7 đã đo.
- Full/SAMPLE-01/call_2/turn 3 (delivery) và full/SAMPLE-03/call_2/turn 3 (đơn hoàn về kho): raw model v7 vẫn sinh **3 restock items** (1 + 2). Chốt deterministic đã loại cả 3; trace cuối không giữ chúng. Không mô tả đây là model đã hiểu đúng cả ba câu.
- Trên toàn 78 lượt v7: **3 raw restock items, 0 final restock claims**. Chưa có tập positive restock được human review để tính recall/sensitivity, nên số 0 không tự chứng minh extractor giữ được mọi ngày nhập kho thật. 11 synthetic regressions của root là bằng chứng code riêng; không thay cho semantic gold. `v7-restock-audit.json` giữ identity, raw items, cache key/hash và claims cuối để kiểm tay, không đưa raw hội thoại vào ledger.
- Fresh model extraction giữa các version có thể đổi các claim khác; không suy rằng toàn bộ delta HR chỉ do một dòng deterministic code. Phạm vi kết luận là những lỗi đã audit và bảng same-reply của từng instrument; không claim semantic accuracy human-approved hoặc agent hiện tại cải thiện.

| Trace v7 | SHA-256 |
|---|---|
| full.jsonl | `eb17ba983c2fd29945c1ffd9f8f070b91dbbb89568e5b3c6c3e1b8eac604ac18` |
| baseline.jsonl | `7ddd2e68d0be2b247501f7d2de268917dc98c4cd2132106f84e4707b5dd42fb2` |

`new-v7-result.json` chứa paired reports v4/v6/v7, proof mọi trường reply/tool/history ngoài nhãn giữ nguyên, error/recovery stats, audit và toàn bộ trace/report/diagnostics/log hash. `v7-protocol.json` khóa instrument/snapshot/cohort/root command; `summary.json` tổng hợp. Mọi file trong `before/`, `after/`, `after-v6/`, `after-v7/` vẫn khớp manifest; source/prompt/contracts live và main scorer/KB/pack vẫn khớp khóa sau run. Toàn bộ **10.378 ledger rows trước v7 không đổi**, gồm mọi pending. Không chạy agent, ASR, Docker, commit/push/deploy.

**Ngân sách v7:** smoke 14 attempts **0,049780408 USD**; cohort 63 attempts **0,228585626 USD**; tổng **77 attempts, 0,278366034 USD**, tất cả đã settle usage, không thêm pending. Cộng v5/v6/v7 của task: **235 requests**, settled mới **0,840702901 USD**, pending v5 giữ nguyên **0,425584 USD**, tổng giữ mới **1,266286901 USD**. Ledger toàn cục: settled **10,790402384 USD**, pending **35,061494405 USD** (88 requests), tổng giữ **45,851896789/50 USD**, headroom **4,148103211 USD**. Không manual settle/reset/tăng cap. Đây là token accounting và dự phòng, chưa phải hóa đơn provider đối soát.
