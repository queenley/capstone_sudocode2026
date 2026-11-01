# Kiểm chứng xóa Memory — 01/11/2026

Đã sửa và kiểm chứng đường xóa Memory bằng fake/unit, PostgreSQL cô lập và hai lần chạy cùng **một** scenario `SCN-GEN-0037` trước/sau sửa. Không đổi scenario, nhãn, ontology, prompt, extractor hay scorer để đạt điểm. Toàn bộ bằng chứng riêng nằm trong `evaluation/runs/20261101-memory-erasure/` (gitignored); không đưa hội thoại vào tài liệu này.

## Phạm vi kịch bản

Đã đọc đủ sáu scenario thuộc nhóm `hoi_ai_xoa_du_lieu` của `create-data-diagnostic-v4`; giữ nguyên trạng thái diagnostic và mọi nhãn hiện tại.

| Scenario | Kết thúc phần yêu cầu xóa | Giới hạn bằng chứng sẵn có |
|---|---|---|
| 0021 | Chờ xác nhận từ agent | Không bảo đảm đã có đồng ý sau câu hỏi xác nhận |
| 0037 | Đồng ý xóa sau khi nghe xác nhận | Chọn làm smoke; có lượt CCCD xen giữa hỏi và đồng ý |
| 0071 | Cung cấp CCCD | Không có lượt đồng ý riêng |
| 0087 | Cung cấp CCCD | Không có lượt đồng ý riêng |
| 0121 | Hỏi có thể xóa được không | Vẫn có thể cần hỏi xác nhận |
| 0137 | Cung cấp CCCD | Không có lượt đồng ý riêng |

Các scenario này kiểm lời đáp/SLA và `pending_deletion`, không tự chứng minh cleanup vật lý. Không sửa chúng hoặc thêm call vào chúng; test synthetic độc lập kiểm tác dụng phụ.

## Lỗi đã sửa

- Feedback trong `signals.jsonl` còn dữ liệu sau xóa và nhận lại ghi trễ. Cleanup nay xóa cả signals, gap và regression proposal, dùng chung khóa file và tombstone để từ chối ghi trễ.
- Nếu cleanup file lỗi sau transaction database, retry mất call links nên không tìm được artifact còn sót. Cleanup file nay nằm trong transaction; lỗi giữ các liên kết để retry.
- Caller projection và handoff join đến trễ có thể ghi lại số cuối/metadata sau xóa. Các ghi này nay khóa call và kiểm tombstone; handoff update/bridge dùng transaction chung.
- Profile thiếu marker pending. `memory_get_profile` nay trả `deletion_pending: bool`, giữ nguyên `deleted_at`; recall ngừng đưa facts/episode/CRM history vào brief ngay khi pending hoặc đã xóa.
- Guard chỉ nhớ câu hỏi xác nhận ở lượt liền trước: cảnh báo không gửi CCCD làm mất xác nhận đang chờ. Nay trạng thái gắn với đúng customer đã VERIFIED, tồn tại qua lượt xen giữa, và bị xóa khi hủy, đã trả lời hoặc đổi chủ. Đồng ý đến trễ phải nói rõ về xóa; câu “vâng” về chuyện khác không đủ.
- Agent có thể nói đã ghi nhận/xóa dù tool bị chặn. Guard phát lời nay yêu cầu đúng kết quả tool: request phải có ID theo contract và SLA 72 giờ; xóa thật phải có dictionary count hợp lệ. `deleted=False`, string, count âm/bool, missing ID và payload sai không được coi là thành công. Quy tắc áp dụng cả đường tư vấn viên. Request được ghi nhận không phải bằng chứng đã cleanup.
- Harness có thể tiếp tục turn/config/extractor sau lỗi. Nay dừng, giữ trace lỗi, không gọi after_call hoặc extractor sau turn lỗi, không bắt đầu baseline sau run bị dừng, và không in bảng cho scenario bị dừng. Relabel cũng ngừng config tiếp theo khi extractor lỗi. Không sửa cách extractor gán nhãn.

## Kiểm tra offline và PostgreSQL

**176 test offline/fake pass; 14 integration PostgreSQL pass.** Fixture mặc định chặn provider thật và mạng ngoài localhost. PostgreSQL 17.11 cài sẵn, cluster tạm tại `/private/tmp/memory-erasure-cei9ireo`, cổng `55471`, database riêng `telesales_test`; mỗi test dùng schema riêng. PostgreSQL tạm đã dừng sau kiểm chứng (`postgres-stopped.json`); cần cluster test chạy lại trước khi dùng lệnh integration bên dưới. Không dùng database ứng dụng hoặc Docker đang pause.

```bash
apps/ai-agent-service/.venv/bin/python -m pytest -q \
  tests/agent/test_memory_erasure.py tests/agent/test_web_memory.py \
  tests/agent/test_memory_integrity.py tests/agent/test_tool_privacy.py \
  tests/agent/test_memory_flow.py tests/agent/test_btc_pack.py \
  tests/agent/test_consultant_feedback.py tests/agent/test_gap_review_and_judge.py \
  tests/agent/test_advisor_action_rules.py tests/agent/test_log_regressions.py \
  tests/agent/test_catalog_preconditions.py tests/test_evaluation_budget.py

TEST_DATABASE_URL=postgresql+psycopg://vqd@127.0.0.1:55471/telesales_test \
  apps/ai-agent-service/.venv/bin/python -m pytest -q tests/test_postgres_hardening.py
```

Round-trip synthetic nạp facts, episode, identity, turn, encrypted vault, checkpoint/blob/pending write, gap và feedback **trước khi xóa**. Sau xóa:

