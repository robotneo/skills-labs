# PowerShell 5.1 report engine. All strings and field order come from contract.json.
function New-WifiReport {
    $sections = [ordered]@{}
    foreach ($s in $Contract.fields.PSObject.Properties) {
        $fields = [ordered]@{}
        foreach ($k in $s.Value) { $fields[$k] = [ordered]@{value=$null;unit='';availability='unavailable';source='';reason='not provided by operating system'} }
        $sections[$s.Name]=$fields
    }
    return [ordered]@{schema_version='2.0';sections=$sections;diagnosis=@{};warnings=@()}
}
function Set-WifiField($r,$s,$k,$v,$unit='',$source='') {
    if ($null -ne $v -and "$v" -ne '') { $r.sections[$s][$k]=[ordered]@{value=$v;unit=$unit;availability='available';source=$source;reason=''} }
}
function Set-WifiMissing($r,$s,$k,$reason,$source='') { $r.sections[$s][$k]=[ordered]@{value=$null;unit='';availability='unavailable';source=$source;reason=$reason} }
function Get-WifiValue($r,$s,$k) { $f=$r.sections[$s][$k]; if($f.availability -eq 'available'){return $f.value}; return $null }
function Convert-WifiHashtable($value,$datePrefix='') {
    if($null -eq $value){return $null}
    if($value -is [System.Management.Automation.PSCustomObject]) { $h=[ordered]@{};foreach($p in $value.PSObject.Properties){$h[$p.Name]=Convert-WifiHashtable $p.Value $datePrefix};return $h }
    if($value -is [array]){return ,@($value|ForEach-Object {Convert-WifiHashtable $_ $datePrefix})}
    if($datePrefix -and $value -is [string] -and $value.StartsWith($datePrefix)){return $value.Substring($datePrefix.Length)}
    return $value
}
function Read-WifiJson([string]$text){
    # ConvertFrom-Json on some PS versions silently converts ISO strings to
    # DateTime and loses their original offset/precision. Protect string tokens.
    $prefix='wifi-date-'+[guid]::NewGuid().ToString()+':'
    $safe=[regex]::Replace($text,'"(?:\\.|[^"\\])*"',{
        param($m)
        if($m.Value -match '^"\d{4}-\d{2}-\d{2}T'){return '"'+$prefix+$m.Value.Substring(1)}
        return $m.Value
    })
    return Convert-WifiHashtable ($safe|ConvertFrom-Json) $prefix
}
function Get-WifiDiagnosis($r) {
    $score=100;$observed=0;$issues=New-Object 'System.Collections.Generic.List[string]';$recs=New-Object 'System.Collections.Generic.List[object]'
    $cats=[ordered]@{signal=100;interference=100;link=100;local=100;public=100;security=100}
    function Add-Advice($id,$priority,$reason,$issue=$true){if($issue){$issues.Add($id)};$recs.Add([ordered]@{id=$id;priority=$priority;reason=$reason;action=$Contract.actions.$id})}
    $rssi=Get-WifiValue $r radio rssi;$snr=Get-WifiValue $r radio snr;$same=Get-WifiValue $r radio same_channel_networks;$band=Get-WifiValue $r connection band;$rate=Get-WifiValue $r link tx_rate
    $loss=Get-WifiValue $r local_quality packet_loss;$lat=Get-WifiValue $r local_quality latency;$pub=Get-WifiValue $r public_quality packet_loss;$dns=Get-WifiValue $r public_quality dns_latency
    if($null -ne $rssi){$observed++;if($rssi -lt -75){$score-=30;$cats.signal-=60;Add-Advice weak_signal high ('RSSI {0:F0} dBm' -f $rssi)}elseif($rssi -lt -67){$score-=15;$cats.signal-=30;Add-Advice moderate_signal medium ('RSSI {0:F0} dBm' -f $rssi)}}
    elseif($null -ne $snr){$observed++;if($snr -lt 15){$score-=30;$cats.signal-=60}elseif($snr -lt 25){$score-=15;$cats.signal-=30}}
    if($null -ne $same){$observed++;if($same -ge 4){$score-=10;$cats.interference-=35;Add-Advice channel_congestion medium ("$([int]$same) nearby networks share the channel")}}
    if($band){$observed++;if(([string]$band).StartsWith('2.4') -and $null -ne $same -and $same -ge 4){Add-Advice prefer_higher_band medium 'The 2.4 GHz channel is congested' $false}}
    if($null -ne $rate){$observed++;if($rate -lt 20){$score-=20;$cats.link-=60}elseif($rate -lt 50){$score-=10;$cats.link-=30}}
    if($null -ne $loss){$observed++;if($loss -gt 3){$deduction=[math]::Min(30,[math]::Floor($loss*2));$score-=$deduction;$cats.local-=[math]::Min(70,$deduction*2);Add-Advice gateway_loss high ('Gateway packet loss {0:F1}%' -f $loss)}}
    if($null -ne $lat){$observed++;if($lat -gt 50){$score-=10;$cats.local-=30}}
    if($null -ne $pub){$observed++;if($pub -gt 3 -and ($null -eq $loss -or $loss -le 1)){$score-=8;$cats.public-=30;Add-Advice upstream_loss medium 'Public loss is elevated while the gateway is stable'}}
    if($null -ne $dns){$observed++;if($dns -gt 250){$score-=5;$cats.public-=15;Add-Advice slow_dns medium ('DNS lookup took {0:F0} ms' -f $dns)}}
    $security="$(Get-WifiValue $r connection security) $(Get-WifiValue $r connection authentication)"
    if($security){$observed++;if($security -match 'open|wep|开放'){$score-=20;$cats.security-=70;Add-Advice weak_security high 'Open or obsolete Wi-Fi security was detected'}}
    $score=[math]::Max(0,[math]::Min(100,$score));$confidence=$observed*10
    $verdict=if($confidence -lt 25){'insufficient_data'}elseif($score -ge 85){'healthy'}elseif($score -ge 65){'warning'}else{'poor'}
    if($recs.Count -eq 0 -and $confidence -ge 25){Add-Advice no_action low 'No material issue was observed' $false}
    return [ordered]@{score=$score;confidence_percent=$confidence;verdict=$verdict;category_scores=$cats;issues=@($issues.ToArray());recommendations=@($recs.ToArray())}
}
function Protect-WifiReport($r){
    foreach($section in $r.sections.Values){foreach($k in @($section.Keys)){
        $f=$section[$k];if($null -eq $f.value){continue};$t=[string]$f.value
        switch -Regex ($k){
            '^(ssid|dns_servers)$' {$f.value='***';break}
            '^(mac|bssid)$' {$p=$t -split '[:-]';$f.value=if($p.Count -eq 6){($p[0],$p[1],'**','**',$p[4],$p[5]) -join ':'}else{'***'};break}
            '^(ipv4|gateway)$' {$p=$t -split '\.';if($p.Count -eq 4){$f.value=($p[0],$p[1],'***',$p[3]) -join '.'};break}
            '^ipv6$' {$f.value=($t -split ':')[0]+':***';break}
        }
    }}
}
function Escape-WifiText($v){
    if(($v -is [double] -or $v -is [single] -or $v -is [decimal]) -and $v -eq [math]::Truncate($v)){
        $v=$v.ToString('0',[Globalization.CultureInfo]::InvariantCulture)
    }
    if($v -is [array]){$v=$v -join ', '}
    return ([string]$v).Replace('|','\|').Replace("`r`n",'<br>').Replace("`n",'<br>').Replace("`r",'<br>')
}
function Format-WifiField($r,$s,$k,$zh){
    $f=$r.sections[$s][$k]
    if($f.availability -ne 'available' -or $null -eq $f.value){$reason=$f.reason;if($zh -and $Contract.REASON_ZH.$reason){$reason=$Contract.REASON_ZH.$reason};if($zh){return "—（系统未提供：$reason）"};return "— (Unavailable: $reason)"}
    $v=$f.value;if($v -is [bool]){$v=if($zh){if($v){'是'}else{'否'}}else{if($v){'Yes'}else{'No'}}}
    $shown=Escape-WifiText $v;if($f.unit){$shown+=' '+$f.unit};return $shown
}
function Format-WifiReport($r,$language){
    $zh=$language -eq 'zh';$d=$r.diagnosis;$lines=New-Object 'System.Collections.Generic.List[string]'
    function L([string]$text=''){$lines.Add($text)}
    function F($s,$k){Format-WifiField $r $s $k $zh}
    L $(if($zh){'# 📶 Wi-Fi 健康报告'}else{'# 📶 Wi-Fi Health Report'});L
    $checked=if($zh){'检测时间'}else{'Checked'};$system=if($zh){'系统'}else{'System'};$interface=if($zh){'接口'}else{'Interface'}
    L "> ${checked}: $(F system checked_at)　|　${system}: $(F system os)　|　${interface}: $(F adapter interface)";L
    L $(if($zh){'| 健康状态 | 健康评分 | 数据置信度 |'}else{'| Health | Score | Data Confidence |'});L '| :---: | :---: | :---: |'
    L "| $($Contract.BADGES.$language.($d.verdict)) | **$($d.score)/100** | **$($d.confidence_percent)%** |";L
    L $(if($zh){'## ⭐ 核心参数'}else{'## ⭐ Core Metrics'});L
    L $(if($zh){'| 核心参数 | 当前值 |'}else{'| Metric | Current Value |'});L '| --- | --- |'
    $labels=if($zh){$Contract.ZH_CORE_ROW_LABELS}else{$Contract.EN_CORE_ROW_LABELS}
    L "| $($labels[0]) | $(F system os) $(F system os_version) |"
    $paths='system.architecture','adapter.mac','connection.ssid','adapter.interface','connection.band','connection.channel','connection.channel_width','radio.rssi','radio.snr','link.tx_rate','link.rx_rate','local_quality.latency','local_quality.jitter','local_quality.packet_loss','public_quality.latency','public_quality.packet_loss','connection.security'
    for($i=0;$i -lt $paths.Count;$i++){$p=$paths[$i].Split('.');L "| $($labels[$i+1]) | $(F $p[0] $p[1]) |"}
    foreach($s in 'local_quality','public_quality'){
        L
        if($s -eq 'local_quality'){L $(if($zh){'## 🏠 本地网络质量'}else{'## 🏠 Local Network Quality'});$names='target','reachable','latency','jitter','packet_loss';$labels=if($zh){$Contract.ZH_LOCAL_ROW_LABELS}else{$Contract.EN_LOCAL_ROW_LABELS}}
        else{L $(if($zh){'## 🌐 公网质量'}else{'## 🌐 Public Network Quality'});$names='target','reachable','dns_latency','latency','jitter','packet_loss','download_speed';$labels=if($zh){$Contract.ZH_PUBLIC_ROW_LABELS}else{$Contract.EN_PUBLIC_ROW_LABELS}}
        L;L $(if($zh){'| 参数 | 当前值 | 状态 |'}else{'| Parameter | Current Value | Status |'});L '| --- | --- | :---: |'
        for($i=0;$i -lt $names.Count;$i++){$k=$names[$i];$available=$r.sections[$s][$k].availability -eq 'available';$state=if($zh){if($available){'可用'}else{'不可用'}}else{if($available){'Available'}else{'Unavailable'}};L "| $($labels[$i]) | $(F $s $k) | $state |"}
    }
    L;L $(if($zh){'## 🧭 诊断与建议'}else{'## 🧭 Diagnostics & Recommendations'});L;L $(if($zh){'### 主要问题'}else{'### Main Issues'});L
    if($d.issues.Count){foreach($id in $d.issues){L ('- '+$(if($zh){$Contract.ZH_ISSUES.$id}else{$Contract.EN_ISSUES.$id}))}}else{L $(if($zh){'- 未发现明确问题'}else{'- No specific issue was identified'})}
    L;L $(if($zh){'### 优化建议'}else{'### Recommendations'});L
    if(-not $d.recommendations.Count){L $(if($zh){'- 暂无建议'}else{'- No recommendation'})}
    $i=0;foreach($item in $d.recommendations){$i++;$reason=$item.reason;$action=$item.action;$priority=(Get-Culture).TextInfo.ToTitleCase($item.priority)
        if($zh){$n=[regex]::Match($reason,'-?[\d.]+').Value;$reasons=@{weak_signal="RSSI 为 $n dBm";moderate_signal="RSSI 为 $n dBm";channel_congestion="当前信道附近检测到 $n 个同信道网络";gateway_loss="网关丢包率为 $n%";slow_dns="DNS 解析耗时 $n ms";upstream_loss='本地网关稳定，但公网链路丢包偏高';weak_security='检测到开放或已过时的 Wi-Fi 安全配置';no_action='未发现需要处理的明显问题'};if($reasons[$item.id]){$reason=$reasons[$item.id]};$action=$Contract.ZH_RECOMMENDATIONS.($item.id);$priority=@{high='高';medium='中';low='低'}[$item.priority]}
        L "$i. **[$priority]** $(Escape-WifiText $reason) — $(Escape-WifiText $action)"
    }
    return ($lines.ToArray() -join "`n")+"`n"
}
function Assert-WifiReport($r){
    if($r.schema_version -ne '2.0'){throw 'Invalid report schema'}
    foreach($s in $Contract.fields.PSObject.Properties){foreach($k in $s.Value){$f=$r.sections[$s.Name][$k];if(-not $f -or $f.availability -notin 'available','unavailable' -or ($f.availability -eq 'unavailable' -and ($null -ne $f.value -or -not $f.reason)) -or ($f.availability -eq 'available' -and $null -eq $f.value)){throw "Invalid report field $($s.Name).$k"}}}
}
function ConvertTo-WifiCsvLiteral($value){
    if($value -is [string] -and $value -match '^\s*[=+@-]'){return "'"+$value}
    return $value
}
function Export-WifiCsv($r){
    $rows=@(foreach($s in $Contract.fields.PSObject.Properties){foreach($k in $s.Value){$f=$r.sections[$s.Name][$k];$v=$f.value;if($v -is [array]){$v=ConvertTo-Json -InputObject $v -Compress};[pscustomobject][ordered]@{section=$s.Name;field=$k;value=(ConvertTo-WifiCsvLiteral $v);unit=(ConvertTo-WifiCsvLiteral $f.unit);availability=$f.availability;source=(ConvertTo-WifiCsvLiteral $f.source);reason=(ConvertTo-WifiCsvLiteral $f.reason)}}})
    return (($rows|ConvertTo-Csv -NoTypeInformation) -join "`r`n")+"`r`n"
}
