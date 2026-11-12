$scannerRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
foreach ($role in @('web', 'worker')) {
    foreach ($kind in @('supervisor','child')) {
        $pidFile = Join-Path $scannerRoot ('data\' + $role + '-' + $kind + '.pid')
        if (Test-Path -LiteralPath $pidFile) {
            $scannerPid = 0
            if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$scannerPid)) {
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$scannerPid" -ErrorAction SilentlyContinue
                if ($process -and $process.CommandLine -and $process.CommandLine.Contains($scannerRoot)) {
                    Stop-Process -Id $scannerPid -ErrorAction SilentlyContinue
                }
            }
        }
    }
}
Write-Host 'Se detuvieron únicamente los procesos identificados del nuevo escáner.'
