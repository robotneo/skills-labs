#!/usr/bin/env python3
"""Secret file permission audit."""
from __future__ import annotations
import argparse,json,stat
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['.env','data/.master_key','data/secrets.json']

def mode(p): return oct(p.stat().st_mode & 0o777)[2:]
def audit(fix=False):
    rows=[]; ok=True
    for rel in FILES:
        p=ROOT/rel
        if not p.exists():
            rows.append({'file':rel,'exists':False,'ok':False,'reason':'missing'}); ok=False; continue
        m=mode(p)
        if fix and m!='600':
            p.chmod(0o600); m=mode(p)
        good=(m=='600')
        rows.append({'file':rel,'exists':True,'mode':m,'ok':good})
        ok=ok and good
    return {'status':'success' if ok else 'failed','items':rows}
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--fix',action='store_true'); a=ap.parse_args()
    print(json.dumps(audit(a.fix),ensure_ascii=False,indent=2))
