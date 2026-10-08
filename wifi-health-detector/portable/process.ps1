# Bounded subprocesses; argument quoting follows the Windows CRT rules.
function Quote-WifiArgument([string]$value) {
    return '"'+[regex]::Replace([regex]::Replace($value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'
}
function Stop-WifiProcess($process){
    if($process.HasExited){return}
    if([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT){
        $killer=New-Object Diagnostics.Process
        $killer.StartInfo.FileName=Join-Path $env:SystemRoot 'System32/taskkill.exe'
        $killer.StartInfo.Arguments="/PID $($process.Id) /T /F"
        $killer.StartInfo.UseShellExecute=$false;$killer.StartInfo.CreateNoWindow=$true
        $killer.StartInfo.RedirectStandardOutput=$true;$killer.StartInfo.RedirectStandardError=$true
        try{[void]$killer.Start();if(-not $killer.WaitForExit(1000)){$killer.Kill()}}catch{}finally{$killer.Dispose()}
    }
    if(-not $process.HasExited){$process.Kill()}
}
function Invoke-WifiBatch($specs,[double]$timeout,[datetime]$deadline) {
    $results=@{};$running=New-Object 'System.Collections.Generic.List[object]'
    foreach($key in $specs.Keys){
        if([datetime]::UtcNow -ge $deadline){$results[$key]=@{stdout='';status=124;elapsed_ms=0};continue}
        $spec=$specs[$key];$p=New-Object System.Diagnostics.Process
        $p.StartInfo.FileName=$spec[0];$p.StartInfo.Arguments=(@($spec|Select-Object -Skip 1|ForEach-Object {Quote-WifiArgument $_}) -join ' ')
        $p.StartInfo.UseShellExecute=$false;$p.StartInfo.CreateNoWindow=$true;$p.StartInfo.RedirectStandardOutput=$true;$p.StartInfo.RedirectStandardError=$true
        # Console tools use the OEM code page, unlike PowerShell JSON (forced UTF-8).
        $encoding=if([IO.Path]::GetFileName($spec[0]) -match '^powershell') {New-Object Text.UTF8Encoding $false} elseif($script:WifiNativeEncoding){$script:WifiNativeEncoding} else {[Console]::OutputEncoding}
        $p.StartInfo.StandardOutputEncoding=$encoding;$p.StartInfo.StandardErrorEncoding=$encoding
        $start=[datetime]::UtcNow
        try{[void]$p.Start();$running.Add(@{key=$key;p=$p;out=$p.StandardOutput.ReadToEndAsync();err=$p.StandardError.ReadToEndAsync();start=$start})}
        catch{$p.Dispose();$results[$key]=@{stdout='';status=127;elapsed_ms=0}}
    }
    try{
        while($running.Count){
            for($i=$running.Count-1;$i -ge 0;$i--){$job=$running[$i];$elapsed=([datetime]::UtcNow-$job.start).TotalMilliseconds;$expired=[datetime]::UtcNow -ge $deadline -or $elapsed -ge $timeout*1000
                if(-not $job.p.HasExited -and -not $expired){continue}
                if(-not $job.p.HasExited){Stop-WifiProcess $job.p;[void]$job.p.WaitForExit(1000)}
                [void]$job.out.Wait(200);[void]$job.err.Wait(200)
                $status=if($expired){124}else{$job.p.ExitCode};$stdout=if($job.out.IsCompleted){$job.out.Result}else{''};$stderr=if($job.err.IsCompleted){$job.err.Result}else{''}
                $results[$job.key]=@{stdout=$stdout;stderr=$stderr;status=$status;elapsed_ms=[math]::Round($elapsed,2)};$job.p.Dispose();$running.RemoveAt($i)
            }
            if($running.Count){Start-Sleep -Milliseconds 20}
        }
    }finally{foreach($job in $running){Stop-WifiProcess $job.p;$job.p.Dispose()}}
    return $results
}
