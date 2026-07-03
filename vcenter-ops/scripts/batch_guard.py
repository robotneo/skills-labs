#!/usr/bin/env python3
"""Batch operation limit guard."""
from __future__ import annotations
import argparse,json
DEFAULT_MAX=5; ADMIN_MAX=20
HIGH_RISK={'delete_vm','batch','batch_clone','power_vm'}
def check(a):
    limit=ADMIN_MAX if a.role=='admin' else DEFAULT_MAX
    denied=[]
    if a.count>limit: denied.append(f'count {a.count} > limit {limit} for role {a.role}')
    if a.action in {'delete_vm'} and a.count>1: denied.append('delete_vm batch is forbidden')
    if a.workers>a.max_workers: denied.append(f'workers {a.workers} > max_workers {a.max_workers}')
    if a.failure_rate>=0.3: denied.append(f'failure_rate {a.failure_rate} >= 0.3 circuit breaker')
    return {'status':'allowed' if not denied else 'denied','action':a.action,'count':a.count,'role':a.role,'limit':limit,'denied_reasons':denied}
def parse():
    p=argparse.ArgumentParser(); p.add_argument('--action',required=True); p.add_argument('--count',type=int,default=1); p.add_argument('--role',default='operator',choices=['viewer','operator','admin'])
    p.add_argument('--workers',type=int,default=1); p.add_argument('--max-workers',type=int,default=2); p.add_argument('--failure-rate',type=float,default=0)
    return p.parse_args()
if __name__=='__main__': print(json.dumps(check(parse()),ensure_ascii=False,indent=2))
