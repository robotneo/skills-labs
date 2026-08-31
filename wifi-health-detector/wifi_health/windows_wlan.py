from __future__ import absolute_import

import os


def channel_width_from_ies(blob):
    """Return the current 20/40/80/160 MHz width from 802.11 operation IEs."""
    widths = []
    offset = 0
    while offset + 2 <= len(blob):
        element_id = blob[offset]
        length = blob[offset + 1]
        data = blob[offset + 2:offset + 2 + length]
        if len(data) != length:
            break
        if element_id == 61 and length >= 2:  # HT Operation
            secondary_offset = data[1] & 0x03
            supports_40 = bool(data[1] & 0x04)
            widths.append(40 if supports_40 and secondary_offset in (1, 3) else 20)
        elif element_id == 192 and length >= 1:  # VHT Operation
            widths.append({1: 80, 2: 160, 3: 160}.get(data[0], 20))
        offset += 2 + length
    return max(widths) if widths else None


def current_channel_width(ssid=None, bssid=None):
    """Query the active Windows BSS and derive its width from beacon IEs."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class DOT11_SSID(ctypes.Structure):
        _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]

    class WLAN_RATE_SET(ctypes.Structure):
        _fields_ = [("uRateSetLength", wintypes.ULONG), ("usRateSet", wintypes.USHORT * 126)]

    class WLAN_INTERFACE_INFO(ctypes.Structure):
        _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", wintypes.WCHAR * 256), ("isState", wintypes.DWORD)]

    class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
        _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]

    class WLAN_BSS_ENTRY(ctypes.Structure):
        _fields_ = [
            ("dot11Ssid", DOT11_SSID), ("uPhyId", wintypes.ULONG),
            ("dot11Bssid", ctypes.c_ubyte * 6), ("dot11BssType", wintypes.DWORD),
            ("dot11BssPhyType", wintypes.DWORD), ("lRssi", wintypes.LONG),
            ("uLinkQuality", wintypes.ULONG), ("bInRegDomain", ctypes.c_ubyte),
            ("usBeaconPeriod", wintypes.USHORT), ("ullTimestamp", ctypes.c_ulonglong),
            ("ullHostTimestamp", ctypes.c_ulonglong), ("usCapabilityInformation", wintypes.USHORT),
            ("ulChCenterFrequency", wintypes.ULONG), ("wlanRateSet", WLAN_RATE_SET),
            ("ulIeOffset", wintypes.ULONG), ("ulIeSize", wintypes.ULONG),
        ]

    class WLAN_BSS_LIST(ctypes.Structure):
        _fields_ = [("dwTotalSize", wintypes.DWORD), ("dwNumberOfItems", wintypes.DWORD), ("wlanBssEntries", WLAN_BSS_ENTRY * 1)]

    wlan = ctypes.WinDLL("wlanapi")
    handle = wintypes.HANDLE()
    negotiated = wintypes.DWORD()
    interfaces_ptr = ctypes.c_void_p()
    if wlan.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle)) != 0:
        return None
    try:
        if wlan.WlanEnumInterfaces(handle, None, ctypes.byref(interfaces_ptr)) != 0:
            return None
        try:
            interface_list = ctypes.cast(interfaces_ptr, ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)).contents
            interface_base = interfaces_ptr.value + WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
            candidates = []
            wanted_bssid = _normalize_bssid(bssid)
            for index in range(interface_list.dwNumberOfItems):
                interface = WLAN_INTERFACE_INFO.from_address(interface_base + index * ctypes.sizeof(WLAN_INTERFACE_INFO))
                bss_ptr = ctypes.c_void_p()
                result = wlan.WlanGetNetworkBssList(handle, ctypes.byref(interface.InterfaceGuid), None, 3, False, None, ctypes.byref(bss_ptr))
                if result != 0:
                    continue
                try:
                    bss_list = ctypes.cast(bss_ptr, ctypes.POINTER(WLAN_BSS_LIST)).contents
                    entry_base = bss_ptr.value + WLAN_BSS_LIST.wlanBssEntries.offset
                    for entry_index in range(bss_list.dwNumberOfItems):
                        entry = WLAN_BSS_ENTRY.from_address(entry_base + entry_index * ctypes.sizeof(WLAN_BSS_ENTRY))
                        entry_ssid = bytes(entry.dot11Ssid.ucSSID[:entry.dot11Ssid.uSSIDLength]).decode("utf-8", "replace")
                        entry_bssid = ":".join("%02x" % value for value in entry.dot11Bssid)
                        if wanted_bssid and entry_bssid != wanted_bssid:
                            continue
                        if not wanted_bssid and ssid and entry_ssid != ssid:
                            continue
                        ies = ctypes.string_at(ctypes.addressof(entry) + entry.ulIeOffset, entry.ulIeSize)
                        width = channel_width_from_ies(ies)
                        if width:
                            candidates.append((entry.lRssi, width))
                finally:
                    wlan.WlanFreeMemory(bss_ptr)
            return max(candidates)[1] if candidates else None
        finally:
            wlan.WlanFreeMemory(interfaces_ptr)
    finally:
        wlan.WlanCloseHandle(handle, None)


def _normalize_bssid(value):
    if not value:
        return ""
    return str(value).lower().replace("-", ":")
