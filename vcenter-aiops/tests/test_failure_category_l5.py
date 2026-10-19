"""L-5: --json failures must carry a stable ``category`` so automation can tell
a business failure apart from an internal error despite both exiting 5.

* handler returns status failed/partial -> category="business_failure"
* an unexpected exception is caught      -> category="internal_error"
Exit code stays 5 in both cases (contract unchanged).
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from vcenter_aiops.domain.models import Result
from vcenter_aiops.cli import main as cli


class FailureCategoryJsonTests(unittest.TestCase):
    def run_cli(self, invoke_side_effect):
        out = io.StringIO()
        with patch("vcenter_aiops.cli.main.invoke", side_effect=invoke_side_effect):
            with contextlib.redirect_stdout(out):
                code = cli.main(["cache", "status", "--kind", "vm"])
        return code, json.loads(out.getvalue())

    def test_business_failure_is_categorized(self):
        def fail_business(command, params, ctx):
            return Result(status="failed",
                          error={"code": "some_business_rule", "message": "业务未满足",
                                 "retryable": False})

        code, payload = self.run_cli(fail_business)
        self.assertEqual(code, 5)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["category"], "business_failure")
        self.assertEqual(payload["error"]["code"], "some_business_rule")

    def test_business_partial_is_categorized(self):
        def partial(command, params, ctx):
            return Result(status="partial", error={"code": "partial_apply",
                                                   "message": "部分完成", "retryable": False})

        code, payload = self.run_cli(partial)
        self.assertEqual(code, 5)
        self.assertEqual(payload["category"], "business_failure")

    def test_internal_error_is_categorized(self):
        def boom(command, params, ctx):
            raise RuntimeError("local defect")

        code, payload = self.run_cli(boom)
        self.assertEqual(code, 5)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["category"], "internal_error")
        self.assertEqual(payload["error"]["code"], "internal_error")
        # Generic message only; the defect text must never leak to stdout.
        self.assertNotIn("local defect", json.dumps(payload, ensure_ascii=False))

    def test_success_has_no_failure_category(self):
        def ok(command, params, ctx):
            return Result(status="succeeded", data={"state": "missing"})

        code, payload = self.run_cli(ok)
        self.assertEqual(code, 0)
        self.assertNotIn("category", payload)

    def test_awaiting_confirmation_is_not_a_failure_category(self):
        def awaiting(command, params, ctx):
            return Result(status="awaiting_confirmation", data={"digest": "abc"})

        code, payload = self.run_cli(awaiting)
        self.assertEqual(code, 4)
        self.assertNotIn("category", payload)


if __name__ == "__main__":
    unittest.main()
