import os
import ssl
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.connection import Session
from vcenter_aiops.providers.vsphere.inventory import Inventory


class ConnectionTests(unittest.TestCase):
    profile = {"host": "not-a-real-vcenter.test", "user": "reader", "password_ref": "env:VC_TEST"}

    def test_tls_default_and_disconnect(self):
        with patch.dict(os.environ, {"VC_TEST": "example-only"}), patch("pyVim.connect.SmartConnect") as connect, patch("pyVim.connect.Disconnect") as disconnect:
            with Session(self.profile) as si:
                self.assertIs(si, connect.return_value)
                ctx = connect.call_args.kwargs["sslContext"]
                self.assertTrue(ctx.check_hostname)
                self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
                self.assertEqual(connect.call_args.kwargs["httpConnectionTimeout"], 30)
            disconnect.assert_called_once_with(si)

    def test_explicit_insecure_only(self):
        with patch.dict(os.environ, {"VC_TEST": "example-only"}), patch("pyVim.connect.SmartConnect") as connect, patch("pyVim.connect.Disconnect"):
            with Session({**self.profile, "verify_tls": False}):
                self.assertEqual(connect.call_args.kwargs["sslContext"].verify_mode, ssl.CERT_NONE)

    def test_sdk_error_does_not_leak_password(self):
        with patch.dict(os.environ, {"VC_TEST": "private-test"}), patch("pyVim.connect.SmartConnect", side_effect=RuntimeError("private-test")):
            with self.assertRaises(OperationError) as error:
                with Session(self.profile):
                    pass
            self.assertNotIn("private-test", str(error.exception))

    def test_missing_credential_never_connects(self):
        with patch.dict(os.environ, {}, clear=True), patch("pyVim.connect.SmartConnect") as connect:
            with self.assertRaises(OperationError):
                with Session(self.profile):
                    pass
            connect.assert_not_called()


class InventoryTests(unittest.TestCase):
    def make(self, pages):
        from pyVmomi import vim
        view = vim.view.ContainerView("view-test", None)
        manager = MagicMock()
        manager.CreateContainerView.return_value = view
        collector = MagicMock()
        collector.RetrievePropertiesEx.return_value = pages[0]
        collector.ContinueRetrievePropertiesEx.side_effect = pages[1:]
        content = NS(viewManager=manager, propertyCollector=collector, rootFolder=vim.Folder("root", None))
        si = NS(RetrieveContent=lambda: content)
        return Inventory(si), collector

    @staticmethod
    def item(number):
        return NS(obj=NS(_moId=str(number)), propSet=[NS(name="name", val="vm" + str(number))], missingSet=[])

    def test_bulk_pages_and_truncation_clean_up(self):
        from pyVmomi import vim
        pages = [NS(token="t1", objects=[self.item(1)]), NS(token="t2", objects=[self.item(2)])]
        inventory, collector = self.make(pages)
        with patch.object(vim.view.ContainerView, "Destroy") as destroy:
            result = inventory.list(limit=2)
        self.assertTrue(result["truncated"])
        self.assertEqual([x["id"] for x in result["items"]], ["1", "2"])
        collector.CancelRetrievePropertiesEx.assert_called_once_with(token="t2")
        destroy.assert_called_once()

    def test_view_destroyed_even_if_query_fails(self):
        from pyVmomi import vim
        inventory, collector = self.make([None])
        collector.RetrievePropertiesEx.side_effect = RuntimeError("query failed")
        with patch.object(vim.view.ContainerView, "Destroy") as destroy:
            with self.assertRaises(RuntimeError):
                inventory.list()
        destroy.assert_called_once()

    def test_vm_and_host_enum_properties_leave_provider_as_plain_strings(self):
        from pyVmomi import vim
        cases = (("vm", "runtime.powerState", vim.VirtualMachinePowerState.poweredOn, "poweredOn"),
                 ("host", "runtime.connectionState", vim.HostSystemConnectionState.connected, "connected"))
        for kind, field, enum, expected in cases:
            with self.subTest(kind=kind):
                item = NS(obj=NS(_moId="one"), propSet=[NS(name=field, val=enum)], missingSet=[])
                inventory, _ = self.make([NS(token=None, objects=[item])])
                with patch.object(vim.view.ContainerView, "Destroy"):
                    result = inventory.list(kind, 10)
                self.assertEqual(result["items"][0][field], expected)
                self.assertIs(type(result["items"][0][field]), str)

    def test_unknown_sdk_property_object_is_rejected_at_provider_boundary(self):
        from pyVmomi import vim
        item = NS(obj=NS(_moId="one"), propSet=[NS(name="runtime.powerState", val=object())], missingSet=[])
        inventory, _ = self.make([NS(token=None, objects=[item])])
        with patch.object(vim.view.ContainerView, "Destroy") as destroy:
            with self.assertRaises(OperationError) as error:
                inventory.list("vm", 10)
        self.assertEqual(error.exception.code, "query_incomplete")
        destroy.assert_called_once()
