import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notification_bridge.cli import InstallerProcessRunner


class InstallProcessTests(unittest.TestCase):
    def test_timeout_stops_installer_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'must-not-exist'
            child = 'import time,pathlib;time.sleep(1);pathlib.Path({!r}).touch()'.format(str(marker))
            parent = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[1]]);time.sleep(5)'
            started = time.monotonic()
            result = InstallerProcessRunner(timeout=0.2).run([sys.executable, '-c', parent, child])
            self.assertEqual(result.returncode, 124)
            self.assertLess(time.monotonic() - started, 2)
            time.sleep(1.1)
            self.assertFalse(marker.exists())
