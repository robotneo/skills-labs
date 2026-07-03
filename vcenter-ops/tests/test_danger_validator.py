import pytest, time
from scripts.danger_validator import scan_danger, validate_danger, confirm_danger, is_confirmed, DangerConfirmRequired

def test_scan_hit():
    m = scan_danger("prod-mysql-master-01", "delete_vm")
    assert len(m) >= 2

def test_scan_whitelisted():
    m = scan_danger("dev-test01", "delete_vm")
    assert m == []

def test_validate_raise_and_confirm():
    import uuid
    target = f"pytest-prod-db-master-{uuid.uuid4().hex[:8]}"
    with pytest.raises(DangerConfirmRequired):
        validate_danger(target, "delete_vm")
    confirm_danger(target, "delete_vm")
    assert is_confirmed(target, "delete_vm")
    validate_danger(target, "delete_vm")  # 不抛
