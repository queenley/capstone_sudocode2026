# Đánh giá Gap Loop: học từ mẫu data/dev (50% GEN, 50% ADV) + bộ gốc data/gap-loop, đo trước/sau trên cả hai
# bộ frozen, chỉ cấu hình full (không baseline). Chỉ câu agent không trả lời được mới thành câu hỏi của Gap Loop.
#
#   .\scripts\evaluation\gaploop.ps1 -Step learn   -Name gap-dev-1   # chạy bộ learn, ghi câu chưa trả lời được
#   .\scripts\evaluation\gaploop.ps1 -Step answers -Name gap-dev-1   # tạo answers.json để điền/xóa
#   .\scripts\evaluation\gaploop.ps1 -Step measure -Name gap-dev-1   # đo trước/sau, lưu compare.txt, kết luận
#   .\scripts\evaluation\gaploop.ps1 -Step verdict -Name gap-dev-1   # chấm lại kết luận, không gọi model
#
# Tiêu chí (scripts/evaluation/verdict.py):
#   gap-loop  : 10 ca của 5 chủ đề đạt mọi lần chạy sau; 3 ca đối chứng (F11-F13) không broken
#   mẫu dev   : broken 0, không HARM, TSR và hallucination không xấu đi quá mức dao động
#
# Mỗi kịch bản là một lần gọi model (tốn phí): frozen chạy -Runs lần mỗi bên. Thử nhỏ trước (-Learn 10 -Frozen 6).
param(
    [ValidateSet("learn", "answers", "measure", "verdict")][string]$Step = "learn",
    [Parameter(Mandatory)][string]$Name,
    [int]$Learn = 40, [int]$Frozen = 20, [double]$AdvShare = 0.5, [int]$Seed = 1, [int]$Runs = 2
)
& "$PSScriptRoot\_round.ps1" -Kind gap @PSBoundParameters
exit $LASTEXITCODE
