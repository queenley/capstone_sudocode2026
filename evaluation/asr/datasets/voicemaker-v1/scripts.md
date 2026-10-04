# Script Voice Maker v1 — chờ duyệt

26 hội thoại: 6 dev + 20 eval. Chỉ là script, chưa có audio; vùng miền chưa được xác minh. SĐT giả lập, không gọi/nhắn tin. Agent A / khách C dùng hai voice khác nhau. Chỉ gửi từng `turn.text` lên TTS, không gửi GT/metadata. Không đổi script sau khi khóa; nếu TTS đọc khác, nghe duyệt rồi tạo version mới.

## Danh sách

| ID | Miền khách dự kiến | Nhiễu | SKU | SĐT | Ngày gọi | Hẹn |
|---|---|---|---|---|---|---|
| VM-V1-DEV-01 | north | False | SKU-AP-X | 0901242486 | 2026-10-15 | 2026-10-16 |
| VM-V1-DEV-02 | north | False | SKU-AP-X | 0901242486 | 2026-10-16 | 2026-10-17 |
| VM-V1-DEV-03 | central | False | SKU-SN-RUN1 | 0901250405 | 2026-10-15 | 2026-10-17 |
| VM-V1-DEV-04 | central | False | SKU-SN-RUN1 | 0901250405 | 2026-10-16 | 2026-10-18 |
| VM-V1-DEV-05 | south | False | SKU-MB-STR1 | 0901258324 | 2026-10-15 | 2026-10-16 |
| VM-V1-DEV-06 | south | True | SKU-MB-STR1 | 0901258324 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-07 | north | False | SKU-AP-X | 0901266243 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-08 | north | False | SKU-AP-X | 0901266243 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-09 | north | False | SKU-SN-RUN1 | 0901274162 | 2026-10-15 | 2026-10-17 |
| VM-V1-EVAL-10 | north | True | SKU-SN-RUN1 | 0901274162 | 2026-10-16 | 2026-10-18 |
| VM-V1-EVAL-11 | north | False | SKU-MB-STR1 | 0901282081 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-12 | north | False | SKU-MB-STR1 | 0901282081 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-13 | north | False | SKU-AP-X | 0901290000 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-14 | north | False | SKU-AP-X | 0901290000 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-15 | central | True | SKU-SN-RUN1 | 0901297919 | 2026-10-15 | 2026-10-17 |
| VM-V1-EVAL-16 | central | False | SKU-SN-RUN1 | 0901297919 | 2026-10-16 | 2026-10-18 |
| VM-V1-EVAL-17 | central | False | SKU-MB-STR1 | 0901305838 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-18 | central | False | SKU-MB-STR1 | 0901305838 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-19 | central | False | SKU-AP-X | 0901313757 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-20 | central | True | SKU-AP-X | 0901313757 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-21 | south | False | SKU-SN-RUN1 | 0901321676 | 2026-10-15 | 2026-10-17 |
| VM-V1-EVAL-22 | south | False | SKU-SN-RUN1 | 0901321676 | 2026-10-16 | 2026-10-18 |
| VM-V1-EVAL-23 | south | False | SKU-MB-STR1 | 0901329595 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-24 | south | False | SKU-MB-STR1 | 0901329595 | 2026-10-16 | 2026-10-17 |
| VM-V1-EVAL-25 | south | True | SKU-AP-X | 0901337514 | 2026-10-15 | 2026-10-16 |
| VM-V1-EVAL-26 | south | False | SKU-AP-X | 0901337514 | 2026-10-16 | 2026-10-17 |

## VM-V1-DEV-01

Khách `SYN-C01`, call 1; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai bốn, hai bốn tám sáu.
8. **C:** Mình hẹn gọi lại ngày 16 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901242486"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-DEV-02

Khách `SYN-C01`, call 2; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai bốn, hai bốn tám sáu.
8. **C:** Mình hẹn gọi lại ngày 17 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901242486"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-DEV-03

Khách `SYN-C02`, call 1; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai năm, không bốn không năm.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901250405"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-DEV-04

Khách `SYN-C02`, call 2; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai năm, không bốn không năm.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901250405"}`; GT ngày bổ sung: `{"callback_date": "2026-10-18"}`.

## VM-V1-DEV-05

Khách `SYN-C03`, call 1; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai năm, tám ba hai bốn.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901258324"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-DEV-06

Khách `SYN-C03`, call 2; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai năm, tám ba hai bốn.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901258324"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-07

Khách `SYN-C04`, call 1; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi đã gọi rồi, lần này mong được hỗ trợ rõ ràng hơn.
5. **A:** Dạ em ghi nhận và sẽ chuyển thông tin mình cần hỗ trợ cho nhân viên.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai sáu, sáu hai bốn ba.
8. **C:** Mình hẹn gọi lại ngày 16 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901266243"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-08

Khách `SYN-C04`, call 2; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi đã gọi rồi, lần này mong được hỗ trợ rõ ràng hơn.
5. **A:** Dạ em ghi nhận và sẽ chuyển thông tin mình cần hỗ trợ cho nhân viên.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai sáu, sáu hai bốn ba.
8. **C:** Mình hẹn gọi lại ngày 17 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901266243"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-09

Khách `SYN-C05`, call 1; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn hỏi thêm nhưng chưa mua ngay.
5. **A:** Dạ mình có thể cân nhắc thêm, em chưa tạo đơn hàng.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai bảy, bốn một sáu hai.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901274162"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-10

