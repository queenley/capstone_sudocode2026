# Chờ người dùng: agent thật và dịch vụ ngoài

Cập nhật 01/11/2026: người dùng đã giao hai luồng xóa Memory trong evaluation và popup chào khách quay lại. Đã chạy smoke thật `SCN-GEN-0037` trước/sau sửa, kiểm PostgreSQL erasure và browser popup; xem `../evaluation/memory-erasure-verification.md` và `../frontend/returning-customer-popup.md`. Phạm vi này đã được kiểm, không coi lại là chưa từng chạy. SLA 72 giờ, worker/outbox production, backup/export và các cohort agent khác vẫn nằm ngoài kết luận của smoke này.

Các mục bên dưới cần phạm vi được người dùng cho phép. Yêu cầu mới ngày 01/11/2026 đã cho phép khóa cohort và gọi model nếu điều kiện/ngân sách hiện có cho phép để đối chiếu extractor; theo RUN-LEDGER.md, một smoke trước cohort. Các mục agent/provider ngoài phạm vi này vẫn chờ yêu cầu riêng. Ngoại lệ đã được người dùng ủy quyền ngày 01/11/2026: tải và chạy ASR local Zipformer 30M, PhoWhisper-small và VieGem trên audio có sẵn, không API trả phí. Đã mở rộng phạm vi sang web voice, WER/CER và entity diagnostic; xem `../evaluation/asr-local.md`.

## Nguồn đánh giá và ngân sách

- Theo xác nhận mới nhất của người dùng: giữ test, scenario, harness và `reference_eval.py` của main, mốc đồng bộ `41eda490bc47577018541c7778c0e8443ed8e6c8`. Không khôi phục ZIP BTC; không sửa tiếp bộ dữ liệu hoặc công thức chấm.
- Dataset nghiệp vụ và nhãn/lexicon nền vẫn do người khác phụ trách. Bộ ASR hard-test đã được xóa theo yêu cầu mới; không tự sửa ground truth hoặc pack BTC.
- Trước mọi lần gọi model: đặt `EVAL_BUDGET_DB` trỏ vào ledger hiện có `evaluation/runs/20261024-work/budget.sqlite`, kiểm tra phần ngân sách còn lại, không tạo lại ledger để vượt cap.
- Chạy một scenario trước cohort. Trace, hội thoại, audio, khóa và dữ liệu khách không được commit.
- Khi đổi extractor: ghi phiên bản; dùng `--relabel` trên cùng transcript để so dụng cụ đo.

## 1. Hành vi agent thật

Chuẩn bị PostgreSQL riêng cho evaluation, provider key, cấu hình model và một scenario đã được duyệt. Khóa commit/snapshot của mã sau gia cố trước khi thu số; mốc main bên trên chỉ là nguồn nền, chưa phải commit của toàn bộ thay đổi local. Ví dụ smoke trên mẫu phát triển có sẵn:

```sh
export EVAL_BUDGET_DB="$PWD/evaluation/runs/20261024-work/budget.sqlite"
apps/ai-agent-service/.venv/bin/python run_eval.py --scenarios apps/ai-agent-service/data/btc/test_set/public_sample --only SAMPLE-01 --out evaluation/runs/manual-smoke
```

Kiểm tra câu mở đầu tiếp nối, không hỏi lại, giá/KM theo ngày, tạo/sửa đơn đúng đối tượng, tool lỗi/timeout, số dùng chung, đổi kênh, hẹn gọi và bàn giao. Đặc biệt kiểm tra tác động của việc giữ fact chưa xác nhận ở trạng thái cách ly.

Bằng chứng: trace, diagnostics, errors, manifest, usage. Không kết luận PASS khi thiếu nhãn hoặc lượt bị lỗi.

## 2. Full/baseline và extractor

Sau smoke đạt, dùng cùng cohort đã duyệt, cùng model/tham số/tool/KB; chỉ khác đọc memory. Giữ holdout độc lập, không dùng để tạo FAQ/playbook.

Mục tiêu của đề: TSR ≥70%; RQR giảm tương đối ≥40%; HR giá/KM ≤5%. Báo CCR, TSR ca khó, guardrail và mẫu số. Phân tích ít nhất 10 lỗi; không lấy số của commit cũ làm số của bản mới.

## 3. Rubric judge và người duyệt

