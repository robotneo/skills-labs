$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Candidates = @()

if ($env:ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON) {
    $Candidates += $env:ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON
}
if ($env:WIFI_HEALTH_PYTHON) {
    $Candidates += $env:WIFI_HEALTH_PYTHON
}
$Candidates += @("py", "python3", "python")
$PythonCommand = $null
$PythonPrefix = @()

foreach ($Candidate in $Candidates) {
    try {
        if ($Candidate -eq "py") {
            & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,7) else 3)" 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonCommand = "py"; $PythonPrefix = @("-3"); break }
        } else {
            & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,7) else 3)" 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonCommand = $Candidate; break }
        }
    } catch {
        continue
    }
}

if (-not $PythonCommand) {
    Write-Error "Enterprise Notification Bridge cannot start: a working Python 3.7+ runtime was not found."
    exit 3
}

$env:PYTHONUTF8 = "1"
& $PythonCommand @PythonPrefix (Join-Path $ScriptDir "main.py") @args
exit $LASTEXITCODE
