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

### 2026-11-08 · Màn hình giám sát: gộp phiên theo khách, Call Brief lên đầu, chuông báo đỏ qua Kafka

Loại: tính năng · Trạng thái: xong · Chỉ số: không có (giao diện nhân viên); e2e

- **Vấn đề:** hàng chờ của `/calls` và `/ban-hang` có một dòng cho mỗi phiên, nên một khách nhắn web, rồi Zalo, rồi gọi hotline chiếm ba dòng rời nhau. Call Brief nằm cuối cột "Bằng chứng" bên phải, dưới phần ngữ cảnh. Khi trợ lý chuyển máy, nhân viên chỉ thấy ở lần tải lại kế tiếp (5 giây ở `/calls`, 10 giây ở `/ban-hang`). Hook báo động `useHandoffAlerts` có sẵn nhưng không trang nào gắn vào.
- **Bằng chứng:** đọc code. `handoff.requested` đã được ghi vào outbox (`runtime/platform.py`) và worker đẩy lên topic `telesales.sales.events`, nhưng không ai nghe topic đó để báo cho nhân viên. Chỉ cuộc web chat (có `conversation_id`) ghi outbox; hotline và Zalo đặt `handoff_status = 'pending'` thẳng vào bảng `calls`.
- **Sửa:**
  - **Backend.** Thêm `runtime/alerts.py`: một hub đánh thức các luồng đọc khi có handoff. Hub được gọi từ `calls.request_handoff`, `accept_handoff`, `hang_up` và từ harness khi trợ lý chuyển máy. Một consumer Kafka chạy trong thread riêng, mỗi process một consumer group (`auto.offset.reset=latest`), nên mọi instance đều nghe được và không lấy mất message của worker outbox. Danh sách khách chờ luôn đọc từ bảng `calls`: Kafka chỉ báo lúc cần đọc lại, nhờ vậy hotline và Zalo vẫn hiện dù không đi qua outbox.
  - **Endpoint.** `GET /api/agent/handoffs/stream` (SSE) gửi `handoffs` mỗi khi danh sách đổi, gửi keepalive mỗi 15 giây, và tự đóng sau 100 giây để vừa giới hạn 120 giây của proxy. Không có `KAFKA_BROKERS` thì vẫn đọc lại mỗi 5 giây. `_call` trả thêm `handoff_requested_at`.
  - **Chuông.** `HandoffBell` đọc stream bằng fetch, vì EventSource không gửi được token nhân viên. Stream không mở được hai lần thì chuyển sang polling 5 giây và thử lại. Chuông đỏ, có số đếm và rung khi có người chờ; kêu chuông và thông báo trình duyệt như hook cũ. Danh sách mở ra ghi thời gian chờ, lý do và nguồn tín hiệu (Kafka, máy chủ đọc lại, hay trang tự tải). Toast được render qua portal, vì `.sl-topbar` giữ phần tử `fixed` ở đầu trang. Chuông được gắn vào header `/calls` và topbar `/ban-hang`; bấm vào thì mở cuộc gọi đó trong tab hội thoại.
  - **Hàng chờ.** `features/call-groups.ts` gộp các phiên theo `customer_id`. Phiên không có `customer_id` (khách lạ, số dùng chung) vẫn đứng riêng, vì không có căn cứ để gộp. Thứ tự: nhóm có người chờ trước, rồi nhóm đang mở, rồi mới nhất. Phía trên brief có dải "Các phiên của khách này" để chuyển giữa các phiên.
  - **Call Brief.** Component riêng ở đầu khung hội thoại, gập được: bàn giao từ trợ lý cạnh brief và cảnh báo, khung đỏ khi khách đang chờ. Cột phải chỉ còn ngữ cảnh, các lượt của trợ lý và after-call.
