"""Security regressions for untrusted network names and portable entrypoints."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wifi_health.models import Report
from wifi_health.output import render_csv


class SecurityTests(unittest.TestCase):
    def test_dns_uses_native_resolver_and_rejects_empty_success(self):
        from unittest.mock import patch
        from wifi_health.network import dns_test
        empty = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        answer = subprocess.CompletedProcess([], 0, stdout='name: www.baidu.com\nip_address: 192.0.2.1\n', stderr='')
        with patch('wifi_health.network.platform.system', return_value='Darwin'):
            with patch('wifi_health.network.subprocess.run', return_value=empty) as run:
                self.assertFalse(dns_test('www.baidu.com')['reachable'])
                self.assertEqual(run.call_args[0][0][0], '/usr/bin/dscacheutil')
            with patch('wifi_health.network.subprocess.run', return_value=answer):
                self.assertTrue(dns_test('www.baidu.com')['reachable'])
            with patch('wifi_health.network.subprocess.run') as run:
                self.assertFalse(dns_test('-malformed')['reachable'])
                run.assert_not_called()

    def test_csv_network_names_are_literal_cells(self):
        for ssid in ('=1+1', '+1+1', '-1+1', '@SUM(1)', '\t=1+1', ' =1+1'):
            report = Report.empty()
            report.set('connection', 'ssid', ssid)
            report.set('radio', 'rssi', -60)
            rows = list(csv.DictReader(io.StringIO(render_csv(report))))
            value = next(row['value'] for row in rows if row['field'] == 'ssid')
            self.assertEqual(value, "'" + ssid)
            self.assertEqual(next(row['value'] for row in rows if row['field'] == 'rssi'), '-60')

    def test_portable_csv_network_names_are_literal_cells(self):
        engines = []
        node = os.environ.get('TEST_NODE')
        if node:
            engines.append([node, str(ROOT / 'portable/node.cjs')])
        if sys.platform == 'darwin':
            engines.append(['/usr/bin/osascript', '-l', 'JavaScript', str(ROOT / 'portable/macos.js')])
        powershell = os.environ.get('TEST_POWERSHELL')
        if powershell:
            engines.append([powershell, '-NoProfile', '-File', str(ROOT / 'portable/windows.ps1')])
        if not engines:
            self.skipTest('No portable runtime supplied')
        report = Report.empty()
        report.set('connection', 'ssid', '=1+1')
        report.set('radio', 'rssi', -60)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.json'
            target = Path(directory) / 'output.csv'
            source.write_text(json.dumps(report.to_dict()), encoding='utf-8')
            for engine in engines:
                with self.subTest(engine=engine[0]):
                    result = subprocess.run(engine + ['--report-input', str(source), '--csv', str(target), '--no-notify'], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    rows = list(csv.DictReader(io.StringIO(target.read_text(encoding='utf-8-sig'))))
                    self.assertEqual(next(row['value'] for row in rows if row['field'] == 'ssid'), "'=1+1")
                    self.assertEqual(next(row['value'] for row in rows if row['field'] == 'rssi'), '-60')

    def test_windows_entries_preserve_execution_policy(self):
        for path in ROOT.rglob('*.bat'):
            self.assertNotIn('-executionpolicy', path.read_text().lower(), str(path))

    def test_jxa_has_no_dynamic_source_evaluation(self):
        import re
        source = (ROOT / 'portable/macos.js').read_text()
        self.assertIsNone(re.search(r'\beval\s*\(', source))


if __name__ == '__main__':
    unittest.main()
