[CmdletBinding()]
param([Parameter(Mandatory = $true)][ValidateSet('start','stop','restart','status','uninstall')] [string]$Action)

$serviceName = 'KepwareMonitoring'
$serviceExe = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\service')).Path 'kepware-monitor.exe'
if ($Action -eq 'uninstall') {
    if (Test-Path $serviceExe) { & $serviceExe stop; & $serviceExe uninstall } else { sc.exe delete $serviceName }
    exit $LASTEXITCODE
}
if ($Action -eq 'status') { Get-Service -Name $serviceName | Format-Table Name, Status, StartType -AutoSize; exit }
if (-not (Test-Path $serviceExe)) { throw 'Service wrapper not found. Run scripts\install-service.ps1 first.' }
& $serviceExe $Action
