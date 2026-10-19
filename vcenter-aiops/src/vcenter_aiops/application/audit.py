"""Local evidence views without payloads, credentials or raw subject identifiers."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

from ..domain.models import fail


class AuditLog:
    def __init__(self, store):
        self.store = store
        store.db.execute("CREATE TABLE IF NOT EXISTS audit_metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        with store.transaction():
            store.db.execute("INSERT OR IGNORE INTO audit_metadata VALUES('pseudonym_key',?)", (secrets.token_hex(32),))
            self.key = bytes.fromhex(store.db.execute("SELECT value FROM audit_metadata WHERE name='pseudonym_key'").fetchone()[0])

    def list(self, after_id=0, limit=100, snapshot_max_id=None):
        if type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 10000:
            fail("audit_query_invalid", "游标须非负，数量须为 1–10000", 2)
        maximum = self.store.db.execute("SELECT COALESCE(MAX(id),0) FROM audit").fetchone()[0]
        if snapshot_max_id is not None:
            if type(snapshot_max_id) is not int or snapshot_max_id < 0:
                fail("audit_query_invalid", "快照上界须为非负整数", 2)
            maximum = min(maximum, snapshot_max_id)
        rows = list(self.store.db.execute("SELECT id,event,subject,created FROM audit WHERE id>? AND id<=? ORDER BY id LIMIT ?", (after_id, maximum, limit + 1)))
        items = [{"id": row["id"], "event": row["event"], "created": row["created"],
                  "subject_ref": hmac.new(self.key, row["subject"].encode(), hashlib.sha256).hexdigest()} for row in rows[:limit]]
        return {"scope": "all_local_profiles", "items": items, "truncated": len(rows) > limit, "next_cursor": items[-1]["id"] if items else after_id,
                "snapshot_max_id": maximum, "redaction": "subject_hmac_sha256; no operation payloads",
                "collected_at": datetime.now(timezone.utc).isoformat(), "untrusted_content": True}

    def export(self, path, after_id=0, limit=10000, snapshot_max_id=None):
        payload = self.list(after_id, limit, snapshot_max_id)
        target = Path(path).absolute()
        encoded = (json.dumps({"schema_version": "1", **payload}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        # Publish only to a name that does not yet exist. If the name is present
        # it must not be a symlink or special file: never publish through a link
        # (which could redirect the export outside the intended directory). lstat
        # does not follow the terminal component, so a planted link is seen as-is.
        try:
            preexisting = target.lstat()
        except FileNotFoundError:
            preexisting = None
        except OSError:
            fail("export_failed", "无法安全检查导出目标；请检查目录权限", 5)
        if preexisting is not None and (stat.S_ISLNK(preexisting.st_mode) or not stat.S_ISREG(preexisting.st_mode)):
            fail("export_target_unsafe", "导出目标是符号链接或非常规文件，拒绝写入", 3)
        temporary = None
        warnings = []
        try:
            # Publish by an exclusive hard link: no overwrite race or symlink following.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".audit-export-", delete=False) as handle:
                temporary = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, target)
        except FileExistsError:
            fail("export_exists", "导出目标已存在，禁止覆盖；请指定新文件名", 2)
        except OSError:
            fail("export_failed", "无法安全写入导出文件；请检查目录权限与文件系统支持", 5)
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    warnings.append("导出临时文件清理失败，请检查目标目录中的 .audit-export- 文件")
        digest = hashlib.sha256(encoded).hexdigest()
        audit_recorded = False
        try:
            self.store.audit("audit_exported", digest)
            audit_recorded = True
        except Exception:
            warnings.append("文件已导出，但审计记录写入失败；请保留文件和校验值，不要在原路径重复导出")
        return {"status": "partial" if warnings else "succeeded", "audit_recorded": audit_recorded, "warnings": warnings,
                "path": str(target), "sha256": digest, "count": len(payload["items"]),
                "truncated": payload["truncated"], "next_cursor": payload["next_cursor"], "snapshot_max_id": payload["snapshot_max_id"]}
