# EC03: xác nhận mua gắn với đúng phiên và đúng đơn

Cập nhật 01/11/2026 trên nhánh `codex/backend-frontend-memory-welcome`. Phần vá đang ở working tree, chưa commit/deploy. Đây là kiểm thử offline bằng dữ liệu giả và fake model; không phải điểm số evaluation BTC hay đo tần suất model thật hiểu sai.

## Kết quả sau vá

**Các trường hợp EC03 đã có chốt chặn ở agent và backend.** “Vâng” sau câu hỏi xem ảnh tại Zalo B không tạo đơn ở B và không kích hoạt hotline A. Nếu model vẫn gọi nhầm `order_create`, guard trả `CONFIRMATION_REQUIRED`; hệ thống chỉ đọc lại một đơn cụ thể để khách xác nhận, chưa ghi đơn.

Cả yêu cầu mua chủ động cũng được đọc lại payload cuối trước khi tạo đơn. Khách đồng ý ở lượt tiếp theo, trong chính phiên phát câu hỏi và còn hạn, thì mới được thực thi. Đây là thay đổi hành vi có chủ đích so với quy tắc trước đây “khách muốn đặt thì ghi đơn ngay trong lượt”.

| Trường hợp | Kết quả sau vá |
|---|---|
| A hỏi mua, B hỏi xem ảnh, khách nói “vâng” ở B | Không ghi đơn; checkpoint A giữ nguyên |
| Model cố tình phát lệnh tạo đơn sai tại B | Bị chặn trước tool; phải đọc lại đơn và nhận xác nhận mới ở B |
| Đổi SKU, đơn giá, số lượng, thanh toán, địa chỉ hoặc mã khuyến mãi | Xác nhận cũ không khớp; phải phát draft/câu hỏi mới |
| Hủy, sửa yêu cầu hoặc nói sang chuyện khác rồi mới “vâng” | Pending confirmation cũ bị vô hiệu hóa |
| Câu hỏi sau cùng là xem ảnh, hoặc câu đọc đơn bị ngắt | “Vâng” không cấp quyền tạo đơn |
| Dùng xác nhận ở call/kênh/customer/turn khác | Bị chặn; không tự chuyển quyền chỉ vì cùng customer profile |
| Xác nhận chưa dùng đã hết hạn | Backend từ chối ghi đơn |
| Hai request cùng xác nhận chạy đồng thời | Một mutation; request còn lại nhận kết quả đầu tiên |
| Replay một giao dịch đã thành công sau khi receipt hết hạn | Trả kết quả đã lưu, không tạo đơn mới |
| Giả receipt, sửa payload/scope/key trước khi gọi MCP | Backend từ chối |
| Payload và câu xác nhận khớp, khách đồng ý đúng phiên | Tạo đơn thành công; xóa pending trong working state |

TTL xác nhận là **5 phút theo đồng hồ thực**, độc lập với ngày kinh doanh giả lập của catalog. Đổi kênh phải chuẩn bị và xác nhận lại đơn tại kênh đích. Chưa bổ sung API chuyển giao một intent giữa hai phiên; xác nhận ở A không được thừa kế tại B.

## Luồng triển khai

