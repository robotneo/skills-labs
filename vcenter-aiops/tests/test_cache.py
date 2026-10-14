"""Explicit inventory cache behavior with a real temporary SQLite Store."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.application.registry import COMMANDS, lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.db"
        self.profile_config = {"host": "vcenter.test", "port": 443, "user": "admin",
                               "password_ref": "env:OFFLINE", "verify_tls": True}
        self.calls = []
        self.rows = [{"id": "vm-1", "kind": "vm", "name": "one", "unavailable": []}]

    def context(self, profile="lab", server="server-a"):
        owner = self

        class Context:
            profiles = NS(get=lambda name: owner.profile_config)

            def __init__(self):
                self.profile = profile

            @contextmanager
            def store(self):
                store = Store(owner.path)
                try:
                    yield store
                finally:
                    store.close()

            @contextmanager
            def session(self):
                owner.calls.append(("session", profile))
                about = NS(instanceUuid=server, apiVersion="8.0", version="8.0",
                           build="1", apiType="VirtualCenter")
                yield NS(RetrieveContent=lambda: NS(about=about))

        return Context()

    def invoke(self, command, ctx, **params):
        spec = lookup(command)
        return spec.handler()(ctx, spec.validate(params))

    @contextmanager
    def store(self):
        store = Store(self.path)
        try:
            yield store
        finally:
            store.close()

    def refresh(self, ctx, *, truncated=False):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.commands.cache"),
                             "cache command module is missing")
        class Reader:
            def __init__(reader, si):
                pass

            def list(reader, kind, limit):
                self.calls.append(("list", kind, limit))
                return {"items": self.rows, "truncated": truncated}

        with patch("vcenter_aiops.application.commands.cache.Inventory", Reader):
            return self.invoke("cache refresh", ctx, kind="vm")

    def test_commands_expose_explicit_scopes(self):
        for command, category in (("cache status", "local_read"),
                                  ("cache refresh", "remote_read"),
                                  ("cache invalidate", "local_write")):
            with self.subTest(command=command):
                self.assertIn(command, [spec.path for spec in COMMANDS])
                self.assertEqual(lookup(command).category, category)
                self.assertEqual(lookup(command).validate({"kind": "vm"})["kind"], "vm")
                with self.assertRaises(OperationError):
                    lookup(command).validate({"kind": "../../state.db"})

    def test_refresh_publishes_bounded_snapshot_and_status_never_connects(self):
        ctx = self.context()
        refreshed = self.refresh(ctx)
        self.assertEqual(refreshed.status, "succeeded")
        self.assertEqual(refreshed.data["count"], 1)
        self.assertEqual(refreshed.data["instance_uuid"], "server-a")
        self.assertIn("committed", refreshed.data)
        self.assertTrue(refreshed.data["committed"])
        self.assertTrue(refreshed.data["current_at_check"])
        self.assertIn("checked_at", refreshed.data)
        self.assertEqual(self.calls, [("session", "lab"), ("list", "vm", 1000)])
        self.calls.clear()
        status = self.invoke("cache status", ctx, kind="vm")
        self.assertEqual(self.calls, [])
        self.assertEqual(len(status.data["snapshots"]), 1)
        snapshot = status.data["snapshots"][0]
        self.assertEqual(snapshot["source"], "live_inventory")
        self.assertEqual(snapshot["count"], 1)
        self.assertTrue(snapshot["age_fresh"])
        self.assertTrue(snapshot["current_server_unverified"])

    def test_profile_and_server_snapshots_are_isolated(self):
        self.refresh(self.context("lab", "server-a"))
        self.refresh(self.context("lab", "server-b"))
        self.refresh(self.context("other", "server-a"))
        lab = self.invoke("cache status", self.context("lab"), kind="vm").data["snapshots"]
        other = self.invoke("cache status", self.context("other"), kind="vm").data["snapshots"]
        self.assertEqual({s["instance_uuid"] for s in lab}, {"server-a", "server-b"})
        self.assertEqual([s["instance_uuid"] for s in other], ["server-a"])

    def test_invalidate_removes_only_profile_kind_and_blocks_inflight_publish(self):
        from vcenter_aiops.infrastructure.cache import CacheStore
        self.refresh(self.context("lab", "server-a"))
        self.refresh(self.context("other", "server-a"))
        with self.store() as store:
            cache = CacheStore(store)
            old_generation = cache.begin("lab", "vm")
        removed = self.invoke("cache invalidate", self.context("lab"), kind="vm")
        self.assertEqual(removed.data["removed"], 1)
        with self.store() as store:
            cache = CacheStore(store)
            self.assertFalse(cache.publish("lab", "server-a", "vm", old_generation,
                                           self.profile_config, {"items": self.rows, "truncated": False}))
        self.assertEqual(self.invoke("cache status", self.context("lab"), kind="vm").data["snapshots"], [])
        self.assertEqual(len(self.invoke("cache status", self.context("other"), kind="vm").data["snapshots"]), 1)

    def test_missing_status_is_explicit(self):
        data = self.invoke("cache status", self.context(), kind="vm").data
        self.assertIn("state", data)
        self.assertEqual(data["state"], "missing")
        self.assertFalse(data["present"])

    def test_refresh_failure_reports_attempt_and_old_collection_time(self):
        ctx = self.context()
        first = self.refresh(ctx)
        old_time = first.data["collected_at"]

        class BrokenInventory:
            def __init__(self, si):
                pass

            def list(self, kind, limit):
                raise OperationError("query_failed", "查询失败", 4)

        with patch("vcenter_aiops.application.commands.cache.Inventory", BrokenInventory):
            failed = self.invoke("cache refresh", ctx, kind="vm")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error["code"], "query_failed")
        self.assertIn("attempted_at", failed.data)
        self.assertGreaterEqual(failed.data["attempted_at"], old_time)
        self.assertEqual(failed.data["previous"]["snapshots"][0]["collected_at"], old_time)

    def test_status_rejects_corrupt_and_unsupported_payload(self):
        self.refresh(self.context())
        with self.store() as store:
            store.db.execute("UPDATE inventory_cache SET payload=? WHERE profile='lab'", ("not-json",))
        corrupt = self.invoke("cache status", self.context(), kind="vm").data["snapshots"][0]
        self.assertEqual(corrupt["state"], "corrupt")
        self.assertNotIn("count", corrupt)
        with self.store() as store:
            store.db.execute("UPDATE inventory_cache SET payload=? WHERE profile='lab'",
                             (json.dumps({"schema_version": 99, "data": {"items": [], "truncated": False}}),))
        unsupported = self.invoke("cache status", self.context(), kind="vm").data["snapshots"][0]
        self.assertEqual(unsupported["state"], "corrupt")

    def test_status_marks_expiry_and_truncated_without_claiming_completeness(self):
        self.refresh(self.context(), truncated=True)
        partial = self.invoke("cache status", self.context(), kind="vm").data["snapshots"][0]
        self.assertEqual(partial["state"], "partial")
        self.assertTrue(partial["truncated"])
        with self.store() as store:
            row = store.db.execute("SELECT payload FROM inventory_cache WHERE profile='lab'").fetchone()
            payload = json.loads(row["payload"])
            payload["collected_at"] = 1
            store.db.execute("UPDATE inventory_cache SET payload=? WHERE profile='lab'", (json.dumps(payload),))
        expired = self.invoke("cache status", self.context(), kind="vm").data["snapshots"][0]
        self.assertEqual(expired["state"], "expired")
        self.assertFalse(expired["age_fresh"])

    def test_oversized_or_nonprimitive_refresh_keeps_previous_snapshot(self):
        ctx = self.context()
        original = self.refresh(ctx).data["collected_at"]
        for bad_row in ({"id": "vm-2", "kind": "vm", "name": "x" * 1_000_000},
                        {"id": "vm-2", "kind": "vm", "sdk": object()}):
            with self.subTest(bad_row=type(bad_row.get("sdk"))):
                self.rows = [bad_row]
                failed = self.refresh(ctx)
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.data["previous"]["snapshots"][0]["collected_at"], original)

    def test_later_started_refresh_wins_even_when_older_finishes_last(self):
        from vcenter_aiops.infrastructure.cache import CacheStore
        with self.store() as store:
            cache = CacheStore(store)
            older = cache.begin("lab", "vm")
            newer = cache.begin("lab", "vm")
            self.assertTrue(cache.publish("lab", "server-a", "vm", newer, self.profile_config,
                                          {"items": self.rows, "truncated": False}, collected_at=200))
            self.assertFalse(cache.publish("lab", "server-a", "vm", older, self.profile_config,
                                           {"items": [], "truncated": False}, collected_at=300))
            payload = store.db.execute("SELECT payload FROM inventory_cache WHERE profile='lab'").fetchone()[0]
            self.assertEqual(json.loads(payload)["collected_at"], 200)

    def test_changed_profile_cannot_claim_old_snapshot_matches(self):
        self.refresh(self.context())
        self.profile_config = {**self.profile_config, "host": "new-vcenter.test"}
        snapshot = self.invoke("cache status", self.context(), kind="vm").data["snapshots"][0]
        self.assertEqual(snapshot["state"], "profile_changed")
        self.assertFalse(snapshot["profile_matches"])

    def test_invalidate_after_commit_cannot_be_reported_as_current_cache(self):
        from vcenter_aiops.infrastructure.cache import CacheStore
        original = CacheStore.publish

        def publish_then_invalidate(cache, *args, **kwargs):
            published = original(cache, *args, **kwargs)
            with self.store() as store:
                CacheStore(store).invalidate("lab", "vm")
            return published

        with patch.object(CacheStore, "publish", publish_then_invalidate):
            result = self.refresh(self.context())
        self.assertEqual(result.status, "partial")
        self.assertFalse(result.data["published"])
        self.assertIn("committed", result.data)
        self.assertTrue(result.data["committed"])
        self.assertFalse(result.data["current_at_check"])
        self.assertEqual(result.data["previous"]["state"], "missing")

    def test_newer_publication_after_commit_cannot_replace_response_metadata(self):
        from vcenter_aiops.infrastructure.cache import CacheStore
        original = CacheStore.publish

        def publish_then_newer(cache, *args, **kwargs):
            published = original(cache, *args, **kwargs)
            with self.store() as store:
                newer_cache = CacheStore(store)
                generation = newer_cache.begin("lab", "vm")
                original(newer_cache, "lab", "server-a", "vm", generation, self.profile_config,
                         {"items": [{"id": "vm-new", "kind": "vm"}], "truncated": False})
            return published

        with patch.object(CacheStore, "publish", publish_then_newer):
            result = self.refresh(self.context())
        self.assertEqual(result.status, "partial")
        self.assertFalse(result.data["published"])
        self.assertIn("committed", result.data)
        self.assertTrue(result.data["committed"])
        self.assertFalse(result.data["current_at_check"])
        self.assertEqual(result.data["previous"]["snapshots"][0]["count"], 1)
        with self.store() as store:
            payload = store.db.execute("SELECT payload FROM inventory_cache WHERE profile='lab'").fetchone()[0]
        self.assertEqual(json.loads(payload)["data"]["items"][0]["id"], "vm-new")


if __name__ == "__main__":
    unittest.main()
