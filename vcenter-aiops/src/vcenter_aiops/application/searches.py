"""Durable read-task receipts, kept separate from mutation target locks."""
import json
import time
import uuid

from ..domain.models import OperationError, Result, fail
from ..infrastructure.store import canonical


class Searches:
    def __init__(self, store, provider, profile):
        self.store, self.provider, self.profile = store, provider, profile
        store.db.execute('''CREATE TABLE IF NOT EXISTS datastore_searches (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, profile TEXT NOT NULL,
            params TEXT NOT NULL, scope TEXT NOT NULL, receipt TEXT, state TEXT NOT NULL,
            result TEXT, created REAL NOT NULL)''')

    def record(self, search_id):
        row = self.store.db.execute("SELECT * FROM datastore_searches WHERE id=?", (search_id,)).fetchone()
        if not row:
            fail("search_not_found", "搜索记录不存在", 2)
        if row["profile"] != self.profile:
            fail("profile_mismatch", "搜索记录绑定其他 Profile", 4)
        return dict(row)

    def result(self, search_id):
        row = self.record(search_id)
        state = row["state"]
        # A crash before the receipt is saved cannot prove no task was started.
        if state == "submitting":
            state = "reconciliation_required"
        data = {"search_id": search_id, "request_id": row["request_id"], "scope": json.loads(row["scope"]),
                "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
                "result": json.loads(row["result"]) if row["result"] else None, "created": row["created"]}
        next_action = None
        warnings = []
        if state in ("running", "reconciliation_required"):
            if row["receipt"]:
                next_action = {"command": "datastore search-status", "search_id": search_id, "profile": self.profile}
            else:
                warnings.append("未保存任务回执，无法自动定位原任务；请在 vCenter 人工核对，不自动重提搜索")
        return Result(status=state, data=data, operation_id=search_id,
                      target={"profile": self.profile, "instance_uuid": data["scope"]["server_uuid"]},
                      next_action=next_action, warnings=warnings)

    def start(self, params, request_id=None, timeout=30):
        if not self.profile:
            fail("profile_required", "搜索记录需要明确 Profile", 2)
        request_id = request_id or uuid.uuid4().hex
        encoded = canonical(params)
        row = self.store.db.execute("SELECT * FROM datastore_searches WHERE request_id=?", (request_id,)).fetchone()
        if row:
            if row["profile"] != self.profile or row["params"] != encoded:
                fail("request_conflict", "同一请求 ID 不能更改搜索参数或 Profile", 2)
            return self.result(row["id"])
        scope = self.provider.prepare(**params)
        search_id = uuid.uuid4().hex
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM datastore_searches WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row["profile"] != self.profile or row["params"] != encoded:
                    fail("request_conflict", "同一请求 ID 参数冲突", 2)
                return self.result(row["id"])
            self.store.db.execute("INSERT INTO datastore_searches VALUES(?,?,?,?,?,NULL,'submitting',NULL,?)",
                                  (search_id, request_id, self.profile, encoded, canonical(scope), time.time()))
            self.store.audit("datastore_search_submitting", search_id)
        try:
            receipt = self.provider.submit(scope)
            with self.store.transaction():
                self.store.db.execute("UPDATE datastore_searches SET receipt=?,state='running' WHERE id=?", (canonical(receipt), search_id))
                self.store.audit("datastore_search_receipted", search_id)
        except Exception:
            self.update(search_id, "reconciliation_required", None)
            return self.result(search_id)
        return self.reconcile(search_id, timeout)

    def update(self, search_id, state, data):
        with self.store.transaction():
            current = self.record(search_id)
            if current["state"] in ("succeeded", "failed"):
                return  # Late observers cannot overwrite a persisted terminal result.
            self.store.db.execute("UPDATE datastore_searches SET state=?,result=? WHERE id=?", (state, canonical(data) if data is not None else None, search_id))
            self.store.audit("datastore_search_" + state, search_id)

    def reconcile(self, search_id, timeout=0):
        row = self.record(search_id)
        if row["state"] in ("succeeded", "failed") or not row["receipt"]:
            return self.result(search_id)
        try:
            data = self.provider.observe(json.loads(row["receipt"]), timeout)
            state = data["state"]
            if state not in ("running", "succeeded"):
                state = "reconciliation_required"
        except OperationError as exc:
            if exc.code in ("server_mismatch", "task_identity_mismatch"):
                raise
            state = "failed" if exc.code == "datastore_search_failed" else "reconciliation_required"
            data = {"error": {"code": exc.code, "message": str(exc)}}
        except Exception:
            state, data = "reconciliation_required", {"error": {"code": "search_observation_unknown", "message": "无法核对原搜索任务；不自动重新提交"}}
        self.update(search_id, state, data)
        return self.result(search_id)

    def list(self, limit=100):
        return Result(data=[dict(row) for row in self.store.db.execute(
            "SELECT id,request_id,state,created FROM datastore_searches WHERE profile=? ORDER BY created DESC LIMIT ?", (self.profile, limit))])