1. `order_create` vẫn đi qua các kiểm tra phone, tier, SKU đáng tin, quote, COD và chống trùng cùng call. Số lượng phải là số nguyên dương, tránh đọc lại một lượng khác lượng tool sẽ thực hiện.
2. Nếu chưa có consent khớp, `ActionGuardMiddleware` tạo một draft chỉ chứa metadata và hash: `draft_id`, `call_id`, `channel`, owner hash, `issued_turn_id`, `action_type`, `target_id`, `payload_hash`, `expires_at`, `status`, câu hỏi đã token hóa. Không ghi pending này vào customer facts.
3. Hot graph phát câu xác nhận chuẩn gồm sản phẩm/SKU, số lượng, đơn giá, tổng, thanh toán, mã khuyến mãi và địa chỉ. Với stream, dừng model sau kết quả chuẩn bị và tự phát câu hỏi; với non-stream, phản hồi được thay bằng câu hỏi chuẩn. Model không tự diễn đạt lại payload để cấp quyền.
4. `perceive` chỉ chuyển pending sang `authorized` khi lượt kế tiếp là lời đồng ý đơn thuần và câu hỏi đó vẫn là phần cuối lời agent vừa nói. Câu có thêm yêu cầu sửa (“vâng nhưng đổi thành 2 cái”), câu hỏi khác, phần thoại bị ngắt, sai scope hoặc hết hạn đều không cấp quyền. `confirmed_turn_id` gắn với lượt đồng ý hiện tại.
5. Guard đối chiếu đầy đủ payload đã resolve: SKU, unit price, qty, payment, promo, địa chỉ thật từ vault, phone và ngày kinh doanh. HMAC receipt chỉ được middleware tạo từ context tin cậy; các trường scope/receipt/key do model gửi đều bị ghi đè. Receipt không được lưu vào tool-args trace đưa lại cho model.
6. MCP CRM kiểm chữ ký, call/turn, action, payload hash và idempotency key. Trong cùng transaction/advisory lock ghi `mock_state`, backend kiểm expiry/consumed, thực hiện order và lưu `purchase_consumed[draft_id]`. Không consume khi business tool từ chối. Các write khác giữ lại consumed map. Cùng consent không được dùng cho một key khác.

Hash receipt dùng payload chuẩn hóa; idempotency giữ cách tính key cũ cho các business args tương đương để không làm mất replay của đơn có trước bản vá. Backend chấp nhận các dạng optional field bị bỏ trống hoặc `null` tương ứng, nhưng không chấp nhận key của payload khác.

Các service AI/MCP cần chạy cùng phiên bản và cùng `APP_SECRET` khi áp dụng bản vá. Client/runtime cũ không có receipt bị backend từ chối. Không có SQL migration: pending ở checkpoint, consumed ở JSON `mock_state`. Đường Commerce checkout qua `OrderService` vẫn kiểm authorization, boolean xác nhận, giá/tổng tiền và tồn kho riêng; agent `order.create` không đi qua bảng `orders` của Commerce.

## Timeline demo và assert

| Mốc | Hành động | Assert |
|---|---|---|
| T0 | Hai kênh được resolve thành cùng `EC03-CUSTOMER` | Cả hai đọc fact `color=trang`, nhưng call/checkpoint/draft riêng |
| T1A | A chuẩn bị máy màu trắng | Chỉ phát câu xác nhận; spy tạo đơn = 0; có pending của A |
| T1B | B hỏi xem ảnh màu trắng | Câu hỏi cuối là xem ảnh; chưa có quyền mua |
| T2 | Khách chỉ nói “vâng” ở B; fake model cố tình phát lệnh mua | Spy = 0; A giữ nguyên; B phải phát một câu xác nhận mua mới nếu model đề nghị đơn |
| T3 | Khách đồng ý với câu đọc đơn mới ở B | Một lệnh có receipt/key của B; pending B được xóa; A chưa tạo đơn |
| T4 | Khách đồng ý tại A | Chỉ consent của A cấp quyền; không dùng draft B |
| DB | Hai lần gọi backend cùng receipt/key đồng thời | Một order, một idempotent result và một consumed entry; payload/scope sửa hoặc receipt hết hạn chưa dùng không tăng số đơn |

Test kiểm cả xen kẽ và `asyncio.gather`, dùng chung một `AdvisorAgent`/graph/customer facts. PostgreSQL còn kiểm hai lease khác call cùng được giữ, lease thứ hai cùng call bị từ chối, checkpoint và `turns` tách theo call kể cả khi hai phiên có cùng `turn_id` đầu.

## File thay đổi

