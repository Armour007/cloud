#Requires -Version 5.1
<#
.SYNOPSIS
  GitContainer Cloud — start the local web interface.
.DESCRIPTION
  Uses .venv (created by setup.ps1). Run setup.ps1 first on a fresh machine.
#>
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir

$venvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host "  [XX] Virtual environment not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================="
Write-Host " GitContainer Cloud is running"
Write-Host "========================================="
Write-Host ""
Write-Host "  Open:"
Write-Host "  http://localhost:8000"
Write-Host ""
Write-Host "  Press Ctrl+C to stop."
Write-Host ""
Write-Host "========================================="
Write-Host ""

& $venvPy app.py