- **Đã kiểm:**
  - `tests/agent/test_handoff_alerts.py` (7 test): hub đánh thức mọi luồng đọc, kể cả khi bị gọi từ thread Kafka; chỉ sự kiện làm đổi danh sách chờ mới kêu; không có Kafka thì đọc lại theo nhịp; stream gửi lại khi danh sách đổi; một lần đánh thức đến trước nhịp đọc lại.
  - `e2e/call-console.spec.ts`: thêm 4 test (gộp 3 phiên của một khách thành một dòng và chuyển phiên; chuông đỏ từ stream rồi mở cuộc gọi; polling khi stream trả 502; chuông ở `/ban-hang` mở tab hội thoại). Cả 6 test pass trên dev server.
  - Test demo trong `redesign-snapshots` đọc brief ở vị trí mới; 3 test console và sales pass. `tsc` sạch. Toàn bộ `tests/` trên venv của `ai-agent-service` (Python 3.12): 1.391 passed, 35 failed, 14 errors. Tất cả fail và error nằm ở ASR và voice (`test_asr_*`, `test_voice_transport`), cộng thêm `test_settlement_does_not_recreate_a_missing_ledger` (Windows khóa file SQLite). Test này cũng fail trên HEAD khi chưa có thay đổi.
- **Số đo:** không có chỉ số agent. e2e console: 6/6.
- **Còn lại:**
  - Handoff của hotline và Zalo chưa ghi outbox, nên instance khác chỉ thấy sau tối đa 5 giây. Muốn tức thì thì cần ghi `handoff.requested` cho cả cuộc không có `conversation_id`; `aggregate_id` của outbox phải là UUID.
  - Hàng chờ chỉ gộp các phiên trong 50 cuộc gần nhất.
  - Chưa thử với Kafka thật (profile `async` của docker-compose).

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

### 2026-11-09 · Lần kiểm thứ hai: thanh toán, diện tích, kịch bản chung SĐT (nhóm 27–31)

Loại: dữ liệu · Trạng thái: xong (nhóm 19–24, 31 chờ duyệt) · Chỉ số: TSR, RQR, CCR

- **Vấn đề:** một người kiểm khác đọc từng cuộc của dev và test, báo khoảng 40 nhãn sai.
  - `args_match.payment` ghi cách thanh toán khách không nói (4 cuộc dev).
  - `room_area_m2` không có trong lời khách: khách quay lại đã chuyển nhà, lịch sử CRM 20 m² đã quá hạn (9 cuộc dev, 2 test).
  - Ở kịch bản hai người chung SĐT, call_2 gán fact của người kia (dev 18, test 4), kèm vài câu lẫn vai.
  - README của test mô tả sai ("chỉ lời khách được viết lại").
  - DISPUTES ghi "chưa có golden_manifest".
- **Bằng chứng:** đọc lại từng cuộc trong danh sách của người kiểm; mọi mục đều đúng. So test với dev: 51 cuộc đổi ngày, GEN-0033/c2 và GEN-0049/c2 đổi `hen_goi_lai` sang `chot_don`. `auto_verify.py` (và danh sách nhóm 14) đã coi lịch sử CRM là "khách đã nói", và chỉ cần có một số đi kèm m², không đối chiếu giá trị.
- **Sửa:**
  - Nhóm 27: khách nói cách thanh toán.
  - Nhóm 28: khách nói diện tích phòng mới.
  - Nhóm 29: bỏ fact người gọi call_2 không nói.
  - Nhóm 30: câu đúng vai; cô Loan xưng "cô" như CRM.
  - Nhóm 27–30 ghi là người duyệt yêu cầu.
  - `grounded` của `auto_verify.py` giờ khớp giá trị, không tính lịch sử CRM, và ở kịch bản chung SĐT chỉ tính lời trong chính cuộc đó. Bộ đọc số đọc được "4.500.000đ" và "7 triệu bảy trăm".
  - Bộ kiểm chặt hơn lộ thêm 2 nhãn `has_children` không có căn cứ (GEN-0066/c1, GEN-0181/c1): thành nhóm 31, chờ duyệt.
  - Xoá quyết định cũ trong `review_sheet.csv` ở 36 cuộc dev và 7 cuộc test có nhãn đổi sau lần ký, để ký lại.
  - Sửa README và DISPUTES.
- **Đã kiểm:** 0 lỗi khóa; oracle CCR 100 · RQR 0 · TSR 100 · HR 0; validator dev 770/797, test 186/192. `auto_verify`: dev 785/801 cuộc nhãn qua, test 189/192; các nhãn còn N chỉ là các nhóm chờ duyệt và ADV-0024/0119 c2 (RUN-10 dùng một lần, nhãn đúng). Pending khớp DISPUTES: dev 23, test 2.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** người duyệt duyệt nhóm 19–24, 31 rồi ký lại. Audio và hội thoại mẫu chưa sinh lại (người duyệt chờ tập khách ổn định).

