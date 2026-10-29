"""WlanAPI 原生探测：当前 Wi-Fi 连接与附近网络扫描。

对应 MS Learn 的 WlanQueryInterface / WlanGetAvailableNetworkList /
WlanGetNetworkBssList。所有公开函数失败返回 None，由 wifi_check 回退 netsh。
"""

import ctypes
import sys
from ctypes import wintypes

from .winapi_common import GUID, WlanSession, Win32Error, native_enabled

IS_WINDOWS = sys.platform == "win32"

# WLAN_INTF_OPCODE
OPCODE_CURRENT_CONNECTION = 7
OPCODE_CHANNEL_NUMBER = 8

WLAN_INTERFACE_STATE_CONNECTED = 1
# WLAN_AVAILABLE_NETWORK dwFlags
FLAG_CONNECTED = 0x1

DOT11_BSS_TYPE_ANY = 3


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", wintypes.WCHAR * 256),
        ("isState", wintypes.DWORD),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", wintypes.DWORD),
        ("ucSSID", ctypes.c_ubyte * 32),
    ]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", wintypes.DWORD),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11PhyType", wintypes.DWORD),
        ("uDot11PhyIndex", wintypes.DWORD),
        ("wlanSignalQuality", wintypes.DWORD),
        ("ulRxRate", wintypes.DWORD),
        ("ulTxRate", wintypes.DWORD),
    ]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", wintypes.BOOL),
        ("bOneXEnabled", wintypes.BOOL),
        ("dot11AuthAlgorithm", wintypes.DWORD),
        ("dot11CipherAlgorithm", wintypes.DWORD),
    ]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", wintypes.DWORD),
        ("wlanConnectionMode", wintypes.DWORD),
        ("strProfileName", wintypes.WCHAR * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
    ]


class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
    _fields_ = [
        ("strProfileName", wintypes.WCHAR * 256),
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", wintypes.DWORD),
        ("uNumberOfBssids", wintypes.DWORD),
        ("bNetworkConnectable", wintypes.BOOL),
        ("wlanNotConnectableReason", wintypes.DWORD),
        ("uNumberOfPhyTypes", wintypes.DWORD),
        ("dot11PhyTypes", wintypes.DWORD * 8),
        ("bMorePhyTypes", wintypes.BOOL),
        ("wlanSignalQuality", wintypes.DWORD),
        ("bSecurityEnabled", wintypes.BOOL),
        ("dot11DefaultAuthAlgorithm", wintypes.DWORD),
        ("dot11DefaultCipherAlgorithm", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
    ]


class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("Network", WLAN_AVAILABLE_NETWORK * 1),
    ]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", wintypes.DWORD),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11BssType", wintypes.DWORD),
        ("dot11BssPhyType", wintypes.DWORD),
        ("lRssi", ctypes.c_long),
        ("uLinkQuality", wintypes.DWORD),
        ("bInRegDomain", ctypes.c_ubyte),
        ("usBeaconPeriod", wintypes.WORD),
        ("ullTimestamp", ctypes.c_ulonglong),
        ("ullHostTimestamp", ctypes.c_ulonglong),
        ("usCapabilityInformation", wintypes.WORD),
        ("ulChCenterFrequency", wintypes.DWORD),   # kHz
        ("wlanRateSetLength", wintypes.DWORD),
        ("wlanRateSet", wintypes.WORD * 126),
        ("ulIeOffset", wintypes.DWORD),
        ("ulIeSize", wintypes.DWORD),
    ]


class WLAN_BSS_LIST(ctypes.Structure):
    _fields_ = [
        ("dwTotalSize", wintypes.DWORD),
        ("dwNumberOfItems", wintypes.DWORD),
        ("wlanBssEntries", WLAN_BSS_ENTRY * 1),
    ]


if IS_WINDOWS:
    # 结构体一旦错位，后续所有字段都是脏数据，启动即暴露比运行时乱码好
    assert ctypes.sizeof(WLAN_INTERFACE_INFO) == 532
    assert ctypes.sizeof(WLAN_CONNECTION_ATTRIBUTES) == 604
    assert ctypes.sizeof(WLAN_AVAILABLE_NETWORK) == 628
    assert ctypes.sizeof(WLAN_BSS_ENTRY) == 360

_AUTH_NAMES = {
    1: "开放",
    2: "WEP共享",
    3: "WPA",
    4: "WPA-PSK",
    5: "WPA-None",
    6: "WPA2",
    7: "WPA2-PSK",
    8: "WPA3",
    9: "WPA3-SAE",
    10: "OWE",
    11: "WPA3-ENT-192",
    12: "WPA3-SAE-192",
}

_PHY_NAMES = {
    4: "802.11a",
    5: "802.11b",
    6: "802.11g",
    7: "802.11n",
    8: "802.11ac",
    9: "802.11ad",
    10: "802.11ax",
    11: "802.11be",
}


