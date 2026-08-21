from __future__ import absolute_import

import locale
import os
import subprocess


class CommandResult(object):
    def __init__(self, args, returncode, stdout="", stderr="", error=""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.error = error

    @property
    def ok(self):
        return self.returncode == 0


class CommandRunner(object):
    def __init__(self, timeout=10, verbose=False):
        self.timeout = timeout
        self.verbose = verbose

    def run(self, args, timeout=None):
        try:
            process = subprocess.Popen(
                list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False
            )
            stdout, stderr = process.communicate(timeout=timeout or self.timeout)
            return CommandResult(
                list(args), process.returncode, self._decode(stdout), self._decode(stderr)
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return CommandResult(list(args), 124, self._decode(stdout), self._decode(stderr), "timeout")
        except OSError as exc:
            return CommandResult(list(args), 127, error=str(exc))

    @staticmethod
    def _decode(value):
        if not value:
            return ""
        encodings = ["utf-8", locale.getpreferredencoding(False), "mbcs", "gb18030"]
        for encoding in encodings:
            try:
                return value.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                pass
        return value.decode("utf-8", errors="replace")
