"""Structured feature fixtures follow Broadcom govmomi simulator/license_manager.go."""
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim
from vcenter_aiops.domain.models import OperationError


SECRET = "DO-NOT-EXPORT-LICENSE-KEY"


def assignment(entity_id="host-1", features=("drs", "vmotion")):
    props = [NS(key="feature", value=vim.KeyValue(key=key, value=key)) for key in features]
    props.append(NS(key="expirationDate", value="2099-01-01T00:00:00Z"))
    return NS(entityId=entity_id, scope="server-1", assignedLicense=NS(
        licenseKey=SECRET, editionKey="fixture", total=8, used=2,
        costUnit="cpuPackage", properties=props))


class LicenseEntitlementTests(unittest.TestCase):
    def checker(self, rows=None, query=None):
        module = importlib.import_module("vcenter_aiops.providers.vsphere.licenses")
        manager = NS(QueryAssignedLicenses=query or (lambda **kwargs: rows))
        content = NS(licenseManager=NS(licenseAssignmentManager=manager))
        return module.Licenses(content, now=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc))

    def test_valid_assignment_yields_sanitized_json_evidence(self):
        calls = []
        checker = self.checker(query=lambda **kwargs: calls.append(kwargs) or [assignment()])
        evidence = checker.require("host-1", ("drs", "vmotion"), "server-1")
        self.assertEqual(calls, [{"entityId": "host-1"}])
        self.assertEqual(evidence["features"], ["drs", "vmotion"])
        self.assertEqual(evidence["entity_id"], "host-1")
        self.assertNotIn(SECRET, json.dumps(evidence))
        self.assertNotIn("licenseKey", json.dumps(evidence))

    def test_unavailable_query_is_sanitized(self):
        def query(**kwargs):
            raise RuntimeError(SECRET)
        with self.assertRaises(OperationError) as error:
            self.checker(query=query).require("host-1", ("drs",), "server-1")
        self.assertNotIn(SECRET, str(error.exception))
        self.assertEqual(error.exception.code, "license_unknown")

    def test_missing_mismatched_or_missing_feature_evidence_is_rejected(self):
        # H-6 relaxation: multiple in-scope rows now aggregate features, so only
        # absent/foreign rows and genuinely missing features are rejected.
        cases = (None, [], [assignment("host-2")],
                 [assignment(features=("vmotion",))])
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(OperationError):
                    self.checker(rows).require("host-1", ("drs",), "server-1")

    def test_zero_rows_is_license_unverifiable_not_granted(self):
        # "查不到就允许" must remain impossible.
        with self.assertRaises(OperationError) as error:
            self.checker([]).require("host-1", ("drs",), "server-1")
        self.assertEqual(error.exception.code, "license_unverifiable")
        self.assertEqual(error.exception.exit_code, 4)

    def test_multiple_inscope_rows_aggregate_features(self):
        # Cluster/suite features commonly arrive across two rows; union grants.
        drs_row = assignment(features=("drs",))
        vmotion_row = assignment(features=("vmotion",))
        evidence = self.checker([drs_row, vmotion_row]).require(
            "host-1", ("drs", "vmotion"), "server-1")
        self.assertEqual(evidence["features"], ["drs", "vmotion"])
        self.assertEqual(len(evidence["licenses"]), 2)

    def test_foreign_scope_rows_never_contribute(self):
        # A row scoped to a different vCenter must not be aggregated into a grant.
        with self.assertRaises(OperationError):
            self.checker([assignment(features=("drs",))]).require(
                "host-1", ("drs",), "server-other")

    def test_perpetual_license_without_expiration_is_accepted(self):
        row = assignment(features=("drs", "vmotion"))
        row.assignedLicense.properties = [
            NS(key="feature", value=vim.KeyValue(key=key, value=key))
            for key in ("drs", "vmotion")]
        evidence = self.checker([row]).require("host-1", ("drs",), "server-1")
        self.assertEqual(evidence["features"], ["drs"])
        term = evidence["licenses"][0]
        self.assertTrue(term["perpetual"])
        self.assertIsNone(term["expires_at"])

    def test_unknown_property_keys_are_ignored(self):
        row = assignment(features=("drs",))
        row.assignedLicense.properties.append(NS(key="SomeFuture803Key", value="x"))
        evidence = self.checker([row]).require("host-1", ("drs",), "server-1")
        self.assertEqual(evidence["features"], ["drs"])

    def test_invalid_expired_diagnostic_and_unsupported_shapes_are_rejected(self):
        def expire(row):
            row.assignedLicense.properties[-1].value = "2020-01-01T00:00:00Z"
        def malformed(row):
            row.assignedLicense.properties[0].value = "drs"
        def diagnostic(row):
            row.assignedLicense.properties.append(NS(key="diagnostic", value=SECRET))
        def unparseable_expiry(row):
            # A concrete expiry that cannot parse must stay fail-closed and must
            # never be mistaken for a perpetual (no-key) license.
            row.assignedLicense.properties[-1].value = "not-a-date"
        for mutate in (expire, malformed, diagnostic, unparseable_expiry,
                       lambda row: setattr(row, "scope", "server-2"),
                       lambda row: setattr(row.assignedLicense, "total", 0),
                       lambda row: row.assignedLicense.properties.append(NS(key="license_not_set", value=1))):
            with self.subTest(mutate=mutate):
                row = assignment()
                mutate(row)
                with self.assertRaises(OperationError) as error:
                    self.checker([row]).require("host-1", ("drs",), "server-1")
                self.assertNotIn(SECRET, str(error.exception))


if __name__ == "__main__":
    unittest.main()
