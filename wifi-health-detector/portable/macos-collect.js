/* Foundation NSTask only: no Apple Events, Accessibility or GUI automation. */
function collectMac(o,c) {
    var input={platform:'Darwin',checked_at:new Date().toISOString(),commands:{}},deadline=Date.now()+o.budget*1000;
    var fm=$.NSFileManager.defaultManager,base=ObjC.unwrap($.NSTemporaryDirectory())+'wifi-health-'+ObjC.unwrap($.NSUUID.UUID.UUIDString);
    if(!fm.createDirectoryAtPathWithIntermediateDirectoriesAttributesError($(base),true,$.NSDictionary.dictionary,null))throw Error('Cannot create capture directory');
    ObjC.bindFunction('kill',['int',['int','int']]);
    function batch(specs){var active=[];
        Object.keys(specs).forEach(function(key){var args=specs[key],task=$.NSTask.alloc.init,path=base+'/'+key,handle,start=Date.now();
            if(start>=deadline){input.commands[key]={stdout:'',status:124,elapsed_ms:0};return;}
            try{fm.createFileAtPathContentsAttributes($(path),$.NSData.data,$.NSDictionary.dictionary);handle=$.NSFileHandle.fileHandleForWritingAtPath($(path));task.launchPath=$(args[0]);task.arguments=$(args.slice(1));task.standardOutput=handle;task.standardError=handle;task.standardInput=$.NSFileHandle.fileHandleWithNullDevice;task.launch;active.push({key:key,task:task,path:path,handle:handle,start:start,expires:Math.min(deadline,start+o.timeout*1000)});}
            catch(e){if(handle)handle.closeFile;input.commands[key]={stdout:'',status:127,elapsed_ms:Date.now()-start};}
        });
        while(active.length){for(var i=active.length-1;i>=0;i--){var p=active[i],timed=Date.now()>=p.expires;if(p.task.running&&!timed)continue;if(timed&&p.task.running){$.kill(p.task.processIdentifier,9);p.task.waitUntilExit;}p.handle.closeFile;input.commands[p.key]={stdout:readFile(p.path),status:timed?124:Number(p.task.terminationStatus),elapsed_ms:Date.now()-p.start};active.splice(i,1);}if(active.length)$.NSThread.sleepForTimeInterval(0.02);}
    }
    try{batch(WifiParse.initial('Darwin',o));var first=WifiParse.capture(input,c,o);batch(WifiParse.network('Darwin',WifiCore.val(first,'ip','gateway'),o));return input;}
    finally{fm.removeItemAtPathError($(base),null);}
}
