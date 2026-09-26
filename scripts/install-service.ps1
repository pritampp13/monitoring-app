[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$serviceName = 'KepwareMonitoring'
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serviceDir = Join-Path $projectDir 'service'
$serviceExe = Join-Path $serviceDir 'kepware-monitor.exe'
$serviceXml = Join-Path $serviceDir 'kepware-monitor.xml'

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated (Administrator) PowerShell window.'
}

$winsw = Get-Command winsw.exe -ErrorAction SilentlyContinue
if (-not $winsw) {
    Write-Host 'Installing the Windows Service Wrapper through Winget...'
    winget install --id CloudBees.WindowsServiceWrapper --source winget --silent --accept-package-agreements --accept-source-agreements
    $winsw = Get-Command winsw.exe -ErrorAction SilentlyContinue
}
if (-not $winsw) {
    $candidate = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter winsw.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $winsw = @{ Source = $candidate.FullName } }
}
if (-not $winsw) { throw 'WinSW could not be located after installation. Install CloudBees.WindowsServiceWrapper, then rerun this script.' }

if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
    throw "The $serviceName service already exists. Use scripts\service-control.ps1 or uninstall it first."
}

$pythonExe = (Get-Command python -ErrorAction Stop).Source
$xml = Get-Content (Join-Path $serviceDir 'kepware-monitor.xml.template') -Raw
$xml = $xml.Replace('__PYTHON_EXE__', [System.Security.SecurityElement]::Escape($pythonExe))
$xml = $xml.Replace('__PROJECT_DIR__', [System.Security.SecurityElement]::Escape($projectDir))
Set-Content -LiteralPath $serviceXml -Value $xml -Encoding UTF8
Copy-Item -LiteralPath $winsw.Source -Destination $serviceExe -Force

# WinSW runs under LocalSystem by default. Grant that account only the read/write
# roles it needs in the configured monitor database, without touching other databases.
$envFile = Join-Path $projectDir '.env'
$envValues = @{}
Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*[^#=]+=' } | ForEach-Object {
    $pair = $_ -split '=', 2; $envValues[$pair[0].Trim()] = $pair[1].Trim()
}
if ($envValues['MSSQL_SERVER'] -and $envValues['MSSQL_DATABASE'] -and $envValues['MSSQL_TRUSTED_CONNECTION'] -ne 'false') {
    $sql = @"
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'NT AUTHORITY\SYSTEM') CREATE LOGIN [NT AUTHORITY\SYSTEM] FROM WINDOWS;
USE [$($envValues['MSSQL_DATABASE'])];
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'NT AUTHORITY\SYSTEM') CREATE USER [NT AUTHORITY\SYSTEM] FOR LOGIN [NT AUTHORITY\SYSTEM];
ALTER ROLE db_datareader ADD MEMBER [NT AUTHORITY\SYSTEM];
ALTER ROLE db_datawriter ADD MEMBER [NT AUTHORITY\SYSTEM];
"@
    & sqlcmd -S $envValues['MSSQL_SERVER'] -E -C -Q $sql
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant the LocalSystem service account access to the configured MSSQL database.' }
}

& $serviceExe install
sc.exe config $serviceName start= auto | Out-Null
sc.exe failure $serviceName reset= 86400 actions= restart/10000/restart/10000/restart/30000 | Out-Null
& $serviceExe start
Write-Host "$serviceName is installed, set to start automatically, and started. Dashboard: http://localhost:8000"
