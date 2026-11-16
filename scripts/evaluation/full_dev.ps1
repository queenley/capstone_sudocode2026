# Chạy cả data/dev (409 kịch bản) cho một phương pháp, với phiên bản tri thức/skills mà vòng của nó đã học.
# Không chạy lại vòng học: chỉ chép lại các file đã học, chạy run_eval.py --config full, rồi gỡ chúng ra (về v0).
#
#   .\scripts\evaluation\full_dev.ps1 -Method gaploop -Only SCN-GEN-0001     # thử một kịch bản trước (tốn phí nhỏ)
#   .\scripts\evaluation\full_dev.ps1 -Method gaploop                        # cả 409 kịch bản (tốn phí)
#
#   gaploop     kb v5 của gaploop-5             (--profile gaploop: chỉ tri thức, skills gốc)
#   reflection  skills v2 của reflection-1      (--profile reflection: chỉ skills, tri thức gốc)
#   combined    kb v5 của gaploop-5 + skills v2 của reflection-1 (--profile combined): đúng hai phiên bản của hai
#               cột riêng, không phải vòng học combined_1 (đã bỏ, quyết định 16/11/2026)
#
# Không chạy baseline: cột Baseline đã có từ eval_3. Kết quả: evaluation\runs\full-dev\<method>[-trial]\.
# Agent không được publish gì: tri thức và skills đang bật vẫn là v0 (knowledge.yaml, active.json); phiên bản
# chỉ được chọn qua --kb-version / --skills-version của lần chạy này. Hai phương pháp không chạy song song được.
param(
    [Parameter(Mandatory)][ValidateSet("gaploop", "reflection", "combined")][string]$Method,
    [string[]]$Only = @(),
    [switch]$Resume   # chạy tiếp run bị dừng (DB mất, máy ngủ): giữ kịch bản đã xong, chỉ chạy phần còn lại
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$py = ".\apps\ai-agent-service\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
$kbDir = "apps\ai-agent-service\data\kb"
$skillsDir = "apps\ai-agent-service\data\skills"

$plan = @{
    gaploop    = @{ KbRound = "gaploop-5"; Kb = 5;     SkillsRound = $null;          Skills = $null }
    reflection = @{ KbRound = $null;       Kb = $null; SkillsRound = "reflection-1"; Skills = 2 }
    combined   = @{ KbRound = "gaploop-5"; Kb = 5;     SkillsRound = "reflection-1"; Skills = 2 }
}[$Method]

# Chỉ chạy khi agent đang bật bản gốc: knowledge.yaml ở version 0 và không có phiên bản skills (thư mục rỗng thì được).
# Các file kb v1..v5 đã được commit vào data/kb từ 15/11/2026, nên có file không có nghĩa là đang bật.
$active = Select-String -Path "apps\ai-agent-service\config\knowledge.yaml" -Pattern '^version:\s*(\d+)' | Select-Object -First 1
$skillFiles = @(if (Test-Path $skillsDir) { Get-ChildItem $skillsDir -File })
if (($active -and $active.Matches[0].Groups[1].Value -ne "0") -or $skillFiles.Count) {
    "Agent không ở v0: knowledge.yaml version $(if ($active) { $active.Matches[0].Groups[1].Value }), $(($skillFiles).Name -join ', '). Rollback trước."
    exit 2
}

$name = if ($Only.Count) { "$Method-trial" } else { $Method }
$out = "evaluation\runs\full-dev\$name"
if (Test-Path "$out\full.manifest.json") {
    if ((Get-Content "$out\full.manifest.json" -Raw -Encoding utf8 | ConvertFrom-Json).finished_at) {
        "== $out đã chạy xong, không chạy lại."; exit 0
    }
}
if ($Resume -and -not (Test-Path "$out\full.manifest.json")) { "Không có run để chạy tiếp ở $out."; exit 2 }
if (-not $Resume -and (Test-Path $out) -and (Get-ChildItem $out).Count) {
    Move-Item $out ("$out.stopped-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Force $out | Out-Null

$copied = @()
try {
    $cmd = @("run_eval.py", "--scenarios", "data\dev\scenarios", "--config", "full", "--out", "$out\full.jsonl",
             "--profile", $Method, "--purpose", "adhoc")
    if ($null -ne $plan.Kb) {
        $source = "evaluation\runs\$($plan.KbRound)\learned\kb\v$($plan.Kb).jsonl"
        $target = "$kbDir\v$($plan.Kb).jsonl"
        if (Test-Path $target) {
            # Bản đã commit phải giống từng byte bản vòng GapLoop đã học.
            if ((Get-FileHash $source).Hash -ne (Get-FileHash $target).Hash) { "$target khác $source"; exit 2 }
        } else { Copy-Item $source $target; $copied += $target }
        $cmd += @("--kb-version", $plan.Kb)
    }
    if ($null -ne $plan.Skills) {
        New-Item -ItemType Directory -Force $skillsDir | Out-Null
        $file = "evaluation\runs\$($plan.SkillsRound)\learned\skills\v$($plan.Skills).yaml"
        Copy-Item $file "$skillsDir\v$($plan.Skills).yaml"; $copied += "$skillsDir\v$($plan.Skills).yaml"
        Set-Content "$skillsDir\active.json" '{"version": 0}' -Encoding utf8   # đang bật vẫn là v0
        $copied += "$skillsDir\active.json"
        $cmd += @("--skills-version", $plan.Skills)
    }
    foreach ($id in $Only) { $cmd += @("--only", $id) }
    # --resume lấy cohort, profile và phiên bản từ manifest của run; chỉ cần file phiên bản có mặt.
    if ($Resume) { $cmd = @("run_eval.py", "--resume", "$out\full.jsonl") }
    "== $Method : kb $($plan.Kb) ($($plan.KbRound)) skills $($plan.Skills) ($($plan.SkillsRound)) -> $out"
    & $py @cmd
    $code = $LASTEXITCODE
    if (Test-Path "$out\full.jsonl") {
        & $py apps\ai-agent-service\data\btc\eval\reference_eval.py --scenarios "$out\full.scenarios" --trace "$out\full.jsonl" --out "$out\report.json" | Out-Null
    }
} finally {
    # Về v0: gỡ đúng những gì đã chép.
    foreach ($path in $copied) { if (Test-Path $path) { Remove-Item $path -Recurse -Force } }
    "== đã gỡ phiên bản đã học, agent về v0"
}
exit $code
