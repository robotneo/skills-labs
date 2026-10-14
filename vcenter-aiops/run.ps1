$ErrorActionPreference = 'Stop'
$runtime = if ($env:VCENTER_AIOPS_PYTHON) { $env:VCENTER_AIOPS_PYTHON } else { 'python' }
& $runtime -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)'
if ($LASTEXITCODE -ne 0) { throw 'vCenter AIops requires Python 3.10+' }
$env:PYTHONPATH = (Join-Path $PSScriptRoot 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
& $runtime -m vcenter_aiops @args
exit $LASTEXITCODE
