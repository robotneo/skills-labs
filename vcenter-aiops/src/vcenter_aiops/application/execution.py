"""Confirmed execution with durable intent, no automatic resubmission.

Provider methods exchange JSON values only. A timeout, a missing remote task,
or a lost response is uncertainty, not a reason to repeat a remote mutation.
"""
import hashlib
import json
import time
import uuid

from ..domain.models import Result, SubmissionRejected, fail
from ..infrastructure.store import canonical
from ..infrastructure.locking import exclusive


class Engine:
    def __init__(self, store, provider, profile, timeout=30):
        self.store, self.provider, self.profile, self.timeout = store, provider, profile, timeout
        if hasattr(provider, "configure_evidence"):
            provider.configure_evidence(store, profile)
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS execution_requests (
                request_id TEXT PRIMARY KEY, request TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES plans(id));
            CREATE TABLE IF NOT EXISTS execution_steps (
                plan_id TEXT NOT NULL REFERENCES plans(id), position INTEGER NOT NULL,
                operation_id TEXT NOT NULL REFERENCES operations(id), receipt TEXT, observation TEXT,
                PRIMARY KEY(plan_id, position));
            CREATE TABLE IF NOT EXISTS compensation_links (
                plan_id TEXT PRIMARY KEY REFERENCES plans(id), source_id TEXT NOT NULL REFERENCES plans(id),
                omitted TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resume_confirmations (
                plan_id TEXT PRIMARY KEY REFERENCES plans(id), value TEXT NOT NULL,
                expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS execution_epochs (
                plan_id TEXT PRIMARY KEY REFERENCES plans(id), epoch INTEGER NOT NULL);
        ''')

    def preview(self, command, params, request_id=None):
        return self.preview_steps([{"command": command, "params": params}], request_id)

    def preview_steps(self, steps, request_id=None):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
            fail("plan_invalid", "计划须包含 1–100 个明确步骤", 2)
        for step in steps:
            if not isinstance(step, dict) or set(step) != {"command", "params"} or not isinstance(step["params"], dict):
                fail("plan_invalid", "每个步骤须包含 command 和 params", 2)
        request_id = request_id or uuid.uuid4().hex
        request = canonical({"steps": steps, "profile": self.profile})
        row = self.store.db.execute("SELECT * FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
        if row:
            if row["request"] != request:
                fail("request_conflict", "同一请求 ID 不能更改 Profile、命令或参数", 2)
            return self.result(row["plan_id"])
        bound = self.provider.bind_steps(steps) if hasattr(self.provider, "bind_steps") else [{**step, "binding": self.provider.preflight(step["command"], step["params"])} for step in steps]
        payload = canonical({"schema_version": 1, "profile": self.profile,
                             "steps": bound, "description": "固定对象变更计划"})
        digest = hashlib.sha256(payload.encode()).hexdigest()
        plan_id = uuid.uuid4().hex
        with self.store.transaction():
            # Serialise concurrent previews, including the request-id check.
            row = self.store.db.execute("SELECT * FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row["request"] != request:
                    fail("request_conflict", "同一请求 ID 参数冲突", 2)
                plan_id = row["plan_id"]
            else:
                self.store.db.execute("INSERT INTO plans VALUES(?,?,?,?,?)", (plan_id, payload, digest, "awaiting_confirmation", time.time()))
                self.store.db.execute("INSERT INTO execution_requests VALUES(?,?,?)", (request_id, request, plan_id))
                self.store.audit("plan_previewed", plan_id)
        return self.result(plan_id)

    def checked_plan(self, plan_id):
        plan = self.store.plan(plan_id)
        if plan["payload"]["profile"] != self.profile:
            fail("profile_mismatch", "计划绑定的 Profile 不匹配", 4)
        if hashlib.sha256(canonical(plan["payload"]).encode()).hexdigest() != plan["digest"]:
            fail("plan_corrupted", "计划内容摘要不匹配，禁止执行", 4)
        return plan

    def validate(self, plan_id):
        with exclusive(self.store.path.parent / ("plan-" + plan_id + ".lock"), blocking=False) as acquired:
            plan = self.checked_plan(plan_id)
            if not acquired or plan["status"] not in ("awaiting_confirmation", "ready_to_resume"):
                fail("plan_validation_blocked", "仅校验待确认或待恢复计划；运行或未知结果须先核对原任务", 4)
            completed = {row[0] for row in self.store.db.execute(
                "SELECT e.position FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? AND o.state='succeeded'", (plan_id,))}
            pending = [(i, step) for i, step in enumerate(plan["payload"]["steps"]) if i not in completed]
            inputs = [{"command": step["command"], "params": step["params"]} for _, step in pending]
            actual = self.provider.bind_steps(inputs) if hasattr(self.provider, "bind_steps") else [
                {**step, "binding": self.provider.preflight(step["command"], step["params"])} for step in inputs]
            matches = getattr(self.provider, "matches", lambda expected, observed: expected == observed)
            details = [{"position": i, "target": step["binding"]["target"], "unchanged": matches(step["binding"], observed["binding"])}
                       for (i, step), observed in zip(pending, actual)]
            return Result(data={"valid": len(actual) == len(pending) and all(d["unchanged"] for d in details),
                                "steps": details, "completed_steps": sorted(completed)},
                          warnings=["验证不授予执行权限，不提交变更；实际提交仍须重新检查"])

    def result(self, plan_id):
        plan = self.checked_plan(plan_id)
        steps = [dict(row) for row in self.store.db.execute(
            "SELECT e.position,e.operation_id,o.state,o.remote_task,e.receipt,e.observation FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? ORDER BY e.position", (plan_id,))]
        for step in steps:
            for field in ("receipt", "observation"):
                step[field] = json.loads(step[field]) if step[field] else None
        data = {**plan, "execution": steps}
        confirmation = self.store.db.execute("SELECT * FROM resume_confirmations WHERE plan_id=?", (plan_id,)).fetchone()
        data["confirmation"] = confirmation["value"] if plan["status"] == "ready_to_resume" and confirmation else plan["digest"]
        data["confirmation_expires"] = confirmation["expires"] if plan["status"] == "ready_to_resume" and confirmation else plan["created"] + 600
        if any(s["binding"]["risk"] == "destructive" for s in plan["payload"]["steps"]):
            data["second_confirmation"] = "DESTROY:" + plan["digest"]
        rejection = next((s["observation"]["error"] for s in reversed(steps)
                          if s["observation"] and s["observation"].get("state") == "not_submitted"), None)
        return Result(status=plan["status"], data=data,
                      error=rejection,
                      warnings=list(dict.fromkeys(w for s in plan["payload"]["steps"] for w in s["binding"].get("warnings", []))),
                      operation_id=steps[0]["operation_id"] if len(steps) == 1 else None,
                      next_action={"command": "plan apply", "plan_id": plan_id, "confirm": data["confirmation"]} if plan["status"] in ("awaiting_confirmation", "ready_to_resume")
                      else {"command": "plan reconcile", "plan_id": plan_id} if plan["status"] in ("running", "executing", "reconciliation_required") else None)

    def apply(self, plan_id, confirmation, second_confirmation=None, wait=True):
        self.checked_plan(plan_id)
        with exclusive(self.store.path.parent / ("plan-" + plan_id + ".lock"), blocking=False) as acquired:
            if not acquired:
                result = self.result(plan_id)
                result.warnings.append("另一进程正在执行此计划，本次未重复执行")
                return result
            return self._apply(plan_id, confirmation, second_confirmation, wait)

    def _apply(self, plan_id, confirmation, second_confirmation=None, wait=True):
        plan = self.checked_plan(plan_id)
        if plan["status"] not in ("awaiting_confirmation", "ready_to_resume"):
            # A previous process may still own submission; never resume by apply.
            return self.result(plan_id)
        self.check_confirmation(plan, confirmation)
        steps = plan["payload"]["steps"]
        if any(s["binding"]["risk"] == "destructive" for s in steps) and second_confirmation != "DESTROY:" + plan["digest"]:
            fail("second_confirmation_required", "危险操作需要第二次明确确认精确计划", 4)
        completed = {row[0] for row in self.store.db.execute("SELECT e.position FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? AND o.state='succeeded'", (plan_id,))}
        checked_targets = set()
        for index, step in enumerate(steps):
            if index in completed:
                continue
            if step["binding"]["target"] in checked_targets:
                continue  # Projected conditions are rechecked at actual submission.
            checked_targets.add(step["binding"]["target"])
            matches = getattr(self.provider, "matches", lambda a, b: a == b)
            if not matches(step["binding"], self.provider.preflight(step["command"], step["params"])):
                fail("plan_stale", "目标身份或前置条件变化，请重新预览", 4)
        with self.store.transaction():
            self.check_confirmation(plan, confirmation)
            changed = self.store.db.execute("UPDATE plans SET status='executing' WHERE id=? AND status=?", (plan_id, plan["status"])).rowcount
            if not changed:
                fail("plan_busy", "计划已被另一进程认领", 6)
            self.store.audit("confirmation_consumed", plan_id)
            self.store.db.execute("UPDATE resume_confirmations SET consumed=1 WHERE plan_id=?", (plan_id,))
            self.store.db.execute("INSERT INTO execution_epochs VALUES(?,1) ON CONFLICT(plan_id) DO UPDATE SET epoch=epoch+1", (plan_id,))
            epoch = self.epoch(plan_id)
        for index, step in enumerate(steps):
            if index in completed:
                continue
            operation = self.store.prepare(plan_id + ":" + str(index), step["binding"]["target"], step)
            with self.store.transaction():
                self.store.db.execute("INSERT INTO execution_steps(plan_id,position,operation_id) VALUES(?,?,?)", (plan_id, index, operation["id"]))
            try:
                self.store.claim(operation["id"])
            except Exception:
                self.status(plan_id, "reconciliation_required")
                raise
            try:
                receipt = self.provider.submit(step["command"], step["params"], step["binding"])
            except SubmissionRejected as exc:
                observation = {"state": "not_submitted", "error": {"code": exc.code, "message": str(exc), "retryable": False}}
                with self.store.transaction():
                    self.store.db.execute("UPDATE operations SET state='failed' WHERE id=? AND state='submitting'", (operation["id"],))
                    self.store.db.execute("UPDATE execution_steps SET observation=? WHERE plan_id=? AND position=?", (canonical(observation), plan_id, index))
                    self.store.audit("operation_not_submitted", operation["id"])
                has_completed = self.store.db.execute("SELECT 1 FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? AND o.state='succeeded'", (plan_id,)).fetchone()
                self.status(plan_id, "partial" if has_completed else "failed", epoch)
                return self.result(plan_id)
            except Exception:
                self.store.mark_unknown(operation["id"])
                self.status(plan_id, "reconciliation_required")
                return self.result(plan_id)
            try:
                # Receipt persistence and operation state change are one transaction.
                with self.store.transaction():
                    self.store.db.execute("UPDATE execution_steps SET receipt=? WHERE plan_id=? AND position=?", (canonical(receipt), plan_id, index))
                    self.store.db.execute("UPDATE operations SET state='running',remote_task=? WHERE id=?", (receipt.get("task_id"), operation["id"]))
                    self.store.audit("operation_receipted", operation["id"])
            except Exception:
                self.store.mark_unknown(operation["id"])
                self.status(plan_id, "reconciliation_required")
                return self.result(plan_id)
            if not self.poll(plan_id, index, step, receipt, wait, epoch):
                return self.result(plan_id)
        self.status(plan_id, "succeeded", epoch)
        return self.result(plan_id)

    def epoch(self, plan_id):
        row = self.store.db.execute("SELECT epoch FROM execution_epochs WHERE plan_id=?", (plan_id,)).fetchone()
        return row[0] if row else 0

    def status(self, plan_id, state, epoch=None, derive=False):
        with self.store.transaction():
            if epoch is not None and epoch != self.epoch(plan_id):
                return
            if derive:
                states = [row[0] for row in self.store.db.execute(
                    "SELECT o.state FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=?", (plan_id,))]
                total = len(self.store.plan(plan_id)["payload"]["steps"])
                if not states or any(s in ("prepared", "submitting", "unknown") for s in states):
                    state = "reconciliation_required"
                elif any(s in ("failed", "cancelled") for s in states):
                    state = "partial" if "succeeded" in states else "failed"
                elif any(s in ("running", "cancel_requested") for s in states):
                    state = "running"
                elif all(s == "succeeded" for s in states):
                    state = "succeeded" if len(states) == total else "ready_to_resume"
                else:
                    state = "reconciliation_required"
            current = self.store.plan(plan_id)["status"]
            terminal = ("succeeded", "failed", "partial", "archived", "compensated", "compensation_partial", "compensation_failed")
            if current in terminal and state not in (current, "archived"):
                return  # A late observer cannot regress a completed/compensated plan.
            if current == "compensating":
                return
            self.store.db.execute("UPDATE plans SET status=? WHERE id=?", (state, plan_id))
            self.store.audit("plan_" + state, plan_id)
            if state == "ready_to_resume":
                record = self.store.db.execute("SELECT * FROM resume_confirmations WHERE plan_id=?", (plan_id,)).fetchone()
                if not record or record["consumed"] or record["expires"] <= time.time():
                    self.store.db.execute("INSERT OR REPLACE INTO resume_confirmations VALUES(?,?,?,0)", (plan_id, uuid.uuid4().hex, time.time() + 600))
                    self.store.audit("resume_confirmation_issued", plan_id)
            link = self.store.db.execute("SELECT * FROM compensation_links WHERE plan_id=?", (plan_id,)).fetchone()
            if link and state in ("succeeded", "failed", "partial", "reconciliation_required", "running"):
                source_state = ("compensation_partial" if json.loads(link["omitted"]) else "compensated") if state == "succeeded" else "compensation_failed" if state == "failed" else "compensation_partial" if state == "partial" else "compensating"
                if state == "failed":
                    completed = self.store.db.execute("SELECT 1 FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? AND o.state='succeeded'", (plan_id,)).fetchone()
                    if completed:
                        source_state = "compensation_partial"
                self.store.db.execute("UPDATE plans SET status=? WHERE id=?", (source_state, link["source_id"]))
                self.store.audit(source_state, link["source_id"])

    def check_confirmation(self, plan, value):
        if plan["status"] == "ready_to_resume":
            row = self.store.db.execute("SELECT * FROM resume_confirmations WHERE plan_id=?", (plan["id"],)).fetchone()
            valid = row and not row["consumed"] and value == row["value"] and time.time() < row["expires"]
        else:
            valid = value == plan["digest"] and time.time() < plan["created"] + 600
        if not valid:
            fail("confirmation_invalid", "确认不匹配、已消费或已过期；恢复须使用本轮 confirmation 值", 4)

    def poll(self, plan_id, index, step, receipt, wait, epoch=None):
        deadline = time.monotonic() + self.timeout
        delay = 0.2
        pending_at_deadline = None
        operation_id = self.store.db.execute("SELECT operation_id FROM execution_steps WHERE plan_id=? AND position=?", (plan_id, index)).fetchone()[0]
        while True:
            try:
                observation = pending_at_deadline or self.provider.observe(receipt, step["binding"])
                remote = observation["state"]
                if (receipt.get("kind") == "guest_wrapper" and observation.get("phase") == "completion_pending"
                        and wait and time.monotonic() >= deadline):
                    observation = {**observation, "state": "unknown", "error": {
                        "code": "guest_completion_timeout", "message": "等待期限内未获得完成证据；不证明进程存活，不会重发", "retryable": False}}
                    remote = "unknown"
                if remote == "success" and not self.provider.verify(step["command"], step["params"], step["binding"], observation):
                    remote = "unknown"
            except Exception:
                observation, remote = {"state": "unknown"}, "unknown"
            state = {"success": "succeeded", "error": "failed", "queued": "running", "running": "running"}.get(remote, "unknown")
            if state == "failed" and observation.get("cancelled") is True:
                state = "cancelled"
            with self.store.transaction():
                row = self.store.db.execute(
                    "SELECT o.state, e.observation FROM operations o "
                    "JOIN execution_steps e ON e.operation_id=o.id "
                    "WHERE e.plan_id=? AND e.position=?", (plan_id, index)).fetchone()
                current = row["state"]
                try:
                    observation_text = canonical(observation)
                    # SQLite binds TEXT as UTF-8: a lone surrogate survives
                    # json.dumps but fails the bind, so probe the encoding too.
                    observation_text.encode("utf-8")
                except (TypeError, ValueError, UnicodeEncodeError):
                    # The remote write was already submitted and this evidence
                    # cannot be durably stored: unprovable result, never a reason
                    # to resubmit. Replace it with a structured unknown and route
                    # the plan to reconciliation (exit 6), keeping operation id.
                    observation = {"state": "unknown", "error": {
                        "code": "observation_unserializable",
                        "message": "写后观测无法序列化保存，远端结果不可证明；请核对，不自动重发",
                        "retryable": False}}
                    observation_text = canonical(observation)
                    state = "unknown"
                if current in ("succeeded", "failed", "cancelled"):
                    state = current
                # M-1 (plan A): skip the three fsync-bearing writes while neither
                # the operation state nor its observation changed. State
                # transitions and the first terminal write still persist; this is
                # safe because the reconciliation model never relies on a
                # per-poll running heartbeat (no WAL/-shm side files introduced).
                unchanged = state == current and observation_text == (row["observation"] if row else None)
                if not unchanged:
                    self.store.db.execute("UPDATE operations SET state=? WHERE id=?", (state, operation_id))
                    self.store.db.execute("UPDATE execution_steps SET observation=? WHERE plan_id=? AND position=?", (observation_text, plan_id, index))
                    self.store.audit("operation_" + state, operation_id)
            if state == "succeeded":
                return True
            if state != "running":
                completed = self.store.db.execute("SELECT 1 FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? AND o.state='succeeded'", (plan_id,)).fetchone()
                self.status(plan_id, "reconciliation_required" if state == "unknown" else "partial" if completed else "failed", epoch)
                return False
            if not wait or time.monotonic() >= deadline:
                if wait and receipt.get("kind") == "guest_wrapper" and observation.get("phase") == "completion_pending":
                    # Persistence may have crossed the deadline. Finalize the
                    # already-read pending evidence locally, without another call.
                    pending_at_deadline = observation
                    continue
                self.status(plan_id, "running", epoch)
                return False
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, 2)

    def reconcile(self, plan_id, wait=False):
        return self._reconcile(plan_id, wait)

    def _reconcile(self, plan_id, wait, *, recovery_owned=False):
        plan = self.checked_plan(plan_id)
        epoch = self.epoch(plan_id)
        if plan["status"] in ("succeeded", "failed", "partial", "awaiting_confirmation", "archived", "compensated", "compensation_partial", "compensation_failed", "compensating"):
            return self.result(plan_id)
        rows = list(self.store.db.execute("SELECT * FROM execution_steps WHERE plan_id=? ORDER BY position", (plan_id,)))
        if not rows:
            self.finish_reconcile(plan_id, "reconciliation_required", epoch, recovery_owned=recovery_owned)
            return self.result(plan_id)
        for row in rows:
            operation = self.store.operation(row["operation_id"])
            if operation["state"] == "succeeded":
                continue
            if not row["receipt"]:
                receipt = None
                if operation["state"] in ("submitting", "unknown") and hasattr(self.provider, "recover_receipt"):
                    if not recovery_owned:
                        with exclusive(self.store.path.parent / ("plan-" + plan_id + ".lock"), blocking=False) as acquired:
                            if not acquired:
                                result = self.result(plan_id)
                                result.warnings.append("计划仍由提交或恢复入口持有；本次未恢复缺失回执，也未修改执行状态")
                                return result
                            # Re-read under the same lock held through recovery,
                            # receipt persistence, observation and final state.
                            return self._reconcile(plan_id, wait, recovery_owned=True)
                    step = plan["payload"]["steps"][row["position"]]
                    try:
                        receipt = self.provider.recover_receipt(step["command"], step["params"], step["binding"])
                    except Exception:
                        pass  # Never turn failed recovery into a repeated submission.
                if receipt is None:
                    self.finish_reconcile(plan_id, "reconciliation_required", epoch, recovery_owned=recovery_owned)
                    return self.result(plan_id)
                with self.store.transaction():
                    self.store.db.execute("UPDATE execution_steps SET receipt=? WHERE plan_id=? AND position=? AND receipt IS NULL",
                                          (canonical(receipt), plan_id, row["position"]))
                row = self.store.db.execute("SELECT * FROM execution_steps WHERE plan_id=? AND position=?", (plan_id, row["position"])).fetchone()
            if not self.poll(plan_id, row["position"], plan["payload"]["steps"][row["position"]], json.loads(row["receipt"]), wait, epoch):
                return self.result(plan_id)
        self.finish_reconcile(plan_id, "succeeded" if len(rows) == len(plan["payload"]["steps"]) else "ready_to_resume", epoch,
                              recovery_owned=recovery_owned)
        return self.result(plan_id)

    def finish_reconcile(self, plan_id, state, epoch, *, recovery_owned=False):
        if recovery_owned:
            # Missing-receipt recovery already owns the OS lock. Reacquiring it
            # through another file handle would block our own final transition.
            self.status(plan_id, state, epoch, derive=True)
            return
        # Prevent ready_to_resume while an apply owner is between two steps.
        # The OS releases this lock on process death, permitting recovery.
        with exclusive(self.store.path.parent / ("plan-" + plan_id + ".lock"), blocking=False) as acquired:
            if acquired:
                # The caller's snapshot may predate later steps in this epoch.
                self.status(plan_id, state, epoch, derive=True)

    def archive(self, plan_id):
        plan = self.checked_plan(plan_id)
        if plan["status"] not in ("succeeded", "failed", "archived", "compensated", "compensation_partial", "compensation_failed"):
            fail("plan_unfinished", "未结束计划不能归档", 4)
        self.status(plan_id, "archived")
        return self.result(plan_id)

    def rollback(self, plan_id):
        plan = self.checked_plan(plan_id)
        if plan["status"] not in ("succeeded", "failed", "partial"):
            fail("compensation_blocked", "只有已结束且结果明确的计划可以预览补偿", 4)
        steps, omitted, groups = [], [], {}
        rows = list(self.store.db.execute("SELECT e.position,e.observation,o.state FROM execution_steps e JOIN operations o ON o.id=e.operation_id WHERE e.plan_id=? ORDER BY e.position DESC", (plan_id,)))
        for row in rows:
            if row["state"] != "succeeded":
                continue
            step = plan["payload"]["steps"][row["position"]]
            before, p, command = step["binding"]["before"], step["params"], step["command"]
            params = {}
            if command == "vm rename":
                params["new_name"] = before["name"]
            elif command == "vm reconfigure" and ("memory_gb" not in p or before["memory_mb"] % 1024 == 0):
                if "disks" in p:
                    omitted.append({"position": row["position"], "command": command, "fields": ["disks"],
                                    "reason": "磁盘新增和扩容不可保证补偿；不会删除或缩容"})
                if "cpu" in p:
                    params["cpu"] = before["cpu"]
                if "memory_gb" in p:
                    params["memory_gb"] = before["memory_mb"] // 1024
                if not params:
                    continue
            else:
                omitted.append({"position": row["position"], "command": command, "reason": "没有可保证恢复原状态的补偿，不会伪造回滚"})
                continue
            key = (step["binding"]["target"], command)
            params["vm_id"] = p["vm_id"]
            if key not in groups:
                groups[key] = {"command": command, "params": {}, "expected": {}, "binding": step["binding"], "observation": json.loads(row["observation"])}
            group = groups[key]
            group["params"].update(params)  # Reverse traversal retains the earliest before value.
            for field, value in p.items():
                group["expected"].setdefault(field, value)  # Latest written value per field.
        for group in groups.values():
            if not self.provider.verify(group["command"], group["expected"], group["binding"], group["observation"]):
                fail("compensation_stale", "执行后对象已变化，请人工核对后创建新计划", 4)
            steps.append({"command": group["command"], "params": group["params"]})
        if not steps:
            return Result(status="failed", data={"uncompensated": omitted}, error={"code": "compensation_unavailable", "message": "没有可执行的补偿步骤", "retryable": False})
        result = self.preview_steps(steps, "compensate:" + plan_id)
        with self.store.transaction():
            self.store.db.execute("INSERT OR IGNORE INTO compensation_links VALUES(?,?,?)", (result.data["id"], plan_id, canonical(omitted)))
            self.store.audit("compensation_previewed", plan_id)
        result.data["compensation_of"] = plan_id
        result.data["uncompensated"] = omitted
        return result

    def cancel(self, operation_id, confirmation):
        operation = self.store.operation(operation_id)
        row = self.store.db.execute("SELECT * FROM execution_steps WHERE operation_id=?", (operation_id,)).fetchone()
        if row:
            plan = self.checked_plan(row["plan_id"])
            step = plan["payload"]["steps"][row["position"]]
            if step["command"] == "vm guest-exec" and step["binding"].get("provider_kind") == "guest":
                fail("cancellation_unsupported", "Guest 包装器不支持可保证身份的取消；不会发送 Kill", 4)
        if not row or not row["receipt"] or not operation["remote_task"]:
            fail("reconciliation_required", "无法定位原远端任务，不能宣告取消或重发", 6)
        plan = self.checked_plan(row["plan_id"])
        if confirmation != operation["remote_task"]:
            fail("confirmation_required", "取消须明确确认精确的 server:task 身份", 4)
        with self.store.transaction():
            changed = self.store.db.execute("UPDATE operations SET state='cancel_requested' WHERE id=? AND state IN ('running','unknown')", (operation_id,)).rowcount
            if not changed:
                fail("transition_invalid", "操作已结束或正在处理取消", 4)
            self.store.audit("cancel_requested", operation_id)
        try:
            self.provider.cancel(json.loads(row["receipt"]), plan["payload"]["steps"][row["position"]]["binding"])
        except Exception:
            self.store.mark_unknown(operation_id)
            self.status(row["plan_id"], "reconciliation_required")
        return self.result(row["plan_id"])
