<# Dừng PostgreSQL portable trong .tools. Dùng: .\scripts\db_stop.ps1 #>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path $PSScriptRoot -Parent
$Bin  = Join-Path $Root ".tools\pgsql\bin"
$Data = Join-Path $Root ".tools\pgdata"
& (Join-Path $Bin "pg_ctl.exe") -D $Data -m fast -w stop
