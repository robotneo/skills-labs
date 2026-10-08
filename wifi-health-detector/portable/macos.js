/* JXA is supplied by macOS; no Python, Node, third-party modules or GUI scripting. */
ObjC.import('Foundation');
function readFile(path) {
    var value=$.NSString.stringWithContentsOfFileEncodingError($(path),$.NSUTF8StringEncoding,null);
    if(!value)throw Error('Cannot read '+path);return ObjC.unwrap(value);
}
function writeFile(path,text) {
    if(!$(text).writeToFileAtomicallyEncodingError($(path),true,$.NSUTF8StringEncoding,null))throw Error('Cannot write '+path);
}
function run(argv) {
    var own=ObjC.deepUnwrap($.NSProcessInfo.processInfo.arguments).filter(function(x){return /macos\.js$/.test(x);})[0];
    var dir=own.slice(0,own.lastIndexOf('/'));
    eval(readFile(dir+'/core.js'));
    var c=JSON.parse(readFile(dir+'/contract.json')),o=WifiCore.options(argv);
    if(o.help)return WifiCore.help.replace(/\n$/,'');
    var r;
    if(o.reportInput)r=JSON.parse(readFile(o.reportInput));
    else {eval(readFile(dir+'/parse.js'));eval(readFile(dir+'/macos-collect.js'));r=WifiParse.capture(o.captureInput?JSON.parse(readFile(o.captureInput)):collectMac(o,c),c,o);}
    WifiCore.validate(r,c);r.diagnosis=WifiCore.diagnose(r,c);r=WifiCore.masked(r,o.mask);
    if(o.json)writeFile(o.json,JSON.stringify(r,null,2)+'\n');
    if(o.csv)writeFile(o.csv,WifiCore.csv(r,c));
    if(!o.noNotify&&!o.reportInput&&!o.captureInput){var message=$('Enterprise notification: portable engine does not invoke the Python Bridge; report retained.\n').dataUsingEncoding($.NSUTF8StringEncoding);$.NSFileHandle.fileHandleWithStandardError.writeData(message);}
    return WifiCore.text(r,c,o.language).replace(/\n$/,'');
}
