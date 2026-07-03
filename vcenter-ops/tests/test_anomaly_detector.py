from scripts.anomaly_detector import compute_baseline, detect_one
from scripts import metrics_collector as mc
from datetime import datetime
import json

def test_baseline():
    b = compute_baseline([0.5]*10 + [0.51, 0.49])
    assert b["samples"] == 12
    assert abs(b["mean"] - 0.5) < 0.05

def test_detect_spike(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "METRICS_DIR", tmp_path)
    monkeypatch.setattr(mc, "_today_file", lambda d=None: tmp_path / f"{(d or datetime.now()).strftime('%Y-%m-%d')}.jsonl")
    fp = mc._today_file()
    # 注入 15 个正常 + 1 个突刺
    for v in [0.5]*15 + [0.95]:
        with open(fp,"a") as f:
            f.write(json.dumps({"ts":datetime.now().isoformat(),"type":"ds_used","target":"PY-SPIKE","value":v})+"\n")
    r = detect_one("ds_used", "PY-SPIKE", since_days=1)
    assert r["anomaly"] is True
    assert r["type"] == "hard_threshold"
