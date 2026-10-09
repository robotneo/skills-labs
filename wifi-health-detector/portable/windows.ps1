# Native Windows engine; no external runtime or module installation.
$ErrorActionPreference='Stop'
$script:WifiNativeEncoding=[Console]::OutputEncoding
[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::InvariantCulture
[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false
$Options=@{language='zh';timeout=10;budget=35;view='summary'}
$flags=@{'--mask'='mask';'--speedtest'='speedtest';'--no-public-test'='noPublic';'--no-notify'='noNotify';'--verbose'='verbose';'--fast'='fast';'--help'='help';'-h'='help'}
$values=@{'--interface'='interface';'--json'='json';'--csv'='csv';'--language'='language';'--timeout'='timeout';'--budget'='budget';'--view'='view';'--report-input'='reportInput';'--capture-input'='captureInput';'--engine'='engine'}
try{
    for($i=0;$i -lt $args.Count;$i++){$a=$args[$i];if($flags[$a]){$Options[$flags[$a]]=$true}elseif($values[$a]){if($i+1 -ge $args.Count){throw "Missing value for $a"};$i++;$Options[$values[$a]]=$args[$i]}else{throw "Unknown argument $a"}}
    foreach($k in 'timeout','budget'){if("$($Options[$k])" -notmatch '^[1-9]\d*$'){throw "$k must be a positive integer"};$Options[$k]=[int]$Options[$k]}
    if($Options.language -notin 'zh','en' -or $Options.view -ne 'summary'){throw 'Invalid language/view'}
    if($Options.help){[Console]::Write("Wi-Fi Health Detector`n--engine auto|python|native --interface NAME --language zh|en`n--timeout SECONDS --budget SECONDS --fast --no-public-test --speedtest`n--mask --json PATH --csv PATH --no-notify --verbose --view summary`n");exit 0}
    $Contract=Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'contract.json')|ConvertFrom-Json
    . (Join-Path $PSScriptRoot 'report.ps1')
    . (Join-Path $PSScriptRoot 'process.ps1')
    . (Join-Path $PSScriptRoot 'windows-collect.ps1')
    if($Options.reportInput){$report=Read-WifiJson (Get-Content -Raw -Encoding UTF8 $Options.reportInput)}
    else{$capture=if($Options.captureInput){Read-WifiJson (Get-Content -Raw -Encoding UTF8 $Options.captureInput)}else{Get-WifiCapture $Options};$report=Convert-WifiCapture $capture $Options}
    Assert-WifiReport $report;$report.diagnosis=Get-WifiDiagnosis $report;if($Options.mask){Protect-WifiReport $report}
    $encoding=New-Object Text.UTF8Encoding $false
    if($Options.json){[IO.File]::WriteAllText($Options.json,($report|ConvertTo-Json -Depth 20)+"`n",$encoding)}
    if($Options.csv){[IO.File]::WriteAllText($Options.csv,(Export-WifiCsv $report),$encoding)}
    [Console]::Write((Format-WifiReport $report $Options.language))
    if(-not $Options.noNotify -and -not $Options.reportInput -and -not $Options.captureInput){[Console]::Error.WriteLine('Enterprise notification: portable engine does not invoke the Python Bridge; report retained.')}
    exit 0
}catch{[Console]::Error.WriteLine('Wi-Fi detector error: '+$_.Exception.Message);exit 2}
