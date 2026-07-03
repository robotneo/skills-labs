#!/usr/bin/env python3
"""Persistent delivery state machine."""
from __future__ import annotations
import argparse,json,uuid
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'data'/'deliveries'
STATES=['planned','prechecked','cloning','cloned','verified','asset_registered','monitoring_generated','delivered','failed','rolled_back']

def now(): return datetime.now().isoformat(timespec='seconds')
def path(i): return DIR/f'{i}.json'
def load(i):
    p=path(i)
    if not p.exists(): return None
    return json.loads(p.read_text())
def save(d):
    DIR.mkdir(parents=True,exist_ok=True)
    d['updated_at']=now()
    path(d['id']).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    return d

def create(a):
    did=a.delivery_id or str(uuid.uuid4())[:8]
    d={'id':did,'vm_name':a.vm_name,'ip':a.ip,'owner':a.owner,'state':'planned','created_at':now(),'updated_at':now(),'history':[{'ts':now(),'state':'planned','note':'created'}]}
    return save(d)
def advance(a):
    d=load(a.delivery_id)
    if not d: return {'status':'not_found','id':a.delivery_id}
    if a.state not in STATES: return {'status':'error','message':'invalid state'}
    d['state']=a.state
    d.setdefault('history',[]).append({'ts':now(),'state':a.state,'note':a.note or ''})
    return save(d)
def get(a): return load(a.delivery_id) or {'status':'not_found','id':a.delivery_id}
def list_(a):
    DIR.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(p.read_text()) for p in sorted(DIR.glob('*.json'), reverse=True)[:a.limit]]
    return {'status':'success','count':len(rows),'data':rows}

def parse():
    p=argparse.ArgumentParser()
    p.add_argument('--action',required=True,choices=['create','advance','get','list'])
    p.add_argument('--delivery-id'); p.add_argument('--vm-name'); p.add_argument('--ip'); p.add_argument('--owner')
    p.add_argument('--state',choices=STATES); p.add_argument('--note'); p.add_argument('--limit',type=int,default=20)
    return p.parse_args()
if __name__=='__main__':
    a=parse()
    res={'create':create,'advance':advance,'get':get,'list':list_}[a.action](a)
    print(json.dumps(res,ensure_ascii=False,indent=2))