`run_eval.py --judge` là tùy chọn có thêm phí model, ghi sidecar `<config>.judge.jsonl`; không sửa điểm của reference_eval. Judge dùng cấu hình model extractor, với vai trò `rubric_judge` riêng.

Chỉ bật sau khi xác nhận ngân sách. Đối chiếu ≥20 cặp (call, criterion), báo agreement và Cohen's kappa; kappa <0.6 phải phân tích lại. Thiếu criterion, evidence không có trong transcript hoặc provider lỗi là INCOMPLETE.

## 4. Cải tiến R0/R1/R2

Khóa tập học/tập kiểm/holdout, model, extractor và code nền. Thu feedback trên tập học, duyệt proposal, đo trên cùng tập kiểm ở ba vòng. Tách đóng góp Reflection và Gap Loop; minh chứng một thay đổi gây hại và rollback.

Knowledge gap tạo `regression-proposals/` ở thư mục improvement local. Đây là đề xuất chờ người duyệt, không phải scenario hay nhãn đã được phê duyệt. Publish KB yêu cầu người duyệt; nạp lại dịch vụ trợ lý để áp dụng phiên bản mới.

## 5. Simulator, voice và hiệu năng có model

- Simulator: 5 scenario ×3 seed; báo trung bình/độ lệch và biên độ TSR ≤10 điểm.
- Đo ≥100 lượt sau warm-up, cùng phần cứng/provider/model cho hai cấu hình.
- M1: TTFT p95 ≤3s, total p95 ≤8s, Call Brief ≤5s.
- M2: TTFA p95 ≤2.5s, Call Brief ≤3s, ≥2 phiên đồng thời.
- Kiểm tra barge-in, mạng chậm/ngắt, quyền micro, giải phóng thiết bị, hàng đợi âm thanh và kích thước frame. Test giao thức giả không chứng minh chất lượng giọng nói hay các ngưỡng trên.

## 6. Kênh ngoài và deployment

Chỉ kết nối Zalo/hotline/provider hoặc triển khai khi người dùng yêu cầu. Kiểm tra HTTPS, webhook signature/replay, secret production, runtime nhiều replica và smoke từ máy khách.

Xác minh xóa dữ liệu xuyên kênh với tài khoản tổng hợp, receipt chuyển từ pending sang deleted chỉ sau agent acknowledgement; worker phải tiếp tục retry khi agent bận hoặc mất kết nối. Kiểm tra các hệ thống log/backup ngoài repo theo chính sách vận hành trước khi nhận dữ liệu khách thật.

E2E gọi agent thật hiện cần bật rõ `RUN_LIVE_AGENT=1`; không bật trong bộ test mặc định.

## Lệnh và điều kiện chạy từng lượt

Các lệnh dưới đây **chưa được chạy**. Dùng biến `SCENARIOS` trỏ tới revision đã duyệt, `SCENARIO_ID` là một ca smoke của revision đó, `RUN_DIR` là thư mục bằng chứng mới. Đặt `PYTHONPATH=apps/ai-agent-service/src:packages/backend-common:.` cho các module improve.