### 2026-11-09 · Tự động hoá phần kiểm trước bộ vàng; người duyệt ký bằng một lệnh

Loại: evaluation · Trạng thái: xong (chờ người duyệt ký) · Chỉ số: không đổi

- **Vấn đề:** người duyệt muốn hoàn tất bộ vàng tự động. Theo `SKILL.md`, nhãn chỉ thành vàng khi có người duyệt độc lập; Claude không tự duyệt nhãn mình sửa.
- **Sửa:**
  - Chạy lại `validate_rules` trên nhãn mới: dev 773/797 hội thoại mẫu qua, test 186/192.
  - `auto_verify.py` kiểm mọi cuộc, không gọi model: khóa, pending, fact có căn cứ trong lời khách, lời đồng ý, outcome, dữ kiện so với mock BTC, gọi lại, validator, judge, đánh dấu N. Kết quả ghi vào `review/auto_verified.json` (`not_golden: true`) và `review/review_sheet.csv`, có đề xuất Y/N tách riêng cho nhãn (quyết định `official_gt_approved`) và cho hội thoại mẫu (quyết định `golden_manifest.json`); cột duyệt để trống.
  - `approve_gold.py` cho người duyệt ký. `--accept-suggestions` nhận đề xuất nhưng manifest ghi `method` trung thực. Script không cho Y khi validator trượt.
- **Đã kiểm:** dev có 785/801 cuộc nhãn qua, 411 hội thoại dùng được; test có 188/192 và 111. Chạy `approve_gold.py` trên bản sao tạm: không cờ thì từ chối; có cờ thì ghi manifest, `official_gt_approved` vẫn false vì còn nhãn N. Dữ liệu thật chưa ký.
- **Bổ sung:** nhóm 26 do người duyệt quyết. ADV-0031/c1 (dev, test) và ADV-0126/c1 (dev) nói "Nhà anh có một phòng ngủ của con", nên đổi `has_children` false thành true; lời khách giữ nguyên. Regex `grounded` của `auto_verify.py` nhận thêm "của con". Sau khi dựng lại: dev 787/801 cuộc nhãn qua, test 189/192. Các cuộc còn N là nhóm 19–24 đang chờ duyệt và ADV-0024/0119 c2 (giá RUN-10 dùng một lần: nhãn đúng, bộ kiểm chặt).
- **Còn lại:** người duyệt ký. Judge của 245 hội thoại cần chạy lại (gọi model) nếu muốn dùng chúng.

### 2026-11-09 · Rà lại sau khi gộp: trạng thái pending, hội thoại mẫu lỗi, blocker chỉ nói ngân sách, GEN-0099

Loại: dữ liệu · Trạng thái: xong (nhóm 19–24 vẫn chờ duyệt) · Chỉ số: entity_accuracy (ASR); hội thoại mẫu không vào chấm điểm

- **Vấn đề:** người duyệt chỉ ra bốn điểm.
  - `DISPUTES.md` ghi "không còn thay đổi nào ở trạng thái pending", trong khi `conversion-report.json` còn 21 (dev) và 2 (test). Câu này do Claude chèn sai khi thêm nhóm 19–24.
  - Hội thoại mẫu lỗi (33 ca J02 có câu bịa, GEN-0133/c2, 4 ca hỏi quá `max_agent_questions`) chưa được đánh dấu là không dùng.
  - Còn nhãn `vuot ngan sach` ở câu chỉ nói ngân sách.
  - GEN-0099/c1 nói "có một bé lớn" mà `has_children: false`.
- **Bằng chứng:**
  - Đếm `decision` trong `conversion-report.json`.
  - Đọc 29 nhãn `vuot ngan sach` của dev: 15 câu chỉ nói ngân sách, giữ ADV-0110 c2 t4 ("ngân sách eo hẹp quá nên cần trả góp"). Test không có câu loại này. Con số "khoảng 60" là trước khi nhóm 11 bỏ bớt.
  - Quét `has_children: false` có nhắc tới con: chỉ GEN-0099 mơ hồ (GEN-0131 nói rõ "không có bé nhỏ").
