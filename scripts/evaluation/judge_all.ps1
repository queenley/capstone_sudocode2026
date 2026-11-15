# Chấm rubric J01–J12 cho mọi phương pháp trên cùng một mẫu kịch bản (--judge-run --only), rồi dựng lại bảng.
#
#   .\scripts\evaluation\judge_all.ps1 -Step plan    # in mẫu, các run và số cuộc gọi judge; không gọi model
#   .\scripts\evaluation\judge_all.ps1 -Step try     # chỉ một run (GapLoop) để xem chi phí và kết quả
#   .\scripts\evaluation\judge_all.ps1 -Step all     # mọi run còn lại; run đã chấm xong (có judge-run.json kèm summary) được bỏ qua
#   .\scripts\evaluation\judge_all.ps1 -Step table   # chạy lại method_metrics.py (không gọi model)
#
# Mẫu: 20 SCN-GEN + 10 SCN-ADV của eval_3, trải đều persona, lấy trước frozen 20 (-Anchor) để mọi phương pháp
# được chấm trên cùng 20 kịch bản đó. Run của các vòng chỉ có frozen 20 nên --only chỉ giữ phần trùng.
# Mỗi cuộc gọi là một lần gọi judge (tốn phí). -Second thêm lần chạy thứ hai (-2) của mỗi phương pháp.
param(
    [ValidateSet("plan", "try", "all", "table")][string]$Step = "plan",
    [int]$Gen = 20, [int]$Adv = 10, [int]$Seed = 20261115,
    [string]$Anchor = "evaluation\runs\gaploop-5\r1-gaploop-5\full.scenarios",
    [switch]$Second, [switch]$Proof
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root
$py = ".\apps\ai-agent-service\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"

$runs = [ordered]@{
    "Baseline + Router" = "evaluation\runs\eval_3"
    "GapLoop"           = "evaluation\runs\gaploop-5\r1-gaploop-5"
    "Reflection"        = "evaluation\runs\reflection-1\r1-reflection-1"
    "GapLoop + Reflection" = "evaluation\runs\combined_1\r1-combined_1"
}
if ($Second) {
    $runs["GapLoop (lần 2)"] = "evaluation\runs\gaploop-5\r1-gaploop-5-2"
    $runs["Reflection (lần 2)"] = "evaluation\runs\reflection-1\r1-reflection-1-2"
    $runs["GapLoop + Reflection (lần 2)"] = "evaluation\runs\combined_1\r1-combined_1-2"
}
if ($Proof) {
    # Bộ proof không trùng mẫu: chấm toàn bộ (ít kịch bản).
    $runs["Proof gap-loop: Router"] = "evaluation\runs\gaploop-5\r0-gap-loop-1"
    $runs["Proof gap-loop: GapLoop"] = "evaluation\runs\gaploop-5\r1-gap-loop"
    $runs["Proof budget: Router"] = "evaluation\runs\reflection-1\r0-budget-1"
    $runs["Proof budget: Reflection"] = "evaluation\runs\reflection-1\r1-budget"
}

if ($Step -eq "table") {
    & $py scripts\evaluation\method_metrics.py
    exit $LASTEXITCODE
}

$ids = & $py scripts\evaluation\judge_sample.py evaluation\runs\eval_3 --gen $Gen --adv $Adv --seed $Seed --anchor $Anchor --ids
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$ids = @($ids | Where-Object { $_ })

function Scenarios($run) {
    foreach ($name in "scenarios", "full.scenarios") {
        if (Test-Path "$run\$name") { return @(Get-ChildItem "$run\$name\*.json" | ForEach-Object { $_.BaseName }) }
    }
    return @()
}
function Chosen($label, $run) {
    if ($label -like "Proof*") { return @() }   # cả run
    $have = Scenarios $run
    return @($ids | Where-Object { $have -contains $_ })
}
function Calls($run, $only) {
    $n = 0
    foreach ($trace in "full.jsonl", "baseline.jsonl") {
        if (-not (Test-Path "$run\$trace")) { continue }
        $seen = @{}
        foreach ($line in Get-Content "$run\$trace" -Encoding utf8) {
            if (-not $line.Trim()) { continue }
            $row = $line | ConvertFrom-Json
            if ($only.Count -and $only -notcontains $row.scenario_id) { continue }
            $seen["$($row.scenario_id)|$($row.call)"] = 1
        }
        $n += $seen.Count
    }
    return $n
}
function Done($run) {
    # Chấm xong khi judge-run.json có summary (ghi ở cuối). status INCOMPLETE ở đây chỉ nghĩa là có cuộc gọi
    # judge trả evidence không trích nguyên văn: chấm lại cũng tốn phí như vậy, nên không chấm lại.
    $record = "$run-judge\judge-run.json"
    return (Test-Path $record) -and ($null -ne (Get-Content $record -Raw -Encoding utf8 | ConvertFrom-Json).summary)
}

if ($Step -eq "plan") {
    & $py scripts\evaluation\judge_sample.py evaluation\runs\eval_3 --gen $Gen --adv $Adv --seed $Seed --anchor $Anchor | Select-Object -SkipLast 2
    ""
    $total = 0
    foreach ($label in $runs.Keys) {
        $run = $runs[$label]
        if (-not (Test-Path $run)) { "{0,-32} thiếu run: {1}" -f $label, $run; continue }
        $only = Chosen $label $run
        $calls = Calls $run $only
        $state = if (Done $run) { "đã chấm" } else { $total += $calls; "" }
        "{0,-32} {1,3} kịch bản  {2,4} cuộc gọi judge  {3}" -f $label, $(if ($only.Count) { $only.Count } else { "all" }), $calls, $state
    }
    ""
    "Tổng cuộc gọi judge còn phải chạy: $total"
    exit 0
}

$todo = if ($Step -eq "try") { @("GapLoop") } else { @($runs.Keys) }
$failed = @()
foreach ($label in $todo) {
    $run = $runs[$label]
    if (Done $run) { "== $label : đã chấm xong, bỏ qua"; continue }
    if (Test-Path "$run-judge") {
        # Lần trước dừng giữa chừng: giữ lại để xem, chấm lại từ đầu.
        Move-Item "$run-judge" ("$run-judge.incomplete-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    }
    $only = Chosen $label $run
    $cmd = @("run_eval.py", "--judge-run", $run, "--out", "$run-judge")
    foreach ($id in $only) { $cmd += @("--only", $id) }
    "== $label : $run ($(if ($only.Count) { "$($only.Count) kịch bản" } else { 'toàn bộ' }))"
    & $py @cmd
    if (-not (Done $run)) { $failed += $label }   # mã 1 = có cuộc gọi INCOMPLETE nhưng run đã chấm xong
}
if ($failed.Count) {
    "Chưa xong: $($failed -join ', '). Chạy lại -Step all để chấm tiếp (run đã chấm xong được bỏ qua)."
    exit 1
}
if ($Step -eq "all") { & $py scripts\evaluation\method_metrics.py }
