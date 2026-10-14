import contextlib
import io
import json
import unittest

from vcenter_aiops.application.registry import COMMANDS
from vcenter_aiops.cli.main import main
from vcenter_aiops.domain.models import OperationError


class ContractTests(unittest.TestCase):
    def test_each_leaf_has_strict_schema_and_callable_handler(self):
        for spec in COMMANDS:
            with self.subTest(command=spec.path):
                self.assertTrue(callable(getattr(spec, "input_schema", None)))
                self.assertFalse(spec.input_schema()["additionalProperties"])
                self.assertTrue(callable(spec.handler()))

    def test_cli_exposes_schema_without_connecting(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["capabilities", "show", "vm inspect"])
        self.assertEqual(code, 0)
        data = json.loads(output.getvalue())["data"]
        self.assertIn("id", data["input_schema"]["properties"])
        self.assertEqual(data["vsphere"]["6.5"], "not_lab_verified")

    def test_parameters_reject_unknown_and_wrong_types(self):
        spec = next(c for c in COMMANDS if c.path == "ip reserve")
        self.assertTrue(callable(getattr(spec, "validate", None)))
        for params in ({"scope": "n", "ip": "10.0.0.1", "owner": "u", "minutes": True},
                       {"scope": "n", "ip": "10.0.0.1", "owner": "u", "password": "unsafe"},
                       {"ip": "10.0.0.1", "owner": "u"}):
            with self.assertRaises(OperationError):
                spec.validate(params)

    def test_profile_update_does_not_reset_unspecified_tls_settings(self):
        spec = next(c for c in COMMANDS if c.path == "profile update")
        self.assertTrue(callable(getattr(spec, "validate", None)))
        self.assertEqual(spec.validate({"name": "lab", "user": "reader"}), {"name": "lab", "user": "reader"})
