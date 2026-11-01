# Popup chào khách quay lại

Popup cạnh nút chat gọi đúng tên tài khoản và nhắc một blocker còn hiệu lực từ **Memory của agent**. Đây là lời chào deterministic; không gọi LLM, tạo call, chạy after-call, gửi tin hoặc đặt hàng.

## Hành vi trên web

- Chờ `/api/customer/me` xác nhận tài khoản trước khi đọc Memory. Anonymous hoặc tài khoản mới chưa có Memory không thấy popup cá nhân.
- Hiển thị một lần cho mỗi tài khoản trong tab. `sessionStorage` chỉ lưu marker `shop-welcome-seen:<account id> = 1`, không lưu tên, blocker hay response. Đóng, mở chat, chuyển trang hoặc reload không bật lại lời chào đã hiển thị.
- Popup không tự giành focus và không khóa trang. Nút đóng có vùng bấm 44px, ở header riêng ngoài vùng cuộn nên luôn nhìn thấy kể cả khi tên/blocker dài. Escape khi focus ở popup đóng và trả focus về nút chat. CTA “Tiếp tục tư vấn” mở/resume hội thoại như nút chat; không soạn hoặc tự gửi tin. Đóng chat trả focus về launcher còn tồn tại.
- Trong lúc đọc, launcher chat vẫn dùng được; chưa có tên/blocker nào được hiển thị. Lỗi tạm thời có thông báo chung, “Thử lại” và CTA chat; không đưa lỗi server thô ra UI.
- Mỗi response có thời hạn tối đa 30 giây; popup đang mở đọc lại khi hết hạn. Blur/ẩn tab xóa nội dung cá nhân khỏi UI; focus/quay lại tab xác thực lại trước khi hiện. Nếu server trả blocker đã hết hạn thì chỉ chào tên.
- Đổi/logout/thu hồi token, sự kiện reset hội thoại hoặc bắt đầu xóa dữ liệu hủy request và vô hiệu hóa callback cũ. Account revision, token captured và số thứ tự request cùng được kiểm tra. Đổi tài khoản ở tab khác xóa account UI ngay, trước khi tải `/me` mới xong.
- Nội dung tên/blocker là React text, không dùng HTML hay Markdown injection. Tên và blocker dài xuống dòng trong panel cuộn được ở mobile; tiếp tục dùng các token light/dark hiện có.

## API và quyền sở hữu

`GET /api/agent/welcome`, bearer **customer token**; gateway đã định tuyến prefix `/api/agent/` tới AI Agent Service. Route mới độc lập ở `api/routes/welcome.py`; response schema được xuất vào `contracts/api/openapi/ai-agent-service.json`, caller TypeScript ở `services/api.ts`.

Ví dụ response synthetic:

```json
{
  "returning": true,
  "name": "Khách An",
  "blocker": {
    "text": "cần hỏi người nhà",
    "valid_until": "2026-12-02T00:00:00+07:00"
  },
  "expires_at": "2026-11-01T10:00:30+07:00"
}
```

Response không có lịch sử hợp lệ: `returning: false`, `name: null`, `blocker: null`, vẫn có `expires_at`. HTTP 401 khi token sai/hết hạn/thu hồi/tài khoản đã xóa. Không có điện thoại đã xác minh thì trả response rỗng. Memory lỗi trả 503 với thông báo chung. Response thành công dùng `Cache-Control: no-store, private` và `Vary: Authorization`; BFF tiếp tục dùng `no-store`.

Quyền đọc bắt đầu từ `Security.customer`, Customer chưa xóa và CustomerIdentity phone còn verified/chưa revoked. Route không nhận customer ID, phone, ngày nghiệp vụ hoặc nội dung từ model làm quyền truy cập. Query `customer_id` do client thêm không thay đổi chủ thể.

