$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Candidates = @()

if ($env:WIFI_HEALTH_PYTHON) { $Candidates += $env:WIFI_HEALTH_PYTHON }
$Candidates += @("py", "python3", "python")
$PythonCommand = $null
$PythonPrefix = @()
$LastError = ""

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
        $LastError = $_.Exception.Message
    }
}

if (-not $PythonCommand) {
    Write-Error "Wi-Fi Health Detector cannot start: a working Python 3.7+ runtime was not found. Install Python from python.org or Microsoft Store. This is a Python runtime problem, not a Wi-Fi disconnected diagnosis. $LastError"
    exit 3
}

& $PythonCommand @PythonPrefix (Join-Path $ScriptDir "main.py") @args
exit $LASTEXITCODE
