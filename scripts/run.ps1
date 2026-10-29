<# Chạy máy chủ phát triển (đảm bảo PostgreSQL đang chạy). Dùng: .\scripts\run.ps1 [-Port 8000] #>
param([int]$Port = 8000, [switch]$KhongDungPostgresPortable)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
if (-not $KhongDungPostgresPortable -and (Test-Path (Join-Path $Root ".tools\pgsql\bin\pg_ctl.exe"))) {
    & (Join-Path $PSScriptRoot "db_start.ps1")
}
& (Join-Path $Root ".venv\Scripts\python.exe") manage.py runserver "127.0.0.1:$Port"
