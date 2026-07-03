import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    p = subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_asset_upsert_export_and_sd(tmp_path):
    vm = "10.0.0.10-test-vm"
    res = run("scripts/asset_registry.py", "--action", "upsert", "--vm-name", vm, "--ip", "10.0.0.10", "--owner", "tester", "--env", "test", "--app", "demo", "--monitoring-status", "pending")
    assert res["status"] == "success"
    got = run("scripts/asset_registry.py", "--action", "get", "--vm-name", vm)
    assert got["record"]["ip"] == "10.0.0.10"
    out = tmp_path / "sd.json"
    sd = run("scripts/monitoring_integrator.py", "--action", "prometheus_sd", "--output", str(out), "--port", "9100")
    assert sd["status"] == "success"
    data = json.loads(out.read_text())
    assert any("10.0.0.10:9100" in x["targets"] for x in data)
    retired = run("scripts/asset_registry.py", "--action", "retire", "--vm-name", vm)
    assert retired["status"] == "success"
