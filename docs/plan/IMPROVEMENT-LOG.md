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
