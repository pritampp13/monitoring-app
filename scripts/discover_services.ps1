# Read-only discovery of actual Kepware/KepServer services from Windows SCM.
Get-CimInstance Win32_Service |
    Where-Object { $_.Name -match '(?i)kepware|kepserver' -or $_.DisplayName -match '(?i)kepware|kepserver' } |
    Select-Object Name, DisplayName, State, StartMode |
    Format-Table -AutoSize
