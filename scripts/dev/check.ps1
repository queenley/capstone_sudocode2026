$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot ../..)
& ./.venv/Scripts/python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location apps/web
try { npm run typecheck; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } } finally { Pop-Location }
& ./.venv/Scripts/python.exe evaluation/agent-evaluation/run_eval.py rag-offline
exit $LASTEXITCODE
