from datetime import datetime
import scripts.change_window as cw

def test_disabled_pass():
    allowed, _, _ = cw.is_change_allowed("clone_vm", "any")
    assert allowed

def test_block_window(monkeypatch):
    def fake_cfg():
        return {
            "enabled": True,
            "actions": ["clone_vm","delete_vm"],
            "allow_windows": [{"weekdays":[0,1,2,3,4],"start":"09:00","end":"18:00"}],
            "block_windows": [{"weekdays":[0,1,2,3,4,5,6],"start":"00:00","end":"06:00","reason":"夜间"}],
            "blackout_dates": [],
            "whitelist_users": [],
            "whitelist_actions": ["list_all"],
        }
    monkeypatch.setattr(cw, "load_window_config", fake_cfg)

    night = datetime(2026,5,22,3,0)
    allowed, reason, _ = cw.is_change_allowed("clone_vm","x", now=night)
    assert not allowed and "夜间" in reason

    day = datetime(2026,5,22,14,0)
    allowed, _, _ = cw.is_change_allowed("clone_vm","x", now=day)
    assert allowed

def test_blackout(monkeypatch):
    def fake_cfg():
        return {"enabled":True,"actions":["clone_vm"],"allow_windows":[],
                "block_windows":[],"blackout_dates":["2026-01-01"],
                "whitelist_users":[],"whitelist_actions":[]}
    monkeypatch.setattr(cw, "load_window_config", fake_cfg)
    blackday = datetime(2026,1,1,12,0)
    allowed, _, _ = cw.is_change_allowed("clone_vm","x", now=blackday)
    assert not allowed
