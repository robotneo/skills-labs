"""M-3: cache refresh must keep the previous snapshot only for *expected*
external/storage faults, and let local programming faults (TypeError/KeyError/
...) propagate so the CLI catch-all maps them to internal_error/exit5 instead
of masking them as a business ``cache_refresh_failed``.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


PROFILE_CONFIG = {"host": "vcenter.test", "port": 443, "user": "admin",
                  "password_ref": "env:OFFLINE", "verify_tls": True}
ROWS = [{"id": "vm-1", "kind": "vm", "name": "one"}]


class CacheRefreshFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.db"

    def context(self):
        owner = self

        class Context:
            profile = "lab"
            profiles = NS(get=lambda name: PROFILE_CONFIG)

            @contextmanager
            def store(self):
                store = Store(owner.path)
                try:
                    yield store
                finally:
                    store.close()

            @contextmanager
            def session(self):
                about = NS(instanceUuid="server-a", apiVersion="8.0", version="8.0",
                           build="1", apiType="VirtualCenter")
                yield NS(RetrieveContent=lambda: NS(about=about))

        return Context()

    def invoke(self, ctx, **params):
        spec = lookup("cache refresh")
        return spec.handler()(ctx, spec.validate(params))

    def refresh_with_list_raising(self, ctx, exc):
        class BrokenInventory:
            def __init__(self, si):
                pass

            def list(self, kind, limit):
                raise exc

        with patch("vcenter_aiops.application.commands.cache.Inventory", BrokenInventory):
            return self.invoke(ctx, kind="vm")

    def seed_snapshot(self, ctx):
        class Reader:
            def __init__(self, si):
                pass

            def list(self, kind, limit):
                return {"items": ROWS, "truncated": False}

        with patch("vcenter_aiops.application.commands.cache.Inventory", Reader):
            return self.invoke(ctx, kind="vm")

    # -- local programming faults must NOT be swallowed as business failures --

    def test_local_typeerror_propagates(self):
        with self.assertRaises(TypeError):
            self.refresh_with_list_raising(self.context(), TypeError("local bug"))

    def test_local_keyerror_propagates(self):
        with self.assertRaises(KeyError):
            self.refresh_with_list_raising(self.context(), KeyError("missing-key"))

    def test_local_attribute_error_propagates(self):
        with self.assertRaises(AttributeError):
            self.refresh_with_list_raising(self.context(), AttributeError("bad attr"))

    # -- expected external/storage faults keep the previous snapshot ----------

    def _assert_previous_retained(self, result):
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "cache_refresh_failed")
        self.assertFalse(result.error["retryable"])
        self.assertEqual(result.data["previous"]["snapshots"][0]["count"], 1)

    def test_os_error_keeps_previous_snapshot(self):
        ctx = self.context()
        self.seed_snapshot(ctx)
        result = self.refresh_with_list_raising(ctx, OSError("network reset"))
        self._assert_previous_retained(result)

    def test_remote_method_fault_keeps_previous_snapshot(self):
        from pyVmomi import vmodl
        ctx = self.context()
        self.seed_snapshot(ctx)
        result = self.refresh_with_list_raising(ctx, vmodl.MethodFault())
        self._assert_previous_retained(result)

    def test_sqlite_error_keeps_previous_snapshot(self):
        ctx = self.context()
        self.seed_snapshot(ctx)

        class Reader:
            def __init__(self, si):
                pass

            def list(self, kind, limit):
                return {"items": ROWS, "truncated": False}

        with patch("vcenter_aiops.application.commands.cache.Inventory", Reader), \
                patch("vcenter_aiops.application.commands.cache.CacheStore.publish",
                      side_effect=sqlite3.OperationalError("disk I/O error")):
            result = self.invoke(ctx, kind="vm")
        self._assert_previous_retained(result)

    # -- OperationError branch still carries its structured code --------------

    def test_operation_error_keeps_structured_code(self):
        ctx = self.context()
        self.seed_snapshot(ctx)
        result = self.refresh_with_list_raising(ctx, OperationError("query_failed", "查询失败", 4))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "query_failed")
        self.assertEqual(result.data["previous"]["snapshots"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
