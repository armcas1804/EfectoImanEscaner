param([Parameter(Mandatory=$true)][ValidateSet('web','worker')][string]$Role)
$ErrorActionPreference = 'Stop'
$scannerRoot = $PSScriptRoot
$scannerMutex = New-Object System.Threading.Mutex($false, ('Local\EfectoImanScanner-' + $Role))
if (-not $scannerMutex.WaitOne(0)) { exit 0 }
$logFolder = Join-Path $scannerRoot 'logs'
$pidFolder = Join-Path $scannerRoot 'data'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
New-Item -ItemType Directory -Path $pidFolder -Force | Out-Null
$supervisorPidPath = Join-Path $pidFolder ($Role + '-supervisor.pid')
$childPidPath = Join-Path $pidFolder ($Role + '-child.pid')
Set-Content -LiteralPath $supervisorPidPath -Value $PID
$scannerPython = Join-Path $scannerRoot '.venv\Scripts\python.exe'
$entryPoint = if ($Role -eq 'web') { 'app.py' } else { 'worker.py' }
try {
    while ($true) {
        $childArgs = @('-u', ('"' + (Join-Path $scannerRoot $entryPoint) + '"'))
        $child = Start-Process -FilePath $scannerPython -ArgumentList $childArgs -WorkingDirectory $scannerRoot `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logFolder ($Role + '.log')) `
            -RedirectStandardError (Join-Path $logFolder ($Role + '.error.log'))
        Set-Content -LiteralPath $childPidPath -Value $child.Id
        $child.WaitForExit()
        Start-Sleep -Seconds 5
    }
} finally {
    $scannerMutex.ReleaseMutex()
    $scannerMutex.Dispose()
}
