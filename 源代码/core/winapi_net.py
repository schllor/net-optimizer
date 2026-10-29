"""IP Helper 原生 DNS 列表：GetAdaptersAddresses 遍历活动网卡的 DNS 服务器。

相比解析 `ipconfig /all` 的中英文标签，原生接口不受系统语言与输出格式影响。
失败返回 None，由调用方回退文本解析。
"""

import ctypes
import socket
import sys
from ctypes import wintypes

from .winapi_common import load_dll, native_enabled

IS_WINDOWS = sys.platform == "win32"

AF_INET = 2
AF_INET6 = 23
AF_UNSPEC = 0
ERROR_BUFFER_OVERFLOW = 111
IF_OPER_STATUS_UP = 1
IF_TYPE_SOFTWARE_LOOPBACK = 24
GAA_FLAG_SKIP_ANYCAST = 0x2
GAA_FLAG_SKIP_MULTICAST = 0x4
GAA_FLAG_SKIP_DNS_SUFFIX = 0x100


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("lpSockaddr", ctypes.c_void_p),
        ("iSockaddrLength", ctypes.c_int),
    ]


class IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("Reserved", wintypes.DWORD),
        ("Next", ctypes.c_void_p),
        ("Address", SOCKET_ADDRESS),
    ]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG),
    ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.c_void_p),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.c_void_p),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.ULONG),
    ("Flags", wintypes.ULONG),
    ("Mtu", wintypes.ULONG),
    ("IfType", wintypes.ULONG),
    ("OperStatus", ctypes.c_int),
    ("Ipv6IfIndex", wintypes.DWORD),
    ("ZoneIndices", wintypes.DWORD * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_ulonglong),
    ("ReceiveLinkSpeed", ctypes.c_ulonglong),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.c_void_p),
    ("Ipv4Metric", wintypes.ULONG),
    ("Ipv6Metric", wintypes.ULONG),
    ("Luid", ctypes.c_ulonglong),
    ("Dhcpv4Server", SOCKET_ADDRESS),
    ("CompartmentId", wintypes.ULONG),
    ("NetworkGuid", ctypes.c_ubyte * 16),
    ("ConnectionType", ctypes.c_int),
    ("TunnelType", ctypes.c_int),
    ("Dhcpv6Server", SOCKET_ADDRESS),
    ("Dhcpv6ClientDuid", ctypes.c_ubyte * 130),
    ("Dhcpv6ClientDuidLength", wintypes.ULONG),
    ("Dhcpv6Iaid", wintypes.ULONG),
    ("FirstDnsSuffix", ctypes.c_void_p),
]

if IS_WINDOWS:
    # x64 下该结构固定 448 字节；32 位系统长度不同，不做断言
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(IP_ADAPTER_ADDRESSES) == 448


def _sockaddr_to_ip(address):
    """SOCKET_ADDRESS → IPv4/IPv6 字面量；无法识别返回 None。"""
    ptr = address.lpSockaddr
    if not ptr:
        return None
    raw = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte))
    family = ctypes.cast(ptr, ctypes.POINTER(wintypes.USHORT)).contents.value
    if family == AF_INET and address.iSockaddrLength >= 8:
        packed = bytes(raw[4:8])
        return socket.inet_ntop(socket.AF_INET, packed)
    if family == AF_INET6 and address.iSockaddrLength >= 24:
        packed = bytes(raw[8:24])
        return socket.inet_ntop(socket.AF_INET6, packed)
    return None


def get_dns_servers():
    """返回活动网卡配置的 DNS 列表（去重保序）；失败返回 None。"""
    if not native_enabled():
        return None
    try:
        dll = load_dll("iphlpapi")
        size = wintypes.ULONG(15 * 1024)
        flags = (GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST
                 | GAA_FLAG_SKIP_DNS_SUFFIX)
        for _ in range(3):
            buf = ctypes.create_string_buffer(size.value)
            ret = dll.GetAdaptersAddresses(
                AF_UNSPEC, flags, None, buf, ctypes.byref(size))
            if ret == ERROR_BUFFER_OVERFLOW:
                continue
            if ret != 0:
                return None
            return _parse_adapters(buf)
        return None
    except (OSError, AttributeError, ValueError):
        return None


def _is_noise_dns(ip):
    """过滤回环与已废弃的站点本地/链路本地 IPv6（常见于虚拟网卡）。"""
    lower = ip.lower()
    return (ip.startswith("127.") or lower == "::1"
            or lower.startswith(("fe80:", "fec0:")))


def _parse_adapters(buffer):
    adapters = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    seen = []
    adapter = adapters
    while adapter:
        node = adapter.contents
        if (node.OperStatus == IF_OPER_STATUS_UP
                and node.IfType != IF_TYPE_SOFTWARE_LOOPBACK):
            dns_ptr = node.FirstDnsServerAddress
            while dns_ptr:
                entry = ctypes.cast(
                    dns_ptr,
                    ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)).contents
                ip = _sockaddr_to_ip(entry.Address)
                if ip and ip not in seen and not _is_noise_dns(ip):
                    seen.append(ip)
                dns_ptr = entry.Next
        adapter = ctypes.cast(
            node.Next, ctypes.POINTER(IP_ADAPTER_ADDRESSES)) if node.Next else None
    return seen
