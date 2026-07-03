#!/usr/bin/env python3
"""Unified preflight safety gate.

Does not execute target action. It validates safety prerequisites.
"""
from __future__ import annotations
import argparse,json,subprocess,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DANGER={'delete_vm','secret','rbac','approval_policy','change_window'}
BATCH={'batch','batch_clone','power_vm'}

def run(cmd):
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    try: data=json.loads(p.stdout[p.stdout.find('{'):])
    except Exception: data={'raw':p.stdout,'stderr':p.stderr}
    return p.returncode,data

def precise(target):
    if not target: return False
    bad=['*','?','全部','所有','清空','all']
    return not any(x in target for x in bad)

def gate(a):
    checks=[]; allowed=True
    def add(name,ok,detail=''):
        nonlocal allowed; checks.append({'name':name,'ok':ok,'detail':detail}); allowed=allowed and ok
    add('target_precise', precise(a.target) if a.action in DANGER else True, 'danger action requires exact target')
    rc,sec=run([sys.executable,'scripts/secret_audit.py'])
    add('secret_permissions', sec.get('status')=='success', sec)
    if a.action in BATCH or a.count>1:
        rc,bg=run([sys.executable,'scripts/batch_guard.py','--action',a.action,'--count',str(a.count),'--role',a.role,'--workers',str(a.workers)])
        add('batch_guard', bg.get('status')=='allowed', bg)
    if a.action in DANGER:
        if a.evidence:
            add('evidence_present', Path(a.evidence).exists(), a.evidence)
        else:
            add('evidence_present', False, 'required for danger action')
        if a.token:
            rc,tok=run([sys.executable,'scripts/danger_token.py','--action','verify','--actor',a.actor,'--target-action',a.action,'--target',a.target,'--token',a.token])
            add('danger_token', tok.get('status')=='success', tok)
        else:
            add('danger_token', False, 'required for danger action')
    return {'status':'allowed' if allowed else 'denied','action':a.action,'target':a.target,'actor':a.actor,'checks':checks}

def parse():
    p=argparse.ArgumentParser(); p.add_argument('--action',required=True); p.add_argument('--target',default=''); p.add_argument('--actor',default='agent'); p.add_argument('--role',default='operator')
    p.add_argument('--count',type=int,default=1); p.add_argument('--workers',type=int,default=1); p.add_argument('--token'); p.add_argument('--evidence')
    return p.parse_args()
if __name__=='__main__': print(json.dumps(gate(parse()),ensure_ascii=False,indent=2))