def channel_from_frequency(mhz):
    """频率（MHz）换算信道号；未知频段返回 None。"""
    try:
        mhz = int(mhz)
    except (TypeError, ValueError):
        return None
    if 2400 <= mhz < 2500:
        return 14 if mhz == 2484 else int((mhz - 2407) / 5)
    if 4900 <= mhz < 5900:
        return int(mhz / 5 - 1000)
    if 5925 <= mhz <= 7125:
        return int((mhz - 5950) / 5)
    return None


def ssid_to_str(ssid):
    """DOT11_SSID → 字符串；空/隐藏 SSID 返回空串。"""
    length = min(int(ssid.uSSIDLength), 32)
    raw = bytes(ssid.ucSSID[:length])
    if not raw or not raw.strip(b"\x00"):
        return ""
    return raw.decode("utf-8", errors="replace").strip("\x00").strip()


def mac_to_str(raw, length=6):
    return ":".join(f"{raw[i]:02x}" for i in range(min(length, 6)))


def phy_name(phy_type):
    return _PHY_NAMES.get(int(phy_type), "")


def auth_name(auth_type):
    return _AUTH_NAMES.get(int(auth_type), "")


def _check(func, code):
    if code != 0:
        raise Win32Error(func, code)
    return code


def _enum_interfaces(session):
    """返回 [(GUID, 描述, 状态)]，已复制出 API 内存，可安全释放。"""
    ptr = ctypes.c_void_p()
    ret = session.dll.WlanEnumInterfaces(
        session.handle, None, ctypes.byref(ptr))
    _check("WlanEnumInterfaces", ret)
    try:
        info_list = ctypes.cast(
            ptr, ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)).contents
        items_ptr = ctypes.cast(
            ctypes.byref(info_list.InterfaceInfo[0]),
            ctypes.POINTER(WLAN_INTERFACE_INFO))
        items = []
        for i in range(info_list.dwNumberOfItems):
            info = items_ptr[i]
            guid = GUID.from_buffer_copy(info.InterfaceGuid)
            items.append((guid, info.strInterfaceDescription, int(info.isState)))
        return items
    finally:
        session.free(ptr)


def _query_channel(session, guid):
    try:
        data = ctypes.c_void_p()
        size = wintypes.DWORD()
        ret = session.dll.WlanQueryInterface(
            session.handle, ctypes.byref(guid), OPCODE_CHANNEL_NUMBER,
            None, ctypes.byref(size), ctypes.byref(data), None)
        if ret != 0 or not data:
            return None
        try:
            return int(ctypes.cast(data, ctypes.POINTER(wintypes.ULONG)).contents.value)
        finally:
            session.free(data)
    except Exception:
        return None


def _read_available(session, guid):
    ptr = ctypes.c_void_p()
    ret = session.dll.WlanGetAvailableNetworkList(
        session.handle, ctypes.byref(guid), 2, None, ctypes.byref(ptr))
    if ret != 0:
        raise Win32Error("WlanGetAvailableNetworkList", ret)
    try:
        net_list = ctypes.cast(
            ptr, ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST)).contents
        net_ptr = ctypes.cast(
            ctypes.byref(net_list.Network[0]),
            ctypes.POINTER(WLAN_AVAILABLE_NETWORK))
        networks = []
        for i in range(net_list.dwNumberOfItems):
            net = net_ptr[i]
            ssid = ssid_to_str(net.dot11Ssid)
            if not ssid:
                continue
            networks.append({
                "ssid": ssid,
                "signal": int(net.wlanSignalQuality),
                "auth": auth_name(net.dot11DefaultAuthAlgorithm),
                "connected": bool(net.dwFlags & FLAG_CONNECTED),
            })
        return networks
    finally:
        session.free(ptr)


def _read_bss(session, guid):
    ptr = ctypes.c_void_p()
    ret = session.dll.WlanGetNetworkBssList(
        session.handle, ctypes.byref(guid), None, DOT11_BSS_TYPE_ANY,
        False, None, ctypes.byref(ptr))
    if ret != 0:
        raise Win32Error("WlanGetNetworkBssList", ret)
    try:
        bss_list = ctypes.cast(ptr, ctypes.POINTER(WLAN_BSS_LIST)).contents
        bss_ptr = ctypes.cast(
            ctypes.byref(bss_list.wlanBssEntries[0]),
            ctypes.POINTER(WLAN_BSS_ENTRY))
        entries = []
        for i in range(bss_list.dwNumberOfItems):
            bss = bss_ptr[i]
            ssid = ssid_to_str(bss.dot11Ssid)
            if not ssid:
                continue
            entries.append({
                "ssid": ssid,
                "bssid": mac_to_str(bss.dot11Bssid),
                "signal": int(bss.uLinkQuality),
                "rssi": int(bss.lRssi),
                "freq": int(bss.ulChCenterFrequency / 1000.0),
                "channel": channel_from_frequency(bss.ulChCenterFrequency / 1000.0),
                "phy": phy_name(bss.dot11BssPhyType),
            })
        return entries
    finally:
        session.free(ptr)


