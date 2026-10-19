"""Transactional operation intents and scoped IP leases. No remote calls."""
import hashlib
import ipaddress
import json
import os
import re
import stat
import sqlite3
import time
import uuid
from contextlib import contextmanager

from ..domain.models import fail
from .paths import ensure_private


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parent_scope(payload):
    step = json.loads(payload)
    if step.get("command") not in ("deploy linked-clone", "vm delete", "vm snapshot-delete", "vm snapshot-revert", "vm migrate"):
        return None
    binding = step.get("binding", {})
    server, parent = binding.get("server_uuid"), binding.get("instance_uuid")
    return (server, parent) if server and parent else None


class Store:
    def __init__(self, path):
        self.path = path
        ensure_private(path.parent)
        if path.exists():
            self._verify_private_db(path)
        else:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                self._verify_private_db(path)  # Raced with another process creating it.
            else:
                os.close(fd)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS leases (
                scope TEXT NOT NULL, ip TEXT NOT NULL, owner TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE, expires REAL, PRIMARY KEY(scope, ip));
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL,
                status TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL, target TEXT NOT NULL,
                state TEXT NOT NULL, remote_task TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, event TEXT NOT NULL,
                subject TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_operations_target
                ON operations(target);
        ''')

    def close(self):
        self.db.close()

    @staticmethod
    def _verify_private_db(path):
        """Refuse to open a state DB reached through a symlink or unsafe target.

        On POSIX open with O_NOFOLLOW so the kernel rejects a pre-planted link,
        then validate on the opened descriptor that it is a single-link regular
        file owned by the current user. Loose group/other bits are tightened to
        0600 rather than fatal (an older install may carry a permissive umask);
        a symlink, non-regular file, foreign owner or extra hard link is refused.
        Non-POSIX keeps the historical connect path.
        """
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            return
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            fd = os.open(path, flags)
        except OSError:
            fail("state_db_unsafe", "状态库路径不可安全打开（拒绝符号链接或非常规文件）", 3)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                fail("state_db_unsafe", "状态库必须是普通文件，拒绝符号链接或特殊文件", 3)
            if info.st_uid != os.getuid():
                fail("state_db_unsafe", "状态库不属于当前用户，拒绝打开", 3)
            if info.st_nlink != 1:
                fail("state_db_unsafe", "状态库存在额外硬链接，拒绝打开", 3)
            if info.st_mode & 0o077:
                try:
                    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # tighten to 0600
                except OSError:
                    fail("state_db_unsafe", "状态库权限过宽且无法收紧为 0600", 3)
        finally:
            os.close(fd)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self, event, subject):
        self.db.execute("INSERT INTO audit(event,subject,created) VALUES(?,?,?)",
                        (event, subject, time.time()))

    def reserve(self, scope, ip, owner, minutes=None):
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            fail("ip_invalid", "IP 地址无效", 2)
        if not scope or not owner or (minutes is not None and minutes <= 0):
            fail("lease_invalid", "scope/owner 必填，租约时长须为正数", 2)
        token = uuid.uuid4().hex
        expires = time.time() + minutes * 60 if minutes else None
        with self.transaction():
            # Expiry does not prove a remotely deployed address is free.
            try:
                self.db.execute("INSERT INTO leases VALUES(?,?,?,?,?)", (scope, ip, owner, token, expires))
            except sqlite3.IntegrityError:
                fail("ip_reserved", "该作用域的地址已预留，过期记录也须核对后释放")
            self.audit("ip_reserved", token)
        return {"scope": scope, "ip": ip, "owner": owner, "lease_id": token, "expires": expires}

    def release(self, token):
        with self.transaction():
            changed = self.db.execute("DELETE FROM leases WHERE token=?", (token,)).rowcount
            if not changed:
                fail("lease_not_found", "指定租约不存在", 2)
            self.audit("ip_released", token)

    def leases(self, scope=None):
        rows = self.db.execute("SELECT * FROM leases WHERE (? IS NULL OR scope=?) ORDER BY scope,ip", (scope, scope))
        return [dict(row) for row in rows]

    def create_plan(self, steps, profile, description=""):
        if not profile or not isinstance(steps, list) or not steps:
            fail("plan_invalid", "计划须包含 profile 和非空步骤", 2)
        payload = canonical({"schema_version": 1, "profile": profile, "steps": steps, "description": description})
        digest = hashlib.sha256(payload.encode()).hexdigest()
        plan_id = uuid.uuid4().hex
        with self.transaction():
            self.db.execute("INSERT INTO plans VALUES(?,?,?,?,?)", (plan_id, payload, digest, "draft", time.time()))
            self.audit("plan_created", plan_id)
        return self.plan(plan_id)

    def plan(self, plan_id):
        row = self.db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            fail("plan_not_found", "指定计划不存在", 2)
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        return value

    def plans(self):
        return [self.plan(row[0]) for row in self.db.execute("SELECT id FROM plans ORDER BY created DESC")]

    def guest_run(self, run_id, profile):
        """Find the trusted binding for a guest run by its run_id.

        Scans plan payloads for a step whose fixed run id matches, restricted to
        the current profile. Returns (binding dict) or fails; never reconstructs
        a run from caller-supplied parameters.
        """
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            fail("invalid_arguments", "run_id 须为 32 位十六进制", 2)
        rows = self.db.execute("SELECT payload FROM plans ORDER BY created DESC").fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            if payload.get("profile") != profile:
                continue
            for step in payload.get("steps", []):
                binding = step.get("binding", {})
                run = binding.get("run")
                if run is not None and run.get("run_id") == run_id:
                    return {"command": step["command"], "binding": binding}
        fail("guest_run_not_found", "未找到属于当前 Profile 的该运行记录", 2)

    def prepare(self, request_id, target, parameters):
        if not request_id or not target:
            fail("operation_invalid", "请求和目标身份不能为空", 2)
        payload = canonical(parameters)
        with self.transaction():
            existing = self.db.execute("SELECT * FROM operations WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["payload"] != payload or existing["target"] != target:
                    fail("request_conflict", "同一请求 ID 不能更改目标或参数", 2)
                return dict(existing)
            operation_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO operations VALUES(?,?,?,?,?,NULL)",
                            (operation_id, request_id, payload, target, "prepared"))
            self.audit("operation_prepared", operation_id)
        return self.operation(operation_id)

    def operation(self, operation_id):
        row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            fail("operation_not_found", "操作不存在", 2)
        return dict(row)

    def claim(self, operation_id):
        with self.transaction():
            op = self.operation(operation_id)
            if op["state"] != "prepared":
                fail("reconciliation_required", "操作已提交或状态不明，必须先核对", 6)
            busy = self.db.execute("SELECT id FROM operations WHERE target=? AND state IN ('submitting','running','unknown','cancel_requested')",
                                   (op["target"],)).fetchone()
            if busy:
                fail("target_busy", "目标存在进行中或待核对的操作", 4)
            scope = parent_scope(op["payload"])
            if scope:
                # The same transaction covers lookup and claim. Profile and
                # mutable inventory MoID are intentionally not scope keys.
                active = self.db.execute("SELECT payload FROM operations WHERE state IN ('submitting','running','unknown','cancel_requested')")
                if any(parent_scope(row[0]) == scope for row in active):
                    fail("target_busy", "同一服务端/父 VM UUID 存在进行中或未知的克隆/清理操作", 4)
            self.db.execute("UPDATE operations SET state='submitting' WHERE id=?", (operation_id,))
            self.audit("operation_submitting", operation_id)

    def submitted(self, operation_id, remote_task):
        if not remote_task:
            fail("task_invalid", "远端任务标识不能为空", 2)
        with self.transaction():
            updated = self.db.execute("UPDATE operations SET state='running',remote_task=? WHERE id=? AND state='submitting'",
                                      (remote_task, operation_id)).rowcount
            if updated != 1:
                fail("transition_invalid", "只有已认领操作可以登记远端任务")
            self.audit("operation_running", operation_id)

    def mark_unknown(self, operation_id):
        """Retain task identity and target exclusion after lost observation."""
        with self.transaction():
            op = self.operation(operation_id)
            if op["state"] not in ("submitting", "running", "unknown", "cancel_requested"):
                fail("transition_invalid", "该操作不处于可标记未知的状态")
            self.db.execute("UPDATE operations SET state='unknown' WHERE id=?", (operation_id,))
            self.audit("operation_unknown", operation_id)

    def observe_task(self, operation_id, remote_task, task_state):
        """Internal provider boundary, never a user-supplied completion override.

        Caller must observe the task on the bound server. A missing task or a
        lost submission response cannot establish success, failure or cancellation.
        """
        states = {"queued": "running", "running": "running", "success": "succeeded", "error": "failed"}
        if task_state not in states:
            fail("task_state_invalid", "未知远端任务状态，不能推断执行结果", 2)
        with self.transaction():
            op = self.operation(operation_id)
            if not remote_task or op["remote_task"] != remote_task:
                fail("task_identity_mismatch", "远端任务身份未绑定或不匹配")
            if op["state"] not in ("running", "unknown"):
                fail("transition_invalid", "仅进行中或待核对操作可更新远端结果")
            state = states[task_state]
            self.db.execute("UPDATE operations SET state=? WHERE id=?", (state, operation_id))
            self.audit("operation_" + state, operation_id)
