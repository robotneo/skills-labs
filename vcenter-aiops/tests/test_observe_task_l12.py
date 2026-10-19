"""L-12 regression: dangling task at observe is structured unknown/6.

After submit, the engine polls Mutations.observe() to read ``task.info``. The task
(or the inventory record backing it) can be removed between submit and poll, in
which case the ``info`` fetch raises ManagedObjectNotFound. That is a *post-write*
condition: the mutation may already have succeeded, so it must never become a
deterministic not_found (exit 4, safe to retry) -- retrying could re-issue a power
change or a clone. observe() must return a structured unknown observation carrying
``task_state_unknown`` and a reconcile hint that the engine persists and routes to
reconciliation_required (6), rather than letting the raw SDK fault escape.
"""
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim, vmodl

from vcenter_aiops.providers.vsphere.mutations import Mutations


def stale_task(task_id):
    """vim.Task subclass whose ``.info`` fetch raises MONF naming the task."""
    base = vim.Task
    fault = vmodl.fault.ManagedObjectNotFound(obj=vim.Task(task_id, object()))

    def __getattr__(self, name):
        if name == "info":
            raise fault
        raise AttributeError(name)

    cls = type("Stale" + base.__name__, (base,), {"__getattr__": __getattr__})
    return cls(task_id, object())


def make_provider(task_obj):
    content = NS(about=NS(instanceUuid="server-1"))
    si = NS(RetrieveContent=lambda: content, _stub=None)
    return Mutations(si, resolver=lambda kind, oid:
                     task_obj if kind == "task" else None)


class ObserveDanglingTaskTests(unittest.TestCase):
    RECEIPT = {"task_id": "server-1:task-1"}
    BINDING = {"server_uuid": "server-1"}

    def test_dangling_task_info_returns_structured_unknown(self):
        provider = make_provider(stale_task("task-1"))
        observation = provider.observe(self.RECEIPT, self.BINDING)
        self.assertEqual(observation["state"], "unknown")
        error = observation.get("error")
        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "task_state_unknown")
        self.assertFalse(error.get("retryable", True))
        self.assertIn("task-1", error["message"])

    def test_fault_naming_other_task_is_not_rewritten(self):
        # A fault that names a different object is not the dangling receipt task;
        # it must propagate rather than be reported as our task going unknown.
        other = vmodl.fault.ManagedObjectNotFound(obj=vim.Task("task-999", object()))

        class TaskWithOtherFault(vim.Task):
            def __getattr__(self, name):
                if name == "info":
                    raise other
                raise AttributeError(name)

        task = TaskWithOtherFault("task-1", object())
        provider = make_provider(task)
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider.observe(self.RECEIPT, self.BINDING)

    def test_healthy_task_info_is_observed_normally(self):
        info = NS(state="success", error=None, result=None, progress=100)
        task = NS(_moId="task-1", info=info)
        provider = make_provider(task)
        observation = provider.observe(self.RECEIPT, self.BINDING)
        self.assertEqual(observation["state"], "success")
        self.assertEqual(observation["progress"], 100)


if __name__ == "__main__":
    unittest.main()
