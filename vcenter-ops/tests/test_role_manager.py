from scripts.role_manager import list_roles, get_role, get_role_actions, has_permission

def test_builtin_roles():
    roles = list_roles()
    names = [r["name"] for r in roles]
    assert "guest" in names and "operator" in names and "admin" in names

def test_admin_wildcard():
    actions = get_role_actions("admin")
    assert "*" in actions

def test_guest_readonly():
    actions = get_role_actions("guest")
    assert "list_all" in actions
    assert "delete_vm" not in actions

def test_disabled_by_default_all_pass():
    # 默认 enabled=False，all pass
    assert has_permission("anyone", "delete_vm") is True
