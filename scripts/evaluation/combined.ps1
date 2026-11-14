# Đánh giá Combined: Gap Loop và Reflection trong cùng một vòng. Học từ mẫu data/dev (50% GEN, 50% ADV) + data/gap-loop
# + data/reflection/<Proof>; đo trước/sau trên mọi bộ frozen, chỉ cấu hình full (không baseline).
#
#   .\scripts\evaluation\combined.ps1 -Step learn   -Name comb-dev-1 [-Proof budget]
#   .\scripts\evaluation\combined.ps1 -Step answers -Name comb-dev-1
#   .\scripts\evaluation\combined.ps1 -Step measure -Name comb-dev-1 [-Proof ...]   # cùng -Proof như bước learn
#   .\scripts\evaluation\combined.ps1 -Step verdict -Name comb-dev-1 [-Proof ...]
#
# Tiêu chí: như gaploop.ps1 cho gap-loop, như reflection.ps1 cho bộ Reflection, và mẫu dev: broken 0, không HARM,
# TSR và hallucination không xấu đi quá mức dao động.
#
# Mỗi kịch bản là một lần gọi model (tốn phí): frozen chạy -Runs lần mỗi bên. Thử nhỏ trước (-Learn 10 -Frozen 6).
param(
    [ValidateSet("learn", "answers", "measure", "verdict")][string]$Step = "learn",
    [Parameter(Mandatory)][string]$Name,
    [int]$Learn = 40, [int]$Frozen = 20, [double]$AdvShare = 0.5, [int]$Seed = 1, [int]$Runs = 2, [string[]]$Proof = @("budget")
)
& "$PSScriptRoot\_round.ps1" -Kind combined @PSBoundParameters
exit $LASTEXITCODE
