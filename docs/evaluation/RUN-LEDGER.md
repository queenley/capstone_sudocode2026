# Lịch sử chạy evaluation

Đọc file này trước khi chọn case. Đây là mục theo dõi chung; raw log/trace giữ local, không commit.
Một scenario chạy cả full/baseline vẫn là một scenario mới về độ phủ. Chạy R1 cùng cohort là retest có chủ đích, không cộng vào số case mới.

Từ 25/10/2026, `scripts/evaluation/` đổi thành `evaluation/harness/` và `scripts/create_data/` thành `evaluation/data-generation/`. Các mục bên dưới giữ đường dẫn lúc ghi; thư mục bằng chứng `scripts/evaluation/runs/<run>` giờ nằm ở `evaluation/harness/runs/<run>`, nội dung không đổi.

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