- **Sửa:**
  - DISPUTES ghi đúng số đang chờ.
  - Nhóm 11c (bỏ 15 nhãn) và 25 (GEN-0099 nói rõ "nhà không có trẻ nhỏ", nhãn giữ), ghi là người duyệt nêu.
  - `mark_conversations.py` mới ghi `approve: N` kèm lý do vào `review/needs_manual_review.csv`, đúng cơ chế stage 8 của data-generation: người duyệt điền N thì hội thoại luôn bị loại. Đánh dấu dev 217 hội thoại (33 J02, 5 ca trên, 179 cuộc đã đổi lời khách), test 44. Script không ghi `Y` và không chạy `--ingest`, nên không tạo `golden_manifest.json`.
- **Đã kiểm:** số `pending` khớp giữa report và DISPUTES (21, 2). 0 lỗi khóa; oracle CCR 100 · RQR 0 · TSR 100 · HR 0.
- **Còn lại:** bộ vàng cần người duyệt độc lập (`official_gt_approved` vẫn false); nhóm 19–24 chờ duyệt; hội thoại mẫu và audio của các cuộc đổi lời cần sinh lại.

### 2026-11-09 · Một thư mục cho mỗi bộ: nhãn r4 vào thẳng data/dev, r1 vào data/test; ADV-0154 theo LN-02

Loại: dữ liệu · Trạng thái: xong · Chỉ số: không đổi (cùng nhãn)

- **Vấn đề:** hai bản (`data/dev` và `data/dev-r4`, `data/test` và `data/test-r1`) dễ chạy nhầm bản cũ. Người duyệt chọn giữ một thư mục cho mỗi bộ. Ở SCN-ADV-0154/call_1, đáp án ghi kết quả `schedule.callback` là 08:00 (mock BTC thô dời 22:00), trong khi nhãn và `must_say_any` là 22:00.
- **Bằng chứng:** tool `schedule_callback` của agent (`mcp/servers/crm.py`, `clock.SPECIAL_HOURS`) giữ 22:00 ngày 11/11 theo LN-02 (tổng đài 07:00–23:00). Chỉ `mock_tools.schedule_callback` của BTC chưa có ngoại lệ này.
- **Sửa:**
  - `build_dev_r4.py` và `build_test_r1.py` đọc nhãn gốc từ git (`SOURCE_REF` là `46b2f2ff` và `cfb43fbb`), dựng trong `data/.build/` (gitignored). Sau đó chỉ thay các thư mục nhãn, `conversion-report.json` và `DISPUTES.md` của `data/dev` và `data/test`; audio và hội thoại mẫu không đụng tới.
  - README của bản sửa gộp vào `data/dev/README.md` và `data/test/README.md` (mới). Notes chuyển sang `notes/dev`, `notes/test`; `SKILL.md` ghi quy ước mới.
  - `ground_truth.json` ghi lại với thụt lề 2 như bộ sinh, nên diff chỉ còn các dòng đổi.
  - Nhóm 24 (chờ duyệt): kết quả trong `tools/` của ADV-0154 là 22:00, `moved_from: null`.
- **Đã kiểm:** so từng byte, `data/dev` giống bản dev-r4 ngoại trừ đúng `tools/` của ADV-0154, `data/test` giống hệt test-r1. Mọi file kịch bản git báo đổi đều có mục trong `conversion-report.json`. 0 lỗi khóa; loader `run_eval` nạp 404/404 và 99/99; oracle qua `reference_eval.py` CCR 100 · RQR 0 · TSR 100 · HR 0. `tests/agent/test_extractor_vocabulary.py`, `test_btc_pack.py`: 30 pass; test của `evaluation/data-generation`: 112 pass.
- **Số đo:** không có (nhãn không đổi so với bản đã kiểm).
- **Còn lại:** nhóm 19–24 chờ duyệt. Các run cũ trong `evaluation/runs/` chấm trên nhãn r3: không so số trực tiếp với run mới.

### 2026-11-09 · Hành động kỳ vọng của agent: dev-r4 và test-r1, nhóm 19–23

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: TSR, HR

