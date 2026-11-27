# Hội thoại mẫu Claude đề xuất N

Claude đọc lại ngày 24/11/2026. Nhãn của các cuộc này vẫn đề xuất Y; chỉ hội thoại mẫu bị đề xuất N.
Cột "Đã ký" là `approve_conversation` sau lần ký ngày 24/11/2026: người duyệt đã ký Y cho cả 15 cuộc, nên các hội thoại này nằm trong `golden_manifest.json`.

| Dataset | Dòng CSV | Cuộc | Persona | Bộ persona | Đã ký | Hội thoại | Lý do |
|---|---|---|---|---|---|---|---|
| dev | 117 | SCN-ADV-0068__call_2 | khach_nhieu_thong_tin | Nâng cao | Y | [call_2.json](dev/conversations/scenarios_SCN-ADV-0068/call_2.json) | lượt agent lệch, trả lời trước khi khách hỏi; tự thêm 'anh ở TP Huế', '2-4 ngày' không có trong GT |
| dev | 124 | SCN-ADV-0073__call_2 | khach_hoi_gio_hang | Nâng cao | Y | [call_2.json](dev/conversations/scenarios_SCN-ADV-0073/call_2.json) | lượt agent lệch: nhắc ngân sách 5 triệu và COD trước khi khách nói; câu hỏi tổng tiền bị trả lời bằng câu về ngân sách |
| dev | 171 | SCN-ADV-0098__call_2 | khach_go_khong_dau | Nâng cao | Y | [call_2.json](dev/conversations/scenarios_SCN-ADV-0098/call_2.json) | báo phí ship 35.000đ rồi lại chốt tổng 119.000đ (tự mâu thuẫn); đã đánh dấu J02 |
| dev | 186 | SCN-ADV-0107__call_2 | khach_hoi_gio_hang | Nâng cao | Y | [call_2.json](dev/conversations/scenarios_SCN-ADV-0107/call_2.json) | đọc lại địa chỉ Cầu Giấy trước khi khách nói; tạo đơn mà khách chưa xác nhận bản đọc lại |
| dev | 343 | SCN-GEN-0035__call_2 | khach_co_don_chua_co_lich_su | BTC | Y | [call_2.json](dev/conversations/scenarios_SCN-GEN-0035/call_2.json) | lời chào nói nhầm sản phẩm (RunLite 2 Pro) trong khi đơn OD900202 là giày trekking HikePro |
| dev | 416 | SCN-GEN-0069__call_2 | khach_co_don_chua_co_lich_su | BTC | Y | [call_2.json](dev/conversations/scenarios_SCN-GEN-0069/call_2.json) | lượt agent lệch: nói Long Biên trước khi khách nói |
| dev | 482 | SCN-GEN-0099__call_2 | khach_mua_nhieu_mon | BTC | Y | [call_2.json](dev/conversations/scenarios_SCN-GEN-0099/call_2.json) | nói tổng 11.160.000đ 'vẫn nằm trong' ngân sách 8,5 triệu: sai |
| dev | 486 | SCN-GEN-0101__call_2 | khach_co_don_chua_co_lich_su | BTC | Y | [call_2.json](dev/conversations/scenarios_SCN-GEN-0101/call_2.json) | lượt agent lệch: nói Quận 7 và 'không ảnh hưởng thời gian giao' trước khi khách nói |
| dev | 607 | SCN-GEN-0158__call_1 | khach_da_mua_doi_size | BTC | Y | [call_1.json](dev/conversations/scenarios_SCN-GEN-0158/call_1.json) | lượt agent lệch: nói Hải Châu/COD và hỏi 'xem trên website' trước khi khách nói |
| dev | 628 | SCN-GEN-0167__call_2 | khach_mua_nhieu_mon | BTC | Y | [call_2.json](dev/conversations/scenarios_SCN-GEN-0167/call_2.json) | đọc lại địa chỉ Nha Trang trước khi khách cho địa chỉ; thứ tự lượt lệch |
| dev | 677 | SCN-GEN-0190__call_1 | khach_da_mua_doi_size | BTC | Y | [call_1.json](dev/conversations/scenarios_SCN-GEN-0190/call_1.json) | đọc lại Long Biên + chuyển khoản trước khi khách nói, rồi hỏi lại chính các thông tin đó |
| dev | 785 | SCN-GEN-0240__call_1 | khach_da_mua_doi_size | BTC | Y | [call_1.json](dev/conversations/scenarios_SCN-GEN-0240/call_1.json) | tạo đơn mà không đọc lại đơn cho khách xác nhận; thêm 'dòng mới nhất' không có nguồn |
| test | 7 | SCN-ADV-0003__call_2 | khach_go_khong_dau | Nâng cao | Y | [call_2.json](test/conversations/scenarios_SCN-ADV-0003/call_2.json) | tạo đơn trước khi khách cho thanh toán/địa chỉ; hai lượt khách cuối không có agent trả lời |
| test | 42 | SCN-ADV-0024__call_1 | khach_mua_lai_khuyen_mai_mot_lan | Nâng cao | Y | [call_1.json](test/conversations/scenarios_SCN-ADV-0024/call_1.json) | lên đơn khi chưa đọc lại đơn; lượt khách cuối (giá khuyến mãi lần trước) không được trả lời |
| test | 157 | SCN-GEN-0033__call_2 | khach_mua_nhieu_mon | BTC | Y | [call_2.json](test/conversations/scenarios_SCN-GEN-0033/call_2.json) | tự điền địa chỉ Thủ Đức mà khách chưa nói; không đọc lại đơn trước khi tạo; đã đánh dấu J02 |

