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
    function csv(r,c){var rows=[['section','field','value','unit','availability','source','reason']];Object.keys(c.fields).forEach(function(s){c.fields[s].forEach(function(k){var f=r.sections[s][k];rows.push([s,k,f.value===null?'':Array.isArray(f.value)?JSON.stringify(f.value):f.value,f.unit,f.availability,f.source,f.reason]);});});return rows.map(function(row){return row.map(function(x){return '"'+String(x).replace(/"/g,'""')+'"';}).join(',');}).join('\r\n')+'\r\n';}
    function validate(r,c){if(r.schema_version!=='2.0')throw Error('Invalid schema');Object.keys(c.fields).forEach(function(s){c.fields[s].forEach(function(k){var f=r.sections[s]&&r.sections[s][k];if(!f||['available','unavailable'].indexOf(f.availability)<0||typeof f.reason!=='string'||(f.availability==='unavailable'&&(f.value!==null||!f.reason))||(f.availability==='available'&&(f.value===null||f.value===undefined)))throw Error('Invalid field '+s+'.'+k);});});}
    function options(args){var o={language:'zh',timeout:10,budget:35,view:'summary'},flags={'--mask':'mask','--speedtest':'speedtest','--no-public-test':'noPublic','--no-notify':'noNotify','--verbose':'verbose','--fast':'fast','--help':'help','-h':'help'},values={'--interface':'interface','--json':'json','--csv':'csv','--language':'language','--timeout':'timeout','--budget':'budget','--view':'view','--report-input':'reportInput','--capture-input':'captureInput','--engine':'engine'};for(var i=0;i<args.length;i++){var a=args[i];if(flags[a])o[flags[a]]=true;else if(values[a]){if(i+1>=args.length)throw Error('Missing value for '+a);o[values[a]]=args[++i];}else throw Error('Unknown argument '+a);}if(['zh','en'].indexOf(o.language)<0||o.view!=='summary')throw Error('Invalid language/view');['timeout','budget'].forEach(function(k){o[k]=Number(o[k]);if(!isFinite(o[k])||o[k]<1||Math.floor(o[k])!==o[k])throw Error(k+' must be a positive integer');});return o;}
    var help='Wi-Fi Health Detector\n--engine auto|python|native|node --interface NAME --language zh|en\n--timeout SECONDS --budget SECONDS --fast --no-public-test --speedtest\n--mask --json PATH --csv PATH --no-notify --verbose --view summary\n';
    return {empty:empty,set:set,missing:missing,val:val,diagnose:diagnose,masked:masked,text:text,csv:csv,validate:validate,options:options,help:help};
}());
if(typeof module!=='undefined')module.exports=WifiCore;
