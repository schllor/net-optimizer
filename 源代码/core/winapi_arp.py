"""IP Helper 原生邻居表与 ARP 探测：取代解析 `arp -a` 文本。

GetIpNetTable 只含 IPv4 邻居（局域网扫描正需要这一点），结构比
GetIpNetTable2 小得多、跨系统版本稳定；SendARP 用于确认设备是否真的在线。
所有公开函数失败返回 None，由 lan_scan 回退 arp -a。
"""

import ctypes
import socket
import struct
import sys
import threading
import time
from ctypes import wintypes

from .winapi_common import load_dll, native_enabled

IS_WINDOWS = sys.platform == "win32"

ERROR_INSUFFICIENT_BUFFER = 122
MIB_IPNET_TYPE_DYNAMIC = 3
MIB_IPNET_TYPE_STATIC = 4


class MIB_IPNETROW(ctypes.Structure):
    _fields_ = [
        ("dwIndex", wintypes.DWORD),
        ("dwPhysAddrLen", wintypes.DWORD),
        ("bPhysAddr", ctypes.c_ubyte * 8),
        ("dwAddr", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
    ]


class MIB_IPNETTABLE(ctypes.Structure):
    _fields_ = [
        ("dwNumEntries", wintypes.DWORD),
        ("table", MIB_IPNETROW * 1),
    ]


if IS_WINDOWS:
    assert ctypes.sizeof(MIB_IPNETROW) == 24


def ip_from_dword(value):
    """MIB_IPNETROW.dwAddr 为网络字节序，转点分十进制。"""
    return socket.inet_ntoa(struct.pack("<L", int(value)))


def mac_from_bytes(raw, length):
    length = min(int(length or 0), 6)
    if length <= 0:
        return ""
    return ":".join(f"{raw[i]:02x}" for i in range(length))


def parse_neighbor_rows(rows):
    """把 MIB_IPNETROW 列表转成 [{ip,mac,ifindex,state}]（纯函数，便于离线测试）。"""
    devices = []
    for row in rows:
        if int(row.dwType) not in (MIB_IPNET_TYPE_DYNAMIC, MIB_IPNET_TYPE_STATIC):
            continue
        mac = mac_from_bytes(row.bPhysAddr, row.dwPhysAddrLen)
        if not mac or mac == "00:00:00:00:00:00":
            continue
        devices.append({
            "ip": ip_from_dword(row.dwAddr),
            "mac": mac,
            "ifindex": int(row.dwIndex),
            "state": "static" if int(row.dwType) == MIB_IPNET_TYPE_STATIC else "dynamic",
        })
    return devices


def get_neighbors():
    """返回邻居表 [{ip,mac,ifindex,state}]；API 不可用返回 None。"""
    if not native_enabled():
        return None
    try:
        dll = load_dll("iphlpapi")
        size = wintypes.ULONG(0)
        ret = dll.GetIpNetTable(None, ctypes.byref(size), True)
        if ret not in (0, ERROR_INSUFFICIENT_BUFFER) or size.value == 0:
            return None
        for _ in range(2):
            buf = ctypes.create_string_buffer(size.value)
            table = ctypes.cast(buf, ctypes.POINTER(MIB_IPNETTABLE))
            ret = dll.GetIpNetTable(table, ctypes.byref(size), True)
            if ret == ERROR_INSUFFICIENT_BUFFER:
                continue
            if ret != 0:
                return None
            count = table.contents.dwNumEntries
            row_ptr = ctypes.cast(
                ctypes.byref(table.contents.table[0]),
                ctypes.POINTER(MIB_IPNETROW))
            rows = [MIB_IPNETROW.from_buffer_copy(row_ptr[i])
                    for i in range(count)]
            return parse_neighbor_rows(rows)
        return None
    except (OSError, AttributeError, ValueError):
        return None


def send_arp(ip):
    """向指定 IP 发送 ARP 请求；有应答返回 MAC，否则 None。"""
    try:
        dest = struct.unpack("<L", socket.inet_aton(ip))[0]
        dll = load_dll("iphlpapi")
        mac = (ctypes.c_ubyte * 8)()
        length = wintypes.ULONG(8)
        ret = dll.SendARP(dest, 0, mac, ctypes.byref(length))
        if ret != 0 or length.value <= 0:
            return None
        return mac_from_bytes(mac, length.value)
    except (OSError, AttributeError, ValueError):
        return None


def probe_online(ips, timeout=2.0, cancel=None):
    """并发 SendARP 探测，返回 {ip: mac}；到截止时间返回已拿到的部分结果。

    使用守护线程而非线程池：后者在解释器退出时会 join，弱网下可能拖慢关闭。
    """
    targets = []
    for ip in ips or []:
        if ip and ip not in targets:
            targets.append(ip)
    if not targets:
        return {}
    if cancel is not None and cancel.is_set():
        return {}

    results = {}
    lock = threading.Lock()
    cursor = {"index": 0}
    cursor_lock = threading.Lock()
    stopped = threading.Event()

    def worker():
        while not stopped.is_set():
            with cursor_lock:
                idx = cursor["index"]
                if idx >= len(targets):
                    return
                cursor["index"] = idx + 1
            ip = targets[idx]
            mac = send_arp(ip)
            if mac:
                with lock:
                    results[ip] = mac

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(min(8, len(targets)))]
    for t in threads:
        t.start()

    deadline = time.monotonic() + max(0.2, timeout)
    for t in threads:
        while t.is_alive():
            if cancel is not None and cancel.is_set():
                stopped.set()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stopped.set()
                break
            t.join(min(0.05, remaining))
        if stopped.is_set():
            break

    with lock:
        return dict(results)
