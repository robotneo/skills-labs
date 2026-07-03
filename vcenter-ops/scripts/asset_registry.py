#!/usr/bin/env python3
"""Local asset registry for vcenter-ops.

Stores VM lifecycle records in data/assets.json and can export CSV/Markdown.
No external CMDB write is performed here.
"""
from __future__ import annotations
import argparse, csv, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "assets.json"

FIELDS = [
    "vm_name", "ip", "owner", "env", "app", "status", "cluster", "host",
    "datastore", "network", "cpu", "memory_gb", "disk_gb", "os", "template",
    "created_at", "updated_at", "expired_at", "monitoring_status", "backup_status",
    "approval_id", "notes",
]

ACTIVE = {"active", "created", "running"}


def now():
    return datetime.now().isoformat(timespec="seconds")


def load():
    if not DATA.exists():
        return []
    try:
        data = json.loads(DATA.read_text())
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        raise SystemExit(f"invalid json: {DATA}")


def save(rows):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


def find(rows, vm_name=None, ip=None):
    for i, r in enumerate(rows):
        if vm_name and r.get("vm_name") == vm_name:
            return i, r
        if ip and r.get("ip") == ip:
            return i, r
    return None, None


def normalize(args, old=None):
    r = dict(old or {})
    for f in FIELDS:
        v = getattr(args, f, None)
        if v is not None:
            r[f] = v
    # Upsert means the asset is active again unless caller explicitly sets another status.
    if getattr(args, "action", "") == "upsert" and getattr(args, "status", None) is None:
        r["status"] = "active"
    else:
        r.setdefault("status", "active")
    r.setdefault("created_at", now())
    r["updated_at"] = now()
    return {f: r.get(f, "") for f in FIELDS}


def upsert(args):
    rows = load()
    idx, old = find(rows, args.vm_name, args.ip)
    rec = normalize(args, old)
    if idx is None:
        rows.append(rec)
        op = "created"
    else:
        rows[idx] = rec
        op = "updated"
    save(rows)
    return {"status": "success", "action": "upsert", "op": op, "record": rec}


def retire(args):
    rows = load()
    idx, old = find(rows, args.vm_name, args.ip)
    if old is None:
        return {"status": "not_found", "action": "retire", "vm_name": args.vm_name, "ip": args.ip}
    old["status"] = "retired"
    old["updated_at"] = now()
    if args.notes:
        old["notes"] = args.notes
    rows[idx] = old
    save(rows)
    return {"status": "success", "action": "retire", "record": old}


def list_rows(args):
    rows = load()
    if args.status:
        rows = [r for r in rows if r.get("status") == args.status]
    if args.owner:
        rows = [r for r in rows if r.get("owner") == args.owner]
    if args.env:
        rows = [r for r in rows if r.get("env") == args.env]
    return {"status": "success", "action": "list", "count": len(rows), "data": rows}


def get(args):
    rows = load()
    _, r = find(rows, args.vm_name, args.ip)
    return {"status": "success" if r else "not_found", "action": "get", "record": r}


def export(args):
    rows = list_rows(args)["data"]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    elif args.format == "csv":
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader(); w.writerows(rows)
    else:
        lines = ["# vCenter Assets", "", f"count: {len(rows)}", "", "| VM | IP | Owner | Env | App | Status | Cluster | Datastore | Monitoring |", "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r.get('vm_name','')} | {r.get('ip','')} | {r.get('owner','')} | {r.get('env','')} | {r.get('app','')} | {r.get('status','')} | {r.get('cluster','')} | {r.get('datastore','')} | {r.get('monitoring_status','')} |")
        out.write_text("\n".join(lines) + "\n")
    return {"status": "success", "action": "export", "output": str(out), "count": len(rows)}


def parse():
    p = argparse.ArgumentParser(description="vcenter-ops asset registry")
    p.add_argument("--action", required=True, choices=["upsert", "retire", "list", "get", "export"])
    for f in FIELDS:
        p.add_argument(f"--{f.replace('_','-')}", dest=f)
    p.add_argument("--format", choices=["json", "csv", "markdown"], default="markdown")
    p.add_argument("--output", default="reports/assets.md")
    return p.parse_args()


def main():
    args = parse()
    if args.action == "upsert": res = upsert(args)
    elif args.action == "retire": res = retire(args)
    elif args.action == "list": res = list_rows(args)
    elif args.action == "get": res = get(args)
    else: res = export(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
