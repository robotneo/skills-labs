import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(*args):
    p=subprocess.run([sys.executable,*args],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)

def test_batch_guard_limits():
    res=run('scripts/batch_guard.py','--action','batch_clone','--count','6','--role','operator')
    assert res['status']=='denied'
    ok=run('scripts/batch_guard.py','--action','batch_clone','--count','5','--role','operator')
    assert ok['status']=='allowed'

def test_danger_token_one_time():
    c=run('scripts/danger_token.py','--action','create','--actor','tester','--target-action','delete_vm','--target','unit-vm')
    token=c['token']
    v=run('scripts/danger_token.py','--action','verify','--actor','tester','--target-action','delete_vm','--target','unit-vm','--token',token)
    assert v['status']=='success'
    v2=run('scripts/danger_token.py','--action','verify','--actor','tester','--target-action','delete_vm','--target','unit-vm','--token',token)
    assert v2['status']=='denied'

def test_preflight_denies_imprecise_delete():
    res=run('scripts/preflight_gate.py','--action','delete_vm','--target','all','--actor','tester','--role','admin')
    assert res['status']=='denied'
    assert any(c['name']=='target_precise' and not c['ok'] for c in res['checks'])
