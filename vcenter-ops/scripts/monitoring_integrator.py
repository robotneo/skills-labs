#!/usr/bin/env python3
"""Monitoring integration helpers.

Current production-safe implementation:
- generate Prometheus file_sd targets from data/assets.json
- mark monitoring_status in local asset registry
No remote Prometheus/Nightingale/Categraf write is performed.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "data" / "assets.json"
DEFAULT_SD = ROOT / "monitoring" / "vcenter-vms.file_sd.json"


def load_assets():
    if not ASSETS.exists():
        return []
    return json.loads(ASSETS.read_text())


def active_assets(rows):
    return [r for r in rows if r.get("status", "active") not in {"retired", "deleted", "disabled"}]


def gen_file_sd(args):
    rows = active_assets(load_assets())
    targets = []
    for r in rows:
        ip = r.get("ip")
        if not ip:
            continue
        labels = {
            "vm_name": r.get("vm_name", ""),
            "owner": r.get("owner", ""),
            "env": r.get("env", ""),
            "app": r.get("app", ""),
            "cluster": r.get("cluster", ""),
            "datastore": r.get("datastore", ""),
            "source": "vcenter-ops",
        }
        targets.append({"targets": [f"{ip}:{args.port}"], "labels": labels})
    out = Path(args.output or DEFAULT_SD)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(targets, ensure_ascii=False, indent=2) + "\n")
    return {"status": "success", "action": "prometheus_sd", "output": str(out), "targets": len(targets)}


def mark(args):
    cmd = [sys.executable, str(ROOT / "scripts" / "asset_registry.py"), "--action", "upsert", "--vm-name", args.vm_name, "--monitoring-status", args.status]
    if args.ip:
        cmd += ["--ip", args.ip]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        return {"status": "error", "stderr": p.stderr}
    return {"status": "success", "action": "mark", "result": json.loads(p.stdout)}


def verify(args):
    rows = active_assets(load_assets())
    missing = [r for r in rows if not r.get("monitoring_status") or r.get("monitoring_status") in {"none", "pending"}]
    return {"status": "success", "action": "verify", "active": len(rows), "missing_monitoring": len(missing), "missing": missing[:50]}


def parse():
    p = argparse.ArgumentParser(description="vcenter-ops monitoring integrator")
    p.add_argument("--action", required=True, choices=["prometheus_sd", "mark", "verify"])
    p.add_argument("--output")
    p.add_argument("--port", default="9100")
    p.add_argument("--vm-name")
    p.add_argument("--ip")
    p.add_argument("--status", default="enabled", choices=["enabled", "pending", "disabled", "removed"])
    return p.parse_args()


def main():
    args = parse()
    if args.action == "prometheus_sd": res = gen_file_sd(args)
    elif args.action == "mark": res = mark(args)
    else: res = verify(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
