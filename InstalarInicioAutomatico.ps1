$ErrorActionPreference = 'Stop'
$scannerRoot = $PSScriptRoot
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument `
    ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $scannerRoot 'Iniciar.ps1') + '" -SinNavegador')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'EfectoImanScanner' -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Arranca el nuevo escáner local al iniciar sesión. Independiente de EfectoIman antiguo.' `
    -User $user -RunLevel Limited -Force | Out-Null
Write-Host 'Inicio automático configurado para este usuario. La computadora debe estar encendida y sin suspenderse.'
