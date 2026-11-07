// HandoffBrief.escalation_reason (data/btc/schemas/handoff_brief.schema.json), in words.
const REASON: Record<string, string> = {
  cau_hoi_y_te: "Câu hỏi y tế",
  ngoai_pham_vi_tai_lieu: "Ngoài phạm vi tài liệu",
  khach_yeu_cau_gap_nguoi: "Khách muốn gặp nhân viên",
  khieu_nai_nghiem_trong: "Khiếu nại nghiêm trọng",
  loi_he_thong: "Lỗi hệ thống",
  khach_mat_kien_nhan: "Khách mất kiên nhẫn",
  khac: "Lý do khác",
};

export function reasonLabel(reason: string) {
  return REASON[reason] || reason;
}
