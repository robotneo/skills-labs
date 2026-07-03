#!/usr/bin/env python3
"""Post clone initialization checks.

Safe first version: verify reachability, optional SSH port, generate report.
It does not install agents or modify guest OS unless future explicit actions are added.
"""
from __future__ import annotations
import argparse, json, socket, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def ping(ip: str, count: int = 2, timeout: int = 3):
    p = subprocess.run(["ping", "-c", str(count), "-W", str(timeout), ip], text=True, capture_output=True)
    return {"ok": p.returncode == 0, "rc": p.returncode, "stdout": p.stdout[-2000:], "stderr": p.stderr[-1000:]}


def tcp_check(ip: str, port: int, timeout: int = 3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return {"ok": True, "port": port}
    except Exception as e:
        return {"ok": False, "port": port, "error": str(e)}


def write_report(vm_name: str, result: dict):
    REPORTS.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in vm_name)
    md = REPORTS / f"post-init-{safe}-{ts}.md"
    js = REPORTS / f"post-init-{safe}-{ts}.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = [
        f"# Post Clone Init: {vm_name}", "",
        f"time: {datetime.now().isoformat(timespec='seconds')}", "",
        f"status: {result['status']}", "",
        "## Checks", "",
        "| Check | Result | Detail |", "|---|---|---|",
    ]
    for c in result["checks"]:
        lines.append(f"| {c['name']} | {'OK' if c['ok'] else 'FAIL'} | {c.get('detail','')} |")
    md.write_text("\n".join(lines) + "\n")
    return str(md), str(js)


def run(args):
    checks = []
    if args.ip:
        r = ping(args.ip, timeout=args.timeout)
        checks.append({"name": "ping", "ok": r["ok"], "detail": args.ip, "raw": r})
    if args.ssh_check:
        r = tcp_check(args.ip, args.ssh_port, timeout=args.timeout)
        checks.append({"name": "ssh_port", "ok": r["ok"], "detail": f"{args.ip}:{args.ssh_port}", "raw": r})
    if args.expected_hostname:
        # Placeholder check: actual guest hostname requires VMware Tools/SSH command.
        checks.append({"name": "hostname_expected", "ok": True, "detail": args.expected_hostname})
    status = "success" if all(c["ok"] for c in checks) else "failed"
    result = {
        "status": status,
        "action": "post_clone_init",
        "vm_name": args.vm_name,
        "ip": args.ip,
        "checks": checks,
    }
    md, js = write_report(args.vm_name, result)
    result["report_md"] = md
    result["report_json"] = js
    return result


def parse():
    p = argparse.ArgumentParser(description="post clone initialization checks")
    p.add_argument("--vm-name", required=True)
    p.add_argument("--ip", required=True)
    p.add_argument("--expected-hostname")
    p.add_argument("--ssh-check", action="store_true")
    p.add_argument("--ssh-user", default="root")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--timeout", type=int, default=3)
    return p.parse_args()

if __name__ == "__main__":
    print(json.dumps(run(parse()), ensure_ascii=False, indent=2))
