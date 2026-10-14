"""Offline Win32 boundary tests; these do not claim Windows execution coverage."""
import ctypes
from ctypes import wintypes as w
import unittest
from unittest.mock import patch

from vcenter_aiops.providers.vsphere.guest_wrapper import WindowsDirectories, check_windows_acl


CURRENT = "S-1-5-21-123-456-789-1001"


class NativeFunction:
    def __init__(self, function):
        self.function = function
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.function(*args)


class Win32Boundary:
    def __init__(self):
        self.buffers = []
        self.sids = {100: CURRENT, 200: CURRENT}
        self.attributes = 0x10
        self.null_dacl = False
        self.entries = [(0, 0, 0x1F01FF, CURRENT)]
        self.next_handle = 1000
        self.paths = []
        self.security_error = 0
        methods = {
            "GetCurrentProcess": lambda: 900,
            "CloseHandle": lambda handle: True,
            "LocalFree": lambda pointer: None,
            "OpenProcessToken": self.open_token,
            "GetTokenInformation": self.token_info,
            "ConvertSidToStringSidW": self.convert_sid,
            "CreateFileW": self.create_file,
            "GetFileInformationByHandleEx": self.file_info,
            "GetSecurityInfo": self.security_info,
            "GetAce": self.get_ace,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": self.convert_descriptor,
            "CreateDirectoryW": lambda path, attributes: True,
            "MoveFileExW": lambda source, destination, flags: True,
        }
        for name, function in methods.items():
            setattr(self, name, NativeFunction(function))

    @staticmethod
    def set_pointer(destination, value, kind=ctypes.c_void_p):
        ctypes.cast(destination, ctypes.POINTER(kind))[0] = value

    def open_token(self, process, rights, destination):
        self.set_pointer(destination, 901)
        return True

    def token_info(self, token, kind, buffer, size, needed):
        self.set_pointer(needed, 32, w.DWORD)
        if buffer is None:
            return False
        ctypes.c_void_p.from_buffer(buffer).value = 100
        return True

    def convert_sid(self, pointer, destination):
        address = pointer.value if isinstance(pointer, ctypes.c_void_p) else pointer
        value = ctypes.create_unicode_buffer(self.sids[address])
        self.buffers.append(value)
        self.set_pointer(destination, ctypes.addressof(value))
        return True

    def create_file(self, path, *args):
        self.paths.append(path)
        self.next_handle += 1
        return self.next_handle

    def file_info(self, handle, kind, buffer, length):
        buffer[0] = self.attributes
        return True

    def security_info(self, handle, kind, flags, owner, group, dacl, sacl, descriptor):
        if self.security_error:
            return self.security_error
        self.set_pointer(owner, 200)
        self.set_pointer(descriptor, 300)
        if self.null_dacl:
            self.set_pointer(dacl, None)
            return 0
        acl = ctypes.create_string_buffer(8)
        ctypes.c_uint16.from_buffer(acl, 4).value = len(self.entries)
        self.buffers.append(acl)
        self.set_pointer(dacl, ctypes.addressof(acl))
        self.aces = []
        for ace_type, flags, mask, sid in self.entries:
            ace = ctypes.create_string_buffer(32)
            ctypes.c_ubyte.from_buffer(ace, 0).value = ace_type
            ctypes.c_ubyte.from_buffer(ace, 1).value = flags
            ctypes.c_uint16.from_buffer(ace, 2).value = 32
            ctypes.c_uint32.from_buffer(ace, 4).value = mask
            self.sids[ctypes.addressof(ace) + 8] = sid
            self.aces.append(ace)
            self.buffers.append(ace)
        return 0

    def get_ace(self, dacl, index, destination):
        self.set_pointer(destination, ctypes.addressof(self.aces[index]))
        return True

    def convert_descriptor(self, sddl, revision, destination, length):
        self.set_pointer(destination, 500)
        return True


class WindowsSecurityTests(unittest.TestCase):
    def guard(self, boundary):
        with patch.object(ctypes, "WinDLL", return_value=boundary, create=True):
            return WindowsDirectories()

    def test_current_system_admin_allowed_but_foreign_writers_and_null_acl_rejected(self):
        for sid in (CURRENT, "S-1-5-18", "S-1-5-32-544"):
            check_windows_acl(CURRENT, CURRENT, [(0, 0, 0x1F01FF, sid)], True)
        for parent, mask in ((True, 2), (True, 4), (True, 0x40000000), (False, 0x40), (False, 0x10000), (False, 0x40000), (False, 0x80000)):
            with self.subTest(parent=parent, mask=mask):
                with self.assertRaises(PermissionError):
                    check_windows_acl(CURRENT, CURRENT, [(0, 0, mask, "S-1-1-0")], parent)
        for owner, entries in ((CURRENT, None), ("S-1-1-0", []), (CURRENT, [(5, 0, 0, CURRENT)])):
            with self.assertRaises(PermissionError):
                check_windows_acl(owner, CURRENT, entries, True)

    def test_real_security_adapter_decodes_aces_and_rejects_cross_user_write(self):
        for defect in ("foreign", "null", "unsupported", "api_failure"):
            with self.subTest(defect=defect):
                api = Win32Boundary()
                if defect == "foreign": api.entries = [(0, 0, 0x1F01FF, "S-1-1-0")]
                elif defect == "null": api.null_dacl = True
                elif defect == "unsupported": api.entries = [(5, 0, 0x1F01FF, CURRENT)]
                else: api.security_error = 5
                guard = self.guard(api)
                try:
                    with self.assertRaises(PermissionError):
                        guard.claim(r"C:\PrivateRuns", "a"*32)
                finally:
                    guard.close()
                self.assertEqual(api.CreateDirectoryW.calls, [])
                self.assertIn((1001,), api.CloseHandle.calls)

    def test_pins_each_ancestor_rejects_reparse_and_creates_protected_acl(self):
        api = Win32Boundary()
        guard = self.guard(api)
        try:
            guard.claim(r"C:\PrivateRuns", "a"*32)
            self.assertEqual(api.paths, ["C:\\", r"C:\PrivateRuns", "C:\\PrivateRuns\\" + "a"*32])
            for args in api.CreateFileW.calls:
                self.assertEqual(args[2], 3)  # No FILE_SHARE_DELETE.
                self.assertEqual(args[5], 0x02200000)  # Reparse itself, no traversal.
            sddl = api.ConvertStringSecurityDescriptorToSecurityDescriptorW.calls[0][0]
            self.assertEqual(sddl, "O:" + CURRENT + "D:P(A;OICI;FA;;;" + CURRENT + ")")
            self.assertEqual(api.CreateFileW.restype, w.HANDLE)
            self.assertEqual(len(api.GetSecurityInfo.argtypes), 8)
        finally:
            guard.close()
        self.assertEqual(api.CloseHandle.calls[-3:], [(1003,), (1002,), (1001,)])
        api = Win32Boundary()
        api.attributes = 0x410
        guard = self.guard(api)
        try:
            with self.assertRaises(PermissionError):
                guard.claim(r"C:\PrivateRuns", "a"*32)
            self.assertEqual(api.CreateDirectoryW.calls, [])
        finally:
            guard.close()

    def test_native_create_collision_does_not_open_existing_run(self):
        api = Win32Boundary()
        api.CreateDirectoryW.function = lambda *args: False
        guard = self.guard(api)
        try:
            with self.assertRaises(PermissionError):
                guard.claim(r"C:\PrivateRuns", "a"*32)
            self.assertEqual(len(api.CreateFileW.calls), 2)
        finally:
            guard.close()
