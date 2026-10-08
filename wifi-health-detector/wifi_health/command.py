from __future__ import absolute_import

import locale
import os
import subprocess
import time
import signal


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
    def __init__(self, timeout=10, verbose=False, budget=None):
        self.timeout = timeout
        self.verbose = verbose
        self.deadline = time.monotonic() + budget if budget is not None else None

    def remaining(self):
        return max(0, self.deadline - time.monotonic()) if self.deadline is not None else self.timeout

    def run(self, args, timeout=None):
        duration = min(timeout or self.timeout, self.timeout, self.remaining())
        if duration <= 0:
            return CommandResult(list(args), 124, error="total time budget exhausted")
        try:
            process = subprocess.Popen(
                list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                start_new_session=(os.name != "nt")
            )
            stdout, stderr = process.communicate(timeout=duration)
            return CommandResult(
                list(args), process.returncode, self._decode(stdout), self._decode(stderr)
            )
        except subprocess.TimeoutExpired as expired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if process.poll() is None:
                    process.kill()
            try:
                stdout, stderr = process.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                stdout, stderr = expired.output or b"", expired.stderr or b""
                process.stdout.close()
                process.stderr.close()
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
