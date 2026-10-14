import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.guest_customize import validate_spec


def adapter(**changes):
    value = {"mac": "00:11:22:33:44:55",
             "ipv4": {"method": "static", "address": "192.168.1.10",
                      "prefix": 24, "gateway": "192.168.1.1"},
             "dns_servers": ["8.8.8.8"], "dns_search": ["example.com"]}
    value.update(changes)
    return value


class ValidateSpecTests(unittest.TestCase):
    def test_static_ok(self):
        result = validate_spec({"hostname": "web-01", "adapter": adapter()})
        self.assertEqual(result["hostname"], "web-01")
        self.assertEqual(result["adapter"]["ipv4"]["address"], "192.168.1.10")
        self.assertEqual(result["adapter"]["mac"], "00:11:22:33:44:55")

    def test_dhcp_ok(self):
        a = adapter(ipv4={"method": "dhcp"})
        result = validate_spec({"adapter": a})
        self.assertIsNone(result["hostname"])
        self.assertEqual(result["adapter"]["ipv4"]["method"], "dhcp")

    def test_selector_by_name_ok(self):
        a = adapter()
        a.pop("mac")
        a["name"] = "eth0"
        result = validate_spec({"adapter": a})
        self.assertEqual(result["adapter"]["name"], "eth0")

    def test_missing_adapter_rejected(self):
        with self.assertRaises(OperationError) as ctx:
            validate_spec({"hostname": "x"})
        self.assertEqual(ctx.exception.code, "guest_spec_invalid")

    def test_both_selector_rejected(self):
        a = adapter()
        a["name"] = "eth0"
        with self.assertRaises(OperationError):
            validate_spec({"adapter": a})

    def test_neither_selector_rejected(self):
        a = adapter()
        a.pop("mac")
        with self.assertRaises(OperationError):
            validate_spec({"adapter": a})

    def test_bad_prefix_rejected(self):
        a = adapter(ipv4={"method": "static", "address": "10.0.0.2",
                          "prefix": 33})
        with self.assertRaises(OperationError):
            validate_spec({"adapter": a})

    def test_dhcp_with_static_fields_rejected(self):
        a = adapter(ipv4={"method": "dhcp", "address": "10.0.0.1"})
        with self.assertRaises(OperationError):
            validate_spec({"adapter": a})

    def test_static_missing_gateway_ok_optional(self):
        a = adapter(ipv4={"method": "static", "address": "10.0.0.2",
                          "prefix": 24})
        result = validate_spec({"adapter": a})
        self.assertIsNone(result["adapter"]["ipv4"]["gateway"])

    def test_bad_dns_rejected(self):
        a = adapter(dns_servers=["not-an-ip"])
        with self.assertRaises(OperationError):
            validate_spec({"adapter": a})

    def test_bad_hostname_rejected(self):
        with self.assertRaises(OperationError):
            validate_spec({"hostname": "bad host!", "adapter": adapter()})

    def test_unknown_field_rejected(self):
        with self.assertRaises(OperationError):
            validate_spec({"adapter": adapter(), "extra": 1})


if __name__ == "__main__":
    unittest.main()
