"""Standalone, explicitly previewed Guest runtime. Uses only Python's stdlib."""
import base64 as _base64
import ctypes
import ntpath
import os
import stat
import subprocess
import sys


# Bounded capture limits enforced inside the Guest, never trusted from outside.
MAX_OUTPUT_BYTES = 65536
STDOUT_NAME = "stdout.b64"
STDERR_NAME = "stderr.b64"


def check_windows_acl(owner, current, entries, parent):
    """Reject NULL/unsupported ACLs; trust only this user, SYSTEM and admins."""
    trusted = {current, "S-1-5-18", "S-1-5-32-544"}
    if owner not in ({current} if parent else trusted) or entries is None:
        raise PermissionError("private directory required")
    # Parent: all writes. Ancestors: rights capable of replacing a child path.
    dangerous = 0x10000000 | 0x40000000 | 0x000D0040
    if parent:
        dangerous |= 0x00000116
    for kind, flags, mask, sid in entries:
        if kind not in (0, 1):
            raise PermissionError("unsupported DACL entry")
        if kind == 0 and not flags & 8 and sid not in trusted and mask & dangerous:
            raise PermissionError("directory writable by another principal")


class WindowsDirectories:
    """Win32 handles pin every ancestor against rename/delete until completion."""
    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.handles = []
        self._declare(self.kernel.GetCurrentProcess, [], w.HANDLE)
        self._declare(self.kernel.CloseHandle, [w.HANDLE], w.BOOL)
        self._declare(self.kernel.LocalFree, [ctypes.c_void_p], ctypes.c_void_p)
        self._declare(self.kernel.CreateFileW, [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)
        self._declare(self.kernel.GetFileInformationByHandleEx, [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL)
        self._declare(self.kernel.CreateDirectoryW, [w.LPCWSTR, ctypes.c_void_p], w.BOOL)
        self._declare(self.kernel.MoveFileExW, [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.BOOL)
        self._declare(self.advapi.OpenProcessToken, [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL)
        self._declare(self.advapi.GetTokenInformation, [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL)
        self._declare(self.advapi.ConvertSidToStringSidW, [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)], w.BOOL)
        self._declare(self.advapi.GetSecurityInfo, [w.HANDLE, ctypes.c_int, w.DWORD] + [ctypes.POINTER(ctypes.c_void_p)]*5, w.DWORD)
        self._declare(self.advapi.GetAce, [ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)], w.BOOL)
        self._declare(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW, [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD)], w.BOOL)
        token = w.HANDLE()
        self._ok(self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            needed = w.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not 1 <= needed.value <= 65536:
                raise PermissionError("token unavailable")
            buffer = ctypes.create_string_buffer(needed.value)
            self._ok(self.advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)))
            self.sid = self._sid(ctypes.c_void_p.from_buffer(buffer).value)
        finally:
            self.kernel.CloseHandle(token)

    @staticmethod
    def _declare(function, arguments, result):
        function.argtypes, function.restype = arguments, result

    @staticmethod
    def _ok(value):
        if not value:
            raise PermissionError("Win32 security operation failed")

    def _sid(self, pointer):
        value = self.w.LPWSTR()
        self._ok(self.advapi.ConvertSidToStringSidW(pointer, ctypes.byref(value)))
        try:
            return value.value
        finally:
            self.kernel.LocalFree(ctypes.cast(value, ctypes.c_void_p))

    def _open(self, path, parent):
        # FILE_READ_ATTRIBUTES | READ_CONTROL; share read/write, never DELETE.
        handle = self.kernel.CreateFileW(path, 0x20080, 3, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value or handle is None:
            raise PermissionError("directory handle unavailable")
        self.handles.append(handle)
        info = (ctypes.c_uint32 * 2)()
        self._ok(self.kernel.GetFileInformationByHandleEx(handle, 9, info, ctypes.sizeof(info)))
        if info[0] & 0x400 or not info[0] & 0x10:
            raise PermissionError("reparse point or non-directory")
        owner, group, dacl, sacl, descriptor = [ctypes.c_void_p() for _ in range(5)]
        error = self.advapi.GetSecurityInfo(handle, 1, 5, *[ctypes.byref(x) for x in (owner, group, dacl, sacl, descriptor)])
        if error:
            raise PermissionError("directory security unavailable")
        try:
            entries = None
            if dacl.value:
                # ACL header: revision byte, spare byte, size WORD, count WORD.
                count = ctypes.c_uint16.from_address(dacl.value + 4).value
                if count > 1024:
                    raise PermissionError("DACL too large")
                entries = []
                for index in range(count):
                    ace = ctypes.c_void_p()
                    self._ok(self.advapi.GetAce(dacl, index, ctypes.byref(ace)))
                    kind = ctypes.c_ubyte.from_address(ace.value).value
                    flags = ctypes.c_ubyte.from_address(ace.value + 1).value
                    length = ctypes.c_uint16.from_address(ace.value + 2).value
                    if kind not in (0, 1) or length < 16:
                        raise PermissionError("unsupported DACL entry")
                    mask = ctypes.c_uint32.from_address(ace.value + 4).value
                    entries.append((kind, flags, mask, self._sid(ace.value + 8)))
            check_windows_acl(self._sid(owner), self.sid, entries, parent)
        finally:
            self.kernel.LocalFree(descriptor)

    def claim(self, parent, run_id):
        drive, tail = ntpath.splitdrive(parent)
        current = drive + "\\"
        self._open(current, not tail.strip("\\"))
        parts = tail.strip("\\").split("\\")
        for index, part in enumerate(parts):
            current = ntpath.join(current, part)
            self._open(current, index == len(parts)-1)
        descriptor = ctypes.c_void_p()
        self._ok(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "O:" + self.sid + "D:P(A;OICI;FA;;;" + self.sid + ")", 1, ctypes.byref(descriptor), None))
        class Attributes(ctypes.Structure):
            _fields_ = [("length", self.w.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", self.w.BOOL)]
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        self.path = ntpath.join(parent, run_id)
        try:
            self._ok(self.kernel.CreateDirectoryW(self.path, ctypes.byref(attributes)))
        finally:
            self.kernel.LocalFree(descriptor)
        self._open(self.path, True)

    def publish(self, temporary, final):
        temporary = ntpath.join(self.path, temporary)
        with open(temporary, "xb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        # MOVEFILE_WRITE_THROUGH, explicitly WITHOUT REPLACE_EXISTING.
        self._ok(self.kernel.MoveFileExW(temporary, ntpath.join(self.path, final), 8))

    def publish_data(self, final, data):
        temporary = ntpath.join(self.path, final + ".tmp")
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self._ok(self.kernel.MoveFileExW(temporary, ntpath.join(self.path, final), 8))

    def close(self):
        for handle in reversed(self.handles):
            self.kernel.CloseHandle(handle)


class PosixDirectories:
    def __init__(self):
        self.handles = []

    def claim(self, parent, run_id):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open("/", flags)
        self.handles.append(fd)
        parts = parent.strip("/").split("/")
        for index, part in enumerate(parts):
            fd = os.open(part, flags, dir_fd=fd)
            self.handles.append(fd)
            info = os.fstat(fd)
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise PermissionError("untrusted ancestor")
            if index == len(parts)-1 and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise PermissionError("private parent required")
        os.mkdir(run_id, 0o700, dir_fd=fd)
        self.fd = os.open(run_id, flags, dir_fd=fd)
        self.handles.append(self.fd)

    def publish(self, temporary, final):
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, final, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        os.fsync(self.fd)

    def publish_data(self, final, data):
        descriptor = os.open(final + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(final + ".tmp", final, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        os.fsync(self.fd)

    def close(self):
        for handle in reversed(self.handles):
            os.close(handle)


def run_wrapper(payload):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 required")
    if (os.name == "nt") != (payload["os_family"] == "windows"):
        raise RuntimeError("OS mismatch")
    guard = WindowsDirectories() if os.name == "nt" else PosixDirectories()
    try:
        guard.claim(payload["run_parent"], payload["run_id"])
        suffix = payload["run_id"] + "-" + payload["digest"]
        guard.publish("claimed.tmp", "claimed-v1-" + suffix)
        capture = bool(payload.get("capture_output"))
        if payload.get("mode") == "customize":
            code = apply_customize(payload)
        elif capture:
            completed = subprocess.run(
                [payload["program"], *payload["argv"]], shell=False,
                cwd=payload["working_directory"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
            code = completed.returncode
            stdout, stderr = completed.stdout or b"", completed.stderr or b""
            guard.publish_data(STDOUT_NAME, _bounded_b64(stdout))
            guard.publish_data(STDERR_NAME, _bounded_b64(stderr))
        else:
            completed = subprocess.run([payload["program"], *payload["argv"]], shell=False,
                                 cwd=payload["working_directory"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            code = completed.returncode
        if (payload["os_family"] == "windows" and not 0 <= code <= 4294967295) or (
                payload["os_family"] == "linux" and not -127 <= code <= 255):
            raise RuntimeError("invalid exit code")
        guard.publish("done.tmp", "done-v1-" + suffix + "-" + str(code))
    finally:
        guard.close()


def _run(argv, env=None):
    # Every external invocation is an argv list (shell=False); spec values are
    # data passed as argv elements or environment, never a shell string.
    completed = subprocess.run(argv, shell=False, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               close_fds=True)
    return completed.returncode


def apply_customize(payload):
    """Apply a validated declarative spec inside the Guest.

    A zero code means the fixed program reached the end; it does not prove the
    network has converged (DHCP lease, DNS propagation or reboot may follow).
    Submission and observed guest completion are reported separately upstream.
    """
    spec = payload["customize_spec"]
    family = payload["os_family"]
    code = 0
    hostname = spec.get("hostname")
    if hostname:
        code = _apply_hostname(hostname, family) or code
    adapter = spec["adapter"]
    iface = adapter.get("name")
    code = _apply_ipv4(iface, adapter["ipv4"], family) or code
    if adapter.get("dns_servers"):
        code = _apply_dns(iface, adapter["dns_servers"], family) or code
    return code


def _apply_hostname(hostname, family):
    if family == "windows":
        # Pass the name via environment, never interpolated into the command.
        env = dict(os.environ, VCENTER_NEW_NAME=hostname)
        return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "Rename-Computer -NewName $env:VCENTER_NEW_NAME -Force"], env=env)
    return _run(["hostnamectl", "set-hostname", hostname])


def _apply_ipv4(iface, ipv4, family):
    if iface is None:
        # MAC-based adapter resolution is a live-verification item; require an
        # explicit adapter name offline so no target interface is guessed.
        return 1
    if family == "windows":
        if ipv4["method"] == "dhcp":
            return _run(["netsh", "interface", "ipv4", "set", "address",
                         "name=" + iface, "source=dhcp"])
        argv = ["netsh", "interface", "ipv4", "set", "address",
                "name=" + iface, "static", ipv4["address"],
                str(ipv4["prefix"])]
        if ipv4.get("gateway"):
            argv.append(ipv4["gateway"])
        return _run(argv)
    if ipv4["method"] == "dhcp":
        return _run(["dhclient", iface]) or _run(["dhcpcd", iface])
    if _run(["ip", "addr", "flush", "dev", iface]) != 0:
        return 1
    cidr = ipv4["address"] + "/" + str(ipv4["prefix"])
    if _run(["ip", "addr", "add", cidr, "dev", iface]) != 0:
        return 1
    if ipv4.get("gateway"):
        _run(["ip", "route", "replace", "default", "via",
              ipv4["gateway"], "dev", iface])
    return 0


def _apply_dns(iface, servers, family):
    if family == "windows":
        code = 0
        for index, server in enumerate(servers):
            verb = "set" if index == 0 else "add"
            step = _run(["netsh", "interface", "ipv4", verb, "dnsservers",
                         "name=" + iface, "address=" + server,
                         "index=" + str(index + 1)])
            code = step or code
        return code
    # Linux resolv.conf is the dependency-free baseline; NetworkManager/
    # netplan integration per distro is a live-verification item.
    try:
        with open("/etc/resolv.conf", "w", encoding="utf-8") as handle:
            for server in servers:
                handle.write("nameserver " + server + "\n")
        return 0
    except OSError:
        return 1


def _bounded_b64(raw):
    truncated = raw[:MAX_OUTPUT_BYTES]
    return _base64.b64encode(truncated)