Phone được chuẩn hóa/hash bằng cùng thuật toán và identity secret của hot graph. Chỉ một identity ledger **confirmed** duy nhất mới được nối sang hồ sơ legacy. Key shared/provisional hoặc trỏ `web:` của tài khoản khác bị bỏ qua. Khi chưa có mapping, chỉ đọc `web:<verified account id>`. Không dùng ProfileFact/Episode/WorkingMemory của platform hoặc CRM seed làm Memory thay thế. Tên hiển thị lấy từ chính tài khoản đã xác thực; không trả tên người khác trong hồ sơ legacy.

`returning` cần fact active trong khoảng hiệu lực hoặc episode của ledger. Chỉ chọn blocker active duy nhất có provenance `call_id`, `turn`, `said_by: customer` và confidence hữu hạn trong `[0.6, 1]`. Route áp TTL từ ontology cả khi row cũ thiếu `valid_to`; không khôi phục row invalidated/disputed/unconfirmed. Outcome `chot_don`/`tu_choi` hoặc order mới hơn giải quyết blocker. Timestamp có offset được đổi về UTC trước so sánh; date-only bao phủ cả ngày và ordering không chắc chắn sẽ ẩn blocker. Metadata thời gian/confidence hỏng không được dùng làm lời chào về blocker.

Sau các lần đọc, route kiểm tra lại profile, mapping identity và account/token. Nếu profile/mapping đã đổi theo hướng không an toàn, không trả thông tin cũ. Không serialize episode summary, provenance, identity hay raw phone ra response.

## Xóa dữ liệu

Route dùng `memory_get_profile.deleted_at` **và** `deletion_pending` do luồng erasure cung cấp. Marker trên own web identity hoặc legacy identity đều chặn cả tên và blocker; không đợi việc xóa hoàn tất mới chặn. Platform erasure thu hồi token ngay, trước cleanup agent bất đồng bộ; lần đọc mới bị 401 kể cả khi cleanup đang chờ.

Trang đơn hàng phát reset ngay khi người dùng xác nhận xóa, trước khi chờ DELETE response. Popup hủy request đang chờ; callback cũ không thể phục hồi nội dung. Khi xóa xong, logout và token-change cũng hủy UI. Luồng popup không sửa implementation deletion/MCP, không tự xóa fact hay ghi Memory.

## Kiểm chứng ngày 01/11/2026

Mọi tên, số điện thoại, blocker và hội thoại trong test/ảnh là synthetic. Model factory và mạng provider bị chặn trong pytest; browser fixture fulfill mọi API và chặn HTTPS bên ngoài. Smoke riêng nối **bản production → BFF thật → FastAPI/Identity SQLite thật → ledger giả** trong `tests/offline_api.py`, chỉ seed lịch sử giả cho tên dành riêng `Khách Offline Welcome`.

| Kiểm tra | Kết quả |
| --- | --- |
| `pytest tests/agent/test_returning_welcome.py tests/agent/test_web_memory.py tests/test_gateway.py` | 58 passed, 1 skipped (Redis integration chưa cấu hình) |
| `npm run typecheck` | PASS |
| `npm run test:unit` | 15 passed |
| `npm run build` | PASS, webpack + TypeScript + standalone production |
| Chrome trên production, suite popup + session + design checklist + smoke API offline (trước chỉnh header luôn hiện) | 31 passed |
| Chrome trên production cuối, popup + session; cuộn nội dung dài rồi click đóng, không mở chat | 15 passed |

Backend kiểm tra token/customer ownership, phone không verified, key shared/provisional, legacy confirmed, tài khoản khác, không side effect, TTL/status/provenance/confidence, resolution timestamp khác offset, Memory lỗi, revocation/erasure/mapping đổi giữa request. Browser kiểm tra anonymous, tải chậm/lỗi/retry, CTA resume không gửi tin, logout/đổi tài khoản/xóa khi request đang chờ, expiry, dismiss/reload/navigation, focus, light/dark và nội dung độc hại/dài ở 320px.

Build/preview nằm riêng trong `/private/tmp/quivo-returning-web-v265f8a8/web`, không copy `.env`, không dùng `.next` workspace. Không chạy `RUN_LIVE_AGENT`, evaluation/model, SMS thật, Docker hoặc deployment.

