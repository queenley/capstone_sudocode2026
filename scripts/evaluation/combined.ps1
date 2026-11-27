# Kết hợp GapLoop + Reflection: KHÔNG học thêm. Chạy thiết kế 2x2 (Router, GapLoop, Reflection, Combined) với đúng
# hai phiên bản mà hai vòng đơn đã học và được duyệt, mỗi cấu hình k lần trên cùng một bộ đo (mẫu data/dev đối chứng,
# bộ chứng minh gap-loop, các bộ chứng minh của Reflection), rồi kết luận theo tiêu chí cố định. Quyết định 16/11/2026:
# bỏ vòng học riêng combined_1 (nó học ra kb v5 + skills v1, không chứng minh được cột nào).
#
#   .\scripts\evaluation\combined.ps1 -Name abl-1 -GapRound gaploop-5 -KbVersion 5 -ReflectionRound reflection-1 -SkillsVersion 2
#   .\scripts\evaluation\combined.ps1 -Name abl-1 -Step verdict      # chấm lại từ các run đã có, không gọi model
#
# Mỗi run là một lần gọi model thật (tốn phí): 4 cấu hình x k lần x (20 + 13 + bộ proof) kịch bản.
param(
    [ValidateSet("measure", "verdict")][string]$Step = "measure",
    [Parameter(Mandatory)][string]$Name,
    [string]$GapRound, [int]$KbVersion = -1,
    [string]$ReflectionRound, [int]$SkillsVersion = -1,
    [string[]]$Proof = @("budget"),
    [int]$Runs = 3
)
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$env:PYTHONPATH = "apps/ai-agent-service/src;packages/backend-common"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py = "apps\ai-agent-service\.venv\Scripts\python.exe"
$folder = "evaluation/runs/$Name"

if ($Step -eq "measure") {
    if (-not $GapRound -or -not $ReflectionRound -or $KbVersion -lt 1 -or $SkillsVersion -lt 1) {
        Write-Error "Cần -GapRound, -KbVersion, -ReflectionRound, -SkillsVersion: phiên bản hai vòng đơn đã học"; exit 2
    }
    $cmd = @("scripts/evaluation/ablation.py", "--name", $Name, "--gap-round", $GapRound, "--kb-version", $KbVersion,
             "--reflection-round", $ReflectionRound, "--skills-version", $SkillsVersion, "--runs", $Runs)
    foreach ($p in $Proof) { $cmd += @("--proof", $p) }
    New-Item -ItemType Directory -Force $folder | Out-Null
    & $py @cmd | Tee-Object "$folder/ablation.log"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $py scripts/evaluation/ablation_verdict.py --name $Name | Tee-Object "$folder/ablation-verdict.txt"
exit $LASTEXITCODE
