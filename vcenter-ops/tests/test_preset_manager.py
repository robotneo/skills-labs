import pytest
from scripts.preset_manager import apply_preset, save_preset, delete_preset, get_preset, parse_preset_from_text

def test_apply_builtin():
    m = apply_preset("dev-small", {"new_name": "x"})
    assert m["cpus"] == 2
    assert m["memory_gb"] == 4
    assert m["new_name"] == "x"

def test_apply_unknown():
    with pytest.raises(ValueError):
        apply_preset("nope")

def test_save_and_delete():
    save_preset("pytest-tmp", {"cpus": 16, "memory_gb": 32}, overwrite=True)
    assert get_preset("pytest-tmp")["params"]["cpus"] == 16
    delete_preset("pytest-tmp")
    assert get_preset("pytest-tmp") is None

def test_parse_at():
    assert parse_preset_from_text("克隆 @dev-small foo") == "dev-small"
    assert parse_preset_from_text("无at") is None
