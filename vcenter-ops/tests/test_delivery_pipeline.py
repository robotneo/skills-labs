import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = [
    "scripts/delivery_pipeline.py",
    "--name", "unit-web01",
    "--ip", "10.0.0.21",
    "--owner", "tester",
    "--env", "test",
    "--app", "web",
    "--template", "tpl",
    "--dc", "DC",
    "--cluster", "CL",
    "--datastore", "DS",
    "--network", "VLAN",
    "--gateway", "10.0.0.1",
]


def run(args):
    p = subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_delivery_plan_generates_report():
    res = run([BASE[0], "--action", "plan", *BASE[1:]])
    assert res["status"] == "success"
    assert res["steps"] == 9
    assert Path(res["report_md"]).exists()
    assert Path(res["report_json"]).exists()


def test_execute_requires_confirm():
    res = run([BASE[0], "--action", "execute", *BASE[1:], "--skip-clone"])
    assert res["status"] == "blocked"