- **Vấn đề:** một số `success_if`, tham số và `tools/` của đáp án chuẩn không khớp lời khách hoặc chính sách. Khách hẹn giờ gọi lại mà nhãn không đòi `schedule.callback`. Khách hoãn mà nhãn vẫn đòi tạo đơn. Lời khách mua một món, nhãn ghi món khác. Lịch gọi lại rơi vào ngày nghỉ thì `args_match` chỉ chấp nhận một trong hai cách làm đúng.
- **Bằng chứng:** bộ kiểm hành động không gọi model. Nó đối chiếu `schedule.callback` (ngày, giờ, kết quả `mock_tools.schedule_callback`), `order.create` (sản phẩm được nhắc, số lượng, câu cuối có hoãn không), `order.update` (action và size so với lời khách), `order.status`, `handoff.transfer` (khách đòi người hoặc hỏi y tế). Khoảng 60 mục bị báo, đọc từng câu: phần lớn là báo động giả (câu hỏi y tế chuyển máy đúng luật, khách nhắc nhân viên cũ, "Thứ Hai tuần sau"…). Còn lại 5 lỗi thật, và 1 chỗ chính sách mâu thuẫn với mock BTC.
- **Sửa (chờ duyệt, cờ `ACTION_PROPOSALS_REVIEWED`):**
  - Nhóm 19: GEN-0184/c2 đòi `schedule.callback` 19:00 ngày hôm sau.
  - Nhóm 20: ADV-0123/c1 đổi thành `hen_goi_lai`, không tạo đơn.
  - Nhóm 21: GEN-0197/c2 (dev) và GEN-0015/c2 (test), lời khách đổi sang mua AirPure Mini đúng nhãn.
  - Nhóm 22: 7 cuộc dev và 1 cuộc test, bỏ `args_match.callback_at` khi giờ hẹn rơi vào ngày nghỉ LN-02; giữ giờ đã dời ở `ground_truth_facts` và `must_say_any`.
  - Nhóm 23: ADV-0117/c1, khách tự xưng nhất quán là "anh".
  - Cũng sửa lỗi của chính nhóm 14 (đã duyệt): câu thêm vào dùng cách người gọi tự xưng, không theo `honorific` của kịch bản. Ở các kịch bản hai người chung SĐT, chị Dung từng bị ghi "Phòng cô…".
- **Đã kiểm:** dựng lại hai revision; 0 lỗi khoá; loader `run_eval` nạp 404/404 và 99/99; oracle qua `reference_eval.py` cho CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** chờ duyệt. Ở SCN-ADV-0154/call_1, LN-02 cho gọi 22:00 ngày 11/11 nhưng mock BTC dời về 08:00; cần người duyệt chọn theo chính sách hay theo mock.

### 2026-11-09 · Nhãn có căn cứ trong lời khách: dev-r4 và test-r1, nhóm 14–16

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR

- **Vấn đề:** `facts_established` ghi diện tích, trẻ nhỏ, tuổi bé, ngân sách mà khách không nói ở cuộc nào, seed_history cũng không có. Cuộc sau lại cấm hỏi (RQR) hoặc bắt nhớ (CCR) chính các slot đó: agent hỏi lại vì chưa biết thì bị trừ điểm, còn agent bịa ra số thì được cộng. Ở tập test, 8 cuộc đòi `order.create` mà khách không nói lời đồng ý nào. Ở dev, 2 cuộc ghi `freeship: true` khi không biết nơi giao.
- **Bằng chứng:** bộ kiểm mâu thuẫn không gọi model, chạy trên dev, dev-r4, test, test-r1. Nó đối chiếu nhãn với lời khách, `ground_truth_facts` với `mock_tools.py` của BTC theo ngày cuộc gọi (giá, tồn kho, khuyến mãi), danh tính với CRM, `expected_outcome` với tool, ngày giữa các cuộc.
  - Giá, tồn kho, khuyến mãi, outcome, ngày, thanh toán: không có mâu thuẫn. ADV-0024/0119 trông như sai giá nhưng là RUN-10 `once_per_customer`; các khách không có trong CRM đều là persona ẩn danh hoặc số mới.
  - Facts không nói ở đâu, trên dev-r4: room 29, has_children 29, child_age 41, budget khoảng 105; trên test-r1: 6, 11, 4, 21. Đa số bị cuộc sau dùng tới.
