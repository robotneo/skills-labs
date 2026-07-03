#!/usr/bin/env python3
"""Small async task wrapper for long-running safe commands."""
from __future__ import annotations
import argparse, json, subprocess, shlex, os
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
TASKS=ROOT/'data'/'async_tasks'


def now(): return datetime.now().isoformat(timespec='seconds')
def task_path(tid): return TASKS/f'{tid}.json'
def log_path(tid): return TASKS/f'{tid}.log'

def submit(args):
    TASKS.mkdir(parents=True,exist_ok=True)
    tid=datetime.now().strftime('%Y%m%d%H%M%S')+'-'+str(os.getpid())
    cmd=args.cmd
    meta={'id':tid,'status':'running','cmd':cmd,'created_at':now(),'updated_at':now(),'pid':None,'rc':None}
    lf=open(log_path(tid),'w')
    p=subprocess.Popen(cmd,shell=True,cwd=ROOT,stdout=lf,stderr=subprocess.STDOUT,start_new_session=True)
    meta['pid']=p.pid
    task_path(tid).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return meta

def refresh(meta):
    pid=meta.get('pid')
    if meta.get('status')=='running' and pid:
        try:
            os.kill(pid,0)
        except ProcessLookupError:
            meta['status']='unknown_done'; meta['updated_at']=now()
    return meta

def status(args):
    p=task_path(args.task_id)
    if not p.exists(): return {'status':'not_found','id':args.task_id}
    meta=refresh(json.loads(p.read_text()))
    p.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    if args.tail:
        lp=log_path(args.task_id)
        meta['log_tail']=''.join(lp.read_text(errors='ignore').splitlines(True)[-args.tail:]) if lp.exists() else ''
    return meta

def list_tasks(args):
    TASKS.mkdir(parents=True,exist_ok=True)
    rows=[]
    for p in sorted(TASKS.glob('*.json'), reverse=True)[:args.limit]:
        rows.append(refresh(json.loads(p.read_text())))
    return {'status':'success','count':len(rows),'data':rows}

def parse():
    p=argparse.ArgumentParser()
    p.add_argument('--action',required=True,choices=['submit','status','list'])
    p.add_argument('--cmd')
    p.add_argument('--task-id')
    p.add_argument('--tail',type=int,default=0)
    p.add_argument('--limit',type=int,default=20)
    return p.parse_args()

if __name__=='__main__':
    a=parse()
    if a.action=='submit': res=submit(a)
    elif a.action=='status': res=status(a)
    else: res=list_tasks(a)
    print(json.dumps(res,ensure_ascii=False,indent=2))