- [`purchase.py`](../../apps/ai-agent-service/src/ai_agent_service/components/guardrails/purchase.py): draft, khớp câu trả lời, payload/hash, HMAC receipt và ràng buộc key.
- [`advisor.py`](../../apps/ai-agent-service/src/ai_agent_service/agents/advisor.py), [`hot/state.py`](../../apps/ai-agent-service/src/ai_agent_service/pipeline/hot/state.py), [`hot/nodes.py`](../../apps/ai-agent-service/src/ai_agent_service/pipeline/hot/nodes.py): guard, pending theo call và phát câu xác nhận chuẩn.
- [`mcp/tools.py`](../../apps/ai-agent-service/src/ai_agent_service/mcp/tools.py), [`mcp/servers/crm.py`](../../apps/ai-agent-service/src/ai_agent_service/mcp/servers/crm.py), [`mcp/servers/btc.py`](../../apps/ai-agent-service/src/ai_agent_service/mcp/servers/btc.py): resolve payload, inject receipt, verify và consume atomic.
- [`actions.py`](../../apps/ai-agent-service/src/ai_agent_service/components/guardrails/actions.py), [`advisor/rules.md`](../../config/prompts/agent/advisor/rules.md): quantity validation và hướng dẫn quy trình xác nhận.
- [`test_ec03_confirmation_isolation.py`](../../tests/agent/test_ec03_confirmation_isolation.py): regression tests, gồm luồng bị chặn và mua thành công.

## Kiểm thử và giới hạn

Bộ EC03 có **52 case**, gồm graph/AdvisorAgent/middleware thật với fake model và spy; các trường hợp sửa payload/scope/expiry/cancellation; lời đồng ý tự nhiên; chữ ký giả; bảo toàn idempotency key cũ; middleware ghi đè tham số model; runtime reply replay; backend consume/replay; PostgreSQL call/checkpointer/CallStore và MCP business transaction thật; API Commerce.

Kết quả cuối: **654 passed, 1 skipped trong 18,00 giây pytest**, chạy toàn bộ `tests` ngoài `tests/agent/test_asr*`. Đủ 52 case EC03 đã chạy, không skip case EC03. Test bị skip duy nhất là `tests/test_gateway.py:82` vì chưa có `TEST_REDIS_URL`. Các test Commerce/PostgreSQL hiện có cũng đã chạy trên database tạm riêng. Không tính thời gian khởi tạo/dừng cluster vào thời gian pytest.

Lượt PostgreSQL dùng cluster mới hoàn toàn trong thư mục tạm, chỉ listen localhost, có hai database `ec03_test` và `telesales_test`. Chạy toàn bộ test ngoài ASR, không kết nối DB cấu hình ứng dụng. Server được dừng và data directory bị xóa sau mỗi lượt. Test Redis độc lập chỉ chạy khi có `TEST_REDIS_URL`; không skip EC03 để làm xanh test.

Lệnh kiểm tra nhanh (case PostgreSQL skip khi chưa cấu hình DB riêng):

```bash
TEST_DATABASE_URL=sqlite:// apps/ai-agent-service/.venv/bin/python -m pytest -q tests/agent/test_ec03_confirmation_isolation.py
```

Bằng chứng sau vá nằm trong `evaluation/runs/20261101-ec03/fix/`: `manifest.json`, `pytest-postgres.txt`; không lên Git. Không gọi provider trả phí, không sửa extractor/scorer/scenario/ground truth/BTC pack, không thay ASR, commit, push hoặc deploy.

Chưa gọi model thật để đo chất lượng hội thoại/tỷ lệ hoàn tất sau khi thêm bước xác nhận; chưa kiểm mạng Zalo/telephony hoặc audio thực. Các test MCP business chạy qua Python và database thật; không chạy deployment HTTP/stdin MCP đầy đủ. Không thử hủy một lệnh mua đã được khách xác nhận và đang thực thi trên mạng; trường hợp này cần quy trình hủy đơn riêng.

## Bằng chứng lịch sử trước vá

Ở mốc `8f5319e`, code đã cách ly working memory theo call và không có boolean chung `waiting_for_confirmation`. Tuy nhiên fake model gọi nhầm tạo đơn tại B vẫn vượt guard, kể cả lời khách “không mua đâu”; PostgreSQL `mock_state` ghi được đơn. Lượt characterization trước vá có 82 test xanh vì assert mô tả hành vi chưa an toàn. Log cũ ở thư mục cha `evaluation/runs/20261101-ec03/` chỉ là bằng chứng lịch sử, không phải kết quả bản vá. Các expectation unsafe trong file test hiện tại đã đổi thành yêu cầu từ chối, không giữ chúng làm tiêu chí PASS.
