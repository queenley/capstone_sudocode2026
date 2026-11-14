# Phần chung của gaploop.ps1, reflection.ps1, combined.ps1: một vòng cải tiến học và đo trên mẫu data/dev
# (trộn GEN/ADV) cùng các bộ chứng minh gốc, chỉ cấu hình full (không baseline), rồi kết luận theo tiêu chí cố định.
# Không gọi trực tiếp: dùng một trong ba script trên.
param(
    [Parameter(Mandatory)][ValidateSet("gap", "reflection", "combined")][string]$Kind,
    [ValidateSet("learn", "answers", "measure", "verdict")][string]$Step = "learn",
    [Parameter(Mandatory)][string]$Name,
    [int]$Learn = 40,           # số kịch bản học lấy từ data/dev
    [int]$Frozen = 20,          # số kịch bản đo trước/sau lấy từ data/dev
    [double]$AdvShare = 0.5,    # tỉ lệ ADV: 0.5 = 50% general, 50% advance
    [int]$Seed = 1,             # cùng seed thì cùng mẫu
    [int]$Runs = 2,             # số lần chạy frozen mỗi bên (trước/sau) để tách dao động
    [string[]]$Proof = @()      # bộ chứng minh gốc của Reflection: budget, warranty, conduct
)

Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$env:PYTHONPATH = "apps/ai-agent-service/src;packages/backend-common"
$env:PYTHONIOENCODING = "utf-8"   # output chuyển qua Tee-Object: không có dòng này Python dùng cp1252 và lỗi chữ Việt
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py = "apps\ai-agent-service\.venv\Scripts\python.exe"
$sets = "data/.build/rounds/$Name"
$folder = "evaluation/runs/$Name"

if ($Name -in @("gap-loop", "budget", "warranty", "conduct")) { Write-Error "-Name trùng tên một bộ chứng minh"; exit 2 }

function Run { & $py @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }  # một bước lỗi thì dừng

# Bộ chứng minh gốc của từng loại vòng.
$gapProof = $Kind -in @("gap", "combined")
if ($Kind -eq "gap") { $Proof = @() }
elseif ($Proof.Count -eq 0) { $Proof = @("budget") }
$proofArgs = @()
if ($gapProof) {
    $proofArgs += @("--learn", "data/gap-loop/learn/scenarios", "--frozen", "data/gap-loop/frozen/scenarios",
                    "--frozen-ids", "data/gap-loop/frozen.json")
}
foreach ($p in $Proof) {
    $proofArgs += @("--learn", "data/reflection/$p/learn/scenarios", "--frozen", "data/reflection/$p/frozen/scenarios",
                    "--frozen-ids", "data/reflection/$p/frozen.json")
}
$round = @("-m", "ai_agent_service.pipeline.improve", "round", "--name", $Name,
           "--learn", "$sets/learn/scenarios", "--frozen", "$sets/frozen/scenarios", "--frozen-ids", "$sets/frozen.json") + $proofArgs
$verdictArgs = @("scripts/evaluation/verdict.py", "--name", $Name)
if ($gapProof) { $verdictArgs += @("--proof", "gap-loop") }
foreach ($p in $Proof) { $verdictArgs += @("--proof", $p) }

function Assert-FromDev {
    # Mỗi kịch bản trong mẫu phải là bản y hệt một kịch bản của data/dev/scenarios.
    foreach ($part in @("learn", "frozen")) {
        foreach ($f in Get-ChildItem "$sets/$part/scenarios" -Filter *.json) {
            $source = "data/dev/scenarios/$($f.Name)"
            if (-not (Test-Path $source) -or (Get-FileHash $f.FullName).Hash -ne (Get-FileHash $source).Hash) {
                Write-Error "$($f.Name) trong $sets/$part không lấy từ data/dev/scenarios"; exit 2
            }
        }
    }
    Write-Host "Mẫu lấy đúng từ data/dev/scenarios."
}

switch ($Step) {
    "learn" {
        if (-not (Test-Path "$sets/frozen.json")) {
            Run scripts/improvements/make_sets.py --name $Name --learn $Learn --frozen $Frozen --adv-share $AdvShare --seed $Seed
        } else { Write-Host "Dùng lại mẫu đã tạo ở $sets (cùng -Name)." }
        Assert-FromDev
        Run @round   # không --scripted: dừng sau bộ learn, chưa tốn phí cho bộ frozen
        if ($Kind -eq "reflection") { $next = "measure" } else { $next = "answers" }
        Write-Host "`nTiếp theo: -Step $next -Name $Name"
    }
    "answers" {
        if ($Kind -eq "reflection") { Write-Error "Reflection không cần câu trả lời: dùng -Step measure"; exit 2 }
        Run scripts/improvements/gap_answers_template.py --name $Name --include data/gap-loop/answers.json
        Write-Host "Điền 'answer' trong $sets/answers.json; XÓA câu để trống, câu tài liệu ghi 'không có thông tin'"
        Write-Host "và câu trùng chủ đề với 5 câu gốc. Rồi: -Step measure -Name $Name"
    }
    "measure" {
        $extra = @("--approved", "--scripted", "--r0-runs", "$Runs", "--r1-runs", "$Runs")
        if ($Kind -ne "reflection") {
            if (-not (Test-Path "$sets/answers.json")) { Write-Error "Chưa có $sets/answers.json: chạy -Step answers trước"; exit 2 }
            $extra += @("--answers", "$sets/answers.json")
        }
        New-Item -ItemType Directory -Force $folder | Out-Null
        & $py @round @extra | Tee-Object "$folder/compare.txt"   # bộ learn không chạy lại
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $py @verdictArgs | Tee-Object "$folder/verdict.txt"
        exit $LASTEXITCODE
    }
    "verdict" {   # chấm lại kết luận từ các run đã có, không gọi model
        & $py @verdictArgs
        exit $LASTEXITCODE
    }
}
