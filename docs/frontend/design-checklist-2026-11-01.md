# Frontend design checklist — 01/11/2026

Nguồn đã đọc: [Front-End Design Checklist, README](https://github.com/thedaviddias/Front-End-Design-Checklist). Áp dụng các mục phù hợp với sản phẩm hiện có; giữ bộ nhận diện emerald, component và contract hiện tại. Không thêm dependency.

## Checklist áp dụng

| Mục nguồn | Thay đổi cụ thể | Bằng chứng |
| --- | --- | --- |
| 1.1 Grid; 1.7 Responsive | Cột co giãn bằng `minmax(0, 1fr)`, giỏ mobile tách giá và thao tác thành hàng riêng; nội dung console dài xuống dòng; form token mobile xếp một cột, header gọn thành hai hàng. | Browser kiểm tra 8 route ở 320, 390, 768, 1440 px, mỗi route ở light/dark. |
| 1.2 Colors | Nút chính light dùng emerald đậm hơn; viền input rõ hơn trong hai theme; tổng tiền dùng màu thương hiệu. | Browser tính tương phản token: chữ/nút ≥ 4.5:1, viền input ≥ 3:1. Đây là kiểm tra các token này, không phải chứng nhận toàn bộ trang. |
| 1.3 Fonts/text | Nhịp dòng chung 1.5; hội thoại console/voice 14px, metadata 11px; composer mobile 16px; hướng dẫn checkout bằng tiếng Việt. | Screenshot và assertion font-size trong console có hội thoại giả. Font fallback được kiểm tra khi request font ngoài bị chặn. |
| 1.4 Links/navigation | Skip link, focus outline, trạng thái trang hiện tại, Escape cho menu mobile; tên trường tìm/lọc đơn; nút mở chi tiết đơn có `aria-expanded`. | Keyboard tests: skip, menu, mở chi tiết đơn và tìm kiếm. Console mobile có assertion nút làm mới nằm dưới checkbox, không chồng lên nhãn. |
| 1.6 Forms/buttons | Các nút chính cao tối thiểu 44px; OTP tự focus và bỏ ký tự không phải số; bước checkout bị khóa vẫn đọc rõ; CTA có hướng dẫn điều kiện còn thiếu. | Luồng OTP → địa chỉ → xác nhận → đặt hàng; gửi hai lần chỉ tạo một request; focus về heading thành công. |
| 1.6 Loading/error/disabled | Catalog có thử lại và dừng skeleton khi lỗi; kết quả lọc rỗng có “Xóa bộ lọc”; thêm giỏ có phản hồi; số lượng không giảm về 0 hoặc tăng quá tồn kho tại giỏ. | Browser thử lỗi 503, retry, bộ lọc rỗng, giới hạn số lượng và phản hồi thêm món. |
| 1.8 Components/style guide | Tiếp tục dùng `theme.css`, `shop.css`, `globals.css`, `sales.css` và component hiện có. | Không thêm thư viện, không tạo bộ style song song. |
| 1.9 Error pages/popups | Trang 404 có đường quay lại; shop error boundary có thử lại; chat/voice dùng native modal dialog. | Browser kiểm tra 404, modal, background inert, Escape và trả focus. Error boundary chưa được chủ động gây crash để kiểm tra trực tiếp. |
| 2–4 Analysis/validation/development | Đọc quy tắc repo, Next.js docs đi kèm, caller và test trước khi sửa; kiểm tra lại production CSS. | Build, typecheck, unit và browser tests; kết quả bên dưới. |

## Các lỗi hành vi đã sửa

- `useCartItems` chỉ coi 404 là sản phẩm bị gỡ. Lỗi tạm thời giữ giỏ, cho thử lại và chặn đặt hàng; SKU mới phải tải xong trước khi hiển thị thông tin/tổng tiền. Request cũ được hủy khi thay giỏ hoặc rời trang.
- Catalog/search/product không để phản hồi cũ thay kết quả mới; lỗi tải có lối thử lại.
- Giỏ hàng dùng button disabled thật khi chưa đủ dữ liệu, thay cho link trỏ `#`. Nút tăng/giảm/xóa có tên sản phẩm để phân biệt bằng screen reader.
- Checkout tôn trọng `cod.enabled` từ API; phương thức bị tắt không được chọn tự động. Giữ nguyên cơ chế quote, idempotency và phục hồi đơn có sẵn.
- Chat/composer không gửi Enter trong khi IME đang ghép chữ. Khi đóng chat, focus trở về đúng nút đã mở nó; đóng voice trả về nút gọi trong chat.
- Voice không đọc lại timer mỗi giây cho screen reader; thông báo mất kết nối không lộ hướng dẫn config backend. Chỉ đổi UI, giữ contract microphone và playback acknowledgement.
- Console chờ khởi tạo token trước khi cho nhập, tránh mất dữ liệu nhập trong lúc hydrate; có trạng thái tải và nút kết nối bị khóa trong lúc tải. Console nhúng dùng section/h2, tránh lồng hai main và h1.
- Giảm motion cho animation và cuộn hội thoại theo lựa chọn hệ thống; cuộn tin nhắn tới vị trí gần nhất để hạn chế kéo cả trang.

## Kiểm chứng

Kết quả cuối cùng trên source hiện tại:

| Kiểm tra | Kết quả |
| --- | --- |
| `npm run typecheck` | PASS |
| `npm run test:unit` | 15/15 PASS, gồm microphone profile và playback acknowledgement |
| `npm run build` | PASS: webpack, TypeScript, tạo trang và đóng gói standalone |
| Browser trên artifact standalone production | 20/20 PASS, Chrome; không có request ngoài fixture hoặc pageerror trong suite design-checklist |
| Responsive | 64 kiểm tra chiều rộng: 8 route × 4 viewport × 2 theme, cộng console có nội dung ở 390/1440 px |
| Whitespace | `git -c core.whitespace=cr-at-eol diff --check -- apps/web docs/frontend`: PASS (repo có các file CRLF từ trước) |

Đã xem ảnh home desktop, cart/checkout mobile, chat mobile, lỗi micro và copilot desktop/mobile. Ảnh được giữ ngoài git tại thư mục artifact của chat này:

- [Home desktop, light](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/home-1440-light.png)
- [Giỏ mobile, dark](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/giohang-390-dark.png)
- [Checkout mobile, light](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/thanhtoan-390-light.png)
- [Chat mobile](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/chat-mobile.png)
- [Copilot desktop](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/copilot-1440.png)
- [Copilot mobile](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/copilot-390.png)
- [Lỗi quyền micro](/Users/vqd/.codex/visualizations/2026/10/31/01a19312-9e84-7643-b0f7-0965ff6a4f62/frontend-checklist/voice-permission-error.png)

Các lệnh chạy trong `apps/web` (browser trỏ tới bản sao frontend trên cổng riêng):

```sh
npm run typecheck
npm run test:unit
npm run build
WEB_URL=http://127.0.0.1:3317 npm run test:e2e -- e2e/design-checklist.spec.ts e2e/call-console.spec.ts e2e/session.spec.ts
```

Preview/build dùng thư mục tạm riêng, không chép `.env`, không dùng chung `.next` với workspace. Browser test mới fulfill mọi request `/backend/**` bằng fixture và chặn HTTPS bên ngoài. Ca voice giả lập từ chối quyền micro. Không chạy model, `run_eval.py` hoặc cohort; không gọi ASR đang chạy. Các test mua hàng live và offline stack không được chạy trong đợt này.

Ảnh browser được sinh qua `test.info().outputPath(...)` trong `test-results`: home desktop light/dark, cart/checkout mobile light/dark, sales orders desktop light/dark, chat mobile, lỗi quyền micro, console có hội thoại mobile/desktop. Toàn bộ dữ liệu trong ảnh là giả.

## Chưa kiểm tra / không áp dụng

- Chưa kiểm tra Safari/Firefox, thiết bị iOS/Android thật, VoiceOver/NVDA, zoom trình duyệt 200–400% và forced-colors.
- Chưa kiểm tra cuộc gọi thật, ASR/TTS, SMS, chuyển khoản/VietQR thực, backend production hoặc latency của model.
- Chưa chạy Lighthouse/axe toàn site; chưa đo payload webfont, Core Web Vitals hoặc kiểm chứng tất cả title/heading/contrast của các trang ngoài phạm vi.
- Các mục bàn giao PSD/Sketch, giấy phép font mới và xuất asset thiết kế không áp dụng: đây là sửa frontend đang có, không có bộ file thiết kế mới.
- Những thay đổi local/backend đã có trước đợt này được giữ nguyên; không commit, push hay deploy.
