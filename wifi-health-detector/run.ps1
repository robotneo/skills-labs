$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Engine=if($env:WIFI_HEALTH_ENGINE){$env:WIFI_HEALTH_ENGINE}else{'auto'}
for($i=0;$i -lt $args.Count;$i++){if($args[$i] -eq '--engine' -and $i+1 -lt $args.Count){$Engine=$args[$i+1]}}
if($Engine -notin 'auto','python','native','node'){[Console]::Error.WriteLine('Invalid --engine');exit 2}
. (Join-Path $ScriptDir 'portable/process.ps1')
if($Engine -in 'auto','python'){
    $Candidates=@($env:WIFI_HEALTH_PYTHON)
    if($env:VIRTUAL_ENV){$Candidates+=Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe'}
    if($env:CONDA_PREFIX){$Candidates+=Join-Path $env:CONDA_PREFIX 'python.exe'}
    $Candidates+=@('py','python3','python')
    foreach($root in 'HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore'){
        foreach($key in @(Get-ChildItem $root -ErrorAction SilentlyContinue)){
            $install=Get-Item (Join-Path $key.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if($install){$exe=$install.GetValue('ExecutablePath');if(-not $exe){$exe=Join-Path $install.GetValue('') 'python.exe'};$Candidates+=$exe}
        }
    }
    foreach($Candidate in @($Candidates|Where-Object {$_}|Select-Object -Unique)){
        $prefix=if($Candidate -eq 'py'){@('-3')}else{@()}
        $probe=Invoke-WifiBatch @{python=(@($Candidate)+$prefix+@('-c','import sys,json,ctypes,concurrent.futures; raise SystemExit(0 if sys.version_info >= (3,7) else 3)'))} 2 ([datetime]::UtcNow.AddSeconds(2))
        if($probe.python.status -eq 0){$env:PYTHONUTF8='1';& $Candidate @prefix (Join-Path $ScriptDir 'main.py') @args;exit $LASTEXITCODE}
    }
}
if($Engine -in 'auto','native'){
    if($PSVersionTable.PSVersion -ge [version]'5.1' -and $ExecutionContext.SessionState.LanguageMode -eq 'FullLanguage'){
        & (Join-Path $ScriptDir 'portable/windows.ps1') @args
        exit $LASTEXITCODE
    }
}
if($Engine -in 'auto','node'){
    foreach($Candidate in @($env:WIFI_HEALTH_NODE,'node')|Where-Object {$_}){
        $probe=Invoke-WifiBatch @{node=@($Candidate,'-e','if(Number(process.versions.node.split(".")[0])<16)process.exit(3);require("child_process");require("fs");')} 2 ([datetime]::UtcNow.AddSeconds(2))
        if($probe.node.status -eq 0){& $Candidate (Join-Path $ScriptDir 'portable/node.cjs') @args;exit $LASTEXITCODE}
    }
}
[Console]::Error.WriteLine('No usable Python, native PowerShell, or Node engine. This is a runtime/capability problem, not a Wi-Fi disconnected diagnosis.')
exit 3
