# NNN. Tên cải tiến

| | |
|---|---|
| Trạng thái | ý tưởng / đề xuất / đã duyệt / đang làm / đang đo / xong / bỏ |
| Người phụ trách | |
| Ngày tạo | YYYY-MM-DD |
| Loại | tri thức / playbook / prompt / hard guard / soft guard / action guard / tool / signal / lane / slot bộ nhớ / ITN / lexicon / config |
| Chỉ số mục tiêu | TSR / CCR / RQR / HR / latency / ... |

## 1. Vấn đề

Agent đang làm sai gì? Viết bằng ví dụ cụ thể.

## 2. Bằng chứng

- Run / kịch bản / lượt: `evaluation/agent-evaluation/runs/...`, `SCN-GEN-xxxx call_N turn_K`
- Khách nói: "..."
- Agent nói: "..."
- Đáng lẽ: "..."
- Xảy ra bao nhiêu lần trên bao nhiêu lượt:

(Không dán hội thoại có dữ liệu khách thật.)

## 3. Giải pháp

Sửa ở đâu (xem bảng "Thêm skill ở đâu" trong [README](README.md)), sửa thế nào. Vì sao chọn chỗ này thay vì chỗ khác.

## 4. Rủi ro

Thay đổi này có thể làm hỏng tình huống nào khác? (Ví dụ: quy tắc "không hỏi lại" có thể khiến agent không xác nhận khi cần.)

## 5. Cách đo

- Test offline thêm:
- Cohort đo trước/sau (ID, lấy từ [RUN-LEDGER](../evaluation/RUN-LEDGER.md)):
- Kỳ vọng: chỉ số X từ ... lên ...
- Điều kiện quay lui:

## 6. Kết quả

| Chỉ số | Trước | Sau |
|---|---|---|
| | | |

Kết luận, và có giữ thay đổi không.
