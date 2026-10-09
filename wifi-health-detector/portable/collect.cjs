'use strict';
const {execFile}=require('node:child_process');
const os=require('node:os'),parser=require('./macos.js').parser,core=require('./macos.js').core,contract=require('./contract.json');
function decode(buffer){try{return new TextDecoder('utf-8',{fatal:true}).decode(buffer);}catch(_){return new TextDecoder('gb18030').decode(buffer);}}
function runCommand(args,timeout){return new Promise(resolve=>{
    const start=Date.now();let settled=false,timer;
    function done(result){if(settled)return;settled=true;clearTimeout(timer);resolve({...result,elapsed_ms:Date.now()-start});}
    const child=execFile(args[0],args.slice(1),{shell:false,detached:process.platform!=='win32',maxBuffer:4*1024*1024,windowsHide:true,encoding:'buffer'},(err,stdout,stderr)=>{
        done({stdout:decode(stdout||Buffer.alloc(0)),stderr:decode(stderr||Buffer.alloc(0)),status:err?(typeof err.code==='number'?err.code:127):0});
    });
    timer=setTimeout(()=>{
        if(child.pid){
            if(process.platform==='win32')execFile('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{timeout:1000,windowsHide:true},()=>{try{child.kill();}catch(_){}}).unref();
            else try{process.kill(-child.pid,'SIGKILL');}catch(_){}
        }
        if(child.stdout)child.stdout.destroy();if(child.stderr)child.stderr.destroy();child.unref();
        done({stdout:'',stderr:'timeout',status:124});
    },timeout);
});}
exports.runCommand=runCommand;
exports.collect=async function(o){
    const platform=process.platform==='darwin'?'Darwin':process.platform==='win32'?'Windows':null;
    if(!platform)throw Error('Unsupported operating system: '+process.platform);
    const input={platform,checked_at:new Date().toISOString(),architecture:os.arch(),os_version:os.release(),commands:{}};
    const deadline=Date.now()+o.budget*1000;
    async function batch(specs){await Promise.all(Object.entries(specs).map(async ([key,args])=>{
        const timeout=Math.min(o.timeout*1000,deadline-Date.now());
        if(timeout<=0){input.commands[key]={stdout:'',status:124,elapsed_ms:0};return;}
        input.commands[key]=await runCommand(args,timeout);
    }));}
    await batch(parser.initial(platform,o));
    const first=parser.capture(input,contract,o);
    await batch(parser.network(platform,core.val(first,'ip','gateway'),o));
    return input;
};
