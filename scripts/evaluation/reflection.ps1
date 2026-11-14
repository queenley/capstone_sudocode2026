# Đánh giá Reflection: học từ mẫu data/dev (50% GEN, 50% ADV) + bộ gốc data/reflection/<Proof>, đo trước/sau,
# chỉ cấu hình full (không baseline). Thay đổi là câu trong skill, học khi 3+ khách cùng một bài học.
#
#   .\scripts\evaluation\reflection.ps1 -Step learn   -Name refl-dev-1 [-Proof budget,warranty,conduct]
#   .\scripts\evaluation\reflection.ps1 -Step measure -Name refl-dev-1 [-Proof ...]   # cùng -Proof như bước learn
#   .\scripts\evaluation\reflection.ps1 -Step verdict -Name refl-dev-1 [-Proof ...]
#
# Tiêu chí (scripts/evaluation/verdict.py):
#   bộ gốc    : ca mục tiêu đạt mọi lần chạy sau; ca đối chứng (forbidden_claims, F04-F06) không broken
#   mẫu dev   : broken 0, không HARM, TSR và hallucination không xấu đi quá mức dao động
#
# Mỗi kịch bản là một lần gọi model (tốn phí): frozen chạy -Runs lần mỗi bên. Thử nhỏ trước (-Learn 10 -Frozen 6).
param(
    [ValidateSet("learn", "measure", "verdict")][string]$Step = "learn",
    [Parameter(Mandatory)][string]$Name,
    [int]$Learn = 40, [int]$Frozen = 20, [double]$AdvShare = 0.5, [int]$Seed = 1, [int]$Runs = 2, [string[]]$Proof = @("budget")
)
& "$PSScriptRoot\_round.ps1" -Kind reflection @PSBoundParameters
exit $LASTEXITCODE
