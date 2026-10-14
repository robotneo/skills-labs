from pathlib import Path
import runpy
import tempfile
import unittest
from zipfile import ZipFile


class PackageVerificationTests(unittest.TestCase):
    def test_wheel_guard_rejects_stale_missing_and_modified_modules(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "verify_wheel.py"
        self.assertTrue(script.is_file(), "wheel/source comparison missing")
        verify = runpy.run_path(str(script))["verify"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src"
            source.mkdir()
            (source / "module.py").write_text("VALUE = 1\n")
            wheel = root / "package.whl"
            for files, valid in (({"module.py": "VALUE = 1\n"}, True),
                                 ({"module.py": "VALUE = 1\n", "removed.py": "pass\n"}, False),
                                 ({"module.py": "VALUE = 2\n"}, False), ({}, False)):
                with ZipFile(wheel, "w") as archive:
                    for name, content in files.items():
                        archive.writestr(name, content)
                if valid:
                    self.assertEqual(verify(wheel, source)["modules"], 1)
                else:
                    with self.assertRaises(ValueError):
                        verify(wheel, source)
