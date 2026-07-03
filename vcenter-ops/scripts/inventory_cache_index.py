#!/usr/bin/env python3
"""Fast local index over vCenter cache/assets/metrics.

P1 goal: reduce live vCenter API calls by answering common lookups from local files.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'data'/'vc_session_cache.json'
ASSETS=ROOT/'data'/'assets.json'
INDEX=ROOT/'data'/'inventory_index.json'


def read_json(p, default):
    if not p.exists(): return default
    try: return json.loads(p.read_text())
    except Exception: return default


def flatten_vms(cache):
    if isinstance(cache, list): return cache
    for key in ('vms','virtual_machines','vm_list'):
        if isinstance(cache, dict) and isinstance(cache.get(key), list): return cache[key]
    return []


def build():
    cache=read_json(CACHE,{})
    assets=read_json(ASSETS,[])
    vms=flatten_vms(cache)
    by_name={}; by_ip={}; by_cluster={}; by_ds={}
    for src,row in [('cache',r) for r in vms] + [('asset',r) for r in assets]:
        name=row.get('name') or row.get('vm_name') or row.get('hostname')
        ip=row.get('ip') or row.get('guest_ip') or row.get('ipv4')
        cluster=row.get('cluster') or ''
        ds=row.get('datastore') or row.get('ds') or ''
        rec={'source':src, **row}
        if name: by_name[name]=rec
        if ip: by_ip[ip]=rec
        if cluster: by_cluster.setdefault(cluster,[]).append(name or ip or '')
        if ds: by_ds.setdefault(ds,[]).append(name or ip or '')
    idx={'generated_at':datetime.now().isoformat(timespec='seconds'),'counts':{'vms':len(vms),'assets':len(assets),'names':len(by_name),'ips':len(by_ip)},'by_name':by_name,'by_ip':by_ip,'by_cluster':by_cluster,'by_datastore':by_ds}
    INDEX.parent.mkdir(exist_ok=True)
    INDEX.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n')
    return idx


def query(args):
    idx=read_json(INDEX,{})
    if not idx or args.refresh: idx=build()
    if args.name: return idx.get('by_name',{}).get(args.name)
    if args.ip: return idx.get('by_ip',{}).get(args.ip)
    if args.cluster: return idx.get('by_cluster',{}).get(args.cluster,[])
    if args.datastore: return idx.get('by_datastore',{}).get(args.datastore,[])
    return {'generated_at':idx.get('generated_at'),'counts':idx.get('counts')}


def parse():
    p=argparse.ArgumentParser()
    p.add_argument('--action',choices=['build','query','summary'],default='summary')
    p.add_argument('--refresh',action='store_true')
    p.add_argument('--name'); p.add_argument('--ip'); p.add_argument('--cluster'); p.add_argument('--datastore')
    return p.parse_args()

if __name__=='__main__':
    a=parse()
    if a.action=='build': res=build()
    elif a.action=='query': res=query(a)
    else:
        if not INDEX.exists(): build()
        res=query(a)
    print(json.dumps({'status':'success','action':a.action,'data':res},ensure_ascii=False,indent=2))
