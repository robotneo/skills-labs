"""Bounded, profile-aware views of existing plan and operation evidence."""
import json

from ..domain.models import fail


class History:
    def __init__(self, store):
        self.store = store

    def list(self, profile=None, after_id=0, limit=100, snapshot_max_id=None):
        maximum = self.store.db.execute("SELECT COALESCE(MAX(rowid),0) FROM plans").fetchone()[0]
        if snapshot_max_id is not None:
            maximum = min(maximum, snapshot_max_id)
        condition = " AND json_extract(payload,'$.profile')=?" if profile is not None else ""
        values = (after_id, maximum, profile, limit + 1) if profile is not None else (after_id, maximum, limit + 1)
        rows = list(self.store.db.execute(
            "SELECT rowid,id,status,created,json_extract(payload,'$.profile') AS profile "
            "FROM plans WHERE rowid>? AND rowid<=?" + condition + " ORDER BY rowid LIMIT ?", values))
        items = [self._summary(row) for row in rows[:limit]]
        return {"scope": profile if profile is not None else "all_local_profiles", "items": items,
                "truncated": len(rows) > limit, "next_cursor": items[-1]["cursor"] if items else after_id,
                "snapshot_max_id": maximum}

    def show(self, plan_id, profile=None):
        row = self.store.db.execute("SELECT rowid,id,status,created,payload FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            fail("history_not_found", "历史记录不存在于指定范围", 4)
        try:
            payload = json.loads(row["payload"])
            owner = payload["profile"]
            steps = payload["steps"]
            if not isinstance(owner, str) or not isinstance(steps, list):
                raise ValueError()
            commands = [step["command"] for step in steps]
            if any(not isinstance(command, str) for command in commands):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            fail("history_corrupt", "历史记录结构损坏", 4)
        if profile is not None and owner != profile:
            fail("history_not_found", "历史记录不存在于指定范围", 4)
        operations = [dict(item) for item in self.store.db.execute(
            "SELECT e.position,o.state FROM execution_steps e JOIN operations o ON o.id=e.operation_id "
            "WHERE e.plan_id=? ORDER BY e.position", (plan_id,))] if self._has_execution() else []
        return {"id": row["id"], "scope": profile if profile is not None else "all_local_profiles",
                "profile": owner, "source": "stored_plan", "status": row["status"],
                "created": row["created"], "commands": commands, "operations": operations,
                "step_count": len(steps), "replay": False}

    def reusable_step(self, plan_id, profile, position):
        if not profile:
            fail("profile_required", "预设须显式指定 --profile", 3)
        self.show(plan_id, profile)
        payload = self.store.plan(plan_id)["payload"]
        steps = payload["steps"]
        if position >= len(steps):
            fail("history_step_not_found", "指定步骤不存在", 2)
        step = steps[position]
        if not isinstance(step, dict) or not isinstance(step.get("command"), str) or not isinstance(step.get("params"), dict):
            fail("history_corrupt", "历史步骤结构损坏", 4)
        return step["command"], step["params"]

    def _has_execution(self):
        return self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_steps'").fetchone() is not None

    @staticmethod
    def _summary(row):
        return {"cursor": row["rowid"], "id": row["id"], "profile": row["profile"],
                "source": "stored_plan", "status": row["status"], "created": row["created"]}
