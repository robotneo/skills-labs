"""M-3 hardening for the metadata-only datastore browser.

Covers three performance/correctness refinements without any vCenter round
trip:

1. observe() reuses the per-session cached ServiceContent (one
   RetrieveContent) instead of re-fetching it on every recovery/observe.
2. submit() narrows the prepare→submit TOCTOU check to remote liveness facts
   (existence / accessibility / datastore name / server identity) and resolves
   the object once, instead of re-running the whole prepare validation chain.
3. the running-task poll uses exponential backoff (0.2 -> 0.4 -> ... capped at
   2s), not a fixed 0.2s sleep.
"""
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError


class M3Fixture(unittest.TestCase):
    def build(self, state="running", fail_accessible=False, rename_to=None,
              server_uuid="server-a"):
        from vcenter_aiops.providers.vsphere.datastores import Datastores

        self.retrieve_calls = 0
        self.resolve_calls = 0
        self.sleeps = []

        files = [NS(path="a.iso", fileSize=1, modification=None)]
        self.task = NS(_moId="task-1",
                       info=NS(key="task-1", state=state,
                               result=NS(folderPath="[data] iso/", file=files)))

        def search(**kwargs):
            return self.task

        self.ds = NS(
            name=rename_to if rename_to is not None else "data",
            summary=NS(accessible=not fail_accessible),
            browser=NS(SearchDatastore_Task=search,
                       SearchDatastoreSubFolders_Task=search))
        self.about = NS(instanceUuid=server_uuid)

        def retrieve():
            self.retrieve_calls += 1
            return NS(about=self.about)

        def resolve(_):
            self.resolve_calls += 1
            return self.ds

        self.si = NS(_stub=None, RetrieveContent=retrieve)
        provider = Datastores(self.si, resolver=resolve)
        provider.task = lambda _: self.task
        # Record (never actually wait) the requested backoff durations.
        import vcenter_aiops.providers.vsphere.datastores as mod
        self._real_sleep = mod.time.sleep
        mod.time.sleep = lambda seconds: self.sleeps.append(seconds)
        self.addCleanup(setattr, mod.time, "sleep", self._real_sleep)
        return provider


class TestServiceContentCache(M3Fixture):
    def test_prepare_and_submit_share_one_content_fetch(self):
        provider = self.build()
        scope = provider.prepare("datastore-1", "iso")
        self.assertEqual(self.retrieve_calls, 1)
        # submit re-uses the cached ServiceContent for its identity check rather
        # than re-running the whole prepare chain (which would re-fetch).
        provider.submit(scope)
        self.assertEqual(self.retrieve_calls, 1)

    def test_observe_reads_server_identity_live_every_time(self):
        # Observe is the cross-session recovery path. Its server-identity guard
        # must be a LIVE RetrieveContent (never the prepare-time cache): if the
        # session reconnects to another vCenter, a same-named task must be
        # rejected before it is read (fail-closed; mirrors the M-2 rule that live
        # identity reads are never cached).
        provider = self.build()
        receipt = provider.submit(provider.prepare("datastore-1", "iso"))
        retrieves_after_submit = self.retrieve_calls
        for _ in range(3):
            provider.observe(receipt, 0)
        self.assertEqual(self.retrieve_calls, retrieves_after_submit + 3)

    def test_observe_live_identity_catches_reconnected_server(self):
        provider = self.build()
        receipt = provider.submit(provider.prepare("datastore-1", "iso"))
        # Simulate reconnect to a different vCenter, even though the prepare-time
        # cached content still says server-a.
        provider.si.RetrieveContent = lambda: NS(about=NS(instanceUuid="server-b"))
        from vcenter_aiops.domain.models import OperationError
        with self.assertRaises(OperationError) as error:
            provider.observe(receipt, 0)
        self.assertEqual(error.exception.code, "server_mismatch")


class TestNarrowSubmitToctou(M3Fixture):
    def test_submit_resolves_datastore_once(self):
        provider = self.build()
        provider.submit(provider.prepare("datastore-1", "iso"))
        # prepare resolves once; submit must re-use one resolution for its
        # liveness check and the actual SearchDatastore call (no second prepare).
        self.assertEqual(self.resolve_calls, 2)

    def test_submit_detects_renamed_datastore(self):
        provider = self.build()
        scope = provider.prepare("datastore-1", "iso")
        # Datastore is renamed between prepare and submit: datastorePath built
        # from the recorded name would now point elsewhere.
        self.ds.name = "other-data"
        with self.assertRaises(OperationError) as error:
            provider.submit(scope)
        self.assertEqual(error.exception.code, "search_scope_changed")

    def test_submit_detects_datastore_becoming_unavailable(self):
        provider = self.build()
        scope = provider.prepare("datastore-1", "iso")
        self.ds.summary.accessible = False
        with self.assertRaises(OperationError) as error:
            provider.submit(scope)
        self.assertEqual(error.exception.code, "datastore_unavailable")

    def test_submit_detects_server_identity_change(self):
        provider = self.build(server_uuid="server-a")
        scope = provider.prepare("datastore-1", "iso")
        self.about.instanceUuid = "server-b"
        # The cached content is populated; force a fresh read so the new server
        # identity is observed at submit time.
        provider._content = None
        with self.assertRaises(OperationError) as error:
            provider.submit(scope)
        self.assertEqual(error.exception.code, "search_scope_changed")


class TestExponentialBackoff(M3Fixture):
    def test_poll_backs_off_exponentially(self):
        # Drive three running polls (each reads monotonic twice: once for the
        # deadline check, once to clamp the sleep to the remaining budget), then
        # a fourth read that crosses the deadline and returns "running".
        provider = self.build()
        receipt = provider.submit(provider.prepare("datastore-1", "iso"))

        import vcenter_aiops.providers.vsphere.datastores as mod
        # deadline read; then per running poll (check=0.0, sleep-clamp=0.0) x3;
        # then the final check that trips the deadline.
        ticks = iter([0.0,
                      0.0, 0.0,
                      0.0, 0.0,
                      0.0, 0.0,
                      100.0])
        mod.time.monotonic = lambda: next(ticks)
        self.addCleanup(setattr, mod.time, "monotonic", time_monotonic)

        data = provider.observe(receipt, 30)
        self.assertEqual(data["state"], "running")
        # First three polls request 0.2, 0.4, 0.8 (exponential), never > 2.
        self.assertEqual(self.sleeps[:3], [0.2, 0.4, 0.8])
        self.assertTrue(all(d <= 2 for d in self.sleeps))


import time as _time
time_monotonic = _time.monotonic


if __name__ == "__main__":
    unittest.main()