## Persona và số cuộc gọi

Đếm từ `review_sheet.csv` sau lần ký ngày 24/11/2026. "Hội thoại ký N" là số cuộc có `approve_conversation = N` (nhãn vẫn Y, chỉ hội thoại mẫu không vào golden). BTC = 16 persona ban đầu của BTC (`evaluation/data-generation/config/personas.yaml`); Nâng cao = persona của nhóm (`evaluation/data-generation/config/personas_advanced.yaml`).

### Persona BTC (ban đầu) (16 persona)

| Persona | dev: số cuộc | dev: hội thoại ký N | test: số cuộc | test: hội thoại ký N |
|---|---|---|---|---|
| khach_do_du_hoi_nguoi_nha | 42 | 2 | 6 | 0 |
| khach_so_gia | 38 | 24 | 6 | 4 |
| khach_da_mua_doi_size | 30 | 13 | 6 | 2 |
| khach_hoi_nhieu_khong_mua | 38 | 1 | 6 | 1 |
| khach_goi_lan_3_het_kien_nhan | 48 | 3 | 12 | 1 |
| khach_da_kenh_fb_hotline | 30 | 0 | 6 | 0 |
| khach_ngoai_pham_vi_chuyen_may | 30 | 30 | 6 | 6 |
| khach_hoi_ngoai_tai_lieu | 30 | 5 | 6 | 0 |
| khach_da_kenh_mau_thuan | 45 | 5 | 9 | 0 |
| hai_nguoi_chung_sdt | 42 | 40 | 10 | 10 |
| khach_quay_lai_sau_8_thang | 32 | 5 | 6 | 0 |
| khach_mua_nhieu_mon | 30 | 0 | 6 | 0 |
| khach_asr_nhiem_tool_timeout | 30 | 2 | 6 | 0 |
| khach_co_don_chua_co_lich_su | 30 | 5 | 6 | 0 |
| khach_cap_nhat_thong_tin | 30 | 10 | 6 | 2 |
| khach_yeu_cau_xoa_du_lieu | 20 | 18 | 4 | 4 |
| **Tổng** | **545** | **163** | **107** | **30** |

### Persona nâng cao (33 persona)

| Persona | dev: số cuộc | dev: hội thoại ký N | test: số cuộc | test: hội thoại ký N |
|---|---|---|---|---|
| khach_hoi_san_pham_khong_ban | 12 | 0 | 4 | 0 |
| khach_hoi_ngoai_chu_de | 12 | 0 | 4 | 0 |
| khach_go_khong_dau | 12 | 0 | 4 | 0 |
| khach_go_sai_chinh_ta | 12 | 0 | 4 | 0 |
| khach_hoi_ky_san_pham | 10 | 0 | 4 | 0 |
| khach_can_tu_van_nhieu | 12 | 0 | 4 | 0 |
| khach_nhieu_thong_tin | 12 | 1 | 4 | 0 |
| khach_bao_hanh_trong_han | 5 | 0 | 2 | 0 |
| khach_bao_hanh_het_han | 5 | 0 | 2 | 0 |
| khach_tra_hang_trong_han | 12 | 0 | 4 | 0 |
| khach_tra_hang_qua_han | 5 | 0 | 2 | 0 |
| khach_hoi_gio_hang | 12 | 5 | 4 | 2 |
| khach_mua_phu_kien_thay_the | 5 | 0 | 2 | 0 |
| khach_hoi_bao_hanh_mo_rong | 12 | 0 | 4 | 0 |
| khach_hoi_tra_gop | 12 | 0 | 4 | 0 |
| khach_khieu_nai_giao_cham | 5 | 0 | 2 | 0 |
| khach_chuyen_giua_nguoi_va_ai | 13 | 13 | 5 | 5 |
| khach_chua_co_danh_tinh | 12 | 0 | 4 | 0 |
| khach_hoi_thong_tin_nguoi_khac | 9 | 9 | 1 | 1 |
| khach_prompt_injection | 9 | 9 | 2 | 2 |
| khach_lon_tuoi | 10 | 0 | 2 | 0 |
| khach_hoi_khuyen_mai_sap_toi | 6 | 0 | 2 | 0 |
| khach_doi_cong_don_khuyen_mai | 2 | 0 | 1 | 0 |
| khach_mua_lai_khuyen_mai_mot_lan | 4 | 0 | 2 | 0 |
| khach_hoi_freeship_theo_vung | 4 | 0 | 1 | 0 |
| khach_doi_qua_thanh_tien | 4 | 0 | 2 | 0 |
| khach_thanh_toan_vi_dien_tu | 6 | 0 | 2 | 0 |
| khach_mua_so_luong | 3 | 0 | 1 | 1 |
| khach_goi_so_moi_xung_khach_cu | 3 | 2 | 1 | 1 |
| khach_tach_don_cod | 6 | 3 | 2 | 0 |
| khach_hoi_may_thu_hai | 4 | 1 | 1 | 0 |
| khach_mua_nhieu_may_loc | 6 | 4 | 1 | 1 |
| khach_chot_don_doc_lai | 6 | 1 | 2 | 0 |
| **Tổng** | **262** | **48** | **86** | **13** |
