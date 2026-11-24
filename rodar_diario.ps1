# Execução diária do Catajobs. Log em logs\diario_AAAA-MM-DD.log
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $PSScriptRoot ("logs\diario_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
& "$PSScriptRoot\.venv\Scripts\python.exe" -m catajobs diario *>> $log