- **Sửa:** nhóm 14 thêm câu khách nói đúng giá trị đã gán, nối vào lượt đầu nên số lượt không đổi. Đây là cách đã duyệt ở nhóm 1 và 3, giữ được phép thử trí nhớ. dev-r4 có 144 cuộc / 196 nhãn, test-r1 có 27 cuộc / 37 nhãn; danh sách đọc lại từng cuộc. Nhóm 15 (test-r1) thêm lượt đồng ý cho 8 cuộc tạo đơn. Nhóm 16 (dev-r4) bỏ `freeship` ở 2 cuộc. Người duyệt chấp nhận các nhóm 11b, 14–18 ngày 09/11/2026 (cờ `NEW_PROPOSALS_REVIEWED` trong `build_dev_r4.py`; dựng lại, 2.582 và 612 file nhãn không đổi byte nào).
- **Đã kiểm:** dựng lại cả hai revision; 0 lỗi khoá. Oracle qua `reference_eval.py`: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 lỗi schema. Kiểm lại thì không còn fact nào khách không nói (8 mục còn lại đều đã đọc, khách nói bằng chữ như "một tháng", "một triệu"); 0 cuộc tạo đơn thiếu lời đồng ý.
- **Số đo:** chưa đo trên agent thật.
- **Bổ sung cùng ngày:**
  - Nhóm 11b (dev-r4): đọc 432 nhãn `blocker` của ASR, gồm những câu có từ gợi ý. Bỏ 8 nhãn (câu không nêu lý do, xin chuyển máy, lý do đã xong như "đã hỏi vợ và quyết định mua rồi"). Đổi 4 nhãn chê giá mà không so với nơi khác sang `vuot ngan sach`.
  - Nhóm 17: theo quy tắc người duyệt đưa ra, khách ẩn danh không đọc SĐT thì cuộc sau không nối được với cuộc đầu, nên chỉ giữ slot khách nói lại. Áp cho ADV-0050/0093/0145 call_2; nếu khách đọc số thì phải lưu và giữ ngữ cảnh.
  - Nhóm 18: bỏ `owned_sku` khỏi `must_carry_over` ở ADV-0045/c1, vì `seed_history` chỉ là thông tin tham khảo.
  - Size và `return_days` của ASR test-r1: đọc 35 nhãn, đều đúng.
  - Dựng lại: 0 lỗi khoá, oracle CCR 100 · RQR 0 · TSR 100 · HR 0.
- **Còn lại:** audio của các lượt có lời mới chưa sinh lại (người duyệt sẽ sinh khi dữ liệu ổn).

### 2026-11-08 · data/test-r1: sửa nhãn tập test theo các nhóm của dev-r4

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR, entity_accuracy (ASR)

- **Vấn đề:** `data/test` mang lại các lỗi nhãn đã sửa ở dev-r4, vì nó được sinh lại từ 99 kịch bản đầu của `data/dev` (cùng mã, khách, persona và kế hoạch cuộc gọi; chỉ lời khách khác). Đây cũng là lý do tập này không độc lập với dev.
- **Bằng chứng:**
  - Chạy kiểm không gọi model trên dev, dev-r4 và test: khoá theo `scenario-keys.yaml`, loader `run_eval`, oracle qua `reference_eval.py` của BTC, schema, độ khớp giữa các thư mục.
  - So mã: 99/99 mã của test có trong dev, cùng số điện thoại, 0 kịch bản trùng nội dung.
  - Đo từng nhóm của dev-r4 thành quy tắc trên dev: nhóm 5 khớp 22/22, nhóm 9 khớp 130/130. Các nhóm còn lại không tái tạo được danh sách đã duyệt (G1 độ chính xác 0,68, G3 0,79, G7 và G8 không dùng được), nên phải đọc câu.
  - Cũng trong lần kiểm này, phát hiện nhóm 7 của dev-r4 để lại `facts_established: {}` ở 5 cuộc. Đã sửa trong `build_dev_r4.py`, dựng lại; đúng 5 file đổi, oracle không đổi.
