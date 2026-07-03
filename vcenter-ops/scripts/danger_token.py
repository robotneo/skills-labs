#!/usr/bin/env python3
"""Danger confirmation token bound to actor/action/target with TTL."""
from __future__ import annotations
import argparse,json,secrets,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'danger_tokens.json'

def load():
    if not DB.exists(): return []
    try: return json.loads(DB.read_text())
    except: return []
def save(rows):
    DB.parent.mkdir(exist_ok=True); DB.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
def digest(tok): return hashlib.sha256(tok.encode()).hexdigest()
def create(a):
    token=f"{a.action.upper()}-{a.target}-{secrets.randbelow(9000)+1000}"
    rows=[r for r in load() if r.get('expires_at',0)>time.time()]
    rows.append({'token_hash':digest(token),'actor':a.actor,'action':a.action,'target':a.target,'expires_at':time.time()+a.ttl,'used':False})
    save(rows)
    return {'status':'success','token':token,'expires_in':a.ttl}
def verify(a):
    rows=load(); ok=False; reason='not_found'
    for r in rows:
        if r['token_hash']==digest(a.token) and r['actor']==a.actor and r['action']==a.action and r['target']==a.target:
            if r.get('used'): reason='used'
            elif r.get('expires_at',0)<time.time(): reason='expired'
            else:
                r['used']=True; ok=True; reason='ok'
            break
    save(rows)
    return {'status':'success' if ok else 'denied','reason':reason}
def parse():
    p=argparse.ArgumentParser(); p.add_argument('--action',required=True,choices=['create','verify'])
    p.add_argument('--actor',required=True); p.add_argument('--target-action',dest='target_action',required=True); p.add_argument('--target',required=True)
    p.add_argument('--token'); p.add_argument('--ttl',type=int,default=300)
    return p.parse_args()
if __name__=='__main__':
    a=parse(); a.action,a.op=(a.target_action,a.action)
    print(json.dumps(create(a) if a.op=='create' else verify(a),ensure_ascii=False,indent=2))
