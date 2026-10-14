"""Profile-scoped declarative presets. They contain no execution authority."""
import json
import re
import sqlite3
import time

from ..domain.models import OperationError, fail
from ..infrastructure.store import canonical
from .registry import lookup


_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_CONTROL = {"confirm", "confirm_destruction", "plan_id", "request_id", "operation_id",
            "receipt", "binding", "remote_task", "dry_run", "wait", "search_id"}


def _validate(profile, name, command, params):
    if not isinstance(profile, str) or not _NAME.fullmatch(profile):
        fail("profile_required", "预设须显式指定有效 --profile", 3)
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        fail("preset_invalid", "预设名称只能含字母、数字、下划线和连字符，长度 1–64", 2)
    if not isinstance(params, dict) or len(canonical(params).encode("utf-8")) > 16384:
        fail("preset_invalid", "预设参数必须是至多 16 KiB 的对象", 2)
    if any(key in _CONTROL or any(word in key.lower() for word in ("password", "secret", "credential", "token"))
           for key in params if isinstance(key, str)):
        fail("preset_invalid", "预设不能保存执行控制、身份绑定或秘密字段", 2)
    try:
        spec = lookup(command)
        if spec.category != "remote_write":
            fail("preset_invalid", "预设仅支持已注册远端原子写命令", 2)
        spec.validate(params)
    except OperationError:
        fail("preset_invalid", "预设命令或参数不符合当前 schema", 2)
    return spec.path


class Presets:
    def __init__(self, store):
        self.store = store
        store.db.execute("CREATE TABLE IF NOT EXISTS presets (profile TEXT NOT NULL,name TEXT NOT NULL,payload TEXT NOT NULL,"
                         "created REAL NOT NULL,PRIMARY KEY(profile,name))")

    def save(self, profile, name, command, params, source=None):
        command = _validate(profile, name, command, params)
        if source is None:
            source = {"type": "explicit"}
        payload = {"schema_version": 1, "command": command, "params": params, "source": source}
        if len(canonical(payload).encode("utf-8")) > 16384:
            fail("preset_invalid", "预设内容超过 16 KiB", 2)
        with self.store.transaction():
            try:
                self.store.db.execute("INSERT INTO presets VALUES(?,?,?,?)",
                                      (profile, name, canonical(payload), time.time()))
            except sqlite3.IntegrityError:
                fail("preset_exists", "预设已存在，不会覆盖", 2)
            self.store.audit("preset_saved", profile + ":" + name)
        return self.show(profile, name)

    def show(self, profile, name):
        if not profile:
            fail("profile_required", "预设须显式指定 --profile", 3)
        row = self.store.db.execute("SELECT payload,created FROM presets WHERE profile=? AND name=?", (profile, name)).fetchone()
        if not row:
            fail("preset_not_found", "指定 Profile 下的预设不存在", 2)
        try:
            payload = json.loads(row["payload"])
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "command", "params", "source"} or payload["schema_version"] != 1:
                raise ValueError()
            _validate(profile, name, payload["command"], payload["params"])
            source = payload["source"]
            if not isinstance(source, dict):
                raise ValueError()
            if source == {"type": "explicit"}:
                pass
            elif (set(source) == {"type", "plan_id", "position"} and source["type"] == "history"
                  and isinstance(source["plan_id"], str) and re.fullmatch(r"[0-9a-f]{32}", source["plan_id"])
                  and type(source["position"]) is int and source["position"] >= 0):
                pass
            elif (set(source) == {"type", "source_vm_id"} and source["type"] == "vm"
                  and isinstance(source["source_vm_id"], str) and re.fullmatch(r"vm-\d+", source["source_vm_id"])):
                pass
            else:
                raise ValueError()
        except (ValueError, TypeError, KeyError, OperationError):
            fail("preset_corrupt", "预设损坏或不符合当前 schema", 4)
        return {"profile": profile, "name": name, "created": row["created"], **payload,
                "authorization": "not_inherited"}

    def list(self, profile, after_name="", limit=100):
        if not profile:
            fail("profile_required", "预设须显式指定 --profile", 3)
        rows = list(self.store.db.execute("SELECT name,created FROM presets WHERE profile=? AND name>? ORDER BY name LIMIT ?",
                                          (profile, after_name, limit + 1)))
        items = [{"name": row["name"], "created": row["created"]} for row in rows[:limit]]
        return {"scope": profile, "items": items, "truncated": len(rows) > limit,
                "next_cursor": items[-1]["name"] if items else after_name}

    def delete(self, profile, name):
        if not profile:
            fail("profile_required", "预设须显式指定 --profile", 3)
        with self.store.transaction():
            changed = self.store.db.execute("DELETE FROM presets WHERE profile=? AND name=?", (profile, name)).rowcount
            if not changed:
                fail("preset_not_found", "指定 Profile 下的预设不存在", 2)
            self.store.audit("preset_deleted", profile + ":" + name)
        return {"profile": profile, "deleted": name}
