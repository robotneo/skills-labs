function Get-WifiNumber($text){$m=[regex]::Match([string]$text,'-?\d+(?:[.,]\d+)?');if($m.Success){return [double]::Parse($m.Value.Replace(',','.'),[Globalization.CultureInfo]::InvariantCulture)};return $null}
function Get-WifiMedian($items){$a=@($items|Sort-Object);if(-not $a.Count){return $null};$n=$a.Count;if($n%2){return $a[[int][math]::Floor($n/2)]};return [math]::Round(($a[$n/2-1]+$a[$n/2])/2,3)}
function Read-WifiPing($item){
    if(-not $item -or $item.status -in 124,127){return $null};$t=$item.stdout
    if(($t+$item.stderr) -match 'transmit failed|general failure|permission denied|operation not permitted|sendto:|network is unreachable|传输失败|常见故障|一般故障|拒绝访问'){return $null}
    $m=[regex]::Match($t,'([\d.]+)%\s*(?:packet loss|loss|丢失)','IgnoreCase');if(-not $m.Success){return $null}
    $p=@{loss=[double]$m.Groups[1].Value;latency=$null;jitter=$null}
    $a=[regex]::Match($t,'(?:Average|平均)\s*=\s*([\d.]+)ms','IgnoreCase');if($a.Success){$p.latency=[double]$a.Groups[1].Value}
    $lo=[regex]::Match($t,'(?:Minimum|最短)\s*=\s*([\d.]+)ms','IgnoreCase');$hi=[regex]::Match($t,'(?:Maximum|最长)\s*=\s*([\d.]+)ms','IgnoreCase');if($lo.Success -and $hi.Success){$p.jitter=[double]$hi.Groups[1].Value-[double]$lo.Groups[1].Value};return $p
}
function Convert-WifiCapture($inputData,$o){
    $r=New-WifiReport;$cmd=$inputData.commands
    function Raw($k){if($cmd[$k] -and $cmd[$k].status -eq 0){return [string]$cmd[$k].stdout};return ''}
    Set-WifiField $r system os Windows;Set-WifiField $r system os_version $inputData.os_version;Set-WifiField $r system architecture $inputData.architecture;Set-WifiField $r system checked_at $inputData.checked_at;Set-WifiField $r system privilege 'current user';Set-WifiMissing $r system python_version 'Python is not used by this engine' runtime
    $aliases=@{'name'='interface';'名称'='interface';'description'='description';'描述'='description';'physical address'='mac';'物理地址'='mac';'state'='state';'状态'='state';'ssid'='ssid';'bssid'='bssid';'radio type'='current_phy';'无线电类型'='current_phy';'authentication'='authentication';'身份验证'='authentication';'cipher'='cipher';'密码'='cipher';'channel'='channel';'频道'='channel';'channel width'='channel_width';'信道宽度'='channel_width';'频道宽度'='channel_width';'receive rate (mbps)'='rx_rate';'接收速率(mbps)'='rx_rate';'transmit rate (mbps)'='tx_rate';'传输速率(mbps)'='tx_rate';'signal'='signal_percent';'信号'='signal_percent';'band'='band';'频带'='band'}
    $all=New-Object 'System.Collections.Generic.List[object]';$v=@{}
    foreach($line in ((Raw wireless) -split '\r?\n')){if($line -notmatch '^\s*([^:]+):\s*(.*)$'){continue};$key=$aliases[($Matches[1].Trim() -replace '\s+',' ').ToLowerInvariant()];$value=$Matches[2].Trim();if(-not $key){continue};if($key -eq 'interface' -and $v.interface){$all.Add($v);$v=@{}};$v[$key]=if($key -match '^(channel|channel_width|rx_rate|tx_rate|signal_percent)$'){Get-WifiNumber $value}else{$value}}
    $all.Add($v);$v=@($all|Where-Object {if($o.interface){$_.interface -eq $o.interface}else{$_.ssid}}|Select-Object -First 1)[0];if(-not $v){$v=@{}}
    $mapping=@{interface='adapter';description='adapter';mac='adapter';current_phy='adapter';state='connection';ssid='connection';bssid='connection';authentication='connection';cipher='connection';band='connection';channel='connection';channel_width='connection';rx_rate='link';tx_rate='link';signal_percent='radio'}
    if($v.band -match '(2\.4|5|6)'){$v.band=$Matches[1]+' GHz'}elseif($v.channel){$v.band=if($v.channel -le 14){'2.4 GHz'}else{'5 GHz'}}
    foreach($k in $v.Keys){$unit=switch($k){channel_width{'MHz'};rx_rate{'Mbps'};tx_rate{'Mbps'};signal_percent{'%'};default{''}};Set-WifiField $r $mapping[$k] $k $v[$k] $unit 'netsh wlan'}
    if($v.authentication){Set-WifiField $r connection security $v.authentication '' 'netsh wlan'}
    if($null -ne $v.signal_percent){Set-WifiField $r radio rssi ([math]::Truncate($v.signal_percent/2-100)) 'dBm estimated' 'derived from signal percent'}
    try{$configs=@((Raw ip)|ConvertFrom-Json);$config=$configs|Where-Object {$_.interface -eq $v.interface}|Select-Object -First 1;if($config){foreach($k in 'ipv4','ipv6','gateway','dns_servers','subnet'){Set-WifiField $r ip $k $config.$k '' 'Get-NetIPConfiguration'}}}catch{$r.warnings+= 'IP configuration could not be parsed'}
    if($o.fast){Set-WifiMissing $r radio same_channel_networks 'disabled by --fast';Set-WifiMissing $r radio adjacent_channel_networks 'disabled by --fast'}
    elseif($v.channel -and (Raw nearby)){$channels=@([regex]::Matches((Raw nearby),'(?:Channel|频道)\s*:\s*(\d+)','IgnoreCase')|ForEach-Object {[int]$_.Groups[1].Value});if($channels.Count){Set-WifiField $r radio same_channel_networks ([math]::Max(0,@($channels|Where-Object {$_ -eq $v.channel}).Count-1)) networks 'wireless scan';Set-WifiField $r radio adjacent_channel_networks (@($channels|Where-Object {$_ -ne $v.channel -and [math]::Abs($_-$v.channel) -le 4}).Count) networks 'wireless scan'}}
    $gateway=Get-WifiValue $r ip gateway;if($gateway){Set-WifiField $r local_quality target $gateway '' 'default gateway'}else{Set-WifiMissing $r local_quality target 'default gateway not available'}
    $p=Read-WifiPing $cmd.gateway
    if($p){Set-WifiField $r local_quality reachable ($p.loss -lt 100) '' ping;Set-WifiField $r local_quality packet_loss $p.loss '%' ping;Set-WifiField $r local_quality latency $p.latency ms ping;Set-WifiField $r local_quality jitter $p.jitter ms ping}
    elseif($gateway){foreach($k in 'reachable','packet_loss','latency','jitter'){Set-WifiMissing $r local_quality $k 'ping did not produce a valid measurement' ping}}
    if($o.noPublic){foreach($k in @($r.sections.public_quality.Keys)){Set-WifiMissing $r public_quality $k 'disabled by --no-public-test'}}
    else{
        Set-WifiField $r public_quality target '223.5.5.5 / 223.6.6.6 / 119.29.29.29 / www.baidu.com / www.taobao.com' '' 'mainland China defaults'
        $results=@('public0','public1','public2'|ForEach-Object {Read-WifiPing $cmd[$_]}|Where-Object {$null -ne $_})
        if($results.Count){Set-WifiField $r public_quality reachable (@($results|Where-Object {$_.loss -lt 100}).Count -gt 0) '' 'multi-target ping';Set-WifiField $r public_quality packet_loss (Get-WifiMedian @($results|ForEach-Object {$_.loss})) '%' 'multi-target ping median';Set-WifiField $r public_quality latency (Get-WifiMedian @($results|ForEach-Object {$_.latency}|Where-Object {$null -ne $_})) ms 'multi-target ping median';Set-WifiField $r public_quality jitter (Get-WifiMedian @($results|ForEach-Object {$_.jitter}|Where-Object {$null -ne $_})) ms 'multi-target ping median'}
        else{foreach($k in 'reachable','packet_loss','latency','jitter'){Set-WifiMissing $r public_quality $k 'ping did not produce a valid measurement' ping}}
        $times=@('dns0','dns1'|Where-Object {$cmd[$_] -and $cmd[$_].status -eq 0 -and $cmd[$_].stdout -match 'address|地址'}|ForEach-Object {$cmd[$_].elapsed_ms});Set-WifiField $r public_quality dns_latency (Get-WifiMedian $times) ms 'system resolver command (includes process overhead)'
        if($o.speedtest){$speed=Get-WifiNumber (Raw speed);if($null -ne $speed){Set-WifiField $r public_quality download_speed ([math]::Round($speed*8/1000000,2)) Mbps 'Cloudflare 1 MB'}else{Set-WifiMissing $r public_quality download_speed 'download test failed'}}else{Set-WifiMissing $r public_quality download_speed 'enable with --speedtest'}
    }
    foreach($k in $cmd.Keys){if($cmd[$k].status -ne 0 -and $k -ne 'gateway' -and $k -notlike 'public*'){$r.warnings+="$k`: command failed or timed out ($($cmd[$k].status))"}};return $r
}
function Get-WifiCapture($o){
    $deadline=[datetime]::UtcNow.AddSeconds($o.budget)
    $inputData=@{platform='Windows';checked_at=[datetime]::UtcNow.ToString('o');architecture=$env:PROCESSOR_ARCHITECTURE;os_version=[Environment]::OSVersion.Version.ToString();commands=@{}}
    $ipScript='[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-NetIPConfiguration | ForEach-Object { [pscustomobject]@{interface=$_.InterfaceAlias;ipv4=($_.IPv4Address.IPAddress|Select-Object -First 1);ipv6=($_.IPv6Address.IPAddress|Select-Object -First 1);gateway=($_.IPv4DefaultGateway.NextHop|Select-Object -First 1);dns_servers=@($_.DNSServer.ServerAddresses)} }) | ConvertTo-Json -Depth 4 -Compress'
    $inputData.commands=Invoke-WifiBatch @{wireless=@('netsh.exe','wlan','show','interfaces');ip=@('powershell.exe','-NoProfile','-NonInteractive','-Command',$ipScript)} $o.timeout $deadline
    $first=Convert-WifiCapture $inputData $o;$gateway=Get-WifiValue $first ip gateway;$specs=@{}
    if($gateway){$specs.gateway=@('ping.exe','-n','3','-w','1000',[string]$gateway)}
    if(-not $o.noPublic){$i=0;foreach($target in '223.5.5.5','223.6.6.6','119.29.29.29'){$specs["public$i"]=@('ping.exe','-n','3','-w','1000',$target);$i++};$i=0;foreach($hostName in 'www.baidu.com','www.taobao.com'){$specs["dns$i"]=@('nslookup.exe',$hostName);$i++};if($o.speedtest){$specs.speed=@('curl.exe','--silent','--show-error','--fail','--max-time',[string]$o.timeout,'-o','NUL','-w','%{speed_download}','https://speed.cloudflare.com/__down?bytes=1000000')}}
    if(-not $o.fast){$specs.nearby=@('netsh.exe','wlan','show','networks','mode=bssid')}
    $more=Invoke-WifiBatch $specs $o.timeout $deadline;foreach($k in $more.Keys){$inputData.commands[$k]=$more[$k]};return $inputData
}
