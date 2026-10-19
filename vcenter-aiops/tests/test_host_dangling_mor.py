"""H-1 / L-5 hardening for host maintenance.

H-1 preflight: a well-formed but dangling host MoRef (host-999999) must surface
     as a structured host_not_found failure (exit 4), not a top-level
     internal_error (exit 5). A ManagedObjectNotFound naming a *different* object
     must still propagate.
L-5 post-write: a dangling task/host during observe/cancel is expired evidence ->
     unknown (exit 6) requiring reconciliation, never a deterministic not_found.
     verify() must treat expired evidence as unconfirmed (False), never raise.
"""
import unittest

from pyVmomi import vim, vmodl

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.hosts import Hosts
from test_host_maintenance import HostFixture, params as host_params


def _missing(mo_id):
    return vmodl.fault.ManagedObjectNotFound(obj=vim.HostSystem(mo_id, None))


class _FaultTask:
    """A task ref whose first evidence read raises ManagedObjectNotFound."""

    def __init__(self, mo_id="host-1"):
        self._missing_mo_id = mo_id

    @property
    def info(self):
        raise _missing(self._missing_mo_id)


class DanglingHostPreflightTests(unittest.TestCase):
    def _provider_with_dangling_host(self, fault):
        fixture = HostFixture()

        def resolve(kind, object_id):
            if kind == "host":
                if object_id == "host-999999":
                    raise fault
                return fixture.host
            if kind == "task":
                return fixture.task
            raise AssertionError((kind, object_id))

        return Hosts(fixture.si, resolver=resolve)

    def test_h1_dangling_host_preflight_is_structured_not_found(self):
        provider = self._provider_with_dangling_host(_missing("host-999999"))
        with self.assertRaises(OperationError) as error:
            provider.preflight("host maintenance-enter", host_params(host_id="host-999999"))
        self.assertEqual(error.exception.code, "host_not_found")
        self.assertEqual(error.exception.exit_code, 4)
        self.assertIn("host-999999", str(error.exception))

    def test_h1_malformed_host_id_stays_argument_error(self):
        # A non host-N id is rejected before any resolution (exit 2), proving the
        # not_found normalisation only applies to well-formed dangling refs.
        provider = self._provider_with_dangling_host(_missing("host-999999"))
        with self.assertRaises(OperationError) as error:
            provider.preflight("host maintenance-enter", host_params(host_id="not-a-host"))
        self.assertEqual(error.exception.code, "target_invalid")
        self.assertEqual(error.exception.exit_code, 2)

    def test_h1_unrelated_managed_object_fault_is_not_swallowed(self):
        # A fault naming a different object must propagate rather than be rewritten
        # as host_not_found, preserving fail-closed exact-object matching.
        provider = self._provider_with_dangling_host(_missing("host-777"))
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider.preflight("host maintenance-enter", host_params(host_id="host-999999"))


class PostWriteExpiredEvidenceTests(unittest.TestCase):
    def _committed(self):
        fixture = HostFixture(maintenance=False)
        provider = fixture.provider()
        command = "host maintenance-enter"
        binding = provider.preflight(command, host_params(allow_drs_migration=False))
        # No powered-on VMs in this fixture -> enter proceeds without DRS grant.
        receipt = provider.submit(command, host_params(), binding)
        return fixture, provider, command, binding, receipt

    def test_l5_observe_dangling_task_is_unknown_not_internal_error(self):
        fixture, provider, command, binding, receipt = self._committed()

        def resolve(kind, object_id):
            if kind == "task" and object_id == "task-1":
                return _FaultTask("host-1")
            if kind == "host":
                return fixture.host
            raise AssertionError((kind, object_id))

        expired = Hosts(fixture.si, resolver=resolve)
        with self.assertRaises(OperationError) as error:
            expired.observe(receipt, binding)
        self.assertEqual(error.exception.code, "task_state_unknown")
        self.assertEqual(error.exception.exit_code, 6)

    def test_l5_cancel_dangling_task_is_unknown(self):
        fixture, provider, command, binding, receipt = self._committed()

        def resolve(kind, object_id):
            if kind == "task" and object_id == "task-1":
                return _FaultTask("host-1")
            if kind == "host":
                return fixture.host
            raise AssertionError((kind, object_id))

        expired = Hosts(fixture.si, resolver=resolve)
        with self.assertRaises(OperationError) as error:
            expired.cancel(receipt, binding)
        self.assertEqual(error.exception.code, "task_state_unknown")
        self.assertEqual(error.exception.exit_code, 6)

    def test_l5_verify_dangling_host_is_unconfirmed_not_raised(self):
        fixture, _, command, binding, receipt = self._committed()

        def resolve(kind, object_id):
            if kind == "host":
                # Same-id dangling ref normalises to host_not_found inside
                # _existing_host; verify must still return False (unconfirmed).
                raise _missing("host-1")
            if kind == "task":
                return fixture.task
            raise AssertionError((kind, object_id))

        expired = Hosts(fixture.si, resolver=resolve)
        self.assertFalse(expired.verify(command, host_params(), binding, {}))

    def test_l5_verify_unrelated_fault_is_unconfirmed_not_raised(self):
        fixture, _, command, binding, receipt = self._committed()

        def resolve(kind, object_id):
            if kind == "host":
                raise _missing("host-777")  # different object -> raw MONF
            if kind == "task":
                return fixture.task
            raise AssertionError((kind, object_id))

        expired = Hosts(fixture.si, resolver=resolve)
        self.assertFalse(expired.verify(command, host_params(), binding, {}))


if __name__ == "__main__":
    unittest.main()
