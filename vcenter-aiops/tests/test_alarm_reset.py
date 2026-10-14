"""Offline coverage for the bulk ``alarm reset`` command (ClearTriggeredAlarms).

Only the SOAP transport is faked; real pyVmomi DTOs (AlarmFilterSpec, Status
enum), the confirmed-execution engine and the Alarms reader are production code.
The API can only filter by managed-object TYPE (VM/Host) + status and cannot
target a precise entity/alarm, so the tests assert that bulk, filter-only shape.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.providers.vsphere.alarms import Alarms
from vcenter_aiops.providers.vsphere.mutations import Mutations


class ResetHarness:
    def __init__(self, states, api_version="8.0.3"):
        self.specs = []
        self.cleared = []
        self._states = states
        root = vim.Folder("group-d1")

        def retrieve(specSet, options):
            self.specs.extend(specSet)
            return NS(token=None,
                      objects=[NS(obj=root, propSet=[NS(name="triggeredAlarmState", val=states)], missingSet=[])])

        self.content = NS(
            about=NS(instanceUuid="server-a", apiType="VirtualCenter", apiVersion=api_version),
            rootFolder=root,
            propertyCollector=NS(RetrievePropertiesEx=retrieve),
            alarmManager=NS(ClearTriggeredAlarms=lambda filter: self._clear(filter)))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=None)

    def _clear(self, filter_spec):
        # Mirror the server: drop every alarm matching the requested filter.
        token = filter_spec.typeEntity
        prefix = {"entityTypeVm": "vm-", "entityTypeHost": "host-"}[token]
        statuses = {str(s) for s in filter_spec.status}
        kept = [s for s in self.states
                if not (s.entity._moId.startswith(prefix) and str(s.overallStatus) in statuses)]
        self.cleared.append((token, sorted(statuses), len(self.states) - len(kept)))
        self.states[:] = kept

    @property
    def states(self):
        return self._states

    def reader(self):
        return Alarms(self.si)

    def mutations(self):
        return Mutations(self.si)


def state(key, entity, status="red", acknowledged=None):
    return NS(key=key, alarm=NS(_moId="alarm-" + key), entity=NS(_moId=entity),
              overallStatus=status, time=None, acknowledged=acknowledged,
              acknowledgedByUser=None, acknowledgedTime=None)


class AlarmResetTests(unittest.TestCase):
    def harness(self, *states, api_version="8.0.3"):
        h = ResetHarness(list(states), api_version)
        return h

    def test_preview_binds_exact_matched_set_and_filter_scope(self):
        h = self.harness(state("k1", "vm-1", "red"), state("k2", "vm-2", "yellow"),
                         state("k3", "host-1", "red"))
        binding = h.reader().preflight_reset({"entity_type": "vm"})
        self.assertEqual(binding["scope"]["entity_type"], "vm")
        self.assertEqual(binding["scope"]["type_entity"], "entityTypeVm")
        self.assertEqual(binding["scope"]["statuses"], ["red", "yellow"])
        self.assertEqual(binding["scope"]["count"], 2)
        self.assertEqual(binding["scope"]["entities"], ["vm-1", "vm-2"])
        self.assertEqual(binding["before"]["matched_keys"], ["k1", "k2"])
        self.assertEqual(binding["server_uuid"], "server-a")
        self.assertTrue(any("不能精确定位" in w for w in binding["warnings"]))
        json.dumps(binding)

    def test_engine_apply_clears_and_verifies_bound_set_gone(self):
        h = self.harness(state("k1", "vm-1", "red"), state("k2", "vm-2", "yellow"),
                         state("k3", "host-9", "red"))
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.db")
            try:
                engine = Engine(store, h.mutations(), "lab")
                plan = engine.preview("alarm reset", {"entity_type": "vm"}).data
                self.assertEqual(h.cleared, [])  # preview never writes
                result = engine.apply(plan["id"], plan["confirmation"])
                self.assertEqual(result.status, "succeeded")
            finally:
                store.close()
        self.assertEqual(len(h.cleared), 1)
        token, statuses, count = h.cleared[0]
        self.assertEqual(token, "entityTypeVm")
        self.assertEqual(statuses, ["red", "yellow"])
        self.assertEqual(count, 2)
        # Host alarms are outside the VM-type filter and must survive.
        self.assertEqual([s.entity._moId for s in h.states], ["host-9"])

    def test_status_filter_is_honoured(self):
        h = self.harness(state("k1", "vm-1", "red"), state("k2", "vm-2", "yellow"))
        binding = h.reader().preflight_reset({"entity_type": "vm", "statuses": ["red"]})
        self.assertEqual(binding["scope"]["statuses"], ["red"])
        self.assertEqual(binding["before"]["matched_keys"], ["k1"])
        h.reader().submit_reset({"entity_type": "vm", "statuses": ["red"]}, binding)
        self.assertEqual(h.cleared[0][1], ["red"])
        self.assertEqual([s.entity._moId for s in h.states], ["vm-2"])

    def test_6_5_is_rejected(self):
        h = self.harness(state("k1", "vm-1"), api_version="6.5.0")
        with self.assertRaises(OperationError) as caught:
            h.reader().preflight_reset({"entity_type": "vm"})
        self.assertEqual(caught.exception.code, "capability_unsupported")
        self.assertEqual(h.cleared, [])

    def test_6_7_is_supported(self):
        h = self.harness(state("k1", "vm-1"), api_version="6.7.0")
        binding = h.reader().preflight_reset({"entity_type": "vm"})
        h.reader().submit_reset({"entity_type": "vm"}, binding)
        self.assertEqual(h.cleared[0][0], "entityTypeVm")

    def test_cluster_and_datastore_entity_types_are_rejected(self):
        h = self.harness(state("k1", "vm-1"))
        for bad in ("cluster", "datastore"):
            with self.assertRaises(OperationError) as caught:
                h.reader().preflight_reset({"entity_type": bad})
            self.assertEqual(caught.exception.code, "invalid_arguments")
        self.assertEqual(h.cleared, [])

    def test_empty_match_refuses_global_write(self):
        h = self.harness(state("k1", "host-1", "red"))
        with self.assertRaises(OperationError) as caught:
            h.reader().preflight_reset({"entity_type": "vm"})
        self.assertEqual(caught.exception.code, "precondition_failed")
        self.assertEqual(h.cleared, [])

    def test_new_alarm_appearing_after_preview_blocks_submission(self):
        states = [state("k1", "vm-1", "red")]
        h = self.harness(*states)
        reader = h.reader()
        binding = reader.preflight_reset({"entity_type": "vm"})
        # A second VM alarm enters the same filter scope before submission.
        h.states.append(state("k9", "vm-9", "red"))
        with self.assertRaises(OperationError) as caught:
            reader.submit_reset({"entity_type": "vm"}, binding)
        self.assertEqual(caught.exception.code, "plan_stale")
        self.assertEqual(h.cleared, [])

    def test_alarm_self_clearing_between_preview_and_submit_is_allowed(self):
        h = self.harness(state("k1", "vm-1", "red"), state("k2", "vm-2", "red"))
        reader = h.reader()
        binding = reader.preflight_reset({"entity_type": "vm"})
        h.states.pop(0)  # k1 cleared on its own; the confirmed set only shrinks.
        receipt = reader.submit_reset({"entity_type": "vm"}, binding)
        self.assertTrue(receipt["reset"])
        self.assertEqual(h.cleared[0][2], 1)

    def test_engine_rejects_stale_expansion_before_write(self):
        h = self.harness(state("k1", "vm-1", "red"))
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.db")
            try:
                engine = Engine(store, h.mutations(), "lab")
                plan = engine.preview("alarm reset", {"entity_type": "vm"}).data
                h.states.append(state("k9", "vm-9", "red"))
                # The engine's submit-time preflight recheck compares the bound
                # alarm set and refuses before any bulk write.
                with self.assertRaises(OperationError) as caught:
                    engine.apply(plan["id"], plan["confirmation"])
                self.assertEqual(caught.exception.code, "plan_stale")
            finally:
                store.close()
        self.assertEqual(h.cleared, [])

    def test_invalid_statuses_rejected(self):
        h = self.harness(state("k1", "vm-1"))
        for bad in ({"entity_type": "vm", "statuses": ["green"]},
                    {"entity_type": "vm", "statuses": []},
                    {"entity_type": "vm", "statuses": ["red", "red"]}):
            with self.assertRaises(OperationError):
                h.reader().preflight_reset(bad)

    def test_submission_rejected_wraps_pre_write_failure(self):
        h = self.harness(state("k1", "vm-1"))
        binding = h.mutations().preflight("alarm reset", {"entity_type": "vm"})
        # Force the submit-time preflight recheck to fail before the write.
        h.content.about.apiVersion = "6.5.0"
        with self.assertRaises(SubmissionRejected):
            h.mutations().submit("alarm reset", {"entity_type": "vm"}, binding)
        self.assertEqual(h.cleared, [])


if __name__ == "__main__":
    unittest.main()
