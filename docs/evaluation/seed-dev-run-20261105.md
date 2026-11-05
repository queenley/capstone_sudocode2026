# seed-dev, 05/11/2026: kết quả, lỗi và độ tin của bộ test

Mục đích: sửa hệ thống **đúng chỗ** hôm nay, không sửa theo nhãn sai. Mọi số dưới đây là **chẩn đoán**: nhãn seed-dev chưa có người duyệt (`review/golden_manifest.json` chưa có), bộ chấm là `reference_eval.py` của main, extractor `product-extractor-v8`.

## 1. Kết luận ngắn

- Đã đo **41 kịch bản / 80 cuộc gọi** (28 trong 50 case dự kiến + 13 case phủ loại). Chỉ **3/41 kịch bản đạt TSR** ở cấu hình `full`.
- Lỗi **không phân bố đều**: 4 nguyên nhân đầu (#1–#4 ở mục 5) chiếm **40/58 cuộc trượt**; trong đó 9 cuộc là lỗi bộ test, không phải hệ thống.
- **Bộ test đúng về số liệu** (giá, trạng thái đơn, slot nhớ) nhưng **sai ở lời khách và chưa ai duyệt nhãn hành vi**. 35/80 cuộc đã chạy có nhãn nghi vấn. Không sửa hệ thống dựa trên cuộc nhãn nghi vấn.
- **Không chạy toàn bộ 398 kịch bản trước khi sửa**: trace sẽ lỗi thời ngay khi agent đổi; ước tính $43 và 9 giờ.

## 2. Đã chạy gì

| Run (`evaluation/runs/…`) | Kịch bản | Cấu hình | Nhãn extractor | Trạng thái | Ghi chú |
|---|---|---|---|---|---|
| `20261105-seeddev-50` | 27 xong + `SCN-GEN-0069` dở | chỉ `full` | chưa | INCOMPLETE | Dừng vì ledger cạn do khoản đặt trước treo (đã sửa). TSR chấm offline bằng `check_call` của BTC; tiêu chí dựa trên claim/câu hỏi chưa chấm được nên số này **lạc quan** |
| `20261105-fixcheck` | `SCN-ADV-0008`, `SCN-ADV-0014` | `full` + `baseline_no_memory` | có | COMPLETE | Kiểm bản sửa ledger: 0 khoản treo |
| `20261105-cover14` | 14 kịch bản phủ loại (chỉ `SCN-GEN-0163` thuộc 50 case) | `full` + `baseline_no_memory` | có | COMPLETE | Có `blocked_draft_texts` (nội dung bản nháp bị chặn) |
| `20261105-smoke-2` | `SCN-GEN-0051` bộ v4 cũ | cả hai | có | COMPLETE | Bộ v4 đã xoá; chỉ dùng cho lỗi "shipping" |

**50 case dự kiến:** đo được 28 (27 + 0163), **22 chưa chạy**: 0069 (dở), 0077, 0103, 0124, 0129, 0140, 0143, 0144, 0167, 0181, 0190, 0191, 0193, 0194, 0201, 0209, 0217, 0218, 0232, 0241, 0244, 0250 (đều `SCN-GEN-`).

**Chi phí thật** (ước tính của ledger, không phải hóa đơn): khoảng $1.29 (run 50) + $2.87 (fixcheck + cover14) ≈ **$4.2**. Ledger `20261105-key3-budget.sqlite` còn khoảng $5.6.

## 3. Bảng điểm (chỉ run có nhãn)

`cover14` (14 kịch bản):

| Chỉ số | Baseline | Hệ thống |
|---|---|---|
| RQR (%) | 15.4 | 11.4 |
| CCR (%) | 8.9 | 26.6 |
| TSR (%) | 7.1 | 7.1 |
| HR giá&KM (%) | 33.3 | 38.3 |
| TSR ca khó (%) | | 8.3 |
| Vi phạm guardrail | 1 | 1 (over-escalation, `SCN-GEN-0163`) |
| Latency p50 / p95 (ms) | | 2.625 / 17.731 |

Trên 32 cuộc có nhãn (fixcheck + cover14): `full` đạt 8, `baseline` đạt 9. **Bộ nhớ chưa giúp TSR** vì cả hai cấu hình cùng vấp các lỗi dưới đây; bộ nhớ có tác dụng ở CCR (26.6 so với 8.9) và RQR.

Theo tool kỳ vọng (80 cuộc, `full`): `order.create` **0/26**, `schedule.callback` 0/7, `order.status` 0/5, `order.update` 0/4, `handoff.transfer` 1/3, cuộc không cần tool 21/34.

## 4. Bộ test seed-dev đáng tin tới đâu

Kiểm offline trên toàn bộ 400 kịch bản, không gọi model:

| Phép kiểm | Kết quả | Kết luận |
|---|---|---|
| Giá `order.create` tính lại bằng mock BTC | 233/235 khớp; 2 lệch là khuyến mãi dùng một lần (đúng) | **Tin được** |
| `order_status`, `tracking` so với CRM | 37/37, 20/20 | **Tin được** |
| `must_carry_over` có được cung cấp trước | 2.251/2.251 | **Tin được** |
| Cụm bắt buộc có số so với chính sách/catalog | 327/333; 6 là tổng giỏ tự tính | Tin được |
| Lời khách so với hội thoại mẫu | **74 cuộc `order.create` bị cắt câu xác nhận cuối** ("Đúng rồi em, lên đơn giúp chị nhé") | **Sai** |
| Oracle "hoàn hảo" | Trace oracle dựng từ chính nhãn, có câu chèn để khớp cụm (ví dụ "Dạ gọi xác nhận ạ") và tạo đơn không đọc lại | **Không chứng minh được nhãn đúng** |
| Duyệt tay | 243 mục / 155 kịch bản cần duyệt, cột `approve` trống hết; ~30 mục `J02_no_fabrication` | **Chưa duyệt** |
| Khoá `success_if` lạ | `say_at_most` ở 3 cuộc, bộ chấm BTC bỏ qua | Tiêu chí không được chấm |
| Ngày phiên cũ | `SCN-GEN-0080`, `SCN-GEN-0146` có phiên sau ngày gọi | Runner từ chối, đã loại |
| Cụm bắt buộc chỉ có dạng số | 143 cuộc | Không sai, nhưng chấm theo hình thức chữ |

**Quy tắc dùng bộ test hôm nay:** một cuộc là *nhãn sạch* khi không bị cắt câu xác nhận, không nằm trong danh sách duyệt tay, không dùng `say_at_most`. Trong 80 cuộc đã chạy: **45 sạch, 35 nghi vấn**. Chỉ sửa hệ thống khi lỗi **lặp lại ở ≥ 2 cuộc nhãn sạch** và có **bằng chứng ngoài nhãn** (chính sách, mock, bản nháp bị chặn).

## 5. Lỗi gộp, mức độ và chỗ sửa

Số cuộc: tổng cuộc trượt vì nguyên nhân đó / trong đó nhãn sạch. Một cuộc chỉ tính một nguyên nhân chính.

| # | Nguyên nhân | Mức | Cuộc (sạch) | Bằng chứng | Sửa ở đâu | Loại |
|---|---|---|---|---|---|---|
| 1 | **Luật xác nhận mua quá chặt** so với PB-09 | **Cao** | 12 (7) | `CONFIRMATION_REQUIRED` 13 lần; `YES.fullmatch` chỉ nhận câu "có" ngắn ngay sau câu đọc lại; chỉ 12/235 cuộc trong bộ test qua được | `components/guardrails/purchase.py` | Hệ thống (cần duyệt) |
| 2 | **Câu xác nhận của khách bị cắt** khi xuất kịch bản | **Cao** | 9 (0) | 74 cuộc trong 400; hội thoại mẫu có câu đó, kịch bản không | revision mới của bộ test theo `ground-truth-review/SKILL.md` | **Bộ test**, không sửa hệ thống |
| 3 | Agent thiếu/sai tool (`schedule.callback` sai tham số, `order.update`, `order.status`) | **Cao** | 11 (7) | Có gọi nhưng `args_match` không khớp; đặt lịch năm 2024; chọn tuần sai | prompt/logic advisor, xử lý ngày | Hệ thống |
| 4 | **Tool bị precondition chặn** | TB | 8 (5) | handoff "chưa cần chuyển máy" (16 lần); sau `handoff.transfer` thành công cuộc gọi chuyển sang **copilot** và agent im lặng vì eval không bật `HANDOFF_AUTO_ACCEPT`; `pricing.get_quote` "mã sản phẩm chưa xác nhận" (13); `order.status` "xác nhận danh tính" (4) | guard tool, cấu hình harness eval | Hệ thống + cấu hình (cần duyệt) |
| 5 | **Guard "chuyển máy" bắt nhầm "vận chuyển … máy lọc"** | **Cao** | 5 (4) | Bản nháp "em miễn phí vận chuyển cho hai máy lọc không khí" bị chặn; regex `TRANSFER_PROMISE` khớp; lý do chặn nhiều nhất (39 lần) | `components/guardrails/hard.py` | Hệ thống (an toàn để sửa) |
| 6 | Agent không chốt đơn, không gọi `order.create` | TB | 5 (3) | Không bị chặn, chỉ hỏi lại | prompt chốt đơn | Hệ thống |
| 7 | Có tri thức/kết quả tool nhưng không nói cụm bắt buộc | TB | 5 (3) | `BH-03` (7–15 ngày), `BH-05` (8%) đã được tìm thấy; mã "shipping" thay vì "đang giao" | prompt, chuẩn hoá trạng thái | Hệ thống |
| 8 | Guard số tiền chặn giá đúng | TB | 2 (1) | Chặn "giảm 50% máy thứ hai", giá combo trước khi có tool; agent lách bằng giá viết chữ | `hard.py` | Hệ thống (cần duyệt) |
| 9 | Guard trạng thái đơn chặn nhầm khi khách có nhiều đơn | TB | 1 (1) | Tái hiện bằng mô phỏng; còn chặn thông tin đơn từ brief | `hard.py` `_order_state` | Hệ thống |
| 10 | Guard "thời hạn" bắt nhầm giờ hẹn ("5 giờ 30") | Thấp | — | `DURATION` khớp giờ đồng hồ | `hard.py` | Hệ thống (an toàn để sửa) |

**HR cao không phải chủ yếu do bịa số.** Mọi giá sai đều có trong kết quả tool, nhưng là giá của **sản phẩm khác**. `cover14`, 18 claim giá/KM sai (HR giá&KM 38.3%):

| Nguồn | Claim | Loại |
|---|---|---|
| Khách không nêu tên mẫu, agent chọn mẫu khác với mẫu trong lịch sử (Joie Pact thay Combi ở 0036: 7; RunLite 1 thay RunLite 2 Pro ở 0024: 2) | 9 | Lỗi agent: không dùng lịch sử để chọn sản phẩm |
| Báo giá combo thay cho máy lẻ (0078) | 4 | Lỗi agent |
| Size 43 báo giá size thường (0008) | 1 | Lỗi agent |
| Extractor gán phụ phí 50.000đ thành `price_vnd` (0008) | 1 | **Lỗi dụng cụ đo** |
| `promo_active` (0031, 0022, 0171) | 3 | Chưa phân định |

HR tổng (33.3%, 27/81) còn có `total_vnd` sai 4 (cộng giá niêm yết, thiếu món), `freeship` 4 (**extractor** gán "miễn phí thu hộ COD" thành miễn phí vận chuyển), `return_days` 1.

Lỗi ngoài agent:

| # | Lỗi | Trạng thái |
|---|---|---|
| E1 | Ledger giữ trọn $0.42 cho mỗi stream bị guard cắt | **Đã sửa** (`settle_abandoned`), kiểm: 0 khoản treo |
| E2 | Runner không nhận kênh `fb` trong `seed_history` | **Đã sửa** (`CRM_SESSION_CHANNELS`) |
| E3 | Diagnostics không có nội dung bản nháp bị chặn | **Đã sửa** (`blocked_draft_texts`) |
| E4 | Diagnostics chỉ lưu ID chunk tri thức | Chưa sửa |
| E5 | `_order_date` chọn đơn mới nhất thay vì đơn khách hỏi | Chưa sửa |
| E6 | Eval không bật `HANDOFF_AUTO_ACCEPT`: sau khi chuyển máy, agent im lặng hết cuộc | Chưa sửa, cần quyết |
| E7 | Latency p95 17,7 giây | Chưa điều tra |
| E8 | Tài liệu trỏ bộ v4 đã xoá | **Đã sửa** |

## 6. Thứ tự sửa hôm nay (tránh làm dơ hệ thống)

1. **Sửa an toàn, có test, không đổi chính sách:** #5 (regex chuyển máy), #10 (regex thời hạn), E5, E4, chuẩn hoá trạng thái đơn sang tiếng Việt (#7 phần "shipping").
2. **Cần bạn duyệt phương án trước:** #1 luật xác nhận (nhận đồng ý trong câu dài, có kiểm phủ định, vẫn đọc lại một lần theo PB-09), #4/E6 handoff trong eval, #8 và #9 guard tiền/đơn.
3. **Sửa agent:** #3, #6, #7, chọn đúng sản phẩm/biến thể và tổng giỏ (HR).
4. **Bộ test, làm riêng và báo riêng:** #2 khôi phục câu xác nhận thành revision mới; đánh dấu các cuộc `J02_no_fabrication`.
5. **Extractor, làm riêng:** sửa `freeship`/phụ phí thành version mới, so bằng `--relabel` trên cùng replies.
6. **Đo lại:** chạy lại 41 kịch bản này (cùng ledger, khoảng $5) và 22 case chưa chạy của bộ 50 nếu còn ngân sách. So số chỉ trên cuộc nhãn sạch.

## 7. Phụ lục: từng kịch bản

"Full đạt/cuộc" là số cuộc đạt `success_if` trên tổng số cuộc có tiêu chí. Run 50-case chưa có baseline.

| Kịch bản | Run | Mức | Ca khó | Full đạt/cuộc | Baseline đạt/cuộc | Nhãn | Nguyên nhân chính |
|---|---|---|---|---|---|---|---|
| SCN-ADV-0001 | 50-case (full, chưa nhãn) | M2 |  | 1/2 | — | sạch | AGENT: thiếu/sai tool call |
| SCN-ADV-0008 | fixcheck (full+baseline) | M2 |  | 0/1 | 1/1 | sạch | GUARD: chặn "trạng thái đơn" |
| SCN-ADV-0013 | 50-case (full, chưa nhãn) | M2 |  | 0/1 | — | nghi vấn | DATA: câu xác nhận của khách bị cắt |
| SCN-ADV-0014 | fixcheck (full+baseline) | M2 |  | 0/2 | 1/2 | nghi vấn | DATA: câu xác nhận của khách bị cắt; GUARD: chặn nhầm "chuyển máy" (vận chuyển) |
| SCN-ADV-0017 | 50-case (full, chưa nhãn) | M2 | chuyen_nguoi_roi_quay_lai_ai | 1/3 | — | nghi vấn | GUARD: tool bị chặn bởi precondition; XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0020 | 50-case (full, chưa nhãn) | M2 | prompt_injection | 0/2 | — | nghi vấn | AGENT: thiếu/sai tool call; XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0031 | cover-14 (full+baseline) | M2 |  | 0/1 | 0/1 | nghi vấn | GUARD: chặn số tiền |
| SCN-ADV-0048 | 50-case (full, chưa nhãn) | M2 |  | 0/1 | — | sạch | GUARD: tool bị chặn bởi precondition |
| SCN-ADV-0050 | 50-case (full, chưa nhãn) | M2 |  | 1/2 | — | nghi vấn | DATA: câu xác nhận của khách bị cắt |
| SCN-ADV-0053 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | sạch | AGENT: không chốt/không gọi order.create; GUARD: tool bị chặn bởi precondition |
| SCN-ADV-0070 | 50-case (full, chưa nhãn) | M2 |  | 0/1 | — | sạch | AGENT: có/không có tri thức nhưng không nói cụm bắt buộc |
| SCN-ADV-0075 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | nghi vấn | DATA: câu xác nhận của khách bị cắt; GUARD: chặn nhầm "chuyển máy" (vận chuyển) |
| SCN-ADV-0078 | cover-14 (full+baseline) | M2 | y_te_chuyen_nguoi_roi_ai_chot | 2/3 | 1/3 | nghi vấn | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0087 | 50-case (full, chưa nhãn) | M2 |  | 1/2 | — | sạch | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0089 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | sạch | AGENT: không chốt/không gọi order.create; AGENT: thiếu/sai tool call |
| SCN-ADV-0095 | 50-case (full, chưa nhãn) | M2 | prompt_injection | 0/1 | — | nghi vấn | AGENT: thiếu/sai tool call |
| SCN-ADV-0098 | 50-case (full, chưa nhãn) | M2 |  | 1/2 | — | nghi vấn | DATA: câu xác nhận của khách bị cắt |
| SCN-ADV-0107 | cover-14 (full+baseline) | M2 |  | 0/2 | 0/2 | nghi vấn | GUARD: chặn nhầm "chuyển máy" (vận chuyển); XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0111 | 50-case (full, chưa nhãn) | M2 |  | 0/1 | — | sạch | AGENT: có/không có tri thức nhưng không nói cụm bắt buộc |
| SCN-ADV-0124 | 50-case (full, chưa nhãn) | M2 |  | 1/1 | — | nghi vấn | đạt |
| SCN-ADV-0129 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | sạch | AGENT: thiếu/sai tool call |
| SCN-ADV-0137 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | sạch | GUARD: tool bị chặn bởi precondition; XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-ADV-0141 | 50-case (full, chưa nhãn) | M2 |  | 0/2 | — | sạch | AGENT: không chốt/không gọi order.create; GUARD: chặn nhầm "chuyển máy" (vận chuyển) |
| SCN-ADV-0144 | cover-14 (full+baseline) | M2 | khieu_nai_chuyen_nguoi_roi_ai_theo_doi | 0/2 | 0/2 | nghi vấn | AGENT: có/không có tri thức nhưng không nói cụm bắt buộc; GUARD: tool bị chặn bởi precondition |
| SCN-GEN-0001 | cover-14 (full+baseline) | M2 | quay_lai_8_thang_ttl_trade_in | 0/2 | 0/2 | nghi vấn | AGENT: thiếu/sai tool call; DATA: câu xác nhận của khách bị cắt |
| SCN-GEN-0008 | cover-14 (full+baseline) | M1 | km_loai_tru_size | 0/2 | 0/2 | nghi vấn | AGENT: không chốt/không gọi order.create; GUARD: tool bị chặn bởi precondition |
| SCN-GEN-0010 | 50-case (full, chưa nhãn) | M2 | het_hang_luc_khach_quyet | 1/3 | — | sạch | AGENT: có/không có tri thức nhưng không nói cụm bắt buộc; GUARD: chặn số tiền |
| SCN-GEN-0011 | cover-14 (full+baseline) | M2 | teencode_da_kenh | 1/2 | 1/2 | sạch | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0014 | 50-case (full, chưa nhãn) | M2 | ba_kenh_bao_gia_lech | 2/3 | — | sạch | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0015 | 50-case (full, chưa nhãn) | M2 | chung_sdt_memory_poisoning | 0/2 | — | nghi vấn | AGENT: không chốt/không gọi order.create; AGENT: thiếu/sai tool call |
| SCN-GEN-0017 | cover-14 (full+baseline) | M2 | 16_luot_4_san_pham_vuot_cod | 1/2 | 1/2 | sạch | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0018 | cover-14 (full+baseline) | M2 | asr_loi_tool_timeout | 2/2 | 2/2 | sạch | đạt |
| SCN-GEN-0022 | cover-14 (full+baseline) | M1 | hen_goi_lai_ngay_nghi | 0/2 | 0/2 | nghi vấn | DATA: câu xác nhận của khách bị cắt; GUARD: tool bị chặn bởi precondition |
| SCN-GEN-0023 | 50-case (full, chưa nhãn) | M1 | ep_gia_do_gia_nhap | 2/2 | — | nghi vấn | đạt |
| SCN-GEN-0024 | cover-14 (full+baseline) | M1 | doi_san_pham_hoan_chenh_lech | 0/2 | 0/2 | nghi vấn | AGENT: thiếu/sai tool call; XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0036 | cover-14 (full+baseline) | M2 | ba_phien_doi_thong_tin | 1/3 | 1/3 | nghi vấn | AGENT: thiếu/sai tool call; DATA: câu xác nhận của khách bị cắt |
| SCN-GEN-0039 | 50-case (full, chưa nhãn) | M1 | doi_khuyen_mai_het_han | 1/2 | — | nghi vấn | DATA: câu xác nhận của khách bị cắt |
| SCN-GEN-0060 | 50-case (full, chưa nhãn) | M2 | doi_khuyen_mai_het_han | 1/3 | — | nghi vấn | AGENT: thiếu/sai tool call; XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0066 | 50-case (full, chưa nhãn) | M2 | doi_khuyen_mai_het_han | 1/2 | — | nghi vấn | XUNG ĐỘT: luật xác nhận mua quá chặt |
| SCN-GEN-0163 | cover-14 (full+baseline) | M2 | phien_ban_chinh_sach_cu | 0/2 | 0/2 | nghi vấn | AGENT: có/không có tri thức nhưng không nói cụm bắt buộc; GUARD: chặn nhầm "chuyển máy" (vận chuyển) |
| SCN-GEN-0171 | cover-14 (full+baseline) | M2 | hoi_ai_va_xoa_du_lieu | 1/2 | 1/2 | nghi vấn | GUARD: tool bị chặn bởi precondition |