| Mục | Lệnh khởi đầu sau khi bạn yêu cầu | Ngân sách và tiêu chuẩn nghiệm thu |
|---|---|---|
| Continuity/order/identity/memory/delete/handoff | `python run_eval.py --scenarios "$SCENARIOS" --only "$SCENARIO_ID" --out evaluation/runs/manual-smoke` | Dùng ledger hiện có; một scenario trước. Thu trace/tool state/diagnostics; đúng quyền, không tạo trùng, không khẳng định thao tác khi thiếu evidence. |
| Full/baseline | `python run_eval.py --scenarios "$SCENARIOS" --out evaluation/runs/manual-cohort` | Chỉ sau smoke và còn cap. Không `--config` để chạy cả hai; giữ manifest cùng extractor_version, báo mẫu số và mục tiêu ở mục 2. |
| Extractor/J01–J12 | `python run_eval.py --relabel "$RUN_DIR" --out evaluation/runs/manual-relabel`; thêm `--judge` vào lệnh smoke riêng | Relabel/judge đều có phí, không chạy khi cap không đủ. Rubric sidecar tách khỏi điểm main; ≥20 mẫu đối chiếu người, thiếu evidence là INCOMPLETE. |
| R0/R1/R2 và Reflection | `python -m ai_agent_service.pipeline.improve harvest --run "$RUN_DIR" --scenarios "$SCENARIOS" --round R1`; `python -m ai_agent_service.pipeline.improve explore --round R1 --limit 1`; `python -m ai_agent_service.pipeline.improve propose --round R1` | Chỉ học từ learning set; frozen set/holdout đã khóa. Explore/propose có phí; giới hạn một lỗi trước. Chưa tự publish nội dung model. Đo lại từng vòng bằng run_eval, phân tích contribution/ablation trước khi kết luận. |
| Publish/rollback có duyệt | `python -m ai_agent_service.pipeline.improve publish --review "$REVIEW_FILE"`; `python -m ai_agent_service.pipeline.improve rollback --to "$PREVIOUS_VERSION" --reviewer "$REVIEWER" --reason "$REASON"` | Bản thân thao tác file không có phí model; replay sau đó có phí. Review artifact phải chỉ rõ người duyệt, nguồn và version. Restart rồi đọc lại, không sửa phiên bản cũ. |
| Simulator nhiều seed | `python -m ai_agent_service.pipeline.improve measure --label manual-smoke --scenarios "$SCENARIOS" --only "$SCENARIO_ID" --seeds 1` | Có phí agent và simulator. Một seed/ca trước, rồi cohort 5 ca ×3 seed; giữ persona, seed, cấu hình và logs; báo biến thiên như mục 5. |
| Voice/load | Chạy stack đã cấu hình rồi mở trang khách để gọi; `RUN_LIVE_AGENT=1 npm run test:e2e -- e2e/buyer.spec.ts` trong apps/web cho smoke agent | Voice/browser E2E này có phí và có thể tạo order tổng hợp. Chỉ dùng tài khoản thử riêng. Chưa có CLI đo tải voice hoàn chỉnh; cần chốt thiết bị, kịch bản và rate trước lượt này. Thu ≥100 lượt, barge-in, TTFA và ≥2 cuộc đồng thời. |
| Kênh/deploy | `python scripts/dev/zalo_simulator.py --user 9000000001 "Xin tư vấn sản phẩm"`; `curl -fsS "$DEPLOYMENT_URL/health/ready"` | Zalo simulator có thể gọi model và gửi ra kênh nếu có access token. Chỉ dùng sandbox được bạn chỉ định; ngân sách model và chi phí provider/hạ tầng phải được chốt. Thu signature/replay, receipt xóa xuyên kênh, restart/replica, readiness và rollback deployment. |

Ngân sách: không ấn định hoặc tăng thêm tiền trong đợt này. Mỗi mục dùng phần còn lại của ledger đã có và mức bạn chấp thuận ở lượt chạy. Ledger hiện chỉ hỗ trợ pricing `openai:gpt-4.1-mini`; model khác phải được xác minh pricing và hỗ trợ cap trước, không bỏ ledger để chạy. Reservation chưa quyết toán phải giữ nguyên và vẫn tính vào ngân sách; chỉ được dispatch nếu phần khả dụng còn đủ reservation tối đa cho request. Nếu cap không đủ, dừng; không xóa pending, settle phỏng đoán hoặc tạo lại ledger. Với lượt được yêu cầu hiện tại, không ấn định thêm ngân sách ngoài cap sẵn có.

Không thể suy ra điểm BTC của agent hay năng lực chịu tải production từ kết quả offline. Số ASR local chỉ áp dụng cho audio/model/decoder được ghi trong manifest; không suy rộng tuyển tập y tế thành chất lượng telesales hoặc toàn bộ tiếng Việt.

## ASR: còn chờ bạn

Zipformer 30M greedy là mặc định. Audio/nhãn/kết quả hard-test cũ đã xóa theo yêu cầu; xem ASR-DATA-CLEANUP.md. Giữ code và weights để dùng với bộ audio/reference được cung cấp sau này.

- Kiểm tra mic/loa thật, capture profile, barge-in và nhiều câu liên tiếp với agent/TTS thật; cần lượt được yêu cầu và ngân sách riêng.
- Cung cấp cohort commerce/audio/entity gold đã duyệt khi muốn đo chất lượng tiếp. Không lấy dữ liệu đã xóa hoặc số đo lịch sử làm bằng chứng cho code mới.
- GPU, tải nhiều phiên, native streaming và triển khai ngoài máy chưa được xác minh trong lượt này.