Lệnh kiểm tra frontend từ `apps/web`:

```sh
npm run typecheck
npm run test:unit
npm run build
RUN_OFFLINE_WELCOME=1 WEB_URL=http://127.0.0.1:3324 npm run test:e2e -- e2e/returning-welcome.spec.ts e2e/returning-welcome-offline.spec.ts e2e/session.spec.ts e2e/design-checklist.spec.ts
```

Smoke opt-in cần preview trỏ `BACKEND_URL=http://127.0.0.1:18023` tới API fixture được khởi động bằng:

```sh
PYTHONPATH=tests:packages/backend-common:apps/ai-agent-service/src apps/ai-agent-service/.venv/bin/python -m uvicorn offline_api:app --host 127.0.0.1 --port 18023
```

Ảnh kết quả (ngoài git):

- [Desktop synthetic](/Users/vqd/.codex/visualizations/2026/10/31/01a1935d-351d-70b0-9c4b-c4b4d1cb4e69/returning-popup/returning-desktop.png)
- [Mobile synthetic](/Users/vqd/.codex/visualizations/2026/10/31/01a1935d-351d-70b0-9c4b-c4b4d1cb4e69/returning-popup/returning-mobile.png)
- [Nội dung dài/độc hại, dark 320px](/Users/vqd/.codex/visualizations/2026/10/31/01a1935d-351d-70b0-9c4b-c4b4d1cb4e69/returning-popup/returning-320-dark.png)

## Kiểm tra lại sau đồng bộ main — 01/11/2026

- Giữ endpoint xác thực, đọc Memory theo chủ tài khoản và nút đóng ở header riêng ngoài vùng cuộn.
- Provenance blocker phải có `call_id` là chuỗi không trắng hoặc số nguyên dương, và `turn` là số nguyên dương; bool, chuỗi số, số âm và số thập phân không hợp lệ.
- Outcome `chot_don`/`tu_choi` trong episode mới hoặc cùng cuộc gọi cũng ngăn nhắc lại blocker, ngay cả khi fact outcome chưa có. Episode cũ không xóa blocker mới; mốc cuối của ngày là cận không bao gồm, tránh nhầm hai ngày liền kề là trùng nhau.
- Thêm ca response chậm không được ghi đè lần xác thực lại khi focus. Kiểm tra tọa độ nút đóng không đổi sau khi cuộn ở mobile, cả light/dark.
- Backend: **114 passed, 1 skipped** (Redis integration). Build production và TypeScript đạt. Chrome: **17 passed**, gồm smoke BFF/Identity thật với SQLite và ledger giả; không gọi model hoặc SMS.
- Build/preview tách riêng ở `/private/tmp/capstone-welcome-verification-20261101/web`; không dùng `.env` hay `.next` của workspace. Ảnh synthetic: [mobile](/Users/vqd/.codex/visualizations/2026/11/01/01a196f3-fba7-7be0-9d81-65dea86f8335/returning-popup/returning-mobile.png), [cuộn nội dung dài ở dark 320px](/Users/vqd/.codex/visualizations/2026/11/01/01a196f3-fba7-7be0-9d81-65dea86f8335/returning-popup/returning-320-dark.png).

## Giới hạn

Không thể biết người ngồi trước một trình duyệt vẫn đăng nhập có phải chủ tài khoản hay không; anonymous, logout, đổi tài khoản và identity shared đã được chặn. Việc thu hồi/xóa từ thiết bị khác được phát hiện khi revalidate (tối đa 30 giây khi popup đang mở), hoặc ngay khi tab được focus lại; không có push channel mới.

Chưa kiểm tra PostgreSQL Memory thật trong luồng popup, Safari/Firefox, thiết bị thật hoặc screen reader thật. Không kiểm thử model/voice/SMS/production backend. Các ca SQLite và synthetic ledger xác minh data contract/UI, không thay thế kiểm chứng hạ tầng production.
