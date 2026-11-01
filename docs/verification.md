# Nghiệm thu gia cố backend/frontend

Mốc main: `41eda490bc47577018541c7778c0e8443ed8e6c8`. Đợt này giữ test, scenario, harness và scorer tại main làm nền; thêm regression test và sửa caller/contract cùng implementation. Không khôi phục ZIP BTC, sửa nhãn hoặc thay dữ liệu/tiếng Việt.

`reference_eval.py` không đổi so với main, SHA-256: `18f1fa0881a345b8dd01c4160ec8fc31aea5ff8385c09a3eb3db96a88372843e`. Pack BTC không có diff; test ghim hash vẫn nằm trong suite. Extractor được nâng riêng lên v7 trong lượt bổ sung dưới đây; không thay công thức main. Manifest evaluation có checksum scorer. Rubric judge tùy chọn ghi sidecar riêng, không thay kết quả scorer.

## Bổ sung 01/11/2026 — xóa Memory và popup khách quay lại

- Suite tổng hợp sau hai luồng: `apps/ai-agent-service/.venv/bin/python -m pytest -q` — **629 passed, 15 skipped**. Lượt tổng hợp không bật PostgreSQL/Redis; 15 integration skips không được tính là đạt. Luồng erasure đã kiểm riêng **14 test PostgreSQL pass** trên cluster tạm, rồi dừng cluster; không unpause Docker.
- Smoke agent thật `SCN-GEN-0037` trước/sau sửa dùng root `run_eval.py`, ledger hiện có và cùng extractor v7. Sau sửa, full và baseline đều ghi nhận đúng yêu cầu xóa và cleanup **9 facts / 1 episode / 1 identity → 0/0/0**. Main từng trả TSR 100% ngay cả khi baseline trước sửa chưa cleanup; vì vậy kiểm trạng thái thật được ghi độc lập, không sửa scorer/GT để tăng điểm. Xem [kiểm chứng Memory erasure](evaluation/memory-erasure-verification.md).
- Đã sửa xác nhận xóa bị gián đoạn, báo thành công khi tool chưa thành công, payload tool sai schema, feedback/metadata ghi trễ và retry cleanup mất liên kết. Marker `deletion_pending` chặn recall và popup trước cleanup hoàn tất; tombstone chặn ghi phục hồi.
- Popup dùng endpoint authenticated `/api/agent/welcome`, tên tài khoản và blocker hợp lệ từ agent Memory; không tự tạo call/gửi tin. Kiểm ownership, TTL/provenance, outcome mới, timezone/NaN, phản hồi cũ, logout/đổi tài khoản/xóa và nội dung dài. Root đã xem ảnh desktop/mobile/320px; header giữ nút đóng ngoài vùng cuộn.
- Frontend typecheck, production build và **15 unit tests pass**. Chrome production trước chỉnh header: **31 passed**; bản cuối popup/session + regression cuộn rồi đóng: **15 passed**. Các tập kiểm có phần trùng nhau, không cộng thành 46 ca độc lập. Chi tiết và ảnh ở [popup khách quay lại](frontend/returning-customer-popup.md).
- Giới hạn: smoke là một scenario diagnostic, không phải cohort chất lượng chung. Chưa kiểm SLA 72 giờ hoặc backup/export/worker production. Popup phát hiện thay đổi từ thiết bị khác khi revalidate, tối đa 30 giây khi đang mở; chưa kiểm trình duyệt/thiết bị/screen reader thật ngoài Chrome local. Mọi artifact UI dùng dữ liệu synthetic; không commit/push/deploy.

## Bổ sung 01/11/2026 — ASR mặc định và extractor v7

