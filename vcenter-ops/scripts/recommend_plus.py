#!/usr/bin/env python3
"""Enhanced recommendation wrapper.

Combines existing recommender output with latest metrics/index signals when available.
This first version is non-invasive and does not modify handler.py.
"""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run_json(cmd):
    p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    if p.returncode!=0:
        return {'status':'error','stderr':p.stderr,'stdout':p.stdout}
    txt=p.stdout[p.stdout.find('{'):]
    try: return json.loads(txt)
    except Exception: return {'status':'raw','stdout':p.stdout}

def latest_metrics():
    mdir=ROOT/'data'/'metrics'
    files=sorted(mdir.glob('*.jsonl'))
    rows=[]
    if files:
        for line in files[-1].read_text().splitlines():
            try: rows.append(json.loads(line))
            except: pass
    return rows

def score_adjust(item, metrics):
    ds=item.get('datastore')
    cluster=item.get('cluster')
    penalty=0; reasons=[]
    for r in metrics:
        if r.get('type')=='ds_used' and r.get('target')==ds and r.get('value',0)>0.85:
            penalty+=15; reasons.append(f"DS水位高 {r.get('value'):.1%}")
        if r.get('type')=='cluster_mem' and r.get('target')==cluster and r.get('value',0)>0.75:
            penalty+=10; reasons.append(f"集群内存较高 {r.get('value'):.1%}")
    item['score_plus']=round(max(0,float(item.get('score',0))-penalty),2)
    item['plus_reasons']=reasons
    return item

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cpu',default='4'); ap.add_argument('--memory',default='8'); ap.add_argument('--disk',default='100'); ap.add_argument('--top',default='3')
    a=ap.parse_args()
    base=run_json([sys.executable,'scripts/handler.py','--action','recommend','--cpu',a.cpu,'--memory',a.memory,'--disk',a.disk,'--recommend-top',a.top])
    data=base.get('data') or []
    metrics=latest_metrics()
    enhanced=[score_adjust(dict(x),metrics) for x in data]
    enhanced.sort(key=lambda x:x.get('score_plus',0), reverse=True)
    print(json.dumps({'status':'success','action':'recommend_plus','data':enhanced,'base_status':base.get('status')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