- **Sửa:** revision mới `data/test-r1`, dựng bằng `evaluation/datasets/ground-truth-review/build_test_r1.py` (dùng lại các hàm của `build_dev_r4.py`); `data/test` không đổi.
  - 43 thay đổi theo quy tắc đã duyệt: nhóm 5 có 5, nhóm 9 có 31, phần định dạng của 11 có 6, nhóm 12 có 1.
  - 83 thay đổi Claude đề xuất sau khi đọc câu: nhóm 1, 2, 3, 4, 7, 8, 10 và phần nghĩa của 11. Người duyệt chấp nhận cả bảng cùng ngày (`proposed_by: claude`, `reviewed_on: 2026-11-08`; cờ `CLAUDE_PROPOSALS_REVIEWED` trong script). Chi tiết ở `DISPUTES.md`.
  - `data/test-r*/` thêm vào `.gitignore` như `data/dev-r*/`. README và DISPUTES của cả hai revision chuyển vào `evaluation/datasets/ground-truth-review/notes/`; script chép nguyên byte khi dựng.
  - 21 cuộc có `budget_vnd` mà khách không nói ngân sách: để lại cho người duyệt.
- **Đã kiểm:** 99/99 kịch bản nạp được bằng loader của `run_eval`; 0 lỗi khoá. Oracle trên test-r1: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 vi phạm, 0 lỗi schema.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** 21 cuộc `budget_vnd` khách không nói chờ người duyệt chọn cách sửa; audio của các lượt khách đã đổi chưa sinh lại; `size_old`/`return_days` của ASR ở test chưa đọc. Muốn có tập test độc lập thì phải sinh tập mới với mã và khách riêng.

### 2026-11-08 · data/dev-r4: sửa nhãn theo bản tổng hợp 08/11/2026

Loại: dữ liệu · Trạng thái: đang đo · Chỉ số: CCR, RQR, TSR, HR, entity_accuracy (ASR)

- **Vấn đề:** nhãn của `data/dev` mâu thuẫn với lời khách, với dữ liệu BTC hoặc với chính bộ dữ liệu, nên agent làm đúng vẫn bị chấm trượt. Ví dụ: cuộc chat không nối được với cuộc sau; đòi nhớ `owned_sku` của món không liên quan; đơn vượt hạn mức COD mà khách chưa đồng ý chuyển khoản; `promo_active: true` khi chỉ có freeship.
- **Bằng chứng:** bản tổng hợp nhãn của người làm tập dev (08/11/2026). Mình tính lại từng nhóm trên `data/dev` và pack BTC (`promotions.json`, `crm_seed.json`, `inventory_timeline.json`), vì các file bằng chứng mà bản tổng hợp dẫn tới không có trên máy. Khi đọc lại nhãn ASR, mình thấy 22 nhãn `promo_expiry` thật ra là ngày hẹn gọi lại.
- **Sửa:** revision mới `data/dev-r4`, dựng bằng `evaluation/datasets/ground-truth-review/build_dev_r4.py`; `data/dev` không đổi. 515 dòng thay đổi (tính cả bản ASR của lời khách) được người duyệt chấp nhận (nhóm 1, 2, 3, 4 cho ADV-0028, 5, 8, 9, 10, phần định dạng của 11). 124 thay đổi do Claude đề xuất (ADV-0023, hotline nhóm 7, `blocker`/tiền/`promo_expiry`/`phone`/`restock_date` của ASR, tag nguồn), người duyệt chấp nhận cả bảng cùng ngày. Trong `conversion-report.json`, các mục này có `decision: revise`, `proposed_by: claude`, `reviewed_on: 2026-11-08`; cờ `CLAUDE_PROPOSALS_REVIEWED` trong script đưa chúng về `pending` nếu cần. Phần giữ nguyên và chưa làm ghi trong `DISPUTES.md`.
- **Đã kiểm:** 404/404 kịch bản nạp được; độ dài `customer_turns_asr` khớp. Oracle trên r4: CCR 100 · RQR 0 · TSR 100 · HR 0, 0 vi phạm, 0 lỗi schema. Khi chuyển 124 đề xuất sang đã duyệt: dựng lại bằng `--force`, 2.582 file nhãn giống hệt từng byte, và 640 thay đổi trong report giữ nguyên nội dung, chỉ đổi trạng thái.
- **Số đo:** chưa đo trên agent thật.
- **Còn lại:** audio của các lượt khách đã đổi (nhóm 1, 3, 10) chưa được sinh lại; hội thoại mẫu J02 và max_agent_questions chưa sinh lại (cần model); nhãn `blocker` có từ gợi ý chưa đọc; `official_gt_approved` vẫn false.

### 2026-11-08 · Chỉ đọc lại đơn khi đủ thông tin, và "đồng ý" kèm từ đệm vẫn tạo được đơn

