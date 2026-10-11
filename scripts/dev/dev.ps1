param([switch]$Stop)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot ../..)
if ($Stop) { docker compose down } else { docker compose up --build }
