"""M-2: guest observe avoids repeated privilege SOAP while staying fail-closed.

During a long guest wait, observe() is called every ~2s. The HasPrivilegeOnEntity
grant for one fixed run must be proven once (keyed by run_id + bound identity +
digest), while the live ListFilesInGuest call still happens every poll and the
live VM/vCenter identity checks still run every tick. The Execute grant, submit,
recover and transfer paths never use the cache. Also verifies wrapper-source
caching never changes the anti-tamper digest.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from test_guest_processes import Fixture, options, SECRET


class GuestObservePrivilegeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name,
                                      "TEST_GUEST_PASSWORD": SECRET}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.fixture = Fixture()

    def _counting_provider(self):
        provider = self.fixture.provider()
        privilege_calls = []
        manager = self.fixture.content.authorizationManager
        original = manager.HasPrivilegeOnEntity

        def counting(**kwargs):
            privilege_calls.append(tuple(kwargs["privId"]))
            return original(**kwargs)

        manager.HasPrivilegeOnEntity = counting
        return provider, privilege_calls

    def _listfiles_calls(self):
        return [name for name, _ in self.fixture.stub.calls if name == "ListFilesInGuest"]

    def test_privilege_soap_once_per_run_but_listfiles_every_poll(self):
        provider, privilege_calls = self._counting_provider()
        binding = provider.preflight("vm guest-exec", options())
        receipt = provider.submit("vm guest-exec", options(), binding)
        privilege_calls.clear()  # preflight+submit execute grants excluded

        # First two polls: claimed marker only -> still running; third: done(0).
        self.fixture.stub.markers(binding, None)
        provider.observe(receipt, binding)
        provider.observe(receipt, binding)
        self.fixture.stub.markers(binding, 0)
        final = provider.observe(receipt, binding)

        # One Query-only privilege proof across all observe polls (execute grant
        # is never cached), but ListFilesInGuest stays live on every poll.
        self.assertEqual(privilege_calls, [("VirtualMachine.GuestOperations.Query",)])
        self.assertEqual(len(self._listfiles_calls()), 3)
        self.assertEqual(final["state"], "success")

    def test_cached_grant_not_reused_across_runs_or_identity(self):
        provider, privilege_calls = self._counting_provider()
        binding_one = provider.preflight("vm guest-exec", options())
        receipt_one = provider.submit("vm guest-exec", options(), binding_one)
        self.fixture.stub.markers(binding_one, 0)
        provider.observe(receipt_one, binding_one)

        # A second, distinct run (fresh preflight -> new run_id) must prove its
        # own privilege; the cache key includes run_id/identity/digest.
        binding_two = provider.preflight("vm guest-exec", options())
        receipt_two = provider.submit("vm guest-exec", options(), binding_two)
        self.fixture.stub.markers(binding_two, 0)
        provider.observe(receipt_two, binding_two)

        # One Query grant observed per run, i.e. two distinct cached proofs.
        observed_query = privilege_calls.count(("VirtualMachine.GuestOperations.Query",))
        self.assertEqual(observed_query, 2)

    def test_live_identity_change_still_detected_despite_cache(self):
        provider, privilege_calls = self._counting_provider()
        binding = provider.preflight("vm guest-exec", options())
        receipt = provider.submit("vm guest-exec", options(), binding)
        self.fixture.stub.markers(binding, 0)
        self.assertEqual(provider.observe(receipt, binding)["state"], "success")

        # Privilege proof is cached, but live identity is re-read every tick:
        # replacing the VM UUID must still turn the observation unknown.
        self.fixture.vm.config.instanceUuid = "replacement"
        self.assertEqual(provider.observe(receipt, binding)["state"], "unknown")


class WrapperSourceCacheDigestTests(unittest.TestCase):
    def test_cached_wrapper_source_preserves_digest(self):
        from vcenter_aiops.providers.vsphere import guest_protocol as gp

        identity = {"server_uuid": "vc-uuid", "object_id": "vm-1", "instance_uuid": "vm-uuid"}
        params = options()
        first = gp.build_run(identity, params, "a" * 32)
        second = gp.build_run(identity, params, "b" * 32)
        # The packaged wrapper prefix (which embeds the anti-tamper wrapper hash
        # into the payload) is identical across runs even though the source is
        # module-cached after the first read; per-run payload/digest still differ.
        wrapper_prefix = first["source"].rsplit("\nimport base64, json", 1)[0]
        self.assertEqual(wrapper_prefix, second["source"].rsplit("\nimport base64, json", 1)[0])
        self.assertNotEqual(first["digest"], second["digest"])
        # The bound digest is a real 256-bit hex covering wrapper + payload, so
        # first-execution anti-tamper verification remains in effect.
        self.assertRegex(first["digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(second["digest"], r"^[0-9a-f]{64}$")

    def test_wrapper_cache_invalidates_on_mtime_size_change(self):
        from vcenter_aiops.providers.vsphere import guest_protocol as gp

        class FakeStat:
            st_mtime_ns = 111
            st_size = 222

        class FakePath:
            def __init__(self, text, stat_result):
                self._text = text
                self._stat = stat_result
            def stat(self):
                return self._stat
            def read_text(self, encoding=None):
                return self._text

        real_path = gp.Path
        try:
            gp.Path = lambda p: FakePath("SOURCE-A", FakeStat())
            gp._WRAPPER_CACHE.clear()
            self.assertEqual(gp._wrapper_source(), "SOURCE-A")
            # Same key -> served from cache without re-reading.
            self.assertEqual(gp._wrapper_source(), "SOURCE-A")
            # mtime/size change -> cache invalidates and new content is read.
            class FakeStat2:
                st_mtime_ns = 333
                st_size = 444
            gp.Path = lambda p: FakePath("SOURCE-B", FakeStat2())
            self.assertEqual(gp._wrapper_source(), "SOURCE-B")
        finally:
            gp.Path = real_path
            gp._WRAPPER_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
