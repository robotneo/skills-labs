"""Differential tests: portable engines must preserve the existing contract."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wifi_health.models import Report
from wifi_health.diagnose import diagnose
from wifi_health.output import render_text, validate_standard_json


class PortableTests(unittest.TestCase):
    def test_node_and_native_report_match_python(self):
        node = os.environ.get('TEST_NODE') or shutil.which('node')
        engines = []
        if node:
            engines.append([node, str(ROOT / 'portable' / 'node.cjs')])
        if sys.platform == 'darwin':
            engines.append(['/usr/bin/osascript', '-l', 'JavaScript', str(ROOT / 'portable' / 'macos.js')])
        powershell = os.environ.get('TEST_POWERSHELL') or ('powershell.exe' if sys.platform == 'win32' else shutil.which('pwsh'))
        if powershell:
            engines.append([powershell, '-NoProfile', '-File', str(ROOT / 'portable' / 'windows.ps1')])
        self.assertTrue(engines, 'Set TEST_NODE to run portable contract tests')
        for degraded in (False, True):
            report = Report.empty()
            report.set('system', 'os', 'Darwin')
            report.set('system', 'checked_at', '2026-10-08T12:00:00+08:00')
            report.set('connection', 'ssid', '办公 "Wi-Fi" | \\ test\nnext')
            report.set('local_quality', 'jitter', 0.0, 'ms')
            if not degraded:
                for section, name, value in [('radio','rssi',-80), ('radio','same_channel_networks',5), ('connection','band','2.4 GHz'), ('link','tx_rate',12), ('local_quality','packet_loss',4.5), ('local_quality','latency',60), ('public_quality','dns_latency',300), ('connection','security','Open')]:
                    report.set(section, name, value)
            report.diagnosis = diagnose(report)
            with tempfile.TemporaryDirectory() as directory:
                source = pathlib.Path(directory) / 'report.json'
                source.write_text(json.dumps(report.to_dict()), encoding='utf-8')
                for engine in engines:
                    for language, mask in [('zh',False), ('en',True)]:
                        target = pathlib.Path(directory) / 'out.json'
                        args = engine + ['--report-input', str(source), '--language', language, '--json', str(target), '--no-notify'] + (['--mask'] if mask else [])
                        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, render_text(report, language, mask))
                        payload = json.loads(target.read_text())
                        validate_standard_json(payload)
                        self.assertEqual(payload['diagnosis'], report.diagnosis)

    def test_launcher_explicit_native_help(self):
        if sys.platform == 'win32':
            self.skipTest('macOS launcher')
        result = subprocess.run(['/bin/sh', str(ROOT / 'run.sh'), '--engine', 'native', '--help'], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--engine', result.stdout)

    def test_python_path_with_spaces(self):
        if sys.platform == 'win32':
            self.skipTest('macOS launcher')
        with tempfile.TemporaryDirectory(prefix='wifi test ') as directory:
            candidate = pathlib.Path(directory) / 'python interpreter'
            candidate.symlink_to(sys.executable)
            result = subprocess.run(['/bin/sh', str(ROOT / 'run.sh'), '--help'], env=dict(os.environ, WIFI_HEALTH_PYTHON=str(candidate)), capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_collection_without_python(self):
        if sys.platform != 'darwin':
            self.skipTest('macOS native runtime')
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / 'report.json'
            result = subprocess.run(['/bin/sh', str(ROOT / 'run.sh'), '--engine', 'native', '--budget', '3', '--timeout', '1', '--fast', '--no-public-test', '--no-notify', '--json', str(target)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(target.read_text())
            validate_standard_json(payload)
            self.assertEqual(payload['sections']['system']['python_version']['availability'], 'unavailable')

    def test_capture_errors_do_not_become_packet_loss(self):
        node = os.environ.get('TEST_NODE') or shutil.which('node')
        if not node: self.skipTest('Node required')
        capture = {'platform':'Windows','checked_at':'2026-10-08T00:00:00Z','commands':{'public0':{'status':127,'stdout':'permission denied'},'public1':{'status':124,'stdout':''},'public2':{'status':1,'stdout':'access denied'}}}
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'capture.json';source.write_text(json.dumps(capture))
            target=pathlib.Path(directory)/'out.json'
            result=subprocess.run([node,str(ROOT/'portable/node.cjs'),'--capture-input',str(source),'--json',str(target),'--no-notify'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads(target.read_text());validate_standard_json(payload)
            self.assertEqual(payload['sections']['public_quality']['packet_loss']['availability'],'unavailable')

    def test_python_failed_command_is_not_packet_loss(self):
        from wifi_health.network import ping_target
        from wifi_health.command import CommandResult
        class BrokenRunner:
            def run(self, *args, **kwargs): return CommandResult([],127,error='permission denied')
        self.assertIsNone(ping_target(BrokenRunner(),'192.0.2.1'))

    def test_command_runner_honors_total_budget(self):
        from wifi_health.command import CommandRunner
        runner=CommandRunner(timeout=10,budget=0.1)
        result=runner.run([sys.executable,'-c','import time;time.sleep(2)'])
        self.assertEqual(result.returncode,124)
        self.assertEqual(runner.run([sys.executable,'-c','print(1)']).returncode,124)

    def test_quality_probes_overlap(self):
        import threading
        from unittest.mock import patch
        from wifi_health.cli import apply_quality
        barrier=threading.Barrier(6, timeout=2)
        def ping(runner,target):
            barrier.wait()
            return {'reachable':True,'packet_loss_percent':0,'latency_ms':2,'jitter_ms':1}
        def dns(host,timeout=10):
            barrier.wait()
            return {'reachable':True,'latency_ms':2}
        report=Report.empty();report.set('ip','gateway','192.0.2.1')
        with patch('wifi_health.cli.ping_target',side_effect=ping),patch('wifi_health.cli.dns_test',side_effect=dns):
            apply_quality(report,object())
        self.assertEqual(report.get('local_quality','packet_loss').value,0)

    def test_timeout_cleans_up_descendants(self):
        import time
        from wifi_health.command import CommandRunner
        start=time.monotonic()
        code='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(3)"]);time.sleep(3)'
        result=CommandRunner(timeout=10,budget=0.1).run([sys.executable,'-c',code])
        self.assertEqual(result.returncode,124)
        self.assertLess(time.monotonic()-start,1.5)

    def test_operational_ping_failure_with_loss_summary(self):
        from wifi_health.network import ping_target
        from wifi_health.command import CommandResult
        text='PING: transmit failed. General failure.\nPackets: Sent = 3, Received = 0, Lost = 3 (100% loss)'
        class BrokenRunner:
            def run(self,*args,**kwargs):return CommandResult([],1,stdout=text)
        self.assertIsNone(ping_target(BrokenRunner(),'192.0.2.1'))
        node=os.environ.get('TEST_NODE') or shutil.which('node')
        if node:
            code='const p=require(process.argv[1]).parser;if(p.ping({status:1,stdout:process.argv[2]})!==null)process.exit(1)'
            result=subprocess.run([node,'-e',code,str(ROOT/'portable/macos.js'),text],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_windows_capture_parity(self):
        node=os.environ.get('TEST_NODE') or shutil.which('node')
        powershell=os.environ.get('TEST_POWERSHELL') or ('powershell.exe' if sys.platform=='win32' else shutil.which('pwsh'))
        if not node or not powershell:self.skipTest('Node and PowerShell are required for capture parity')
        def command(text,status=0):return {'stdout':text,'status':status,'elapsed_ms':12}
        capture={'platform':'Windows','checked_at':'2026-10-08T00:00:00Z','os_version':'10.0','architecture':'AMD64','commands':{
            'wireless':command('名称 : WLAN\nSSID : 办公网:测试\n频道 : 44\n信道宽度 : 80 MHz\n身份验证 : WPA2-个人\n信号 : 76%\n接收速率(Mbps) : 866\n传输速率(Mbps) : 780\n'),
            'ip':command(json.dumps([{'interface':'WLAN','gateway':'192.0.2.1','ipv4':'192.0.2.2','dns_servers':['223.5.5.5']}])) ,
            'gateway':command('Packets: Sent = 3, Received = 0, Lost = 3 (100% loss)',1),
            'public0':command('Packets: Sent = 3, Received = 3, Lost = 0 (0% loss)\nMinimum = 1ms, Maximum = 3ms, Average = 2ms'),
            'dns0':command('Name: www.baidu.com\nAddress: 192.0.2.4'),
            'nearby':command('频道 : 44\n频道 : 44\n频道 : 48')}}
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'capture.json';source.write_text(json.dumps(capture),encoding='utf-8')
            outputs=[]
            for engine in [[node,str(ROOT/'portable/node.cjs')],[powershell,'-NoProfile','-File',str(ROOT/'portable/windows.ps1')]]:
                target=pathlib.Path(directory)/'out.json'
                result=subprocess.run(engine+['--capture-input',str(source),'--json',str(target),'--mask','--no-notify'],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                payload=json.loads(target.read_text(encoding='utf-8'));validate_standard_json(payload)
                outputs.append((result.stdout,payload['diagnosis']))
            self.assertEqual(outputs[0],outputs[1])

    def test_node_timeout_cleans_up_descendants(self):
        import time
        node=os.environ.get('TEST_NODE') or shutil.which('node')
        if not node:self.skipTest('Node required')
        child='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(3)"]);time.sleep(3)'
        code='require(process.argv[1]).runCommand([process.argv[2],"-c",process.argv[3]],100).then(x=>{if(x.status!==124)process.exitCode=1})'
        start=time.monotonic()
        result=subprocess.run([node,'-e',code,str(ROOT/'portable/collect.cjs'),sys.executable,child],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(time.monotonic()-start,1.5)

    def test_shared_contract_does_not_drift_from_python(self):
        from wifi_health import output
        from wifi_health.models import SECTION_FIELDS
        contract=json.loads((ROOT/'portable/contract.json').read_text(encoding='utf-8'))
        self.assertEqual(contract['fields'],{s:list(names) for s,names in SECTION_FIELDS.items()})
        for key in ('ZH_RECOMMENDATIONS','ZH_ISSUES','EN_ISSUES','BADGES','REASON_ZH','ZH_CORE_ROW_LABELS','EN_CORE_ROW_LABELS','ZH_LOCAL_ROW_LABELS','EN_LOCAL_ROW_LABELS','ZH_PUBLIC_ROW_LABELS','EN_PUBLIC_ROW_LABELS'):
            expected=getattr(output,key)
            self.assertEqual(contract[key],list(expected) if isinstance(expected,tuple) else expected)

    def test_powershell_process_output_and_deadline(self):
        powershell=os.environ.get('TEST_POWERSHELL') or ('powershell.exe' if sys.platform=='win32' else shutil.which('pwsh'))
        if not powershell:self.skipTest('PowerShell required')
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'process test.ps1'
            source.write_text('''param([string]$Root,[string]$Python)
. (Join-Path $Root 'portable/process.ps1')
$jobs=@{text=@($Python,'-c','import sys;print(sys.argv[1])','space "quote" \\ path');slow=@($Python,'-c','import time;time.sleep(5)')}
$result=Invoke-WifiBatch $jobs 1 ([datetime]::UtcNow.AddSeconds(2))
$result|ConvertTo-Json -Depth 5 -Compress
''',encoding='utf-8-sig')
            result=subprocess.run([powershell,'-NoProfile','-File',str(source),str(ROOT),sys.executable],capture_output=True,text=True,timeout=6)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads(result.stdout)
            self.assertEqual(payload['text']['status'],0)
            self.assertEqual(payload['text']['stdout'].strip(),'space "quote" \\ path')
            self.assertEqual(payload['slow']['status'],124)


if __name__ == '__main__':
    unittest.main()
