param([switch]$SinNavegador)
$ErrorActionPreference = 'Stop'
$scannerRoot = $PSScriptRoot
$scannerPython = Join-Path $scannerRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $scannerPython)) {
    throw 'Primero ejecuta: py -3.11 -m venv .venv y .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}
foreach ($role in @('web', 'worker')) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        ('"' + (Join-Path $scannerRoot 'Run-Service.ps1') + '"'), '-Role', $role)
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $scannerRoot -WindowStyle Hidden
}
if (-not $SinNavegador) {
    Start-Sleep -Seconds 3
    Start-Process 'http://127.0.0.1:8601/'
}
Write-Host 'Efecto Imán Scanner: http://127.0.0.1:8601/ — captura independiente de la página.'