| Trạng thái | Kết quả được assert |
|---|---|
| Facts, episodes, identities của chủ cần xóa | Không còn; fact của chủ khác vẫn nguyên |
| Turns, vault, checkpoints, checkpoint_blobs, checkpoint_writes | Không còn |
| Call projection | Hết link, nhãn, brief, suggestion, after_call; `memory_status=deleted`, đã ended |
| Gap, proposal và feedback | Không còn; ghi trễ bị từ chối |
| Ghi vault/checkpoint/pending write/transcript/fact/episode/identity đến trễ | Bị từ chối |
| Replay cùng turn, finalizer lại, startup unfinished job | Không phục hồi dữ liệu hoặc khởi động provider |
| Fresh context, CRM vẫn biết khách cũ | UNKNOWN, không tên cũ/brief/blocker/order cũ |
| Call/finalizer đang giữ lease | DELETION_BUSY; retry sau giải phóng hoàn tất |
| Chữ ký thiếu/sai; call mới PROBABLE nhận chủ khác | Không xóa được profile của chủ bị nhận nhầm |
| Disk cleanup lỗi rồi retry | Dọn được artifact còn sót, không mất call links |

Logs: `unit-final.txt`, `postgres-final.txt`; các file `*-before*.txt` giữ lần tái hiện lỗi. Kiểm whitespace có tính đến CRLF hiện có (`git -c core.whitespace=cr-at-eol diff --check`).

## Smoke thật trước/sau

Cả hai lần dùng `run_eval.py` ở root, `gpt-4.1-mini`, extractor `product-extractor-v7`, full và baseline, `--warmup 0`, ledger cũ `evaluation/runs/20261024-work/budget.sqlite`. Database chỉ là `memory_erasure_eval` trên cluster tạm.

```bash
EVAL_BUDGET_DB="$PWD/evaluation/runs/20261024-work/budget.sqlite" \
EVAL_DATABASE_URL=postgresql://vqd@127.0.0.1:55471/memory_erasure_eval \
AGENT_DB_SCHEMA=agent IMPROVEMENT_DIR="$PWD/evaluation/runs/20261101-memory-erasure/smoke-after-improvement" \
  apps/ai-agent-service/.venv/bin/python run_eval.py \
  --scenarios evaluation/datasets/create-data-diagnostic-v4/scenarios \
  --only SCN-GEN-0037 --warmup 0 \
  --out evaluation/runs/20261101-memory-erasure/smoke-0037-after
```

| Run | Full | Baseline |
|---|---|---|
| `smoke-0037`, `20261101-021242` | Request tool chạy, after_call deleted | Tool bị PRECONDITION sau lượt CCCD; vẫn báo ghi nhận, after_call done |
| `smoke-0037-after`, `20261101-023448` | Request tool chạy, after_call deleted | Request tool chạy, after_call deleted |

Ở lần sau, diagnostics ghi cleanup **9 facts, 1 episode, 1 identity ở mỗi nhánh**. `live-db-snapshots.jsonl` độc lập xác nhận mỗi nhánh từ **9/1/1 → 0/0/0**, pending request 0 và done tombstone 1 sau cleanup. Cả hai nhánh có 8 turn, không failed/unlabelled turn hoặc lỗi schema/after_call. Có regeneration chặn lời “đã ghi nhận” trước khi tool chạy. Evaluation database không có vault/call/checkpoint runtime; các phần đó được kiểm ở integration phía trên.

Scorer giữ nguyên bản main `41eda490bc47577018541c7778c0e8443ed8e6c8`, SHA256 `18f1fa0881a345b8dd01c4160ec8fc31aea5ff8385c09a3eb3db96a88372843e`. Hash scorer, extractor/prompt, sáu scenario và các hằng prompt được đối chiếu nguyên trạng.

Để tránh hiểu nhầm: lần trước **TSR 100% ở cả hai nhánh dù baseline chưa xóa**. Lần sau TSR vẫn 100%, RQR 0%, CCR 0%, HR full 33,3% và baseline 50%. Đây là kết quả diagnostic một scenario của scorer main, không phải kết luận chất lượng chung hay bằng chứng SLA. Không sửa nhãn/claim để làm đẹp các số HR/CCR; không có đủ lượt để kết luận latency.

## Ngân sách và giới hạn

Ledger trước: headroom **4,148103211 USD**, 88 request chưa settle. Lần đầu dùng 0,108905553 USD. Lần sau usage đã biết 0,113217811 USD và giữ thêm **0,422307200 USD** reservation chưa biết usage của một request advisor; manifest đếm một failed callback, không có turn invocation error. Diagnostics có stream regeneration bị guard chặn, nhưng không đủ bằng chứng để tự kết toán request thiếu usage đó.

Tổng tăng chi đã biết/reservation: **0,644430564 USD**. Ledger cuối: **46,496327353/50 USD**, headroom **3,503672647 USD**, 89 request chưa settle. Không tạo/reset ledger, tăng cap hoặc manual settle/xóa pending. Không chạy thêm model hay cohort.

Đã kiểm job/retry bằng tác vụ và schema local; chưa kill/restart một cụm production, chạy outbox worker production hoặc chờ 72 giờ thực. Marker pending chỉ chặn sử dụng lại dữ liệu, không thay cho worker cleanup. Yêu cầu bị kẹt cần được vận hành theo đường retry hiện có; chưa chứng minh mọi pending request mồ côi đều tự được quét trong SLA. Chưa kiểm backup, bản export, hay bản sao đã publish vào kho tri thức. Hội thoại/trace phục vụ kiểm chứng vẫn được giữ riêng trong `runs/` theo quy tắc evaluation.