Loại: hard guard, prompt · Trạng thái: đang đo · Chỉ số: TSR

- **Vấn đề:** 23 cuộc trong `eval2` trượt TSR vì không có `order.create` nào (`success_if` chờ `order.create` khớp `args_match`). Khi trả lời câu agent đọc lại đơn, khách thường đưa thông tin còn thiếu chứ không nói "đồng ý", nên câu đọc lại bị phí. Còn khi khách đã đồng ý thì đơn vẫn không được tạo.
- **Bằng chứng:** `evaluation/runs/eval2-full-relabel-3`. Trong 23 cuộc, 19 có `pricing.get_quote` lỗi `BAD_ENVELOPE` vì tham số `payment` (đã sửa ở mục "Tham số thừa…", sau khi chạy run này); 13 cuộc đọc lại đơn ở lượt cuối nên không còn lượt để khách xác nhận. Trên toàn run có 153 câu trả lời ngay sau câu đọc lại đơn: 116 không phải lời đồng ý (phần lớn là địa chỉ hoặc cách thanh toán, ví dụ SCN-ADV-0018 call_2 lượt 3 "Giao hàng cho chị ở Thủ Đức"); 35 được `purchase.answer()` (qua `agrees()`) nhận là đồng ý nhưng không có đơn, trong khi `purchase.matches()` đòi `YES.fullmatch`; chỉ 2 tạo được đơn. `agrees()` còn từ chối "Ừ, vậy em lên đơn cho anh luôn đi." (SCN-GEN-0232) và "Chị đồng ý lên đơn rồi, em làm cho chị nhé." (SCN-GEN-0240). Mẫu BTC: cả 5 cuộc chấm `order.create` đều để khách nói "lên đơn" ở lượt cuối.
- **Sửa:** (1) `ActionGuardMiddleware` trả `ORDER_INCOMPLETE`, kèm phần còn thiếu và không phát hành bản nháp, khi đơn thiếu thanh toán do model truyền, thiếu địa chỉ (lấy từ lời khách hoặc bộ nhớ qua `order_arguments`) hoặc thiếu ngày giao từ `delivery.estimate` (`purchase.missing`, `purchase.estimated_delivery`). Câu đọc lại có thêm "giao dự kiến ngày …" (PB-09). Rule 12 trong `rule_packs.yaml` bỏ "thiếu địa chỉ hay thanh toán không phải lý do chờ / tự đặt COD": giờ chỉ hỏi phần còn thiếu, và gọi `order_create` ngay khi khách vừa đưa thông tin cuối cùng, để câu "chốt đơn" kế tiếp là lời xác nhận. (2) `purchase.matches()` dùng `agrees()`, cùng quy tắc với `answer()`; các điều kiện khác giữ nguyên: đúng câu đọc lại ở lượt trước, cùng nội dung đơn, còn trong 300 giây, có biên nhận HMAC. (3) `COURTESY` thêm "vậy", "làm"; câu có "nhưng", "đổi", "thêm", "chuyển khoản" vẫn không được tính là đồng ý.
- **Đã kiểm:** thêm 12 test trong `tests/agent/test_ec03_confirmation_isolation.py` (đơn thiếu từng trường; câu đọc lại có ngày giao; 4 câu đồng ý kèm từ đệm tạo được đơn; 4 câu có ý đổi đơn bị từ chối). Fixture được cập nhật cho đơn đủ thông tin. Kế hoạch mua sai trên kênh khác giờ dừng ở `ORDER_INCOMPLETE`, không còn tạo bản nháp. `tests/agent`: 1.285 passed; 11 failed và 14 errors đều nằm ở ASR và voice (`test_asr_*`, `test_voice_transport`), các file không bị đổi trong mục này.
- **Số đo:** chưa đo.
- **Quay lui một phần (merge `origin/main`, commit `1fac83c9`):** bỏ phần (1) `ORDER_INCOMPLETE`, vì skill đặt hàng của `main` cố ý cho tạo đơn khi chưa có địa chỉ (hỏi sau) và mặc định COD. Giữ lại ngày giao dự kiến trong câu đọc lại, phần (2) và phần (3). Đã bỏ các test đơn thiếu từng trường; giữ 3 test về ngày giao và câu đồng ý.
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
