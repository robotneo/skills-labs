/* ES5-compatible: the same deterministic report core runs in Node and macOS JXA.
 * No network, subprocesses, eval of data, or host-specific APIs here. */
var WifiCore = (function () {
    'use strict';
    function empty(c) {
        var r = {schema_version:'2.0', sections:{}, diagnosis:{}, warnings:[]};
        Object.keys(c.fields).forEach(function(s) { r.sections[s]={}; c.fields[s].forEach(function(k) {
            r.sections[s][k]={value:null,unit:'',availability:'unavailable',source:'',reason:'not provided by operating system'};
        }); }); return r;
    }
    function set(r,s,k,v,u,src) {
        if (v === null || v === undefined || v === '') return;
        r.sections[s][k]={value:v,unit:u||'',availability:'available',source:src||'',reason:''};
    }
    function missing(r,s,k,reason,src) { r.sections[s][k]={value:null,unit:'',availability:'unavailable',source:src||'',reason:reason}; }
    function val(r,s,k) { var f=r.sections[s][k]; return f.availability==='available' ? f.value : null; }
    function diagnose(r,c) {
        var score=100, observed=0, issues=[], rec=[], cats={signal:100,interference:100,link:100,local:100,public:100,security:100};
        function add(id,priority,reason,issue) { if(issue!==false) issues.push(id); rec.push({id:id,priority:priority,reason:reason,action:c.actions[id]}); }
        var rssi=val(r,'radio','rssi'),snr=val(r,'radio','snr'),same=val(r,'radio','same_channel_networks'),band=val(r,'connection','band'),rate=val(r,'link','tx_rate');
        var loss=val(r,'local_quality','packet_loss'),lat=val(r,'local_quality','latency'),pub=val(r,'public_quality','packet_loss'),dns=val(r,'public_quality','dns_latency');
        if(rssi!==null) { observed++; if(rssi < -75) {score-=30;cats.signal-=60;add('weak_signal','high','RSSI '+Number(rssi).toFixed(0)+' dBm');}
            else if(rssi < -67) {score-=15;cats.signal-=30;add('moderate_signal','medium','RSSI '+Number(rssi).toFixed(0)+' dBm');} }
        else if(snr!==null) {observed++;if(snr<15){score-=30;cats.signal-=60;}else if(snr<25){score-=15;cats.signal-=30;}}
        if(same!==null) {observed++;if(same>=4){score-=10;cats.interference-=35;add('channel_congestion','medium',Math.trunc ? Math.trunc(same)+' nearby networks share the channel' : parseInt(same,10)+' nearby networks share the channel');}}
        if(band) {observed++;if(String(band).indexOf('2.4')===0 && same!==null && same>=4) add('prefer_higher_band','medium','The 2.4 GHz channel is congested',false);}
        if(rate!==null){observed++;if(rate<20){score-=20;cats.link-=60;}else if(rate<50){score-=10;cats.link-=30;}}
        if(loss!==null){observed++;if(loss>3){var deduction=Math.min(30,Math.floor(loss*2));score-=deduction;cats.local-=Math.min(70,deduction*2);add('gateway_loss','high','Gateway packet loss '+Number(loss).toFixed(1)+'%');}}
        if(lat!==null){observed++;if(lat>50){score-=10;cats.local-=30;}}
        if(pub!==null){observed++;if(pub>3&&(loss===null||loss<=1)){score-=8;cats.public-=30;add('upstream_loss','medium','Public loss is elevated while the gateway is stable');}}
        if(dns!==null){observed++;if(dns>250){score-=5;cats.public-=15;add('slow_dns','medium','DNS lookup took '+Number(dns).toFixed(0)+' ms');}}
        // Keep schema-2.0 scoring parity, including the existing security observation.
        var security=((val(r,'connection','security')||'')+' '+(val(r,'connection','authentication')||'')).toLowerCase();
        if(security){observed++;if(/open|wep|开放/.test(security)){score-=20;cats.security-=70;add('weak_security','high','Open or obsolete Wi-Fi security was detected');}}
        score=Math.max(0,Math.min(100,score));var confidence=observed*10;
        if(!rec.length&&confidence>=25)add('no_action','low','No material issue was observed',false);
        return {score:score,confidence_percent:confidence,verdict:confidence<25?'insufficient_data':score>=85?'healthy':score>=65?'warning':'poor',category_scores:cats,issues:issues,recommendations:rec};
    }
    function mask(k,v) {
        if(v===null)return v;var t=String(v),p;
        if(k==='ssid'||k==='dns_servers')return '***';
        if(k==='mac'||k==='bssid'){p=t.split(/[:-]/);return p.length===6?p.slice(0,2).concat(['**','**'],p.slice(-2)).join(':'):'***';}
        if(k==='ipv4'||k==='gateway'){p=t.split('.');if(p.length===4)return [p[0],p[1],'***',p[3]].join('.');}
        if(k==='ipv6')return t.split(':')[0]+':***';return v;
    }
    function masked(r,enabled) {
        var copy=JSON.parse(JSON.stringify(r));if(enabled)Object.keys(copy.sections).forEach(function(s){Object.keys(copy.sections[s]).forEach(function(k){if(/^(ssid|bssid|mac|ipv4|ipv6|gateway|dns_servers)$/.test(k))copy.sections[s][k].value=mask(k,copy.sections[s][k].value);});});return copy;
    }
    function escape(v){return String(Array.isArray(v)?v.join(', '):v).replace(/\|/g,'\\|').replace(/\r\n|\n|\r/g,'<br>');}
    function text(r,c,lang) {
        var zh=lang==='zh',d=r.diagnosis,lines=[];
        function field(s,k){var f=r.sections[s][k];if(f.availability!=='available'||f.value===null){var reason=zh?(c.REASON_ZH[f.reason]||f.reason):f.reason;return zh?'—（系统未提供：'+reason+'）':'— (Unavailable: '+reason+')';}var v=f.value;if(typeof v==='boolean')v=zh?(v?'是':'否'):(v?'Yes':'No');return escape(v)+(f.unit?' '+f.unit:'');}
        lines.push(zh?'# 📶 Wi-Fi 健康报告':'# 📶 Wi-Fi Health Report','', '> '+(zh?'检测时间':'Checked')+': '+field('system','checked_at')+'　|　'+(zh?'系统':'System')+': '+field('system','os')+'　|　'+(zh?'接口':'Interface')+': '+field('adapter','interface'),'');
        lines.push(zh?'| 健康状态 | 健康评分 | 数据置信度 |':'| Health | Score | Data Confidence |','| :---: | :---: | :---: |','| '+c.BADGES[lang][d.verdict]+' | **'+d.score+'/100** | **'+d.confidence_percent+'%** |','',zh?'## ⭐ 核心参数':'## ⭐ Core Metrics','',zh?'| 核心参数 | 当前值 |':'| Metric | Current Value |','| --- | --- |');
        var paths=['system.architecture','adapter.mac','connection.ssid','adapter.interface','connection.band','connection.channel','connection.channel_width','radio.rssi','radio.snr','link.tx_rate','link.rx_rate','local_quality.latency','local_quality.jitter','local_quality.packet_loss','public_quality.latency','public_quality.packet_loss','connection.security'];
        var values=[field('system','os')+' '+field('system','os_version')];paths.forEach(function(p){p=p.split('.');values.push(field(p[0],p[1]));});
        var labels=c[zh?'ZH_CORE_ROW_LABELS':'EN_CORE_ROW_LABELS'];values.forEach(function(v,i){lines.push('| '+labels[i]+' | '+v+' |');});
        [['local_quality',zh?'## 🏠 本地网络质量':'## 🏠 Local Network Quality',['target','reachable','latency','jitter','packet_loss'],c[zh?'ZH_LOCAL_ROW_LABELS':'EN_LOCAL_ROW_LABELS']],['public_quality',zh?'## 🌐 公网质量':'## 🌐 Public Network Quality',['target','reachable','dns_latency','latency','jitter','packet_loss','download_speed'],c[zh?'ZH_PUBLIC_ROW_LABELS':'EN_PUBLIC_ROW_LABELS']]].forEach(function(spec){lines.push('',spec[1],'',zh?'| 参数 | 当前值 | 状态 |':'| Parameter | Current Value | Status |','| --- | --- | :---: |');spec[2].forEach(function(k,i){var available=r.sections[spec[0]][k].availability==='available';lines.push('| '+spec[3][i]+' | '+field(spec[0],k)+' | '+(zh?(available?'可用':'不可用'):(available?'Available':'Unavailable'))+' |');});});
        lines.push('',zh?'## 🧭 诊断与建议':'## 🧭 Diagnostics & Recommendations','',zh?'### 主要问题':'### Main Issues','');
        if(d.issues.length)d.issues.forEach(function(id){lines.push('- '+c[zh?'ZH_ISSUES':'EN_ISSUES'][id]);});else lines.push(zh?'- 未发现明确问题':'- No specific issue was identified');
        lines.push('',zh?'### 优化建议':'### Recommendations','');
        if(!d.recommendations.length)lines.push(zh?'- 暂无建议':'- No recommendation');
        d.recommendations.forEach(function(item,i){var evidence=item.reason,num=(evidence.match(/-?[\d.]+/)||['—'])[0];if(zh){var reasons={weak_signal:'RSSI 为 '+num+' dBm',moderate_signal:'RSSI 为 '+num+' dBm',channel_congestion:'当前信道附近检测到 '+num+' 个同信道网络',gateway_loss:'网关丢包率为 '+num+'%',slow_dns:'DNS 解析耗时 '+num+' ms',upstream_loss:'本地网关稳定，但公网链路丢包偏高',weak_security:'检测到开放或已过时的 Wi-Fi 安全配置',no_action:'未发现需要处理的明显问题'};evidence=reasons[item.id]||evidence;}var priority=zh?{high:'高',medium:'中',low:'低'}[item.priority]:item.priority.charAt(0).toUpperCase()+item.priority.slice(1);lines.push((i+1)+'. **['+priority+']** '+escape(evidence)+' — '+escape(zh?c.ZH_RECOMMENDATIONS[item.id]:item.action));});return lines.join('\n')+'\n';
    }
    function csv(r,c){var rows=[['section','field','value','unit','availability','source','reason']];Object.keys(c.fields).forEach(function(s){c.fields[s].forEach(function(k){var f=r.sections[s][k];rows.push([s,k,f.value===null?'':Array.isArray(f.value)?JSON.stringify(f.value):f.value,f.unit,f.availability,f.source,f.reason]);});});return rows.map(function(row){return row.map(function(x){if(typeof x==='string'&&/^[\s]*[=+@-]/.test(x))x="'"+x;return '"'+String(x).replace(/"/g,'""')+'"';}).join(',');}).join('\r\n')+'\r\n';}
    function validate(r,c){if(r.schema_version!=='2.0')throw Error('Invalid schema');Object.keys(c.fields).forEach(function(s){c.fields[s].forEach(function(k){var f=r.sections[s]&&r.sections[s][k];if(!f||['available','unavailable'].indexOf(f.availability)<0||typeof f.reason!=='string'||(f.availability==='unavailable'&&(f.value!==null||!f.reason))||(f.availability==='available'&&(f.value===null||f.value===undefined)))throw Error('Invalid field '+s+'.'+k);});});}
    function options(args){var o={language:'zh',timeout:10,budget:35,view:'summary'},flags={'--mask':'mask','--speedtest':'speedtest','--no-public-test':'noPublic','--no-notify':'noNotify','--verbose':'verbose','--fast':'fast','--help':'help','-h':'help'},values={'--interface':'interface','--json':'json','--csv':'csv','--language':'language','--timeout':'timeout','--budget':'budget','--view':'view','--report-input':'reportInput','--capture-input':'captureInput','--engine':'engine'};for(var i=0;i<args.length;i++){var a=args[i];if(flags[a])o[flags[a]]=true;else if(values[a]){if(i+1>=args.length)throw Error('Missing value for '+a);o[values[a]]=args[++i];}else throw Error('Unknown argument '+a);}if(['zh','en'].indexOf(o.language)<0||o.view!=='summary')throw Error('Invalid language/view');['timeout','budget'].forEach(function(k){o[k]=Number(o[k]);if(!isFinite(o[k])||o[k]<1||Math.floor(o[k])!==o[k])throw Error(k+' must be a positive integer');});return o;}
    var help='Wi-Fi Health Detector\n--engine auto|python|native --interface NAME --language zh|en\n--timeout SECONDS --budget SECONDS --fast --no-public-test --speedtest\n--mask --json PATH --csv PATH --no-notify --verbose --view summary\n';
    return {empty:empty,set:set,missing:missing,val:val,diagnose:diagnose,masked:masked,text:text,csv:csv,validate:validate,options:options,help:help};
}());

/* Shared native-command capture protocol. Capture data is never executed. */
var WifiParse=(function(){
    'use strict';
    var core=WifiCore;
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

/* Foundation NSTask only: no Apple Events, Accessibility or GUI automation. */
function collectMac(o,c) {
    var input={platform:'Darwin',checked_at:new Date().toISOString(),commands:{}},deadline=Date.now()+o.budget*1000;
    var fm=$.NSFileManager.defaultManager,base=ObjC.unwrap($.NSTemporaryDirectory())+'wifi-health-'+ObjC.unwrap($.NSUUID.UUID.UUIDString);
    if(!fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError($(base),true,$.NSDictionary.dictionary,null))throw Error('Cannot create capture directory');
    function batch(specs){var active=[];
        Object.keys(specs).forEach(function(key){var args=specs[key],task=$.NSTask.alloc.init,path=base+'/'+key,handle,start=Date.now();
            if(start>=deadline){input.commands[key]={stdout:'',status:124,elapsed_ms:0};return;}
            try{fm.createFileAtPathContentsAttributes($(path),$.NSData.data,$.NSDictionary.dictionary);handle=$.NSFileHandle.fileHandleForWritingAtPath($(path));task.launchPath=$(args[0]);task.arguments=$(args.slice(1));task.standardOutput=handle;task.standardError=handle;task.standardInput=$.NSFileHandle.fileHandleWithNullDevice;task.launch;active.push({key:key,task:task,path:path,handle:handle,start:start,expires:Math.min(deadline,start+o.timeout*1000)});}
            catch(e){if(handle)handle.closeFile;input.commands[key]={stdout:'',status:127,elapsed_ms:Date.now()-start};}
        });
        while(active.length){for(var i=active.length-1;i>=0;i--){var p=active[i],timed=Date.now()>=p.expires;if(p.task.running&&!timed)continue;if(timed&&p.task.running){var stop=$.NSTask.alloc.init;stop.launchPath=$('/bin/kill');stop.arguments=$(['-KILL',String(p.task.processIdentifier)]);stop.launch;stop.waitUntilExit;p.task.waitUntilExit;}p.handle.closeFile;input.commands[p.key]={stdout:readFile(p.path),status:timed?124:Number(p.task.terminationStatus),elapsed_ms:Date.now()-p.start};active.splice(i,1);}if(active.length)$.NSThread.sleepForTimeInterval(0.02);}
    }
    try{batch(WifiParse.initial('Darwin',o));var first=WifiParse.capture(input,c,o);batch(WifiParse.network('Darwin',WifiCore.val(first,'ip','gateway'),o));return input;}
    finally{fm.removeItemAtPathError($(base),null);}
}

/* JXA is supplied by macOS; no Python, Node, third-party modules or GUI scripting. */
function readFile(path) {
    var value=$.NSString.stringWithContentsOfFileEncodingError($(path),$.NSUTF8StringEncoding,null);
    if(!value)throw Error('Cannot read '+path);return ObjC.unwrap(value);
}
function writeFile(path,text) {
    if(!$(text).writeToFileAtomicallyEncodingError($(path),true,$.NSUTF8StringEncoding,null))throw Error('Cannot write '+path);
}
function run(argv) {
    ObjC.import('Foundation');
    var own=ObjC.deepUnwrap($.NSProcessInfo.processInfo.arguments).filter(function(x){return /macos\.js$/.test(x);})[0];
    var dir=own.slice(0,own.lastIndexOf('/'));
    var c=JSON.parse(readFile(dir+'/contract.json')),o=WifiCore.options(argv);
    if(o.help)return WifiCore.help.replace(/\n$/,'');
    var r;
    if(o.reportInput)r=JSON.parse(readFile(o.reportInput));
    else {r=WifiParse.capture(o.captureInput?JSON.parse(readFile(o.captureInput)):collectMac(o,c),c,o);}
    WifiCore.validate(r,c);r.diagnosis=WifiCore.diagnose(r,c);r=WifiCore.masked(r,o.mask);
    if(o.json)writeFile(o.json,JSON.stringify(r,null,2)+'\n');
    if(o.csv)writeFile(o.csv,WifiCore.csv(r,c));
    if(!o.noNotify&&!o.reportInput&&!o.captureInput){var message=$('Enterprise notification: portable engine does not invoke the Python Bridge; report retained.\n').dataUsingEncoding($.NSUTF8StringEncoding);$.NSFileHandle.fileHandleWithStandardError.writeData(message);}
    return WifiCore.text(r,c,o.language).replace(/\n$/,'');
}

if(typeof module!=='undefined')module.exports={core:WifiCore,parser:WifiParse};
