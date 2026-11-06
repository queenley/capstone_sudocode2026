---
name: improvement-log
description: Ghi lại mỗi cải tiến vào docs/plan/IMPROVEMENT-LOG.md. Dùng sau khi sửa một kịch bản hoặc lượt trả lời sai, sửa lỗi TSR, CCR, RQR, HR, thêm tính năng cho agent, evaluation hoặc dữ liệu, hoặc khi người dùng nói "ghi lại cải tiến". Dùng cả khi cải tiến bị quay lui. Không dùng cho đổi tên, format code hay sửa chính tả.
---

# Nhật ký cải tiến

Mỗi lần sửa case sai hoặc thêm tính năng, thêm một mục vào [`docs/plan/IMPROVEMENT-LOG.md`](../../../docs/plan/IMPROVEMENT-LOG.md). Nhật ký trả lời: đã đổi gì, vì sao, đã kiểm thế nào, và số đo có tốt lên thật không.

Nhật ký không thay file đề xuất. Quy trình trong [`docs/plan/README.md`](../../../docs/plan/README.md) vẫn áp dụng: thay đổi chạm prompt, guard hoặc bộ nhớ cần được duyệt trước khi code.

## Khi nào ghi

Ghi sau khi code và test đã xong, trong cùng lượt làm việc, trước khi báo kết quả cho người dùng. Nếu đo xong mới có số, sửa lại mục cũ thay vì thêm mục mới.

Một thay đổi có nhiều lỗi độc lập thì tách thành nhiều mục, để sau này quay lui được từng lỗi.

## Viết một mục

Thêm lên đầu phần "Các mục", theo đúng mẫu trong file nhật ký:

1. **Loại:** lấy từ bảng "Thêm skill ở đâu" của `docs/plan/README.md` (prompt, hard guard, slot bộ nhớ...), hoặc `dữ liệu`, `evaluation`, `tính năng`.
2. **Vấn đề:** agent làm sai gì, hoặc thiếu gì. Một hai câu.
3. **Bằng chứng:** run, `SCN-... call_N turn_K`, chỉ số. Đọc trace để viết, không suy đoán nguyên nhân.
4. **Sửa:** file và cách sửa, kèm lý do chọn chỗ đó nếu không hiển nhiên.
5. **Đã kiểm:** test nào, kết quả thật.
6. **Số đo:** trước và sau trên cùng cohort. Chưa chạy thì ghi `chưa đo`, không ghi kỳ vọng thành kết quả.
7. **Còn lại:** phần chưa làm, rủi ro, việc cần người quyết định.

Trạng thái dùng chung với `docs/plan/README.md`: `đang đo`, `xong`, `bỏ`. Chỉ ghi `xong` khi đã có số đo; đã code và qua test nhưng chưa đo thì ghi `đang đo`. Cải tiến thất bại vẫn giữ mục, ghi `bỏ` và lý do.

## Quy tắc

- Không dán hội thoại, số điện thoại, địa chỉ, key hay dữ liệu khách. Chỉ dẫn mã kịch bản và đường dẫn run.
- Chỉ so số giữa các run cùng `extractor_version` và cùng bộ kịch bản; đổi nhãn dữ liệu thì ghi rõ.
- Không tự commit. Commit khi người dùng yêu cầu.
