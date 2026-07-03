#!/usr/bin/env python3
"""Collect pre-change/delete evidence without executing destructive action."""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports'/'evidence'

def run(cmd):
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    return {'cmd':cmd,'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr}

def safe(s): return ''.join(c if c.isalnum() or c in '._-' else '_' for c in s)
def collect(a):
    ts=datetime.now().strftime('%Y%m%d-%H%M%S')
    target=safe(a.target)
    d=BASE/a.action/target/ts
    d.mkdir(parents=True,exist_ok=True)
    meta={'action':a.action,'target':a.target,'actor':a.actor,'created_at':datetime.now().isoformat(timespec='seconds'),'path':str(d)}
    (d/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    checks={
      'vm.json':[sys.executable,'scripts/handler.py','--action','get_vm','--hostname',a.target],
      'snapshots.json':[sys.executable,'scripts/handler.py','--action','snapshot','--hostname',a.target,'--snap_action','list'],
      'events.json':[sys.executable,'scripts/handler.py','--action','events','--minutes',str(a.minutes)],
      'asset.json':[sys.executable,'scripts/asset_registry.py','--action','get','--vm-name',a.target],
      'monitoring.json':[sys.executable,'scripts/monitoring_integrator.py','--action','verify'],
    }
    results=[]
    for name,cmd in checks.items():
        r=run(cmd); results.append({'file':name,'rc':r['rc'],'cmd':cmd})
        (d/name).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    rollback=f"""# Rollback Note\n\nAction: {a.action}\nTarget: {a.target}\nActor: {a.actor}\n\n## 删除类操作说明\n\nVM 删除后原则上不可直接回滚。只能依赖备份、快照、存储残留或重新克隆恢复。\n执行前必须确认本证据包完整、审批通过、目标精确。\n"""
    (d/'rollback.md').write_text(rollback)
    summary={'status':'success','evidence_dir':str(d),'results':results}
    (d/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary

def parse():
    p=argparse.ArgumentParser()
    p.add_argument('--action',required=True)
    p.add_argument('--target',required=True)
    p.add_argument('--actor',default='agent')
    p.add_argument('--minutes',type=int,default=1440)
    return p.parse_args()
if __name__=='__main__': print(json.dumps(collect(parse()),ensure_ascii=False,indent=2))
