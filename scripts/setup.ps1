<#
 Cài đặt lần đầu: tạo venv (nếu thiếu), pip install, tạo .env, khởi động PostgreSQL, migrate, seed_demo.
 Dùng: .\scripts\setup.ps1 [-KhongDungPostgresPortable]   (thêm cờ nếu bạn dùng Docker / PostgreSQL cài sẵn)
#>
param([switch]$KhongDungPostgresPortable)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "Tạo môi trường ảo .venv (Python 3.12) ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv (Join-Path $Root ".venv") }
    else { & python -m venv (Join-Path $Root ".venv") }
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được venv. Cần cài Python 3.12." }
}
Write-Host "Cài thư viện ..."
& $Py -m pip install --disable-pip-version-check -q -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install thất bại" }

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "Đã tạo .env từ .env.example"
}

if (-not $KhongDungPostgresPortable) { & (Join-Path $PSScriptRoot "db_start.ps1") }

Write-Host "migrate ..."
& $Py manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "migrate thất bại" }
Write-Host "seed_demo ..."
& $Py manage.py seed_demo
if ($LASTEXITCODE -ne 0) { throw "seed_demo thất bại" }
Write-Host ""
Write-Host "Xong. Chạy ứng dụng: .\scripts\run.ps1  rồi mở http://127.0.0.1:8000/"
