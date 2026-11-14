# Vòng cải tiến trên mẫu data/dev, trộn GEN (general) / ADV (advance) theo tỉ lệ.
#
#   Reflection, một lệnh:
#     powershell -ExecutionPolicy ByPass -File scripts\improvements\scripts.ps1 -Step reflection -Name dev-1
#   GapLoop, ba bước (bước 2 là người viết câu trả lời):
#     ... scripts.ps1 -Step gap-learn   -Name dev-gap-1   # chạy bộ learn, ghi câu hỏi chưa trả lời được
#     ... scripts.ps1 -Step gap-answers -Name dev-gap-1   # tạo answers.json để điền, xóa câu không trả lời
#     ... scripts.ps1 -Step gap-measure -Name dev-gap-1   # đo frozen trước/sau khi đăng câu trả lời
#   Bộ chứng minh cố định cũ (gap-1, budget-1):
#     ... scripts.ps1 -Step proof
#
# Mỗi kịch bản là một lần gọi model (tốn phí); frozen chạy hai lần (trước và sau).
param(
    [ValidateSet("reflection", "gap-learn", "gap-answers", "gap-measure", "proof")]
    [string]$Step = "reflection",
    [string]$Name = "dev-1",
    [int]$Learn = 20,          # số kịch bản học
    [int]$Frozen = 10,         # số kịch bản đo trước/sau
    [double]$AdvShare = 0.5,   # tỉ lệ ADV trong mỗi bộ: 0.5 = 50% general, 50% advance
    [int]$Seed = 1             # cùng seed thì cùng mẫu
)

Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$env:PYTHONPATH = "apps/ai-agent-service/src;packages/backend-common"
$py = "apps\ai-agent-service\.venv\Scripts\python.exe"
$sets = "data/.build/rounds/$Name"

function Run { & $py @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }  # một bước lỗi thì dừng

function Build-Sets {
    # Dùng lại bộ đã tạo khi chạy tiếp cùng -Name, để learn và frozen không đổi giữa các bước.
    if (-not (Test-Path "$sets/frozen.json")) {
        Run scripts/improvements/make_sets.py --name $Name --learn $Learn --frozen $Frozen --adv-share $AdvShare --seed $Seed
    }
}

$round = @("-m", "ai_agent_service.pipeline.improve", "round", "--name", $Name,
           "--learn", "$sets/learn/scenarios", "--frozen", "$sets/frozen/scenarios", "--frozen-ids", "$sets/frozen.json")
# GapLoop chạy cả mẫu data/dev lẫn bộ gốc data/gap-loop. Chỉ câu agent không trả lời được (chuyển máy vì tài liệu
# không có, hoặc truy xuất không ra và agent nói chưa có thông tin) mới thành câu hỏi mở của Gap Loop.
$gapRound = $round + @("--learn", "data/gap-loop/learn/scenarios", "--frozen", "data/gap-loop/frozen/scenarios",
                       "--frozen-ids", "data/gap-loop/frozen.json")

switch ($Step) {
    "reflection" {
        Build-Sets
        Run @round --scripted
    }
    "gap-learn" {
        Build-Sets
        Run @gapRound   # không --scripted: dừng sau bộ learn, chưa chạy frozen
        Write-Host "`nTiếp theo: scripts.ps1 -Step gap-answers -Name $Name"
    }
    "gap-answers" {
        # Câu trả lời đã viết cho 5 chủ đề của bộ gốc đi trước; câu hỏi mở từ data/dev để điền hoặc xóa.
        Run scripts/improvements/gap_answers_template.py --name $Name --include data/gap-loop/answers.json
        Write-Host "Điền 'answer' trong $sets/answers.json, xóa câu không trả lời, rồi: scripts.ps1 -Step gap-measure -Name $Name"
    }
    "gap-measure" {
        if (-not (Test-Path "$sets/answers.json")) { Write-Error "Chưa có $sets/answers.json: chạy -Step gap-answers trước"; exit 2 }
        Run @gapRound --answers "$sets/answers.json" --approved --scripted   # bộ learn không chạy lại
    }
    "proof" {
        # GapLoop: câu hỏi tài liệu BTC không có (lắp đặt, gói quà, nhận tại shop...)
        Run -m ai_agent_service.pipeline.improve round --name gap-1 `
            --learn data/gap-loop/learn/scenarios --frozen data/gap-loop/frozen/scenarios `
            --frozen-ids data/gap-loop/frozen.json --answers data/gap-loop/answers.json --scripted
        # Reflection: bộ budget (báo khi tổng đơn vượt ngân sách khách nói)
        Run -m ai_agent_service.pipeline.improve round --name budget-1 `
            --learn data/reflection/budget/learn/scenarios --frozen data/reflection/budget/frozen/scenarios `
            --frozen-ids data/reflection/budget/frozen.json --scripted
    }
}
