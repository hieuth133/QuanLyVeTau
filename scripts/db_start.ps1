<#
 Khởi động PostgreSQL portable trong .tools (tự initdb nếu chưa có dữ liệu), tạo role qlvt và CSDL quanlyvetau.
 Dùng: .\scripts\db_start.ps1 [-Port 5432]
#>
param([int]$Port = 5432)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path $PSScriptRoot -Parent
$Bin  = Join-Path $Root ".tools\pgsql\bin"
$Data = Join-Path $Root ".tools\pgdata"
$Log  = Join-Path $Data "server.log"
$DbName = "quanlyvetau"; $DbUser = "qlvt"; $DbPass = "qlvt"

if (-not (Test-Path (Join-Path $Bin "pg_ctl.exe"))) {
    throw "Không tìm thấy PostgreSQL portable tại $Bin. Giải nén bản binaries của PostgreSQL 16 vào .tools\pgsql (hoặc dùng Docker: docker compose up -d db)."
}

# 1. Khởi tạo cụm dữ liệu nếu chưa có
if (-not (Test-Path (Join-Path $Data "PG_VERSION"))) {
    Write-Host "Khởi tạo cụm dữ liệu PostgreSQL tại $Data ..."
    $pwFile = Join-Path ([System.IO.Path]::GetTempPath()) ("pw_" + [guid]::NewGuid().ToString("N") + ".txt")
    [System.IO.File]::WriteAllText($pwFile, $DbPass)
    try {
        & (Join-Path $Bin "initdb.exe") -D $Data -U $DbUser -A scram-sha-256 -E UTF8 --locale=C "--pwfile=$pwFile"
        if ($LASTEXITCODE -ne 0) { throw "initdb thất bại (mã $LASTEXITCODE)" }
    } finally { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue }
}

# 2. Khởi động server nếu chưa chạy
& (Join-Path $Bin "pg_isready.exe") -h localhost -p $Port | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Khởi động PostgreSQL ở cổng $Port ..."
    & (Join-Path $Bin "pg_ctl.exe") -D $Data -l $Log -o "-p $Port" -w start
    if ($LASTEXITCODE -ne 0) { throw "Không khởi động được PostgreSQL, xem $Log" }
} else {
    Write-Host "PostgreSQL đã chạy ở cổng $Port."
}

# 3. Bảo đảm có role và CSDL
$env:PGPASSWORD = $DbPass
$psql = Join-Path $Bin "psql.exe"
$coRole = & $psql -h localhost -p $Port -U $DbUser -d postgres -tAc "SELECT 1" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tạo role $DbUser ..."
    & $psql -h localhost -p $Port -U postgres -d postgres -c "CREATE ROLE $DbUser LOGIN SUPERUSER PASSWORD '$DbPass'"
}
$coDb = & $psql -h localhost -p $Port -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'"
if ("$coDb".Trim() -ne "1") {
    Write-Host "Tạo CSDL $DbName ..."
    & $psql -h localhost -p $Port -U $DbUser -d postgres -c "CREATE DATABASE $DbName"
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được CSDL $DbName" }
}
Write-Host "Sẵn sàng: postgresql://${DbUser}:***@localhost:$Port/$DbName"
