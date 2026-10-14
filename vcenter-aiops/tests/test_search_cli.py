import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.application.context import Context
from vcenter_aiops.cli.main import main
from test_search_recovery import SearchProvider


class SearchCliTests(unittest.TestCase):
    def test_recursive_search_recovers_through_cli_without_resubmitting(self):
        from vcenter_aiops.application.registry import lookup
        spec = lookup("datastore scan")
        self.assertIn("recursive", spec.input_schema()["properties"], "recursive CLI contract missing")
        @contextlib.contextmanager
        def session(ctx):
            yield object()
        provider = SearchProvider()
        def call(args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--profile", "lab", *args])
            return code, json.loads(out.getvalue())
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp}), \
             patch.object(Context, "session", session), \
             patch("vcenter_aiops.application.commands.datastores.Datastores", return_value=provider), \
             patch("vcenter_aiops.infrastructure.config.Profiles.get", return_value={"verify_tls": True}):
            code, started = call(["datastore", "scan", "--datastore-id", "datastore-1", "--recursive", "--no-wait", "--request-id", "cli-search"])
            self.assertEqual(code, 0)
            self.assertTrue(started["data"]["scope"]["recursive"])
            self.assertEqual(started["next_action"]["command"], "datastore search-status")
            search_id = started["operation_id"]
            provider.state = "succeeded"
            code, finished = call(["datastore", "search-status", search_id])
            self.assertEqual(code, 0)
            self.assertEqual(finished["status"], "succeeded")
            self.assertEqual(provider.calls, 1)
            with patch.object(Context, "session", side_effect=AssertionError("local inspect connected")):
                _, inspected = call(["datastore", "search-inspect", search_id])
                _, listing = call(["datastore", "search-list"])
            self.assertEqual(inspected["data"]["result"]["items"][0]["name"], "boot.iso")
            self.assertEqual(listing["data"][0]["id"], search_id)
