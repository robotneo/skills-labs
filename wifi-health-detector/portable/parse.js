/* Shared native-command capture protocol. Capture data is never executed. */
var WifiParse=(function(){
    'use strict';
    var core=typeof WifiCore!=='undefined'?WifiCore:require('./core.js');
    function trim(s){return String(s).replace(/^\s+|\s+$/g,'');}
    function number(s){var m=String(s).match(/-?\d+(?:[.,]\d+)?/);return m?Number(m[0].replace(',','.')):null;}
    function median(a){if(!a.length)return null;a.sort(function(x,y){return x-y;});var n=a.length;return Math.round((n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2)*1000)/1000;}
    function ping(item){
        if(!item||item.status===124||item.status===127)return null;
        var text=item.stdout||'';
        if(/transmit failed|general failure|permission denied|operation not permitted|sendto:|network is unreachable|传输失败|常见故障|一般故障|拒绝访问/i.test(text+(item.stderr||'')))return null;
        var loss=text.match(/([\d.]+)%\s*(?:packet loss|loss|丢失)/i);
        if(!loss)return null;
        var unix=text.match(/(?:round-trip|rtt) min\/avg\/max\/(?:stddev|mdev)\s*=\s*[\d.]+\/([\d.]+)\/[\d.]+\/([\d.]+)/i),win=text.match(/(?:Average|平均)\s*=\s*([\d.]+)ms/i);
        var result={loss:Number(loss[1]),latency:null,jitter:null};
        if(unix){result.latency=Number(unix[1]);result.jitter=Number(unix[2]);}
        else if(win){result.latency=Number(win[1]);var lo=text.match(/(?:Minimum|最短)\s*=\s*([\d.]+)ms/i),hi=text.match(/(?:Maximum|最长)\s*=\s*([\d.]+)ms/i);if(lo&&hi)result.jitter=Number(hi[1])-Number(lo[1]);}return result;
    }
    var mappings={interface:['adapter','interface'],description:['adapter','description'],mac:['adapter','mac'],state:['connection','state'],ssid:['connection','ssid'],bssid:['connection','bssid'],security:['connection','security'],authentication:['connection','authentication'],cipher:['connection','cipher'],band:['connection','band'],channel:['connection','channel'],channel_width:['connection','channel_width','MHz'],rssi:['radio','rssi','dBm'],noise:['radio','noise','dBm'],snr:['radio','snr','dB'],signal_percent:['radio','signal_percent','%'],tx_rate:['link','tx_rate','Mbps'],rx_rate:['link','rx_rate','Mbps'],max_rate:['link','max_rate','Mbps'],mcs:['link','mcs'],current_phy:['adapter','current_phy'],firmware:['adapter','firmware'],country_code:['adapter','country_code'],supported_phy:['adapter','supported_phy']};
    function apply(r,values,source){Object.keys(values).forEach(function(k){var m=mappings[k];if(m)core.set(r,m[0],m[1],values[k],m[2],source);});}
    function macValues(text){var v={},current=false,indent=0;
        text.split(/\r?\n/).forEach(function(line){var m=line.match(/^(\s*)([^:]+):\s*(.*)$/);if(!m)return;var key=trim(m[2]),value=trim(m[3]);
            if(key==='Current Network Information'){current=true;indent=-1;return;}
            if(current&&indent===-1){v.ssid=trim(line).replace(/:$/,'');indent=m[1].length;return;}
            if(current&&m[1].length<=indent)current=false;
            var general={'Firmware Version':'firmware','Country Code':'country_code','Supported PHY Modes':'supported_phy','Card Type':'description'};
            if(general[key]&&!v[general[key]])v[general[key]]=value;
            if(!current)return;
            var aliases={'PHY Mode':'current_phy','BSSID':'bssid','Security':'security'};if(aliases[key])v[aliases[key]]=value;
            if(key==='Channel'){v.channel=number(value);var width=value.match(/(\d+)\s*MHz/i);if(width)v.channel_width=Number(width[1]);var band=value.match(/(2\.4|5|6)\s*GHz/i);if(band)v.band=band[1]+' GHz';}
            if(key==='Signal / Noise'){var parts=value.match(/(-?\d+)\s*dBm\s*\/\s*(-?\d+)/i);if(parts){v.rssi=Number(parts[1]);v.noise=Number(parts[2]);}}
            if(key==='Transmit Rate')v.tx_rate=number(value);
        });return v;
    }
    function airportValues(text){var v={},aliases={agrctlrssi:'rssi',agrctlnoise:'noise',lasttxrate:'tx_rate',maxrate:'max_rate',bssid:'bssid',ssid:'ssid',mcs:'mcs',state:'state','802.11 auth':'authentication','link auth':'security'};text.split(/\r?\n/).forEach(function(line){var m=line.match(/^\s*([^:]+):\s*(.*)$/);if(!m)return;var k=trim(m[1]).toLowerCase(),x=trim(m[2]);if(k==='channel'){v.channel=number(x);var w=x.match(/,\s*(\d+)/);if(w)v.channel_width=Number(w[1]);}else if(aliases[k])v[aliases[k]]=/^(rssi|noise|tx_rate|max_rate|mcs)$/.test(aliases[k])?number(x):x;});return v;}
    function winValues(text,requested){var aliases={'name':'interface','名称':'interface','description':'description','描述':'description','physical address':'mac','物理地址':'mac','state':'state','状态':'state','ssid':'ssid','bssid':'bssid','radio type':'current_phy','无线电类型':'current_phy','authentication':'authentication','身份验证':'authentication','cipher':'cipher','密码':'cipher','channel':'channel','频道':'channel','channel width':'channel_width','信道宽度':'channel_width','频道宽度':'channel_width','receive rate (mbps)':'rx_rate','接收速率(mbps)':'rx_rate','transmit rate (mbps)':'tx_rate','传输速率(mbps)':'tx_rate','signal':'signal_percent','信号':'signal_percent','band':'band','频带':'band'},all=[],v={};
        text.split(/\r?\n/).forEach(function(line){var m=line.match(/^\s*([^:]+):\s*(.*)$/);if(!m)return;var k=aliases[trim(m[1]).replace(/\s+/g,' ').toLowerCase()];if(!k)return;if(k==='interface'&&v.interface){all.push(v);v={};}v[k]=/^(channel|channel_width|rx_rate|tx_rate|signal_percent)$/.test(k)?number(m[2]):trim(m[2]);});all.push(v);v=all.filter(function(x){return requested?x.interface===requested:!!x.ssid;})[0]||{};if(v.authentication)v.security=v.authentication;if(v.band){var b=v.band.match(/2\.4|5|6/);if(b)v.band=b[0]+' GHz';}return v;
    }
    function capture(input,c,o){
        var r=core.empty(c),cmd=input.commands||{},windows=input.platform==='Windows',source=windows?'netsh wlan':'macOS wireless tools';
        function raw(k){return cmd[k]&&cmd[k].status===0?cmd[k].stdout||'':'';}
        core.set(r,'system','os',input.platform);core.set(r,'system','checked_at',input.checked_at||new Date().toISOString());core.set(r,'system','architecture',trim(raw('arch'))||input.architecture);core.set(r,'system','os_version',trim(raw('version'))||input.os_version);core.set(r,'system','build',trim(raw('build'))||input.build);core.set(r,'system','privilege','current user');core.missing(r,'system','python_version','Python is not used by this engine','runtime');
        var v=windows?winValues(raw('wireless'),o.interface):macValues(raw('wireless'));
        if(!windows){var a=airportValues(raw('airport'));Object.keys(a).forEach(function(k){v[k]=a[k];});var hardware=raw('hardware').match(/Hardware Port:\s*(?:Wi-Fi|AirPort)\s*\r?\nDevice:\s*(\S+)/i);v.interface=o.interface||(hardware?hardware[1]:null);core.missing(r,'link','rx_rate','macOS does not expose the current receive PHY rate',source);}
        if(v.rssi!==undefined&&v.noise!==undefined)v.snr=v.rssi-v.noise;
        if(v.channel&&!v.band)v.band=v.channel<=14?'2.4 GHz':'5 GHz';
        apply(r,v,source);
        if(v.signal_percent!==undefined)core.set(r,'radio','rssi',Math.trunc?Math.trunc(v.signal_percent/2-100):Math.ceil(v.signal_percent/2-100),'dBm estimated','derived from signal percent');
        if(v.rssi!==undefined)core.set(r,'radio','signal_level',v.rssi>=-60?'strong':v.rssi>=-67?'good':v.rssi>=-75?'weak':'poor','','derived from RSSI');
        if(v.interface){
            if(windows){try{var configs=JSON.parse(raw('ip')||'[]');if(!Array.isArray(configs))configs=[configs];var config=configs.filter(function(x){return x.interface===v.interface;})[0];if(config)['ipv4','ipv6','gateway','dns_servers','subnet'].forEach(function(k){core.set(r,'ip',k,config[k],'','Get-NetIPConfiguration');});}catch(e){r.warnings.push('IP configuration could not be parsed');}}
            else{var blocks=raw('ip').split(/\n(?=\S)/),block=blocks.filter(function(x){return x.indexOf(v.interface+':')===0;})[0]||'';[['mac',/\bether\s+([\da-f:]+)/i,'adapter'],['ipv4',/\binet\s+([\d.]+)/,'ip'],['ipv6',/\binet6\s+([^\s%]+)/,'ip'],['subnet',/\bnetmask\s+(\S+)/,'ip'],['status',/\bstatus:\s*(\S+)/,'adapter']].forEach(function(spec){var m=block.match(spec[1]);if(m)core.set(r,spec[2],spec[0],m[1],'','ifconfig');});raw('routes').split(/\r?\n/).some(function(line){var cols=trim(line).split(/\s+/);if(cols[0]==='default'&&cols.indexOf(v.interface)>=0&&/^[\d.]+$/.test(cols[1])){core.set(r,'ip','gateway',cols[1],'','netstat');return true;}return false;});var servers=[],re=/nameserver\[\d+\]\s*:\s*(\S+)/g,m;while((m=re.exec(raw('dnsconfig'))))if(servers.indexOf(m[1])<0)servers.push(m[1]);if(servers.length)core.set(r,'ip','dns_servers',servers,'','scutil');}
        }
        if(o.fast){core.missing(r,'radio','same_channel_networks','disabled by --fast');core.missing(r,'radio','adjacent_channel_networks','disabled by --fast');}
        else if(v.channel&&raw('nearby')){var channels=[],re=windows?/(?:Channel|频道)\s*:\s*(\d+)/gi:/\s-?\d+\s+(\d+)(?:,[+-]?\d+)?\s/g,m;while((m=re.exec(raw('nearby'))))channels.push(Number(m[1]));if(channels.length){core.set(r,'radio','same_channel_networks',Math.max(0,channels.filter(function(x){return x===v.channel;}).length-1),'networks','wireless scan');core.set(r,'radio','adjacent_channel_networks',channels.filter(function(x){return x!==v.channel&&Math.abs(x-v.channel)<=4;}).length,'networks','wireless scan');}}
        var gateway=core.val(r,'ip','gateway'),local=ping(cmd.gateway);
        if(gateway)core.set(r,'local_quality','target',gateway,'','default gateway');else core.missing(r,'local_quality','target','default gateway not available');
        function quality(section,p){if(!p)return;core.set(r,section,'reachable',p.loss<100,'','ping');core.set(r,section,'packet_loss',p.loss,'%','ping');core.set(r,section,'latency',p.latency,'ms','ping');core.set(r,section,'jitter',p.jitter,'ms','ping');}quality('local_quality',local);
        if(!local&&gateway)['reachable','packet_loss','latency','jitter'].forEach(function(k){core.missing(r,'local_quality',k,'ping did not produce a valid measurement','ping');});
        if(o.noPublic)Object.keys(r.sections.public_quality).forEach(function(k){core.missing(r,'public_quality',k,'disabled by --no-public-test');});
        else{core.set(r,'public_quality','target','223.5.5.5 / 223.6.6.6 / 119.29.29.29 / www.baidu.com / www.taobao.com','','mainland China defaults');var results=['public0','public1','public2'].map(function(k){return ping(cmd[k]);}).filter(Boolean),latencies=results.map(function(x){return x.latency;}).filter(function(x){return x!==null;}),jitters=results.map(function(x){return x.jitter;}).filter(function(x){return x!==null;});if(results.length){core.set(r,'public_quality','reachable',results.some(function(x){return x.loss<100;}),'','multi-target ping');core.set(r,'public_quality','packet_loss',median(results.map(function(x){return x.loss;})),'%','multi-target ping median');core.set(r,'public_quality','latency',median(latencies),'ms','multi-target ping median');core.set(r,'public_quality','jitter',median(jitters),'ms','multi-target ping median');}else ['reachable','packet_loss','latency','jitter'].forEach(function(k){core.missing(r,'public_quality',k,'ping did not produce a valid measurement','ping');});
            var times=['dns0','dns1'].filter(function(k){return cmd[k]&&cmd[k].status===0&&/address|ip_address|地址/i.test(cmd[k].stdout);}).map(function(k){return cmd[k].elapsed_ms;});core.set(r,'public_quality','dns_latency',median(times),'ms','system resolver command (includes process overhead)');
            if(o.speedtest){var bytes=number(raw('speed'));if(bytes!==null)core.set(r,'public_quality','download_speed',Math.round(bytes*8/1000000*100)/100,'Mbps','Cloudflare 1 MB');else core.missing(r,'public_quality','download_speed','download test failed');}else core.missing(r,'public_quality','download_speed','enable with --speedtest');
        }
        Object.keys(cmd).forEach(function(k){if(cmd[k].status!==0&&k!=='gateway'&&k.indexOf('public')!==0)r.warnings.push(k+': command failed or timed out ('+cmd[k].status+')');});return r;
    }
    function initial(platform,o){if(platform==='Darwin')return {hardware:['/usr/sbin/networksetup','-listallhardwareports'],ip:['/sbin/ifconfig','-a'],routes:['/usr/sbin/netstat','-rn','-f','inet'],wireless:['/usr/sbin/system_profiler','SPAirPortDataType'],airport:['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport','-I'],dnsconfig:['/usr/sbin/scutil','--dns'],version:['/usr/bin/sw_vers','-productVersion'],build:['/usr/bin/sw_vers','-buildVersion'],arch:['/usr/bin/uname','-m']};
        return {wireless:['netsh.exe','wlan','show','interfaces'],ip:['powershell.exe','-NoProfile','-NonInteractive','-Command',"[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-NetIPConfiguration | ForEach-Object { [pscustomobject]@{interface=$_.InterfaceAlias;ipv4=($_.IPv4Address.IPAddress|Select-Object -First 1);ipv6=($_.IPv6Address.IPAddress|Select-Object -First 1);gateway=($_.IPv4DefaultGateway.NextHop|Select-Object -First 1);dns_servers=@($_.DNSServer.ServerAddresses)} }) | ConvertTo-Json -Depth 4 -Compress"]};
    }
    function network(platform,gateway,o){var specs={},win=platform==='Windows';function pingArgs(target){return win?['ping.exe','-n','3','-w','1000',target]:['/sbin/ping','-c','3','-W','1000',target];}if(gateway)specs.gateway=pingArgs(String(gateway));if(!o.noPublic){['223.5.5.5','223.6.6.6','119.29.29.29'].forEach(function(t,i){specs['public'+i]=pingArgs(t);});['www.baidu.com','www.taobao.com'].forEach(function(t,i){specs['dns'+i]=win?['nslookup.exe',t]:['/usr/bin/dscacheutil','-q','host','-a','name',t];});if(o.speedtest)specs.speed=[win?'curl.exe':'/usr/bin/curl','--silent','--show-error','--fail','--max-time',String(o.timeout),'-o',win?'NUL':'/dev/null','-w','%{speed_download}','https://speed.cloudflare.com/__down?bytes=1000000'];}if(!o.fast)specs.nearby=win?['netsh.exe','wlan','show','networks','mode=bssid']:['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport','-s'];return specs;}
    return {capture:capture,initial:initial,network:network,ping:ping,winValues:winValues,macValues:macValues};
}());
if(typeof module!=='undefined')module.exports=WifiParse;
