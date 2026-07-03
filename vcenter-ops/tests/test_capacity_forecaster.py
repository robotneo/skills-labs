from scripts.capacity_forecaster import linear_regression, forecast_one
from scripts import metrics_collector as mc
from datetime import datetime, timedelta
import json

def test_linear_regression():
    slope, intercept, r2 = linear_regression([1,2,3,4], [2,4,6,8])
    assert abs(slope - 2.0) < 0.001
    assert abs(intercept) < 0.001
    assert abs(r2 - 1.0) < 0.001

def test_forecast(tmp_path, monkeypatch):
    # 注入临时 metrics 数据
    monkeypatch.setattr(mc, "METRICS_DIR", tmp_path)
    monkeypatch.setattr(mc, "_today_file", lambda d=None: tmp_path / f"{(d or datetime.now()).strftime('%Y-%m-%d')}.jsonl")

    # 14 天线性增长 0.30 → 0.69
    for day_offset in range(14, 0, -1):
        ts = (datetime.now() - timedelta(days=day_offset)).isoformat(timespec='seconds')
        val = round(0.30 + (14 - day_offset) * 0.03, 4)
        fp = tmp_path / f"{(datetime.now() - timedelta(days=day_offset)).strftime('%Y-%m-%d')}.jsonl"
        with open(fp, "a") as f:
            f.write(json.dumps({"ts":ts,"type":"ds_used","target":"PY-DS","value":val})+"\n")

    r = forecast_one("ds_used", "PY-DS", since_days=20, threshold=0.9, min_samples=10)
    assert r["status"] in ("warning", "critical")
    assert r["r_squared"] > 0.99
    assert 5 <= r["days_until_threshold"] <= 10
