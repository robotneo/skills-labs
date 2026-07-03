import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(*args):
    p=subprocess.run([sys.executable,*args],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)

def test_inventory_index_build_query():
    res=run('scripts/inventory_cache_index.py','--action','build')
    assert res['status']=='success'
    assert 'counts' in res['data']

def test_delivery_state_create_advance():
    res=run('scripts/delivery_state.py','--action','create','--vm-name','unit-vm','--ip','10.0.0.30','--owner','tester')
    did=res['id']
    adv=run('scripts/delivery_state.py','--action','advance','--delivery-id',did,'--state','prechecked','--note','ok')
    assert adv['state']=='prechecked'
    got=run('scripts/delivery_state.py','--action','get','--delivery-id',did)
    assert got['id']==did

def test_async_runner_submit_status():
    res=run('scripts/async_runner.py','--action','submit','--cmd','echo async-ok')
    assert res['status']=='running'
    got=run('scripts/async_runner.py','--action','status','--task-id',res['id'],'--tail','5')
    assert got['id']==res['id']
