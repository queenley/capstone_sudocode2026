# Chạy cả data/dev (409 kịch bản) cho một phương pháp, với phiên bản tri thức/skills mà vòng của nó đã học.
# Không chạy lại vòng học: chỉ chép lại các file đã học, chạy run_eval.py --config full, rồi gỡ chúng ra (về v0).
#
#   .\scripts\evaluation\full_dev.ps1 -Method gaploop -Only SCN-GEN-0001     # thử một kịch bản trước (tốn phí nhỏ)
#   .\scripts\evaluation\full_dev.ps1 -Method gaploop                        # cả 409 kịch bản (tốn phí)
#
#   gaploop     kb v5 của gaploop-5             (--profile gaploop: chỉ tri thức, skills gốc)
#   reflection  skills v2 của reflection-1      (--profile reflection: chỉ skills, tri thức gốc)
#   combined    kb v5 + skills v1 của combined_1 (--profile combined)
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
    gaploop    = @{ Round = "gaploop-5";    Kb = 5;     Skills = $null }
    reflection = @{ Round = "reflection-1"; Kb = $null; Skills = 2 }
    combined   = @{ Round = "combined_1";   Kb = 5;     Skills = 1 }
}[$Method]
$learned = "evaluation\runs\$($plan.Round)\learned"

# Chỉ chạy khi agent đang ở bản gốc: không có kb v>0, không có phiên bản skills (thư mục rỗng thì được).
$stray = @(Get-ChildItem "$kbDir\v*.jsonl" | Where-Object { $_.Name -ne "v0.jsonl" })
$skillFiles = @(if (Test-Path $skillsDir) { Get-ChildItem $skillsDir -File })
if ($stray.Count -or $skillFiles.Count) {
    "Agent không ở v0: $(($stray + $skillFiles).Name -join ', '). Rollback trước."
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
        foreach ($file in Get-ChildItem "$learned\kb\v*.jsonl") {
            Copy-Item $file.FullName "$kbDir\$($file.Name)"; $copied += "$kbDir\$($file.Name)"
        }
        $cmd += @("--kb-version", $plan.Kb)
    }
    if ($null -ne $plan.Skills) {
        New-Item -ItemType Directory -Force $skillsDir | Out-Null
        foreach ($file in Get-ChildItem "$learned\skills\v*.yaml") {
            Copy-Item $file.FullName "$skillsDir\$($file.Name)"; $copied += "$skillsDir\$($file.Name)"
        }
        Set-Content "$skillsDir\active.json" '{"version": 0}' -Encoding utf8   # đang bật vẫn là v0
        $copied += "$skillsDir\active.json"
        $cmd += @("--skills-version", $plan.Skills)
    }
    foreach ($id in $Only) { $cmd += @("--only", $id) }
    # --resume lấy cohort, profile và phiên bản từ manifest của run; chỉ cần file phiên bản có mặt.
    if ($Resume) { $cmd = @("run_eval.py", "--resume", "$out\full.jsonl") }
    "== $Method : kb $($plan.Kb) skills $($plan.Skills) từ $learned -> $out"
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
