---
name: write-docs
description: Viết hoặc cập nhật tài liệu chi tiết trong repo, kèm sơ đồ Mermaid khi có luồng hoặc cấu trúc cần vẽ. Dùng khi người dùng nói "viết docs", "cập nhật tài liệu", "giải thích chi tiết", "thêm sơ đồ", "vẽ luồng", khi thêm tính năng cần người khác hiểu, hoặc khi đổi hành vi mà tài liệu đang mô tả. Không dùng cho nhật ký cải tiến (dùng improvement-log), đề xuất thay đổi (dùng docs/plan/_TEMPLATE.md) hay docstring trong code.
---

# Viết tài liệu

Tài liệu mô tả code hiện tại, viết sao cho người chưa đọc code vẫn làm được việc họ cần. Mỗi điều ghi trong tài liệu phải kiểm được từ code hoặc từ một lần chạy thật.

## 1. Đọc trước khi viết

1. Xác định người đọc và việc họ cần làm: chạy lệnh, sửa code, hay hiểu vì sao một con số ra như vậy.
2. Tìm tài liệu sẵn có trong [`docs/README.md`](../../../docs/README.md) và [`docs/ai/README.md`](../../../docs/ai/README.md). Sửa trang đang nói về chủ đề đó, không tạo trang thứ hai. Chủ đề đã có trang riêng thì dẫn link, không chép lại.
3. Đọc code thật: hàm, file cấu hình, migration, test. Không viết từ trí nhớ hay từ tên hàm. Chạy thử lệnh sẽ ghi vào tài liệu, trừ lệnh tốn phí model.
4. Chạm `evaluation/` hoặc cách tính điểm thì đọc `evaluation/README.md` và `docs/evaluation/scoring-flow.md` trước.

## 2. Viết chi tiết đến mức nào

Viết bằng tiếng Việt, giữ nguyên tên kỹ thuật (`run_eval.py`, TSR, lane). Một trang chi tiết thường có:

1. **Trang này để làm gì:** một đoạn ngắn, nói điều quan trọng nhất ngay đầu.
2. **Sơ đồ tổng quan**, nếu vẽ được (mục 3).
3. **Từng bước hoặc từng thành phần:** làm gì, nằm ở file nào, nhận gì, trả gì.
4. **Ví dụ thật:** lệnh chạy được và kết quả mong đợi, cấu hình mẫu, một lượt trace đã che dữ liệu khách.
5. **Khi có sự cố:** lỗi thường gặp, nguyên nhân, cách xử lý.
6. **Giới hạn:** phần chưa làm, phần chưa đo, phần chưa có người duyệt.

Bỏ mục không có nội dung thật. Chi tiết nghĩa là đủ để làm theo, không phải dài. Giải thích cả lý do khi lựa chọn không hiển nhiên. Không ghi kỳ vọng thành kết quả: số đo phải có run, bộ kịch bản và `extractor_version`.

Dẫn code bằng link tương đối đến file, ví dụ `[advisor.py](../../apps/ai-agent-service/src/ai_agent_service/agents/advisor.py)`. Không ghi số dòng, vì số dòng cũ đi rất nhanh.

## 3. Sơ đồ

Vẽ khi có ít nhất một trong các thứ sau: luồng từ ba bước trở lên, nhiều thành phần gọi nhau, rẽ nhánh, vòng đời trạng thái, quan hệ dữ liệu. Nội dung chỉ là danh sách hoặc bảng thì không vẽ, và nói rõ lý do nếu người dùng đã yêu cầu sơ đồ.

Dùng khối ` ```mermaid `, như `docs/ai/`, để sơ đồ nằm cùng tài liệu và diff được. Không dán ảnh trừ khi người dùng yêu cầu.

| Cần cho thấy | Loại |
|---|---|
| Các bước, rẽ nhánh, thành phần nối nhau | `flowchart LR` hoặc `flowchart TD` |
| Ai gọi ai, theo thứ tự thời gian | `sequenceDiagram` |
| Trạng thái và điều kiện chuyển | `stateDiagram-v2` |
| Bảng dữ liệu và quan hệ | `erDiagram` |

Quy tắc:

- Vẽ cơ chế thật theo code, tên nút khớp tên trong code hoặc tên đã dùng trong trang.
- Mỗi sơ đồ trả lời một câu hỏi, câu đó đứng ngay trên sơ đồ. Quá khoảng 15 nút thì tách thành sơ đồ tổng quan và sơ đồ chi tiết.
- Đặt nhãn có dấu cách, dấu ngoặc, dấu hai chấm hoặc tiếng Việt trong ngoặc kép: `A["Nạp brief (p95)"]`. Nhãn không ngoặc kép là lỗi hay gặp nhất khi Mermaid không dựng được.
- Dùng `subgraph` để nhóm theo service hoặc giai đoạn, ghi nhãn trên cạnh khi điều kiện rẽ nhánh quan trọng.
- Sơ đồ không thay phần chữ: mỗi nút quan trọng được giải thích ở dưới.

## 4. Kiểm trước khi xong

- Chạy lại từng lệnh và mở từng link, đường dẫn trong trang.
- Kiểm sơ đồ dựng được: xem trước Markdown trong VS Code nếu có hỗ trợ Mermaid, hoặc chạy `mmdc -i <file>.md -o <thư mục tạm>/out.md` nếu máy có Mermaid CLI. Chưa dựng thử được thì báo rõ với người dùng.
- Trang mới phải có dòng trong `docs/README.md` hoặc `docs/ai/README.md`.
- Tìm các trang khác còn nói điều cũ về cùng chủ đề và sửa luôn.

## Quy tắc

- Không dán hội thoại thật, số điện thoại, địa chỉ, key hay dữ liệu khách, kể cả trong ví dụ và sơ đồ.
- Không sửa `apps/ai-agent-service/data/btc`.
- Không viết lại báo cáo đã có ngày, ví dụ `docs/evaluation/seed-dev-run-20261105.md`: chúng ghi lại sự việc lúc đó.
- Không tự commit.