- Chạy `apps/ai-agent-service/.venv/bin/python -m pytest -q`: **548 passed, 9 skipped**. Không đặt PostgreSQL/Redis TEST URL trong lượt này; 9 test integration bị skip, không tính là đạt. Không gọi provider thật trong pytest; model factory và mạng ngoài bị chặn.
- Các regression trong suite gồm schema/docstring/mô tả trường tiếng Việt, JSON repair từ text/tool args, retry giữ nguyên toàn bộ lỗi, token truncation, không retry lỗi invocation, quote/source/role/history, contract open/confirm và pack BTC. Có test sync/async dùng ChatOpenAI SDK với `httpx.MockTransport` tái hiện invalid output span, kiểm usage callback trước local Pydantic validation và retry thành công.
- Thêm 11 ca phân biệt ngày nhập/bổ sung hàng với ngày giao, nhận, gọi lại và hàng hoàn; `restock_date` phải có bằng chứng đúng chủ thể trong quote. Đổi instrument lên v7, giữ kết quả v6 riêng trong ledger.
- Zipformer 30M int8 greedy là mặc định HTTP/WebSocket, agent config, preload, fetch và evaluation runner. Audio/nhãn/kết quả ASR hard-test đã xóa theo phạm vi người dùng; code, weights, dữ liệu agent, pack BTC và ledger được giữ. Xem [ASR-DATA-CLEANUP.md](plan/ASR-DATA-CLEANUP.md).
- Extractor v7 giữ cách gửi `model_json_schema()` cho provider và validate tại helper, tránh lỗi native SDK làm mất raw/usage trước repair. Giữ v5 INCOMPLETE, snapshot và reservation. Các lượt model thật sau pytest chỉ gắn nhãn lại **cùng replies lịch sử**, ghi riêng trong [RUN-LEDGER.md](evaluation/RUN-LEDGER.md); không phải chạy lại agent hiện tại hoặc bằng chứng semantic gold đã được duyệt.
- Không sửa frontend trong lượt bổ sung này; bằng chứng nghiệm thu thiết kế riêng ở [design-checklist-2026-11-01.md](frontend/design-checklist-2026-11-01.md). Các số local bên dưới là mốc nghiệm thu backend/frontend trước lượt bổ sung, không thay thế kết quả suite hiện tại.

## Kết quả local

| Lớp | Kết quả | Bằng chứng/phạm vi |
|---|---|---|
| Backend đầy đủ | **447 passed** | `pytest -q --maxfail=1`, Python 3.12; PostgreSQL 17 và Redis 7.4 local; model factory và mạng ngoài bị chặn |
| PostgreSQL | **8 passed**, nằm trong suite trên | Hai khách tranh tồn cuối; erasure/checkpoint/vault; bận thì retry; mở một call; claim handoff; force; fact cách ly; finalizer duy nhất |
| Redis | **1 passed**, nằm trong suite trên | Rate limit TTL nguyên tử qua Redis thật, namespace test riêng |
| Frontend unit | **13 passed** | Cart/account race, retry attach, BFF PATCH/upload hủy/quá lớn, text error/status, SSE Unicode/CRLF/truncated, fake microphone/socket cleanup |
| Frontend typecheck | **Đạt** | `npm run typecheck` |
| Production build | **Đạt** | `npm run build` dùng `next build --webpack`; route tĩnh và động được build |
| Browser production | **10 passed** | Chrome; API platform thật với agent giả → gateway thật → Next BFF; session/OTP muộn, checkout, fault sau commit, staff console, mobile 390 px và bàn phím |

Không có model/provider thật, dữ liệu khách thật, SMS, thanh toán ngân hàng hoặc gửi tin ra kênh ngoài trong các test trên. Các test tạo dữ liệu tổng hợp; PostgreSQL chỉ cho DB riêng có tên `telesales_test`, Redis dùng namespace riêng. Improvement artifacts của pytest được cách ly vào thư mục tạm. Docker đang paused được giữ nguyên; dependency local tạm được dừng sau test.

## Các lỗi và regression chính

| Nhóm | Hành vi đã gia cố | Test |
|---|---|---|
| HTTP/stream | PATCH/HEAD/OPTIONS xuyên proxy; giới hạn body/frame; timeout, lỗi text, request ID, Retry-After; đóng upstream và task khi disconnect | `tests/test_gateway.py`, frontend unit |
| Commerce | COD thiếu phương thức vẫn chịu hạn mức; replay kiểm tra toàn payload; lookup key theo chủ tài khoản; tồn kho reserve/hoàn đúng một lần | `tests/test_checkout_hardening.py`, `tests/test_postgres_hardening.py`, workflows |
| Evidence/tool | Đọc đơn rỗng không chứng minh tạo đơn; kiểm tra hành động, mã đơn và từng trạng thái; output sai schema không coi là thành công; context ID hệ thống ghi đè model | `tests/agent/test_order_follow_up.py`, `test_tool_privacy.py` |
| Identity/memory | Xác nhận danh tính/liên hệ không kích hoạt toàn bộ fact cách ly; tombstone chặn ghi muộn và liên kết lại | `tests/agent/test_memory_integrity.py`, PostgreSQL |
| Erasure | Mapping web/verified owner; chữ ký nội bộ; batch command; receipt chỉ completed sau acknowledgement; cleanup ledger/episode/call/vault/checkpoint/gap; ngăn gap job cũ ghi lại | PostgreSQL, checkout, gap review, outbox |
| Call/staff | Khóa mở call theo conversation; đóng chờ turn; finalizer có lease/heartbeat/retry sau restart; claim một chủ; force không vượt quyền/PII/internal guard | PostgreSQL, `test_voice_transport.py` |
| Outbox | ProcessedEvent idempotency; lỗi consumer giữ event hiện tại trước khi poll/commit offset sau | `tests/test_outbox_retry.py` |
| Improvement | Gap dedup, khử PII, người duyệt và nguồn public; regression proposal chưa được coi là nhãn; publish/rollback/revoke serialized và atomic; judge fake lỗi/missing/evidence bịa/whitespace là INCOMPLETE | `tests/agent/test_gap_review_and_judge.py`, improvement loop tests |
| Frontend | Response account/call cũ bị bỏ qua; debounce cart ghi theo thứ tự; quote thay đổi cần xác nhận lại; double-click không tạo trùng; timeout tra key trước retry; chat giữ partial và turn ID; voice cleanup | frontend unit và browser |

