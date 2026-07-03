import os, tempfile
from scripts.secret_manager import encrypt_value, decrypt_value, set_secret, get_secret, delete_secret, list_secret_keys

def test_round_trip():
    plain = "Hello-世界-123!@#"
    ct = encrypt_value(plain)
    assert ct != plain
    assert decrypt_value(ct) == plain

def test_secret_store():
    set_secret("PYTEST_KEY", "supersecret", description="测试")
    assert get_secret("PYTEST_KEY") == "supersecret"
    keys = [k["key"] for k in list_secret_keys()]
    assert "PYTEST_KEY" in keys
    delete_secret("PYTEST_KEY")
    assert get_secret("PYTEST_KEY") is None
