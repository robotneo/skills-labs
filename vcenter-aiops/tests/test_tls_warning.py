import contextlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vcenter_aiops.application.registry import lookup
from vcenter_aiops.cli.main import TLS_DISABLED_WARNING, append_tls_warning, main
from vcenter_aiops.domain.models import Result
from test_execution import FakeProvider


class CtxStub:
    def __init__(self, verify_tls):
        self.profile = "lab"
        self.profiles = SimpleNamespace(
            get=lambda name: {"verify_tls": verify_tls})


class TlsWarningUnitTests(unittest.TestCase):
    def _spec(self, path="vm power-on"):
        return lookup(path)

    def test_remote_write_warns_when_tls_disabled(self):
        result = Result(status="awaiting_confirmation")
        out = append_tls_warning(CtxStub(False), self._spec(), result)
        self.assertIn(TLS_DISABLED_WARNING, out.warnings)

    def test_remote_write_silent_when_tls_verified(self):
        result = Result(status="awaiting_confirmation")
        out = append_tls_warning(CtxStub(True), self._spec(), result)
        self.assertNotIn(TLS_DISABLED_WARNING, out.warnings)

    def test_warning_is_added_once(self):
        result = Result(status="succeeded", warnings=[TLS_DISABLED_WARNING])
        out = append_tls_warning(CtxStub(False), self._spec(), result)
        self.assertEqual(out.warnings.count(TLS_DISABLED_WARNING), 1)

    def test_error_result_is_not_decorated(self):
        result = Result(status="failed", error={"code": "x"})
        out = append_tls_warning(CtxStub(False), self._spec(), result)
        self.assertEqual(out.warnings, [])

    def test_plan_apply_path_is_covered(self):
        spec = lookup("plan apply")
        result = Result(status="succeeded")
        out = append_tls_warning(CtxStub(False), spec, result)
        self.assertIn(TLS_DISABLED_WARNING, out.warnings)


class TlsWarningCliTests(unittest.TestCase):
    def test_preview_carries_tls_warning_when_disabled(self):
        @contextlib.contextmanager
        def session(ctx):
            yield object()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp}):
            from vcenter_aiops.application.context import Context
            provider = FakeProvider()
            output = io.StringIO()
            with patch.object(Context, "session", session), \
                 patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=provider), \
                 patch("vcenter_aiops.infrastructure.config.Profiles.get",
                       return_value={"verify_tls": False}), \
                 contextlib.redirect_stdout(output):
                code = main(["--profile", "lab", "vm", "power-on",
                             "--vm-id", "vm-1", "--request-id", "tls-1"])
            self.assertEqual(code, 4)
            payload = json.loads(output.getvalue())
            self.assertIn(TLS_DISABLED_WARNING, payload["warnings"])


if __name__ == "__main__":
    unittest.main()
