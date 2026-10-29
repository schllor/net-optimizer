"""
实时流量监控模块 - 采集所有网卡累计字节，计算实时上行/下行速率。
架构（借鉴 NetSpeedTray）：采集与 UI 刷新解耦，每秒调用一次几乎无 CPU 开销；
psutil 缺失或原生调用失败时自动降级：(None, None)，上层优雅显示 "--"。

性能说明：psutil.net_io_counters() 在 Windows 上实测约 8ms/次（要枚举全部网卡并逐条建对象），
每秒在 GUI 线程跑一次会挤压动画帧；改用 IP Helper API 的 GetIfTable2 实测约 0.8ms/次。
"""

import sys
import time

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except Exception:
    _psutil = None
    _HAS_PSUTIL = False


def _read_psutil():
    c = _psutil.net_io_counters()
    return c.bytes_sent, c.bytes_recv


def _build_win_reader():
    """基于 GetIfTable2 的采样函数：只统计物理网卡，避免过滤驱动重复上报计数。"""
    import ctypes
    from ctypes import wintypes

    class _MibIfRow2(ctypes.Structure):
        _fields_ = [
            ("InterfaceLuid", ctypes.c_ulonglong),
            ("InterfaceIndex", wintypes.DWORD),
            ("InterfaceGuid", ctypes.c_ubyte * 16),
            ("Alias", wintypes.WCHAR * 257),
            ("Description", wintypes.WCHAR * 257),
            ("PhysicalAddressLength", wintypes.DWORD),
            ("PhysicalAddress", ctypes.c_ubyte * 32),
            ("PermanentPhysicalAddress", ctypes.c_ubyte * 32),
            ("Mtu", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TunnelType", wintypes.DWORD),
            ("MediaType", wintypes.DWORD),
            ("PhysicalMediumType", wintypes.DWORD),
            ("AccessType", wintypes.DWORD),
            ("DirectionType", wintypes.DWORD),
            ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
            ("OperStatus", wintypes.DWORD),
            ("AdminStatus", wintypes.DWORD),
            ("MediaConnectState", wintypes.DWORD),
            ("NetworkGuid", ctypes.c_ubyte * 16),
            ("ConnectionType", wintypes.DWORD),
            ("TransmitLinkSpeed", ctypes.c_ulonglong),
            ("ReceiveLinkSpeed", ctypes.c_ulonglong),
            ("InOctets", ctypes.c_ulonglong),
            ("InUcastPkts", ctypes.c_ulonglong),
            ("InNUcastPkts", ctypes.c_ulonglong),
            ("InDiscards", ctypes.c_ulonglong),
            ("InErrors", ctypes.c_ulonglong),
            ("InUnknownProtos", ctypes.c_ulonglong),
            ("InUcastOctets", ctypes.c_ulonglong),
            ("InMulticastOctets", ctypes.c_ulonglong),
            ("InBroadcastOctets", ctypes.c_ulonglong),
            ("OutOctets", ctypes.c_ulonglong),
            ("OutUcastPkts", ctypes.c_ulonglong),
            ("OutNUcastPkts", ctypes.c_ulonglong),
            ("OutDiscards", ctypes.c_ulonglong),
            ("OutErrors", ctypes.c_ulonglong),
            ("OutUcastOctets", ctypes.c_ulonglong),
            ("OutMulticastOctets", ctypes.c_ulonglong),
            ("OutBroadcastOctets", ctypes.c_ulonglong),
            ("OutQLen", ctypes.c_ulonglong),
        ]

    class _MibIfTable2(ctypes.Structure):
        _fields_ = [("NumEntries", ctypes.c_ulong), ("Table", _MibIfRow2 * 1)]

    iphlpapi = ctypes.WinDLL("iphlpapi")
    row_ptr = ctypes.POINTER(_MibIfRow2)

    def read():
        table = ctypes.POINTER(_MibIfTable2)()
        if iphlpapi.GetIfTable2(ctypes.byref(table)) != 0:
            return None
        try:
            rows = ctypes.cast(ctypes.byref(table.contents.Table[0]), row_ptr)
            sent = recv = 0
            for i in range(table.contents.NumEntries):
                row = rows[i]
                if not (row.InterfaceAndOperStatusFlags & 1):   # HardwareInterface=0 的是过滤驱动
                    continue
                sent += row.OutOctets
                recv += row.InOctets
            return sent, recv
        finally:
            iphlpapi.FreeMibTable(table)

    return read


if sys.platform == "win32":
    try:
        _READER = _build_win_reader()
    except Exception:
        _READER = _read_psutil if _HAS_PSUTIL else None
else:
    _READER = _read_psutil if _HAS_PSUTIL else None


def available():
    return _READER is not None


class TrafficMonitor:
    """实时网速采样器：每次 sample() 返回 (上行bytes/s, 下行bytes/s)"""

    def __init__(self, reader=None):
        self._reader = reader or _READER
        self.enabled = self._reader is not None
        self._prev_bytes = None   # (bytes_sent, bytes_recv)
        self._prev_time = None

    def sample(self):
        """返回 (upload_bps, download_bps)；首次调用或异常返回 (None, None)"""
        if not self.enabled:
            return None, None
        try:
            now = time.monotonic()   # 单调时钟：不受系统校时/夏令时影响
            cur = self._reader()     # 全部物理网卡累计
            if cur is None:
                return None, None
            if self._prev_bytes is None:
                self._prev_bytes = cur
                self._prev_time = now
                return None, None
            dt = now - self._prev_time
            # 网卡重置/驱动重载时计数器会回退，按 0 处理而不是产生负速度
            delta_up = max(0, cur[0] - self._prev_bytes[0])
            delta_dn = max(0, cur[1] - self._prev_bytes[1])
            up = delta_up / dt if dt > 0 else 0.0
            dn = delta_dn / dt if dt > 0 else 0.0
            self._prev_bytes = cur
            self._prev_time = now
            return up, dn
        except Exception:
            return None, None

    def reset(self):
        """重采样基线，避免长时间累计后溢出，或切换网卡"""
        self._prev_bytes = None
        self._prev_time = None
