// Offline test harness: never collects network or starts processes.
'use strict';
const fs=require('node:fs');
const core=require('../portable/macos.js').core;
const contract=require('../portable/contract.json');
async function main(){
    const o=core.options(process.argv.slice(2));
    if(o.help){process.stdout.write(core.help);return;}
    let report;
    if(o.reportInput)report=JSON.parse(fs.readFileSync(o.reportInput,'utf8'));
    else {const parser=require('../portable/macos.js').parser;const capture=JSON.parse(fs.readFileSync(o.captureInput,'utf8'));report=parser.capture(capture,contract,o);}
    core.validate(report,contract);report.diagnosis=core.diagnose(report,contract);report=core.masked(report,o.mask);
    if(o.json)fs.writeFileSync(o.json,JSON.stringify(report,null,2)+'\n');
    if(o.csv)fs.writeFileSync(o.csv,core.csv(report,contract));
    process.stdout.write(core.text(report,contract,o.language));
}
main().catch(e=>{process.stderr.write('Wi-Fi detector error: '+e.message+'\n');process.exitCode=2;});