## Tái lập

Từ gốc repo, dùng môi trường Python đã cài `requirements-dev.txt`:

```sh
# Thay URL bằng PostgreSQL/Redis TEST riêng; không dùng database vận hành.
TEST_DATABASE_URL=postgresql+psycopg://test_runner@127.0.0.1:55432/telesales_test \
TEST_REDIS_URL=redis://127.0.0.1:56379/15 \
apps/ai-agent-service/.venv/bin/python -m pytest -q

# Không đặt hai URL trên thì phần integration sẽ SKIP, không được ghi nhận đã đạt.
apps/ai-agent-service/.venv/bin/python -m scripts.contracts.export_contracts
git -c core.whitespace=cr-at-eol diff --check
```

Trong `apps/web`:

```sh
npm ci
npm run typecheck
npm run test:unit
npm run build
```

Browser dùng fixture `tests/offline_api.py` (provider key bị bỏ và model factory bị chặn). Chạy ba tiến trình riêng, dừng chúng sau test:

```sh
# Terminal 1, gốc repo
PYTHONPATH=tests:packages/backend-common:apps/ai-agent-service/src:. \
apps/ai-agent-service/.venv/bin/python -m uvicorn offline_api:app --host 127.0.0.1 --port 18000

# Terminal 2, gốc repo
COMMERCE_SERVICE_URL=http://127.0.0.1:18000 \
IDENTITY_SERVICE_URL=http://127.0.0.1:18000 \
SALES_SERVICE_URL=http://127.0.0.1:18000 \
AI_AGENT_SERVICE_URL=http://127.0.0.1:18000 REDIS_URL= \
apps/ai-agent-service/.venv/bin/python -m uvicorn main:app --app-dir apps/api-gateway/src --host 127.0.0.1 --port 18001

# Terminal 3, apps/web, sau build
BACKEND_URL=http://127.0.0.1:18001 npm run start -- --hostname 127.0.0.1 --port 13000

# Terminal 4, apps/web
OFFLINE_STACK=1 WEB_URL=http://127.0.0.1:13000 \
npx playwright test e2e/session.spec.ts e2e/offline-checkout.spec.ts e2e/call-console.spec.ts
```

Local dùng Chrome đã cài; CI cài Chromium và chọn browser mặc định. `next start` hiện in cảnh báo cấu hình standalone; deployment standalone cần dùng entry server đã đóng gói theo cấu hình repo. Smoke ở đây chạy code production đã build.

Workflow `.github/workflows/offline-checks.yml` tự cài dependency, PostgreSQL/Redis, chạy backend, frontend typecheck/unit/build và browser fixture. Chưa push để chạy GitHub Actions từ xa; các bước tương ứng đã chạy local.

## Giới hạn kết luận

Các test xác nhận những invariant và lỗi nêu trên; chúng không chứng minh phần mềm không còn bất kỳ lỗ hổng nào. Chưa kết luận điểm của bản mới, chất lượng model/judge/extractor, latency có model, thiết bị voice thật, tải nhiều replica hoặc deployment. Kafka offset retry được fault-inject bằng consumer giả; chưa nghiệm thu broker Kafka thật, rebalance hoặc process kill trên deployment.

Phần tài khoản/OTP/quyền dùng endpoint thật trong suite; kiểm tra thu hồi quyền xuyên nhiều dịch vụ, proxy/IP rate limit sau load balancer, secret rotation và log/backup ngoài repo cần đối chiếu trên topology triển khai. Không dùng số local làm số vận hành.

Các lượt còn chờ, lệnh, ngân sách, bằng chứng và tiêu chuẩn đạt nằm trong [WAITING-FOR-USER.md](plan/WAITING-FOR-USER.md). Dữ liệu/tiếng Việt tiếp tục ngoài phạm vi. File local/untracked có trước được bảo toàn; chưa commit hoặc push thay đổi.
