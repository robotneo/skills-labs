#!/usr/bin/env python3
"""Standard VM delivery pipeline.

Safe by default:
- plan: generate delivery plan only
- verify: verify existing delivery artifacts
- execute: requires --confirm and runs local steps; clone can be disabled by --skip-clone
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def run(cmd, allow_fail=False):
    p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if p.returncode != 0 and not allow_fail:
        raise SystemExit(json.dumps({"status":"error","cmd":cmd,"stdout":p.stdout,"stderr":p.stderr}, ensure_ascii=False, indent=2))
    return {"cmd": cmd, "rc": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-4000:]}


def ts():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def vm_name(args):
    return args.vm_name or f"{args.ip}-{args.name}"


def build_plan(args):
    vm = vm_name(args)
    steps = [
        {"id": 1, "name": "healthcheck", "cmd": "python3 scripts/healthcheck.py", "risk": "blue"},
        {"id": 2, "name": "resource_recommend", "cmd": f"python3 scripts/handler.py --action recommend --cpu {args.cpu} --memory {args.memory} --disk {args.disk} --recommend-top 3", "risk": "blue"},
        {"id": 3, "name": "ip_check", "cmd": f"python3 scripts/ip_scanner.py --check {args.ip}", "risk": "blue"},
        {"id": 4, "name": "clone_vm", "cmd": f"python3 scripts/handler.py --action clone_vm --preset {args.preset} --hostname {vm} --template {args.template} --dc {args.dc} --cluster {args.cluster} --ds {args.datastore} --network {args.network} --ip {args.ip} --mask {args.mask} --gw {args.gateway} --power_on", "risk": "yellow"},
        {"id": 5, "name": "verify_vm", "cmd": f"python3 scripts/handler.py --action get_vm --hostname {vm}", "risk": "blue"},
        {"id": 6, "name": "register_asset", "cmd": f"python3 scripts/asset_registry.py --action upsert --vm-name {vm} --ip {args.ip} --owner {args.owner} --env {args.env} --app {args.app} --cluster {args.cluster} --datastore {args.datastore} --network {args.network} --cpu {args.cpu} --memory-gb {args.memory} --disk-gb {args.disk} --template {args.template} --monitoring-status pending", "risk": "blue"},
        {"id": 7, "name": "generate_monitoring_sd", "cmd": "python3 scripts/monitoring_integrator.py --action prometheus_sd --port 9100", "risk": "blue"},
        {"id": 8, "name": "monitoring_verify", "cmd": "python3 scripts/monitoring_integrator.py --action verify", "risk": "blue"},
        {"id": 9, "name": "delivery_report", "cmd": "generate report", "risk": "blue"},
    ]
    return {"vm_name": vm, "created_at": datetime.now().isoformat(timespec="seconds"), "mode": args.action, "inputs": vars(args), "steps": steps}


def write_report(plan, results=None):
    REPORTS.mkdir(exist_ok=True)
    vm = plan["vm_name"].replace("/", "_")
    base = REPORTS / f"delivery-{vm}-{ts()}"
    json_path = Path(str(base) + ".json")
    md_path = Path(str(base) + ".md")
    json_path.write_text(json.dumps({"plan": plan, "results": results or []}, ensure_ascii=False, indent=2) + "\n")
    lines = [f"# VM Delivery Report: {plan['vm_name']}", "", f"time: {datetime.now().isoformat(timespec='seconds')}", "", "## Steps", "", "| # | Step | Risk | Result |", "|---|---|---|---|"]
    for s in plan["steps"]:
        status = "planned"
        if results:
            hit = next((r for r in results if r.get("step") == s["name"]), None)
            status = "OK" if hit and hit.get("rc") == 0 else ("SKIP" if hit and hit.get("skipped") else "FAIL")
        lines.append(f"| {s['id']} | {s['name']} | {s['risk']} | {status} |")
    lines += ["", "## Inputs", "", "```json", json.dumps(plan["inputs"], ensure_ascii=False, indent=2), "```"]
    md_path.write_text("\n".join(lines) + "\n")
    return str(md_path), str(json_path)


def do_plan(args):
    plan = build_plan(args)
    md, js = write_report(plan)
    return {"status": "success", "action": "plan", "vm_name": plan["vm_name"], "report_md": md, "report_json": js, "steps": len(plan["steps"])}


def do_execute(args):
    if not args.confirm:
        return {"status": "blocked", "reason": "execute requires --confirm"}
    plan = build_plan(args)
    results = []
    for s in plan["steps"]:
        if s["name"] == "clone_vm" and args.skip_clone:
            results.append({"step": s["name"], "skipped": True, "rc": 0})
            continue
        if s["name"] == "delivery_report":
            results.append({"step": s["name"], "rc": 0, "stdout": "generated"})
            continue
        if s["name"] in {"ip_check", "verify_vm"}:
            res = run(s["cmd"].split(), allow_fail=True)
        else:
            res = run(s["cmd"].split(), allow_fail=False)
        res["step"] = s["name"]
        results.append(res)
    md, js = write_report(plan, results)
    return {"status": "success", "action": "execute", "vm_name": plan["vm_name"], "report_md": md, "report_json": js, "results": [{"step": r.get("step"), "rc": r.get("rc"), "skipped": r.get("skipped", False)} for r in results]}


def do_verify(args):
    vm = vm_name(args)
    checks = [
        run([sys.executable, "scripts/asset_registry.py", "--action", "get", "--vm-name", vm], allow_fail=True),
        run([sys.executable, "scripts/monitoring_integrator.py", "--action", "verify"], allow_fail=True),
        run([sys.executable, "scripts/healthcheck.py"], allow_fail=True),
    ]
    return {"status": "success", "action": "verify", "vm_name": vm, "checks": checks}


def parse():
    p = argparse.ArgumentParser(description="vcenter-ops standard delivery pipeline")
    p.add_argument("--action", required=True, choices=["plan", "execute", "verify"])
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--skip-clone", action="store_true")
    p.add_argument("--name", required=True)
    p.add_argument("--vm-name")
    p.add_argument("--ip", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--env", default="dev")
    p.add_argument("--app", default="app")
    p.add_argument("--preset", default="dev-small")
    p.add_argument("--template", required=True)
    p.add_argument("--dc", required=True)
    p.add_argument("--cluster", required=True)
    p.add_argument("--datastore", required=True)
    p.add_argument("--network", required=True)
    p.add_argument("--gateway", required=True)
    p.add_argument("--mask", default="255.255.255.0")
    p.add_argument("--cpu", default="2")
    p.add_argument("--memory", default="4")
    p.add_argument("--disk", default="40")
    return p.parse_args()


def main():
    args = parse()
    if args.action == "plan": res = do_plan(args)
    elif args.action == "execute": res = do_execute(args)
    else: res = do_verify(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