def _pick_interfaces(interfaces):
    """优先当前连接的接口，其次任意无线接口。"""
    for guid, desc, state in interfaces:
        if state == WLAN_INTERFACE_STATE_CONNECTED:
            return guid, desc, state
    if interfaces:
        return interfaces[0]
    return None, "", 0


def _query_connection(session, guid):
    data = ctypes.c_void_p()
    size = wintypes.DWORD()
    ret = session.dll.WlanQueryInterface(
        session.handle, ctypes.byref(guid), OPCODE_CURRENT_CONNECTION,
        None, ctypes.byref(size), ctypes.byref(data), None)
    if ret != 0:
        raise Win32Error("WlanQueryInterface", ret)
    try:
        conn = ctypes.cast(
            data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
        attr = conn.wlanAssociationAttributes
        return {
            "connected": int(conn.isState) == WLAN_INTERFACE_STATE_CONNECTED,
            "ssid": ssid_to_str(attr.dot11Ssid),
            "signal_strength": int(attr.wlanSignalQuality),
            "bssid": mac_to_str(attr.dot11Bssid),
            "rx_rate": round(int(attr.ulRxRate) / 1000.0, 1),
            "tx_rate": round(int(attr.ulTxRate) / 1000.0, 1),
            "radio_type": phy_name(attr.dot11PhyType),
        }
    finally:
        session.free(data)


def get_connection():
    """当前 Wi-Fi 连接信息；API 不可用返回 None，未连接返回 connected=False。"""
    if not native_enabled():
        return None
    try:
        with WlanSession() as session:
            guid, _desc, state = _pick_interfaces(_enum_interfaces(session))
            if guid is None:
                return {"connected": False, "no_interface": True}
            if state != WLAN_INTERFACE_STATE_CONNECTED:
                return {"connected": False}
            info = _query_connection(session, guid)
            if info.get("connected"):
                channel = _query_channel(session, guid)
                if channel is None:
                    try:
                        for bss in _read_bss(session, guid):
                            if bss["bssid"] == info.get("bssid"):
                                channel = bss["channel"]
                                break
                    except (Win32Error, OSError):
                        channel = None
                if channel is not None:
                    info["channel"] = channel
            return info
    except (OSError, Win32Error, AttributeError, ValueError):
        return None


def _merge_networks(available, bss_entries):
    """把可用网络列表（信号/认证/连接标记）与 BSS 列表（信道）合并。"""
    best_bss = {}
    for entry in bss_entries:
        cur = best_bss.get(entry["ssid"])
        if cur is None or entry["signal"] > cur["signal"]:
            best_bss[entry["ssid"]] = entry

    merged = []
    by_ssid = {}
    order = []
    for net in available:
        cur = by_ssid.get(net["ssid"])
        if cur is None:
            cur = dict(net)
            by_ssid[net["ssid"]] = cur
            order.append(net["ssid"])
        else:
            cur["signal"] = max(cur["signal"], net["signal"])
            cur["connected"] = cur["connected"] or net["connected"]
            if not cur["auth"]:
                cur["auth"] = net["auth"]
    for ssid in order:
        net = by_ssid[ssid]
        bss = best_bss.get(ssid, {})
        merged.append({
            "ssid": ssid,
            "signal": net["signal"] or bss.get("signal", 0),
            "channel": bss.get("channel"),
            "freq": bss.get("freq"),
            "auth": net["auth"],
            "connected": net["connected"],
        })
    for ssid, bss in best_bss.items():
        if ssid in by_ssid:
            continue
        merged.append({
            "ssid": ssid,
            "signal": bss["signal"],
            "channel": bss.get("channel"),
            "freq": bss.get("freq"),
            "auth": "",
            "connected": False,
        })
    merged.sort(key=lambda n: (not n["connected"], -n["signal"]))
    return merged


def scan_networks():
    """扫描附近 Wi-Fi；返回 [{ssid,signal,channel,auth,connected}]，失败返回 None。"""
    if not native_enabled():
        return None
    try:
        with WlanSession() as session:
            interfaces = _enum_interfaces(session)
            if not interfaces:
                return []
            guid, _desc, _state = _pick_interfaces(interfaces)
            available, bss_entries = [], []
            errors = 0
            try:
                available = _read_available(session, guid)
            except (Win32Error, OSError):
                errors += 1
            try:
                bss_entries = _read_bss(session, guid)
            except (Win32Error, OSError):
                errors += 1
            if errors == 2:
                raise Win32Error("WlanGetAvailableNetworkList", -1)
            return _merge_networks(available, bss_entries)
    except (OSError, Win32Error, AttributeError, ValueError):
        return None
