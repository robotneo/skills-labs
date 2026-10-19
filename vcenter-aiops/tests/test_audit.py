import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.application.context import Context
from vcenter_aiops.cli.main import main
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        for event, subject in (("operation_prepared", "user@example.com"), ("operation_running", "user@example.com"), ("operation_succeeded", "secret-password")):
            self.store.audit(event, subject)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def log(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.audit"), "audit interface missing")
        from vcenter_aiops.application.audit import AuditLog
        return AuditLog(self.store)

    def test_cursor_pages_are_bounded_and_subjects_are_pseudonymized(self):
        first = self.log().list(limit=2)
        self.assertEqual([r["id"] for r in first["items"]], [1, 2])
        self.assertTrue(first["truncated"])
        second = self.log().list(after_id=first["next_cursor"], limit=2)
        self.assertEqual([r["id"] for r in second["items"]], [3])
        self.assertFalse(second["truncated"])
        self.assertEqual(first["items"][0]["subject_ref"], first["items"][1]["subject_ref"])
        self.assertNotIn("user@example.com", json.dumps(first))
        self.assertNotIn("secret-password", json.dumps(second))

    def test_export_refuses_existing_files_and_symlinks(self):
        log = self.log()
        target = Path(self.temp.name) / "report.json"
        target.write_text("original")
        with self.assertRaises(OperationError):
            log.export(target)
        self.assertEqual(target.read_text(), "original")
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(target)
        with self.assertRaises(OperationError):
            log.export(link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), "original")

    def test_export_records_bounds_and_does_not_include_itself(self):
        target = Path(self.temp.name) / "export.json"
        result = self.log().export(target, limit=2)
        payload = json.loads(target.read_text())
        self.assertEqual(len(payload["items"]), 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["snapshot_max_id"], 3)
        self.assertEqual(result["count"], 2)
        self.assertNotIn("user@example.com", target.read_text())
        self.assertNotIn("secret-password", target.read_text())
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_cli_audit_queries_never_connect(self):
        self.log()
        with patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name}), patch.object(Context, "session", side_effect=AssertionError("audit connected")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["audit", "list", "--limit", "1"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(len(payload["data"]["items"]), 1)
        self.assertTrue(payload["data"]["truncated"])

    def test_snapshot_cursor_excludes_events_created_after_first_page(self):
        log = self.log()
        first = log.list(limit=2)
        self.store.audit("operation_running", "new-subject")
        second = log.list(after_id=first["next_cursor"], limit=2, snapshot_max_id=first["snapshot_max_id"])
        self.assertEqual([r["id"] for r in second["items"]], [3])

    def test_profile_filter_is_not_silently_ignored(self):
        with patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--profile", "lab", "audit", "list"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "audit_scope_unsupported")

    def test_published_export_survives_audit_record_failure_with_partial_result(self):
        import sqlite3
        target = Path(self.temp.name) / "published.json"
        log = self.log()
        with patch.object(self.store, "audit", side_effect=sqlite3.OperationalError("private database detail")):
            result = log.export(target)
        self.assertTrue(target.exists())
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["audit_recorded"])
        self.assertEqual(result["path"], str(target))
        self.assertNotIn("private database detail", json.dumps(result))

    def test_temporary_cleanup_failure_does_not_hide_published_export(self):
        target = Path(self.temp.name) / "published.json"
        log = self.log()
        with patch("vcenter_aiops.application.audit.os.unlink", side_effect=OSError("cleanup failed")):
            result = log.export(target)
        self.assertTrue(target.exists())
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["warnings"])

    def test_cli_export_reports_partial_file_publication(self):
        target = Path(self.temp.name) / "cli.json"
        with patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name}), patch.object(Store, "audit", side_effect=OSError("write failed")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--yes", "audit", "export", "--file", str(target)])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 5)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["data"]["path"], str(target))
        self.assertTrue(target.exists())
