import importlib.util
import json
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError


class AlarmTests(unittest.TestCase):
    def test_confirmed_alarm_plan_verifies_and_declines_fabricated_rollback(self):
        import tempfile
        from pathlib import Path
        from vcenter_aiops.application.execution import Engine
        from vcenter_aiops.infrastructure.store import Store
        from vcenter_aiops.providers.vsphere.mutations import Mutations
        state = self.state(acknowledged=False)
        reader = self.reader([state])
        reader.content.about = NS(instanceUuid="server-a", apiType="VirtualCenter", apiVersion="6.5")
        reader.si.RetrieveContent = lambda: reader.content
        reader.content.alarmManager = NS(AcknowledgeAlarm=lambda **kwargs: setattr(state, "acknowledged", True))
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.db")
            try:
                engine = Engine(store, Mutations(reader.si), "lab")
                plan = engine.preview("alarm acknowledge", {"entity_id": "vm-1", "alarm_id": "alarm-1"}).data
                self.assertFalse(state.acknowledged)
                self.assertEqual(engine.apply(plan["id"], plan["confirmation"]).status, "succeeded")
                self.assertTrue(state.acknowledged)
                self.assertEqual(engine.rollback(plan["id"]).error["code"], "compensation_unavailable")
            finally:
                store.close()

    def reader(self, states=None, missing=False):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.providers.vsphere.alarms"), "alarm reader missing")
        from vcenter_aiops.providers.vsphere.alarms import Alarms
        from pyVmomi import vim
        self.specs = []
        root = vim.Folder("group-d1")
        def retrieve(specSet, options):
            self.specs.extend(specSet)
            obj = specSet[0].objectSet[0].obj
            return NS(token=None, objects=[NS(obj=obj, propSet=[] if missing else [NS(name="triggeredAlarmState", val=states or [])], missingSet=[NS(path="triggeredAlarmState")] if missing else [])])
        si = NS(RetrieveContent=lambda: NS(rootFolder=root, propertyCollector=NS(RetrievePropertiesEx=retrieve)), _stub=None)
        return Alarms(si)

    def state(self, entity="vm-1", status="red", acknowledged=None):
        return NS(key="alarm-state-1", alarm=NS(_moId="alarm-1"), entity=NS(_moId=entity), overallStatus=status,
                  time=None, acknowledged=acknowledged, acknowledgedByUser=None, acknowledgedTime=None)

    def test_list_preserves_exact_alarm_and_entity_and_unknown_acknowledgement(self):
        reader = self.reader([self.state()])
        data = reader.list(limit=100)
        self.assertEqual(data["items"][0]["alarm_id"], "alarm-1")
        self.assertEqual(data["items"][0]["entity_id"], "vm-1")
        self.assertIsNone(data["items"][0]["acknowledged"])
        self.assertEqual(data["scope"]["entity_id"], "group-d1")
        self.assertTrue(data["scope"]["includes_descendants"])
        self.assertEqual(list(self.specs[0].propSet[0].pathSet), ["triggeredAlarmState"])
        json.dumps(data)

    def test_missing_property_is_not_a_healthy_empty_result(self):
        reader = self.reader(missing=True)
        with self.assertRaises(OperationError) as error:
            reader.list()
        self.assertEqual(error.exception.code, "alarm_query_unavailable")

    def test_filter_happens_before_limit_and_marks_truncation(self):
        reader = self.reader([self.state(status="yellow"), self.state(), self.state(entity="vm-2")])
        data = reader.list(status="red", limit=1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["status"], "red")
        self.assertTrue(data["truncated"])

    def test_invalid_entity_does_not_fall_back_to_root(self):
        reader = self.reader()
        with self.assertRaises(OperationError):
            reader.list(entity_id="not-an-id")
        self.assertEqual(self.specs, [])

    def test_acknowledge_requires_exact_entity_and_alarm_then_verifies_state(self):
        state = self.state()
        reader = self.reader([state])
        self.assertTrue(callable(getattr(reader, "preflight_acknowledge", None)), "acknowledgement missing")
        reader.content.about = NS(instanceUuid="server-a", apiType="VirtualCenter", apiVersion="6.5")
        calls = []
        def acknowledge(alarm, entity):
            calls.append((alarm._moId, entity._moId))
        reader.content.alarmManager = NS(AcknowledgeAlarm=acknowledge)
        p = {"entity_id": "vm-1", "alarm_id": "alarm-1"}
        binding = reader.preflight_acknowledge(p)
        self.assertEqual(binding["scope"], {"entity_id": "vm-1", "alarm_id": "alarm-1", "count": 1})
        reader.submit_acknowledge(p, binding)
        self.assertEqual(calls, [("alarm-1", "vm-1")])
        self.assertFalse(reader.verify_acknowledge(p, binding))
        state.acknowledged = True
        self.assertTrue(reader.verify_acknowledge(p, binding))
        with self.assertRaises(OperationError):
            reader.preflight_acknowledge({"entity_id": "vm-2", "alarm_id": "alarm-1"})
        self.assertEqual(len(calls), 1)