Khách `SYN-C05`, call 2; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn hỏi thêm nhưng chưa mua ngay.
5. **A:** Dạ mình có thể cân nhắc thêm, em chưa tạo đơn hàng.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai bảy, bốn một sáu hai.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901274162"}`; GT ngày bổ sung: `{"callback_date": "2026-10-18"}`.

## VM-V1-EVAL-11

Khách `SYN-C06`, call 1; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai tám, hai không tám một.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901282081"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-12

Khách `SYN-C06`, call 2; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai tám, hai không tám một.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901282081"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-13

Khách `SYN-C07`, call 1; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai chín, không không không không.
8. **C:** Mình hẹn gọi lại ngày 16 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901290000"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-14

Khách `SYN-C07`, call 2; region dự kiến `north`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai chín, không không không không.
8. **C:** Mình hẹn gọi lại ngày 17 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901290000"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-15

Khách `SYN-C08`, call 1; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai chín, bảy chín một chín.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901297919"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-16

Khách `SYN-C08`, call 2; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một hai chín, bảy chín một chín.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901297919"}`; GT ngày bổ sung: `{"callback_date": "2026-10-18"}`.

## VM-V1-EVAL-17

Khách `SYN-C09`, call 1; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi đã gọi rồi, lần này mong được hỗ trợ rõ ràng hơn.
5. **A:** Dạ em ghi nhận và sẽ chuyển thông tin mình cần hỗ trợ cho nhân viên.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba không, năm tám ba tám.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901305838"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-18

Khách `SYN-C09`, call 2; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi đã gọi rồi, lần này mong được hỗ trợ rõ ràng hơn.
5. **A:** Dạ em ghi nhận và sẽ chuyển thông tin mình cần hỗ trợ cho nhân viên.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba không, năm tám ba tám.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901305838"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-19

Khách `SYN-C10`, call 1; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn hỏi thêm nhưng chưa mua ngay.
5. **A:** Dạ mình có thể cân nhắc thêm, em chưa tạo đơn hàng.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba một, ba bảy năm bảy.
8. **C:** Mình hẹn gọi lại ngày 16 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901313757"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-20

Khách `SYN-C10`, call 2; region dự kiến `central`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn hỏi thêm nhưng chưa mua ngay.
5. **A:** Dạ mình có thể cân nhắc thêm, em chưa tạo đơn hàng.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba một, ba bảy năm bảy.
8. **C:** Mình hẹn gọi lại ngày 17 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901313757"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-21

Khách `SYN-C11`, call 1; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba hai, một sáu bảy sáu.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901321676"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-22

Khách `SYN-C11`, call 2; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Giày chạy bộ RunLite 1.
3. **A:** Dạ sản phẩm Giày chạy bộ RunLite 1 có giá một triệu một trăm sáu mươi mốt nghìn đồng tại ngày gọi này.
4. **C:** Để tôi hỏi người nhà trước khi quyết định.
5. **A:** Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.
6. **C:** Ngân sách của tôi là một triệu sáu trăm sáu mươi mốt nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba hai, một sáu bảy sáu.
8. **C:** Mình hẹn gọi lại vào ngày kia nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 1161000, "budget_vnd": 1661000, "phone": "0901321676"}`; GT ngày bổ sung: `{"callback_date": "2026-10-18"}`.

## VM-V1-EVAL-23

Khách `SYN-C12`, call 1; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba hai, chín năm chín năm.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901329595"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-24

Khách `SYN-C12`, call 2; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Xe đẩy gấp gọn Joie Pact.
3. **A:** Dạ sản phẩm Xe đẩy gấp gọn Joie Pact có giá ba triệu bốn trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.
5. **A:** Dạ em cung cấp giá của cửa hàng để mình tham khảo.
6. **C:** Ngân sách của tôi là ba triệu chín trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba hai, chín năm chín năm.
8. **C:** Mình hẹn gọi lại vào ngày mai nhé.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 3490000, "budget_vnd": 3990000, "phone": "0901329595"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.

## VM-V1-EVAL-25

Khách `SYN-C13`, call 1; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi muốn tìm hiểu Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba ba, bảy năm một bốn.
8. **C:** Mình hẹn gọi lại ngày 16 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901337514"}`; GT ngày bổ sung: `{"callback_date": "2026-10-16"}`.

## VM-V1-EVAL-26

Khách `SYN-C13`, call 2; region dự kiến `south`.

1. **A:** Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?
2. **C:** Tôi quay lại hỏi Máy lọc không khí AirPure X.
3. **A:** Dạ sản phẩm Máy lọc không khí AirPure X có giá bốn triệu tám trăm chín mươi nghìn đồng tại ngày gọi này.
4. **C:** Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.
5. **A:** Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.
6. **C:** Ngân sách của tôi là năm triệu ba trăm chín mươi nghìn đồng.
7. **C:** Số điện thoại liên hệ của tôi là không chín không, một ba ba, bảy năm một bốn.
8. **C:** Mình hẹn gọi lại ngày 17 tháng 10 năm 2026.
9. **A:** Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.

GT tiền/SĐT: `{"price_vnd": 4890000, "budget_vnd": 5390000, "phone": "0901337514"}`; GT ngày bổ sung: `{"callback_date": "2026-10-17"}`.
