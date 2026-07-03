import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def parse_json(stdout):
    i=stdout.find('{')
    assert i>=0, stdout
    return json.loads(stdout[i:])

def test_handler_delivery_plan():
    p=subprocess.run([
        sys.executable,'scripts/handler.py','--action','delivery','--delivery-action','plan',
        '--name','unit-handler','--ip','10.0.0.40','--owner','tester','--template','tpl','--dc','DC','--cluster','CL','--datastore','DS','--network','VLAN','--gateway','10.0.0.1'
    ],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    res=parse_json(p.stdout)
    assert res['status']=='success'
    assert res['steps']==9

def test_handler_post_init_loopback():
    p=subprocess.run([sys.executable,'scripts/handler.py','--action','post_init','--hostname','127.0.0.1-test','--ip','127.0.0.1'],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    res=parse_json(p.stdout)
    assert res['action']=='post_clone_init'
    assert res['status']=='success'
